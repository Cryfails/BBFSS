# r131a_foliage-translucency: FEATURE patch (lane LRT; owner asks LRT-G090 and LRT-G043). Draft:
# <queue>/LRT/next/r131a_foliage-translucency.draft.md. Applied AFTER r131b_lrt-settings (its end markers are the anchors of the ini key,
# the menu row and the launcher row) and after r130c and r130g; r131c (cabinet glass clear) is stacked beside it (see "Anchors" below).
#
# Owner need (goals.md LRT-G090): "make each blade of grass or foliage slighty transparent to where the lighting can change the color basically kind
# of like subsurface scattering"; LRT-G043: foliage shadows for both sun and lamps. LRT-G050: the cut-out shadows stay (this softens and tints them).
# Two visible parts, each its own sub-knob, both off by default:
#  (A) LIGHT THROUGH LEAVES: a lamp, sun or moon ray that reaches a kept leaf texel passes a share T (the luma share, 0.25) of its light, tinted by the
#      leaf, and goes on (rt_cards.glsl cardTraceShadow with CARD_TRANSMIT; a product below the floor blocks as before).
#  (B) BACK-LIT GLOW: leaf and grass pixels lit from behind gain light colour x leaf albedo x T x back-lit factor x visibility (foliage_glow.comp, over
#      the lit scene, after each G-buffer pass's opaque lighting).
#
# Knobs (all read once; ini key graphics_foliage_translucency 0..3: bit 1 = A, bit 2 = B; the variable wins over the key):
#  BB_FOLIAGE_TRANSLUCENCY=1 master (needs BB_RT_CARD_ALPHA=2); BB_FOLIAGE_LIGHT_THROUGH=1 (A; lamps also need BB_RT_CARD_LAMPS=1, the sun BB_RT_CARD_SUN=1),
#  BB_FOLIAGE_GLOW=1 (B; needs BB_RT_CARD_LAMPS=1: it finds leaves among the cards of the scene). The master on from the variable with no sub-switch has
#  both on. Tuning: BB_FOLIAGE_PASS=0.25, BB_FOLIAGE_TINT=1.0, BB_FOLIAGE_FLOOR=0.02, BB_FOLIAGE_GLOW_STRENGTH=1.0, BB_FOLIAGE_WRAP=0.3,
#  BB_FOLIAGE_SUN_K=0.318, BB_FOLIAGE_GLOW_VIEW=1 (TOOL: the added term x8 over a dim scene).
#
# Off = unchanged: every shader edit sits behind a NEW define (FOLIAGE, CARD_TRANSMIT, COLOUR of the card alpha fill) or adds only #define lines, so the
# SPIR-V of every existing build is byte for byte what it was (compared by the verifying run, before and after); no new build is selected, no image,
# buffer, pipeline or descriptor is made, no counter runs (the lamp counters buffer, the sun counters buffer and the hue image keep their sizes); the
# rasterizer makes no FoliageGlow (its hooks are null pointer tests); settings read once.
#
# Changes from the draft (and why): (1) the CPU mirror of the transmit rule is foliage_translucency.h's PassRun (tested against CardRayRun), not an edit of
# rt_card_layers.h: one shared header less to edit. (2) The glow takes the sun's colour from the brightest light set's light 0 (one colour a frame, from the
# table the directional draw binds), not from each pixel's record: no texture-0 lookup and no second table copy; the direction comes from the shadow resolve
# as the caustics take it. (3) B needs BB_RT_CARD_LAMPS=1 (the capture's cards in the TLAS carry the leaf test), said in the start line. (4) The sun's
# tunables (T, hue mix, floor) go in 16 more bytes of the sun trace's push constants (TracePush is 56 bytes; the other builds' blocks end where they did).
# (5) The lamp counters (rays, rays that passed a leaf, leaves, floor, grey) are those of the counted passes (one pass in CardCountEvery, one pixel in
# 64), like the card counters. (6) Two log lines carry the prefix "Foliage light (r131a)": the lamp line (PointShadow, every 600 frames) and the sun
# line (RtShadow, with the r25 line). (7) The effect pipeline test gets the card alpha fill's COLOUR build; the ray query builds (lamp, sun, glow) need
# the ray tracing extensions and are not made there.
#
# Cost, an estimate (not measured; 4K output, 1080p internal): off 0 ms, 0 bytes, one null pointer test a hook. A lamps: rays that meet a card read up to
# 3 more leaves, +0.02 to 0.06 ms; the colour image of the lamp pass (12 bytes a pixel) is made if BB_LAMP_SHADOW_COLOUR was off (24.9 MB at 1080p). A sun:
# +0.02 to 0.05 ms; the hue image 8.3 MB at 1080p (cleared by each sun trace). Colour layers 2 MiB, fill +0.01 ms a new layer. B: the camera ray on every
# non-sky pixel 0.10 to 0.20 ms, light rays on foliage pixels 0.10 to 0.35 ms, the read-modify-write 0.05 ms; 17 KB of buffers. The whole feature on:
# about 0.3 to 0.75 ms and 10 to 35 MB.
#
# Log lines (each once at the start; every 600 frames while on; off: only the start line): "Foliage translucency (r131a): BB_FOLIAGE_TRANSLUCENCY=0:
# off (nothing made)" or "...: light-through lamps on|off(why), sun on|off(why), glow on|off; T=.. tint=.. floor=..; colour layers 2.0 MiB"; "Foliage
# light (r131a): lamp card rays R, passed a leaf P (T=..), ended at floor F, grey (no colour) G; rest lamps grey ..." and "Foliage light (r131a): sun rays S,
# passed a leaf Q ..."; "Foliage glow (r131a): passes N, pixels X, foliage Y, back-lit Z, lamp rays L, sun rays M, added luma mean A, hue pixels H". Proof it
# runs: P > 0 where leaves are; dark-interior: R = P = 0, passes 0.
#
# Files: host_shaders: rt_cards.glsl, rt_card_layers_layout.h, rt_card_alpha_fill.comp, rt_card_sun_layout.h, point_shadow_ray.comp, rt_shadow.comp, NEW
# foliage_glow.comp, NEW foliage_glow_layout.h. renderer_vulkan: NEW foliage_translucency.h, NEW vk_foliage_glow.h and .cpp, vk_card_alpha.h and .cpp,
# vk_point_shadow.h and .cpp, vk_rt_shadow.h and .cpp, vk_rasterizer.h and .cpp, vk_rasterizer_effects.cpp. engine/gpu/CMakeLists.txt (8 builds, include
# lists, the test), engine/build.sh, engine/tests: NEW test_foliage_translucency.cpp, test_effect_pipelines.cpp, test_settings.cpp. gpu/shim:
# bbport_settings.h and .cpp, bbport_overlay.cpp, bbport_menu_i18n.cpp (8 tables). launcher: IniFile.cs, Choices.cs, both GraphicsPage.cs, 13 Localization
# json (English text everywhere, as r131b). README.md.
#
# Anchors (so the lead can stack r131c, which edits vk_rasterizer_effects.cpp after glass_view->Show and vk_rt_shadow.cpp's glass record mask): in
# vk_rasterizer_effects.cpp: the line `drawn_look->OnGBufferDraw(db_desc.first, cb_descs[0].first);` and its closing brace (EffectsAfterTargets); the closing
# brace of `glass_glint->AddLights(` (EffectsBeforeBind); the closing brace of `caustics->OnShadowResolve(` and of `caustics->OnLightSets(` (the directional
# light draw); the closing brace of `caustics->Apply(` (EffectsBlendedScene, BEFORE blood sheen and glass_view->Show); the closing brace of
# `glass_glint->OnFrameEnd();` (EffectsOnFrameEnd). In vk_rt_shadow.cpp: the include after rt_shadow_half_cards_comp.h; the raw_image destruction in the
# destructor; the line `bool RtShadow::Record(const Inputs& in) {` (MakeSunHue goes before it); the return of CardLampReadersNow; the CardSunNow pipeline
# creation, `++card_sun_cards;`, `use.sampler = readers.sampler;`; TracePush; `EffectPass::Mark(14, "ray traced sun");`; the `r25_clear` line in the record
# lambda; the trace_writes array; `card_sun_cards = card_sun_plain = 0;`. None of these is r130c's glass record write or r131c's mask rule.
#
# Not verified (no full build of the engine, no game run, no GPU): that the engine compiles and links (the C++ is new and only read against the real
# declarations); that the ray query builds run without a validation error; the picture; the cost estimates; the sun's diffuse scale k (BB_FOLIAGE_SUN_K is a
# guess: a wrong k shifts the saturation of the sun's tint, not its brightness); that the G-buffer normal of two-sided leaves is not flipped by the game.
# What was compiled: every new or changed GLSL build with glslangValidator, the pure test with clang (see the run notes of the lead).
#
# Use: python -I -X utf8 r131a_foliage-translucency.py check | apply | revert
# Root: R131A_ROOT, else <tree>; a root without engine/gpu is refused. Needs r131b (the end markers), r130c and r130g applied (revert this one FIRST:
# last in, first out). Line ends kept (CRLF or LF per file; a mixed file is refused; new files take CRLF). Each edit refuses unless its anchor is found
# exactly once; a mixed applied/clean state is refused; text checks run on the result before anything is written. apply backs the originals up in
# r131a_backup next to this script and writes through a temp file and a rename; revert takes out exactly what apply inserted and removes the new files.
import os, sys

ROOT = os.environ.get("R131A_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r131a_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RF = RV + "vk_rasterizer_effects.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
R = "README.md"
NEED = RV + "glass_light_forward.h"  # r130g's file
NEED2 = "engine/gpu/shim/bbport_overlay.cpp"  # r131b's end markers (checked in main)

# New files: path -> text (LF here; written with CRLF).
NEW = {
HS + "foliage_glow_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): what the back-lit glow pass (foliage_glow.comp) and the engine (renderer_vulkan/vk_foliage_glow.cpp,
// foliage_translucency.h, which ties these to its constants with static_asserts) share. Plain #define lines only: the shader includes this
// file through GL_GOOGLE_include_directive and C++ includes it as it is.
#ifndef FOLIAGE_GLOW_LAYOUT_H
#define FOLIAGE_GLOW_LAYOUT_H

// 8x8 threads a group, one a pixel of the scene.
#define FG_GROUP 8
// The lamps of the last G-buffer pass the pass reads (the nearest to the camera when there are more).
#define FG_MAX_LAMPS 32
// The data blocks the host writes, one a dispatch in turn (the GPU reads a block some frames after the host wrote it).
#define FG_SLOTS 16
// The buffer holds FG_COUNTER_WORDS counters (cumulative, u32), then FG_SLOTS blocks of FG_DATA_WORDS words:
//  words 0-2 the direction toward the sun or moon in view space, 3 the sun's diffuse scale k, 4-6 the sun's colour, 7 the lamp count,
//  then FG_MAX_LAMPS records of 8 words: view position x y z, inverse radius squared, colour r g b, 0 (as the game's light grid has them).
#define FG_COUNTER_WORDS 8
#define FG_DATA_WORDS 264
#define FG_DATA_SUN 0
#define FG_DATA_SUN_K 3
#define FG_DATA_SUN_COLOUR 4
#define FG_DATA_LAMP_COUNT 7
#define FG_DATA_LAMPS 8
// The counters: non-sky pixels, pixels the camera ray found a kept leaf texel at, back-lit pixels (a light behind the leaf was traced),
// lamp rays, sun rays, the sum of the luma added x 1000, pixels the sun's hue term reached, short camera rays cast.
#define FG_C_PIXELS 0
#define FG_C_FOLIAGE 1
#define FG_C_BACKLIT 2
#define FG_C_LAMP_RAYS 3
#define FG_C_SUN_RAYS 4
#define FG_C_ADDED 5
#define FG_C_HUE 6
#define FG_C_ID_RAYS 7
// The flags of the push constants: the glow itself, the sun's data are valid, the visibility rays tint (light through leaves is on),
// the sun's hue image is bound and the size of the scene, the test view (the term x8 over a dim scene).
#define FG_FLAG_GLOW 1u
#define FG_FLAG_SUN 2u
#define FG_FLAG_TRANSMIT 4u
#define FG_FLAG_HUE 8u
#define FG_FLAG_VIEW 16u
// The push constants (see foliage_glow.comp).
#define FG_PUSH_BYTES 112
// The strongest lamps and the sun are traced: at most this many lamp rays a pixel.
#define FG_PIXEL_LAMPS 2
// The back-lit visibility ray starts this far (m) on the light's side of the leaf, and is blind to the first FG_RAY_TMIN of its way.
#define FG_RAY_START 0.03
#define FG_RAY_TMIN 0.01
// The reference of an "above the reference" rule for these rays (the sun rays' CARD_SUN_REF).
#define FG_REF_SCALE 0.6

#endif
''',
HS + "foliage_glow.comp": r'''#version 460
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency) FEATURE (BB_FOLIAGE_GLOW, graphics_foliage_translucency bit 2; renderer_vulkan/vk_foliage_glow.cpp): the
// back-lit glow of leaves and grass, added over the lit scene (RGBA16F, read-modify-write), once after each G-buffer pass's opaque lighting.
// Per pixel (8x8 groups, the scene's size):
//  1. The sky and a pixel without a G-buffer normal: nothing.
//  2. The sun's hue term (the hue image of the sun trace's FOLIAGE builds, rt_shadow.comp): the light that came through leaves is tinted by
//     them; the game's own sun light carries only its brightness (a scalar), so the tint is added here as a term of zero luma:
//     sun colour x albedo x k x max(N.L, 0) x a x (2 hue - 1). Every pixel it covers, leaf or not.
//  3. Foliage: a SHORT camera ray (mask CARD_LAMP_MASK, from depth - tol to depth + tol) with the card test (cardTestLod, the game's rule, level 0)
//     finds a kept texel at the depth the game drew: the pixel is a leaf or a blade. It is no G-buffer bit: the capture (the TLAS) says so.
//  4. For the sun and the two strongest lamps behind the leaf (back = clamp((-N.L + W) / (1 + W), 0, 1), N turned to face the camera): one
//     visibility ray from 3 cm on the light's side of the leaf toward the light, with the cut-out cards (cardTraceShadow; with FG_FLAG_TRANSMIT
//     also the light that passes further leaves, tinted by them: CARD_TRANSMIT).
//  5. scene += light colour x leaf albedo x STRENGTH x T x back x falloff x visibility. T (BB_FOLIAGE_PASS) is the same luma share a leaf passes
//     for A. Honest name: thin-leaf diffuse transmission on the front leaf in screen space; not volumetric subsurface scattering.
// Counters (FG_C_*) per group, flushed once.
#extension GL_EXT_ray_query : require
#extension GL_GOOGLE_include_directive : require
#extension GL_EXT_samplerless_texture_functions : require

#define CARD_BINDING_ROWS 5
#define CARD_BINDING_POOL 6
#define CARD_BINDING_LAYER_INFO 7
#define CARD_BINDING_ALPHA 8
#define CARD_BINDING_COLOUR 9
#define CARD_TRACE_SHADOW
#define CARD_TRANSMIT
#include "rt_cards.glsl"
#include "foliage_glow_layout.h"

layout(local_size_x = FG_GROUP, local_size_y = FG_GROUP) in;

layout(set = 0, binding = 0) uniform accelerationStructureEXT scene;
layout(set = 0, binding = 1) uniform texture2D depth_tex;
layout(set = 0, binding = 2, rgba16f) uniform image2D color;
layout(set = 0, binding = 3) uniform texture2D normal_tex; // G-buffer cb0: world normal * 0.5 + 0.5
layout(set = 0, binding = 4) uniform texture2D albedo_tex; // G-buffer cb2: albedo
// bindings 5 to 9: the card tables (rt_cards.glsl), the colour layers last
layout(set = 0, binding = 10, std430) buffer Data {
    uint d[];
} data;
layout(set = 0, binding = 11) uniform texture2D hue_tex; // the sun trace's hue image (bound to the depth's view without FG_FLAG_HUE)

layout(push_constant) uniform Push {
    vec4 proj;       // CameraMotion's: x scale, y scale, z scale, z offset
    vec4 rot0;       // the camera's world to view matrix, rows (the rotation in xyz)
    vec4 rot1;
    vec4 rot2;
    vec2 jitter;     // render pixels, x right, y down
    uvec2 size;
    uint flags;      // FG_FLAG_*
    uint slot;       // the data block
    float strength;  // BB_FOLIAGE_GLOW_STRENGTH
    float wrap;      // BB_FOLIAGE_WRAP
    float pass_share; // T
    float pass_tint;
    float pass_floor;
    float unused;
} pc;

shared uint g_n[FG_COUNTER_WORDS];

void count(uint i, uint n) {
    atomicAdd(g_n[i], n);
}

// A texel of `tex` at the scene's pixel p, at the texture's own size when it is not the scene's.
ivec2 texelOf(texture2D tex, ivec2 p) {
    const ivec2 s = textureSize(tex, 0);
    ivec2 t = p;
    if (any(greaterThanEqual(t, s))) {
        t = ivec2((vec2(p) + 0.5) / vec2(pc.size) * vec2(s));
    }
    return min(t, s - 1);
}

float luma(vec3 c) {
    return dot(c, vec3(0.299, 0.587, 0.114));
}

// The light that reaches `p` of a leaf from the direction `dir` (unit, toward the light) up to `tmax`: 0 blocked, else 1 (the light through
// leaves passed, in each channel, with FG_FLAG_TRANSMIT).
vec3 visibility(vec3 p, vec3 face, vec3 dir, float tmax, uint mask) {
    const vec3 origin = p - face * float(FG_RAY_START);
    card_ref_scale = float(FG_REF_SCALE);
    card_dilate = true;
    card_pass = vec3(1.0);
    card_pass_n = 0u;
    card_pass_floor_n = 0u;
    card_pass_share = (pc.flags & FG_FLAG_TRANSMIT) != 0u ? pc.pass_share : 0.0;
    card_pass_tint = pc.pass_tint;
    card_pass_floor = pc.pass_floor;
    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, mask, origin, float(FG_RAY_TMIN), dir, tmax,
                                        CARD_RAY_CAP_DEFAULT, 0.0, 0.0);
    card_ref_scale = 1.0;
    card_dilate = false;
    return hit.t < 0.0 ? card_pass : vec3(0.0);
}

float back(vec3 face, vec3 dir) {
    return clamp((-dot(face, dir) + pc.wrap) / (1.0 + pc.wrap), 0.0, 1.0);
}

void shade(ivec2 p) {
    const float depth = texelFetch(depth_tex, p, 0).r;
    if (!(depth < 1.0)) {
        return; // the sky
    }
    count(FG_C_PIXELS, 1u);
    // camera_motion.comp's reconstruction (as rt_card_view.comp): ndc +y down, the jitter taken out
    const vec2 size = vec2(pc.size);
    const vec2 scene_uv = (vec2(p) + 0.5) / size - pc.jitter / size;
    const vec2 ndc = scene_uv * 2.0 - 1.0;
    const float z = pc.proj.w / min(depth - pc.proj.z, -1e-8);
    const vec3 point = vec3(ndc.x * z / pc.proj.x, ndc.y * z / pc.proj.y, z);
    const float depth_t = length(point);
    const vec3 view_dir = point / max(depth_t, 1e-6);
    // the G-buffer's normal (ssgi.comp gbufferNormal): world to view, turned to face the camera
    vec3 wn = texelFetch(normal_tex, texelOf(normal_tex, p), 0).xyz * 2.0 - 1.0;
    if (dot(wn, wn) <= 0.25) {
        return;
    }
    wn = normalize(wn);
    vec3 face = normalize(vec3(dot(pc.rot0.xyz, wn), dot(pc.rot1.xyz, wn), dot(pc.rot2.xyz, wn)));
    if (dot(face, point) > 0.0) {
        face = -face;
    }
    const vec3 albedo = texelFetch(albedo_tex, texelOf(albedo_tex, p), 0).rgb;
    const uint base = FG_COUNTER_WORDS + pc.slot * FG_DATA_WORDS;
    const bool have_sun = (pc.flags & FG_FLAG_SUN) != 0u;
    const vec3 sun_dir = uintBitsToFloat(uvec3(data.d[base + FG_DATA_SUN], data.d[base + FG_DATA_SUN + 1u], data.d[base + FG_DATA_SUN + 2u]));
    const float sun_k = uintBitsToFloat(data.d[base + FG_DATA_SUN_K]);
    const vec3 sun_col = uintBitsToFloat(uvec3(data.d[base + FG_DATA_SUN_COLOUR], data.d[base + FG_DATA_SUN_COLOUR + 1u],
                                               data.d[base + FG_DATA_SUN_COLOUR + 2u]));
    vec3 add = vec3(0.0);

    // 2. the sun's hue term, a term of zero luma (every pixel the hue image has a share at)
    if ((pc.flags & FG_FLAG_HUE) != 0u && have_sun) {
        const vec4 h = texelFetch(hue_tex, p, 0);
        if (h.a > 0.0) {
            const float nl = max(dot(face, sun_dir), 0.0);
            add += sun_col * albedo * (sun_k * nl * h.a) * (2.0 * h.rgb - 1.0);
            count(FG_C_HUE, 1u);
        }
    }

    // 3. is this pixel a leaf: a kept card texel at the depth the game drew
    bool foliage = false;
    if ((pc.flags & FG_FLAG_GLOW) != 0u) {
        count(FG_C_ID_RAYS, 1u);
        const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
        rayQueryEXT query;
        rayQueryInitializeEXT(query, scene, gl_RayFlagsNoOpaqueEXT, CARD_LAMP_MASK, vec3(0.0), max(depth_t - tol, 0.0), view_dir,
                              depth_t + tol);
        while (rayQueryProceedEXT(query)) {
            if (rayQueryGetIntersectionTypeEXT(query, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {
                continue;
            }
            const uint slot = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false));
            if (slot == 0u) {
                continue;
            }
            const CardResult c = cardTestLod(slot, uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false)),
                                             rayQueryGetIntersectionBarycentricsEXT(query, false), 0.0);
            if (c.status == CARD_KEPT) {
                foliage = true;
                rayQueryTerminateEXT(query);
                break;
            }
        }
    }
    if (foliage) {
        count(FG_C_FOLIAGE, 1u);
        bool lit = false;
        // 4. the sun, then the two strongest lamps behind the leaf
        if (have_sun) {
            const float b = back(face, sun_dir);
            if (b > 0.0) {
                lit = true;
                count(FG_C_SUN_RAYS, 1u);
                const vec3 vis = visibility(point, face, sun_dir, 800.0, 0x01u | CARD_LAMP_MASK);
                add += sun_col * albedo * (pc.strength * pc.pass_share * sun_k * b) * vis;
            }
        }
        const uint lamps = min(data.d[base + FG_DATA_LAMP_COUNT], uint(FG_MAX_LAMPS));
        float best_score[2] = float[2](0.0, 0.0);
        uint best_at[2] = uint[2](0u, 0u);
        for (uint k = 0u; k < lamps; ++k) {
            const uint w = base + FG_DATA_LAMPS + k * 8u;
            const vec3 lp = uintBitsToFloat(uvec3(data.d[w], data.d[w + 1u], data.d[w + 2u]));
            const float inv_r2 = uintBitsToFloat(data.d[w + 3u]);
            const vec3 to = lp - point;
            const float t2 = dot(to, to) * inv_r2;
            if (!(t2 < 1.0)) {
                continue;
            }
            float f = 1.0 - sqrt(t2);
            f *= f;
            const vec3 lc = uintBitsToFloat(uvec3(data.d[w + 4u], data.d[w + 5u], data.d[w + 6u]));
            const float score = luma(lc) * f * back(face, to * inversesqrt(max(dot(to, to), 1e-8)));
            if (score > best_score[0]) {
                best_score[1] = best_score[0];
                best_at[1] = best_at[0];
                best_score[0] = score;
                best_at[0] = w;
            } else if (score > best_score[1]) {
                best_score[1] = score;
                best_at[1] = w;
            }
        }
        for (uint i = 0u; i < uint(FG_PIXEL_LAMPS); ++i) {
            if (!(best_score[i] > 0.0)) {
                continue;
            }
            const uint w = best_at[i];
            const vec3 lp = uintBitsToFloat(uvec3(data.d[w], data.d[w + 1u], data.d[w + 2u]));
            const float inv_r2 = uintBitsToFloat(data.d[w + 3u]);
            const vec3 lc = uintBitsToFloat(uvec3(data.d[w + 4u], data.d[w + 5u], data.d[w + 6u]));
            const vec3 to = lp - point;
            const float len = length(to);
            const vec3 dir = to / max(len, 1e-6);
            float f = 1.0 - sqrt(len * len * inv_r2);
            f *= f;
            const float b = back(face, dir);
            lit = true;
            count(FG_C_LAMP_RAYS, 1u);
            const vec3 vis = visibility(point, face, dir, max(len - 0.05, 0.0), 0x04u | CARD_LAMP_MASK);
            add += lc * albedo * (pc.strength * pc.pass_share * f * b) * vis;
        }
        if (lit) {
            count(FG_C_BACKLIT, 1u);
        }
    }

    if (add != vec3(0.0)) {
        count(FG_C_ADDED, uint(max(luma(add), 0.0) * 1000.0 + 0.5));
        vec4 c = imageLoad(color, p);
        if ((pc.flags & FG_FLAG_VIEW) != 0u) {
            c.rgb = c.rgb * 0.25 + add * 8.0; // the test view: the term x8 over a dim scene
        } else {
            c.rgb = max(c.rgb + add, vec3(0.0)); // the hue term has negative channels: the scene stays >= 0
        }
        imageStore(color, p, c);
    }
}

void main() {
    if (gl_LocalInvocationIndex < uint(FG_COUNTER_WORDS)) {
        g_n[gl_LocalInvocationIndex] = 0u;
    }
    barrier();
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x < int(pc.size.x) && p.y < int(pc.size.y)) {
        shade(p);
    }
    barrier();
    if (gl_LocalInvocationIndex < uint(FG_COUNTER_WORDS) && g_n[gl_LocalInvocationIndex] != 0u) {
        atomicAdd(data.d[gl_LocalInvocationIndex], g_n[gl_LocalInvocationIndex]);
    }
}
''',
RV + "foliage_translucency.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r131a_foliage-translucency): the pure parts of the foliage translucency: the knobs (rules and tuning), the share of light a
// leaf passes and its hue (the CPU mirror of rt_cards.glsl's cardLeafPass and of the CARD_TRANSMIT rule in cardTraceShadow), and the
// zero-luma hue term of the sun. No Vulkan: tests/test_foliage_translucency.cpp builds this header alone. The functions at the end
// (On, LightThrough, ...) are made by vk_foliage_glow.cpp, which reads the environment, lantern.ini and the cards' own knobs once.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <span>

#include "rt_card_layers.h"
#include "../host_shaders/foliage_glow_layout.h"

namespace Vulkan::FoliageTranslucency {

using Rgb = std::array<float, 3>;

/// The ini key graphics_foliage_translucency: bit 1 light through leaves (A), bit 2 the back-lit glow (B).
inline constexpr int SettingOff = 0, SettingLight = 1, SettingGlow = 2, SettingBoth = 3;

/// The tuning knobs (BB_FOLIAGE_*), with their defaults and limits.
struct Tune {
    float pass = 0.25f;     ///< BB_FOLIAGE_PASS: T, the luma share a leaf lets through
    float tint = 1.0f;      ///< BB_FOLIAGE_TINT: how much of the leaf's hue the light takes, 0 grey, 1 all of it
    float floor = 0.02f;    ///< BB_FOLIAGE_FLOOR: a product below this is blocked
    float strength = 1.0f;  ///< BB_FOLIAGE_GLOW_STRENGTH
    float wrap = 0.3f;      ///< BB_FOLIAGE_WRAP: how far past the edge the back-lit term reaches
    float sun_k = 0.318f;   ///< BB_FOLIAGE_SUN_K: the game's diffuse scale for the sun (a guess)
    bool glow_view = false; ///< BB_FOLIAGE_GLOW_VIEW: TOOL, the added term x8 over a dim scene
};
inline constexpr float PassMin = 0.05f, PassMax = 0.5f, TintMax = 1.0f, FloorMin = 0.001f, FloorMax = 0.5f;
inline constexpr float StrengthMax = 8.0f, WrapMax = 1.0f, SunKMin = 0.05f, SunKMax = 2.0f;

[[nodiscard]] inline bool EnvGiven(const char* text) noexcept {
    return text != nullptr && text[0] != '\0';
}
/// Exactly "1" is on; anything else that is given is off.
[[nodiscard]] inline bool ExactOne(const char* text) noexcept {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}
/// A number in [lo, hi]; unset, empty, text or not finite: `fallback`; outside: the nearest end.
[[nodiscard]] inline float ReadFloat(const char* text, float fallback, float lo, float hi) noexcept {
    if (!EnvGiven(text)) {
        return fallback;
    }
    char* end = nullptr;
    const double v = std::strtod(text, &end);
    if (end == text || *end != '\0' || !std::isfinite(v)) {
        return fallback;
    }
    return std::clamp(float(v), lo, hi);
}
/// The tuning from a getter (std::getenv in the engine, a table in the test).
template <typename Getter>
[[nodiscard]] inline Tune ReadTune(Getter get) noexcept {
    Tune t;
    t.pass = ReadFloat(get("BB_FOLIAGE_PASS"), t.pass, PassMin, PassMax);
    t.tint = ReadFloat(get("BB_FOLIAGE_TINT"), t.tint, 0.0f, TintMax);
    t.floor = ReadFloat(get("BB_FOLIAGE_FLOOR"), t.floor, FloorMin, FloorMax);
    t.strength = ReadFloat(get("BB_FOLIAGE_GLOW_STRENGTH"), t.strength, 0.0f, StrengthMax);
    t.wrap = ReadFloat(get("BB_FOLIAGE_WRAP"), t.wrap, 0.0f, WrapMax);
    t.sun_k = ReadFloat(get("BB_FOLIAGE_SUN_K"), t.sun_k, SunKMin, SunKMax);
    t.glow_view = ExactOne(get("BB_FOLIAGE_GLOW_VIEW"));
    return t;
}

/// What the knobs decide before the cards' own switches: master (the foliage translucency at all), light (A), glow (B).
struct Decision {
    bool master = false;
    bool light = false;
    bool glow = false;
    const char* why = "off"; ///< when the master is off: the reason
};
/// BB_FOLIAGE_TRANSLUCENCY (exactly "1" on, other text off) wins over the ini setting (0 off, 1 A, 2 B, 3 both: any above 0 is on); a
/// master that is on without a sub-switch has both on from the variable, and from the setting the bits it names. BB_FOLIAGE_LIGHT_THROUGH
/// and BB_FOLIAGE_GLOW, when given, decide for their part (exactly "1" on). The master needs the alpha layers (BB_RT_CARD_ALPHA=2).
[[nodiscard]] inline Decision Decide(const char* master_env, const char* light_env, const char* glow_env, int setting,
                                     bool alpha_layers) noexcept {
    Decision d;
    const int s = std::clamp(setting, SettingOff, SettingBoth);
    const bool env = EnvGiven(master_env);
    const bool on = env ? ExactOne(master_env) : s > 0;
    if (!on) {
        d.why = env ? "off (BB_FOLIAGE_TRANSLUCENCY is not 1)" : "off";
        return d;
    }
    if (!alpha_layers) {
        d.why = "off: needs BB_RT_CARD_ALPHA=2";
        return d;
    }
    const int bits = env ? SettingBoth : s;
    d.master = true;
    d.light = EnvGiven(light_env) ? ExactOne(light_env) : (bits & SettingLight) != 0;
    d.glow = EnvGiven(glow_env) ? ExactOne(glow_env) : (bits & SettingGlow) != 0;
    d.why = "";
    return d;
}

[[nodiscard]] inline float Luma(const Rgb& c) noexcept {
    return 0.299f * c[0] + 0.587f * c[1] + 0.114f * c[2];
}
[[nodiscard]] inline float Max3(const Rgb& c) noexcept {
    return std::max(std::max(c[0], c[1]), c[2]);
}

/// cardLeafPass: the light a leaf texel passes. `stored` is the colour layer's rgb (the square root of the linear leaf colour). T is the
/// luma share; the leaf sets the hue (leaf / luma(leaf), each channel at most 3), `tint` mixes it with grey.
[[nodiscard]] inline Rgb LeafPass(const Rgb& stored, float share, float tint) noexcept {
    Rgb leaf{stored[0] * stored[0], stored[1] * stored[1], stored[2] * stored[2]};
    const float l = std::max(Luma(leaf), 1e-3f);
    Rgb out{};
    for (int i = 0; i < 3; ++i) {
        const float hue = std::min(leaf[i] / l, 3.0f);
        out[i] = share * (1.0f + (hue - 1.0f) * tint);
    }
    return out;
}

/// What a traversal hands the loop, in its order. kind: CARD_NO_DATA, CARD_DROPPED, CARD_KEPT (a leaf texel) or CardRayOpaque.
struct Event {
    std::uint32_t kind = CARD_DROPPED;
    Rgb colour{1.0f, 1.0f, 1.0f}; ///< a kept texel's stored colour layer value
    bool grey = false;            ///< a kept texel of a layer without colour (a mask texture): passes grey
};
struct PassResult {
    std::uint32_t how = CARD_RAY_FREE;
    std::uint32_t seen = 0, tested = 0, no_data = 0;
    Rgb product{1.0f, 1.0f, 1.0f}; ///< the light that got through the leaves passed
    std::uint32_t passed = 0, floor_ended = 0, grey = 0;
};
/// cardTraceShadow's loop with the CARD_TRANSMIT rule: a kept texel with a share above 0 multiplies the product by what it passes and the
/// ray goes on, unless the product falls below `floor` (then the texel blocks as before). Share 0 is CardRayRun, bit for bit. Opaque hits
/// end the ray; the cap and the guard count as in CardRayRun (a passed leaf is a tested one).
[[nodiscard]] inline PassResult PassRun(std::span<const Event> events, std::uint32_t cap, float share, float tint, float floor) noexcept {
    PassResult r;
    for (const Event& e : events) {
        if (e.kind == CardRayOpaque) {
            r.how = CARD_RAY_OPAQUE;
            return r;
        }
        ++r.seen;
        if (r.tested >= cap || r.seen > cap * CARD_RAY_GUARD) {
            r.how = CARD_RAY_CAP;
            return r;
        }
        if (e.kind == CARD_NO_DATA) {
            ++r.no_data;
            continue;
        }
        ++r.tested;
        if (e.kind == CARD_KEPT) {
            if (share > 0.0f) {
                Rgb pass{share, share, share};
                if (e.grey) {
                    ++r.grey;
                } else {
                    pass = LeafPass(e.colour, share, tint);
                }
                for (int i = 0; i < 3; ++i) {
                    r.product[i] *= pass[i];
                }
                ++r.passed;
                if (Max3(r.product) >= floor) {
                    continue;
                }
                ++r.floor_ended;
            }
            r.how = CARD_RAY_KEPT;
            return r;
        }
    }
    return r;
}

/// The lamp's reading of a ray that ended free: the grey it dims the lamp by and the hue it gives (point_shadow_ray.comp lampVisibility).
struct LampLight {
    float grey = 1.0f;
    Rgb hue{1.0f, 1.0f, 1.0f};
};
[[nodiscard]] inline LampLight LampLightOf(const Rgb& product) noexcept {
    LampLight l;
    const float g = Luma(product);
    l.grey = std::min(g, 1.0f);
    if (g > 1e-4f) {
        l.hue = {product[0] / g, product[1] / g, product[2] / g};
    }
    return l;
}

/// The sun trace's hue image texel (rt_shadow.comp FOLIAGE builds): rgb = half the mean hue of the rays that passed a leaf (0 to 2 stored in
/// 0 to 1), a = the share of the full sun that came through leaves. `hue_sum` is the sum of those rays' products, `leaf` the sum of their luma,
/// `rays` the sun rays of the pixel.
struct SunHueTexel {
    Rgb rgb{0.5f, 0.5f, 0.5f};
    float a = 0.0f;
};
[[nodiscard]] inline SunHueTexel SunHueStore(const Rgb& hue_sum, float leaf, float rays) noexcept {
    SunHueTexel t;
    const float d = std::max(leaf, 1e-4f);
    for (int i = 0; i < 3; ++i) {
        t.rgb[i] = 0.5f * hue_sum[i] / d;
    }
    t.a = rays > 0.0f ? leaf / rays : 0.0f;
    return t;
}
/// The composite's term (foliage_glow.comp): (2 rgb - 1) times a. Its luma is 0 when the mean hue has luma 1, so only the colour of the
/// light changes, never its brightness.
[[nodiscard]] inline Rgb SunHueTerm(const SunHueTexel& t) noexcept {
    return {(2.0f * t.rgb[0] - 1.0f) * t.a, (2.0f * t.rgb[1] - 1.0f) * t.a, (2.0f * t.rgb[2] - 1.0f) * t.a};
}

/// The back-lit factor (foliage_glow.comp): how far the light lies behind the leaf. `n_dot_l` is the dot of the camera-facing normal with the
/// direction toward the light; 0 when the light is in front.
[[nodiscard]] inline float BackLit(float n_dot_l, float wrap) noexcept {
    return std::clamp((-n_dot_l + wrap) / (1.0f + wrap), 0.0f, 1.0f);
}

/// The specialization constants of the lamp pass's FOLIAGE builds (vk_point_shadow.cpp MakeCardBuild): 16 share, 17 tint, 18 floor, 19 hue.
struct LampSpec {
    float pass = 0.25f, tint = 1.0f, floor = 0.02f;
    std::uint32_t hue = 0; ///< the lamps keep their own hue as well (BB_LAMP_SHADOW_COLOUR=1)
};

static_assert(CARD_COLOUR_SIZE == 64 && FG_MAX_LAMPS == 32 && FG_DATA_WORDS == 8 + FG_MAX_LAMPS * 8);
static_assert(FG_PUSH_BYTES == 112 && FG_COUNTER_WORDS == 8);

// Made by vk_foliage_glow.cpp (read once; the first call prints the start line). On: the master is on and the alpha layers exist.
// LightThrough: A, which needs the colour layers. LampThrough: A for the lamp rays (needs BB_RT_CARD_LAMPS=1). SunThrough: A for the sun
// and moon (needs BB_RT_CARD_SUN=1). Glow: B (needs BB_RT_CARD_LAMPS=1: the cards in the scene).
[[nodiscard]] bool On();
[[nodiscard]] bool LightThrough();
[[nodiscard]] bool LampThrough();
[[nodiscard]] bool SunThrough();
[[nodiscard]] bool Glow();
[[nodiscard]] const Tune& Tuning();
// LightNow and GlowNow: A and B as they are now: the start value (LightThrough, Glow), switched off or on again live by BB_FOLIAGE_LIGHT_THROUGH and
// BB_FOLIAGE_GLOW in the test tools' live knobs file where the build has it (a slot run: set:BB_FOLIAGE_GLOW=0). A part that was off at the start
// stays off (its builds and layers were not made). The lamp pass hands LampFlagOn to its FOLIAGE builds in word 16 of a pass's data.
[[nodiscard]] bool LightNow();
[[nodiscard]] bool GlowNow();
inline constexpr std::uint32_t LampFlagOn = 256u; // point_shadow_ray.comp FOLIAGE_FLAG_ON

} // namespace Vulkan::FoliageTranslucency
''',
RV + "vk_foliage_glow.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the back-lit glow of leaves and grass (host_shaders/foliage_glow.comp) and the knobs of the foliage
// translucency as a whole (foliage_translucency.h has the rules and the pure parts; the functions it declares are made in vk_foliage_glow.cpp).
//
// Off (graphics_foliage_translucency 0 and no BB_FOLIAGE_TRANSLUCENCY, or the glow not asked, or no BB_RT_CARD_ALPHA=2 with BB_RT_CARD_LAMPS=1): the
// rasterizer makes no FoliageGlow (Wanted), so there is no pipeline, buffer or pass, and each of its hooks is one null pointer test.
//
// Inputs, from the rasterizer's hooks (vk_rasterizer_effects.cpp), as the water caustics takes them (vk_caustics.h):
//  - EffectsAfterTargets, at a G-buffer draw (OnGBufferDraw): the depth, the world normal (cb 0) and the albedo (cb 2) of the pass; the lamps
//    gathered so far are another pass's.
//  - EffectsBeforeBind, at a lamp draw of the light grid (AddLights): its records, as drawn (up to FG_MAX_LAMPS, the nearest kept).
//  - The game's shadow resolve (OnSun): the direction toward the sun or moon in the world; its directional light draw (OnLightSets): the light
//    sets' table, of which the brightest set's light 0 is the sun's colour.
//  - EffectsBlendedScene, right after the caustics (Apply): the glow, once after each G-buffer pass's opaque lighting.
// The pass reads the ray traced scene's cut-out cards (RtShadow::CardLampReadersNow: needs BB_RT_CARD_LAMPS=1) and, with the light through leaves on,
// the sun trace's hue image (RtShadow::SunHueNow) and the colour layers.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/foliage_translucency.h"
#include "video_core/renderer_vulkan/lamp_fog_lights.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class PointShadow;
class RtShadow;
class Runtime;
class SceneTargets;
class Scheduler;

class FoliageGlow {
public:
    /// The glow is wanted (FoliageTranslucency::Glow: read once, the first call says the knobs).
    [[nodiscard]] static bool Wanted();
    FoliageGlow(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache, Runtime& runtime,
                SceneTargets& scene_targets, CameraMotion& camera_motion, PointShadow& point_shadow, RtShadow& rt_shadow);
    ~FoliageGlow();
    FoliageGlow(const FoliageGlow&) = delete;
    FoliageGlow& operator=(const FoliageGlow&) = delete;

    /// A G-buffer draw: its depth, world normal and albedo; the lamps gathered so far are another pass's. Arms the pass.
    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo);
    /// A lamp draw of the game's light grid: `count` records of 16 words (lamp_fog_lights.h), kept once each until the next G-buffer pass.
    void AddLights(const u32* records, u32 count);
    /// The game's shadow resolve: the direction toward the sun or moon in the world (`valid`: known this frame).
    void OnSun(const std::array<float, 3>& toward, bool valid);
    /// The game's directional light draw: its light sets' table (`floats` floats, 72 a set; light 0's colour at 16-18): the brightest set's colour is
    /// the sun's.
    void OnLightSets(const float* table, u32 floats);
    /// The first blended draw after the opaque scene: the glow into `color` (the scene colour, RGBA16F) from `depth`.
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
    /// Every frame end; every LineFrames frames the log line.
    void OnFrameEnd();

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    void Report();

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    PointShadow& point_shadow;
    RtShadow& rt_shadow;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    struct Buffer {
        vk::Buffer buffer{};
        VmaAllocation allocation{};
        void* mapped = nullptr;
    } data; ///< host coherent: the counters, then a data block a dispatch (foliage_glow_layout.h)
    bool made = false;
    std::array<ViewEntry, 6> view_cache{};
    u64 view_uses = 0;

    VideoCore::ImageId gbuffer_depth{}, gbuffer_normal{}, gbuffer_albedo{};
    LampFog::FrameLights lamps;
    std::array<float, 3> sun_world{};
    bool sun_valid = false;
    std::array<float, 3> sun_colour{};
    bool sun_colour_valid = false;
    bool armed = false;
    VideoCore::ImageId applied_depth{};
    u32 applied_frame = 0;
    u32 dispatches = 0; ///< the data block is dispatches % FG_SLOTS
    u32 frames = 0;
    bool told_first = false;

    struct Stats {
        u32 calls = 0, passes = 0;
        u32 switched_off = 0, no_scene = 0, no_gbuffer = 0, no_cards = 0, no_light = 0, no_hue = 0;
        u64 lamps = 0;
    } stats;
    std::array<u32, 8> last{}; ///< the counters at the last line
};

} // namespace Vulkan
''',
RV + "vk_foliage_glow.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the foliage translucency's knobs and the back-lit glow (vk_foliage_glow.h; the rules in
// foliage_translucency.h, the pass in host_shaders/foliage_glow.comp).

#include "video_core/renderer_vulkan/vk_foliage_glow.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>
#include <vector>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // the test tools' live knobs (r84_live-test-knobs), when the build has them
#define FT_LIVE_KNOBS 1
#endif
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "video_core/host_shaders/foliage_glow_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/volumetric_area_gate.h"
#include "video_core/texture_cache/texture_cache.h"

// bbport (r131a_foliage-translucency): the setting's numbers are the rules' (0 off, 1 light through leaves, 2 glow, 3 both; off by default).
static_assert(BbSettings::FoliageTranslucencyOff == Vulkan::FoliageTranslucency::SettingOff &&
              BbSettings::FoliageTranslucencyBoth == Vulkan::FoliageTranslucency::SettingBoth &&
              BbSettings::FoliageTranslucencyDefault == Vulkan::FoliageTranslucency::SettingOff);

namespace Vulkan::FoliageTranslucency {
namespace {

struct Config {
    Decision decision;
    bool light = false; ///< the colour layers are made and the visibility rays take them
    bool lamps = false, sun = false, glow = false;
    Tune tune;
};

const char* Env(const char* name) {
    return std::getenv(name);
}

// Read once, by the first caller: the start line.
const Config& State() {
    static const Config config = [] {
        Config c;
        const int setting = BbSettings::Get().startup_foliage_translucency;
        const char* const master = Env("BB_FOLIAGE_TRANSLUCENCY");
        c.decision = Decide(master, Env("BB_FOLIAGE_LIGHT_THROUGH"), Env("BB_FOLIAGE_GLOW"), setting,
                            Shader::Optimization::CardAlphaLevel() == 2);
        c.tune = ReadTune(Env);
        if (!c.decision.master) {
            std::printf("Foliage translucency (r131a): BB_FOLIAGE_TRANSLUCENCY=0: %s (nothing made)\n", c.decision.why);
            return c;
        }
        const char* lamps_why = "off (light through leaves is off)";
        const char* sun_why = lamps_why;
        if (c.decision.light) {
            c.lamps = RtShadow::CardLampsWanted();
            c.sun = RtShadow::CardSunOn();
            lamps_why = c.lamps ? "on" : "off (needs BB_RT_CARD_LAMPS=1)";
            sun_why = c.sun ? "on" : "off (needs BB_RT_CARD_SUN=1)";
        }
        c.glow = c.decision.glow && RtShadow::CardLampsWanted();
        c.light = c.decision.light && (c.lamps || c.sun || c.glow);
        char source[96];
        if (EnvGiven(master)) {
            std::snprintf(source, sizeof source, "BB_FOLIAGE_TRANSLUCENCY=1");
        } else {
            std::snprintf(source, sizeof source, "setting graphics_foliage_translucency=%d", setting);
        }
        std::printf("Foliage translucency (r131a): %s: light-through lamps %s, sun %s, glow %s; T=%.2f tint=%.2f floor=%.3f; "
                    "colour layers %s\n",
                    source, lamps_why, sun_why,
                    c.glow ? "on" : (c.decision.glow ? "off (needs BB_RT_CARD_LAMPS=1)" : "off"), double(c.tune.pass),
                    double(c.tune.tint), double(c.tune.floor),
                    c.light ? "2.0 MiB" : "none");
        if (c.lamps && c.sun == false && c.decision.light) {
            std::printf("Foliage translucency (r131a): the sun and moon stay as before (grey shadows); needs BB_RT_CARD_SUN=1\n");
        }
        if (c.sun && !c.glow) {
            std::printf("Foliage translucency (r131a): sun: grey (no tint without the glow pass)\n");
        }
        if (c.lamps) {
            std::printf("Foliage translucency (r131a): lamps: only the strongest two lamps of a pixel take the leaf's hue, the rest stay grey; "
                        "with BB_GLASS_LIGHT on a frame with leaves runs the foliage build (no glass tint)\n");
        }
        return c;
    }();
    return config;
}

} // namespace

bool On() {
    return State().decision.master;
}
bool LightThrough() {
    return State().light;
}
bool LampThrough() {
    return State().lamps;
}
bool SunThrough() {
    return State().sun;
}
bool Glow() {
    return State().glow;
}
const Tune& Tuning() {
    return State().tune;
}

namespace {
// -1: unset or empty in the live knobs file (the start value stands), else exactly "1" is on and anything else off.
int LiveReading(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : ExactOne(text) ? 1 : 0;
}
// A part as it is now: the start value, and where the build has the live knobs the knob's value (said when it changes).
bool Now(bool start, [[maybe_unused]] const char* name, [[maybe_unused]] bool& told) {
    if (!start) {
        return false;
    }
#ifdef FT_LIVE_KNOBS
    static BbLiveKnobs::Knob<int> light{"BB_FOLIAGE_LIGHT_THROUGH", [](const char* text) -> int { return LiveReading(text); }};
    static BbLiveKnobs::Knob<int> glow{"BB_FOLIAGE_GLOW", [](const char* text) -> int { return LiveReading(text); }};
    const int v = name[11] == 'L' ? light.Get() : glow.Get(); // "BB_FOLIAGE_L..." or "BB_FOLIAGE_G..." (index 11; review fix: 12 swapped the two knobs)
    const bool on = v < 0 || v == 1;
    if (on != told) {
        told = on;
        std::printf("Foliage translucency (r131a): %s now %s (live)\n", name, on ? "on" : "off");
    }
    return on;
#else
    return true;
#endif
}
} // namespace

bool LightNow() {
    static bool told = true;
    return Now(State().light, "BB_FOLIAGE_LIGHT_THROUGH", told);
}
bool GlowNow() {
    static bool told = true;
    return Now(State().glow, "BB_FOLIAGE_GLOW", told);
}

} // namespace Vulkan::FoliageTranslucency

namespace Vulkan {
namespace {
namespace FT = FoliageTranslucency;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u64 ProfileRow = 133; ///< EffectPass::Mark: the row "Lighting: foliage glow"
constexpr vk::DeviceSize BufferBytes = vk::DeviceSize(FG_COUNTER_WORDS + FG_SLOTS * FG_DATA_WORDS) * sizeof(u32);

struct Push {
    std::array<float, 4> proj;
    std::array<float, 4> rot0, rot1, rot2;
    std::array<float, 2> jitter;
    std::array<u32, 2> size;
    u32 flags, slot;
    float strength, wrap, pass_share, pass_tint, pass_floor, unused;
};
static_assert(sizeof(Push) == FG_PUSH_BYTES);

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// Four 8-bit channels (the G-buffer's normal target).
bool FourBytes(const VideoCore::Image& image) {
    const auto f = image.info.pixel_format;
    return f == vk::Format::eR8G8B8A8Unorm || f == vk::Format::eB8G8R8A8Unorm || f == vk::Format::eA8B8G8R8UnormPack32;
}

bool Finite3(const std::array<float, 3>& v) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}
} // namespace

bool FoliageGlow::Wanted() {
    return FT::Glow();
}

FoliageGlow::FoliageGlow(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                         Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                         PointShadow& point_shadow_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, point_shadow{point_shadow_}, rt_shadow{rt_shadow_} {
    using enum vk::DescriptorType;
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, set_layout, layout, pipeline,
                              {eAccelerationStructureKHR, eSampledImage, eStorageImage, eSampledImage, eSampledImage,
                               eStorageBuffer, eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                               eStorageBuffer, eSampledImage},
                              FG_PUSH_BYTES, FOLIAGE_GLOW_COMP, "Foliage glow");
    if (made) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = BufferBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
        };
        VmaAllocationCreateInfo alloc_ci{};
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer raw{};
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &data.allocation, &info) == VK_SUCCESS) {
            data.buffer = raw;
            data.mapped = info.pMappedData;
        }
        made = data.mapped != nullptr;
        if (made) {
            std::memset(data.mapped, 0, BufferBytes);
        }
    }
    const auto& tune = FT::Tuning();
    std::printf("Foliage glow (r131a): %s; leaves and grass lit from behind (the sun, the moon and the two strongest lamps) gain light colour x "
                "leaf albedo x %.2f (strength) x %.2f (T) x back-lit factor (wrap %.2f) x visibility; the sun's constant k %.3f%s; thin-leaf "
                "diffuse transmission on the front leaf in screen space, not volumetric subsurface scattering; the sun's colour is the "
                "brightest light set's, one for the frame\n",
                made ? "on" : "off - the pass could not be made", double(tune.strength), double(tune.pass), double(tune.wrap),
                double(tune.sun_k), tune.glow_view ? "; test view on (the term x8 over a dim scene)" : "");
}

FoliageGlow::~FoliageGlow() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (data.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), data.buffer, data.allocation);
    }
}

void FoliageGlow::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo) {
    gbuffer_depth = depth;
    gbuffer_normal = normal;
    gbuffer_albedo = albedo;
    lamps.Clear(); // the lamps of this pass only (they are in its view space)
    armed = armed || depth != applied_depth || BbStats::frame_number.load(std::memory_order_relaxed) != applied_frame;
}

void FoliageGlow::AddLights(const u32* records, u32 count) {
    lamps.Add(records, count);
}

void FoliageGlow::OnSun(const std::array<float, 3>& toward, bool valid) {
    const float length = std::sqrt(toward[0] * toward[0] + toward[1] * toward[1] + toward[2] * toward[2]);
    sun_valid = valid && Finite3(toward) && length > 1e-6f;
    if (sun_valid) {
        sun_world = {toward[0] / length, toward[1] / length, toward[2] / length};
    }
}

// The brightest set's light 0 (not the fallback): the sun's or the moon's colour for this frame.
void FoliageGlow::OnLightSets(const float* table, u32 floats) {
    namespace AG = VolumetricAreaGate;
    const u32 count = std::min(floats / AG::RecordFloats, AG::Records);
    float best = 0.0f;
    const float* pick = nullptr;
    for (u32 i = 0; i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (AG::IsFallback(set)) {
            continue;
        }
        const float lum = AG::RawLuminance(set + AG::RecordColour);
        if (lum > best) {
            best = lum;
            pick = set;
        }
    }
    sun_colour_valid = pick != nullptr;
    if (pick != nullptr) {
        sun_colour = {pick[AG::RecordColour], pick[AG::RecordColour + 1], pick[AG::RecordColour + 2]};
        sun_colour_valid = Finite3(sun_colour);
    }
}

vk::ImageView FoliageGlow::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.aspect == aspect) {
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
        .view = Check<"create foliage glow view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void FoliageGlow::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id, std::array<float, 2> jitter) {
    // Once after each G-buffer pass: the rasterizer calls at every blended draw of the scene.
    if (!armed) {
        return;
    }
    armed = false;
    applied_depth = gbuffer_depth;
    applied_frame = BbStats::frame_number.load(std::memory_order_relaxed);
    ++stats.calls;
    if (!FT::GlowNow()) { // switched off live (the test tools' knobs file): nothing runs
        ++stats.switched_off;
        return;
    }
    if (!made || !color_id || !depth_id || camera_motion.PreviewFrame()) {
        ++stats.no_scene;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid) {
        ++stats.no_scene;
        return;
    }
    if (gbuffer_depth != depth_id || !gbuffer_normal || !gbuffer_albedo) {
        ++stats.no_gbuffer; // not the pass the lights and targets were noted for
        return;
    }
    // The cards take CARD_LAMP_MASK only while a reader of them exists (as the lamp pass tells the scene).
    rt_shadow.NoteCardLampUser();
    if (!rt_shadow.PrepareScene()) {
        ++stats.no_scene;
        return;
    }
    const auto readers = rt_shadow.CardLampReadersNow();
    const vk::AccelerationStructureKHR tlas = rt_shadow.Scene();
    if (readers.instances == 0 || !readers.rows || !readers.pool || !readers.info || !readers.layers || !readers.sampler || !tlas) {
        ++stats.no_cards; // no card with data in the scene yet
        return;
    }
    const bool has_sun = sun_valid && sun_colour_valid;
    const auto& seen = lamps.Lights();
    const u32 lamp_count = u32(std::min<std::size_t>(seen.size(), FG_MAX_LAMPS));
    if (!has_sun && lamp_count == 0) {
        ++stats.no_light;
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    auto& normal = texture_cache.GetImage(gbuffer_normal);
    auto& albedo = texture_cache.GetImage(gbuffer_albedo);
    const auto albedo_format = albedo.info.pixel_format;
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat || !FourBytes(normal) ||
        (!FourBytes(albedo) && albedo_format != vk::Format::eR8G8B8A8Srgb && albedo_format != vk::Format::eB8G8R8A8Srgb)) {
        ++stats.no_gbuffer;
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size, else the game's render size.
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
        if (!scene_targets.EligibleScene(normal) || !scene_targets.EligibleScene(albedo)) {
            ++stats.no_gbuffer;
            return;
        }
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        ++stats.no_scene;
        return;
    }
    // The sun trace's hue image (the light through leaves: its tint), when it was written this frame at this size.
    const auto hue = rt_shadow.SunHueNow();
    const bool use_hue = has_sun && hue.view && hue.width == width && hue.height == height && FT::SunThrough() && FT::LightNow();
    stats.no_hue += has_sun && FT::SunThrough() && !use_hue ? 1 : 0;
    // The pass reads the camera depth and the lit scene: a lamps-apart batch still open ends first.
    if (point_shadow.Apart()) {
        point_shadow.EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
    }
    const SceneUseScope scene_use{"foliage glow"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, normal_view{}, albedo_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        VideoCore::ImageViewInfo normal_info, albedo_info;
        normal_info.format = normal.info.pixel_format;
        albedo_info.format = albedo.info.pixel_format;
        normal_view = scene_targets.ReadNext(gbuffer_normal, normal_info).view;
        albedo_view = scene_targets.ReadNext(gbuffer_albedo, albedo_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        normal_view = CachedView(normal, vk::ImageAspectFlagBits::eColor);
        albedo_view = CachedView(albedo, vk::ImageAspectFlagBits::eColor);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.Transit(&normal, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.Transit(&albedo, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    // This dispatch's data block (its last reader, FG_SLOTS dispatches ago, is long done): the sun, then the lamps nearest the camera.
    const u32 slot = dispatches % FG_SLOTS;
    u32* block = static_cast<u32*>(data.mapped) + FG_COUNTER_WORDS + slot * FG_DATA_WORDS;
    std::memset(block, 0, FG_DATA_WORDS * sizeof(u32));
    const auto put = [&](u32 at, float v) { std::memcpy(&block[at], &v, sizeof(float)); };
    const auto& tune = FT::Tuning();
    if (has_sun) {
        for (u32 r = 0; r < 3; ++r) {
            put(FG_DATA_SUN + r, camera.view[r * 4] * sun_world[0] + camera.view[r * 4 + 1] * sun_world[1] +
                                     camera.view[r * 4 + 2] * sun_world[2]);
            put(FG_DATA_SUN_COLOUR + r, sun_colour[r]);
        }
        put(FG_DATA_SUN_K, tune.sun_k);
    }
    u32 kept = 0;
    {
        // the nearest to the camera when the pass has more than the shader takes
        std::vector<std::pair<float, u32>> by_distance;
        by_distance.reserve(seen.size());
        for (u32 i = 0; i < u32(seen.size()); ++i) {
            const auto word = [&](u32 w) { return std::bit_cast<float>(seen[i][w]); };
            by_distance.emplace_back(word(0) * word(0) + word(1) * word(1) + word(2) * word(2), i);
        }
        const std::size_t take = std::min<std::size_t>(by_distance.size(), FG_MAX_LAMPS);
        std::partial_sort(by_distance.begin(), by_distance.begin() + take, by_distance.end());
        for (std::size_t k = 0; k < take; ++k) {
            const auto& light = seen[by_distance[k].second];
            if (!LampFog::Readable(light)) {
                continue;
            }
            const u32 at = FG_DATA_LAMPS + kept * 8u;
            for (u32 w = 0; w < 7; ++w) {
                block[at + w] = light[w]; // x y z, inverse radius squared, colour r g b: the light grid's own words
            }
            ++kept;
        }
    }
    block[FG_DATA_LAMP_COUNT] = kept;
    stats.lamps += kept;
    ++stats.passes;
    ++dispatches;
    if (!told_first) {
        told_first = true;
        std::printf("Foliage glow (r131a): first pass at frame %llu: scene %ux%u (%s), %u lamps, sun %s, hue image %s, light through leaves %s\n",
                    static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)), width, height,
                    reduced ? "reduced scene" : "the game's scene", kept, has_sun ? "yes" : "no", use_hue ? "yes" : "no",
                    FT::LightNow() && readers.colour ? "on" : "off");
    }
    Push push{};
    push.proj = camera.proj;
    push.rot0 = {camera.view[0], camera.view[1], camera.view[2], camera.view[3]};
    push.rot1 = {camera.view[4], camera.view[5], camera.view[6], camera.view[7]};
    push.rot2 = {camera.view[8], camera.view[9], camera.view[10], camera.view[11]};
    push.jitter = jitter;
    push.size = {width, height};
    push.flags = FG_FLAG_GLOW | (has_sun ? FG_FLAG_SUN : 0u) | (FT::LightNow() && readers.colour ? FG_FLAG_TRANSMIT : 0u) |
                 (use_hue ? FG_FLAG_HUE : 0u) | (tune.glow_view ? FG_FLAG_VIEW : 0u);
    push.slot = slot;
    push.strength = tune.strength;
    push.wrap = tune.wrap;
    push.pass_share = tune.pass;
    push.pass_tint = tune.tint;
    push.pass_floor = tune.floor;
    // Unbound inputs take the depth's view (the shader reads them only under their flag).
    const vk::ImageView hue_view = use_hue ? hue.view : depth_view;
    const vk::ImageView colour_view = readers.colour ? readers.colour : readers.layers;
    EffectPass::Mark(ProfileRow, "foliage glow");
    scheduler.RecordCrumb(
        {.name = "foliage glow"},
        [push, width, height, tlas, color_view, depth_view, normal_view, albedo_view, hue_view, colour_view, readers,
         buffer = data.buffer, pass_pipeline = *pipeline, pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{.accelerationStructureCount = 1,
                                                                         .pAccelerationStructures = &tlas};
            const std::array infos{Info(color_view), Info(depth_view), Info(normal_view), Info(albedo_view), Info(hue_view)};
            const vk::DescriptorBufferInfo rows_info{readers.rows, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo pool_info{readers.pool, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo layer_info{readers.info, 0, VK_WHOLE_SIZE};
            const vk::DescriptorImageInfo alpha_info{readers.sampler, readers.layers, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo colour_info{readers.sampler, colour_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo data_info{buffer, 0, BufferBytes};
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1, .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[1]},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1, .descriptorType = eStorageImage, .pImageInfo = &infos[0]},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[2]},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[3]},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &rows_info},
                vk::WriteDescriptorSet{.dstBinding = 6, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &pool_info},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &layer_info},
                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1, .descriptorType = eCombinedImageSampler, .pImageInfo = &alpha_info},
                vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1, .descriptorType = eCombinedImageSampler, .pImageInfo = &colour_info},
                vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &data_info},
                vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[4]}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmdbuf.dispatch((width + FG_GROUP - 1) / FG_GROUP, (height + FG_GROUP - 1) / FG_GROUP, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands | Host,
                                      MemoryAll | vk::AccessFlagBits2::eHostRead);
        });
}

void FoliageGlow::OnFrameEnd() {
    if (!made || ++frames < LineFrames) {
        return;
    }
    frames = 0;
    Report();
}

// The counters are cumulative u32 sums of the GPU (differences survive the wrap), read without waiting for it: a line may miss the last pass.
void FoliageGlow::Report() {
    std::array<u32, FG_COUNTER_WORDS> now{};
    std::memcpy(now.data(), data.mapped, sizeof(now));
    std::array<double, FG_COUNTER_WORDS> d{};
    for (u32 i = 0; i < FG_COUNTER_WORDS; ++i) {
        d[i] = double(u32(now[i] - last[i]));
    }
    last = now;
    const double back = d[FG_C_BACKLIT];
    std::printf("Foliage glow (r131a): passes %u, pixels %.0f, foliage %.0f, back-lit %.0f, lamp rays %.0f, sun rays %.0f, added luma mean %.4f, hue pixels %.0f; "
                "calls %u, skipped: %u switched off, %u no scene, %u no G-buffer, %u no cards, %u no light, sun hue missing %u; %u lamps a pass\n",
                stats.passes, d[FG_C_PIXELS], d[FG_C_FOLIAGE], back, d[FG_C_LAMP_RAYS], d[FG_C_SUN_RAYS],
                back > 0.0 ? d[FG_C_ADDED] * 0.001 / back : 0.0, d[FG_C_HUE], stats.calls, stats.switched_off, stats.no_scene, stats.no_gbuffer,
                stats.no_cards, stats.no_light, stats.no_hue, stats.passes != 0 ? u32(stats.lamps / stats.passes) : 0u);
    stats = {};
}

} // namespace Vulkan
''',
"engine/tests/test_foliage_translucency.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the pure parts of the foliage translucency (renderer_vulkan/foliage_translucency.h): the knob rules, the
// share of light a leaf passes and its hue, the CARD_TRANSMIT rule of the card ray against rt_card_layers.h's CardRayRun (share 0 is the old
// result bit for bit; order independence; the floor; the cap), the lamp's reading of what got through, the sun's hue texel and its zero-luma
// term, the back-lit factor. Pure: no Vulkan. Built and run by engine/build.sh --test and the CMake target foliage-translucency-test.
#undef NDEBUG
#include <algorithm>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <utility>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/foliage_translucency.h"

namespace F = Vulkan::FoliageTranslucency;
using Vulkan::CardRayOpaque;
using Vulkan::CardRayRun;

namespace {
bool Near(float a, float b, float eps = 1e-5f) {
    return std::fabs(a - b) <= eps;
}
const char* Lookup(const std::array<std::pair<const char*, const char*>, 4>& table, const char* name) {
    for (const auto& [k, v] : table) {
        if (k != nullptr && std::strcmp(k, name) == 0) {
            return v;
        }
    }
    return nullptr;
}
} // namespace

int main() {
    // a. the shared numbers
    static_assert(CARD_COLOUR_SIZE == CARD_LAYER_SIZE / 4 && FG_PIXEL_LAMPS == 2);
    assert(F::SettingLight == 1 && F::SettingGlow == 2 && F::SettingBoth == 3);

    // b. the knob rules: the master (a variable wins over the setting), the sub-switches, the alpha layers
    {
        using F::Decide;
        assert(!Decide(nullptr, nullptr, nullptr, 0, true).master);              // all off by default
        assert(!Decide("", nullptr, nullptr, 0, true).master);                   // an empty variable falls to the setting (0)
        assert(Decide(nullptr, nullptr, nullptr, 3, true).light && Decide(nullptr, nullptr, nullptr, 3, true).glow);
        assert(Decide(nullptr, nullptr, nullptr, 1, true).light && !Decide(nullptr, nullptr, nullptr, 1, true).glow);
        assert(!Decide(nullptr, nullptr, nullptr, 2, true).light && Decide(nullptr, nullptr, nullptr, 2, true).glow);
        assert(Decide("1", nullptr, nullptr, 0, true).master && Decide("1", nullptr, nullptr, 0, true).light &&
               Decide("1", nullptr, nullptr, 0, true).glow); // the variable with no sub-switch: both on
        assert(!Decide("0", nullptr, nullptr, 3, true).master);   // the variable wins over the setting
        assert(!Decide("x", nullptr, nullptr, 3, true).master && !Decide("11", nullptr, nullptr, 3, true).master);
        assert(Decide("1", "0", nullptr, 0, true).glow && !Decide("1", "0", nullptr, 0, true).light);
        assert(Decide("1", nullptr, "0", 0, true).light && !Decide("1", nullptr, "0", 0, true).glow);
        assert(Decide(nullptr, nullptr, "1", 1, true).glow && Decide(nullptr, nullptr, "1", 1, true).light); // a sub-switch decides for its own part
        assert(!Decide("1", nullptr, nullptr, 0, false).master); // needs BB_RT_CARD_ALPHA=2
        assert(std::strstr(Decide("1", nullptr, nullptr, 0, false).why, "BB_RT_CARD_ALPHA=2") != nullptr);
        assert(Decide(nullptr, nullptr, nullptr, 99, true).glow && !Decide(nullptr, nullptr, nullptr, -4, true).master); // out of range: the nearest end
    }
    // c. the tuning: defaults, limits, text
    {
        const F::Tune d = F::ReadTune([](const char*) -> const char* { return nullptr; });
        assert(Near(d.pass, 0.25f) && Near(d.tint, 1.0f) && Near(d.floor, 0.02f) && Near(d.strength, 1.0f) && Near(d.wrap, 0.3f) &&
               Near(d.sun_k, 0.318f) && !d.glow_view);
        const std::array<std::pair<const char*, const char*>, 4> t{{{"BB_FOLIAGE_PASS", "0.9"}, {"BB_FOLIAGE_TINT", "x"},
                                                                    {"BB_FOLIAGE_FLOOR", "0.0001"}, {"BB_FOLIAGE_GLOW_VIEW", "1"}}};
        const F::Tune r = F::ReadTune([&](const char* name) { return Lookup(t, name); });
        assert(Near(r.pass, F::PassMax));  // above the limit: the nearest end
        assert(Near(r.tint, 1.0f));        // text: the default
        assert(Near(r.floor, F::FloorMin)); // below the limit
        assert(r.glow_view);
    }
    // d. the leaf's pass: the luma share T, the hue from the leaf
    {
        const F::Rgb grey{0.5f, 0.5f, 0.5f}; // stored sqrt: a leaf of linear 0.25 grey
        const F::Rgb pg = F::LeafPass(grey, 0.25f, 1.0f);
        assert(Near(pg[0], 0.25f) && Near(pg[1], 0.25f) && Near(pg[2], 0.25f)); // a grey leaf passes grey
        const F::Rgb green{0.2f, 0.8f, 0.1f};
        for (const float tint : {0.0f, 0.5f, 1.0f}) {
            const F::Rgb p = F::LeafPass(green, 0.25f, tint);
            assert(Near(F::Luma(p), 0.25f, 1e-3f)); // the hue mix is linear: the luma is T at every tint
            if (tint == 0.0f) {
                assert(Near(p[0], 0.25f) && Near(p[1], 0.25f) && Near(p[2], 0.25f)); // tint 0: grey
            }
        }
        const F::Rgb pe = F::LeafPass(green, 0.25f, 1.0f);
        assert(pe[1] > pe[0] && pe[1] > pe[2]); // a green leaf passes green light
        const F::Rgb black{0.0f, 0.0f, 0.0f};
        const F::Rgb pb = F::LeafPass(black, 0.25f, 1.0f);
        assert(std::isfinite(pb[0]) && Near(pb[0], 0.0f) && Near(pb[1], 0.0f)); // a black texel: finite, 0
    }
    // e. the card ray: share 0 is CardRayRun, bit for bit
    {
        std::mt19937 rng(131);
        for (int run = 0; run < 4000; ++run) {
            std::vector<F::Event> events;
            std::vector<std::uint32_t> kinds;
            const int n = int(rng() % 9);
            for (int i = 0; i < n; ++i) {
                const std::uint32_t pick = rng() % 4;
                F::Event e;
                e.kind = pick == 0 ? std::uint32_t(CARD_NO_DATA) : pick == 1 ? std::uint32_t(CARD_DROPPED) : pick == 2 ? std::uint32_t(CARD_KEPT) : CardRayOpaque;
                e.colour = {0.3f, 0.6f, 0.2f};
                events.push_back(e);
                kinds.push_back(e.kind);
            }
            const std::uint32_t cap = 1 + rng() % 6;
            const auto old = CardRayRun(kinds, cap);
            const auto now = F::PassRun(events, cap, 0.0f, 1.0f, 0.02f);
            assert(now.how == old.how && now.seen == old.seen && now.tested == old.tested && now.no_data == old.no_data);
            assert(now.passed == 0 && now.product[0] == 1.0f && now.product[1] == 1.0f && now.product[2] == 1.0f);
        }
    }
    // f. a leaf passes light and the ray goes on; the floor ends it; order independence; the cap
    {
        const auto leaf = [](float r, float g, float b) {
            F::Event e;
            e.kind = CARD_KEPT;
            e.colour = {r, g, b};
            return e;
        };
        const F::Rgb stored{0.5f, 0.5f, 0.5f};
        std::vector<F::Event> two{leaf(0.5f, 0.5f, 0.5f), leaf(0.5f, 0.5f, 0.5f)};
        auto r = F::PassRun(two, 16, 0.25f, 1.0f, 0.02f);
        assert(r.how == CARD_RAY_FREE && r.passed == 2 && Near(r.product[0], 0.0625f)); // 0.25 x 0.25: free
        std::vector<F::Event> three{two[0], two[1], leaf(0.5f, 0.5f, 0.5f)};
        r = F::PassRun(three, 16, 0.25f, 1.0f, 0.02f);
        assert(r.how == CARD_RAY_KEPT && r.floor_ended == 1 && r.passed == 3); // 0.25^3 = 0.0156 < 0.02: the third blocks
        assert(F::PassRun(three, 16, 0.25f, 1.0f, 0.01f).how == CARD_RAY_FREE); // a lower floor: free
        std::vector<F::Event> opaque{leaf(0.5f, 0.5f, 0.5f), F::Event{CardRayOpaque, stored, false}};
        assert(F::PassRun(opaque, 16, 0.25f, 1.0f, 0.02f).how == CARD_RAY_OPAQUE); // an opaque hit ends it as before
        // order independence: coloured leaves in any order give one product
        std::vector<F::Event> mix{leaf(0.2f, 0.8f, 0.1f), leaf(0.7f, 0.7f, 0.2f)};
        const auto a = F::PassRun(mix, 16, 0.4f, 1.0f, 0.001f);
        std::reverse(mix.begin(), mix.end());
        const auto b = F::PassRun(mix, 16, 0.4f, 1.0f, 0.001f);
        for (int i = 0; i < 3; ++i) {
            assert(Near(a.product[i], b.product[i], 1e-6f));
        }
        // grey: a layer without colour passes T in every channel and is counted
        F::Event g = leaf(0.9f, 0.1f, 0.1f);
        g.grey = true;
        const auto rg = F::PassRun(std::vector<F::Event>{g}, 16, 0.25f, 1.0f, 0.02f);
        assert(rg.grey == 1 && Near(rg.product[0], 0.25f) && Near(rg.product[1], 0.25f) && Near(rg.product[2], 0.25f));
        // the cap: a passed leaf is a tested one; the next candidate blocks at the cap
        std::vector<F::Event> many(5, leaf(0.5f, 0.5f, 0.5f));
        const auto rc = F::PassRun(many, 2, 0.5f, 1.0f, 0.001f);
        assert(rc.how == CARD_RAY_CAP && rc.tested == 2);
    }
    // g. the lamp's reading: luma dims, the hue rides along; nothing passed is 1 and white
    {
        const auto none = F::LampLightOf({1.0f, 1.0f, 1.0f});
        assert(none.grey == 1.0f && none.hue[0] == 1.0f && none.hue[1] == 1.0f && none.hue[2] == 1.0f);
        const F::Rgb product = F::LeafPass({0.2f, 0.8f, 0.1f}, 0.25f, 1.0f);
        const auto l = F::LampLightOf(product);
        assert(Near(l.grey, F::Luma(product)) && Near(F::Luma(l.hue), 1.0f, 1e-4f) && l.hue[1] > l.hue[0]);
        const auto dark = F::LampLightOf({0.0f, 0.0f, 0.0f});
        assert(dark.grey == 0.0f && dark.hue[0] == 1.0f); // no light: no hue to give
    }
    // h. the sun's hue texel: the stored term has zero luma, so only the colour changes
    {
        const F::Rgb p1 = F::LeafPass({0.2f, 0.8f, 0.1f}, 0.25f, 1.0f);
        const F::Rgb p2 = F::LeafPass({0.3f, 0.7f, 0.2f}, 0.25f, 1.0f);
        const F::Rgb sum{p1[0] + p2[0], p1[1] + p2[1], p1[2] + p2[2]};
        const float leaf_luma = F::Luma(p1) + F::Luma(p2);
        const auto t = F::SunHueStore(sum, leaf_luma, 8.0f);
        assert(Near(t.a, leaf_luma / 8.0f));
        for (int i = 0; i < 3; ++i) {
            assert(t.rgb[i] >= 0.0f && t.rgb[i] <= 1.0f); // fits the 8-bit texel
        }
        const F::Rgb term = F::SunHueTerm(t);
        assert(Near(F::Luma(term), 0.0f, 1e-4f)); // zero luma by construction
        assert(term[1] > 0.0f && term[0] < 0.0f);  // green leaves: the term is green, less red
        const auto empty = F::SunHueStore({0.0f, 0.0f, 0.0f}, 0.0f, 8.0f);
        const F::Rgb zero = F::SunHueTerm(empty);
        assert(Near(zero[0], 0.0f) && Near(zero[1], 0.0f) && Near(zero[2], 0.0f)); // no leaf: a is 0, the term is 0
    }
    // i. the back-lit factor
    {
        assert(Near(F::BackLit(-1.0f, 0.3f), 1.0f));  // the light straight behind: full
        assert(Near(F::BackLit(1.0f, 0.3f), 0.0f));   // in front: none
        assert(Near(F::BackLit(0.0f, 0.3f), 0.3f / 1.3f)); // edge on: the wrap
        assert(F::BackLit(-0.5f, 0.0f) == 0.5f && F::BackLit(0.2f, 0.0f) == 0.0f);
    }

    std::puts("foliage translucency: ok");
    return 0;
}
''',
}

# ---------------------------------------------------------------- shader edits (every one behind a new define)
LAYOUT_ADD = r'''// bbport (r131a_foliage-translucency): the colour layers (RGBA8, CARD_COLOUR_SIZE square, one level, CARD_LAYER_COUNT layers: the level 2 size of the
// alpha layers; rt_card_alpha_fill.comp COLOUR=1) and the lamp pass's FOLIAGE counters (point_shadow_ray.comp): words CARD_LAMP_FOLIAGE_FIRST on of the
// counters buffer, which is CARD_LAMP_FOLIAGE_WORDS words longer only with FOLIAGE builds: 0 lamp rays, 1 rays that passed a leaf, 2 leaves passed,
// 3 rays that ended at the floor, 4 leaves passed without colour (a mask texture), then three spare.
#define CARD_COLOUR_SIZE 64
#define CARD_LAMP_FOLIAGE_FIRST 218
#define CARD_LAMP_FOLIAGE_WORDS 8
'''

CARD_TRANSMIT_SECTION = r'''#ifdef CARD_TRANSMIT
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

'''

CARD_TRANSMIT_RULE = r'''                // bbport (r131a_foliage-translucency) FEATURE (CARD_TRANSMIT builds only): a kept texel passes light and the query goes on (not
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
'''

FILL_BINDING = r'''#ifdef COLOUR
// bbport (r131a_foliage-translucency): the COLOUR build (rt_card_alpha_fill_colour_comp, made only with the light through leaves on) also writes
// the layer's colour at the size of level 2: the alpha weighted mean of the source's rgb over the same taps (the unweighted mean where the footprint
// holds no alpha), stored as its square root; a is 1 when the cut-out lane is the texture's alpha (a colour texture) and 0 for a mask texture.
layout(set = 0, binding = 4, rgba8) uniform writeonly image2DArray colour2;
#endif
'''
FILL_FUNC = r'''#ifdef COLOUR
vec4 colourAt(ivec2 p, float size) {
    const vec2 src_size = vec2(textureSize(src, 0));
    const float top = float(max(textureQueryLevels(src), 1) - 1);
    const vec2 ratio = max(src_size, vec2(1.0)) / size;
    const float small = min(ratio.x, ratio.y);
    const float lod = small <= 1.0 ? 0.0 : clamp(log2(small) - 1.0, 0.0, top);
    const vec2 texels = ratio * exp2(-lod);
    const int nu = axisTaps(texels.x);
    const int nv = axisTaps(texels.y);
    const vec2 origin = vec2(p) / size;
    vec3 weighted = vec3(0.0);
    vec3 plain = vec3(0.0);
    float weight = 0.0;
    for (int j = 0; j < nv; ++j) {
        for (int i = 0; i < nu; ++i) {
            const vec2 at = origin + (vec2(i, j) + 0.5) / (vec2(nu, nv) * size);
            const vec4 t = textureLod(src, at, lod);
            weighted += t.rgb * lane(t);
            plain += t.rgb;
            weight += lane(t);
        }
    }
    const float n = float(nu * nv);
    const vec3 rgb = weight > 1e-3 * n ? weighted / weight : plain / n;
    return vec4(sqrt(max(rgb, vec3(0.0))), pc.lane == 3u ? 1.0 : 0.0);
}
#endif

'''
FILL_STORE = r'''#ifdef COLOUR
        imageStore(colour2, ivec3(p, layer), colourAt(p, float(size / 4)));
#endif
'''

LAMP_HEAD = r'''#ifdef FOLIAGE
// bbport (r131a_foliage-translucency) FEATURE: the FOLIAGE builds (CARDS=1 COLOUR=1 FOLIAGE=1, made only with the light through leaves on for the
// lamps; the builds without it are the pass as before, word for word). A kept leaf texel passes a share of the lamp's light (cardTraceShadow with
// CARD_TRANSMIT, rt_cards.glsl) and the lamp's colour takes the leaf's hue: lampVisibility returns the luma of what got through and ray_hue, the hue,
// as r130c's glass does (the same colour sums). The colour layers are binding 5 of set 1. Specialization constants 16 to 19: T, the hue mix, the
// floor, and whether the lamps keep their own hue as well (BB_LAMP_SHADOW_COLOUR=1).
#define CARD_TRANSMIT
#define CARD_BINDING_COLOUR 5
#endif
'''
LAMP_SPEC = r'''#ifdef FOLIAGE
layout(constant_id = 16) const float FOLIAGE_PASS = 0.25;
layout(constant_id = 17) const float FOLIAGE_TINT = 1.0;
layout(constant_id = 18) const float FOLIAGE_FLOOR = 0.02;
layout(constant_id = 19) const uint FOLIAGE_HUE = 0u;
vec3 ray_trans = vec3(1.0); // the product of the leaves the last ray passed (1: none, or the ray was not cast)
const uint FOLIAGE_FLAG_ON = 256u; // word 16 of a pass's data, bit 8 (foliage_translucency.h LampFlagOn): the light through leaves is on (live knob)
bool t_fol_on = true;
#endif
'''
LAMP_TUNE = r'''#ifdef FOLIAGE
    t_fol_on = (data.d[at + 16u] & FOLIAGE_FLAG_ON) != 0u; // bbport (r131a_foliage-translucency): the host's word 16 (PointShadow::Flush)
#endif
'''
LAMP_HUE_GLOBALS = r'''#elif defined(FOLIAGE)
// bbport (r131a_foliage-translucency): the hue of what a lamp's ray let through, for the colour sums (as r130c's glass: top_hue and sec_hue are the
// picked lamps'; the weaker lamps stay grey)
vec3 ray_hue = vec3(1.0), top_hue = vec3(1.0), sec_hue = vec3(1.0);
#define GLASS_HUE(h) * h
'''
LAMP_COLOUR_OF = r'''#ifdef FOLIAGE
    if (FOLIAGE_HUE == 0u) { // bbport (r131a_foliage-translucency): the lamps keep no hue of their own: only the leaves change it
        return vec3(1.0);
    }
#endif
'''
LAMP_NOTE = r'''#ifdef FOLIAGE
// bbport (r131a_foliage-translucency): what the last ray did with the leaves, counted like cardCount: rays, rays that passed a leaf, leaves passed,
// rays that ended at the floor, leaves passed without colour
void foliageNote() {
    cardCount(CARD_LAMP_FOLIAGE_FIRST, 1u);
    if (card_pass_n != 0u) {
        cardCount(CARD_LAMP_FOLIAGE_FIRST + 1u, 1u);
        cardCount(CARD_LAMP_FOLIAGE_FIRST + 2u, card_pass_n);
    }
    if (card_pass_floor_n != 0u) {
        cardCount(CARD_LAMP_FOLIAGE_FIRST + 3u, card_pass_floor_n);
    }
    if (card_pass_grey != 0u) {
        cardCount(CARD_LAMP_FOLIAGE_FIRST + 4u, card_pass_grey);
    }
    card_pass_grey = 0u;
}
#endif
'''
LAMP_SET = r'''#ifdef FOLIAGE
        card_pass_share = t_fol_on ? FOLIAGE_PASS : 0.0; // bbport (r131a_foliage-translucency): 0 when switched off live (the leaves block as before)
        card_pass_tint = FOLIAGE_TINT;
        card_pass_floor = FOLIAGE_FLOOR;
        card_pass = vec3(1.0);
        card_pass_n = 0u;
        card_pass_floor_n = 0u;
#endif
'''
LAMP_AFTER_SHARP = r'''#ifdef FOLIAGE
        ray_trans = card_hit.t < 0.0 ? card_pass : vec3(1.0); // bbport (r131a_foliage-translucency): a free ray carries what the leaves passed
        foliageNote();
#endif
'''
LAMP_AFTER_COMBINED = r'''#ifdef FOLIAGE
    ray_trans = hit.t < 0.0 ? card_pass : vec3(1.0); // bbport (r131a_foliage-translucency)
    foliageNote();
#endif
'''
LAMP_VIS_END = r'''#elif defined(FOLIAGE)
    // bbport (r131a_foliage-translucency): a blocked ray is 0; a free one passed the leaves on its way: the luma of what they let through and its
    // hue for the colour sums (1 and white where it met none: the same answer as the build without FOLIAGE)
    if (ray(from, reach, target) >= 0.0) {
        return 0.0;
    }
    const float through = dot(ray_trans, vec3(0.299, 0.587, 0.114));
    ray_hue = through > 1e-4 ? ray_trans / through : vec3(1.0);
    return min(through, 1.0);
'''

SUN_HEAD = r'''#ifdef FOLIAGE
// bbport (r131a_foliage-translucency) FEATURE: the FOLIAGE builds (COVERAGE_SKIP=1 [HALF=1] CARDS=1 FOLIAGE=1, made only with the light through leaves
// on for the sun): a kept leaf texel passes a share of the sun, tinted by the leaf (CARD_TRANSMIT, rt_cards.glsl). The grey part (the luma of what got
// through) is the pixel's shadow term as before, only softer; the hue goes into sun_hue (binding 11), which the glow pass adds as a term of zero luma
// (the game's own sun light takes a scalar). The colour layers are binding 10.
#define CARD_TRANSMIT
#define CARD_BINDING_COLOUR 10
#endif
'''
SUN_DECL = r'''#ifdef FOLIAGE
// bbport (r131a_foliage-translucency): sun_hue: rgb half the mean hue (0 to 2 stored in 0 to 1) of the rays that passed a leaf, a the share of the full
// sun that came through leaves; one texel a pixel the trace shaded (the host clears the image first). lit_f, leaf_f and hue_sum: this pixel's rays;
// f_*: the counts; r131_n: the group's four counters (CARD_SUN_FOLIAGE_WORDS), flushed after the CARDS ones.
layout(set = 0, binding = 11, rgba8) uniform writeonly image2D sun_hue;
float lit_f = 0.0, leaf_f = 0.0;
vec3 hue_sum = vec3(0.0);
uint f_rays = 0u, f_pass = 0u, f_floor = 0u, f_grey = 0u;
shared uint r131_n[CARD_SUN_FOLIAGE_WORDS];
#endif
'''
SUN_PUSH = r'''#ifdef FOLIAGE
    float pass_share; // bbport (r131a_foliage-translucency): T, the hue mix and the floor (BB_FOLIAGE_*)
    float pass_tint;
    float pass_floor;
    uint pass_pad;
#endif
'''
SUN_RAY_SET = r'''#ifdef FOLIAGE
        card_pass_share = pass_share; // bbport (r131a_foliage-translucency)
        card_pass_tint = pass_tint;
        card_pass_floor = pass_floor;
        card_pass = vec3(1.0);
        card_pass_n = 0u;
        card_pass_floor_n = 0u;
#endif
'''
SUN_PIXEL_RESET = r'''#ifdef FOLIAGE
        if (i == 0u) { // bbport (r131a_foliage-translucency): a new pixel
            lit_f = 0.0;
            leaf_f = 0.0;
            hue_sum = vec3(0.0);
            f_rays = 0u;
            f_pass = 0u;
            f_floor = 0u;
            f_grey = 0u;
        }
#endif
'''
SUN_RAY_AFTER = r'''#ifdef FOLIAGE
        if (sun_hit.t < 0.0) { // bbport (r131a_foliage-translucency): what got through, in luma; the leaves' hue
            const float through = dot(card_pass, vec3(0.299, 0.587, 0.114));
            lit_f += through;
            if (card_pass_n != 0u) {
                leaf_f += through;
                hue_sum += card_pass;
            }
        }
        f_rays += 1u;
        f_pass += card_pass_n != 0u ? 1u : 0u;
        f_floor += card_pass_floor_n;
        f_grey += card_pass_grey;
        card_pass_grey = 0u;
#endif
'''
SUN_VIS_BEFORE = "#ifdef FOLIAGE\n    float sun_vis = lit_f * radius_scale; // bbport (r131a_foliage-translucency): the luma of the sun that got through\n#else\n"
SUN_VIS_AFTER = "#endif // FOLIAGE (r131a sun_vis)\n"
SUN_HUE_STORE = r'''#ifdef FOLIAGE
    imageStore(sun_hue, pixel, vec4(0.5 * hue_sum / max(leaf_f, 1e-4), leaf_f * radius_scale)); // bbport (r131a_foliage-translucency)
#endif
'''
SUN_COUNT = r'''#ifdef FOLIAGE
        atomicAdd(r131_n[0], f_rays); // bbport (r131a_foliage-translucency): rays, rays that passed a leaf, rays that ended at the floor, leaves without colour
        atomicAdd(r131_n[1], f_pass);
        atomicAdd(r131_n[2], f_floor);
        atomicAdd(r131_n[3], f_grey);
#endif
'''
SUN_ZERO = r'''#ifdef FOLIAGE
    if (count && gl_LocalInvocationIndex < CARD_SUN_FOLIAGE_WORDS) { // bbport (r131a_foliage-translucency)
        r131_n[gl_LocalInvocationIndex] = 0u;
    }
#endif
'''
SUN_FLUSH = r'''#ifdef FOLIAGE
        if (gl_LocalInvocationIndex < CARD_SUN_FOLIAGE_WORDS && r131_n[gl_LocalInvocationIndex] != 0u) { // bbport (r131a_foliage-translucency)
            atomicAdd(r25_buf.n[CARD_SUN_FIRST_WORD + CARD_SUN_WORDS + gl_LocalInvocationIndex], r131_n[gl_LocalInvocationIndex]);
        }
#endif
'''
SUN_LAYOUT_ADD = r'''// bbport (r131a_foliage-translucency): the FOLIAGE builds' four counters follow the CARDS ones (words 24 to 27 of the sun trace's counters; the buffer is
// four words longer only with them): sun rays, rays that passed a leaf, rays that ended at the floor, leaves passed without colour.
#define CARD_SUN_FOLIAGE_WORDS 4u
'''

SHADER_EDITS = {
HS + "rt_card_layers_layout.h": [
    ("ins", "#define CARD_LAMP_BUFFER_WORDS 218\n", "", "\n" + LAYOUT_ADD),
],
HS + "rt_cards.glsl": [
    ("ins", "// The test at the layer's level 0 (the debug view's ray; bbport r63_leaf-stage4: the lamp rays\n", CARD_TRANSMIT_SECTION, ""),
    ("ins", "                r.how = CARD_RAY_KEPT;\n                block = true;\n", CARD_TRANSMIT_RULE, ""),
],
HS + "rt_card_alpha_fill.comp": [
    ("ins", "layout(set = 0, binding = 3, r8) uniform writeonly image2DArray level2;\n", "", FILL_BINDING),
    ("ins", "void main() {\n    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);\n", FILL_FUNC, ""),
    ("ins", "        imageStore(level2, ivec3(p, layer), vec4(alphaAt(p, float(size / 4))));\n", "", FILL_STORE),
],
HS + "rt_card_sun_layout.h": [
    ("ins", "#define CARD_SUN_WORDS 8u\n", "", SUN_LAYOUT_ADD),
],
HS + "point_shadow_ray.comp": [
    ("ins", "#define CARD_TRACE_SHADOW\n#include \"rt_cards.glsl\"\n", LAMP_HEAD, ""),
    ("ins", "layout(constant_id = 15) const uint CARD_BLOCKS = 0u;\n", "", LAMP_SPEC),
    ("ins", "    t_colour = (f & (1u << 25u)) != 0u;      // bbport (r92_lamp-shadow-colour)\n", "", LAMP_TUNE),
    ("ins", "#else\n#define GLASS_HUE(h)\n#endif\n", LAMP_HUE_GLOBALS, ""),
    ("ins", "    return l > 0.0 ? col / l : vec3(1.0);\n", LAMP_COLOUR_OF, ""),
    ("ins", "void cardCount(uint index, uint n) {\n    if ((mode & MODE_CARD_COUNT) != 0u && ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 7u) == 0u) {\n"
            "        atomicAdd(card_counts[index], n);\n    }\n}\n", "", LAMP_NOTE),
    ("ins", "    g_cast = false; // bbport (r130c_glass-lamp-light): set where the plain ray is cast\n#endif\n", "",
     "#ifdef FOLIAGE\n    ray_trans = vec3(1.0); // bbport (r131a_foliage-translucency)\n#endif\n"),
    ("ins", "        card_skip_from = CARD_HOUSING > 0.0 ? card_len - CARD_HOUSING : 1e30; // bbport (r62n_cutout-skinned-blocker) FEATURE\n", "", LAMP_SET),
    ("ins", "        ray_card_kept = card_hit.how == CARD_RAY_KEPT;\n", "", LAMP_AFTER_SHARP),
    ("ins", "    card_skip_from = CARD_HOUSING > 0.0 ? ray_len - CARD_HOUSING : 1e30; // bbport (r62n_cutout-skinned-blocker) FEATURE\n", "",
     LAMP_SET.replace("        ", "    ")),
    ("ins", "    ray_card_kept = hit.how == CARD_RAY_KEPT;\n", "", LAMP_AFTER_COMBINED),
    ("ins", "    ray_hue = vec3(1.0); // bbport (r130c_glass-lamp-light)\n#endif\n", "",
     "#ifdef FOLIAGE\n    ray_hue = vec3(1.0); // bbport (r131a_foliage-translucency)\n#endif\n"),
    ("ins", "#else\n    return ray(from, reach, target) < 0.0 ? 1.0 : 0.0;\n#endif // GLASS (r130c lampVisibility)\n", LAMP_VIS_END, ""),
    ("ins", "            vsum_top = vsum; // bbport (r92_lamp-shadow-colour): the strongest lamp's part\n", "",
     "#ifdef FOLIAGE\n            top_hue = ray_hue; // bbport (r131a_foliage-translucency): the hue of what the strongest lamp's ray let through\n#endif\n"),
    ("ins", "                vsum += lay_sec_part;\n", "",
     "#ifdef FOLIAGE\n                sec_hue = ray_hue; // bbport (r131a_foliage-translucency): the second strongest lamp's\n#endif\n"),
],
HS + "rt_shadow.comp": [
    ("ins", "#define CARD_TRACE_SHADOW\n#define CARD_SUN_SELF\n#include \"rt_cards.glsl\"\n", SUN_HEAD, ""),
    ("ins", "#include \"rt_card_sun_layout.h\"\n", "", SUN_DECL),
    ("ins", "    uint r25_flags; // bbport (r25_rt-sun-trace): R25_* below\n", "", SUN_PUSH),
    ("ins", "        card_skip_below = max(CARD_SUN_SELF_M, reach);\n", "", SUN_RAY_SET),
    ("ins", "        vec3 ray = normalize(dir + (cos(a) * tangent + sin(a) * bitangent) * r);\n#ifdef CARDS\n", "", SUN_PIXEL_RESET),
    ("ins", "        if (sun_hit.t < 0.0) {\n            ++lit;\n        }\n", "", SUN_RAY_AFTER),
    ("ins", "    float sun_vis = float(lit) * radius_scale;\n", SUN_VIS_BEFORE, SUN_VIS_AFTER),
    ("ins", "    imageStore(raw_img, pixel, vec4(sun_vis));\n", "", SUN_HUE_STORE),
    ("ins", "        atomicAdd(r128_n[6], sun_rays_cap);\n", "", SUN_COUNT),
    ("ins", "        r128_n[gl_LocalInvocationIndex] = 0u;\n    }\n", "", SUN_ZERO),
    ("ins", "            atomicAdd(r25_buf.n[CARD_SUN_FIRST_WORD + gl_LocalInvocationIndex], r128_n[gl_LocalInvocationIndex]);\n        }\n", "", SUN_FLUSH),
],
}

# ---------------------------------------------------------------- engine edits (card alpha, lamp pass, sun trace, rasterizer)
# vk_card_alpha: the colour layers
CA_BINDINGS_OLD = ("    struct Bindings {\n        vk::ImageView layers;\n        vk::Sampler sampler;\n        vk::Buffer info;\n    };\n"
                   "    [[nodiscard]] Bindings ReaderBindings() const noexcept {\n        return {*layers_view, *layer_sampler, info_buffer.buffer};\n    }\n")
CA_BINDINGS_NEW = ("    struct Bindings {\n        vk::ImageView layers;\n        vk::Sampler sampler;\n        vk::Buffer info;\n"
                   "        vk::ImageView colour; // bbport (r131a_foliage-translucency): the colour layers (null unless made: the light through leaves)\n    };\n"
                   "    [[nodiscard]] Bindings ReaderBindings() const noexcept {\n"
                   "        return {*layers_view, *layer_sampler, info_buffer.buffer, colour_view ? *colour_view : vk::ImageView{}};\n    }\n")
CA_MEMBERS = r'''    // bbport (r131a_foliage-translucency): the colour layers: RGBA8, CARD_COLOUR_SIZE square, one level, CardLayerCount layers (2 MiB), written
    // by the COLOUR build of the fill (rt_card_alpha_fill.comp) at the size of level 2; made only with FoliageTranslucency::LightThrough()
    vk::Image colour_image{};
    VmaAllocation colour_allocation{};
    vk::UniqueImageView colour_view;
    bool colour_on = false;
    bool MakeColour();
'''
CA_INC_OLD = '#include "video_core/host_shaders/rt_card_alpha_fill_comp.h"\n'
CA_INC_NEW = ('#include "video_core/host_shaders/rt_card_alpha_fill_colour_comp.h" // bbport (r131a_foliage-translucency)\n'
              '#include "video_core/renderer_vulkan/foliage_translucency.h"       // bbport (r131a_foliage-translucency)\n')
CA_RANGE = r'''// bbport (r131a_foliage-translucency): the colour layers' size and range
constexpr vk::DeviceSize ColourBytes = vk::DeviceSize(CARD_COLOUR_SIZE) * CARD_COLOUR_SIZE * 4 * CardLayerCount;
constexpr vk::ImageSubresourceRange ColourRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, CardLayerCount};
'''
CA_DTOR = r'''    colour_view.reset(); // bbport (r131a_foliage-translucency)
    if (colour_image) {
        vmaDestroyImage(instance.GetAllocator(), colour_image, colour_allocation);
    }
'''
CA_MAKECOLOUR = r'''// bbport (r131a_foliage-translucency): the colour layers (see the member), cleared to 0 (a = 0: no colour) before the first fill. False: not made
// (no room, or the format cannot be stored): the fill is the plain one and the readers get no colour view.
bool CardAlpha::MakeColour() {
    const auto device = instance.GetDevice();
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) || !EffectPass::HasRoom(instance, ColourBytes)) {
        return false;
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {CARD_COLOUR_SIZE, CARD_COLOUR_SIZE, 1},
        .mipLevels = 1,
        .arrayLayers = CardLayerCount,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(instance.GetAllocator(), &image_ci, &alloc_ci, &raw, &colour_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    colour_image = raw;
    SetObjectName(device, colour_image, "Card colour layers");
    colour_view = Check<"create card colour view">(device.createImageViewUnique({
        .image = colour_image,
        .viewType = vk::ImageViewType::e2DArray,
        .format = vk::Format::eR8G8B8A8Unorm,
        .subresourceRange = ColourRange,
    }));
    scheduler.Record([image = colour_image](vk::CommandBuffer cmd) {
        EffectPass::InitGeneral(cmd, image, ColourRange);
        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
        cmd.clearColorImage(image, vk::ImageLayout::eGeneral, zero, ColourRange);
        EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands, MemoryAll);
    });
    return true;
}

'''
CA_FILL_OLD = ('    using enum vk::DescriptorType;\n    if (!EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,\n'
               '                            {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},\n'
               '                            CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COMP, "card alpha fill")) {\n        return false;\n    }\n')
CA_FILL_NEW = ('    using enum vk::DescriptorType;\n'
               '    // bbport (r131a_foliage-translucency): with the light through leaves on, the colour layers and the COLOUR build of the fill (a fifth image)\n'
               '    colour_on = FoliageTranslucency::LightThrough() && MakeColour();\n'
               '    if (colour_on ? !EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,\n'
               '                                        {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage, eStorageImage},\n'
               '                                        CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COLOUR_COMP, "card alpha fill (colour)")\n'
               '                  : !EffectPass::Create(instance, fill_set, fill_layout, fill_pipeline,\n'
               '                                        {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},\n'
               '                                        CARD_FILL_PUSH_BYTES, RT_CARD_ALPHA_FILL_COMP, "card alpha fill")) {\n        return false;\n    }\n')
CA_DST3 = ("    const vk::DescriptorImageInfo dst3{{}, colour_on ? *colour_view : vk::ImageView{}, vk::ImageLayout::eGeneral}; "
           "// bbport (r131a_foliage-translucency)\n")
CA_CAPTURE_OLD = "        [push, src, dst0, dst1, dst2, pipeline = *fill_pipeline,\n         layout = *fill_layout](vk::CommandBuffer cmd) {\n"
CA_CAPTURE_NEW = ("        [push, src, dst0, dst1, dst2, dst3, with_colour = colour_on, pipeline = *fill_pipeline,\n"
                  "         layout = *fill_layout](vk::CommandBuffer cmd) {\n")
CA_WRITE_OLD = ("                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,\n"
                "                                       .descriptorType = vk::DescriptorType::eStorageImage,\n"
                "                                       .pImageInfo = &dst2}};\n")
CA_WRITE_NEW = ("                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,\n"
                "                                       .descriptorType = vk::DescriptorType::eStorageImage,\n"
                "                                       .pImageInfo = &dst2},\n"
                "                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1, // bbport (r131a_foliage-translucency): the colour layers\n"
                "                                       .descriptorType = vk::DescriptorType::eStorageImage,\n"
                "                                       .pImageInfo = &dst3}};\n")
CA_PUSH_OLD = ("            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);\n"
               "            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), push.data());\n")
CA_PUSH_NEW = ("            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,\n"
               "                                     vk::ArrayProxy<const vk::WriteDescriptorSet>(with_colour ? 5u : 4u, writes.data()));\n"
               "            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), push.data());\n")

# vk_point_shadow: the FOLIAGE builds of the lamp pass
PS_INC = ('#include "video_core/host_shaders/point_shadow_ray_cards_colour_foliage_comp.h" // bbport (r131a_foliage-translucency)\n'
          '#include "video_core/host_shaders/point_shadow_ray_centred_cards_colour_foliage_comp.h"\n'
          '#include "video_core/host_shaders/point_shadow_ray_half_cards_colour_foliage_comp.h"\n'
          '#include "video_core/host_shaders/point_shadow_ray_half_centred_cards_colour_foliage_comp.h"\n'
          '#include "video_core/renderer_vulkan/foliage_translucency.h"\n')
PS_H_MEMBERS = r'''    // bbport (r131a_foliage-translucency): the light through leaves for the lamps (FoliageTranslucency::LampThrough, with colour_mode): the CARDS builds
    // are made in their FOLIAGE form (point_shadow_ray.comp CARDS COLOUR FOLIAGE; set 1 has the colour layers as binding 5 and the counters buffer holds
    // CARD_LAMP_FOLIAGE_WORDS words more), and the CARDS passes shadow in colour (LampTuneColour). Off: false, nothing different is made or bound.
    bool foliage_mode = false;
    FoliageTranslucency::LampSpec foliage_spec{};
    u32 card_words = CARD_LAMP_BUFFER_WORDS;
    std::array<u32, 8> foliage_last{};
'''
PS_FOLIAGECODE = r'''// bbport (r131a_foliage-translucency): the CARDS build's SPIR-V, or its FOLIAGE form's (the light through leaves)
std::span<const u32> FoliageCode(bool foliage, std::span<const u32> plain, std::span<const u32> leafy) {
    return foliage ? leafy : plain;
}

'''
PS_MAKE_OLD = "                   std::span<const u32> code, float texel_scale, u32 colour_images = 0) {\n"
PS_MAKE_NEW = ("                   std::span<const u32> code, float texel_scale, u32 colour_images = 0,\n"
               "                   const FoliageTranslucency::LampSpec* foliage = nullptr) { // bbport (r131a_foliage-translucency): FOLIAGE builds only\n")
PS_SPEC_OLD = ("    const vk::SpecializationInfo spec{u32(spec_entries.size()), spec_entries.data(), sizeof(spec_words),\n"
               "                                      spec_words.data()};\n")
PS_SPEC_NEW = (
    "    // bbport (r131a_foliage-translucency): the FOLIAGE builds' constants 16 to 19: T, the hue mix, the floor, whether the lamps keep their own hue\n"
    "    std::array<u32, 20> spec_words_f{};\n"
    "    std::copy(spec_words.begin(), spec_words.end(), spec_words_f.begin());\n"
    "    std::array<vk::SpecializationMapEntry, 20> spec_entries_f{};\n"
    "    std::copy(spec_entries.begin(), spec_entries.end(), spec_entries_f.begin());\n"
    "    if (foliage != nullptr) {\n"
    "        spec_words_f[16] = std::bit_cast<u32>(foliage->pass);\n"
    "        spec_words_f[17] = std::bit_cast<u32>(foliage->tint);\n"
    "        spec_words_f[18] = std::bit_cast<u32>(foliage->floor);\n"
    "        spec_words_f[19] = foliage->hue;\n"
    "        for (u32 i = 16; i < 20; ++i) {\n"
    "            spec_entries_f[i] = vk::SpecializationMapEntry{i, i * 4u, 4};\n"
    "        }\n"
    "    }\n"
    "    const vk::SpecializationInfo spec{foliage != nullptr ? 20u : u32(spec_entries.size()), spec_entries_f.data(),\n"
    "                                      foliage != nullptr ? sizeof(spec_words_f) : sizeof(spec_words),\n"
    "                                      foliage != nullptr ? spec_words_f.data() : spec_words.data()};\n")
PS_READY_ANCHOR = "    glass_mode = rt_shadow.GlassLightWanted();\n"
PS_READY_ADD = (
    "    // bbport (r131a_foliage-translucency): the light through leaves for the lamps needs the colour image too (the leaf's hue rides in the colour sums)\n"
    "    foliage_mode = FoliageTranslucency::LampThrough();\n")
PS_COLOUR_OLD = "    colour_mode = (tune.colour || glass_mode) && EffectPass::StorageFormat(instance, ColourFormat);\n"
PS_COLOUR_NEW = ("    colour_mode = (tune.colour || glass_mode || foliage_mode) && EffectPass::StorageFormat(instance, ColourFormat); // bbport (r131a): foliage_mode\n"
                 "    if (foliage_mode && !colour_mode) {\n"
                 "        std::printf(\"Foliage translucency (r131a): lamps: off (this GPU cannot store A2B10G10R10)\\n\");\n"
                 "        foliage_mode = false;\n"
                 "    }\n"
                 "    if (foliage_mode) {\n"
                 "        const auto& leaf = FoliageTranslucency::Tuning();\n"
                 "        foliage_spec = {leaf.pass, leaf.tint, leaf.floor, tune.colour ? 1u : 0u};\n"
                 "    }\n")
PS_BINDINGS_OLD = (
    "        const std::array<vk::DescriptorSetLayoutBinding, 5> bindings{{{0, eStorageBuffer, 1, Stage},\n"
    "                                                                      {1, eStorageBuffer, 1, Stage},\n"
    "                                                                      {2, eStorageBuffer, 1, Stage},\n"
    "                                                                      {3, eCombinedImageSampler, 1, Stage},\n"
    "                                                                      {4, eStorageBuffer, 1, Stage}}};\n"
    "        auto set = device.createDescriptorSetLayoutUnique(\n"
    "            {.bindingCount = u32(bindings.size()), .pBindings = bindings.data()});\n"
    "        const std::array<vk::DescriptorPoolSize, 2> sizes{\n"
    "            {{eStorageBuffer, 4 * CardSetsMost}, {eCombinedImageSampler, CardSetsMost}}};\n")
PS_BINDINGS_NEW = (
    "        // bbport (r131a_foliage-translucency): with the light through leaves a sixth binding, the colour layers (the plain CARDS builds ignore it)\n"
    "        const std::array<vk::DescriptorSetLayoutBinding, 6> bindings{{{0, eStorageBuffer, 1, Stage},\n"
    "                                                                      {1, eStorageBuffer, 1, Stage},\n"
    "                                                                      {2, eStorageBuffer, 1, Stage},\n"
    "                                                                      {3, eCombinedImageSampler, 1, Stage},\n"
    "                                                                      {4, eStorageBuffer, 1, Stage},\n"
    "                                                                      {5, eCombinedImageSampler, 1, Stage}}};\n"
    "        auto set = device.createDescriptorSetLayoutUnique(\n"
    "            {.bindingCount = foliage_mode ? 6u : 5u, .pBindings = bindings.data()});\n"
    "        const std::array<vk::DescriptorPoolSize, 2> sizes{\n"
    "            {{eStorageBuffer, 4 * CardSetsMost}, {eCombinedImageSampler, (foliage_mode ? 2u : 1u) * CardSetsMost}}};\n")
PS_CARDWORDS = ("        card_words = CARD_LAMP_BUFFER_WORDS + (foliage_mode ? u32(CARD_LAMP_FOLIAGE_WORDS) : 0u); // bbport (r131a_foliage-translucency)\n")
PS_BUF1_OLD = "            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::DeviceLocal, // bbport (r62m): the book too\n"
PS_BUF1_NEW = "            instance, 0, card_words * sizeof(u32), VideoCore::MemoryType::DeviceLocal, // bbport (r62m): the book too; (r131a): card_words\n"
PS_BUF2_OLD = "            instance, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32), VideoCore::MemoryType::HostCached,\n"
PS_BUF2_NEW = "            instance, 0, card_words * sizeof(u32), VideoCore::MemoryType::HostCached, // bbport (r131a): card_words\n"
PS_BUF3_OLD = "        if (card_readback->mapped_data.size() >= CARD_LAMP_BUFFER_WORDS * sizeof(u32)) {\n            std::memset(card_readback->mapped_data.data(), 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32));\n"
PS_BUF3_NEW = "        if (card_readback->mapped_data.size() >= card_words * sizeof(u32)) { // bbport (r131a): card_words\n            std::memset(card_readback->mapped_data.data(), 0, card_words * sizeof(u32));\n"
PS_COPY_OLD = "                    const vk::BufferCopy region{0, 0, CARD_LAMP_BUFFER_WORDS * sizeof(u32)}; // bbport (r62m): the book too\n"
PS_COPY_NEW = "                    const vk::BufferCopy region{0, 0, words * sizeof(u32)}; // bbport (r62m): the book too; (r131a): the foliage words\n"
PS_COPY_CAPTURE_OLD = ("            scheduler.Record([clear = std::exchange(card_counts_clear, false),\n"
                       "                              counters = card_counts->Handle(),\n")
PS_COPY_CAPTURE_NEW = ("            scheduler.Record([clear = std::exchange(card_counts_clear, false), words = card_words, // bbport (r131a_foliage-translucency)\n"
                      "                              counters = card_counts->Handle(),\n")
PS_CALLS = [
    ("                             POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n",
     "                             FoliageCode(foliage_mode, POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COMP,\n"
     "                                         POINT_SHADOW_RAY_HALF_CENTRED_CARDS_COLOUR_FOLIAGE_COMP), card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u, foliage_mode ? &foliage_spec : nullptr); // bbport (r92, r131a)\n"),
    ("                             POINT_SHADOW_RAY_HALF_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n",
     "                             FoliageCode(foliage_mode, POINT_SHADOW_RAY_HALF_CARDS_COMP,\n"
     "                                         POINT_SHADOW_RAY_HALF_CARDS_COLOUR_FOLIAGE_COMP), card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u, foliage_mode ? &foliage_spec : nullptr); // bbport (r92, r131a)\n"),
    ("                             POINT_SHADOW_RAY_CENTRED_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n",
     "                             FoliageCode(foliage_mode, POINT_SHADOW_RAY_CENTRED_CARDS_COMP,\n"
     "                                         POINT_SHADOW_RAY_CENTRED_CARDS_COLOUR_FOLIAGE_COMP), card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u, foliage_mode ? &foliage_spec : nullptr); // bbport (r92, r131a)\n"),
    ("                             POINT_SHADOW_RAY_CARDS_COMP, card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u); // bbport (r92_lamp-shadow-colour)\n",
     "                             FoliageCode(foliage_mode, POINT_SHADOW_RAY_CARDS_COMP,\n"
     "                                         POINT_SHADOW_RAY_CARDS_COLOUR_FOLIAGE_COMP), card_texel_scale,\n"
     "                             colour_mode ? 1u : 0u, foliage_mode ? &foliage_spec : nullptr); // bbport (r92, r131a)\n"),
]
PS_SETCHECK_OLD = "    if (r.instances == 0 || !r.rows || !r.pool || !r.info || !r.layers || !r.sampler) {\n"
PS_SETCHECK_NEW = "    if (r.instances == 0 || !r.rows || !r.pool || !r.info || !r.layers || !r.sampler || (foliage_mode && !r.colour)) { // bbport (r131a)\n"
PS_SETWRITE = r'''    if (foliage_mode) { // bbport (r131a_foliage-translucency): binding 5, the colour layers (read with the alpha layers' sampler)
        const vk::DescriptorImageInfo colour{r.sampler, r.colour, vk::ImageLayout::eGeneral};
        const vk::WriteDescriptorSet colour_write{.dstSet = set, .dstBinding = 5, .descriptorCount = 1,
                                                  .descriptorType = eCombinedImageSampler, .pImageInfo = &colour};
        device.updateDescriptorSets(colour_write, {});
    }
'''
PS_COLOURPASS_OLD = "    const bool colour_pass = use_rays && colour_mode && repair && !card_bind &&\n"
PS_COLOURPASS_NEW = "    const bool colour_pass = use_rays && colour_mode && repair && (card_bind ? foliage_mode : (tune.colour || glass_mode)) && // bbport (r131a)\n"
PS_GLASSFLAGS_OLD = '                data.push_back(GlassLight::Flags(glass_pass, tune.colour));'+'\n'
PS_GLASSFLAGS_NEW = ('                data.push_back(GlassLight::Flags(glass_pass, tune.colour) | // bbport (r131a_foliage-translucency): bit 8, the light through leaves is on'+'\n'+
                     '                                    (foliage_mode && FoliageTranslucency::LightNow() ? FoliageTranslucency::LampFlagOn : 0u));'+'\n')
PS_FOLWORD = ('            if (foliage_mode && !glass_mode) { // bbport (r131a_foliage-translucency): word 16, bit 8: the light through leaves is on (the FOLIAGE builds read it)'+'\n'+
              '                if (data.size() != std::size_t(tune_at) + 16) {'+'\n'+
              '                    data.clear();'+'\n'+
              '                    return;'+'\n'+
              '                }'+'\n'+
              '                data.push_back(FoliageTranslucency::LightNow() ? FoliageTranslucency::LampFlagOn : 0u);'+'\n'+
              '            }'+'\n')
PS_LINE = r'''    if (foliage_mode && card_readback && card_readback->mapped_data.size() >= card_words * sizeof(u32)) {
        // bbport (r131a_foliage-translucency): the lamp rays' leaves (the counted passes' sample, as the counters above): rays, rays that passed a leaf,
        // leaves passed, rays that ended at the floor, leaves passed without colour. Zeroed by the first counted pass; differences survive the wrap.
        std::array<u32, 8> f{};
        card_readback->Invalidate(CARD_LAMP_FOLIAGE_FIRST * sizeof(u32), sizeof(f));
        std::memcpy(f.data(), card_readback->mapped_data.data() + CARD_LAMP_FOLIAGE_FIRST * sizeof(u32), sizeof(f));
        std::array<double, 8> fd{};
        for (u32 i = 0; i < 8; ++i) {
            fd[i] = double(u32(f[i] - foliage_last[i]));
        }
        foliage_last = f;
        std::printf("Foliage light (r131a): lamp card rays %.0f, passed a leaf %.0f (T=%.2f, %.0f leaves), ended at floor %.0f, grey (no colour) %.0f; "
                    "rest lamps grey (the two strongest lamps of a pixel take the hue); counted passes only (one in %u, one pixel in 64)\n",
                    fd[0], fd[1], double(foliage_spec.pass), fd[2], fd[3], fd[4], unsigned(CardCountEvery));
    }
'''

# vk_rt_shadow: the sun trace's FOLIAGE builds, the hue image, the readers' colour view
RS_INC = ('#include "video_core/host_shaders/rt_shadow_cards_foliage_comp.h"      // bbport (r131a_foliage-translucency)\n'
          '#include "video_core/host_shaders/rt_shadow_half_cards_foliage_comp.h" // bbport (r131a_foliage-translucency)\n')
RS_H_INC = '#include "video_core/renderer_vulkan/foliage_translucency.h" // bbport (r131a_foliage-translucency)\n'
RS_H_READERS_OLD = ("        vk::Sampler sampler;\n        u32 instances = 0;\n    };\n    [[nodiscard]] CardLampReaders CardLampReadersNow() const;\n")
RS_H_READERS_NEW = ("        vk::Sampler sampler;\n        u32 instances = 0;\n"
                    "        vk::ImageView colour; // bbport (r131a_foliage-translucency): the colour layers (null unless made)\n    };\n"
                    "    [[nodiscard]] CardLampReaders CardLampReadersNow() const;\n"
                    "    // bbport (r131a_foliage-translucency): BB_RT_CARD_SUN's own switch, for the foliage translucency's start line and the glow pass; and the\n"
                    "    // sun trace's hue image (the FOLIAGE builds' second output, rt_shadow.comp): its view and size, empty unless the trace wrote it this frame or\n"
                    "    // the one before.\n"
                    "    [[nodiscard]] static bool CardSunOn() {\n        return CardSunWanted();\n    }\n"
                    "    struct SunHueView {\n        vk::ImageView view;\n        u32 width = 0, height = 0;\n    };\n"
                    "    [[nodiscard]] SunHueView SunHueNow() const noexcept {\n"
                    "        return sun_hue_view && frame <= sun_hue_frame + 1 ? SunHueView{sun_hue_view, sun_hue_width, sun_hue_height} : SunHueView{};\n    }\n")
RS_H_R25_OLD = "        return RtGlassLightOn() ? RtGlassLightCounterWords : CardSunWanted() ? CardSunCounterWords : R25Slots;\n"
RS_H_R25_NEW = ("        // bbport (r131a_foliage-translucency): the FOLIAGE builds add CARD_SUN_FOLIAGE_WORDS words after the CARDS ones\n"
                "        return RtGlassLightOn() ? RtGlassLightCounterWords\n"
                "               : CardSunWanted() ? CardSunCounterWords + (FoliageTranslucency::SunThrough() ? u32(CARD_SUN_FOLIAGE_WORDS) : 0u)\n"
                "                                 : R25Slots;\n")
RS_H_SUNUSE_OLD = ("        vk::ImageView layers;\n        vk::Sampler sampler;\n    };\n    [[nodiscard]] static bool CardSunWanted();\n")
RS_H_SUNUSE_NEW = ("        vk::ImageView layers;\n        vk::Sampler sampler;\n"
                   "        // bbport (r131a_foliage-translucency): the FOLIAGE build: the colour layers (binding 10) and the hue image (binding 11, cleared first)\n"
                   "        bool foliage = false;\n        vk::ImageView colour, hue;\n        vk::Image hue_image;\n    };\n"
                   "    [[nodiscard]] static bool CardSunWanted();\n")
RS_H_MEMBERS = ("    // bbport (r131a_foliage-translucency): the sun trace's hue image (RGBA8, the trace's size, made by MakeSunHue only with the light through leaves on\n"
                "    // for the sun), the frame the trace last wrote it, and the FOLIAGE counters at the last line\n"
                "    vk::Image sun_hue_image;\n    VmaAllocation sun_hue_allocation{};\n    vk::ImageView sun_hue_view;\n"
                "    u32 sun_hue_width = 0, sun_hue_height = 0;\n    u64 sun_hue_frame = 0;\n"
                "    std::array<u32, 4> foliage_sun_last{};\n    bool MakeSunHue(u32 width, u32 height);\n")
RS_DTOR = r'''    if (sun_hue_view) { // bbport (r131a_foliage-translucency)
        device.destroyImageView(sun_hue_view);
    }
    if (sun_hue_image) {
        vmaDestroyImage(instance.GetAllocator(), sun_hue_image, sun_hue_allocation);
    }
'''
RS_MAKEHUE = r'''// bbport (r131a_foliage-translucency): the sun trace's hue image (rt_shadow.comp FOLIAGE builds, binding 11): RGBA8 at the trace's size, made (and
// made again when the size changes) only with the light through leaves on for the sun. Each trace clears it before it writes.
bool RtShadow::MakeSunHue(u32 width, u32 height) {
    if (sun_hue_image && sun_hue_width == width && sun_hue_height == height) {
        return true;
    }
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    if (sun_hue_image) {
        scheduler.DeferOperation([device, allocator, image = sun_hue_image, memory = sun_hue_allocation, view = sun_hue_view] {
            device.destroyImageView(view);
            vmaDestroyImage(allocator, image, memory);
        });
        sun_hue_image = vk::Image{};
        sun_hue_view = vk::ImageView{};
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(allocator, &image_ci, &alloc_ci, &raw, &sun_hue_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    sun_hue_image = raw;
    const auto [result, view] = device.createImageView({
        .image = sun_hue_image,
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8G8B8A8Unorm,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    sun_hue_view = view;
    sun_hue_width = width;
    sun_hue_height = height;
    return true;
}

'''
RS_READERS_OLD = ("    return {card_rows.buffer, card_pool.buffer, layers.info, layers.layers, layers.sampler,\n            card_lamp_instances};\n")
RS_READERS_NEW = ("    return {card_rows.buffer, card_pool.buffer, layers.info, layers.layers, layers.sampler,\n"
                  "            card_lamp_instances, layers.colour}; // bbport (r131a_foliage-translucency): the colour layers\n")
RS_CREATE_OLD = (
    "        const bool made =\n"
    "            half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,\n"
    "                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,\n"
    "                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,\n"
    "                                       eCombinedImageSampler},\n"
    "                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_COMP},\n"
    "                                      \"Ray traced shadows (cut-outs, half resolution)\")\n")
RS_CREATE_NEW = (
    "        // bbport (r131a_foliage-translucency): with the light through leaves for the sun the FOLIAGE builds: bindings 10 (the colour layers) and 11\n"
    "        // (the hue image) more, and the leaf share in the push constants\n"
    "        const bool foliage = FoliageTranslucency::SunThrough();\n"
    "        const bool made =\n"
    "            foliage ? (half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,\n"
    "                                                 {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,\n"
    "                                                  eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,\n"
    "                                                  eCombinedImageSampler, eCombinedImageSampler, eStorageImage},\n"
    "                                                 sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_FOLIAGE_COMP},\n"
    "                                                 \"Ray traced shadows (cut-outs, leaves, half resolution)\")\n"
    "                            : EffectPass::Create(instance, card_sun_set, card_sun_layout, card_sun_pipeline,\n"
    "                                                 {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,\n"
    "                                                  eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,\n"
    "                                                  eCombinedImageSampler, eCombinedImageSampler, eStorageImage},\n"
    "                                                 sizeof(TracePush), std::span<const u32>{RT_SHADOW_CARDS_FOLIAGE_COMP},\n"
    "                                                 \"Ray traced shadows (cut-outs, leaves)\"))\n"
    "            : half ? EffectPass::Create(instance, card_sun_half_set, card_sun_half_layout, card_sun_half_pipeline,\n"
    "                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage, eAccelerationStructureKHR,\n"
    "                                       eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer, eStorageBuffer,\n"
    "                                       eCombinedImageSampler},\n"
    "                                      sizeof(TracePush), std::span<const u32>{RT_SHADOW_HALF_CARDS_COMP},\n"
    "                                      \"Ray traced shadows (cut-outs, half resolution)\")\n")
RS_SUNNOW_BEFORE = ("    // bbport (r131a_foliage-translucency): the FOLIAGE builds need the colour layers and the hue image\n"
                    "    if (FoliageTranslucency::SunThrough() && (!readers.colour || !MakeSunHue(raw_width, raw_height))) {\n"
                    "        ++card_sun_plain;\n        return use;\n    }\n")
RS_SUNNOW_AFTER = ("    if (FoliageTranslucency::SunThrough()) { // bbport (r131a_foliage-translucency)\n"
                   "        use.foliage = true;\n        use.colour = readers.colour;\n        use.hue = sun_hue_view;\n        use.hue_image = sun_hue_image;\n    }\n")
RS_PUSH_OLD = ("    u32 r25_flags;  // bbport (r25_rt-sun-trace): R25Exact | R25Count | R25HalfFirst | R25HalfFill\n};\nstatic_assert(sizeof(TracePush) == 40);\n")
RS_PUSH_NEW = ("    u32 r25_flags;  // bbport (r25_rt-sun-trace): R25Exact | R25Count | R25HalfFirst | R25HalfFill\n"
               "    // bbport (r131a_foliage-translucency): the FOLIAGE builds' T, hue mix and floor (rt_shadow.comp). The other builds' blocks end at r25_flags; the\n"
               "    // range pushed is wider, which is allowed.\n"
               "    float pass_share, pass_tint, pass_floor;\n    u32 pass_pad;\n};\nstatic_assert(sizeof(TracePush) == 56);\n")
RS_INIT_OLD = "        .far_radius = BbToggle::Experiment(4194304) ? -1 : FilterRadius,\n        .r25_flags = r25_flags,\n    };\n"
RS_INIT_NEW = ("        .far_radius = BbToggle::Experiment(4194304) ? -1 : FilterRadius,\n        .r25_flags = r25_flags,\n"
               "        .pass_share = FoliageTranslucency::LightNow() ? FoliageTranslucency::Tuning().pass : 0.0f, // bbport (r131a_foliage-translucency): 0 switched off live\n"
               "        .pass_tint = FoliageTranslucency::Tuning().tint,\n        .pass_floor = FoliageTranslucency::Tuning().floor,\n    };\n")
RS_HUEFRAME = ("    if (card_sun.foliage && !use_vsm) { // bbport (r131a_foliage-translucency): the hue image of this trace (the glow pass reads it)\n"
               "        sun_hue_frame = frame;\n    }\n")
RS_HUECLEAR = r'''            if (card_sun.foliage && !use_vsm) {
                // bbport (r131a_foliage-translucency): the hue image: undefined to general and cleared to 0 (a pixel the trace does not shade has no leaf share)
                const vk::ImageMemoryBarrier2 hue_to_general{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .image = card_sun.hue_image,
                    .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &hue_to_general});
                const vk::ClearColorValue hue_zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                const vk::ImageSubresourceRange hue_range{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
                cmdbuf.clearColorImage(card_sun.hue_image, vk::ImageLayout::eGeneral, hue_zero, hue_range);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            }
'''
RS_WRITES_OLD = "            const std::array<vk::WriteDescriptorSet, 10> trace_writes{{\n"
RS_WRITES_NEW = ("            // bbport (r131a_foliage-translucency): bindings 10 and 11 are the FOLIAGE builds' colour layers and hue image (pushed only with them)\n"
                 "            const vk::DescriptorImageInfo cs_colour{card_sun.sampler, card_sun.colour, vk::ImageLayout::eGeneral};\n"
                 "            const vk::DescriptorImageInfo cs_hue{{}, card_sun.hue, vk::ImageLayout::eGeneral};\n"
                 "            const std::array<vk::WriteDescriptorSet, 12> trace_writes{{\n")
RS_WRITES_END_OLD = ("                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_alpha},\n            }};\n")
RS_WRITES_END_NEW = ("                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_alpha},\n"
                     "                {.dstBinding = 10, .descriptorCount = 1, // r131a: the colour layers\n"
                     "                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &cs_colour},\n"
                     "                {.dstBinding = 11, .descriptorCount = 1, // r131a: the hue image\n"
                     "                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &cs_hue},\n            }};\n")
RS_COUNT_OLD = "            const vk::ArrayProxy<const vk::WriteDescriptorSet> trace_push(card_sun.pipeline ? 10u : 6u, trace_writes.data());\n"
RS_COUNT_NEW = ("            const vk::ArrayProxy<const vk::WriteDescriptorSet> trace_push(card_sun.foliage ? 12u : card_sun.pipeline ? 10u : 6u,\n"
                "                                                                          trace_writes.data()); // (r131a: 12 with the FOLIAGE build)\n")
RS_LINE = r'''        // bbport (r131a_foliage-translucency): the sun's light through leaves: its four counters follow the CARDS ones (r25 words 24 to 27), means per
        // counted frame as r25's
        if (FoliageTranslucency::SunThrough()) {
            std::array<u32, 4> got{};
            std::memcpy(got.data(), static_cast<const u32*>(r25_readback.mapped) + CardSunFirstWord + CardSunWords, sizeof(got));
            std::array<double, 4> m{};
            for (u32 i = 0; i < 4 && counted != 0; ++i) {
                m[i] = double(u32(got[i] - foliage_sun_last[i])) / double(counted);
            }
            foliage_sun_last = got;
            std::printf("Foliage light (r131a): sun rays %.0f, passed a leaf %.0f (T=%.2f), ended at floor %.0f, grey (no colour) %.0f (a counted frame, %u of "
                        "them); the sun and moon: %s\n",
                        m[0], m[1], double(FoliageTranslucency::Tuning().pass), m[2], m[3], counted,
                        FoliageTranslucency::Glow() ? "grey part through the game's light, hue added by the glow pass"
                                                    : "grey (no tint without the glow pass)");
        }
'''

# the rasterizer: the glow object and its hooks
RAST_H_INC = '#include "video_core/renderer_vulkan/vk_foliage_glow.h" // bbport (r131a_foliage-translucency)\n'
RAST_H_MEMBER = ("    /// bbport (r131a_foliage-translucency): made only with the back-lit glow on (FoliageGlow::Wanted: BB_FOLIAGE_GLOW or the setting, with BB_RT_CARD_ALPHA=2\n"
                 "    /// and BB_RT_CARD_LAMPS=1), else null: its hooks are null pointer tests.\n"
                 "    std::unique_ptr<FoliageGlow> foliage_glow;\n")
RAST_CTOR_ANCHOR = ("        glass_glint = std::make_unique<GlassGlint>(instance, scheduler, texture_cache, runtime,\n"
                    "                                                   *scene_targets, *camera_motion, *rt_shadow);\n    }\n")
RAST_CTOR = ("    // bbport (r131a_foliage-translucency): the back-lit glow (FoliageGlow::Wanted, read once: also says the foliage translucency's start line);\n"
             "    // otherwise none is made and nothing of it runs.\n"
             "    if (FoliageGlow::Wanted()) {\n"
             "        foliage_glow = std::make_unique<FoliageGlow>(instance, scheduler, texture_cache, runtime, *scene_targets, *camera_motion,\n"
             "                                                     *point_shadow, *rt_shadow);\n    }\n")
EFF_GBUFFER_ANCHOR = ("        if (drawn_look_wanted) { // bbport (r45_drawn-look): cb 0 holds the world normals\n"
                      "            drawn_look->OnGBufferDraw(db_desc.first, cb_descs[0].first);\n        }\n")
EFF_GBUFFER = ("        if (foliage_glow) { // bbport (r131a_foliage-translucency): cb 0 holds the world normals, cb 2 the albedo; arms its pass\n"
               "            foliage_glow->OnGBufferDraw(db_desc.first, cb_descs[0].first, cb_descs[2].first);\n        }\n")
EFF_LAMPS_ANCHOR = ("                if (glass_glint) { // bbport (r86b_glass-visible): the lamps of its glints (as drawn)\n"
                    "                    glass_glint->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights),\n"
                    "                                           tile_lights);\n                }\n")
EFF_LAMPS = ("                if (foliage_glow) { // bbport (r131a_foliage-translucency): the lamps the back-lit glow takes (as drawn)\n"
             "                    foliage_glow->AddLights(flickered ? flickered : reinterpret_cast<const u32*>(lights), tile_lights);\n                }\n")
EFF_SUN_ANCHOR = ("            if (caustics) {\n                caustics->OnShadowResolve(cb_descs[0].first, light.world, light.valid);\n            }\n")
EFF_SUN = ("            if (foliage_glow) { // bbport (r131a_foliage-translucency): the sun's or moon's direction for the glow\n"
           "                foliage_glow->OnSun(light.world, light.valid);\n            }\n")
EFF_SETS_ANCHOR = ("                caustics->OnLightSets(reinterpret_cast<const float*>(table), u32(bytes / 4),\n"
                   "                                      ps_info->images[0].GetSharp(*ps_info).Address());\n            }\n        }\n")
EFF_SETS = ("        // bbport (r131a_foliage-translucency): the light sets' table again for the glow's sun colour (the brightest set's light 0)\n"
            "        if (foliage_glow && !ps_info->buffers.empty() && !ps_info->buffers[0].IsSpecial()) {\n"
            "            const u64 skip = dc.push_data.buf_offsets[0] & 255u;\n"
            "            const u64 bytes = std::min<u64>(\n"
            "                dc.buffer_infos[0].range > skip ? dc.buffer_infos[0].range - skip : 0, 256ull * 288ull);\n"
            "            const VAddr table = ps_info->buffers[0].GetSharp(*ps_info).base_address;\n"
            "            if (bytes >= 288 && memory->IsValidGpuMapping(table, 0) && memory->ClampRangeSize(table, bytes) == bytes) {\n"
            "                foliage_glow->OnLightSets(reinterpret_cast<const float*>(table), u32(bytes / 4));\n"
            "            }\n        }\n")
EFF_APPLY_ANCHOR = "        caustics->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter(), wind.Get().wind);\n    }\n"
EFF_APPLY = ("    // bbport (r131a_foliage-translucency): the back-lit glow of leaves and grass, once after each G-buffer pass's opaque lighting, right after the\n"
             "    // caustics and before the blood sheen, the glass view and the drawn look (off: one null pointer test).\n"
             "    if (foliage_glow) {\n        foliage_glow->Apply(cb_descs[0].first, db_desc.first, upscaler->Jitter());\n    }\n")
EFF_END_ANCHOR = ("    if (glass_glint) { // bbport (r86b_glass-visible); a noted pane draw never made is forgotten\n"
                  "        glass_glint->OnFrameEnd();\n        glint_pending = nullptr;\n        glint_gpane_on = false; // bbport (r86i_glint-find-gbuffer)\n    }\n")
EFF_END = "    if (foliage_glow) { // bbport (r131a_foliage-translucency)\n        foliage_glow->OnFrameEnd();\n    }\n"

CPP_EDITS = {
RV + "vk_card_alpha.h": [
    ("rep", CA_BINDINGS_OLD, CA_BINDINGS_NEW),
    ("ins", "    vk::UniqueImageView layers_view;\n", "", CA_MEMBERS),
],
RV + "vk_card_alpha.cpp": [
    ("ins", CA_INC_OLD, "", CA_INC_NEW),
    ("ins", "constexpr vk::ImageSubresourceRange LayersRange{vk::ImageAspectFlagBits::eColor, 0, CardLayerMips,\n"
            "                                                0, CardLayerCount};\n", "", CA_RANGE),
    ("ins", "    layers_view.reset();\n", "", CA_DTOR),
    ("ins", "// The layers (CardLayersBytes), their views, the layer info and the fill pass: all once, at\n", CA_MAKECOLOUR, ""),
    ("rep", CA_FILL_OLD, CA_FILL_NEW),
    ("ins", "    const vk::DescriptorImageInfo dst2{{}, *level_views[2], vk::ImageLayout::eGeneral};\n", "", CA_DST3),
    ("rep", CA_CAPTURE_OLD, CA_CAPTURE_NEW),
    ("rep", CA_WRITE_OLD, CA_WRITE_NEW),
    ("rep", CA_PUSH_OLD, CA_PUSH_NEW),
],
RV + "vk_point_shadow.h": [
    ("ins", '#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)\n', "",
     '#include "video_core/renderer_vulkan/foliage_translucency.h" // bbport (r131a_foliage-translucency)\n'),
    ("ins", "    bool glass_mode = false;\n", "", PS_H_MEMBERS),
],
RV + "vk_point_shadow.cpp": [
    ("ins", '#include "video_core/host_shaders/point_shadow_ray_half_centred_cards_comp.h"\n', "", PS_INC),
    ("ins", "std::array<float, 16> Invert(const u32* words, bool& ok) {\n", PS_FOLIAGECODE, ""),
    ("rep", PS_MAKE_OLD, PS_MAKE_NEW),
    ("rep", PS_SPEC_OLD, PS_SPEC_NEW),
    ("ins", PS_READY_ANCHOR, "", PS_READY_ADD),
    ("rep", PS_COLOUR_OLD, PS_COLOUR_NEW),
    ("rep", PS_BINDINGS_OLD, PS_BINDINGS_NEW),
    ("ins", "        card_counts = std::make_unique<VideoCore::Buffer>(\n", PS_CARDWORDS, ""),
    ("rep", PS_BUF1_OLD, PS_BUF1_NEW),
    ("rep", PS_BUF2_OLD, PS_BUF2_NEW),
    ("rep", PS_BUF3_OLD, PS_BUF3_NEW),
    ("rep", PS_COPY_OLD, PS_COPY_NEW),
    ("rep", PS_COPY_CAPTURE_OLD, PS_COPY_CAPTURE_NEW),
] + [("rep", o, n) for o, n in PS_CALLS] + [
    ("rep", PS_SETCHECK_OLD, PS_SETCHECK_NEW),
    ("ins", "    card_set = set;\n    card_set_rows = r.rows;\n", PS_SETWRITE, ""),
    ("rep", PS_COLOURPASS_OLD, PS_COLOURPASS_NEW),
    ("rep", PS_GLASSFLAGS_OLD, PS_GLASSFLAGS_NEW),
    ("ins", "                rt_shadow.NoteGlassLightPass(glass_pass);\n            }\n", "", PS_FOLWORD),
    ("ins", "    card_last = now;\n    const auto counts = rt_shadow.TakeCardLampCounts();\n", "", PS_LINE),
],
RV + "vk_rt_shadow.h": [
    ("ins", '#include "video_core/renderer_vulkan/rt_card_sun.h" // bbport (r128c_lrt-cutout-props)\n', "", RS_H_INC),
    ("rep", RS_H_READERS_OLD, RS_H_READERS_NEW),
    ("rep", RS_H_R25_OLD, RS_H_R25_NEW),
    ("rep", RS_H_SUNUSE_OLD, RS_H_SUNUSE_NEW),
    ("ins", "    std::array<u32, CardSunWords> card_sun_last{}; ///< the counters' values at the last line\n", "", RS_H_MEMBERS),
],
RV + "vk_rt_shadow.cpp": [
    ("ins", '#include "video_core/host_shaders/rt_shadow_half_cards_comp.h" // bbport (r128c_lrt-cutout-props)\n', "", RS_INC),
    ("ins", "    if (raw_image) {\n        vmaDestroyImage(instance.GetAllocator(), raw_image, raw_allocation);\n    }\n", "", RS_DTOR),
    ("ins", "bool RtShadow::Record(const Inputs& in) {\n", RS_MAKEHUE, ""),
    ("rep", RS_READERS_OLD, RS_READERS_NEW),
    ("rep", RS_CREATE_OLD, RS_CREATE_NEW),
    ("ins", "    ++card_sun_cards;\n    use.pipeline = pipeline;\n", RS_SUNNOW_BEFORE, ""),
    ("ins", "    use.sampler = readers.sampler;\n", "", RS_SUNNOW_AFTER),
    ("rep", RS_PUSH_OLD, RS_PUSH_NEW),
    ("rep", RS_INIT_OLD, RS_INIT_NEW),
    ("ins", "    EffectPass::Mark(14, \"ray traced sun\");\n", RS_HUEFRAME, ""),
    ("ins", "            if (r25_clear) { // bbport (r25_rt-sun-trace): the counters start at zero\n", RS_HUECLEAR, ""),
    ("rep", RS_WRITES_OLD, RS_WRITES_NEW),
    ("rep", RS_WRITES_END_OLD, RS_WRITES_END_NEW),
    ("rep", RS_COUNT_OLD, RS_COUNT_NEW),
    ("ins", "            card_sun_cards = card_sun_plain = 0;\n        }\n", "", RS_LINE),
],
RV + "vk_rasterizer.h": [
    ("ins", '#include "video_core/renderer_vulkan/vk_glass_glint.h" // bbport (r86b_glass-visible)\n', "", RAST_H_INC),
    ("ins", "    std::unique_ptr<GlassGlint> glass_glint;\n", "", RAST_H_MEMBER),
],
RV + "vk_rasterizer.cpp": [
    ("ins", RAST_CTOR_ANCHOR, "", RAST_CTOR),
],
RF: [
    ("ins", EFF_GBUFFER_ANCHOR, "", EFF_GBUFFER),
    ("ins", EFF_LAMPS_ANCHOR, "", EFF_LAMPS),
    ("ins", EFF_SUN_ANCHOR, "", EFF_SUN),
    ("ins", EFF_SETS_ANCHOR, "", EFF_SETS),
    ("ins", EFF_APPLY_ANCHOR, "", EFF_APPLY),
    ("ins", EFF_END_ANCHOR, "", EFF_END),
],
}

# ---------------------------------------------------------------- build lists, tests, settings, menu, launcher, README
CM_INC = r'''    # bbport (r131a_foliage-translucency): the back-lit glow pass includes the card test and its own numbers (foliage_glow_layout.h, shared with C++)
    if (FILENAME MATCHES "^foliage_glow")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_cards.glsl ${SHADER_SRC}/rt_card_uv_layout.h
             ${SHADER_SRC}/foliage_glow_layout.h)
    endif()
'''
CM_BUILDS = r'''# bbport (r131a_foliage-translucency): graphics_foliage_translucency / BB_FOLIAGE_TRANSLUCENCY only: the light through leaves and the back-lit glow. Every
# build above is unchanged, byte for byte: each new form is behind a new define. The COLOUR form of the card alpha fill also writes the colour layers; the
# FOLIAGE form of each CARDS lamp build is CARDS=1 COLOUR=1 FOLIAGE=1 (the lamp's hue comes with the colour image); the sun trace's two CARDS builds get
# a FOLIAGE form (the hue image); the glow is one build.
add_host_shader(rt_card_alpha_fill.comp rt_card_alpha_fill_colour_comp COLOUR=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_cards_colour_foliage_comp CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_cards_colour_foliage_comp HALF=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_cards_colour_foliage_comp CENTRED=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_cards_colour_foliage_comp HALF=1 CENTRED=1 CARDS=1 COLOUR=1 FOLIAGE=1)
add_host_shader(rt_shadow.comp rt_shadow_cards_foliage_comp COVERAGE_SKIP=1 CARDS=1 FOLIAGE=1)
add_host_shader(rt_shadow.comp rt_shadow_half_cards_foliage_comp COVERAGE_SKIP=1 HALF=1 CARDS=1 FOLIAGE=1)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_cards_foliage_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_half_cards_foliage_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl
    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)
add_host_shader(foliage_glow.comp foliage_glow_comp)
'''
CM_TEST = r'''# bbport (r131a_foliage-translucency): the foliage translucency's knob rules, leaf pass and card ray rule (foliage_translucency.h); also built and run by
# engine/build.sh --test.
add_executable(foliage-translucency-test EXCLUDE_FROM_ALL ../tests/test_foliage_translucency.cpp)
target_compile_options(foliage-translucency-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(foliage-translucency-test PRIVATE ..)
'''
BS_TEST = ('    # bbport (r131a_foliage-translucency): the foliage translucency\'s knob rules, leaf pass and card ray rule\n'
           '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_foliage_translucency.cpp -o out/foliage-translucency-test\n'
           '    out/foliage-translucency-test\n')
EP_INC = '#include "video_core/host_shaders/rt_card_alpha_fill_colour_comp.h" // bbport (r131a_foliage-translucency)\n'
EP_ENTRY = ('        // bbport (r131a_foliage-translucency): the card alpha fill\'s COLOUR build, as vk_card_alpha.cpp makes it (CARD_FILL_PUSH_BYTES, 16 bytes; the\n'
            '        // colour layers are a fifth image). The ray query builds (lamp, sun, glow) need the ray tracing extensions and are not made here.\n'
            '        {"card alpha fill (colour)",\n'
            '         RT_CARD_ALPHA_FILL_COLOUR_COMP,\n'
            '         {eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage, eStorageImage},\n'
            '         16},\n')

SET_H_CONST = (
    "// bbport (r131a_foliage-translucency): the foliage translucency (graphics_foliage_translucency: 0 off, 1 light through leaves, 2 back-lit glow, 3 both;\n"
    "// restart; a set BB_FOLIAGE_TRANSLUCENCY, BB_FOLIAGE_LIGHT_THROUGH or BB_FOLIAGE_GLOW wins for its part). Tied to foliage_translucency.h by static_asserts\n"
    "// in vk_foliage_glow.cpp.\n"
    "inline constexpr int FoliageTranslucencyOff = 0, FoliageTranslucencyBoth = 3, FoliageTranslucencyDefault = 0;\n")
SET_H_ATOMIC = ("    std::atomic<int> graphics_foliage_translucency{FoliageTranslucencyDefault}; // 0 off, 1 light through leaves, 2 glow, 3 both, bbport (r131a): restart\n")
SET_H_START = ("    int startup_foliage_translucency = FoliageTranslucencyDefault; // bbport (r131a_foliage-translucency): what the render code uses\n")
SET_C_PARSE = ('    } else if (key == "graphics_foliage_translucency") { // bbport (r131a_foliage-translucency)\n'
               '        v.graphics_foliage_translucency = std::clamp(i, FoliageTranslucencyOff, FoliageTranslucencyBoth);\n')
SET_C_PUT = ('    put("graphics_foliage_translucency", std::to_string(std::clamp(v.graphics_foliage_translucency.load(), FoliageTranslucencyOff, '
             'FoliageTranslucencyBoth))); // bbport (r131a)\n')
SET_C_START = "    v.startup_foliage_translucency = v.graphics_foliage_translucency; // bbport (r131a_foliage-translucency)\n"

EN = {
    "ft_t": "Foliage translucency",
    "ft_c1": "Light through leaves",
    "ft_c2": "Back-lit glow",
    "ft_c3": "Both",
    "ft_h": "Off by default. Applied when the game restarts. Needs Ray traced foliage shadows: Lamps for the lamp parts, Lamps and sun for the "
            "sun and moon. Leaves and grass let a little light through, tinted by their own colour. Light through leaves: lamp, sun and moon "
            "shadows of leaves are softer and take the leaf colour. Back-lit glow: leaves and grass lit from behind glow in their own colour. "
            "Costs GPU time and video memory while on.",
}
TABLE_KEYS = ["ft_t", "ft_c1", "ft_c2", "ft_c3", "ft_h"]   # every one once per menu table ("Off" is in the tables)
LOC_KEYS = ["ft_t", "ft_c1", "ft_c2", "ft_c3"]                 # not in the json files yet ("Off" is)
TABLE_NAMES = ["kSpanish", "kPortugueseBrazil", "kFrench", "kGerman", "kItalian", "kPolish", "kTurkish", "kChinese"]
LOC_CODES = ["de", "es", "fr", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "uk", "zh-CN", "zh-TW"]
H2_PREFIX = '    {"Live, Red by default. The colour of the wet shine.'
LOC_ANCHOR_KEY = '  "Grey (test)": '
END_OVERLAY_FOLIAGE = "    // r131b: end of the foliage shadows row (a later row anchors after this line)\n"
END_GP = "            // r131b: end (a later row anchors here)\n"
END_OVERLAY_R131A = "    // r131a: end of the foliage translucency row\n"
LOC = "launcher/windows/BloodborneLauncher/Localization/"
LW = "launcher/windows/"
GP_B = LW + "BloodborneLauncher/Views/GraphicsPage.cs"
GP_L = LW + "LanternLauncher/Views/GraphicsPage.cs"
INI_FILE = LW + "BloodborneLauncher/Core/IniFile.cs"
CHOICES = LW + "BloodborneLauncher/Core/Choices.cs"
SHIM = "engine/gpu/shim/"
SETTINGS_H = SHIM + "bbport_settings.h"
SETTINGS_C = SHIM + "bbport_settings.cpp"
OVERLAY = SHIM + "bbport_overlay.cpp"
I18N = SHIM + "bbport_menu_i18n.cpp"
T_SETTINGS = "engine/tests/test_settings.cpp"
T_EFFECT = "engine/tests/test_effect_pipelines.cpp"


def cpp_lit(text, indent, width=84):
    """text as adjacent C++ string literals, one per line (the join is exactly the text)."""
    words = text.split(" ")
    pieces, cur = [], ""
    for i, w in enumerate(words):
        add = w + (" " if i < len(words) - 1 else "")
        if cur and len(cur) + len(add) > width:
            pieces.append(cur)
            cur = ""
        cur += add
    pieces.append(cur)
    assert "".join(pieces) == text and all('"' not in p and "\\" not in p for p in pieces)
    return "\n".join(" " * indent + '"' + p + '"' for p in pieces)


OVERLAY_ROW = (
    "    // bbport (r131a_foliage-translucency): the foliage translucency (BB_FOLIAGE_TRANSLUCENCY as a setting): 0 off, 1 light through leaves, 2 back-lit\n"
    "    // glow, 3 both. Read once when the game starts (restart note). It needs the ray traced foliage shadows above (BB_RT_CARD_ALPHA=2; the lamp parts\n"
    "    // BB_RT_CARD_LAMPS=1, the sun part BB_RT_CARD_SUN=1). Each variable that is set and not empty decides for its part (EnvNote).\n"
    '    if (const char* label = Item("%s")) {\n' % EN["ft_t"] +
    '        const char* names[] = {BbSettings::MenuText("Off"), BbSettings::MenuText("%s"),\n' % EN["ft_c1"] +
    '                               BbSettings::MenuText("%s"), BbSettings::MenuText("%s")};\n' % (EN["ft_c2"], EN["ft_c3"]) +
    "        int mode = std::clamp(s.graphics_foliage_translucency.load(), BbSettings::FoliageTranslucencyOff,\n"
    "                              BbSettings::FoliageTranslucencyBoth);\n"
    "        const bool changed = ImGui::Combo(label, &mode, names, BbSettings::FoliageTranslucencyBoth + 1);\n"
    "        Store(s.graphics_foliage_translucency, mode, changed);\n"
    "        Hint(BbSettings::MenuText(\n" + cpp_lit(EN["ft_h"], 12) + "));\n"
    "        if (s.graphics_foliage_translucency != s.startup_foliage_translucency) {\n"
    '            ImGui::TextDisabled("%s", BbSettings::MenuText("Applied when the game restarts.",\n'
    '                                                           "Применяется после перезапуска игры."));\n'
    "        }\n"
    '        EnvNote("BB_FOLIAGE_TRANSLUCENCY");\n'
    '        EnvNote("BB_FOLIAGE_LIGHT_THROUGH");\n'
    '        EnvNote("BB_FOLIAGE_GLOW");\n'
    "    }\n" + END_OVERLAY_R131A)
OVERLAY_FOOTER = "        s.graphics_foliage_translucency != s.startup_foliage_translucency || // bbport (r131a_foliage-translucency)\n"

T_SETTINGS_BLOCK = r"""    // bbport (r131a_foliage-translucency): graphics_foliage_translucency (0 to 3; restart): the default 0, read (and the start copy), written back, a value
    // out of range is the nearest end and text is 0.
    static_assert(BbSettings::FoliageTranslucencyOff == 0 && BbSettings::FoliageTranslucencyBoth == 3 &&
                  BbSettings::FoliageTranslucencyDefault == 0);
    { std::ofstream file(path); file << "graphics_foliage_translucency=3\n"; }
    BbSettings::Load();
    assert(s.graphics_foliage_translucency == 3 && s.startup_foliage_translucency == 3);
    s.graphics_foliage_translucency = 1;
    BbSettings::Save();
    assert(Read(path).find("graphics_foliage_translucency=1\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_foliage_translucency=9\n"; }
    BbSettings::Load();
    assert(s.graphics_foliage_translucency == BbSettings::FoliageTranslucencyBoth);
    { std::ofstream file(path); file << "graphics_foliage_translucency=-3\n"; }
    BbSettings::Load();
    assert(s.graphics_foliage_translucency == BbSettings::FoliageTranslucencyOff);
    { std::ofstream file(path); file << "graphics_foliage_translucency=abc\n"; }
    s.graphics_foliage_translucency = 2;
    BbSettings::Load();
    assert(s.graphics_foliage_translucency == BbSettings::FoliageTranslucencyDefault);
    BbSettings::Save();
"""

INI_BLOCK = ("            // r131a: the foliage translucency, the engine's default (BbSettings::FoliageTranslucencyDefault).\n"
             '            ("graphics_foliage_translucency", "0"),\n')
GP_BLOCK = ("            // r131a: the foliage translucency (applied at the start; needs the ray traced foliage shadows above); the in-game menu has the same row.\n"
            '            IniCombo(SymbolRegular.Lightbulb24, L.T("Foliage translucency"), L.T("Applied when the game starts"), Choices.FoliageTranslucency, '
            '"graphics_foliage_translucency");\n')
CHOICES_BLOCK = (
    "        /// <summary>graphics_foliage_translucency (r131a): 0 off, 1 light through leaves, 2 the back-lit glow, 3 both. The engine reads it when the game\n"
    "        /// starts; it needs the ray traced foliage shadows (Lamps, or Lamps and sun); BB_FOLIAGE_TRANSLUCENCY wins when set.</summary>\n"
    "        public static readonly Choice[] FoliageTranslucency =\n"
    "        {\n"
    '            new(L.T("Off"), "0"),\n'
    '            new(L.T("Light through leaves"), "1"),\n'
    '            new(L.T("Back-lit glow"), "2"),\n'
    '            new(L.T("Both"), "3"),\n'
    "        };\n\n")

README_ANCHOR = "| `BB_RT_CARD_SUN` | FEATURE (r128c)"
README_ROWS = (
    "| `graphics_foliage_translucency` | `lantern.ini` key (r131a_foliage-translucency): the foliage translucency as one setting, 0 to 3, read once when the game "
    "starts: `0` off (the default); `1` light through leaves; `2` the back-lit glow; `3` both. It needs the ray traced foliage shadows (`graphics_rt_foliage_shadows`: "
    "`BB_RT_CARD_ALPHA=2`; the lamp parts also `BB_RT_CARD_LAMPS=1`, the sun and moon part `BB_RT_CARD_SUN=1`); without them the start line says what is missing. "
    "`BB_FOLIAGE_TRANSLUCENCY` (exactly `1` is on) wins over the key and, with no sub-switch, turns both parts on; `BB_FOLIAGE_LIGHT_THROUGH` and `BB_FOLIAGE_GLOW` (exactly "
    "`1`) decide for their part. A value outside the range is the nearest end, text is `0`. Menu: **Insert**, Foliage translucency (a restart note shows); launcher: "
    "Graphics > Lighting. Cost, an estimate (not measured): off 0 (every shader build is unchanged, no object is made); on about 0.3 to 0.75 ms and 10 to 35 MB at 1080p "
    "internal | `0` |\n"
    "| `BB_FOLIAGE_TRANSLUCENCY` | FEATURE (r131a_foliage-translucency), owner ask: make each blade of grass and leaf slightly transparent so the light can change its "
    "colour, like subsurface scattering, for the sun, the moon and lamps. (A) Light through leaves: a ray that reaches a kept leaf texel passes a share `T` of its light "
    "(`BB_FOLIAGE_PASS`, 0.05 to 0.5, default 0.25: the luma share), tinted by the leaf (`BB_FOLIAGE_TINT` 0 to 1, default 1: how much of the leaf's hue), and goes on; a "
    "product below `BB_FOLIAGE_FLOOR` (default 0.02) blocks as before. Lamps: the ray traced lamp pass takes the leaf's hue for the two strongest lamps of a pixel (the weaker "
    "lamps stay grey); the sun and moon: the grey part goes through the game's own sun light (softer weed and tree shadows), and the hue is added by (B)'s pass as a term "
    "of zero luma (without it the log says the sun is grey). The colour comes from a 64 x 64 RGBA8 layer a card texture (2 MiB), at 1/4 the alpha layers' size; a texture "
    "whose cut-out lane is not its alpha passes grey (the log counts it). (B) Back-lit glow: leaves and grass lit from behind gain light colour x leaf albedo x "
    "`BB_FOLIAGE_GLOW_STRENGTH` (default 1) x `T` x back-lit factor (`BB_FOLIAGE_WRAP`, 0 to 1, default 0.3) x visibility, for the sun and moon (the brightest light set's colour; "
    "`BB_FOLIAGE_SUN_K`, default 0.318, the game's diffuse scale, a guess) and the two strongest lamps; a leaf is found by a short camera ray against the cut-out cards "
    "(the capture, not a G-buffer bit). Honest name: thin-leaf diffuse transmission on the front leaf in screen space, not volumetric subsurface scattering. "
    "`BB_FOLIAGE_GLOW_VIEW=1` (TOOL) shows the added term x8 over a dim scene. Log lines: `Foliage translucency (r131a)` once, `Foliage light (r131a)` and `Foliage glow "
    "(r131a)` every 600 frames while on (0 and no GPU work when off). Off: no new shader build is selected and the picture is byte for byte what it was | off |\n")


# ---------------------------------------------------------------- the edit lists
# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old).
STATIC = {}
STATIC.update(SHADER_EDITS)
STATIC.update(CPP_EDITS)
STATIC[CM] = [
    ("ins", "    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)\n", CM_INC, ""),
    ("ins", "add_custom_command(OUTPUT ${SHADER_DIR}/rt_shadow_half_cards_comp.h APPEND DEPENDS ${SHADER_SRC}/rt_cards.glsl\n"
            "    ${SHADER_SRC}/rt_card_layers_layout.h ${SHADER_SRC}/rt_card_uv_layout.h ${SHADER_SRC}/rt_card_sun_layout.h)\n", "", CM_BUILDS),
    ("ins", "target_include_directories(glass-light-forward-test PRIVATE ..)\n", "", CM_TEST),
]
STATIC[BS] = [("ins", "    out/glass-light-forward-test\n", "", BS_TEST)]
STATIC[T_EFFECT] = [
    ("ins", '#include "video_core/host_shaders/caustics_comp.h" // bbport (r107_caustics)\n', "", EP_INC),
    ("ins", '        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},\n', EP_ENTRY, ""),
]
STATIC[SETTINGS_H] = [
    ("ins", "inline constexpr int BloodSheenTintMin = 0, BloodSheenTintMax = 2, BloodSheenTintDefault = 1;\n", "", SET_H_CONST),
    ("ins", "    std::atomic<int> graphics_blood_sheen_tint{BloodSheenTintDefault}; // 0 grey test, 1 red, 2 clear film, bbport (r131b): live\n", "", SET_H_ATOMIC),
    ("ins", "    float startup_blood_sheen = BloodSheenDefault;     // bbport (r131b): for the menu's restart note\n", "", SET_H_START),
]
STATIC[SETTINGS_C] = [
    ("ins", '        v.graphics_blood_sheen_tint = value == "0" ? 0 : value == "2" ? 2 : 1;\n', "", SET_C_PARSE),
    ("ins", '    put("graphics_blood_sheen_tint", std::to_string(std::clamp(v.graphics_blood_sheen_tint.load(), BloodSheenTintMin, BloodSheenTintMax)));\n',
     "", SET_C_PUT),
    ("ins", "    v.startup_blood_sheen = v.graphics_blood_sheen;\n", "", SET_C_START),
]
STATIC[OVERLAY] = [
    ("ins", END_OVERLAY_FOLIAGE, "", OVERLAY_ROW),
    ("ins", "        s.graphics_rt_foliage_shadows != s.startup_rt_foliage_shadows || // bbport (r131b_lrt-settings)\n", "", OVERLAY_FOOTER),
]
STATIC[T_SETTINGS] = [("ins", "    // bbport (r128b_lrt-caustics-water): the water caustics' strengths. Nothing above sets them", T_SETTINGS_BLOCK, "")]
STATIC[INI_FILE] = [("ins", '            ("graphics_blood_sheen_tint", "1"),\n', "", INI_BLOCK)]
STATIC[GP_B] = [("ins", END_GP, "", GP_BLOCK)]
STATIC[GP_L] = [("ins", END_GP, "", GP_BLOCK)]
STATIC[CHOICES] = [("ins", "        public static readonly Choice[] FpsModes =\n", CHOICES_BLOCK, "")]
STATIC[R] = [("ins", README_ANCHOR, README_ROWS, "")]

DYNAMIC = [I18N] + [LOC + code + ".json" for code in LOC_CODES]


def table_span(text, name):
    start = text.find("constexpr Entry %s[] = {" % name)
    if start < 0:
        raise SystemExit("REFUSED: %s: table %s not found" % (I18N, name))
    return text[start:text.index("\n};", start)] + "\n"


def derived_line(text, start, where):
    """the one whole line (with its newline) that begins with `start` in text, else a refusal naming `where`"""
    hits = [l + "\n" for l in text.split("\n") if l.startswith(start)]
    if len(hits) != 1:
        raise SystemExit("REFUSED: %s: the line %r found %d times (r131b applied?)" % (where, start[:50], len(hits)))
    return hits[0]


def dynamic_edits(path, text):
    if path == I18N:
        entries = "".join('    {"%s", "%s"},\n' % (EN[k], EN[k]) for k in TABLE_KEYS)
        eds = []
        for name in TABLE_NAMES:
            # a first comment line makes each table's block its own (every block must be found exactly once in the file); the anchor is the comment
            # line of r131b's block in the same table (its entries are English in every table, so the lines themselves repeat)
            block = "    // r131a_foliage-translucency (%s): new strings, English until translated\n" % name + entries
            marker = "    // r131b_lrt-settings (%s): new strings, English until translated\n" % name
            if table_span(text, name).count(marker) != 1:
                raise SystemExit("REFUSED: %s: r131b's block of %s not found once (r131b applied?)" % (I18N, name))
            eds.append(("ins", marker, block, ""))
        return eds
    anchor = derived_line(text, LOC_ANCHOR_KEY, path)
    return [("ins", anchor, "", "".join('  "%s": "%s",\n' % (EN[k], EN[k]) for k in LOC_KEYS))]


def edits_for(path, text):
    return dynamic_edits(path, text) if path in DYNAMIC else STATIC[path]


ALL_PATHS = list(STATIC) + DYNAMIC


# ---------------------------------------------------------------- machinery
def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        raise SystemExit("REFUSED: %s not found under %s" % (path, ROOT))
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    # a byte order mark is kept: decode as utf-8-sig would drop it, so it is split off and put back
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    return raw, ("\r\n" if crlf else "\n"), raw[len(bom):].decode("utf-8").replace("\r\n", "\n"), bom


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read()
    if raw == NEW[path].replace("\n", "\r\n").encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists and is not the one this patch writes" % path)


def new_lines_check(label, text, limit=180):
    for n, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            raise SystemExit("text check: %s line %d holds a tab" % (label, n))
        if len(line) > limit:
            raise SystemExit("text check: %s line %d is %d columns (%d at most)" % (label, n, len(line), limit))


def edit_texts(eds):
    for e in eds:
        yield from (e[2] + e[3],) if e[0] == "ins" else (e[2],)


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r" % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r" % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def need(cond, message):
    if not cond:
        raise SystemExit("text check: " + message)


def texts_check(texts, news):
    for path, text in news.items():
        new_lines_check(path, text)
        need("—" not in text, "%s holds an em dash" % path)
    for path, text in texts.items():
        for t in edit_texts(edits_for(path, text)):
            new_lines_check(path + " (edited)", t, 100000 if path in (R, I18N, CM, BS) or path.endswith(".json") else 180)  # table rows and strings are long
            need("—" not in t, "an edit of %s holds an em dash" % path)
    # log lines: every printf this patch adds starts with an r131a prefix
    prefixes = ('"Foliage translucency (r131a)', '"Foliage light (r131a)', '"Foliage glow (r131a)')
    mine = [(p, t) for p in STATIC if p.endswith(".cpp") for t in edit_texts(STATIC[p])] + [(p, t) for p, t in news.items() if p.endswith(".cpp")]
    seen = 0
    for path, t in mine:
        lines = t.split("\n")
        for i, line in enumerate(lines):
            if "std::printf(" in line:
                rest = line.split("std::printf(", 1)[1].strip()
                if not rest:  # the text is on the next line
                    rest = lines[i + 1].strip() if i + 1 < len(lines) else ""
                need(rest.startswith(prefixes), "a log line in %s does not start with an r131a prefix: %s" % (path, line.strip()))
                seen += 1
    need(seen >= 9, "too few r131a log lines (%d)" % seen)
    # shaders: every edit of an existing shader is behind a new define (or only #define lines, or the include of a new file's layout)
    for path in SHADER_EDITS:
        for e in SHADER_EDITS[path]:
            body = "".join(edit_texts([e]))
            if path.endswith("_layout.h"):
                need(all(l.startswith("#define") or l.startswith("//") or not l.strip() for l in body.split("\n")), "%s: not only #define lines" % path)
                continue
            first = body.lstrip().split("\n", 1)[0]
            ok = first.startswith(("#ifdef FOLIAGE", "#ifdef CARD_TRANSMIT", "#ifdef COLOUR", "#elif defined(FOLIAGE)", "// bbport (r131a")) or \
                body.lstrip().startswith("#ifdef")
            need(ok, "%s: a shader edit is not behind a new define: %r" % (path, body[:70]))
            need("#ifdef FOLIAGE" in body or "#elif defined(FOLIAGE)" in body or "#ifdef CARD_TRANSMIT" in body or "#ifdef COLOUR" in body,
                 "%s: a shader edit names no new define: %r" % (path, body[:70]))
    # the new files hold what the draft names
    need(news[RV + "foliage_translucency.h"].count("[[nodiscard]] bool Glow();") == 1, "foliage_translucency.h: Glow")
    lay = news[HS + "foliage_glow_layout.h"]
    for want in ("FG_MAX_LAMPS 32", "FG_DATA_WORDS 264", "FG_COUNTER_WORDS 8", "FG_PUSH_BYTES 112"):
        need(lay.count("#define " + want + "\n") == 1, "foliage_glow_layout.h: %s" % want)
    # off: the new object is only made behind Wanted, the lamp and sun builds only behind their switches
    rast = "".join(edit_texts(STATIC[RV + "vk_rasterizer.cpp"]))
    need("if (FoliageGlow::Wanted()) {" in rast, "the rasterizer makes the glow only when it is wanted")
    ps = "".join(edit_texts(STATIC[RV + "vk_point_shadow.cpp"]))
    need("foliage_mode = FoliageTranslucency::LampThrough();" in ps and "FoliageCode(foliage_mode," in ps, "the lamp pass selects FOLIAGE builds only in foliage_mode")
    rs = "".join(edit_texts(STATIC[RV + "vk_rt_shadow.cpp"]))
    need("const bool foliage = FoliageTranslucency::SunThrough();" in rs, "the sun trace selects FOLIAGE builds only with SunThrough")
    ca = "".join(edit_texts(STATIC[RV + "vk_card_alpha.cpp"]))
    need("colour_on = FoliageTranslucency::LightThrough() && MakeColour();" in ca, "the colour layers are made only with LightThrough")
    # the build list: eight new builds, the test, no existing line touched
    cm = "".join(edit_texts(STATIC[CM]))
    need(cm.count("add_host_shader(") == 8, "CMakeLists.txt: eight new shader builds")
    need(sum(1 for l in cm.split("\n") if l.startswith("add_host_shader(") and "FOLIAGE=1" in l) == 6, "CMakeLists.txt: six FOLIAGE builds")
    for name in ("rt_card_alpha_fill_colour_comp", "point_shadow_ray_cards_colour_foliage_comp", "point_shadow_ray_half_cards_colour_foliage_comp",
                 "point_shadow_ray_centred_cards_colour_foliage_comp", "point_shadow_ray_half_centred_cards_colour_foliage_comp",
                 "rt_shadow_cards_foliage_comp", "rt_shadow_half_cards_foliage_comp", "foliage_glow_comp"):
        need(cm.count(" " + name) >= 1, "CMakeLists.txt: build %s" % name)
    # the ini key: settings, menu, launcher, README, once each
    need("graphics_foliage_translucency" in "".join(edit_texts(STATIC[SETTINGS_C])), "settings: the key")
    need('EnvNote("BB_FOLIAGE_TRANSLUCENCY");' in "".join(edit_texts(STATIC[OVERLAY])), "the menu row")
    need("Choices.FoliageTranslucency" in "".join(edit_texts(STATIC[GP_B])), "the launcher row")
    # not these (r131c's or r130c's): the glass record write and the glass registry
    for path in ALL_PATHS + list(NEW):
        need("glass_registry" not in path and "glass_view" not in path and "glass_clear" not in path, "%s must not be touched by this patch" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R131A_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, NEED)):
        raise SystemExit("%s is missing: r130g_glass-light-forward must be applied first" % NEED)
    if END_OVERLAY_FOLIAGE not in load(OVERLAY)[2] and OVERLAY_ROW not in load(OVERLAY)[2]:
        raise SystemExit("the r131b end marker is missing in %s: r131b_lrt-settings must be applied first" % OVERLAY)
    plan = []
    for path in ALL_PATHS:
        raw, eol, cur, bom = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, bom, state_of(cur, eds, path)))
    new_plan = [(path, new_state(path)) for path in NEW]
    states = {p[6] for p in plan} | {s for _, s in new_plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[6]) for p in plan if p[6] != plan[0][6]) + ", " +
                         ", ".join("%s %s" % p for p in new_plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, bom, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    def all_checks(texts):
        texts_check(texts, NEW)

    if cmd == "check":
        if state == "applied":
            all_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            all_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        all_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, bom, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        writes = [(os.path.join(ROOT, path), bom + texts[path].replace("\n", eol).encode("utf-8")) for path, eds, raw, eol, cur, bom, _ in plan]
        writes += [(os.path.join(ROOT, path), text.replace("\n", "\r\n").encode("utf-8")) for path, text in NEW.items()]
        for full, data in writes:
            open(full + ".r131atmp", "wb").write(data)
        for full, data in writes:
            os.replace(full + ".r131atmp", full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, bom, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, edits_for(path, cur), path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = bom + cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, bom, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + ".r131atmp", "wb").write(out[path])
        os.replace(full + ".r131atmp", full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
