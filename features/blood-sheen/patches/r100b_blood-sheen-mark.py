# r100b_blood-sheen-mark: FEATURE follow-up to r100_blood-sheen.fixed.py (branch visual/blood-sheen).
# Applies ON TOP of r100 (refuses a tree without it). Off by default; nothing of it runs while
# BB_BLOOD_SHEEN is off (BloodSheen is not made: the frame stays bit-identical).
#
# What the first slot run showed (batch b10, graveyard-blood, 1920x1080 1:1, 21:52): 600 of 600
# frames keyed the pair 1ea84d9a:bd1d09f0 (1266 indices, the surface probe saw only 1266-index draws
# of it: the accepted draw IS that mesh; the one "other shape" was its first draw, before the camera
# knew the scene depth), GLINT and EDIT ran every frame, but a recent frame counted 0 pool pixels
# (once 62), and the show picture had no cyan: the colour print found almost nothing the draw changed.
#
# Cause, read from the code (certain that the compare itself is sound; the rest is SUSPECTED until one
# run): the order is right (SNAPSHOT is recorded in EffectsBeforeResources before BindResources,
# BeginRendering and the draw; GLINT after the draw command, after EndRendering), the images are the
# draw's own (cb_descs[0] is not redirected: TemporalUpscaler::RedirectColor touches only UI and
# display buffers; the scene is not reduced at 1:1), barriers and layouts are those of the proven
# halation/heat haze passes, and a pixel the draw changes cannot keep its 32-bit print. The 62-pixel
# frame proves the path can see the draw's changes. So the draw itself changes almost no scene pixel:
# it either loses the depth test against the ground it lies on (a decal mesh flush with or a hair
# under the ground: zero most frames, a few edge pixels some frames, as seen), or draws alpha 0
# (SrcAlpha blending then leaves the colour bit for bit), or lies off screen. Then the dark pool on
# screen is not this draw's colour: it is the ground's own albedo (the G-buffer), and the game's wet
# layer is what is missing. The lead's step one (BB_LAMP_SHADOW_VIEW=2: the pool "stays dark") does
# not tell the two apart: that view repaints only lamp-shadowed pixels and the game still multiplies
# by the albedo, so dark blood albedo stays dark either way.
#
# What this patch changes (all inside r100's own files, plus r100's rows in the pipeline test and
# r100's README section):
#   1. The mark (the best fix behind the same knob): SNAPSHOT also copies the scene depth's bits into
#      a second R32UI image; GLINT takes a pixel where the draw changed the colour with an alpha above
#      0 (r100's test) OR wrote its depth (coverage 1 there: its footprint where it left the colour),
#      so a draw that writes depth but leaves the colour (alpha 0) still gets its glint and wet ground.
#   2. Counters for one run that settles the cause: a third periodic line "recent frame's draw": index
#      count, depth test on/off, colour changed (with alpha, mean alpha), depth changed (without colour;
#      nearer / behind by up to 2 cm + 1% / behind by more than the depth before), and the box of the
#      changed pixels; a once-line with the pool draw's depth function, depth bias (front/back, offsets,
#      scales, clamp), depth bounds, stencil and target 0 write mask.
#   3. The test view paints each test in its own colour (cyan drew with alpha, magenta depth only,
#      yellow colour with alpha 0, orange behind by a hair, red behind by more), at least 0.1 bright.
#   4. BB_BLOOD_SHEEN_DEPTH=off (a TEST): the keyed draw runs with the depth compare op Always (a
#      raw vkCmdSetDepthCompareOp after SNAPSHOT, with the scheduler's dynamic-state cache set to the
#      game's op and not dirty, so the draw's own commit records nothing; GLINT, or the next BeforeDraw
#      when the draw was left out, or the frame end records the cached op again). Its footprint and how
#      far behind the ground it lies then show in the picture and the counts.
# Which numbers decide (graveyard-blood, tilted down; jobs S/slot_jobs_r100b.json):
#   - show + BB_BLOOD_SHEEN_DEPTH=off: "colour changed C (A with alpha)" and the box over the pool
#     region, and "behind under 2 cm + 1%" H large  ->  the pool loses the depth test by a hair (next:
#     a depth slack for the keyed draw); "behind more" B only where the hunter stands. A with alpha 0
#     but D large -> it draws alpha 0 (its own alpha, e.g. vertex or instance alpha, is 0 here).
#     All 0 -> the draw is not on screen; the pool is elsewhere (G-buffer albedo: route G).
#   - on (normal depth test): "pool pixels" and "depth changed" well above r100's 0-62 and a visible
#     glint against the off twin -> fixed by the depth rule; still 0 -> settled by the show job above.
#   - dream-house show: "0 with the pool", "2341 under 64 indices"-like counts, no paint: unchanged.
#
# Files: whole-file replacements of r100's six new files (each must be exactly r100's text, else
# REFUSED), and two replacements of r100's own text in engine/tests/test_effect_pipelines.cpp (the
# snapshot and glint rows) and README.md (r100's section). Nothing else; vk_rasterizer*.cpp/.h,
# CMakeLists.txt and build.sh are not touched (the three shader builds and the test target stay).
#
# Off: unchanged from r100 (no BloodSheen made: two null tests a draw, one a frame). On, extra cost:
# SNAPSHOT also reads the depth and writes 4 bytes a pixel, GLINT reads 4 more bytes a pixel and
# keeps 16 counter words (estimate +0.02 ms at 1080p internal per pool draw); memory +8.3 MB at 1080p
# internal (a second R32UI image).
#
# Use: python -I -X utf8 r100b_blood-sheen-mark.py check | apply | revert. Root from R100_ROOT (or
# R100B_ROOT), else <tree>. Revert r100b before reverting r100 (r100's script refuses a tree
# whose blood sheen files are r100b's). Edited files keep their line ends; apply keeps the originals in
# r100b_backup/ next to this script; a mixed state is refused and nothing is written.
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r100b_backup")
ROOT = os.environ.get("R100_ROOT") or os.environ.get("R100B_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
RV = V + "renderer_vulkan/"
HS = V + "host_shaders/"
PIPES = "engine/tests/test_effect_pipelines.cpp"
README = "README.md"
CMAKE = "engine/gpu/CMakeLists.txt"
TMP = ".r100btmp"

# The r100 text of each file this patch replaces, and the r100b text.
FILES = {
'engine/gpu/shadps4/video_core/host_shaders/blood_sheen.comp': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): a wet glint on the game's forward-drawn blood pool, from every light the
// game's own lighting puts into its specular light target (the lamps of its light grid, each scaled
// by the engine's ray traced lamp shadow when that is on, and the sun or moon, shadowed by its screen
// shadow, ray traced when that is on). renderer_vulkan/blood_sheen.h has the rules, vk_blood_sheen.cpp
// records the passes. Three builds, one per pass (each binds only what it uses):
//   BLOOD_SNAPSHOT  right before the pool's draw: a 32-bit print of each scene pixel into `tag_img`
//   BLOOD_GLINT     right after it: a pixel whose print changed is the pool's (it is drawn there, so
//                   not where a nearer surface, the hunter standing in it, hides it); its coverage
//                   (the scene alpha the draw wrote, or 1) times the specular light target under it is
//                   added; `tag_img` then holds (coverage, view depth) of the pool's pixels, 0 elsewhere
//   BLOOD_EDIT      next frame, before the game's sun and lamps light the G-buffer: each pixel is
//                   carried to last frame's screen with both cameras; where the tag found there holds
//                   the pool at the same depth, the ground's gloss and specular colour are raised to a
//                   wet film's, so the game's sun, moon and lamps put a sharp highlight into the
//                   specular light target that GLINT then lays over the pool
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "blood_sheen_layout.h"

#if !((defined(BLOOD_SNAPSHOT) && !defined(BLOOD_GLINT) && !defined(BLOOD_EDIT)) || \
      (!defined(BLOOD_SNAPSHOT) && defined(BLOOD_GLINT) && !defined(BLOOD_EDIT)) || \
      (!defined(BLOOD_SNAPSHOT) && !defined(BLOOD_GLINT) && defined(BLOOD_EDIT)))
#error "blood_sheen.comp: define exactly one of BLOOD_SNAPSHOT, BLOOD_GLINT, BLOOD_EDIT"
#endif

layout(local_size_x = BLOOD_SHEEN_GROUP, local_size_y = BLOOD_SHEEN_GROUP, local_size_z = 1) in;

// BloodSheenRules::Push, word for word (28 words).
layout(push_constant) uniform Push {
    vec4 reproject[3]; // EDIT: the tag's camera (world to view) times this frame's view to world, rows
    vec4 proj;         // this frame's: x scale, y scale (signed: ndc +y down), z scale, z offset
    vec4 prev_proj;    // EDIT: the tag's
    vec2 size;         // pixels
    vec2 jitter;       // this frame's viewport shift in render pixels
    vec2 prev_jitter;  // EDIT: the tag's
    float strength;    // GLINT: the share of the specular light added over the pool
    uint flags;        // BLOOD_SHEEN_FLAG_*
};

#if defined(BLOOD_SNAPSHOT)
layout(binding = 0, rgba16f) uniform readonly image2D scene_img;
layout(binding = 1, r32ui) uniform writeonly uimage2D tag_img;
#elif defined(BLOOD_GLINT)
layout(binding = 0, rgba16f) uniform image2D scene_img;
layout(binding = 1, r32ui) uniform uimage2D tag_img; // the print in, (coverage, depth) out
layout(binding = 2) uniform texture2D depth_tex;     // the scene depth, the pool's in it
layout(binding = 3) uniform texture2D light_tex;     // the game's specular light target
layout(binding = 4, std430) buffer Counters {
    uint counts[];
};
#else
layout(binding = 0) uniform texture2D depth_tex; // the G-buffer pass's depth (the ground)
layout(binding = 1, r32ui) uniform readonly uimage2D tag_img;
layout(binding = 2, rgba8) uniform image2D material_img; // G-buffer target 1: .r gloss
layout(binding = 3, rgba8) uniform image2D specular_img; // G-buffer target 3: rgb root of f0
layout(binding = 4, std430) buffer Counters {
    uint counts[];
};
#endif

// Packs a scene pixel into 32 bits; a pixel the draw changed (colour or alpha) packs differently
// unless two different halves collide (about one in 2^32).
uint Print(vec4 c) {
    const uint a = packHalf2x16(c.rg), b = packHalf2x16(c.ba);
    return a ^ (b * 0x9E3779B1u) ^ (b >> 15u);
}

// View depth (metres, in front: positive) from a depth value, as camera_motion.comp: depth =
// zs + zo / z; 0 for the sky or no depth.
float ViewZ(float depth, vec4 p) {
    if (!(depth > 0.0) || depth >= 1.0) {
        return 0.0;
    }
    return p.w / min(depth - p.z, -1e-8);
}

#if !defined(BLOOD_SNAPSHOT)
shared uint group_counts[BLOOD_SHEEN_SLOT_WORDS];
void AddCounts(uvec4 n) {
    if (gl_LocalInvocationIndex < BLOOD_SHEEN_SLOT_WORDS) {
        group_counts[gl_LocalInvocationIndex] = 0u;
    }
    memoryBarrierShared();
    barrier();
    for (uint i = 0u; i < BLOOD_SHEEN_SLOT_WORDS; ++i) {
        if (n[i] != 0u) {
            atomicAdd(group_counts[i], n[i]);
        }
    }
    memoryBarrierShared();
    barrier();
    if (gl_LocalInvocationIndex < BLOOD_SHEEN_SLOT_WORDS && group_counts[gl_LocalInvocationIndex] != 0u) {
        const uint slot = (flags & BLOOD_SHEEN_FLAG_SLOT) != 0u ? 1u : 0u;
        atomicAdd(counts[slot * BLOOD_SHEEN_SLOT_WORDS + gl_LocalInvocationIndex],
                  group_counts[gl_LocalInvocationIndex]);
    }
}
#endif

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const bool inside = p.x < int(size.x) && p.y < int(size.y);
#if defined(BLOOD_SNAPSHOT)
    if (inside) {
        imageStore(tag_img, p, uvec4(Print(imageLoad(scene_img, p))));
    }
#elif defined(BLOOD_GLINT)
    uvec4 n = uvec4(0u);
    if (inside) {
        const vec4 c = imageLoad(scene_img, p);
        const bool marked = Print(c) != imageLoad(tag_img, p).x;
        float coverage = 0.0, z = 0.0;
        if (marked) {
            coverage = (flags & BLOOD_SHEEN_FLAG_ALPHA_COVERAGE) != 0u ? clamp(c.a, 0.0, 1.0) : 1.0;
        }
        if (coverage > 0.0) {
            z = ViewZ(texelFetch(depth_tex, p, 0).x, proj);
            vec3 light = vec3(0.0);
            if ((flags & BLOOD_SHEEN_FLAG_LIGHT) != 0u) {
                light = texelFetch(light_tex, p, 0).rgb;
                if (any(isnan(light)) || any(isinf(light))) {
                    light = vec3(0.0);
                }
                light = max(light, vec3(0.0));
            }
            // No light under the pool: nothing is added (darkness stays dark).
            const vec3 glint = min(light * (coverage * strength), vec3(BLOOD_SHEEN_GLINT_MAX));
            vec3 rgb = c.rgb + glint;
            if ((flags & BLOOD_SHEEN_FLAG_SHOW) != 0u) {
                // Test view: the marked pixels half cyan, as bright as the pixel (at least a little).
                const float luma = max(dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)), 0.03);
                rgb = mix(rgb, vec3(0.0, 1.0, 1.0) * (2.0 * luma), 0.5 * coverage);
            }
            imageStore(scene_img, p, vec4(rgb, c.a));
            n.x = 1u;
            n.y = dot(light, vec3(1.0)) > 0.0 ? 1u : 0u;
        }
        imageStore(tag_img, p, uvec4(z > 0.0 ? packHalf2x16(vec2(coverage, z)) : 0u));
    }
    AddCounts(n);
#else
    uvec4 n = uvec4(0u);
    if (inside) {
        const float z = ViewZ(texelFetch(depth_tex, p, 0).x, proj);
        if (z > 0.0) {
            const vec2 uv = (vec2(p) + 0.5) / size - jitter / size;
            const vec2 ndc = uv * 2.0 - 1.0;
            const vec4 view = vec4(ndc.x * z / proj.x, ndc.y * z / proj.y, z, 1.0);
            const vec3 prev =
                vec3(dot(reproject[0], view), dot(reproject[1], view), dot(reproject[2], view));
            if (prev.z > 1e-4) {
                const vec2 prev_uv = vec2(prev.x * prev_proj.x, prev.y * prev_proj.y) / prev.z * 0.5 + 0.5;
                const ivec2 q = ivec2(floor(prev_uv * size + prev_jitter));
                if (all(greaterThanEqual(q, ivec2(0))) && all(lessThan(q, ivec2(size)))) {
                    const uint word = imageLoad(tag_img, q).x;
                    const vec2 tag = word != 0u ? unpackHalf2x16(word) : vec2(0.0);
                    if (tag.x > 0.0 && tag.y > 0.0) {
                        n.w = 1u;
                        const float tol = BLOOD_SHEEN_DEPTH_TOL_M + BLOOD_SHEEN_DEPTH_TOL_REL * tag.y;
                        if (abs(prev.z - tag.y) <= tol) {
                            const float w = clamp(tag.x, 0.0, 1.0);
                            vec4 m = imageLoad(material_img, p);
                            m.r = max(m.r, mix(m.r, BLOOD_SHEEN_WET_GLOSS, w));
                            imageStore(material_img, p, m);
                            vec4 s = imageLoad(specular_img, p);
                            s.rgb = max(s.rgb, mix(s.rgb, vec3(BLOOD_SHEEN_WET_SPEC_ROOT), w));
                            imageStore(specular_img, p, s);
                            n.z = 1u;
                        }
                    }
                }
            }
        }
    }
    AddCounts(n);
#endif
}
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): a wet glint on the game's forward-drawn blood pool, from every light the
// game's own lighting puts into its specular light target (the lamps of its light grid, each scaled
// by the engine's ray traced lamp shadow when that is on, and the sun or moon, shadowed by its screen
// shadow, ray traced when that is on). renderer_vulkan/blood_sheen.h has the rules, vk_blood_sheen.cpp
// records the passes. Three builds, one per pass (each binds only what it uses):
//   BLOOD_SNAPSHOT  right before the pool's draw: a 32-bit print of each scene pixel into `tag_img`
//                   and the scene depth's bits into `before_img`
//   BLOOD_GLINT     right after it: a pixel is the pool's where the draw changed its colour with an
//                   alpha above 0, or wrote its depth (bbport r100b_blood-sheen-mark: r100 took the
//                   colour alone and found almost none of the pool's pixels); either way the draw is
//                   drawn there, so not where a nearer surface, the hunter standing in it, hides it.
//                   Its coverage (the scene alpha the draw wrote, or 1; 1 where it wrote its depth
//                   without an alpha above 0) times the specular light target under it is added; `tag_img` then holds
//                   (coverage, view depth) of the pool's pixels, 0 elsewhere. Each test is counted on
//                   its own (BLOOD_SHEEN_WORD_*), and the test view paints each in its own colour
//   BLOOD_EDIT      next frame, before the game's sun and lamps light the G-buffer: each pixel is
//                   carried to last frame's screen with both cameras; where the tag found there holds
//                   the pool at the same depth, the ground's gloss and specular colour are raised to a
//                   wet film's, so the game's sun, moon and lamps put a sharp highlight into the
//                   specular light target that GLINT then lays over the pool
#version 450
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#include "blood_sheen_layout.h"

#if !((defined(BLOOD_SNAPSHOT) && !defined(BLOOD_GLINT) && !defined(BLOOD_EDIT)) || \
      (!defined(BLOOD_SNAPSHOT) && defined(BLOOD_GLINT) && !defined(BLOOD_EDIT)) || \
      (!defined(BLOOD_SNAPSHOT) && !defined(BLOOD_GLINT) && defined(BLOOD_EDIT)))
#error "blood_sheen.comp: define exactly one of BLOOD_SNAPSHOT, BLOOD_GLINT, BLOOD_EDIT"
#endif

layout(local_size_x = BLOOD_SHEEN_GROUP, local_size_y = BLOOD_SHEEN_GROUP, local_size_z = 1) in;

// BloodSheenRules::Push, word for word (28 words).
layout(push_constant) uniform Push {
    vec4 reproject[3]; // EDIT: the tag's camera (world to view) times this frame's view to world, rows
    vec4 proj;         // this frame's: x scale, y scale (signed: ndc +y down), z scale, z offset
    vec4 prev_proj;    // EDIT: the tag's
    vec2 size;         // pixels
    vec2 jitter;       // this frame's viewport shift in render pixels
    vec2 prev_jitter;  // EDIT: the tag's
    float strength;    // GLINT: the share of the specular light added over the pool
    uint flags;        // BLOOD_SHEEN_FLAG_*
};

#if defined(BLOOD_SNAPSHOT)
layout(binding = 0, rgba16f) uniform readonly image2D scene_img;
layout(binding = 1, r32ui) uniform writeonly uimage2D tag_img;
layout(binding = 2) uniform texture2D depth_tex;                 // the scene depth before the draw
layout(binding = 3, r32ui) uniform writeonly uimage2D before_img; // its bits
#elif defined(BLOOD_GLINT)
layout(binding = 0, rgba16f) uniform image2D scene_img;
layout(binding = 1, r32ui) uniform uimage2D tag_img; // the print in, (coverage, depth) out
layout(binding = 2) uniform texture2D depth_tex;     // the scene depth, the pool's in it
layout(binding = 3) uniform texture2D light_tex;     // the game's specular light target
layout(binding = 4, std430) buffer Counters {
    uint counts[];
};
layout(binding = 5, r32ui) uniform readonly uimage2D before_img; // the depth's bits before the draw
#else
layout(binding = 0) uniform texture2D depth_tex; // the G-buffer pass's depth (the ground)
layout(binding = 1, r32ui) uniform readonly uimage2D tag_img;
layout(binding = 2, rgba8) uniform image2D material_img; // G-buffer target 1: .r gloss
layout(binding = 3, rgba8) uniform image2D specular_img; // G-buffer target 3: rgb root of f0
layout(binding = 4, std430) buffer Counters {
    uint counts[];
};
#endif

// Packs a scene pixel into 32 bits; a pixel the draw changed (colour or alpha) packs differently
// unless two different halves collide (about one in 2^32).
uint Print(vec4 c) {
    const uint a = packHalf2x16(c.rg), b = packHalf2x16(c.ba);
    return a ^ (b * 0x9E3779B1u) ^ (b >> 15u);
}

// View depth (metres, in front: positive) from a depth value, as camera_motion.comp: depth =
// zs + zo / z; 0 for the sky or no depth.
float ViewZ(float depth, vec4 p) {
    if (!(depth > 0.0) || depth >= 1.0) {
        return 0.0;
    }
    return p.w / min(depth - p.z, -1e-8);
}

#if !defined(BLOOD_SNAPSHOT)
// The group's counts, then one atomic per word for the group: sums add, the box words are maxima.
shared uint group_counts[BLOOD_SHEEN_SLOT_WORDS];
void AddCounts(uint n[BLOOD_SHEEN_SLOT_WORDS]) {
    if (gl_LocalInvocationIndex < BLOOD_SHEEN_SLOT_WORDS) {
        group_counts[gl_LocalInvocationIndex] = 0u;
    }
    memoryBarrierShared();
    barrier();
    for (uint i = 0u; i < BLOOD_SHEEN_SLOT_WORDS; ++i) {
        if (n[i] != 0u) {
            if (i < BLOOD_SHEEN_WORD_BOX_MIN_X) {
                atomicAdd(group_counts[i], n[i]);
            } else {
                atomicMax(group_counts[i], n[i]);
            }
        }
    }
    memoryBarrierShared();
    barrier();
    const uint w = gl_LocalInvocationIndex;
    if (w < BLOOD_SHEEN_SLOT_WORDS && group_counts[w] != 0u) {
        const uint slot = (flags & BLOOD_SHEEN_FLAG_SLOT) != 0u ? 1u : 0u;
        const uint at = slot * BLOOD_SHEEN_SLOT_WORDS + w;
        if (w < BLOOD_SHEEN_WORD_BOX_MIN_X) {
            atomicAdd(counts[at], group_counts[w]);
        } else {
            atomicMax(counts[at], group_counts[w]);
        }
    }
}
#endif

void main() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    const bool inside = p.x < int(size.x) && p.y < int(size.y);
#if defined(BLOOD_SNAPSHOT)
    if (inside) {
        imageStore(tag_img, p, uvec4(Print(imageLoad(scene_img, p))));
        imageStore(before_img, p, uvec4(floatBitsToUint(texelFetch(depth_tex, p, 0).x)));
    }
#elif defined(BLOOD_GLINT)
    uint n[BLOOD_SHEEN_SLOT_WORDS];
    for (uint i = 0u; i < BLOOD_SHEEN_SLOT_WORDS; ++i) {
        n[i] = 0u;
    }
    if (inside) {
        const vec4 c = imageLoad(scene_img, p);
        const float depth_after = texelFetch(depth_tex, p, 0).x;
        const uint depth_before = imageLoad(before_img, p).x;
        // What the draw changed, each test on its own.
        const bool colour = Print(c) != imageLoad(tag_img, p).x;
        const float alpha =
            (flags & BLOOD_SHEEN_FLAG_ALPHA_COVERAGE) != 0u ? clamp(c.a, 0.0, 1.0) : 1.0;
        const bool with_alpha = colour && alpha > 0.0;
        const bool depth = floatBitsToUint(depth_after) != depth_before;
        // Where the draw's depth lies against the depth before it: 1 nearer (or nothing there
        // before), 2 behind by a hair, 3 behind by more (only with the depth test off or not
        // LessEqual can a draw land behind what was there).
        uint place = 0u;
        if (depth) {
            const float za = ViewZ(depth_after, proj);
            const float zb = ViewZ(uintBitsToFloat(depth_before), proj);
            if (za > 0.0 && (zb <= 0.0 || za <= zb)) {
                place = 1u;
            } else if (za > 0.0 && za - zb <= BLOOD_SHEEN_HAIR_M + BLOOD_SHEEN_HAIR_REL * zb) {
                place = 2u;
            } else {
                place = 3u;
            }
        }
        // The mark: the draw changed the colour with alpha (coverage: that alpha), or wrote its
        // depth without an alpha above 0 (its footprint; coverage 1).
        const float coverage = with_alpha ? alpha : (depth ? 1.0 : 0.0);
        vec3 rgb = c.rgb;
        float z = 0.0;
        if (coverage > 0.0) {
            z = ViewZ(depth_after, proj);
            vec3 light = vec3(0.0);
            if ((flags & BLOOD_SHEEN_FLAG_LIGHT) != 0u) {
                light = texelFetch(light_tex, p, 0).rgb;
                if (any(isnan(light)) || any(isinf(light))) {
                    light = vec3(0.0);
                }
                light = max(light, vec3(0.0));
            }
            // No light under the pool: nothing is added (darkness stays dark).
            rgb += min(light * (coverage * strength), vec3(BLOOD_SHEEN_GLINT_MAX));
            n[BLOOD_SHEEN_WORD_POOL] = 1u;
            n[BLOOD_SHEEN_WORD_LIT] = dot(light, vec3(1.0)) > 0.0 ? 1u : 0u;
        }
        bool painted = false;
        if ((flags & BLOOD_SHEEN_FLAG_SHOW) != 0u) {
            // Test view, each test in its own colour (half of the pixel, as bright as the pixel, at
            // least BLOOD_SHEEN_SHOW_FLOOR): red the draw landed behind by more, orange behind by a
            // hair, magenta it wrote depth without alpha, cyan it drew with alpha (in front),
            // yellow it changed the colour with alpha 0 and left the depth.
            vec3 tint = vec3(0.0);
            if (place == 3u) {
                tint = vec3(1.0, 0.0, 0.0);
            } else if (place == 2u) {
                tint = vec3(1.0, 0.5, 0.0);
            } else if (depth && !with_alpha) {
                tint = vec3(1.0, 0.0, 1.0);
            } else if (with_alpha) {
                tint = vec3(0.0, 1.0, 1.0);
            } else if (colour) {
                tint = vec3(1.0, 1.0, 0.0);
            }
            if (dot(tint, vec3(1.0)) > 0.0) {
                const float luma = max(dot(c.rgb, vec3(0.2126, 0.7152, 0.0722)), BLOOD_SHEEN_SHOW_FLOOR);
                rgb = mix(rgb, tint * (2.0 * luma), 0.5);
                painted = true;
            }
        }
        if (coverage > 0.0 || painted) {
            imageStore(scene_img, p, vec4(rgb, c.a));
        }
        imageStore(tag_img, p, uvec4(z > 0.0 ? packHalf2x16(vec2(coverage, z)) : 0u));
        n[BLOOD_SHEEN_WORD_COLOUR] = colour ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_COLOUR_ALPHA] = with_alpha ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_DEPTH] = depth ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_DEPTH_ONLY] = depth && !with_alpha ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_NEARER] = place == 1u ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_HAIR] = place == 2u ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_BEHIND] = place == 3u ? 1u : 0u;
        n[BLOOD_SHEEN_WORD_ALPHA_SUM] = with_alpha ? uint(alpha * 255.0 + 0.5) : 0u;
        if (colour || depth) {
            n[BLOOD_SHEEN_WORD_BOX_MIN_X] = 65535u - uint(p.x);
            n[BLOOD_SHEEN_WORD_BOX_MIN_Y] = 65535u - uint(p.y);
            n[BLOOD_SHEEN_WORD_BOX_MAX_X] = uint(p.x) + 1u;
            n[BLOOD_SHEEN_WORD_BOX_MAX_Y] = uint(p.y) + 1u;
        }
    }
    AddCounts(n);
#else
    uint n[BLOOD_SHEEN_SLOT_WORDS];
    for (uint i = 0u; i < BLOOD_SHEEN_SLOT_WORDS; ++i) {
        n[i] = 0u;
    }
    if (inside) {
        const float z = ViewZ(texelFetch(depth_tex, p, 0).x, proj);
        if (z > 0.0) {
            const vec2 uv = (vec2(p) + 0.5) / size - jitter / size;
            const vec2 ndc = uv * 2.0 - 1.0;
            const vec4 view = vec4(ndc.x * z / proj.x, ndc.y * z / proj.y, z, 1.0);
            const vec3 prev =
                vec3(dot(reproject[0], view), dot(reproject[1], view), dot(reproject[2], view));
            if (prev.z > 1e-4) {
                const vec2 prev_uv = vec2(prev.x * prev_proj.x, prev.y * prev_proj.y) / prev.z * 0.5 + 0.5;
                const ivec2 q = ivec2(floor(prev_uv * size + prev_jitter));
                if (all(greaterThanEqual(q, ivec2(0))) && all(lessThan(q, ivec2(size)))) {
                    const uint word = imageLoad(tag_img, q).x;
                    const vec2 tag = word != 0u ? unpackHalf2x16(word) : vec2(0.0);
                    if (tag.x > 0.0 && tag.y > 0.0) {
                        n[BLOOD_SHEEN_WORD_TAGS] = 1u;
                        const float tol = BLOOD_SHEEN_DEPTH_TOL_M + BLOOD_SHEEN_DEPTH_TOL_REL * tag.y;
                        if (abs(prev.z - tag.y) <= tol) {
                            const float w = clamp(tag.x, 0.0, 1.0);
                            vec4 m = imageLoad(material_img, p);
                            m.r = max(m.r, mix(m.r, BLOOD_SHEEN_WET_GLOSS, w));
                            imageStore(material_img, p, m);
                            vec4 s = imageLoad(specular_img, p);
                            s.rgb = max(s.rgb, mix(s.rgb, vec3(BLOOD_SHEEN_WET_SPEC_ROOT), w));
                            imageStore(specular_img, p, s);
                            n[BLOOD_SHEEN_WORD_WET] = 1u;
                        }
                    }
                }
            }
        }
    }
    AddCounts(n);
#endif
}
'''),
'engine/gpu/shadps4/video_core/host_shaders/blood_sheen_layout.h': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): what the blood sheen's shader (blood_sheen.comp) and the engine
// (renderer_vulkan/blood_sheen.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef BLOOD_SHEEN_LAYOUT_H
#define BLOOD_SHEEN_LAYOUT_H

// Pixels a side of one workgroup (BloodSheenRules::Group).
#define BLOOD_SHEEN_GROUP 8u
// The push word `flags`: the test view (BB_BLOOD_SHEEN=show); the pool's alpha is its coverage (its
// alpha blend is One/Zero, so the scene's alpha after the draw is the draw's own alpha); the counter
// slot of this frame (0 or 1).
#define BLOOD_SHEEN_FLAG_SHOW 1u
#define BLOOD_SHEEN_FLAG_ALPHA_COVERAGE 2u
#define BLOOD_SHEEN_FLAG_SLOT 4u
// GLINT: the light target is bound and holds this frame's light (else depth stands in for it and
// the glint is 0).
#define BLOOD_SHEEN_FLAG_LIGHT 8u
// A counter slot's words: pool pixels marked (GLINT), of them with light in the light target
// (GLINT), ground pixels made wet (EDIT), pixels whose tag was found after the reprojection (EDIT).
#define BLOOD_SHEEN_SLOT_WORDS 4u
// EDIT: the gloss (G-buffer target 1, red; exponent 2^(13 g) in the game's lighting) and the root of
// the specular colour (G-buffer target 3, rgb; f0 = rgb^2) a fully covered pixel is raised to: a
// water film (f0 0.04), gloss capped below the mirror so the game's static cube map does not show
// a wrong sky. Never lowered (max with what the ground has).
#define BLOOD_SHEEN_WET_GLOSS 0.66
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.2
// EDIT: the tag's view depth (the pool's surface, last frame) and the reprojected ground depth may
// differ by this much: metres plus a share of the distance (the pool lies on the ground).
#define BLOOD_SHEEN_DEPTH_TOL_M 0.05
#define BLOOD_SHEEN_DEPTH_TOL_REL 0.03
// GLINT: at most this much light is added to a channel (RGBA16F stays finite).
#define BLOOD_SHEEN_GLINT_MAX 64.0

#endif
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): what the blood sheen's shader (blood_sheen.comp) and the engine
// (renderer_vulkan/blood_sheen.h, which ties these to its constants with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef BLOOD_SHEEN_LAYOUT_H
#define BLOOD_SHEEN_LAYOUT_H

// Pixels a side of one workgroup (BloodSheenRules::Group).
#define BLOOD_SHEEN_GROUP 8u
// The push word `flags`: the test view (BB_BLOOD_SHEEN=show); the pool's alpha is its coverage (its
// alpha blend is One/Zero, so the scene's alpha after the draw is the draw's own alpha); the counter
// slot of this frame (0 or 1).
#define BLOOD_SHEEN_FLAG_SHOW 1u
#define BLOOD_SHEEN_FLAG_ALPHA_COVERAGE 2u
#define BLOOD_SHEEN_FLAG_SLOT 4u
// GLINT: the light target is bound and holds this frame's light (else depth stands in for it and
// the glint is 0).
#define BLOOD_SHEEN_FLAG_LIGHT 8u
// A counter slot's words (BLOOD_SHEEN_WORD_*). The words before BLOOD_SHEEN_WORD_BOX_MIN_X are sums;
// the four box words are maxima (each pass adds or raises them with atomics; a cleared slot is 0).
#define BLOOD_SHEEN_SLOT_WORDS 16u
// GLINT: pool pixels (the glint goes there: coverage above 0), of them with light in the light
// target; EDIT: ground pixels made wet, pixels whose tag was found after the reprojection.
#define BLOOD_SHEEN_WORD_POOL 0u
#define BLOOD_SHEEN_WORD_LIT 1u
#define BLOOD_SHEEN_WORD_WET 2u
#define BLOOD_SHEEN_WORD_TAGS 3u
// bbport (r100b_blood-sheen-mark): GLINT, what the draw changed, each test on its own: pixels whose
// colour print changed; of them with alpha above 0 after the draw (r100's mark); pixels whose depth
// changed; of them without a colour change with alpha (the draw's footprint where it drew no alpha
// above 0); the depth-changed pixels by where the draw's depth lies against the depth before it:
// nearer (or nothing there before), behind by at most BLOOD_SHEEN_HAIR_M + BLOOD_SHEEN_HAIR_REL of
// the distance (a pool a hair under the ground), behind by more (a body in front of the pool); the
// sum of alpha times 255 over the colour-changed pixels with alpha; the box of every pixel the draw
// changed (colour or depth): 65535 - least x, 65535 - least y, largest x + 1, largest y + 1 (0: none).
#define BLOOD_SHEEN_WORD_COLOUR 4u
#define BLOOD_SHEEN_WORD_COLOUR_ALPHA 5u
#define BLOOD_SHEEN_WORD_DEPTH 6u
#define BLOOD_SHEEN_WORD_DEPTH_ONLY 7u
#define BLOOD_SHEEN_WORD_NEARER 8u
#define BLOOD_SHEEN_WORD_HAIR 9u
#define BLOOD_SHEEN_WORD_BEHIND 10u
#define BLOOD_SHEEN_WORD_ALPHA_SUM 11u
#define BLOOD_SHEEN_WORD_BOX_MIN_X 12u
#define BLOOD_SHEEN_WORD_BOX_MIN_Y 13u
#define BLOOD_SHEEN_WORD_BOX_MAX_X 14u
#define BLOOD_SHEEN_WORD_BOX_MAX_Y 15u
#define BLOOD_SHEEN_HAIR_M 0.02
#define BLOOD_SHEEN_HAIR_REL 0.01
// EDIT: the gloss (G-buffer target 1, red; exponent 2^(13 g) in the game's lighting) and the root of
// the specular colour (G-buffer target 3, rgb; f0 = rgb^2) a fully covered pixel is raised to: a
// water film (f0 0.04), gloss capped below the mirror so the game's static cube map does not show
// a wrong sky. Never lowered (max with what the ground has).
#define BLOOD_SHEEN_WET_GLOSS 0.66
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.2
// EDIT: the tag's view depth (the pool's surface, last frame) and the reprojected ground depth may
// differ by this much: metres plus a share of the distance (the pool lies on the ground).
#define BLOOD_SHEEN_DEPTH_TOL_M 0.05
#define BLOOD_SHEEN_DEPTH_TOL_REL 0.03
// GLINT: at most this much light is added to a channel (RGBA16F stays finite).
#define BLOOD_SHEEN_GLINT_MAX 64.0
// GLINT, test view: the least brightness the marks are painted with (the pool is near black).
#define BLOOD_SHEEN_SHOW_FLOOR 0.1

#endif
'''),
'engine/gpu/shadps4/video_core/renderer_vulkan/blood_sheen.h': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r100_blood-sheen): a wet glint on the game's blood pool from the lamps and the sun or moon.
// The pool at the graveyard is a FORWARD draw (vs 1ea84d9a, ps bd1d09f0: drawn after the lighting,
// alpha blended, writing depth; the game's generic forward material, whose own lights are four
// directional ones and no lamp), so the game's lamps never shine on it. The engine reuses the game's
// own lighting instead of a light model of its own (vk_blood_sheen.cpp records the passes,
// host_shaders/blood_sheen.comp is the shader):
//   EDIT    (at the first light draw after each G-buffer pass: the shadow resolve, the sun or moon,
//           or a lamp of the light grid; not while a lamps-apart batch is open): where last frame's pool lay (its tag,
//           carried to this frame's pixels with both cameras, at the same depth within 5 cm + 3%),
//           the ground's gloss and specular colour in the G-buffer are raised toward a water film's
//           (gloss 0.66, f0 0.04; never lowered), so the game's sun or moon (with its screen shadow,
//           ray traced when that is on) and every lamp of its light grid (each scaled by the
//           engine's ray traced lamp shadow when that is on) put a sharp highlight into the
//           specular light target;
//   SNAPSHOT right before a keyed draw (the pool): a 32-bit print of each scene pixel;
//   GLINT   right after it: each pixel whose print changed is the pool's; its coverage (the draw's
//           alpha when its alpha blend is One/Zero, else 1) times the specular light target at that
//           pixel is added to the scene, times the strength. The pool's pixels and their view depth
//           are the tag for the next frame's EDIT.
// So: no light, no glint (the light target is 0 in the dark), and a surface nearer than the pool
// (the hunter standing in it) is not marked (the draw did not change it). Light that does not pass
// the light target is not in the glint: the pool's own directional lights (already in its shading),
// reflections (cube map, SSR), bounced light and fog.
//
// Knobs (environment, read once):
//   BB_BLOOD_SHEEN        unset, empty, 0, a negative number or other text: off (no BloodSheen is
//                         made: nothing of it runs); 1: on, strength 1; a number: the strength, put
//                         into 0.25..4; "show": strength 1 and the marked pixels painted half cyan
//   BB_BLOOD_SHEEN_PAIRS  the draws taken: "vs:ps" hex hashes (0x optional), at most MaxPairs,
//                         separated by ';', ',' or spaces; unset or empty: DefaultVs:DefaultPs. Text
//                         that holds no readable pair keeps the default (said in the log).
// The key of a draw (Classify): its pair is named; at least MinIndices indices (the pixel shader also
// draws 12-index quads in the Hunter's Dream house: those are left out and counted); one colour
// target, RGBA16F, which is not a G-buffer pass; blending on colour target 0; depth written; the
// depth target is the scene's (the G-buffer pass's).
// No Vulkan here: tests/test_blood_sheen.cpp builds it alone.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/blood_sheen_layout.h"

namespace Vulkan::BloodSheenRules {

inline constexpr float MinStrength = 0.25f, MaxStrength = 4.0f;
inline constexpr std::uint32_t MaxPairs = 8;
/// A keyed draw has at least this many indices (the graveyard pool: 1266; the Hunter's Dream house
/// quads of the same shaders: 12).
inline constexpr std::uint32_t MinIndices = 64;
/// At most this many keyed draws a frame get the passes (bd1d09f0 is the game's generic forward lit
/// material: a place with many keyed draws must not pay three passes for each); the rest are counted.
inline constexpr std::uint32_t MaxPoolDraws = 2;
inline constexpr std::uint64_t DefaultVs = 0x1ea84d9aull, DefaultPs = 0xbd1d09f0ull;
inline constexpr std::uint32_t Group = BLOOD_SHEEN_GROUP;
inline constexpr std::uint32_t SlotWords = BLOOD_SHEEN_SLOT_WORDS, Slots = 2;
inline constexpr std::uint32_t FlagShow = BLOOD_SHEEN_FLAG_SHOW;
inline constexpr std::uint32_t FlagAlphaCoverage = BLOOD_SHEEN_FLAG_ALPHA_COVERAGE;
inline constexpr std::uint32_t FlagSlot = BLOOD_SHEEN_FLAG_SLOT;
inline constexpr std::uint32_t FlagLight = BLOOD_SHEEN_FLAG_LIGHT;
static_assert(Group == 8u && SlotWords == 4u);
static_assert((FlagShow | FlagAlphaCoverage | FlagSlot | FlagLight) == 15u);
// The wet film's numbers, as the shader and the README name them.
static_assert(BLOOD_SHEEN_WET_GLOSS == 0.66 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.2);
static_assert(BLOOD_SHEEN_DEPTH_TOL_M == 0.05 && BLOOD_SHEEN_DEPTH_TOL_REL == 0.03);

struct Pair {
    std::uint64_t vs = 0, ps = 0;
};

struct Knobs {
    float strength = 0.0f; ///< 0: off
    bool show = false;
    std::array<Pair, MaxPairs> pairs{};
    std::uint32_t pair_count = 0;
    bool pairs_named = false; ///< BB_BLOOD_SHEEN_PAIRS gave the pairs
    std::uint32_t pairs_bad = 0; ///< tokens of BB_BLOOD_SHEEN_PAIRS that were not a readable pair
};

/// BB_BLOOD_SHEEN's text: the strength (0: off) and the test view.
inline Knobs ReadStrength(const char* text) {
    Knobs k;
    if (text == nullptr || text[0] == '\0') {
        return k;
    }
    const char* t = text;
    while (*t == ' ') {
        ++t;
    }
    if (t[0] == 's' && t[1] == 'h' && t[2] == 'o' && t[3] == 'w') {
        const char* rest = t + 4;
        while (*rest == ' ') {
            ++rest;
        }
        if (*rest == '\0') {
            k.strength = 1.0f;
            k.show = true;
        }
        return k;
    }
    char* end = nullptr;
    const float value = std::strtof(t, &end);
    if (end == t || !std::isfinite(value)) {
        return k;
    }
    while (*end == ' ') {
        ++end;
    }
    if (*end != '\0' || !(value > 0.0f)) {
        return k;
    }
    k.strength = std::clamp(value, MinStrength, MaxStrength);
    return k;
}

/// One hex number of 1 to 16 digits ("0x" optional) from `p` up to `end`; false if not one.
inline bool Hex(const char* p, const char* end, std::uint64_t& out) {
    if (end - p >= 2 && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
    }
    if (p == end || end - p > 16) {
        return false;
    }
    std::uint64_t v = 0;
    for (; p != end; ++p) {
        const int c = static_cast<unsigned char>(*p);
        int d = -1;
        if (c >= '0' && c <= '9') {
            d = c - '0';
        } else if (c >= 'a' && c <= 'f') {
            d = c - 'a' + 10;
        } else if (c >= 'A' && c <= 'F') {
            d = c - 'A' + 10;
        }
        if (d < 0) {
            return false;
        }
        v = (v << 4) | std::uint64_t(d);
    }
    out = v;
    return true;
}

/// BB_BLOOD_SHEEN_PAIRS into `k` (the default pair when it names none).
inline void ReadPairs(Knobs& k, const char* text) {
    k.pair_count = 0;
    k.pairs_named = false;
    k.pairs_bad = 0;
    const char* p = text ? text : "";
    while (*p != '\0') {
        while (*p == ';' || *p == ',' || *p == ' ') {
            ++p;
        }
        const char* start = p;
        while (*p != '\0' && *p != ';' && *p != ',' && *p != ' ') {
            ++p;
        }
        if (start == p) {
            continue;
        }
        const char* colon = start;
        while (colon != p && *colon != ':') {
            ++colon;
        }
        Pair pair;
        if (colon == p || !Hex(start, colon, pair.vs) || !Hex(colon + 1, p, pair.ps) ||
            k.pair_count == MaxPairs) {
            ++k.pairs_bad;
            continue;
        }
        k.pairs[k.pair_count++] = pair;
    }
    if (k.pair_count != 0) {
        k.pairs_named = true;
        return;
    }
    k.pairs[0] = {DefaultVs, DefaultPs};
    k.pair_count = 1;
}

inline Knobs Read(const char* sheen, const char* pairs) {
    Knobs k = ReadStrength(sheen);
    ReadPairs(k, pairs);
    return k;
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_PAIRS"));
    return knobs;
}

inline bool Matches(const Knobs& k, std::uint64_t vs, std::uint64_t ps) {
    for (std::uint32_t i = 0; i < k.pair_count; ++i) {
        if (k.pairs[i].vs == vs && k.pairs[i].ps == ps) {
            return true;
        }
    }
    return false;
}

/// What the key looks at of a draw.
struct DrawShape {
    std::uint64_t vs = 0, ps = 0;
    std::uint32_t indices = 0;
    std::uint32_t mrt_mask = 0;     ///< the colour targets the pipeline writes
    bool target_rgba16f = false;    ///< colour target 0 is RGBA16F
    bool blended = false;           ///< colour target 0 blends
    bool depth_write = false;       ///< depth test and write on
    bool scene_depth = false;       ///< the depth target is the G-buffer pass's
};

enum class Verdict : std::uint32_t {
    OtherPair = 0, ///< not a named pair (every other draw)
    Keyed,         ///< the pool
    FewIndices,    ///< a named pair with fewer than MinIndices indices (the Dream house quads)
    OtherShape,    ///< a named pair drawn otherwise (targets, blending, depth)
};

inline Verdict Classify(const Knobs& k, const DrawShape& d) {
    if (!Matches(k, d.vs, d.ps)) {
        return Verdict::OtherPair;
    }
    if (d.indices < MinIndices) {
        return Verdict::FewIndices;
    }
    if (d.mrt_mask != 1u || !d.target_rgba16f || !d.blended || !d.depth_write || !d.scene_depth) {
        return Verdict::OtherShape;
    }
    return Verdict::Keyed;
}

/// a * b for two 3x4 row-major affine matrices (a 4th row 0 0 0 1).
inline std::array<float, 12> Multiply(const std::array<float, 12>& a, const std::array<float, 12>& b) {
    std::array<float, 12> r{};
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 4; ++j) {
            float v = a[i * 4 + 0] * b[0 * 4 + j] + a[i * 4 + 1] * b[1 * 4 + j] +
                      a[i * 4 + 2] * b[2 * 4 + j];
            if (j == 3) {
                v += a[i * 4 + 3];
            }
            r[i * 4 + j] = v;
        }
    }
    return r;
}

/// blood_sheen.comp's push block, word for word (28 words).
struct Push {
    std::array<float, 12> reproject{};
    std::array<float, 4> proj{}, prev_proj{};
    std::array<float, 2> size{}, jitter{}, prev_jitter{};
    float strength = 0.0f;
    std::uint32_t flags = 0;
};
static_assert(sizeof(Push) == 112);

/// The flags of a pass of frame slot `slot`.
inline std::uint32_t Flags(const Knobs& k, bool alpha_coverage, bool light, std::uint32_t slot) {
    return (k.show ? FlagShow : 0u) | (alpha_coverage ? FlagAlphaCoverage : 0u) |
           (light ? FlagLight : 0u) | ((slot & 1u) != 0 ? FlagSlot : 0u);
}

} // namespace Vulkan::BloodSheenRules
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r100_blood-sheen): a wet glint on the game's blood pool from the lamps and the sun or moon.
// The pool at the graveyard is a FORWARD draw (vs 1ea84d9a, ps bd1d09f0: drawn after the lighting,
// alpha blended, writing depth; the game's generic forward material, whose own lights are four
// directional ones and no lamp), so the game's lamps never shine on it. The engine reuses the game's
// own lighting instead of a light model of its own (vk_blood_sheen.cpp records the passes,
// host_shaders/blood_sheen.comp is the shader):
//   EDIT    (at the first light draw after each G-buffer pass: the shadow resolve, the sun or moon,
//           or a lamp of the light grid; not while a lamps-apart batch is open): where last frame's pool lay (its tag,
//           carried to this frame's pixels with both cameras, at the same depth within 5 cm + 3%),
//           the ground's gloss and specular colour in the G-buffer are raised toward a water film's
//           (gloss 0.66, f0 0.04; never lowered), so the game's sun or moon (with its screen shadow,
//           ray traced when that is on) and every lamp of its light grid (each scaled by the
//           engine's ray traced lamp shadow when that is on) put a sharp highlight into the
//           specular light target;
//   SNAPSHOT right before a keyed draw (the pool): a 32-bit print of each scene pixel and
//           (bbport r100b_blood-sheen-mark) the bits of the scene depth;
//   GLINT   right after it: a pixel is the pool's where the draw changed its print with an alpha
//           above 0 after it, or wrote its depth (r100 took the print alone; the first slot run
//           found 0 to 62 such pixels a frame on a pool of tens of thousands); its coverage (the
//           draw's alpha when its alpha blend is One/Zero, else 1; 1 where it wrote its depth without an
//           alpha above 0)
//           times the specular light target at that pixel is added to the scene, times the
//           strength. The pool's pixels and their view depth are the tag for the next frame's EDIT.
//           Each test is also counted on its own, with the box of what the draw changed and where its
//           depth lies against the depth before it (the "recent frame's draw" log line).
// So: no light, no glint (the light target is 0 in the dark), and a surface nearer than the pool
// (the hunter standing in it) is not marked (the draw changed neither its colour nor its depth). Light that does not pass
// the light target is not in the glint: the pool's own directional lights (already in its shading),
// reflections (cube map, SSR), bounced light and fog.
//
// Knobs (environment, read once):
//   BB_BLOOD_SHEEN        unset, empty, 0, a negative number or other text: off (no BloodSheen is
//                         made: nothing of it runs); 1: on, strength 1; a number: the strength, put
//                         into 0.25..4; "show": strength 1 and a test view, each pixel the draw
//                         changed painted half in the colour of what it did there (blood_sheen.comp)
//   BB_BLOOD_SHEEN_PAIRS  the draws taken: "vs:ps" hex hashes (0x optional), at most MaxPairs,
//                         separated by ';', ',' or spaces; unset or empty: DefaultVs:DefaultPs. Text
//                         that holds no readable pair keeps the default (said in the log).
//   BB_BLOOD_SHEEN_DEPTH  bbport (r100b): "off": a TEST, the keyed draw runs without its depth test
//                         (it is drawn in front of everything, the hunter too) so the test view and
//                         the counts show its whole footprint and how far behind the scene's depth
//                         it lies; anything else: the draw as the game sets it.
// The key of a draw (Classify): its pair is named; at least MinIndices indices (the pixel shader also
// draws 12-index quads in the Hunter's Dream house: those are left out and counted); one colour
// target, RGBA16F, which is not a G-buffer pass; blending on colour target 0; depth written; the
// depth target is the scene's (the G-buffer pass's).
// No Vulkan here: tests/test_blood_sheen.cpp builds it alone.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/blood_sheen_layout.h"

namespace Vulkan::BloodSheenRules {

inline constexpr float MinStrength = 0.25f, MaxStrength = 4.0f;
inline constexpr std::uint32_t MaxPairs = 8;
/// A keyed draw has at least this many indices (the graveyard pool: 1266; the Hunter's Dream house
/// quads of the same shaders: 12).
inline constexpr std::uint32_t MinIndices = 64;
/// At most this many keyed draws a frame get the passes (bd1d09f0 is the game's generic forward lit
/// material: a place with many keyed draws must not pay three passes for each); the rest are counted.
inline constexpr std::uint32_t MaxPoolDraws = 2;
inline constexpr std::uint64_t DefaultVs = 0x1ea84d9aull, DefaultPs = 0xbd1d09f0ull;
inline constexpr std::uint32_t Group = BLOOD_SHEEN_GROUP;
inline constexpr std::uint32_t SlotWords = BLOOD_SHEEN_SLOT_WORDS, Slots = 2;
inline constexpr std::uint32_t FlagShow = BLOOD_SHEEN_FLAG_SHOW;
inline constexpr std::uint32_t FlagAlphaCoverage = BLOOD_SHEEN_FLAG_ALPHA_COVERAGE;
inline constexpr std::uint32_t FlagSlot = BLOOD_SHEEN_FLAG_SLOT;
inline constexpr std::uint32_t FlagLight = BLOOD_SHEEN_FLAG_LIGHT;
static_assert(Group == 8u && SlotWords == 16u);
static_assert((FlagShow | FlagAlphaCoverage | FlagSlot | FlagLight) == 15u);
// The wet film's numbers, as the shader and the README name them.
static_assert(BLOOD_SHEEN_WET_GLOSS == 0.66 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.2);
static_assert(BLOOD_SHEEN_DEPTH_TOL_M == 0.05 && BLOOD_SHEEN_DEPTH_TOL_REL == 0.03);
// bbport (r100b_blood-sheen-mark): the counter words (blood_sheen.comp writes them, the log reads
// them) and the "behind by a hair" bound, as the README names it.
inline constexpr std::uint32_t WordPool = BLOOD_SHEEN_WORD_POOL, WordLit = BLOOD_SHEEN_WORD_LIT;
inline constexpr std::uint32_t WordWet = BLOOD_SHEEN_WORD_WET, WordTags = BLOOD_SHEEN_WORD_TAGS;
inline constexpr std::uint32_t WordColour = BLOOD_SHEEN_WORD_COLOUR;
inline constexpr std::uint32_t WordColourAlpha = BLOOD_SHEEN_WORD_COLOUR_ALPHA;
inline constexpr std::uint32_t WordDepth = BLOOD_SHEEN_WORD_DEPTH;
inline constexpr std::uint32_t WordDepthOnly = BLOOD_SHEEN_WORD_DEPTH_ONLY;
inline constexpr std::uint32_t WordNearer = BLOOD_SHEEN_WORD_NEARER, WordHair = BLOOD_SHEEN_WORD_HAIR;
inline constexpr std::uint32_t WordBehind = BLOOD_SHEEN_WORD_BEHIND;
inline constexpr std::uint32_t WordAlphaSum = BLOOD_SHEEN_WORD_ALPHA_SUM;
inline constexpr std::uint32_t WordBoxMinX = BLOOD_SHEEN_WORD_BOX_MIN_X;
inline constexpr std::uint32_t WordBoxMinY = BLOOD_SHEEN_WORD_BOX_MIN_Y;
inline constexpr std::uint32_t WordBoxMaxX = BLOOD_SHEEN_WORD_BOX_MAX_X;
inline constexpr std::uint32_t WordBoxMaxY = BLOOD_SHEEN_WORD_BOX_MAX_Y;
static_assert(WordPool == 0 && WordLit == 1 && WordWet == 2 && WordTags == 3);
static_assert(WordColour == 4 && WordColourAlpha == 5 && WordDepth == 6 && WordDepthOnly == 7);
static_assert(WordNearer == 8 && WordHair == 9 && WordBehind == 10 && WordAlphaSum == 11);
static_assert(WordBoxMinX == 12 && WordBoxMinY == 13 && WordBoxMaxX == 14 && WordBoxMaxY == 15);
static_assert(WordBoxMaxY + 1 == SlotWords);
static_assert(BLOOD_SHEEN_HAIR_M == 0.02 && BLOOD_SHEEN_HAIR_REL == 0.01);

struct Pair {
    std::uint64_t vs = 0, ps = 0;
};

struct Knobs {
    float strength = 0.0f; ///< 0: off
    bool show = false;
    std::array<Pair, MaxPairs> pairs{};
    std::uint32_t pair_count = 0;
    bool pairs_named = false; ///< BB_BLOOD_SHEEN_PAIRS gave the pairs
    std::uint32_t pairs_bad = 0; ///< tokens of BB_BLOOD_SHEEN_PAIRS that were not a readable pair
    bool depth_off = false; ///< BB_BLOOD_SHEEN_DEPTH=off (a test): the keyed draw without depth test
};

/// BB_BLOOD_SHEEN's text: the strength (0: off) and the test view.
inline Knobs ReadStrength(const char* text) {
    Knobs k;
    if (text == nullptr || text[0] == '\0') {
        return k;
    }
    const char* t = text;
    while (*t == ' ') {
        ++t;
    }
    if (t[0] == 's' && t[1] == 'h' && t[2] == 'o' && t[3] == 'w') {
        const char* rest = t + 4;
        while (*rest == ' ') {
            ++rest;
        }
        if (*rest == '\0') {
            k.strength = 1.0f;
            k.show = true;
        }
        return k;
    }
    char* end = nullptr;
    const float value = std::strtof(t, &end);
    if (end == t || !std::isfinite(value)) {
        return k;
    }
    while (*end == ' ') {
        ++end;
    }
    if (*end != '\0' || !(value > 0.0f)) {
        return k;
    }
    k.strength = std::clamp(value, MinStrength, MaxStrength);
    return k;
}

/// One hex number of 1 to 16 digits ("0x" optional) from `p` up to `end`; false if not one.
inline bool Hex(const char* p, const char* end, std::uint64_t& out) {
    if (end - p >= 2 && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
    }
    if (p == end || end - p > 16) {
        return false;
    }
    std::uint64_t v = 0;
    for (; p != end; ++p) {
        const int c = static_cast<unsigned char>(*p);
        int d = -1;
        if (c >= '0' && c <= '9') {
            d = c - '0';
        } else if (c >= 'a' && c <= 'f') {
            d = c - 'a' + 10;
        } else if (c >= 'A' && c <= 'F') {
            d = c - 'A' + 10;
        }
        if (d < 0) {
            return false;
        }
        v = (v << 4) | std::uint64_t(d);
    }
    out = v;
    return true;
}

/// BB_BLOOD_SHEEN_PAIRS into `k` (the default pair when it names none).
inline void ReadPairs(Knobs& k, const char* text) {
    k.pair_count = 0;
    k.pairs_named = false;
    k.pairs_bad = 0;
    const char* p = text ? text : "";
    while (*p != '\0') {
        while (*p == ';' || *p == ',' || *p == ' ') {
            ++p;
        }
        const char* start = p;
        while (*p != '\0' && *p != ';' && *p != ',' && *p != ' ') {
            ++p;
        }
        if (start == p) {
            continue;
        }
        const char* colon = start;
        while (colon != p && *colon != ':') {
            ++colon;
        }
        Pair pair;
        if (colon == p || !Hex(start, colon, pair.vs) || !Hex(colon + 1, p, pair.ps) ||
            k.pair_count == MaxPairs) {
            ++k.pairs_bad;
            continue;
        }
        k.pairs[k.pair_count++] = pair;
    }
    if (k.pair_count != 0) {
        k.pairs_named = true;
        return;
    }
    k.pairs[0] = {DefaultVs, DefaultPs};
    k.pair_count = 1;
}

inline Knobs Read(const char* sheen, const char* pairs) {
    Knobs k = ReadStrength(sheen);
    ReadPairs(k, pairs);
    return k;
}

/// BB_BLOOD_SHEEN_DEPTH: exactly "off" (spaces around it allowed) runs the keyed draw without its
/// depth test (a test); anything else leaves the draw as the game sets it.
inline bool ReadDepthOff(const char* text) {
    if (text == nullptr) {
        return false;
    }
    const char* t = text;
    while (*t == ' ') {
        ++t;
    }
    if (t[0] != 'o' || t[1] != 'f' || t[2] != 'f') {
        return false;
    }
    t += 3;
    while (*t == ' ') {
        ++t;
    }
    return *t == '\0';
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs = [] {
        Knobs k = Read(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_PAIRS"));
        k.depth_off = ReadDepthOff(std::getenv("BB_BLOOD_SHEEN_DEPTH"));
        return k;
    }();
    return knobs;
}

/// The box of the pixels a draw changed, from a counter slot (its words are maxima: 65535 - least
/// x and y, largest x and y + 1; all 0 when nothing changed).
struct Box {
    bool any = false;
    std::uint32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0; ///< least and largest pixel, inclusive
};
inline Box DecodeBox(const std::array<std::uint32_t, SlotWords>& c) {
    Box b;
    if (c[WordBoxMaxX] == 0 || c[WordBoxMaxY] == 0 || c[WordBoxMinX] > 65535u ||
        c[WordBoxMinY] > 65535u) {
        return b;
    }
    b.any = true;
    b.x0 = 65535u - c[WordBoxMinX];
    b.y0 = 65535u - c[WordBoxMinY];
    b.x1 = c[WordBoxMaxX] - 1u;
    b.y1 = c[WordBoxMaxY] - 1u;
    return b;
}

inline bool Matches(const Knobs& k, std::uint64_t vs, std::uint64_t ps) {
    for (std::uint32_t i = 0; i < k.pair_count; ++i) {
        if (k.pairs[i].vs == vs && k.pairs[i].ps == ps) {
            return true;
        }
    }
    return false;
}

/// What the key looks at of a draw.
struct DrawShape {
    std::uint64_t vs = 0, ps = 0;
    std::uint32_t indices = 0;
    std::uint32_t mrt_mask = 0;     ///< the colour targets the pipeline writes
    bool target_rgba16f = false;    ///< colour target 0 is RGBA16F
    bool blended = false;           ///< colour target 0 blends
    bool depth_write = false;       ///< depth test and write on
    bool scene_depth = false;       ///< the depth target is the G-buffer pass's
};

enum class Verdict : std::uint32_t {
    OtherPair = 0, ///< not a named pair (every other draw)
    Keyed,         ///< the pool
    FewIndices,    ///< a named pair with fewer than MinIndices indices (the Dream house quads)
    OtherShape,    ///< a named pair drawn otherwise (targets, blending, depth)
};

inline Verdict Classify(const Knobs& k, const DrawShape& d) {
    if (!Matches(k, d.vs, d.ps)) {
        return Verdict::OtherPair;
    }
    if (d.indices < MinIndices) {
        return Verdict::FewIndices;
    }
    if (d.mrt_mask != 1u || !d.target_rgba16f || !d.blended || !d.depth_write || !d.scene_depth) {
        return Verdict::OtherShape;
    }
    return Verdict::Keyed;
}

/// a * b for two 3x4 row-major affine matrices (a 4th row 0 0 0 1).
inline std::array<float, 12> Multiply(const std::array<float, 12>& a, const std::array<float, 12>& b) {
    std::array<float, 12> r{};
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 4; ++j) {
            float v = a[i * 4 + 0] * b[0 * 4 + j] + a[i * 4 + 1] * b[1 * 4 + j] +
                      a[i * 4 + 2] * b[2 * 4 + j];
            if (j == 3) {
                v += a[i * 4 + 3];
            }
            r[i * 4 + j] = v;
        }
    }
    return r;
}

/// blood_sheen.comp's push block, word for word (28 words).
struct Push {
    std::array<float, 12> reproject{};
    std::array<float, 4> proj{}, prev_proj{};
    std::array<float, 2> size{}, jitter{}, prev_jitter{};
    float strength = 0.0f;
    std::uint32_t flags = 0;
};
static_assert(sizeof(Push) == 112);

/// The flags of a pass of frame slot `slot`.
inline std::uint32_t Flags(const Knobs& k, bool alpha_coverage, bool light, std::uint32_t slot) {
    return (k.show ? FlagShow : 0u) | (alpha_coverage ? FlagAlphaCoverage : 0u) |
           (light ? FlagLight : 0u) | ((slot & 1u) != 0 ? FlagSlot : 0u);
}

} // namespace Vulkan::BloodSheenRules
'''),
'engine/gpu/shadps4/video_core/renderer_vulkan/vk_blood_sheen.h': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): a wet glint on the game's forward-drawn blood pool from the lamps and the
// sun or moon (blood_sheen.h has the knobs, the key and the passes' rules; host_shaders/
// blood_sheen.comp the passes).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsBeforeResources, every draw (BeforeDraw): before its textures, barriers and pass. It
//    notes the G-buffer pass's depth and targets 1 and 3, the specular light target (target 1 of the
//    light grid's lamp draws, else of the sun's draw), and a later draw into that target's memory
//    that does more than add light (then the frame's light target is taken as overwritten). At the
//    first light draw after each G-buffer pass (shadow resolve, sun or moon, or a lamp) it records
//    EDIT; at a keyed draw (at most MaxPoolDraws a frame) SNAPSHOT.
//  - EffectsAfterDraw, every draw (AfterDraw): right after the keyed draw, GLINT.
//  - EffectsOnFrameEnd (OnFrameEnd): the counters and every LineFrames frames two log lines.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do. A menu's 3D preview frame (CameraMotion::PreviewFrame) is left alone.
//
// Off (BB_BLOOD_SHEEN unset or 0): the rasterizer makes no BloodSheen (Wanted), so nothing of this is
// made or run; the frame is as before, bit for bit. On: three pipelines and two small buffers are
// made at the first keyed draw; one R32UI image of the scene's size (8.3 MB at 1920x1080) is made
// then, and anew when the scene's size changes. No GPU work runs in a frame without a keyed draw,
// except EDIT in the frame right after one.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_sheen.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace AmdGpu {
union Regs;
}

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class BloodSheen {
public:
    /// BB_BLOOD_SHEEN names a strength above 0 or "show" (BloodSheenRules::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    BloodSheen(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~BloodSheen();
    BloodSheen(const BloodSheen&) = delete;
    BloodSheen& operator=(const BloodSheen&) = delete;

    /// What the hook knows of the draw's pixel shader (the hashes live in the effects file).
    struct Kind {
        bool lamp = false;    ///< a draw of the game's light grid (PointLightCount)
        bool sun = false;     ///< the game's sun or moon (DirectionalFragmentShaderHash)
        bool resolve = false; ///< the game's sun shadow resolve (ShadowResolveHash)
    };
    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target; `lamps_pending`: a lamps-apart batch is still open;
    /// `jitter`: this frame's viewport shift.
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                    Kind kind, bool lamps_pending, std::array<float, 2> jitter);
    /// After every draw: GLINT when it was the keyed draw.
    void AfterDraw();
    /// Every frame end: the counters, and every LineFrames frames the "Blood sheen (r100):" lines.
    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// A game image's view for a pass: the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written or read as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage,
                         bool write);

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    /// Commands every first pass of a frame records first: the last frame's counters to the host,
    /// this frame's slot cleared.
    struct CounterStep {
        bool clear = false, copy_back = false;
        u32 slot = 0;
    };
    CounterStep TakeCounterStep();
    void Edit(std::array<float, 2> jitter);
    void Snapshot(const AmdGpu::Regs& regs, VideoCore::ImageId color, VideoCore::ImageId depth,
                  bool lamps_pending, std::array<float, 2> jitter);
    void Glint();
    void Fail(const char* why);
    /// The specular light target of this frame from here on (`address`: its guest address).
    void TakeLight(VideoCore::ImageId id, u64 address);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, glint_pass, edit_pass;
    /// SNAPSHOT's prints, GLINT's tag (coverage and view depth of the pool's pixels) for the next
    /// frame's EDIT: one R32UI image (EDIT reads the tag before the next SNAPSHOT writes prints).
    VideoCore::UniqueImage tag_image;
    vk::UniqueImageView tag_view;
    u32 tag_width = 0, tag_height = 0;
    bool tag_fresh = false;  ///< made and not yet in the General layout
    bool tag_reduced = false; ///< the tag was written on the reduced scene
    u64 tag_frame = 0;       ///< the frame (frame + 1) whose GLINT wrote the tag; 0: none
    std::array<float, 12> tag_view_matrix{};
    std::array<float, 4> tag_proj{};
    std::array<float, 2> tag_jitter{};
    /// Two slots of SlotWords counters (this frame's, the one before), and the host copy.
    Buffer counters, readback;
    u64 counter_frame = 0; ///< frame + 1 whose slot was cleared; 0: none yet
    u64 counter_used = 0;  ///< frame + 1 that last used a slot
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    u64 frame = 0;

    // This frame, from BeforeDraw.
    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_specular{};
    bool gbuffer_seen = false, edit_tried = false;
    VideoCore::ImageId light{};
    u64 light_uid = 0;     ///< the light target's image_uid when it was taken
    u64 light_address = 0; ///< its guest address (a draw into it by another image id counts too)
    bool light_stale = false;
    bool told_shape = false, told_unfit = false;
    /// SNAPSHOT recorded for the draw being made: GLINT follows it (AfterDraw).
    struct Pending {
        bool on = false;
        VideoCore::ImageId color{}, depth{};
        u32 width = 0, height = 0;
        bool reduced = false, alpha_coverage = false, light = false;
        std::array<float, 2> jitter{};
    } pending;
    bool told_first = false;

    struct Stats {
        u32 frames = 0, keyed_frames = 0, keyed = 0, few_indices = 0, other_shape = 0;
        u32 glints = 0, edits = 0, no_light = 0, light_stale = 0, lamps_pending = 0;
        u32 edit_pending = 0, no_tag = 0, no_room = 0, cannot = 0, previews = 0, twice = 0;
        u32 over_cap = 0;
    } stats;
    u32 keyed_this_frame = 0;
};

} // namespace Vulkan
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): a wet glint on the game's forward-drawn blood pool from the lamps and the
// sun or moon (blood_sheen.h has the knobs, the key and the passes' rules; host_shaders/
// blood_sheen.comp the passes).
//
// Where (hooks in vk_rasterizer_effects.cpp, each a null pointer test while it is off):
//  - EffectsBeforeResources, every draw (BeforeDraw): before its textures, barriers and pass. It
//    notes the G-buffer pass's depth and targets 1 and 3, the specular light target (target 1 of the
//    light grid's lamp draws, else of the sun's draw), and a later draw into that target's memory
//    that does more than add light (then the frame's light target is taken as overwritten). At the
//    first light draw after each G-buffer pass (shadow resolve, sun or moon, or a lamp) it records
//    EDIT; at a keyed draw (at most MaxPoolDraws a frame) SNAPSHOT.
//  - EffectsAfterDraw, every draw (AfterDraw): right after the keyed draw, GLINT.
//  - EffectsOnFrameEnd (OnFrameEnd): the counters and every LineFrames frames three log lines.
// bbport (r100b_blood-sheen-mark): SNAPSHOT also keeps the scene depth's bits, so GLINT takes the
// pixels whose depth the draw wrote as well as those whose colour it changed with alpha; the third
// line counts each test on its own. With BB_BLOOD_SHEEN_DEPTH=off (a TEST) the keyed draw runs
// without its depth test: BeforeDraw records the compare op Always after SNAPSHOT and marks the
// scheduler's cached compare op as the game's and not dirty, so the draw's own dynamic state finds
// nothing to change; GLINT (or the next BeforeDraw, when the draw was left out) records the cached
// op again. A command buffer change in between re-commits the cache: the test is then just not
// in force for that draw.
// Each pass ends the game's render pass (the next draw begins a new one), as the engine's other
// passes between draws do. A menu's 3D preview frame (CameraMotion::PreviewFrame) is left alone.
//
// Off (BB_BLOOD_SHEEN unset or 0): the rasterizer makes no BloodSheen (Wanted), so nothing of this is
// made or run; the frame is as before, bit for bit. On: three pipelines and two small buffers are
// made at the first keyed draw; two R32UI images of the scene's size (8.3 MB each at 1920x1080) are
// made then, and anew when the scene's size changes. No GPU work runs in a frame without a keyed
// draw, except EDIT in the frame right after one.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/blood_sheen.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace AmdGpu {
union Regs;
}

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class GraphicsPipeline;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class BloodSheen {
public:
    /// BB_BLOOD_SHEEN names a strength above 0 or "show" (BloodSheenRules::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    BloodSheen(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~BloodSheen();
    BloodSheen(const BloodSheen&) = delete;
    BloodSheen& operator=(const BloodSheen&) = delete;

    /// What the hook knows of the draw's pixel shader (the hashes live in the effects file).
    struct Kind {
        bool lamp = false;    ///< a draw of the game's light grid (PointLightCount)
        bool sun = false;     ///< the game's sun or moon (DirectionalFragmentShaderHash)
        bool resolve = false; ///< the game's sun shadow resolve (ShadowResolveHash)
    };
    /// Before every draw's resources: `targets` its colour targets (only those in its mrt_mask are
    /// this draw's), `depth` its depth target; `lamps_pending`: a lamps-apart batch is still open;
    /// `jitter`: this frame's viewport shift.
    void BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                    const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                    Kind kind, bool lamps_pending, std::array<float, 2> jitter);
    /// After every draw: GLINT when it was the keyed draw.
    void AfterDraw();
    /// Every frame end: the counters, and every LineFrames frames the "Blood sheen (r100):" lines.
    void OnFrameEnd();

private:
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    /// A game image's view for a pass: the reduced proxy or the image itself (General layout);
    /// null when it cannot serve (`storage`: it is written or read as a storage image).
    vk::ImageView ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage,
                         bool write);

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    bool EnsureImage(u32 width, u32 height);
    void ReleaseImage();
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    /// The scene's size for the image `id` (the reduced one, else the game's render size).
    bool SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced);
    /// Commands every first pass of a frame records first: the last frame's counters to the host,
    /// this frame's slot cleared.
    struct CounterStep {
        bool clear = false, copy_back = false;
        u32 slot = 0;
    };
    CounterStep TakeCounterStep();
    void Edit(std::array<float, 2> jitter);
    void Snapshot(const AmdGpu::Regs& regs, VideoCore::ImageId color, VideoCore::ImageId depth,
                  bool lamps_pending, std::array<float, 2> jitter);
    void Glint();
    /// BB_BLOOD_SHEEN_DEPTH=off (a test): the keyed draw about to be made runs with the depth compare
    /// op Always; RestoreDepthTest records the scheduler's cached op again (once).
    void ForceNoDepthTest(const AmdGpu::Regs& regs);
    void RestoreDepthTest();
    void Fail(const char* why);
    /// The specular light target of this frame from here on (`address`: its guest address).
    void TakeLight(VideoCore::ImageId id, u64 address);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    Pass snapshot_pass, glint_pass, edit_pass;
    /// SNAPSHOT's prints, GLINT's tag (coverage and view depth of the pool's pixels) for the next
    /// frame's EDIT: one R32UI image (EDIT reads the tag before the next SNAPSHOT writes prints).
    VideoCore::UniqueImage tag_image;
    vk::UniqueImageView tag_view;
    u32 tag_width = 0, tag_height = 0;
    bool tag_fresh = false;  ///< made and not yet in the General layout
    bool tag_reduced = false; ///< the tag was written on the reduced scene
    u64 tag_frame = 0;       ///< the frame (frame + 1) whose GLINT wrote the tag; 0: none
    /// bbport (r100b_blood-sheen-mark): SNAPSHOT's copy of the scene depth's bits (R32UI, the tag's
    /// size), for GLINT's "the draw wrote its depth here".
    VideoCore::UniqueImage before_image;
    vk::UniqueImageView before_view;
    std::array<float, 12> tag_view_matrix{};
    std::array<float, 4> tag_proj{};
    std::array<float, 2> tag_jitter{};
    /// Two slots of SlotWords counters (this frame's, the one before), and the host copy.
    Buffer counters, readback;
    u64 counter_frame = 0; ///< frame + 1 whose slot was cleared; 0: none yet
    u64 counter_used = 0;  ///< frame + 1 that last used a slot
    std::array<ViewEntry, 8> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    u64 frame = 0;

    // This frame, from BeforeDraw.
    VideoCore::ImageId gbuffer_depth{}, gbuffer_material{}, gbuffer_specular{};
    bool gbuffer_seen = false, edit_tried = false;
    VideoCore::ImageId light{};
    u64 light_uid = 0;     ///< the light target's image_uid when it was taken
    u64 light_address = 0; ///< its guest address (a draw into it by another image id counts too)
    bool light_stale = false;
    bool told_shape = false, told_unfit = false;
    bool told_state = false; ///< the first keyed draw's depth, bias and write mask said
    u32 last_indices = 0;    ///< the last keyed draw's index count
    bool depth_forced = false; ///< ForceNoDepthTest recorded Always; not yet restored
    /// SNAPSHOT recorded for the draw being made: GLINT follows it (AfterDraw).
    struct Pending {
        bool on = false;
        VideoCore::ImageId color{}, depth{};
        u32 width = 0, height = 0;
        bool reduced = false, alpha_coverage = false, light = false;
        std::array<float, 2> jitter{};
    } pending;
    bool told_first = false;

    struct Stats {
        u32 frames = 0, keyed_frames = 0, keyed = 0, few_indices = 0, other_shape = 0;
        u32 glints = 0, edits = 0, no_light = 0, light_stale = 0, lamps_pending = 0;
        u32 edit_pending = 0, no_tag = 0, no_room = 0, cannot = 0, previews = 0, twice = 0;
        u32 over_cap = 0;
        u32 depth_off = 0; ///< keyed draws run without their depth test (BB_BLOOD_SHEEN_DEPTH=off)
    } stats;
    u32 keyed_this_frame = 0;
};

} // namespace Vulkan
'''),
'engine/gpu/shadps4/video_core/renderer_vulkan/vk_blood_sheen.cpp': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_blood_sheen.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_sheen_edit_comp.h"
#include "video_core/host_shaders/blood_sheen_glint_comp.h"
#include "video_core/host_shaders/blood_sheen_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = BloodSheenRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto GbufferFormat = vk::Format::eR8G8B8A8Unorm;
constexpr auto TagFormat = vk::Format::eR32Uint;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;
constexpr u64 ProfileRow = 100; ///< EffectPass::Mark: the row "Lighting: blood sheen"

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .pBufferInfo = info};
}

/// The counters' commands of a frame's first pass (BloodSheen::TakeCounterStep), then the barrier
/// that lets the pass add to them.
void CounterCommands(vk::CommandBuffer cmd, vk::Buffer counters, vk::Buffer host, bool clear,
                     bool copy_back, u32 slot) {
    if (!clear) {
        return;
    }
    if (copy_back) {
        cmd.copyBuffer(counters, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
    }
    cmd.fillBuffer(counters, slot * SlotBytes, SlotBytes, 0);
    EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                              Compute | vk::PipelineStageFlagBits2::eHost,
                              ReadWrite | vk::AccessFlagBits2::eHostRead);
}

/// What a pass's commands begin with: the game's writes before it (and the frame before's reads of
/// the tag) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                              Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// The draw's output to colour target `cb` only adds to what the target holds (the rule of
/// AddsLight in vk_rasterizer_effects.cpp: the grid's other lights between the lamps), and no fast
/// clear is owed to it. Anything else drawn into the light target replaces the frame's light.
bool OnlyAdds(const AmdGpu::Regs& regs, u32 cb, const VideoCore::TextureCache& texture_cache) {
    using Factor = AmdGpu::BlendControl::BlendFactor;
    const auto& blend = regs.blend_control[cb];
    const auto& target = regs.color_buffers[cb];
    return blend.enable && !target.info.blend_bypass &&
           blend.color_func == AmdGpu::BlendControl::BlendFunc::Add &&
           blend.color_dst_factor == Factor::One &&
           (blend.color_src_factor == Factor::One || blend.color_src_factor == Factor::SrcAlpha) &&
           regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Normal &&
           regs.color_control.rop3 == AmdGpu::ColorControl::LogicOp::Copy &&
           !texture_cache.IsMetaCleared(target.CmaskAddress(), target.BaseSlice());
}
} // namespace

bool BloodSheen::Wanted() {
    return R::Load().strength > 0.0f;
}

BloodSheen::BloodSheen(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const auto& k = R::Load();
    BbReport::Printf("Blood sheen (r100): on, strength %.2f%s; the game's specular light target "
                     "(lamps with their ray traced shadow, sun or moon with its shadow) laid over "
                     "the pool; pool: a named pair, at least %u indices, one RGBA16F target, "
                     "blended, writing the scene depth\n",
                     double(k.strength), k.show ? ", show (marked pixels half cyan)" : "",
                     R::MinIndices);
    std::string pairs;
    for (u32 i = 0; i < k.pair_count; ++i) {
        char text[40];
        std::snprintf(text, sizeof(text), "%s%08llx:%08llx", i ? ";" : "",
                      static_cast<unsigned long long>(k.pairs[i].vs),
                      static_cast<unsigned long long>(k.pairs[i].ps));
        pairs += text;
    }
    BbReport::Printf("Blood sheen (r100): pairs %s (%u): %s%s\n",
                     k.pairs_named ? "from BB_BLOOD_SHEEN_PAIRS" : "default", k.pair_count,
                     pairs.c_str(),
                     k.pairs_bad != 0 ? "; BB_BLOOD_SHEEN_PAIRS had unreadable or extra tokens"
                                      : "");
}

BloodSheen::~BloodSheen() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(counters);
    FreeBuffer(readback);
}

bool BloodSheen::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                            vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
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

void BloodSheen::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodSheen::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TagFormat) &&
        EffectPass::StorageFormat(instance, GbufferFormat) &&
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout,
                           snapshot_pass.pipeline, {eStorageImage, eStorageImage},
                           sizeof(R::Push), BLOOD_SHEEN_SNAPSHOT_COMP, "Blood sheen snapshot") &&
        EffectPass::Create(instance, glint_pass.set_layout, glint_pass.layout, glint_pass.pipeline,
                           {eStorageImage, eStorageImage, eSampledImage, eSampledImage,
                            eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_GLINT_COMP, "Blood sheen glint") &&
        EffectPass::Create(instance, edit_pass.set_layout, edit_pass.layout, edit_pass.pipeline,
                           {eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_EDIT_COMP, "Blood sheen wet ground") &&
        MakeBuffer(counters, R::Slots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void BloodSheen::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Blood sheen (r100): off - %s\n", why);
    ReleaseImage();
}

void BloodSheen::ReleaseImage() {
    if (tag_image) {
        scheduler.DeferOperation([image = std::move(tag_image), view = std::move(tag_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    tag_view.reset();
    tag_width = tag_height = 0;
    tag_frame = 0;
}

bool BloodSheen::EnsureImage(u32 width, u32 height) {
    if (tag_image && tag_width == width && tag_height == height) {
        return true;
    }
    ReleaseImage();
    if (!EffectPass::HasRoom(instance, 4ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    tag_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    tag_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = TagFormat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(tag_image), "Blood sheen tag");
    tag_view = Check<"create blood sheen tag view">(device.createImageViewUnique({
        .image = vk::Image(tag_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    tag_width = width;
    tag_height = height;
    tag_fresh = true;
    tag_frame = 0;
    return true;
}

vk::ImageView BloodSheen::CachedView(const VideoCore::Image& image, vk::Format format,
                                     vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
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
        .format = format,
        .aspect = aspect,
        .view = Check<"create blood sheen view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool BloodSheen::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

vk::ImageView BloodSheen::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage,
                                 bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

BloodSheen::CounterStep BloodSheen::TakeCounterStep() {
    CounterStep step{};
    step.slot = u32(frame & 1);
    if (counter_frame != frame + 1) {
        counter_frame = frame + 1;
        step.clear = true;
        // the frame before used the other slot: its counts are complete in the queue before this
        step.copy_back = counter_used == frame && frame != 0;
    }
    counter_used = frame + 1;
    return step;
}

void BloodSheen::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                            const std::array<VideoCore::ImageId, 8>& targets,
                            VideoCore::ImageId depth, Kind kind, bool lamps_pending,
                            std::array<float, 2> jitter) {
    // A SNAPSHOT whose draw was left out (a pipeline still compiling): its GLINT never comes.
    pending = {};
    if (failed) {
        return;
    }
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    // The G-buffer pass: its depth, gloss (target 1) and specular colour (target 3).
    if (std::popcount(mrt) >= 5 && depth) {
        // Each G-buffer pass's lighting comes after it (a planar reflection's pass and the world's
        // each get their own EDIT and light target).
        edit_tried = false;
        light = {};
        light_stale = false;
        gbuffer_seen = true;
        gbuffer_depth = depth;
        gbuffer_material = (mrt & 2u) ? targets[1] : VideoCore::ImageId{};
        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        return;
    }
    // The specular light target: target 1 of the light grid's lamp draws (they add diffuse into
    // target 0 and specular into target 1), else of the sun's draw. A later draw into its memory
    // (by any image id) that does more than add light replaces what it holds: the frame's lighting
    // is gone from it.
    if (kind.lamp) {
        if ((mrt & 3u) == 3u && targets[1]) {
            TakeLight(targets[1], regs.color_buffers[1].Address());
        }
    } else if (kind.sun) {
        if ((mrt & 2u) && targets[1] && !light) {
            TakeLight(targets[1], regs.color_buffers[1].Address());
        }
    } else if (light && !light_stale) {
        for (u32 cb = 0; cb < targets.size(); ++cb) {
            if (((mrt >> cb) & 1u) && regs.color_buffers[cb] &&
                (targets[cb] == light || regs.color_buffers[cb].Address() == light_address) &&
                !OnlyAdds(regs, cb, texture_cache)) {
                light_stale = true;
            }
        }
    }
    // EDIT: at the first light draw after each G-buffer pass (the shadow resolve, the sun or moon,
    // or a lamp of the grid, whichever comes first), before its pass: the game's own lighting then
    // sees the wet ground. Not while a lamps-apart batch is open (its deferred lamps read the
    // G-buffer later; the batch's lamps would light the ground half dry and half wet): counted.
    if ((kind.resolve || kind.sun || kind.lamp) && gbuffer_seen && !edit_tried) {
        edit_tried = true;
        if (lamps_pending) {
            stats.edit_pending += tag_frame != 0 ? 1 : 0;
        } else if (!camera_motion.PreviewFrame()) {
            Edit(jitter);
        }
    }
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps) {
        return;
    }
    const auto& k = R::Load();
    const u64 vs_hash = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
    if (!R::Matches(k, vs_hash, ps->pgm_hash)) {
        return;
    }
    const R::DrawShape shape{
        .vs = vs_hash,
        .ps = ps->pgm_hash,
        .indices = u32(regs.num_indices),
        .mrt_mask = mrt,
        .target_rgba16f = bool(targets[0]) &&
                          texture_cache.GetImage(targets[0]).info.pixel_format == SceneFormat,
        .blended = regs.blend_control[0].enable != 0 && regs.color_buffers[0].info.blend_bypass == 0,
        .depth_write = regs.depth_control.depth_enable != 0 &&
                       regs.depth_control.depth_write_enable != 0,
        .scene_depth = bool(depth) && depth == camera_motion.Depth(),
    };
    switch (R::Classify(k, shape)) {
    case R::Verdict::FewIndices:
        ++stats.few_indices;
        return;
    case R::Verdict::OtherShape:
        ++stats.other_shape;
        if (!told_shape) {
            told_shape = true;
            BbReport::Printf("Blood sheen (r100): first named pair draw of another shape (left out): "
                             "%u indices, colour targets 0x%x, target 0 format %u (RGBA16F is 97), "
                             "blended %u, depth write %u, the scene depth %u\n",
                             shape.indices, shape.mrt_mask,
                             targets[0] ? u32(texture_cache.GetImage(targets[0]).info.pixel_format)
                                        : 0u,
                             u32(shape.blended), u32(shape.depth_write), u32(shape.scene_depth));
        }
        return;
    case R::Verdict::Keyed:
        break;
    case R::Verdict::OtherPair:
        return;
    }
    ++stats.keyed;
    if (++keyed_this_frame > R::MaxPoolDraws) {
        ++stats.over_cap;
        return;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    Snapshot(regs, targets[0], depth, lamps_pending, jitter);
}

void BloodSheen::Edit(std::array<float, 2> jitter) {
    // The tag of the frame right before this one, on a scene of this size, and both cameras.
    if (tag_frame == 0) {
        return; // no pool in the frame before: nothing to make wet
    }
    // (Not used up here: every G-buffer pass of the frame, a planar reflection's too, gets it; the
    // next SNAPSHOT replaces it.)
    const bool tag_fits = tag_frame == frame;
    if (!tag_fits) {
        tag_frame = 0; // older than the frame before: said once
    }
    const auto camera = camera_motion.PassMatrices();
    if (!tag_image || !tag_fits || !camera.valid || camera.proj[0] == 0.0f ||
        camera.proj[1] == 0.0f || tag_proj[0] == 0.0f || tag_proj[1] == 0.0f) {
        ++stats.no_tag;
        return;
    }
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth() || !gbuffer_material ||
        !gbuffer_specular) {
        ++stats.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(gbuffer_depth, width, height, reduced) || width != tag_width ||
        height != tag_height || reduced != tag_reduced) {
        ++stats.no_tag;
        return;
    }
    // Targets 1 and 3 must be RGBA8 (the shader's rgba8 images) and stand where the depth does.
    for (const auto id : {gbuffer_material, gbuffer_specular}) {
        const auto& image = texture_cache.GetImage(id);
        const bool fits = image.info.pixel_format == GbufferFormat &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == reduced &&
                          image.info.size.width >= (reduced ? 1u : width) &&
                          image.info.size.height >= (reduced ? 1u : height);
        if (!fits) {
            ++stats.cannot;
            if (!told_unfit) {
                told_unfit = true;
                BbReport::Printf("Blood sheen (r100): wet ground left out (first time): G-buffer "
                                 "target 1 format %u, target 3 format %u, %ux%u (the pass writes "
                                 "R8G8B8A8_UNORM, 37, on a %ux%u scene)\n",
                                 u32(texture_cache.GetImage(gbuffer_material).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_specular).info.pixel_format),
                                 image.info.size.width, image.info.size.height, width, height);
            }
            return;
        }
    }
    if (!Ready()) {
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView depth_view = ViewOf(gbuffer_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    const vk::ImageView material_view =
        ViewOf(gbuffer_material, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView specular_view =
        ViewOf(gbuffer_specular, vk::ImageAspectFlagBits::eColor, true, true);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!depth_view || !material_view || !specular_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.reproject = R::Multiply(tag_view_matrix, camera.inv_view);
    push.proj = camera.proj;
    push.prev_proj = tag_proj;
    push.size = {float(width), float(height)};
    push.jitter = jitter;
    push.prev_jitter = tag_jitter;
    push.strength = k.strength;
    push.flags = R::Flags(k, false, false, step.slot);
    ++stats.edits;
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen wet ground"},
        [push, step, width, height, depth_view, material_view, specular_view, tag = *tag_view,
         counter_buffer = counters.buffer, host = readback.buffer, pipeline = *edit_pass.pipeline,
         layout = *edit_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(depth_view), Info(tag), Info(material_view),
                                   Info(specular_view)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]),
                                    ImageWrite(3, eStorageImage, &infos[3]),
                                    BufferWrite(4, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
}

void BloodSheen::Snapshot(const AmdGpu::Regs& regs, VideoCore::ImageId color,
                          VideoCore::ImageId depth, bool lamps_pending,
                          std::array<float, 2> jitter) {
    // Lamps apart (vk_point_shadow.h): a batch still open has its lamp light outside the light
    // target, so GLINT would read it without its lamps.
    if (lamps_pending) {
        ++stats.lamps_pending;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(color, width, height, reduced)) {
        ++stats.cannot;
        return;
    }
    const auto& depth_image = texture_cache.GetImage(depth);
    if ((scene_targets.Reduced() && scene_targets.EligibleScene(depth_image)) != reduced ||
        (!reduced && (depth_image.info.size.width < width || depth_image.info.size.height < height))) {
        ++stats.cannot;
        return;
    }
    if (!Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView color_view = ViewOf(color, vk::ImageAspectFlagBits::eColor, true, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view) {
        ++stats.cannot;
        return;
    }
    using Factor = AmdGpu::BlendControl::BlendFactor;
    const auto& blend = regs.blend_control[0];
    // The draw's alpha blend One/Zero with Add: the scene's alpha after it is the draw's own alpha,
    // its coverage of the pixel.
    const bool alpha_coverage = blend.separate_alpha_blend != 0 &&
                                blend.alpha_func == AmdGpu::BlendControl::BlendFunc::Add &&
                                blend.alpha_src_factor == Factor::One &&
                                blend.alpha_dst_factor == Factor::Zero;
    const bool has_light = light && !light_stale;
    if (!has_light && light) {
        ++stats.light_stale;
    } else if (!has_light) {
        ++stats.no_light;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.size = {float(width), float(height)};
    push.flags = R::Flags(k, false, false, step.slot);
    tag_frame = 0; // the prints take the tag's place
    const bool fresh = std::exchange(tag_fresh, false);
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen snapshot"},
        [push, step, fresh, width, height, color_view, tag_handle = vk::Image(tag_image),
         tag = *tag_view, counter_buffer = counters.buffer, host = readback.buffer,
         pipeline = *snapshot_pass.pipeline, layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
            }
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(tag)};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
    pending = {.on = true,
               .color = color,
               .depth = depth,
               .width = width,
               .height = height,
               .reduced = reduced,
               .alpha_coverage = alpha_coverage,
               .light = has_light,
               .jitter = jitter};
}

void BloodSheen::AfterDraw() {
    if (pending.on) {
        Glint();
    }
}

void BloodSheen::TakeLight(VideoCore::ImageId id, u64 address) {
    light = id;
    light_uid = texture_cache.GetImage(id).image_uid;
    light_address = address;
    light_stale = false;
}

void BloodSheen::Glint() {
    const Pending p = pending;
    pending = {};
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView color_view = ViewOf(p.color, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(p.depth, vk::ImageAspectFlagBits::eDepth, false, false);
    vk::ImageView light_view{};
    if (p.light) {
        // The light target must stand where the scene does (the same proxying, at least its size).
        const auto& image = texture_cache.GetImage(light);
        const bool fits = image.image_uid == light_uid &&
                          (image.aspect_mask & vk::ImageAspectFlagBits::eColor) &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == p.reduced &&
                          (p.reduced || (image.info.size.width >= p.width &&
                                         image.info.size.height >= p.height));
        light_view = fits ? ViewOf(light, vk::ImageAspectFlagBits::eColor, false, false)
                          : vk::ImageView{};
        if (!light_view) {
            ++stats.no_light;
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view || !depth_view) {
        ++stats.cannot;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.proj = camera.proj;
    push.size = {float(p.width), float(p.height)};
    push.jitter = p.jitter;
    push.strength = k.strength;
    push.flags = R::Flags(k, p.alpha_coverage, bool(light_view), step.slot);
    ++stats.glints;
    if (!told_first) {
        told_first = true;
        BbReport::Printf("Blood sheen (r100): first pool draw at frame %llu, %ux%u (%s), coverage "
                         "from %s, specular light target %s\n",
                         static_cast<unsigned long long>(frame), p.width, p.height,
                         p.reduced ? "reduced scene" : "the game's scene",
                         p.alpha_coverage ? "the draw's alpha" : "1 (its alpha blend is not One/Zero Add)",
                         light_view ? "found" : "not found (no glint)");
    }
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen glint"},
        [push, step, width = p.width, height = p.height, color_view, depth_view,
         light_or_depth = light_view ? light_view : depth_view, tag = *tag_view,
         counter_buffer = counters.buffer, host = readback.buffer, pipeline = *glint_pass.pipeline,
         layout = *glint_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(tag), Info(depth_view),
                                   Info(light_or_depth)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eSampledImage, &infos[2]),
                                    ImageWrite(3, eSampledImage, &infos[3]),
                                    BufferWrite(4, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
    // The tag for the next frame's EDIT: this frame's camera (world to view) and jitter.
    if (camera.valid && camera.proj[0] != 0.0f && camera.proj[1] != 0.0f) {
        tag_frame = frame + 1;
        tag_view_matrix = camera.view;
        tag_proj = camera.proj;
        tag_jitter = p.jitter;
        tag_reduced = p.reduced;
    }
}

void BloodSheen::OnFrameEnd() {
    if (keyed_this_frame != 0) {
        ++stats.keyed_frames;
        stats.twice += keyed_this_frame > 1 ? 1 : 0;
    }
    keyed_this_frame = 0;
    pending = {};
    gbuffer_seen = edit_tried = light_stale = false;
    gbuffer_depth = gbuffer_material = gbuffer_specular = light = {};
    light_uid = light_address = 0;
    ++frame;
    if (++stats.frames < LineFrames) {
        return;
    }
    // The host copy of the last frame with a pass whose next frame had one too (no fence is
    // waited for: a log line).
    std::array<u32, R::SlotWords> c{};
    if (readback.mapped) {
        std::memcpy(c.data(), readback.mapped, sizeof(c));
    }
    BbReport::Printf("Blood sheen (r100): %u frames, %u with the pool (%u draws; %u frames with more "
                     "than one, %u draws over the cap of %u a frame), %u glint and %u wet ground "
                     "passes; pair draws left out: %u under %u indices, %u of another shape; %u in "
                     "menu previews\n",
                     stats.frames, stats.keyed_frames, stats.keyed, stats.twice, stats.over_cap,
                     R::MaxPoolDraws, stats.glints, stats.edits, stats.few_indices, R::MinIndices,
                     stats.other_shape, stats.previews);
    BbReport::Printf("Blood sheen (r100): recent frame: %u pool pixels, %u lit, %u ground pixels wet, "
                     "%u tags found; skipped: %u no light target, %u light target drawn over, %u "
                     "lamps pending, %u wet ground lamps open, %u no tag, %u no room, %u unfit%s\n",
                     c[0], c[1], c[2], c[3], stats.no_light, stats.light_stale, stats.lamps_pending,
                     stats.edit_pending, stats.no_tag, stats.no_room, stats.cannot,
                     failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_blood_sheen.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_sheen_edit_comp.h"
#include "video_core/host_shaders/blood_sheen_glint_comp.h"
#include "video_core/host_shaders/blood_sheen_snapshot_comp.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = BloodSheenRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto GbufferFormat = vk::Format::eR8G8B8A8Unorm;
constexpr auto TagFormat = vk::Format::eR32Uint;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;
constexpr u64 ProfileRow = 100; ///< EffectPass::Mark: the row "Lighting: blood sheen"

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .pBufferInfo = info};
}

/// The counters' commands of a frame's first pass (BloodSheen::TakeCounterStep), then the barrier
/// that lets the pass add to them.
void CounterCommands(vk::CommandBuffer cmd, vk::Buffer counters, vk::Buffer host, bool clear,
                     bool copy_back, u32 slot) {
    if (!clear) {
        return;
    }
    if (copy_back) {
        cmd.copyBuffer(counters, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
    }
    cmd.fillBuffer(counters, slot * SlotBytes, SlotBytes, 0);
    EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                              Compute | vk::PipelineStageFlagBits2::eHost,
                              ReadWrite | vk::AccessFlagBits2::eHostRead);
}

/// What a pass's commands begin with: the game's writes before it (and the frame before's reads of
/// the tag) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                              Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// The draw's output to colour target `cb` only adds to what the target holds (the rule of
/// AddsLight in vk_rasterizer_effects.cpp: the grid's other lights between the lamps), and no fast
/// clear is owed to it. Anything else drawn into the light target replaces the frame's light.
bool OnlyAdds(const AmdGpu::Regs& regs, u32 cb, const VideoCore::TextureCache& texture_cache) {
    using Factor = AmdGpu::BlendControl::BlendFactor;
    const auto& blend = regs.blend_control[cb];
    const auto& target = regs.color_buffers[cb];
    return blend.enable && !target.info.blend_bypass &&
           blend.color_func == AmdGpu::BlendControl::BlendFunc::Add &&
           blend.color_dst_factor == Factor::One &&
           (blend.color_src_factor == Factor::One || blend.color_src_factor == Factor::SrcAlpha) &&
           regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Normal &&
           regs.color_control.rop3 == AmdGpu::ColorControl::LogicOp::Copy &&
           !texture_cache.IsMetaCleared(target.CmaskAddress(), target.BaseSlice());
}
} // namespace

bool BloodSheen::Wanted() {
    return R::Load().strength > 0.0f;
}

BloodSheen::BloodSheen(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const auto& k = R::Load();
    BbReport::Printf("Blood sheen (r100): on, strength %.2f%s; the game's specular light target "
                     "(lamps with their ray traced shadow, sun or moon with its shadow) laid over "
                     "the pool; pool: a named pair, at least %u indices, one RGBA16F target, "
                     "blended, writing the scene depth\n",
                     double(k.strength), k.show ? ", show (a colour per test)" : "",
                     R::MinIndices);
    std::string pairs;
    for (u32 i = 0; i < k.pair_count; ++i) {
        char text[40];
        std::snprintf(text, sizeof(text), "%s%08llx:%08llx", i ? ";" : "",
                      static_cast<unsigned long long>(k.pairs[i].vs),
                      static_cast<unsigned long long>(k.pairs[i].ps));
        pairs += text;
    }
    BbReport::Printf("Blood sheen (r100): pairs %s (%u): %s%s\n",
                     k.pairs_named ? "from BB_BLOOD_SHEEN_PAIRS" : "default", k.pair_count,
                     pairs.c_str(),
                     k.pairs_bad != 0 ? "; BB_BLOOD_SHEEN_PAIRS had unreadable or extra tokens"
                                      : "");
}

BloodSheen::~BloodSheen() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(counters);
    FreeBuffer(readback);
}

bool BloodSheen::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                            vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
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

void BloodSheen::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodSheen::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TagFormat) &&
        EffectPass::StorageFormat(instance, GbufferFormat) &&
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout,
                           snapshot_pass.pipeline,
                           {eStorageImage, eStorageImage, eSampledImage, eStorageImage},
                           sizeof(R::Push), BLOOD_SHEEN_SNAPSHOT_COMP, "Blood sheen snapshot") &&
        EffectPass::Create(instance, glint_pass.set_layout, glint_pass.layout, glint_pass.pipeline,
                           {eStorageImage, eStorageImage, eSampledImage, eSampledImage,
                            eStorageBuffer, eStorageImage},
                           sizeof(R::Push), BLOOD_SHEEN_GLINT_COMP, "Blood sheen glint") &&
        EffectPass::Create(instance, edit_pass.set_layout, edit_pass.layout, edit_pass.pipeline,
                           {eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_EDIT_COMP, "Blood sheen wet ground") &&
        MakeBuffer(counters, R::Slots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void BloodSheen::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Blood sheen (r100): off - %s\n", why);
    ReleaseImage();
}

void BloodSheen::ReleaseImage() {
    if (tag_image) {
        scheduler.DeferOperation([image = std::move(tag_image), view = std::move(tag_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    if (before_image) {
        scheduler.DeferOperation(
            [image = std::move(before_image), view = std::move(before_view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    tag_view.reset();
    before_view.reset();
    tag_width = tag_height = 0;
    tag_frame = 0;
}

bool BloodSheen::EnsureImage(u32 width, u32 height) {
    if (tag_image && tag_width == width && tag_height == height) {
        return true;
    }
    ReleaseImage();
    // The tag and (bbport r100b_blood-sheen-mark) the depth before the pool's draw: 4 bytes each.
    if (!EffectPass::HasRoom(instance, 8ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = TagFormat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    tag_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    tag_image.Create(image_ci);
    SetObjectName(device, vk::Image(tag_image), "Blood sheen tag");
    tag_view = Check<"create blood sheen tag view">(device.createImageViewUnique({
        .image = vk::Image(tag_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    before_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    before_image.Create(image_ci);
    SetObjectName(device, vk::Image(before_image), "Blood sheen depth before");
    before_view = Check<"create blood sheen depth before view">(device.createImageViewUnique({
        .image = vk::Image(before_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    tag_width = width;
    tag_height = height;
    tag_fresh = true;
    tag_frame = 0;
    return true;
}

vk::ImageView BloodSheen::CachedView(const VideoCore::Image& image, vk::Format format,
                                     vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
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
        .format = format,
        .aspect = aspect,
        .view = Check<"create blood sheen view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool BloodSheen::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

vk::ImageView BloodSheen::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage,
                                 bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

BloodSheen::CounterStep BloodSheen::TakeCounterStep() {
    CounterStep step{};
    step.slot = u32(frame & 1);
    if (counter_frame != frame + 1) {
        counter_frame = frame + 1;
        step.clear = true;
        // the frame before used the other slot: its counts are complete in the queue before this
        step.copy_back = counter_used == frame && frame != 0;
    }
    counter_used = frame + 1;
    return step;
}

void BloodSheen::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                            const std::array<VideoCore::ImageId, 8>& targets,
                            VideoCore::ImageId depth, Kind kind, bool lamps_pending,
                            std::array<float, 2> jitter) {
    // A SNAPSHOT whose draw was left out (a pipeline still compiling): its GLINT never comes (and
    // a depth test it turned off is turned back on before this draw's state is committed).
    RestoreDepthTest();
    pending = {};
    if (failed) {
        return;
    }
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    // The G-buffer pass: its depth, gloss (target 1) and specular colour (target 3).
    if (std::popcount(mrt) >= 5 && depth) {
        // Each G-buffer pass's lighting comes after it (a planar reflection's pass and the world's
        // each get their own EDIT and light target).
        edit_tried = false;
        light = {};
        light_stale = false;
        gbuffer_seen = true;
        gbuffer_depth = depth;
        gbuffer_material = (mrt & 2u) ? targets[1] : VideoCore::ImageId{};
        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        return;
    }
    // The specular light target: target 1 of the light grid's lamp draws (they add diffuse into
    // target 0 and specular into target 1), else of the sun's draw. A later draw into its memory
    // (by any image id) that does more than add light replaces what it holds: the frame's lighting
    // is gone from it.
    if (kind.lamp) {
        if ((mrt & 3u) == 3u && targets[1]) {
            TakeLight(targets[1], regs.color_buffers[1].Address());
        }
    } else if (kind.sun) {
        if ((mrt & 2u) && targets[1] && !light) {
            TakeLight(targets[1], regs.color_buffers[1].Address());
        }
    } else if (light && !light_stale) {
        for (u32 cb = 0; cb < targets.size(); ++cb) {
            if (((mrt >> cb) & 1u) && regs.color_buffers[cb] &&
                (targets[cb] == light || regs.color_buffers[cb].Address() == light_address) &&
                !OnlyAdds(regs, cb, texture_cache)) {
                light_stale = true;
            }
        }
    }
    // EDIT: at the first light draw after each G-buffer pass (the shadow resolve, the sun or moon,
    // or a lamp of the grid, whichever comes first), before its pass: the game's own lighting then
    // sees the wet ground. Not while a lamps-apart batch is open (its deferred lamps read the
    // G-buffer later; the batch's lamps would light the ground half dry and half wet): counted.
    if ((kind.resolve || kind.sun || kind.lamp) && gbuffer_seen && !edit_tried) {
        edit_tried = true;
        if (lamps_pending) {
            stats.edit_pending += tag_frame != 0 ? 1 : 0;
        } else if (!camera_motion.PreviewFrame()) {
            Edit(jitter);
        }
    }
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps) {
        return;
    }
    const auto& k = R::Load();
    const u64 vs_hash = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
    if (!R::Matches(k, vs_hash, ps->pgm_hash)) {
        return;
    }
    const R::DrawShape shape{
        .vs = vs_hash,
        .ps = ps->pgm_hash,
        .indices = u32(regs.num_indices),
        .mrt_mask = mrt,
        .target_rgba16f = bool(targets[0]) &&
                          texture_cache.GetImage(targets[0]).info.pixel_format == SceneFormat,
        .blended = regs.blend_control[0].enable != 0 && regs.color_buffers[0].info.blend_bypass == 0,
        .depth_write = regs.depth_control.depth_enable != 0 &&
                       regs.depth_control.depth_write_enable != 0,
        .scene_depth = bool(depth) && depth == camera_motion.Depth(),
    };
    switch (R::Classify(k, shape)) {
    case R::Verdict::FewIndices:
        ++stats.few_indices;
        return;
    case R::Verdict::OtherShape:
        ++stats.other_shape;
        if (!told_shape) {
            told_shape = true;
            BbReport::Printf("Blood sheen (r100): first named pair draw of another shape (left out): "
                             "%u indices, colour targets 0x%x, target 0 format %u (RGBA16F is 97), "
                             "blended %u, depth write %u, the scene depth %u\n",
                             shape.indices, shape.mrt_mask,
                             targets[0] ? u32(texture_cache.GetImage(targets[0]).info.pixel_format)
                                        : 0u,
                             u32(shape.blended), u32(shape.depth_write), u32(shape.scene_depth));
        }
        return;
    case R::Verdict::Keyed:
        break;
    case R::Verdict::OtherPair:
        return;
    }
    ++stats.keyed;
    last_indices = shape.indices;
    if (!told_state) {
        // bbport (r100b_blood-sheen-mark): how the game draws the pool (a pool drawn flush with the
        // ground relies on its depth function and bias).
        told_state = true;
        const auto& poly = regs.polygon_control;
        BbReport::Printf("Blood sheen (r100): the pool's draw: %u indices, depth func %u (3 LessEqual), "
                         "bias front %u back %u (offsets %.4g %.4g, scales %.4g %.4g, clamp %.4g), "
                         "depth bounds %u, stencil %u, target 0 write mask 0x%x; depth test %s\n",
                         shape.indices, u32(regs.depth_control.depth_func),
                         u32(poly.enable_polygon_offset_front), u32(poly.enable_polygon_offset_back),
                         double(regs.poly_offset.front_offset), double(regs.poly_offset.back_offset),
                         double(regs.poly_offset.front_scale), double(regs.poly_offset.back_scale),
                         double(regs.poly_offset.depth_bias),
                         u32(regs.depth_control.depth_bounds_enable),
                         u32(regs.depth_control.stencil_enable), regs.color_target_mask.GetMask(0),
                         k.depth_off ? "OFF (BB_BLOOD_SHEEN_DEPTH=off, a test)" : "as the game sets it");
    }
    if (++keyed_this_frame > R::MaxPoolDraws) {
        ++stats.over_cap;
        return;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    Snapshot(regs, targets[0], depth, lamps_pending, jitter);
    if (pending.on && k.depth_off) {
        ForceNoDepthTest(regs);
    }
}

void BloodSheen::ForceNoDepthTest(const AmdGpu::Regs& regs) {
    // The draw's own UpdateDynamicState sets the game's op into this cache; with the cache already
    // holding it and nothing dirty, it records nothing, and the Always recorded here stays in force
    // for the draw (a command buffer change in between re-commits everything: then it does not).
    auto& state = scheduler.GetDynamicState();
    state.depth_compare_op = LiverpoolToVK::CompareOp(regs.depth_control.depth_func);
    state.dirty_state.depth_compare_op = false;
    scheduler.Record([](vk::CommandBuffer cmd) { cmd.setDepthCompareOp(vk::CompareOp::eAlways); });
    depth_forced = true;
    ++stats.depth_off;
}

void BloodSheen::RestoreDepthTest() {
    if (!std::exchange(depth_forced, false)) {
        return;
    }
    // What the cache holds now is what the next draw takes as recorded.
    scheduler.Record([op = scheduler.GetDynamicState().depth_compare_op](vk::CommandBuffer cmd) {
        cmd.setDepthCompareOp(op);
    });
}

void BloodSheen::Edit(std::array<float, 2> jitter) {
    // The tag of the frame right before this one, on a scene of this size, and both cameras.
    if (tag_frame == 0) {
        return; // no pool in the frame before: nothing to make wet
    }
    // (Not used up here: every G-buffer pass of the frame, a planar reflection's too, gets it; the
    // next SNAPSHOT replaces it.)
    const bool tag_fits = tag_frame == frame;
    if (!tag_fits) {
        tag_frame = 0; // older than the frame before: said once
    }
    const auto camera = camera_motion.PassMatrices();
    if (!tag_image || !tag_fits || !camera.valid || camera.proj[0] == 0.0f ||
        camera.proj[1] == 0.0f || tag_proj[0] == 0.0f || tag_proj[1] == 0.0f) {
        ++stats.no_tag;
        return;
    }
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth() || !gbuffer_material ||
        !gbuffer_specular) {
        ++stats.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(gbuffer_depth, width, height, reduced) || width != tag_width ||
        height != tag_height || reduced != tag_reduced) {
        ++stats.no_tag;
        return;
    }
    // Targets 1 and 3 must be RGBA8 (the shader's rgba8 images) and stand where the depth does.
    for (const auto id : {gbuffer_material, gbuffer_specular}) {
        const auto& image = texture_cache.GetImage(id);
        const bool fits = image.info.pixel_format == GbufferFormat &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == reduced &&
                          image.info.size.width >= (reduced ? 1u : width) &&
                          image.info.size.height >= (reduced ? 1u : height);
        if (!fits) {
            ++stats.cannot;
            if (!told_unfit) {
                told_unfit = true;
                BbReport::Printf("Blood sheen (r100): wet ground left out (first time): G-buffer "
                                 "target 1 format %u, target 3 format %u, %ux%u (the pass writes "
                                 "R8G8B8A8_UNORM, 37, on a %ux%u scene)\n",
                                 u32(texture_cache.GetImage(gbuffer_material).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_specular).info.pixel_format),
                                 image.info.size.width, image.info.size.height, width, height);
            }
            return;
        }
    }
    if (!Ready()) {
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView depth_view = ViewOf(gbuffer_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    const vk::ImageView material_view =
        ViewOf(gbuffer_material, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView specular_view =
        ViewOf(gbuffer_specular, vk::ImageAspectFlagBits::eColor, true, true);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!depth_view || !material_view || !specular_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.reproject = R::Multiply(tag_view_matrix, camera.inv_view);
    push.proj = camera.proj;
    push.prev_proj = tag_proj;
    push.size = {float(width), float(height)};
    push.jitter = jitter;
    push.prev_jitter = tag_jitter;
    push.strength = k.strength;
    push.flags = R::Flags(k, false, false, step.slot);
    ++stats.edits;
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen wet ground"},
        [push, step, width, height, depth_view, material_view, specular_view, tag = *tag_view,
         counter_buffer = counters.buffer, host = readback.buffer, pipeline = *edit_pass.pipeline,
         layout = *edit_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(depth_view), Info(tag), Info(material_view),
                                   Info(specular_view)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]),
                                    ImageWrite(3, eStorageImage, &infos[3]),
                                    BufferWrite(4, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
}

void BloodSheen::Snapshot(const AmdGpu::Regs& regs, VideoCore::ImageId color,
                          VideoCore::ImageId depth, bool lamps_pending,
                          std::array<float, 2> jitter) {
    // Lamps apart (vk_point_shadow.h): a batch still open has its lamp light outside the light
    // target, so GLINT would read it without its lamps.
    if (lamps_pending) {
        ++stats.lamps_pending;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(color, width, height, reduced)) {
        ++stats.cannot;
        return;
    }
    const auto& depth_image = texture_cache.GetImage(depth);
    if ((scene_targets.Reduced() && scene_targets.EligibleScene(depth_image)) != reduced ||
        (!reduced && (depth_image.info.size.width < width || depth_image.info.size.height < height))) {
        ++stats.cannot;
        return;
    }
    if (!Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView color_view = ViewOf(color, vk::ImageAspectFlagBits::eColor, true, false);
    const vk::ImageView depth_view = ViewOf(depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view || !depth_view) {
        ++stats.cannot;
        return;
    }
    using Factor = AmdGpu::BlendControl::BlendFactor;
    const auto& blend = regs.blend_control[0];
    // The draw's alpha blend One/Zero with Add: the scene's alpha after it is the draw's own alpha,
    // its coverage of the pixel.
    const bool alpha_coverage = blend.separate_alpha_blend != 0 &&
                                blend.alpha_func == AmdGpu::BlendControl::BlendFunc::Add &&
                                blend.alpha_src_factor == Factor::One &&
                                blend.alpha_dst_factor == Factor::Zero;
    const bool has_light = light && !light_stale;
    if (!has_light && light) {
        ++stats.light_stale;
    } else if (!has_light) {
        ++stats.no_light;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.size = {float(width), float(height)};
    push.flags = R::Flags(k, false, false, step.slot);
    tag_frame = 0; // the prints take the tag's place
    const bool fresh = std::exchange(tag_fresh, false);
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen snapshot"},
        [push, step, fresh, width, height, color_view, depth_view, tag_handle = vk::Image(tag_image),
         before_handle = vk::Image(before_image), tag = *tag_view, before = *before_view,
         counter_buffer = counters.buffer, host = readback.buffer,
         pipeline = *snapshot_pass.pipeline, layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
                EffectPass::InitGeneral(cmd, before_handle, ColorLevel);
            }
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(tag), Info(depth_view), Info(before)};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eSampledImage, &infos[2]),
                                    ImageWrite(3, eStorageImage, &infos[3])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
    pending = {.on = true,
               .color = color,
               .depth = depth,
               .width = width,
               .height = height,
               .reduced = reduced,
               .alpha_coverage = alpha_coverage,
               .light = has_light,
               .jitter = jitter};
}

void BloodSheen::AfterDraw() {
    if (pending.on) {
        Glint();
    }
}

void BloodSheen::TakeLight(VideoCore::ImageId id, u64 address) {
    light = id;
    light_uid = texture_cache.GetImage(id).image_uid;
    light_address = address;
    light_stale = false;
}

void BloodSheen::Glint() {
    RestoreDepthTest(); // (the pool's draw is recorded: its depth test back for the next draws)
    const Pending p = pending;
    pending = {};
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView color_view = ViewOf(p.color, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(p.depth, vk::ImageAspectFlagBits::eDepth, false, false);
    vk::ImageView light_view{};
    if (p.light) {
        // The light target must stand where the scene does (the same proxying, at least its size).
        const auto& image = texture_cache.GetImage(light);
        const bool fits = image.image_uid == light_uid &&
                          (image.aspect_mask & vk::ImageAspectFlagBits::eColor) &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == p.reduced &&
                          (p.reduced || (image.info.size.width >= p.width &&
                                         image.info.size.height >= p.height));
        light_view = fits ? ViewOf(light, vk::ImageAspectFlagBits::eColor, false, false)
                          : vk::ImageView{};
        if (!light_view) {
            ++stats.no_light;
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view || !depth_view) {
        ++stats.cannot;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.proj = camera.proj;
    push.size = {float(p.width), float(p.height)};
    push.jitter = p.jitter;
    push.strength = k.strength;
    push.flags = R::Flags(k, p.alpha_coverage, bool(light_view), step.slot);
    ++stats.glints;
    if (!told_first) {
        told_first = true;
        BbReport::Printf("Blood sheen (r100): first pool draw at frame %llu, %ux%u (%s), coverage "
                         "from %s, specular light target %s\n",
                         static_cast<unsigned long long>(frame), p.width, p.height,
                         p.reduced ? "reduced scene" : "the game's scene",
                         p.alpha_coverage ? "the draw's alpha" : "1 (its alpha blend is not One/Zero Add)",
                         light_view ? "found" : "not found (no glint)");
    }
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen glint"},
        [push, step, width = p.width, height = p.height, color_view, depth_view,
         light_or_depth = light_view ? light_view : depth_view, tag = *tag_view,
         before = *before_view, counter_buffer = counters.buffer, host = readback.buffer,
         pipeline = *glint_pass.pipeline, layout = *glint_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(tag), Info(depth_view),
                                   Info(light_or_depth), Info(before)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eSampledImage, &infos[2]),
                                    ImageWrite(3, eSampledImage, &infos[3]),
                                    BufferWrite(4, &counter_info),
                                    ImageWrite(5, eStorageImage, &infos[4])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
    // The tag for the next frame's EDIT: this frame's camera (world to view) and jitter.
    if (camera.valid && camera.proj[0] != 0.0f && camera.proj[1] != 0.0f) {
        tag_frame = frame + 1;
        tag_view_matrix = camera.view;
        tag_proj = camera.proj;
        tag_jitter = p.jitter;
        tag_reduced = p.reduced;
    }
}

void BloodSheen::OnFrameEnd() {
    RestoreDepthTest();
    if (keyed_this_frame != 0) {
        ++stats.keyed_frames;
        stats.twice += keyed_this_frame > 1 ? 1 : 0;
    }
    keyed_this_frame = 0;
    pending = {};
    gbuffer_seen = edit_tried = light_stale = false;
    gbuffer_depth = gbuffer_material = gbuffer_specular = light = {};
    light_uid = light_address = 0;
    ++frame;
    if (++stats.frames < LineFrames) {
        return;
    }
    // The host copy of the last frame with a pass whose next frame had one too (no fence is
    // waited for: a log line).
    std::array<u32, R::SlotWords> c{};
    if (readback.mapped) {
        std::memcpy(c.data(), readback.mapped, sizeof(c));
    }
    BbReport::Printf("Blood sheen (r100): %u frames, %u with the pool (%u draws; %u frames with more "
                     "than one, %u draws over the cap of %u a frame), %u glint and %u wet ground "
                     "passes; pair draws left out: %u under %u indices, %u of another shape; %u in "
                     "menu previews\n",
                     stats.frames, stats.keyed_frames, stats.keyed, stats.twice, stats.over_cap,
                     R::MaxPoolDraws, stats.glints, stats.edits, stats.few_indices, R::MinIndices,
                     stats.other_shape, stats.previews);
    BbReport::Printf("Blood sheen (r100): recent frame: %u pool pixels, %u lit, %u ground pixels wet, "
                     "%u tags found; skipped: %u no light target, %u light target drawn over, %u "
                     "lamps pending, %u wet ground lamps open, %u no tag, %u no room, %u unfit%s\n",
                     c[R::WordPool], c[R::WordLit], c[R::WordWet], c[R::WordTags], stats.no_light,
                     stats.light_stale, stats.lamps_pending, stats.edit_pending, stats.no_tag,
                     stats.no_room, stats.cannot, failed ? " (off after a failure)" : "");
    // bbport (r100b_blood-sheen-mark): what the draw changed in that frame, each test on its own.
    const R::Box box = R::DecodeBox(c);
    char where[48] = "none";
    if (box.any) {
        std::snprintf(where, sizeof(where), "x %u-%u y %u-%u", box.x0, box.x1, box.y0, box.y1);
    }
    const u32 with_alpha = c[R::WordColourAlpha];
    BbReport::Printf("Blood sheen (r100): recent frame's draw (%u indices, depth test %s %u of %u): "
                     "colour changed %u (%u with alpha, mean %.2f), depth changed %u (%u without "
                     "alpha; %u nearer, %u behind under 2 cm + 1%%, %u behind more); box %s\n",
                     last_indices, R::Load().depth_off ? "off" : "on", stats.depth_off, stats.keyed,
                     c[R::WordColour], with_alpha,
                     with_alpha != 0 ? double(c[R::WordAlphaSum]) / (255.0 * double(with_alpha)) : 0.0,
                     c[R::WordDepth], c[R::WordDepthOnly], c[R::WordNearer], c[R::WordHair],
                     c[R::WordBehind], where);
    stats = {};
}

} // namespace Vulkan
'''),
'engine/tests/test_blood_sheen.cpp': (
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): the blood sheen's knobs, draw key and reprojection (blood_sheen.h).
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target blood-sheen-test.
#undef NDEBUG
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/blood_sheen.h"

using namespace Vulkan::BloodSheenRules;

namespace {
bool Near(double a, double b, double eps = 1e-5) {
    return std::abs(a - b) <= eps;
}

DrawShape Pool() {
    return DrawShape{.vs = DefaultVs,
                     .ps = DefaultPs,
                     .indices = 1266,
                     .mrt_mask = 1u,
                     .target_rgba16f = true,
                     .blended = true,
                     .depth_write = true,
                     .scene_depth = true};
}

/// A 3x4 rotation about y by `a` radians with a translation.
std::array<float, 12> Pose(float a, float x, float y, float z) {
    const float c = std::cos(a), s = std::sin(a);
    return {c, 0.0f, s, x, 0.0f, 1.0f, 0.0f, y, -s, 0.0f, c, z};
}

std::array<float, 3> Apply(const std::array<float, 12>& m, std::array<float, 3> p) {
    return {m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
            m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]};
}
} // namespace

int main() {
    // a. BB_BLOOD_SHEEN: off unless a strength above 0 or "show"; numbers put into 0.25..4.
    assert(ReadStrength(nullptr).strength == 0.0f);
    assert(ReadStrength("").strength == 0.0f);
    assert(ReadStrength("0").strength == 0.0f);
    assert(ReadStrength("-1").strength == 0.0f);
    assert(ReadStrength("yes").strength == 0.0f);
    assert(ReadStrength("1x").strength == 0.0f);
    assert(ReadStrength("nan").strength == 0.0f);
    assert(ReadStrength("1").strength == 1.0f && !ReadStrength("1").show);
    assert(ReadStrength(" 2 ").strength == 2.0f);
    assert(ReadStrength("0.1").strength == MinStrength);
    assert(ReadStrength("9").strength == MaxStrength);
    assert(ReadStrength("0.5").strength == 0.5f);
    const Knobs show = ReadStrength("show");
    assert(show.strength == 1.0f && show.show);
    assert(ReadStrength("shows").strength == 0.0f);
    assert(ReadStrength("sh").strength == 0.0f);

    // b. BB_BLOOD_SHEEN_PAIRS: the default pair unless readable pairs are named.
    {
        const Knobs d = Read("1", nullptr);
        assert(d.pair_count == 1 && !d.pairs_named && d.pairs_bad == 0);
        assert(d.pairs[0].vs == 0x1ea84d9aull && d.pairs[0].ps == 0xbd1d09f0ull);
        assert(Matches(d, 0x1ea84d9a, 0xbd1d09f0) && !Matches(d, 0x4900bbbf, 0xbd1d09f0));
        const Knobs two = Read("1", "0x11:22;AbCdEf01:0x00000003 , 4:5");
        assert(two.pairs_named && two.pair_count == 3 && two.pairs_bad == 0);
        assert(two.pairs[0].vs == 0x11 && two.pairs[0].ps == 0x22);
        assert(two.pairs[1].vs == 0xabcdef01ull && two.pairs[1].ps == 3);
        assert(two.pairs[2].vs == 4 && two.pairs[2].ps == 5);
        assert(!Matches(two, DefaultVs, DefaultPs));
        const Knobs bad = Read("1", "zz:1;12");
        assert(!bad.pairs_named && bad.pair_count == 1 && bad.pairs_bad == 2);
        assert(bad.pairs[0].vs == DefaultVs);
        const Knobs part = Read("1", "1:2;x:3");
        assert(part.pairs_named && part.pair_count == 1 && part.pairs_bad == 1);
        const Knobs many = Read("1", "1:1;2:2;3:3;4:4;5:5;6:6;7:7;8:8;9:9");
        assert(many.pair_count == MaxPairs && many.pairs_bad == 1);
        assert(Read("1", "").pair_count == 1 && !Read("1", " ; ").pairs_named);
        assert(Read("1", "12345678901234567:1").pairs_bad == 1); // 17 digits
    }

    // c. The key: the pool is keyed; the Dream house quads (12 indices) and other shapes are not.
    {
        static_assert(MaxPoolDraws >= 1 && MaxPoolDraws <= 4); // the cost bound in README.md
        const Knobs k = Read("1", nullptr);
        assert(Classify(k, Pool()) == Verdict::Keyed);
        DrawShape quad = Pool();
        quad.indices = 12;
        assert(Classify(k, quad) == Verdict::FewIndices);
        quad.indices = MinIndices - 1;
        assert(Classify(k, quad) == Verdict::FewIndices);
        quad.indices = MinIndices;
        assert(Classify(k, quad) == Verdict::Keyed);
        DrawShape other = Pool();
        other.ps = 0x12345678;
        assert(Classify(k, other) == Verdict::OtherPair);
        other = Pool();
        other.vs = 0x4900bbbf; // church-puddles: the pixel shader with another vertex shader
        assert(Classify(k, other) == Verdict::OtherPair);
        for (int i = 0; i < 5; ++i) {
            DrawShape s = Pool();
            if (i == 0) s.mrt_mask = 3u;
            if (i == 1) s.target_rgba16f = false;
            if (i == 2) s.blended = false;
            if (i == 3) s.depth_write = false;
            if (i == 4) s.scene_depth = false;
            assert(Classify(k, s) == Verdict::OtherShape);
        }
    }

    // d. The reprojection: (tag view) * (this frame's inverse view) takes a point seen now to where
    // the tag's camera saw it.
    {
        const auto world_to_old = Pose(0.3f, 1.0f, -2.0f, 0.5f);
        const auto world_to_new = Pose(-0.2f, 0.4f, 1.5f, -3.0f);
        // The inverse of world_to_new: the rotation's transpose, then -R^T t.
        std::array<float, 12> inverse{};
        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                inverse[i * 4 + j] = world_to_new[j * 4 + i];
            }
        }
        for (int i = 0; i < 3; ++i) {
            inverse[i * 4 + 3] = -(inverse[i * 4 + 0] * world_to_new[3] +
                                   inverse[i * 4 + 1] * world_to_new[7] +
                                   inverse[i * 4 + 2] * world_to_new[11]);
        }
        const auto reproject = Multiply(world_to_old, inverse);
        const std::array<float, 3> world{2.0f, -1.0f, 7.0f};
        const auto seen_now = Apply(world_to_new, world);
        const auto seen_then = Apply(world_to_old, world);
        const auto carried = Apply(reproject, seen_now);
        for (int i = 0; i < 3; ++i) {
            assert(Near(carried[i], seen_then[i], 1e-4));
        }
        // The identity changes nothing.
        const std::array<float, 12> one{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        assert(Multiply(one, world_to_old) == world_to_old && Multiply(world_to_old, one) == world_to_old);
    }

    // e. The push block and the flags as the shader reads them.
    {
        static_assert(sizeof(Push) == 28 * 4);
        static_assert(offsetof(Push, proj) == 48 && offsetof(Push, prev_proj) == 64);
        static_assert(offsetof(Push, size) == 80 && offsetof(Push, jitter) == 88);
        static_assert(offsetof(Push, prev_jitter) == 96 && offsetof(Push, strength) == 104);
        static_assert(offsetof(Push, flags) == 108);
        const Knobs k = Read("show", nullptr);
        assert(Flags(k, true, true, 1) == (FlagShow | FlagAlphaCoverage | FlagLight | FlagSlot));
        assert(Flags(Read("1", nullptr), false, false, 2) == 0u);
        assert(Flags(Read("1", nullptr), false, true, 3) == (FlagLight | FlagSlot));
    }

    std::puts("blood sheen: ok");
    return 0;
}
''',
r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100_blood-sheen): the blood sheen's knobs, draw key and reprojection (blood_sheen.h).
// bbport (r100b_blood-sheen-mark): BB_BLOOD_SHEEN_DEPTH and the counter words' box.
// Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target blood-sheen-test.
#undef NDEBUG
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/blood_sheen.h"

using namespace Vulkan::BloodSheenRules;

namespace {
bool Near(double a, double b, double eps = 1e-5) {
    return std::abs(a - b) <= eps;
}

DrawShape Pool() {
    return DrawShape{.vs = DefaultVs,
                     .ps = DefaultPs,
                     .indices = 1266,
                     .mrt_mask = 1u,
                     .target_rgba16f = true,
                     .blended = true,
                     .depth_write = true,
                     .scene_depth = true};
}

/// A 3x4 rotation about y by `a` radians with a translation.
std::array<float, 12> Pose(float a, float x, float y, float z) {
    const float c = std::cos(a), s = std::sin(a);
    return {c, 0.0f, s, x, 0.0f, 1.0f, 0.0f, y, -s, 0.0f, c, z};
}

std::array<float, 3> Apply(const std::array<float, 12>& m, std::array<float, 3> p) {
    return {m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
            m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11]};
}
} // namespace

int main() {
    // a. BB_BLOOD_SHEEN: off unless a strength above 0 or "show"; numbers put into 0.25..4.
    assert(ReadStrength(nullptr).strength == 0.0f);
    assert(ReadStrength("").strength == 0.0f);
    assert(ReadStrength("0").strength == 0.0f);
    assert(ReadStrength("-1").strength == 0.0f);
    assert(ReadStrength("yes").strength == 0.0f);
    assert(ReadStrength("1x").strength == 0.0f);
    assert(ReadStrength("nan").strength == 0.0f);
    assert(ReadStrength("1").strength == 1.0f && !ReadStrength("1").show);
    assert(ReadStrength(" 2 ").strength == 2.0f);
    assert(ReadStrength("0.1").strength == MinStrength);
    assert(ReadStrength("9").strength == MaxStrength);
    assert(ReadStrength("0.5").strength == 0.5f);
    const Knobs show = ReadStrength("show");
    assert(show.strength == 1.0f && show.show);
    assert(ReadStrength("shows").strength == 0.0f);
    assert(ReadStrength("sh").strength == 0.0f);

    // b. BB_BLOOD_SHEEN_PAIRS: the default pair unless readable pairs are named.
    {
        const Knobs d = Read("1", nullptr);
        assert(d.pair_count == 1 && !d.pairs_named && d.pairs_bad == 0);
        assert(d.pairs[0].vs == 0x1ea84d9aull && d.pairs[0].ps == 0xbd1d09f0ull);
        assert(Matches(d, 0x1ea84d9a, 0xbd1d09f0) && !Matches(d, 0x4900bbbf, 0xbd1d09f0));
        const Knobs two = Read("1", "0x11:22;AbCdEf01:0x00000003 , 4:5");
        assert(two.pairs_named && two.pair_count == 3 && two.pairs_bad == 0);
        assert(two.pairs[0].vs == 0x11 && two.pairs[0].ps == 0x22);
        assert(two.pairs[1].vs == 0xabcdef01ull && two.pairs[1].ps == 3);
        assert(two.pairs[2].vs == 4 && two.pairs[2].ps == 5);
        assert(!Matches(two, DefaultVs, DefaultPs));
        const Knobs bad = Read("1", "zz:1;12");
        assert(!bad.pairs_named && bad.pair_count == 1 && bad.pairs_bad == 2);
        assert(bad.pairs[0].vs == DefaultVs);
        const Knobs part = Read("1", "1:2;x:3");
        assert(part.pairs_named && part.pair_count == 1 && part.pairs_bad == 1);
        const Knobs many = Read("1", "1:1;2:2;3:3;4:4;5:5;6:6;7:7;8:8;9:9");
        assert(many.pair_count == MaxPairs && many.pairs_bad == 1);
        assert(Read("1", "").pair_count == 1 && !Read("1", " ; ").pairs_named);
        assert(Read("1", "12345678901234567:1").pairs_bad == 1); // 17 digits
    }

    // c. The key: the pool is keyed; the Dream house quads (12 indices) and other shapes are not.
    {
        static_assert(MaxPoolDraws >= 1 && MaxPoolDraws <= 4); // the cost bound in README.md
        const Knobs k = Read("1", nullptr);
        assert(Classify(k, Pool()) == Verdict::Keyed);
        DrawShape quad = Pool();
        quad.indices = 12;
        assert(Classify(k, quad) == Verdict::FewIndices);
        quad.indices = MinIndices - 1;
        assert(Classify(k, quad) == Verdict::FewIndices);
        quad.indices = MinIndices;
        assert(Classify(k, quad) == Verdict::Keyed);
        DrawShape other = Pool();
        other.ps = 0x12345678;
        assert(Classify(k, other) == Verdict::OtherPair);
        other = Pool();
        other.vs = 0x4900bbbf; // church-puddles: the pixel shader with another vertex shader
        assert(Classify(k, other) == Verdict::OtherPair);
        for (int i = 0; i < 5; ++i) {
            DrawShape s = Pool();
            if (i == 0) s.mrt_mask = 3u;
            if (i == 1) s.target_rgba16f = false;
            if (i == 2) s.blended = false;
            if (i == 3) s.depth_write = false;
            if (i == 4) s.scene_depth = false;
            assert(Classify(k, s) == Verdict::OtherShape);
        }
    }

    // d. The reprojection: (tag view) * (this frame's inverse view) takes a point seen now to where
    // the tag's camera saw it.
    {
        const auto world_to_old = Pose(0.3f, 1.0f, -2.0f, 0.5f);
        const auto world_to_new = Pose(-0.2f, 0.4f, 1.5f, -3.0f);
        // The inverse of world_to_new: the rotation's transpose, then -R^T t.
        std::array<float, 12> inverse{};
        for (int i = 0; i < 3; ++i) {
            for (int j = 0; j < 3; ++j) {
                inverse[i * 4 + j] = world_to_new[j * 4 + i];
            }
        }
        for (int i = 0; i < 3; ++i) {
            inverse[i * 4 + 3] = -(inverse[i * 4 + 0] * world_to_new[3] +
                                   inverse[i * 4 + 1] * world_to_new[7] +
                                   inverse[i * 4 + 2] * world_to_new[11]);
        }
        const auto reproject = Multiply(world_to_old, inverse);
        const std::array<float, 3> world{2.0f, -1.0f, 7.0f};
        const auto seen_now = Apply(world_to_new, world);
        const auto seen_then = Apply(world_to_old, world);
        const auto carried = Apply(reproject, seen_now);
        for (int i = 0; i < 3; ++i) {
            assert(Near(carried[i], seen_then[i], 1e-4));
        }
        // The identity changes nothing.
        const std::array<float, 12> one{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        assert(Multiply(one, world_to_old) == world_to_old && Multiply(world_to_old, one) == world_to_old);
    }

    // e. The push block and the flags as the shader reads them.
    {
        static_assert(sizeof(Push) == 28 * 4);
        static_assert(offsetof(Push, proj) == 48 && offsetof(Push, prev_proj) == 64);
        static_assert(offsetof(Push, size) == 80 && offsetof(Push, jitter) == 88);
        static_assert(offsetof(Push, prev_jitter) == 96 && offsetof(Push, strength) == 104);
        static_assert(offsetof(Push, flags) == 108);
        const Knobs k = Read("show", nullptr);
        assert(Flags(k, true, true, 1) == (FlagShow | FlagAlphaCoverage | FlagLight | FlagSlot));
        assert(Flags(Read("1", nullptr), false, false, 2) == 0u);
        assert(Flags(Read("1", nullptr), false, true, 3) == (FlagLight | FlagSlot));
    }

    // f. bbport (r100b_blood-sheen-mark): BB_BLOOD_SHEEN_DEPTH is a test only with "off".
    {
        assert(!ReadDepthOff(nullptr) && !ReadDepthOff("") && !ReadDepthOff("0"));
        assert(ReadDepthOff("off") && ReadDepthOff(" off ") && !ReadDepthOff("of"));
        assert(!ReadDepthOff("offf") && !ReadDepthOff("OFF") && !ReadDepthOff("off 1"));
        assert(!Read("show", nullptr).depth_off); // only Load() reads the depth knob
    }

    // g. The counter words: sums first, then the box as maxima of 65535 - least and largest + 1.
    {
        static_assert(SlotWords == 16 && WordBoxMinX == 12);
        std::array<std::uint32_t, SlotWords> c{};
        assert(!DecodeBox(c).any);
        // Pixels (5, 7) and (1919, 1079) changed: what the shader's maxima leave.
        const std::uint32_t xs[2] = {5, 1919}, ys[2] = {7, 1079};
        for (int i = 0; i < 2; ++i) {
            c[WordBoxMinX] = std::max(c[WordBoxMinX], 65535u - xs[i]);
            c[WordBoxMinY] = std::max(c[WordBoxMinY], 65535u - ys[i]);
            c[WordBoxMaxX] = std::max(c[WordBoxMaxX], xs[i] + 1u);
            c[WordBoxMaxY] = std::max(c[WordBoxMaxY], ys[i] + 1u);
        }
        const Box b = DecodeBox(c);
        assert(b.any && b.x0 == 5 && b.y0 == 7 && b.x1 == 1919 && b.y1 == 1079);
        // One pixel at the origin.
        std::array<std::uint32_t, SlotWords> one{};
        one[WordBoxMinX] = one[WordBoxMinY] = 65535u;
        one[WordBoxMaxX] = one[WordBoxMaxY] = 1u;
        const Box o = DecodeBox(one);
        assert(o.any && o.x0 == 0 && o.y0 == 0 && o.x1 == 0 && o.y1 == 0);
        // A slot copied before any pass of its frame (box words 0) has no box.
        std::array<std::uint32_t, SlotWords> half{};
        half[WordBoxMaxX] = 3u;
        assert(!DecodeBox(half).any);
    }

    std::puts("blood sheen: ok");
    return 0;
}
'''),
}

# Replacements of r100's own text in shared files: (r100's, r100b's), each found once.
EDITS = {
PIPES: [(r'''        {"blood sheen snapshot", BLOOD_SHEEN_SNAPSHOT_COMP, {eStorageImage, eStorageImage}, 112},
        {"blood sheen glint",
         BLOOD_SHEEN_GLINT_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eSampledImage, eStorageBuffer},
         112},
''',
r'''        // bbport (r100b_blood-sheen-mark): + the depth before the draw (snapshot 2 and 3, glint 5)
        {"blood sheen snapshot",
         BLOOD_SHEEN_SNAPSHOT_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eStorageImage},
         112},
        {"blood sheen glint",
         BLOOD_SHEEN_GLINT_COMP,
         {eStorageImage, eStorageImage, eSampledImage, eSampledImage, eStorageBuffer,
          eStorageImage},
         112},
''')],
README: [(r'''### Blood sheen (in development)

The game draws the blood pool beside a body (the graveyard) after its own lighting, so none of its lamps (the hunter's lantern, torches, street lamps) ever shines on the pool while they light the ground around it. With `BB_BLOOD_SHEEN` the engine lays the game's own specular light over the pool. In the frame after a pool was drawn, right before the first light draw after each G-buffer pass (the sun's shadow resolve, the sun or moon, or a lamp of the light grid, whichever comes first), the ground where the pool lay (the pool's pixels of that frame carried to this frame with both cameras, where the ground's depth is within 5 cm plus 3% of the distance of the pool's) gets a wet film's gloss and specular colour in the game's G-buffer (gloss raised toward 0.66, specular colour toward f0 0.04, by the pool's coverage; never lowered). The game's sun or moon (shadowed as the game shadows it, ray traced when the ray traced sun is on) and every lamp of its light grid (each with the engine's ray traced lamp shadow when lamp shadows are on) then put a sharp highlight into the game's specular light. Right after the pool's draw, every pixel that draw changed gets that specular light added, times the pool's coverage (the alpha it drew, when its alpha blend replaces the scene's alpha; else 1) and the strength. So the pool glints only where light reaches it (nothing in the dark), and a surface in front of the pool, such as the hunter standing in it, gets no glint (the pool's draw does not change its pixels); the wet ground is only where the depth matches last frame's pool, so at most a thin edge of a moving body can catch it. Not in the glint: the pool's own directional lights (already in its shading), reflections, bounced light and fog. The ground is not made wet while a lamps-apart batch is still open at that first light draw (counted in the log); the glint is not added when no specular light target was seen in the frame or something other than more light was drawn into its memory after it (counted). At most 2 such draws a frame get the passes (the pixel shader is the game's generic forward material; further ones are counted). It needs the upscaler's camera (the engine's default; with `BB_UPSCALER=none` the pool's draw does not match the scene depth and is counted as another shape). A menu's 3D preview is left alone. These environment variables are read once when the game starts; they are for testing, no ini key yet. When on, the session log has lines starting with `Blood sheen (r100`: the knobs at the start, the first pool, the first left-out draw of another shape and the first unfit wet ground (with what did not fit), and every 600 frames the frames and draws with the pool, the draws over the cap, the left-out draws of the named pairs (fewer than 64 indices: the Hunter's Dream house draws 12-index quads with the same shaders; another shape), the passes, the reasons for skipping, and a recent frame's pool pixels, lit pool pixels, wet ground pixels and tags found.

| Variable | What it does | Default |
|---|---|---|
| `BB_BLOOD_SHEEN` | `1`: on, strength 1; a number: the strength, put into 0.25 to 4 (the share of the specular light under the pool that is added over it); `show`: strength 1 and the pool's pixels painted half cyan (as bright as the pixel), a test view of what is taken for the pool. Unset, empty, `0`, a negative number or other text: off, and nothing of it is made. A draw is taken for the pool when its vertex and pixel shader pair is named (`BB_BLOOD_SHEEN_PAIRS`), it has at least 64 indices, writes one colour target (RGBA16F) with blending on, and tests and writes the scene's depth (the G-buffer pass's). Cost: an estimate of 0.1 to 0.2 ms at 1080p internal for each pool draw (at most 2 a frame; two passes over the scene around the draw and the wet-ground pass in the next frame's lighting, each ends the game's render pass), about four times that at 2160p internal, not measured; nothing on a frame without the pool except the wet-ground pass (once for each G-buffer pass) in the frame right after one. Memory: one 4-byte image of the scene's size (8.3 MB at 1080p internal), made at the first pool. It is the `Lighting: blood sheen` row of `BB_GPU_PROFILE=1` | off |
| `BB_BLOOD_SHEEN_PAIRS` | The draws taken for the pool: `vs:ps` pairs of hex shader hashes (`0x` optional), at most 8, separated by `;`, `,` or spaces. Text without a readable pair keeps the default (the log says so) | `1ea84d9a:bd1d09f0` |

''',
r'''### Blood sheen (in development)

The game draws the blood pool beside a body (the graveyard) after its own lighting, so none of its lamps (the hunter's lantern, torches, street lamps) ever shines on the pool while they light the ground around it. With `BB_BLOOD_SHEEN` the engine lays the game's own specular light over the pool. In the frame after a pool was drawn, right before the first light draw after each G-buffer pass (the sun's shadow resolve, the sun or moon, or a lamp of the light grid, whichever comes first), the ground where the pool lay (the pool's pixels of that frame carried to this frame with both cameras, where the ground's depth is within 5 cm plus 3% of the distance of the pool's) gets a wet film's gloss and specular colour in the game's G-buffer (gloss raised toward 0.66, specular colour toward f0 0.04, by the pool's coverage; never lowered). The game's sun or moon (shadowed as the game shadows it, ray traced when the ray traced sun is on) and every lamp of its light grid (each with the engine's ray traced lamp shadow when lamp shadows are on) then put a sharp highlight into the game's specular light. Right after the pool's draw, every pixel where that draw changed the colour with an alpha above 0, or wrote its depth, gets that specular light added, times the pool's coverage (the alpha it drew, when its alpha blend replaces the scene's alpha, else 1; 1 where it wrote its depth without an alpha above 0) and the strength. So the pool glints only where light reaches it (nothing in the dark), and a surface in front of the pool, such as the hunter standing in it, gets no glint (the pool's draw neither changes its colour nor writes its depth there); the wet ground is only where the depth matches last frame's pool, so at most a thin edge of a moving body can catch it. Not in the glint: the pool's own directional lights (already in its shading), reflections, bounced light and fog. The ground is not made wet while a lamps-apart batch is still open at that first light draw (counted in the log); the glint is not added when no specular light target was seen in the frame or something other than more light was drawn into its memory after it (counted). At most 2 such draws a frame get the passes (the pixel shader is the game's generic forward material; further ones are counted). It needs the upscaler's camera (the engine's default; with `BB_UPSCALER=none` the pool's draw does not match the scene depth and is counted as another shape). A menu's 3D preview is left alone. These environment variables are read once when the game starts; they are for testing, no ini key yet. When on, the session log has lines starting with `Blood sheen (r100`: the knobs at the start, how the game draws the first pool (index count, depth function, depth bias, depth bounds and stencil tests, colour write mask, and whether `BB_BLOOD_SHEEN_DEPTH=off` turned its depth test off), the first pool, the first left-out draw of another shape and the first unfit wet ground (with what did not fit), and every 600 frames the frames and draws with the pool, the draws over the cap, the left-out draws of the named pairs (fewer than 64 indices: the Hunter's Dream house draws 12-index quads with the same shaders; another shape), the passes, the reasons for skipping, a recent frame's pool pixels, lit pool pixels, wet ground pixels and tags found, and what that frame's pool draw changed, each test on its own: its index count, its depth test on or off, the pixels whose colour it changed (those with an alpha above 0 after it, and their mean alpha), the pixels whose depth it wrote (those without an alpha above 0; nearer than the depth before it, behind it by up to 2 cm plus 1% of the distance, behind it by more) and the box of all the pixels it changed.

| Variable | What it does | Default |
|---|---|---|
| `BB_BLOOD_SHEEN` | `1`: on, strength 1; a number: the strength, put into 0.25 to 4 (the share of the specular light under the pool that is added over it); `show`: strength 1 and a test view of what the pool's draw did, each pixel painted half in a colour (as bright as the pixel, at least 0.1): cyan where it drew with an alpha above 0, magenta where it wrote its depth without an alpha above 0, yellow where it changed the colour (alpha 0) and left the depth, orange where its depth landed behind the depth that was there by up to 2 cm plus 1% of the distance, red where it landed behind by more (orange and red only with `BB_BLOOD_SHEEN_DEPTH=off` or a pool whose depth function lets it); every painted pixel but a yellow one gets the glint. Unset, empty, `0`, a negative number or other text: off, and nothing of it is made. A draw is taken for the pool when its vertex and pixel shader pair is named (`BB_BLOOD_SHEEN_PAIRS`), it has at least 64 indices, writes one colour target (RGBA16F) with blending on, and tests and writes the scene's depth (the G-buffer pass's). Cost: an estimate of 0.1 to 0.25 ms at 1080p internal for each pool draw (at most 2 a frame; two passes over the scene around the draw and the wet-ground pass in the next frame's lighting, each ends the game's render pass), about four times that at 2160p internal, not measured; nothing on a frame without the pool except the wet-ground pass (once for each G-buffer pass) in the frame right after one. Memory: two 4-byte images of the scene's size (16.6 MB at 1080p internal), made at the first pool. It is the `Lighting: blood sheen` row of `BB_GPU_PROFILE=1` | off |
| `BB_BLOOD_SHEEN_PAIRS` | The draws taken for the pool: `vs:ps` pairs of hex shader hashes (`0x` optional), at most 8, separated by `;`, `,` or spaces. Text without a readable pair keeps the default (the log says so) | `1ea84d9a:bd1d09f0` |
| `BB_BLOOD_SHEEN_DEPTH` | A test, only with `BB_BLOOD_SHEEN` on. `off`: the pool's draw runs without its depth test, so it is drawn in front of everything there (the hunter too) and writes its depth there; the test view and the log then show its whole footprint and how far behind the depth that was there it lies. Anything else: the draw as the game sets it | as the game sets it |

''')],
}


ORDER = list(FILES) + list(EDITS)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("REFUSED %s: missing (r100_blood-sheen.fixed.py must be applied first)" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def file_state(path, cur):
    old, new = FILES[path]
    if cur == new:
        return "applied"
    if cur == old:
        return "clean"
    raise SystemExit("REFUSED %s: neither r100's text nor r100b's (another patch changed it?)" % path)


def edit_state(path, cur):
    done = todo = 0
    for old, new in EDITS[path]:
        o, n = cur.count(old), cur.count(new)
        if o == 1 and n == 0:
            todo += 1
        elif o == 0 and n == 1:
            done += 1
        else:
            raise SystemExit("REFUSED %s: r100's text found %d times, r100b's %d times (wanted 1 and 0, "
                             "or 0 and 1): %r" % (path, o, n, old[:70]))
    if done == len(EDITS[path]):
        return "applied"
    if todo == len(EDITS[path]):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(EDITS[path])))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    def need(path, text, n=1):
        if texts[path].count(text) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d"
                             % (path, text, texts[path].count(text), n))
    cpp = RV + "vk_blood_sheen.cpp"
    comp = HS + "blood_sheen.comp"
    lay = HS + "blood_sheen_layout.h"
    hdr = RV + "blood_sheen.h"
    # r100's builds stay as they are (this patch adds no build).
    for build, define in (("snapshot", "BLOOD_SNAPSHOT"), ("glint", "BLOOD_GLINT"), ("edit", "BLOOD_EDIT")):
        need(CMAKE, "add_host_shader(blood_sheen.comp blood_sheen_%s_comp %s=1)\n" % (build, define))
        need(cpp, "BLOOD_SHEEN_%s_COMP" % build.upper())
        need(PIPES, "BLOOD_SHEEN_%s_COMP" % build.upper())
    need(CMAKE, '    if (FILENAME MATCHES "^blood_sheen")\n        list(APPEND INCLUDES ${SHADER_SRC}/blood_sheen_layout.h)\n')
    # The descriptor lists of the C++, the shader and the pipeline test agree, in order.
    need(cpp, "{eStorageImage, eStorageImage, eSampledImage, eStorageImage},\n")
    need(cpp, "{eStorageImage, eStorageImage, eSampledImage, eSampledImage,\n"
              "                            eStorageBuffer, eStorageImage},\n")
    need(cpp, "{eSampledImage, eStorageImage, eStorageImage, eStorageImage,\n"
              "                            eStorageBuffer},\n")
    need(PIPES, "BLOOD_SHEEN_SNAPSHOT_COMP,\n         {eStorageImage, eStorageImage, eSampledImage, "
                "eStorageImage},\n         112},\n")
    need(PIPES, "BLOOD_SHEEN_GLINT_COMP,\n         {eStorageImage, eStorageImage, eSampledImage, "
                "eSampledImage, eStorageBuffer,\n          eStorageImage},\n         112},\n")
    need(PIPES, "BLOOD_SHEEN_EDIT_COMP,\n         {eSampledImage, eStorageImage, eStorageImage, "
                "eStorageImage, eStorageBuffer},\n         112},\n")
    for line in ("layout(binding = 2) uniform texture2D depth_tex;                 // the scene depth before the draw\n",
                 "layout(binding = 3, r32ui) uniform writeonly uimage2D before_img; // its bits\n",
                 "layout(binding = 5, r32ui) uniform readonly uimage2D before_img; // the depth's bits before the draw\n"):
        need(comp, line)
    need(cpp, "ImageWrite(3, eStorageImage, &infos[3])};\n")
    need(cpp, "ImageWrite(5, eStorageImage, &infos[4])};\n")
    # The counter words and numbers, shared and stated.
    need(lay, "#define BLOOD_SHEEN_SLOT_WORDS 16u\n")
    need(lay, "#define BLOOD_SHEEN_HAIR_M 0.02\n")
    need(lay, "#define BLOOD_SHEEN_HAIR_REL 0.01\n")
    need(lay, "#define BLOOD_SHEEN_SHOW_FLOOR 0.1\n")
    need(hdr, "static_assert(Group == 8u && SlotWords == 16u);")
    need(hdr, "static_assert(BLOOD_SHEEN_HAIR_M == 0.02 && BLOOD_SHEEN_HAIR_REL == 0.01);")
    need(hdr, "static_assert(sizeof(Push) == 112);")
    for words in ("MinStrength = 0.25f, MaxStrength = 4.0f", "MinIndices = 64", "MaxPoolDraws = 2;",
                  "DefaultVs = 0x1ea84d9aull, DefaultPs = 0xbd1d09f0ull"):
        need(hdr, words)
    need(cpp, "behind under 2 cm + 1%%")
    need(cpp, "cmd.setDepthCompareOp(vk::CompareOp::eAlways);")
    need(cpp, "    RestoreDepthTest();\n", 2)
    need(cpp, "RestoreDepthTest(); // (the pool's draw is recorded")
    need(cpp, "ForceNoDepthTest(regs);\n")
    need(cpp, 'EffectPass::Mark(ProfileRow, "blood sheen", true);', 3)
    need(cpp, "EffectPass::HasRoom(instance, 8ull * width * height)")
    rd = texts[README]
    for words in ("within 5 cm plus 3% of the distance", "toward 0.66", "f0 0.04", "at least 64 indices",
                  "0.25 to 4", "`1ea84d9a:bd1d09f0`", "16.6 MB at 1080p internal", "`Lighting: blood sheen`",
                  "`Blood sheen (r100`", "| `BB_BLOOD_SHEEN_DEPTH` |", "2 cm plus 1% of the distance",
                  "at least 0.1)", "or wrote its depth", "At most 2 such draws a frame", "(at most 2 a frame;"):
        if rd.count(words) < 1:
            raise SystemExit("text check: README lacks %r" % words)
    if rd.count("8.3 MB at 1080p internal") != 0:
        raise SystemExit("text check: README still states r100's single image")
    # Every log line of the class starts with "Blood sheen (r100)" (the slot runs keep such lines).
    for line in texts[cpp].split("\n"):
        if 'BbReport::Printf("' in line and "Blood sheen (r100)" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r100b_blood-sheen-mark.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R100_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        state = file_state(path, cur) if path in FILES else edit_state(path, cur)
        plan.append((path, raw, eol, cur, state))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()
    cmake = load(CMAKE)[2]

    def result(forward):
        out = {CMAKE: cmake}
        for path, raw, eol, cur, _ in plan:
            if path in FILES:
                out[path] = FILES[path][1 if forward else 0]
                continue
            for old, new in EDITS[path]:
                cur = cur.replace(new, old) if not forward else cur.replace(old, new)
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

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[3] for p in plan}
            texts[CMAKE] = cmake
            text_checks(texts)
            print("applied (%d files replaced, %d edited; text checks pass)" % (len(FILES), len(EDITS)))
        else:
            text_checks(result(True))
            print("not applied; would apply (%d files replaced, %d files with %d edits; text checks on "
                  "the result pass)" % (len(FILES), len(EDITS), sum(len(e) for e in EDITS.values())))
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
        print("applied (%d files replaced, %d edited)" % (len(FILES), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    write(result(False))
    print("reverted (%d files back to r100's text, %d edits taken out)"
          % (len(FILES), sum(len(e) for e in EDITS.values())))


main()
