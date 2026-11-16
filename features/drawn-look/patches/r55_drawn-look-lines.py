# r55_drawn-look-lines: the drawn look's first ink, and two cleanups the maintainer's rules ask
# for. (A) The test view leaves lantern.ini: graphics_drawn_look_debug is no key any more, the
# view is BB_DRAWN_LOOK_VIEW only. (B) The drawn look's menu texts get their rows in all eight
# translation tables. (C) Ink lines along the silhouettes of shapes (host_shaders/paint_ink.comp,
# new), with a menu row "Drawn look ink lines" (graphics_drawn_look_ink_world, default 0.35), and
# the lines alone when the strokes' strength is 0. Off by default as the whole look is.
# check|apply|revert (revert restores byte for byte). On top of <tree> as it is on
# 2026-11-15. The tree: the one the environment variable R55_ROOT names; without it the current
# directory. Nothing is changed in place: every new text is written beside its target and moved
# over it, and a failure puts back what was already moved. Files keep their line ends; the two new
# files are written with CRLF.
#
# WHY. The owner's drawn look (r45, r45b) paints strokes; the ink was left for later, and its
# menu texts were in English and Russian only. A test view saved in the ini would stay on after a
# restart (the maintainer's rule: test views and debug knobs are environment variables).
#
# WHAT.
#  1. drawn_look_params.h: Knobs::ink_world 0.35 (was 0, unread) and line_scale; Wanted(on,
#     strength, ink_world); Passes and PassesFor (strokes with a strength or in a stroke test
#     view; the colour lock after them without a test view; ink with ink_world > 0 or in view 3,
#     never on a frame painted right before the upscaler; view 3 lays no strokes); LineScaleOf
#     (BB_DRAWN_LOOK_LINE); MakeInk (the ink pass's block: the frame's, with strength = ink_world,
#     1 in view 3, brush = outlines, characters = line scale); InkSharpen(the weight of the ink
#     lines recorded on the frame). View 3 is the ink page.
#  2. host_shaders/paint_ink.comp (new) and CMakeLists.txt's add_host_shader line. Per pixel that
#     is not sky: taps at whole pixels along 4 axes, both ways, out to a pixel past the line's
#     width, read the depth; a tap counts when it lies beyond the pixel's own plane (normal from
#     the depth, as paint_strokes.comp's depthNormal) by 2..6 % of the pixel's depth (the plane's
#     prediction moves at most 4 % of the depth a 1080-line pixel). A jump of 30 % or more inks
#     fully, a step of 5 % or less half. The line lies on the near side. Beyond on both sides of
#     an axis within the taps (something narrower than about twice the line): half the weight
#     along that axis, smoothly. Width 1.5 pixels of a 1080-line scene, narrowing from 4 m with
#     the square root of the distance to half; that width, in 1080-line pixels and without the
#     line scale, under 1 makes the line fainter (none at 0.6), so where lines show does not
#     depend on the render size or BB_DRAWN_LOOK_LINE. In the scene's pixels the width is times
#     height / 1080 and the line scale; under one pixel it is drawn one pixel wide at that share
#     of its weight. Lines fade between 40 and 120 m. A line pixel is rgb * mix(1, f, weight),
#     f = min(0.3 own, 0.05 key) / own: its hue stays, the same at any exposure. What glows
#     (paint_strokes.comp's rule: 4 stops over the key and 1 over its place) gets none. The
#     alpha is kept; the sky, a scene colour that is no number and a result that is none are not
#     written.
#  3. vk_drawn_look.cpp/.h: the ink pass made in Ready() with the others; Paint takes the knobs
#     before Ready() and asks PassesFor; lines alone right before the upscaler record nothing
#     (Result LinesOnlyLate, counted); the strokes' crumb only with strokes; the ink crumb last
#     (EffectPass::Mark(13, "drawn look ink"): BB_GPU_PROFILE's row "Lighting: drawn look ink").
#     BB_DRAWN_LOOK_LINE read once in the constructor. Knobs' defaults (all six) tied to
#     BbSettings' by a static_assert. Wanted(): the switch and (strength > 0 or ink_world > 0).
#     The problems it names are bbport_drawn_look_texts.h's. A frame that records the ink pass
#     sets BbSettings' drawn_look_ink_drawn to the lines' weight; OnFrameEnd sets it back to 0.
#  4. vk_temporal_upscaler.cpp ExtraSharpenStrength: on a frame with ink lines (drawn_look_ink_drawn
#     above 0) the extra sharpening is multiplied by 1 - 0.5 * that weight (it sharpens the lines
#     as any edge); on every other frame it is as before.
#  5. bbport_settings.h/.cpp: graphics_drawn_look_debug gone (struct, Set, Save, the
#     DrawnLookDebugMax constant); an ini line of it is kept by Save as any unknown line and not
#     read. DrawnLookInkWorldDefault 0.35, DrawnLookStrokeSizeDefault and DrawnLookTextureDefault
#     1: the atomics' defaults and the fallbacks for no number. drawn_look_ink_drawn (no key).
#  6. bbport_drawn_look_texts.h (new): the look's menu texts, English and Russian, as constants
#     that bbport_overlay.cpp and vk_drawn_look.cpp use; RussianOf gives a problem's Russian.
#     bbport_overlay.cpp: the look's two hints say what this build does; a slider row "Drawn look
#     ink lines" 0..1 under the strength; a problem shown in Russian too. bbport_menu_i18n.cpp:
#     the section, the rows, the hints, the six problem texts and "Unavailable" (kChinese has it
#     already) in es, pt_BR, fr, de, it, pl, tr and zh (the Chinese checked against
#     LanternMenuSC-glyphs.txt).
#  7. Tests: tests/test_drawn_look_rules.cpp (new; target drawn-look-rules-test in CMakeLists.txt
#     and in build.sh --test, no GPU): Wanted, PassesFor, MakeInk, LineScaleOf, InkSharpen.
#     test_drawn_look.cpp (GPU): Run records as PassesFor says; the ink lines' checks at 1920x1080
#     (outlines inked, the far side and plain surfaces left, hue and alpha kept, the same at 8x
#     and 1/8x exposure and under 8 jitters, the default's share, line scale, after the strokes,
#     the ink page), at 960x540 and 2560x1440 (inked alike, ink with the width), and thin bars
#     (half the weight) in place of "view 3 shows the look". test_settings.cpp: the key gone, the
#     ink default; every text of bbport_drawn_look_texts.h in all eight tables (a hint reworded
#     without its translations fails settings-test). test_effect_pipelines.cpp: the ink pass, and
#     the look's push size 128 (was 112, stale since r45b).
#  8. README.md: the rows; the environment paragraph.
#
# SETTINGS AND KNOBS. graphics_drawn_look_ink_world 0..1, default 0.35, live, menu row "Drawn look
# ink lines" (every Save since r45 wrote it, unread, as 0.00: an existing lantern.ini holds 0.00,
# set the row once). BB_DRAWN_LOOK_VIEW=3: the ink page. BB_DRAWN_LOOK_LINE=0.5..2 (default 1):
# the lines' width in pixels. Neither is saved. A test view needs the strength or the ink lines
# above 0, as the look does.
#
# NOT DONE: lines on inner edges (creases, a wall's corner seen from inside: no depth jump),
# heavier ink on characters (graphics_drawn_look_outlines reaches the pass, unread), painted
# shadow edges, and the plan's later stages; ink on frames painted right before the upscaler; a
# limit on ink per area (thin things get half the weight, no more); no cost measured in the game.
# Older than this round and still open (rule 4): graphics_drawn_look_stroke_size, _texture,
# _characters, _outlines, _shadow_edges, _shadow_soft and _quality are saved keys with no menu or
# launcher row and no reset entry; there is no drawn-look reset list to add ink_world to
# ("Game's own picture" only turns the switch off).
#
# HOW TO TEST IN THE GAME. Same spawn and spot as the look's earlier tests, standing still,
# graphics_ao_quality=1: the look off; on with strength 0 and ink lines 0.35 (lines alone); ink
# 0.7; strength 0.6 with ink 0.35; BB_DRAWN_LOOK_VIEW=3; BB_DRAWN_LOOK_LINE=0.6 and 1.6; a railing
# or foliage crop; a DLSS mode with another render size. BB_GPU_PROFILE=1 BB_GPU_PROFILE_ROWS=250:
# the row "Lighting: drawn look ink".
#
# NOT CHANGED: point_shadow_ray.comp, lamp_shadow_tune.h, vk_point_shadow.h/.cpp,
# test_lamp_shadow_tune.cpp, test_rt_shadows.cpp, vk_rt_shadow.h/.cpp, emit_spirv_special.cpp,
# runtime_info.h, host_shaders/rt_*.comp, volumetric_light.comp, point_volumetric.comp and
# anything of the wind.

import os
import re
import sys

ROOT = os.environ.get("R55_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
VC = G + "shadps4/video_core/"
R = VC + "renderer_vulkan/"
HS = VC + "host_shaders/"
S = G + "shim/"
TESTS = E + "tests/"
GLYPHS = G + "third_party/fonts/LanternMenuSC-glyphs.txt"

TMP = ".r55tmp"  # a new text waits under this name beside its target (main)

# Other rounds' files: this one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "vk_rt_shadow.h", "vk_rt_shadow.cpp",
           "emit_spirv_special.cpp", "runtime_info.h", "volumetric_light.comp", "point_volumetric.comp")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or "wind" in name or (path.startswith(HS) and name.startswith("rt_"))


def B(s):
    """A block written from the line after the opening quotes."""
    return s[1:] if s.startswith("\n") else s


def lit(text, indent, width=100):
    """text as adjacent C++ string literals, one a line, each line at most `width` characters."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if cur and len(indent) + len(cand) + 3 > width:
            lines.append(cur + " ")
            cur = w
        else:
            cur = cand
    lines.append(cur)
    assert "".join(lines) == text and not any('"' in l or "\\" in l for l in lines)
    return "\n".join(indent + '"' + l + '"' for l in lines)


NEW_FILES = {
    HS + "paint_ink.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r55_drawn-look-lines): the drawn look's ink lines. Recorded by
// renderer_vulkan/vk_drawn_look.cpp after the strokes and the colour lock, or alone when the
// strokes' strength is 0 (lines only); not on a frame painted right before the upscaler, where
// fog and particles are already in the scene. It rewrites the scene colour's rgb in place and
// keeps the alpha. The sky is not written.
//
// A pixel gets ink where its surface stands in front of what lies behind it: taps along 4 axes,
// both ways, out to a pixel past the line's width, read the depth, and a tap counts when it is
// farther than the pixel's own plane, carried on to the tap, says it should be (by GAP of the
// pixel's depth). Only the depth decides, never the colour: a texture's cracks and joints get no
// line, and a cobble lip of 2 cm at 3 m is under GAP. The line lies on the near side, on the
// front surface's own pixels. Something that lies in front of what is behind it on both sides of
// an axis within those taps (narrower than about twice the line: a railing, a branch) gets half
// the weight along that axis. A line pixel's rgb is multiplied by mix(1, f, weight), with
// f = min(INK_OWN x its brightness, INK_KEY x the frame's key) / its brightness: one factor for
// the three channels, so its hue stays, and a scene twice as bright gets the same lines. What
// glows (the rule of paint_strokes.comp's keepOwn) gets no ink.
//
// The line's width is LINE_PX_ENV pixels of a 1080-line scene near the camera, narrowing with
// distance; how dark it is far away (`opacity`) is taken from that width in 1080-line pixels, so
// where lines show does not depend on the render size or on BB_DRAWN_LOOK_LINE. In this scene's
// pixels the width is times size.y / 1080 and LINE_SCALE; a line narrower than one pixel is
// drawn one pixel wide with its weight times its width.
//
// The block's words are the other passes' (paint_common.glsl); DrawnLookParams::MakeInk
// (drawn_look_params.h) gives three of its floats the meanings below.
//
// Test view 3 (BB_DRAWN_LOOK_VIEW=3, INK_WORLD 1): a page of the key's grey with the lines
// dark, key * (1 - weight), on every pixel that is not sky.
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

#define INK_WORLD strength    // graphics_drawn_look_ink_world, 0..1 (1 in test view 3)
#define INK_CHARS brush       // graphics_drawn_look_outlines: carried, not read yet
#define LINE_SCALE characters // BB_DRAWN_LOOK_LINE, 0.5..2 (1 without it)

// paint_prep.comp's copy and its smaller levels (rgb the scene before the strokes); its last
// level, one texel, holds the frame's key (paint_key.comp). Linear between texels and levels.
layout(binding = 0) uniform sampler2D prep_tex;
layout(binding = 1) uniform texture2D depth_tex; // depth 0..1 (D3D projection), 1: sky
layout(binding = 2, rgba16f) uniform image2D scene_img;

// A tap counts from the first share of the pixel's depth beyond its plane, fully from the
// second.
const vec2 GAP = vec2(0.02, 0.06);
// The plane's prediction may move the depth by at most this share of the pixel's depth per
// pixel of a 1080-line scene: an edge-on plane would predict any depth at all.
const float SLOPE_CAP = 0.04;
// A jump of the second share of the depth or more (a pillar against the far courtyard) inks
// fully; a step of the first or less (a ledge) inks half.
const vec2 BIG_JUMP = vec2(0.05, 0.30);
// A line's width in pixels of a 1080-line scene near the camera; from LINE_NEAR_M on it narrows
// with the square root of the distance, to half of it at four times that distance.
const float LINE_PX_ENV = 1.5;
const float LINE_NEAR_M = 4.0;
// Between these distances (metres) the lines fade out.
const vec2 ENV_FADE_M = vec2(40.0, 120.0);
// A fully inked pixel: its own brightness times INK_OWN, or the key times INK_KEY where that is
// darker.
const float INK_OWN = 0.30;
const float INK_KEY = 0.05;
// What glows, as paint_strokes.comp: this many stops over the key and over its place.
const vec2 GLOW_STOPS = vec2(4.0, 1.0);
// Beyond on the other side of an axis: from the first share (as a tap's count) the weight along
// the axis goes down, to THIN_WEIGHT from the second.
const vec2 THIN = vec2(0.3, 0.7);
const float THIN_WEIGHT = 0.5;
const uint VIEW_INK = 3u;

float depthAt(ivec2 p) {
    return texelFetch(depth_tex, p, 0).r;
}

// The view position seen at pixel p (sky as very far).
vec3 viewAt(ivec2 p) {
    const float d = depthAt(p);
    return viewPos(vec2(p) + 0.5, d >= 1.0 ? 1e6 : viewZ(d));
}

bool inside(ivec2 p) {
    return all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, ivec2(size)));
}

// The surface's step from the pixel to its neighbour along `step`: of the two neighbours the
// one nearer in depth (as depthNormal in paint_strokes.comp), so it does not lean across an
// edge; at the image's border the one inside.
vec3 tangent(ivec2 pixel, vec3 c, ivec2 step) {
    const ivec2 a = pixel - step, b = pixel + step;
    const bool a_in = inside(a), b_in = inside(b);
    const vec3 pa = a_in ? viewAt(a) : c;
    const vec3 pb = b_in ? viewAt(b) : c;
    if (!a_in) {
        return pb - c;
    }
    if (!b_in) {
        return c - pa;
    }
    return abs(pb.z - c.z) < abs(c.z - pa.z) ? pb - c : c - pa;
}

// The surface's normal from the depth around the pixel, view axes (its sign does not matter).
vec3 viewNormal(ivec2 pixel, vec3 c) {
    const vec3 n = cross(tangent(pixel, c, ivec2(0, 1)), tangent(pixel, c, ivec2(1, 0)));
    return dot(n, n) > 1e-12 ? normalize(n) : -normalize(c);
}

// How much the depth at pixel q lies beyond the plane (normal n, n . P = level) of the pixel
// at depth z, as a share 0..1 (GAP); `jump`: its depth over the pixel's, less 1. The sky is
// four times the pixel's depth. `apart`: the tap's distance in pixels.
float beyond(ivec2 q, vec3 n, float level, float z, float apart, float s, out float jump) {
    const float dq = depthAt(q);
    const float zq = dq >= 1.0 ? 4.0 * z : viewZ(dq);
    const float along = dot(n, viewPos(vec2(q) + 0.5, 1.0));
    const float zplane = abs(along) > 1e-4 ? level / along : z;
    const float limit = SLOPE_CAP * (apart / s) * z;
    const float zhat = z + clamp(zplane - z, -limit, limit);
    jump = (zq - z) / z;
    return smoothstep(GAP.x, GAP.y, (zq - zhat) / z);
}

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (pixel.x >= int(size.x) || pixel.y >= int(size.y)) {
        return;
    }
    const float depth = depthAt(pixel);
    if (depth >= 1.0) {
        return;
    }
    const bool page = ((flags >> 8u) & 7u) == VIEW_INK;
    const float s = size.y / 1080.0;
    const float z = viewZ(depth);
    const vec3 c = viewPos(vec2(pixel) + 0.5, z);
    const float d = length(c);
    // The width in pixels of a 1080-line scene at line scale 1; under one such pixel the line
    // fades (none at 0.6): from about 9 m on at the near width.
    const float narrowed = LINE_PX_ENV * clamp(sqrt(LINE_NEAR_M / d), 0.5, 1.0);
    const float opacity = smoothstep(0.6, 1.0, narrowed);
    // The width in this scene's pixels: the same share of the picture at every render size. A
    // line under one pixel is drawn one pixel wide (`drawn`) at the share `thinner` of its
    // weight: it does not jump from pixel to pixel with the jitter, and the ink along an edge
    // goes with the width.
    const float width = narrowed * s * LINE_SCALE;
    const float drawn = max(width, 1.0);
    const float thinner = min(width, 1.0);
    const float fade = 1.0 - smoothstep(ENV_FADE_M.x, ENV_FADE_M.y, d);
    float line = 0.0;
    if (opacity > 0.0 && fade > 0.0 && INK_WORLD > 0.0) {
        const vec3 n = viewNormal(pixel, c);
        const float level = dot(n, c);
        // Taps at whole pixels out to a pixel past the line; one pixel of the line a tap's way
        // across the edge is the share clamp(drawn + 1 - distance, 0, 1) of that pixel. A tap
        // past the line (share 0) only tells whether the other side lies beyond too.
        const int reach = int(min(ceil(drawn + 1.0), 7.0));
        const vec2 dirs[4] = vec2[4](vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.70710678, 0.70710678),
                                     vec2(0.70710678, -0.70710678));
        for (int i = 0; i < 4; ++i) {
            // la, lb: the line from the taps on each side; fa, fb: how far beyond each side lies
            // anywhere within reach.
            float la = 0.0, lb = 0.0, fa = 0.0, fb = 0.0;
            ivec2 last = ivec2(0);
            for (int r = 1; r <= reach; ++r) {
                const ivec2 o = ivec2(floor(dirs[i] * float(r) + 0.5));
                if (o == last) {
                    continue;
                }
                last = o;
                const float apart = length(vec2(o));
                const float cover = clamp(drawn + 1.0 - apart, 0.0, 1.0);
                const ivec2 qa = clamp(pixel + o, ivec2(0), ivec2(size) - 1);
                const ivec2 qb = clamp(pixel - o, ivec2(0), ivec2(size) - 1);
                float jump_a = 0.0, jump_b = 0.0;
                const float sa = qa != pixel ? beyond(qa, n, level, z, apart, s, jump_a) : 0.0;
                const float sb = qb != pixel ? beyond(qb, n, level, z, apart, s, jump_b) : 0.0;
                fa = max(fa, sa);
                fb = max(fb, sb);
                const float ka = mix(0.5, 1.0, smoothstep(BIG_JUMP.x, BIG_JUMP.y, jump_a));
                const float kb = mix(0.5, 1.0, smoothstep(BIG_JUMP.x, BIG_JUMP.y, jump_b));
                la = max(la, sa * cover * ka);
                lb = max(lb, sb * cover * kb);
            }
            line = max(line, la * mix(1.0, THIN_WEIGHT, smoothstep(THIN.x, THIN.y, fb)));
            line = max(line, lb * mix(1.0, THIN_WEIGHT, smoothstep(THIN.x, THIN.y, fa)));
        }
    }
    float weight = line * thinner * opacity * INK_WORLD * fade;
    if (weight <= 0.0 && !page) {
        return;
    }
    const vec4 scene = imageLoad(scene_img, pixel);
    // A scene colour that is no number stays what it is (the ink page draws over it).
    if (!page && any(isnan(scene.rgb))) {
        return;
    }
    const float own = dot(max(scene.rgb, 0.0), LUMA);
    const float key = textureLod(prep_tex, vec2(0.5), 99.0).r;
    const float black = blackLevel(key);
    // What glows: brighter than the key and than its place, around the pixel over a few pixels
    // and over a large place (about 1/270 and 1/17 of the picture's height), as keepOwn.
    const vec2 uv = (vec2(pixel) + 0.5) / size;
    const float lines = log2(size.y);
    const float near = dot(textureLod(prep_tex, uv, lines - 8.1).rgb, LUMA);
    const float place = dot(textureLod(prep_tex, uv, lines - 4.1).rgb, LUMA);
    const float top = max(own, near);
    const float glow = min(log2((top + black) / (key + black)) - GLOW_STOPS.x,
                           log2((top + black) / (place + black)) - GLOW_STOPS.y);
    weight *= 1.0 - smoothstep(0.0, 1.0, glow);
    vec3 result;
    if (page) {
        result = vec3(key) * (1.0 - weight);
    } else {
        if (weight <= 0.0) {
            return;
        }
        // One factor for all three channels (a channel under 0 included): the hue stays.
        const float factor = min(INK_OWN * own, INK_KEY * key) / max(own, black);
        result = scene.rgb * mix(1.0, factor, weight);
    }
    if (!any(isnan(result))) {
        imageStore(scene_img, pixel, vec4(result, scene.a));
    }
}
""",
    TESTS + "test_drawn_look_rules.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r55_drawn-look-lines): the drawn look's rules that need no GPU, from
// renderer_vulkan/drawn_look_params.h: when the look is wanted (DrawnLook::Wanted), which passes
// a painted frame records (PassesFor), the ink pass's words (MakeInk), BB_DRAWN_LOOK_LINE
// (LineScaleOf) and the factor on the upscaler's extra sharpening (InkSharpen). The passes
// themselves run in drawn-look-test, which needs a Vulkan GPU.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "gpu/shadps4/video_core/renderer_vulkan/drawn_look_params.h"

namespace Look = Vulkan::DrawnLookParams;

namespace {
Look::Knobs KnobsOf(float strength, float ink_world, int view) {
    Look::Knobs knobs;
    knobs.strength = strength;
    knobs.ink_world = ink_world;
    knobs.view = view;
    return knobs;
}

bool SameBits(float a, float b) {
    return std::memcmp(&a, &b, sizeof(float)) == 0;
}
} // namespace

int main() {
    // Wanted: the switch, and strokes or ink lines to draw.
    static_assert(!Look::Wanted(false, 1.0f, 1.0f));
    static_assert(!Look::Wanted(true, 0.0f, 0.0f));
    static_assert(Look::Wanted(true, 0.0f, 0.35f));
    static_assert(Look::Wanted(true, 0.6f, 0.0f));
    static_assert(Look::Wanted(true, 0.6f, 0.35f));
    static_assert(!Look::Wanted(false, 0.0f, 0.0f));
    assert(!Look::Wanted(true, NAN, NAN));

    // The defaults: the look's own and the ink's.
    static_assert(Look::Knobs{}.ink_world == 0.35f && Look::Knobs{}.line_scale == 1.0f &&
                  Look::Knobs{}.view == Look::ViewOff);

    // PassesFor: strokes with a strength or in a stroke test view; the lock after the strokes
    // without a test view; ink with ink lines or in the ink page, never right before the
    // upscaler; the ink page lays no strokes.
    for (const bool late : {false, true}) {
        for (const int view : {int(Look::ViewOff), int(Look::ViewStrokes), int(Look::ViewFine),
                               int(Look::ViewInk), int(Look::ViewBold)}) {
            for (const float strength : {0.0f, 0.6f}) {
                for (const float ink : {0.0f, 0.35f}) {
                    const Look::Passes p = Look::PassesFor(KnobsOf(strength, ink, view), late);
                    const bool page = view == Look::ViewInk;
                    assert(p.strokes == (!page && (strength > 0.0f || view != Look::ViewOff)));
                    assert(p.lock == (p.strokes && view == Look::ViewOff));
                    assert(p.ink == (!late && (ink > 0.0f || page)));
                }
            }
        }
    }
    // The cases the menu gives: strokes alone, lines alone, both; the frame painted right
    // before the upscaler with lines alone records nothing.
    {
        const auto strokes = Look::PassesFor(KnobsOf(0.6f, 0.0f, Look::ViewOff), false);
        assert(strokes.strokes && strokes.lock && !strokes.ink);
        const auto lines = Look::PassesFor(KnobsOf(0.0f, 0.35f, Look::ViewOff), false);
        assert(!lines.strokes && !lines.lock && lines.ink);
        const auto both = Look::PassesFor(KnobsOf(0.6f, 0.35f, Look::ViewOff), false);
        assert(both.strokes && both.lock && both.ink);
        const auto late = Look::PassesFor(KnobsOf(0.0f, 0.35f, Look::ViewOff), true);
        assert(!late.strokes && !late.lock && !late.ink);
        const auto page = Look::PassesFor(KnobsOf(0.6f, 0.0f, Look::ViewInk), false);
        assert(!page.strokes && !page.lock && page.ink);
        // A view outside the range is clamped as Make clamps it.
        const auto high = Look::PassesFor(KnobsOf(0.0f, 0.0f, 9), false);
        assert(high.strokes && !high.lock && !high.ink);
        const auto low = Look::PassesFor(KnobsOf(0.6f, 0.0f, -2), false);
        assert(low.strokes && low.lock);
    }

    // MakeInk: ink_world, outlines and the line scale in strength, brush and characters; every
    // other word as the frame's (the block is the other passes' block).
    {
        Look::Knobs knobs = KnobsOf(0.6f, 0.35f, Look::ViewOff);
        const std::array<float, 12> inv_view{1, 0, 0, 0.3f, 0, 1, 0, 1.6f, 0, 0, 1, -1.0f};
        const std::array<float, 4> proj{1.2f, 2.1f, 1.0f, -0.1f};
        const Look::Params look =
            Look::Make(knobs, inv_view, proj, 1920, 1080, {0.25f, -0.5f}, true, true);
        const Look::Params ink = Look::MakeInk(look, 0.35f, 0.8f, 1.6f);
        assert(ink.strength == 0.35f && ink.brush == 0.8f && ink.characters == 1.6f);
        Look::Params rest = ink;
        rest.strength = look.strength;
        rest.brush = look.brush;
        rest.characters = look.characters;
        assert(std::memcmp(&rest, &look, sizeof(Look::Params)) == 0);
        assert(ink.flags == look.flags && SameBits(ink.cell_fine, look.cell_fine) &&
               SameBits(ink.cell_bold, look.cell_bold));
        // The view stays in the flags: the ink page is read from them, and draws every line at
        // weight 1 whatever ink_world is (0 included).
        knobs.view = Look::ViewInk;
        for (const float ink_world : {0.0f, 0.35f}) {
            const Look::Params page = Look::MakeInk(
                Look::Make(knobs, inv_view, proj, 1920, 1080, {0.0f, 0.0f}, true, false),
                ink_world, 0.35f, 1.0f);
            assert(Look::ViewOf(page.flags) == std::uint32_t(Look::ViewInk) &&
                   page.strength == 1.0f);
        }
        static_assert(sizeof(Look::Params) == 128);
    }

    // BB_DRAWN_LOOK_LINE: 1 without it or without a number in it, else clamped to 0.5..2.
    assert(Look::LineScaleOf(nullptr) == 1.0f);
    assert(Look::LineScaleOf("") == 1.0f && Look::LineScaleOf("bold") == 1.0f);
    assert(Look::LineScaleOf("nan") == 1.0f && Look::LineScaleOf("inf") == 1.0f);
    assert(Look::LineScaleOf("0.6") == 0.6f && Look::LineScaleOf("1.6") == 1.6f);
    assert(Look::LineScaleOf("0.1") == Look::LineScaleMin &&
           Look::LineScaleOf("9") == Look::LineScaleMax);
    assert(Look::LineScaleOf("-3") == 0.5f && Look::LineScaleOf("2") == 2.0f);
    static_assert(Look::LineScaleMin == 0.5f && Look::LineScaleMax == 2.0f);

    // InkSharpen: 1 - 0.5 x the weight of the ink lines the frame recorded, 1 on a frame without
    // them (weight 0).
    static_assert(Look::InkSharpen(0.0f) == 1.0f && Look::InkSharpen(-1.0f) == 1.0f);
    static_assert(Look::InkSharpen(1.0f) == 0.5f && Look::InkSharpen(0.5f) == 0.75f);
    static_assert(Look::InkSharpen(7.0f) == 0.5f);
    assert(std::abs(Look::InkSharpen(0.35f) - 0.825f) < 1e-6f);
    assert(Look::InkSharpen(NAN) == 1.0f);

    std::puts("PASS: drawn look rules");
    return 0;
}
""",
}

INK_TEST = r"""    {
        // bbport (r55_drawn-look-lines): the ink lines (paint_ink.comp) on the lit scene at
        // 1920x1080, recorded as DrawnLookParams::PassesFor says: with the strokes' strength at
        // 0 the strokes and the lock do not run (lines only).
        const Scene lit = MakeScene(large, straight, Paint::Lit);
        const u32 w = large.width, h = large.height, count = w * h;
        const auto ratio = [](const Scene& in, const std::vector<Half4>& out, u32 i) {
            return double(Luminance(out[i])) / std::max(double(Luminance(in.colour[i])), 1e-12);
        };
        // A pixel whose 7x7 neighbourhood is all of its own surface.
        const auto plain = [&](const Scene& in, u32 i) {
            const int x = int(i % w), y = int(i / w);
            if (x < 3 || y < 3 || x + 3 >= int(w) || y + 3 >= int(h)) {
                return false;
            }
            for (int dy = -3; dy <= 3; ++dy) {
                for (int dx = -3; dx <= 3; ++dx) {
                    if (in.surface[u32(y + dy) * w + u32(x + dx)] != in.surface[i]) {
                        return false;
                    }
                }
            }
            return true;
        };
        // A pixel of `what` with a 4-neighbour that is farther and of `behind` (Sky: of any
        // other surface).
        const auto rim = [&](const Scene& in, u32 i, Surface what, Surface behind) {
            const int x = int(i % w), y = int(i / w);
            if (in.surface[i] != what || x < 1 || y < 1 || x + 1 >= int(w) || y + 1 >= int(h)) {
                return false;
            }
            for (const u32 j : {i - 1, i + 1, i - w, i + w}) {
                if (in.surface[j] != what && (behind == Sky || in.surface[j] == behind) &&
                    in.depth[j] > in.depth[i]) {
                    return true;
                }
            }
            return false;
        };
        const auto inked = [&](const Scene& in, const std::vector<Half4>& out, Surface what,
                               Surface behind, double most, u32& of) {
            u32 dark = 0;
            of = 0;
            for (u32 i = 0; i < count; ++i) {
                if (rim(in, i, what, behind)) {
                    ++of;
                    dark += ratio(in, out, i) <= most;
                }
            }
            return dark;
        };
        const auto hue = [](const Half4& pixel) {
            const Rgb c = Colour(pixel);
            const double sum = std::max(double(c[0]) + c[1] + c[2], 1e-12);
            return std::array<double, 3>{c[0] / sum, c[1] / sum, c[2] / sum};
        };
        const auto lines = gpu.Run(lit, Words(large, straight, Look::ViewOff, true, false, 0.0f),
                                   1.0f);

        u32 ball_of = 0, column_of = 0;
        const u32 ball_dark = inked(lit, lines, Ball, Sky, 0.65, ball_of);
        const u32 column_dark = inked(lit, lines, Column, BackWall, 0.65, column_of);
        u32 beside = 0, beside_changed = 0, floor_plain = 0, floor_changed = 0, column_plain = 0,
            column_changed = 0, changed = 0, brighter = 0, sky_changed = 0, alpha_changed = 0;
        double worst_hue = 0.0;
        for (u32 i = 0; i < count; ++i) {
            const bool same = lines[i] == lit.colour[i];
            alpha_changed += lines[i][3] != lit.colour[i][3];
            if (lit.surface[i] == Sky) {
                sky_changed += !same;
                continue;
            }
            if (!same) {
                ++changed;
                brighter += Luminance(lines[i]) >= Luminance(lit.colour[i]);
                const auto a = hue(lit.colour[i]), b = hue(lines[i]);
                for (int k = 0; k < 3; ++k) {
                    worst_hue = std::max(worst_hue, std::abs(a[k] - b[k]));
                }
            }
            if (plain(lit, i)) {
                if (lit.surface[i] == Floor) {
                    ++floor_plain;
                    floor_changed += !same;
                } else if (lit.surface[i] == Column) {
                    ++column_plain;
                    column_changed += !same;
                }
            }
            // Beside the ball and farther, with nothing else in its 7x7 neighbourhood.
            if (lit.surface[i] != Ball) {
                const int x = int(i % w), y = int(i / w);
                bool near_ball = false;
                bool alone = x >= 3 && y >= 3 && x + 3 < int(w) && y + 3 < int(h);
                for (const u32 j : {i - 1, i + 1, i - w, i + w}) {
                    near_ball |= j < count && lit.surface[j] == Ball && lit.depth[j] < lit.depth[i];
                }
                for (int dy = -3; alone && near_ball && dy <= 3; ++dy) {
                    for (int dx = -3; dx <= 3; ++dx) {
                        const Surface there = lit.surface[u32(y + dy) * w + u32(x + dx)];
                        alone &= there == Ball || there == lit.surface[i];
                    }
                }
                if (near_ball && alone) {
                    ++beside;
                    beside_changed += !same;
                }
            }
        }
        std::printf("ink lines alone (ink 1): %u of %u ball outline pixels at 0.65 of their "
                    "brightness or darker, %u of %u of the column's against the back wall; %u of "
                    "%u pixels beside the ball changed; %u of %u plain floor, %u of %u plain "
                    "column pixels changed; %u pixels changed, %u of them not darker, hue moved "
                    "by %.5f at most; %u sky pixels and %u alphas changed\n",
                    ball_dark, ball_of, column_dark, column_of, beside_changed, beside,
                    floor_changed, floor_plain, column_changed, column_plain, changed, brighter,
                    worst_hue, sky_changed, alpha_changed);
        Expect(ball_of > 500 && ball_dark >= ball_of * 0.9,
               "the ball's outline is inked (0.65 of its brightness or darker on 90%)");
        Expect(column_of > 500 && column_dark >= column_of * 0.8,
               "the column's outline against the back wall is inked (on 80%)");
        Expect(beside > 200 && beside_changed == 0,
               "the farther side of an edge is left as it was (the line is on the near side)");
        Expect(floor_plain > 100000 && floor_changed == 0 && column_plain > 5000 &&
                   column_changed == 0,
               "plain floor and the column's round inside get no ink");
        Expect(changed > 0 && brighter == 0 && worst_hue < 1e-3 && sky_changed == 0 &&
                   alpha_changed == 0,
               "lines only: a pixel is either as it was or its own colour darker; sky and alpha "
               "untouched");

        // Another exposure: the same lines (the ink is a share of the pixel's brightness or of
        // the key). Two roundings to half floats (the input's, the output's) lie in each ratio.
        double worst_exposure = 0.0;
        for (const float exposure : {8.0f, 0.125f}) {
            const Scene other = MakeScene(large, straight, Paint::Lit, exposure);
            const auto out =
                gpu.Run(other, Words(large, straight, Look::ViewOff, true, false, 0.0f), 1.0f);
            for (u32 i = 0; i < count; ++i) {
                if (lit.surface[i] != Sky && Luminance(lit.colour[i]) > 0.0f) {
                    const double apart = std::abs(ratio(other, out, i) - ratio(lit, lines, i));
                    worst_exposure = std::max(worst_exposure, apart);
                }
            }
        }
        std::printf("ink lines at 8 and 1/8 times the brightness: out/in differs by %.5f at "
                    "most\n", worst_exposure);
        Expect(worst_exposure < 2e-3, "the lines do not depend on how bright the scene is");

        // A pixel off the scale on the ball's outline glows: no ink on it.
        {
            Scene spark = lit;
            u32 at = count;
            for (u32 i = 0; i < count && at == count; ++i) {
                if (rim(lit, i, Ball, Sky) && ratio(lit, lines, i) < 0.65) {
                    at = i;
                }
            }
            assert(at < count);
            spark.colour[at] = {ToHalf(60000.0f), ToHalf(60000.0f), ToHalf(60000.0f),
                                spark.colour[at][3]};
            const auto out =
                gpu.Run(spark, Words(large, straight, Look::ViewOff, true, false, 0.0f), 1.0f);
            Expect(out[at] == spark.colour[at], "a pixel that glows on an outline gets no ink");
            // A colour with a channel that is no number (a half float NaN) on an outline is
            // left as it is.
            Scene broken = lit;
            broken.colour[at][1] = 0x7E00;
            const auto kept =
                gpu.Run(broken, Words(large, straight, Look::ViewOff, true, false, 0.0f), 1.0f);
            Expect(kept[at] == broken.colour[at],
                   "a pixel whose colour is no number keeps it, on an outline too");
        }

        // Under the jitter: the ink on the ball as a whole stays.
        {
            static constexpr std::array<std::array<float, 2>, 8> Jitters{{{0.0f, 0.0f},
                                                                         {0.25f, -0.17f},
                                                                         {-0.25f, 0.17f},
                                                                         {0.375f, 0.39f},
                                                                         {-0.125f, -0.39f},
                                                                         {0.125f, 0.06f},
                                                                         {-0.375f, -0.28f},
                                                                         {0.44f, -0.06f}}};
            double least = 1e30, most = 0.0;
            for (const auto& jitter : Jitters) {
                Camera moved = straight;
                moved.jitter = jitter;
                const Scene scene_j = MakeScene(large, moved, Paint::Lit);
                const auto out =
                    gpu.Run(scene_j, Words(large, moved, Look::ViewOff, true, false, 0.0f), 1.0f);
                double ink = 0.0;
                for (u32 i = 0; i < count; ++i) {
                    if (scene_j.surface[i] == Ball) {
                        ink += 1.0 - ratio(scene_j, out, i);
                    }
                }
                least = std::min(least, ink);
                most = std::max(most, ink);
            }
            std::printf("ink on the ball under 8 jitters: %.1f to %.1f (pixels' darkening "
                        "summed)\n", least, most);
            Expect(least > 0.0 && most / least - 1.0 < 0.1,
                   "the ink on the ball stays within 10% under the jitter");
        }

        // The default weight: a little of the frame.
        {
            const auto out =
                gpu.Run(lit, Words(large, straight, Look::ViewOff, true, false, 0.0f), 0.35f);
            double before = 0.0, after = 0.0;
            u32 surfaces = 0, darker = 0;
            for (u32 i = 0; i < count; ++i) {
                before += Luminance(lit.colour[i]);
                after += Luminance(out[i]);
                if (lit.surface[i] != Sky) {
                    ++surfaces;
                    darker += ratio(lit, out, i) < 0.98;
                }
            }
            const double loss = 1.0 - after / before, share = double(darker) / surfaces;
            std::printf("ink lines 0.35: the frame's mean brightness %.2f%% lower, %.2f%% of the "
                        "surface pixels inked\n", 100.0 * loss, 100.0 * share);
            // (This scene has few silhouettes: a ball, a column, the walls' corners.)
            Expect(loss < 0.015 && share > 0.002 && share < 0.06,
                   "at 0.35 the lines darken the frame by under 1.5%, on 0.2% to 6% of its "
                   "surfaces");
        }

        // BB_DRAWN_LOOK_LINE: a wider line inks more pixels.
        {
            u32 inked_at[3] = {};
            const float scales[3] = {0.6f, 1.0f, 1.6f};
            for (int k = 0; k < 3; ++k) {
                const auto out = gpu.Run(
                    lit, Words(large, straight, Look::ViewOff, true, false, 0.0f), 1.0f, scales[k]);
                for (u32 i = 0; i < count; ++i) {
                    inked_at[k] += !(out[i] == lit.colour[i]);
                }
            }
            std::printf("ink lines at line scale 0.6, 1 and 1.6: %u, %u and %u pixels\n",
                        inked_at[0], inked_at[1], inked_at[2]);
            Expect(inked_at[0] < inked_at[1] && inked_at[1] < inked_at[2],
                   "the line scale widens the lines");
        }

        // With the strokes: the ink comes after the colour lock, which would otherwise take
        // it back.
        {
            const auto strokes =
                gpu.Run(lit, Words(large, straight, Look::ViewOff, true, false, 0.6f), 0.0f);
            const auto both =
                gpu.Run(lit, Words(large, straight, Look::ViewOff, true, false, 0.6f), 0.35f);
            u32 of = 0, dark = 0;
            for (u32 i = 0; i < count; ++i) {
                if (rim(lit, i, Ball, Sky)) {
                    ++of;
                    dark += Luminance(both[i]) <= 0.8f * Luminance(strokes[i]);
                }
            }
            std::printf("strokes 0.6 with ink lines 0.35: %u of %u ball outline pixels at 0.8 "
                        "of the strokes' brightness or darker\n", dark, of);
            Expect(of > 500 && dark >= of * 0.9, "the ink lies on top of the strokes");
        }

        // Test view 3, the ink page: the key's grey with the lines dark on it, every line at
        // weight 1, the sky as it was; no strokes (the strength is 0.6 here).
        {
            const auto page =
                gpu.Run(lit, Words(large, straight, Look::ViewInk, true, false, 0.6f), 0.0f);
            std::vector<u16> greys;
            u32 sky_kept = 0, sky = 0, coloured = 0;
            for (u32 i = 0; i < count; ++i) {
                if (lit.surface[i] == Sky) {
                    ++sky;
                    sky_kept += page[i] == lit.colour[i];
                } else {
                    coloured += !(page[i][0] == page[i][1] && page[i][1] == page[i][2]);
                    if (plain(lit, i)) {
                        greys.push_back(page[i][0]);
                    }
                }
            }
            std::sort(greys.begin(), greys.end());
            const u16 paper = greys.empty() ? 0 : greys[greys.size() / 2];
            u32 plain_off = 0, above = 0, of = 0, dark = 0;
            for (u32 i = 0; i < count; ++i) {
                if (lit.surface[i] == Sky) {
                    continue;
                }
                above += FromHalf(page[i][0]) > FromHalf(paper);
                plain_off += plain(lit, i) && page[i][0] != paper;
                if (rim(lit, i, Ball, Sky)) {
                    ++of;
                    dark += FromHalf(page[i][0]) <= 0.65f * FromHalf(paper);
                }
            }
            std::printf("test view 3: paper %.4f, %u of %u sky pixels kept, %u surface pixels "
                        "not grey, %u above the paper, %u plain pixels off it; %u of %u ball "
                        "outline pixels dark\n", FromHalf(paper), sky_kept, sky, coloured, above,
                        plain_off, dark, of);
            Expect(paper != 0 && sky_kept == sky && coloured == 0 && above == 0 &&
                       plain_off == 0 && of > 500 && dark >= of * 0.9,
                   "test view 3 is the ink page: the key's grey, the lines dark, the sky kept");
        }

        // Other render sizes: where the lines show does not depend on the size, and the ink
        // along an outline goes with the line's width in the picture (a line under one pixel
        // is drawn one pixel wide at a share of its weight).
        {
            const Lens sizes[3] = {{960, 540}, {1920, 1080}, {2560, 1440}};
            double share[3] = {}, column_share[3] = {}, per_line[3] = {};
            for (int k = 0; k < 3; ++k) {
                const Lens& at = sizes[k];
                const u32 wk = at.width, hk = at.height;
                const Scene in = k == 1 ? lit : MakeScene(at, straight, Paint::Lit);
                const auto out =
                    gpu.Run(in, Words(at, straight, Look::ViewOff, true, false, 0.0f), 1.0f);
                u32 of = 0, dark = 0, column_of = 0, column_dark = 0;
                double ink = 0.0;
                for (u32 y = 1; y + 1 < hk; ++y) {
                    for (u32 x = 1; x + 1 < wk; ++x) {
                        const u32 i = y * wk + x;
                        const double r = double(Luminance(out[i])) /
                                         std::max(double(Luminance(in.colour[i])), 1e-12);
                        if (in.surface[i] == Ball) {
                            ink += 1.0 - r;
                        }
                        bool edge = false;
                        for (const u32 j : {i - 1, i + 1, i - wk, i + wk}) {
                            edge |= in.surface[j] != in.surface[i] && in.depth[j] > in.depth[i] &&
                                    (in.surface[i] == Ball || in.surface[j] == BackWall);
                        }
                        if (edge && in.surface[i] == Ball) {
                            ++of;
                            dark += r <= 0.65;
                        } else if (edge && in.surface[i] == Column) {
                            ++column_of;
                            column_dark += r <= 0.65;
                        }
                    }
                }
                share[k] = of ? double(dark) / of : 0.0;
                column_share[k] = column_of ? double(column_dark) / column_of : 0.0;
                // The ink per outline pixel, per pixel of a 1080-line scene.
                per_line[k] = of ? ink / of / (hk / 1080.0) : 0.0;
                std::printf("ink lines at %ux%u: %u of %u ball outline pixels and %u of %u of the "
                            "column's at 0.65 or darker; %.3f ink per outline pixel per 1080-line "
                            "pixel\n", wk, hk, dark, of, column_dark, column_of, per_line[k]);
            }
            bool same_place = true, same_ink = true;
            for (int k = 0; k < 3; ++k) {
                same_place &= share[k] >= 0.9 && column_share[k] >= 0.8;
                same_ink &= per_line[k] > 0.7 * per_line[1] && per_line[k] < 1.4 * per_line[1];
            }
            Expect(same_place, "at 960x540, 1920x1080 and 2560x1440 the outlines are inked alike");
            Expect(same_ink, "the ink along an outline goes with the line's width in the picture "
                             "(within 0.7 to 1.4 of 1920x1080's)");
        }

        // Thin things (a railing, a branch): bars 1, 2, 3 and 8 pixels wide and 200 high, 40%
        // nearer than the back wall in front of it. A bar narrower than about twice the line
        // gets half the weight; the wide bar's edges get the full line.
        {
            Scene bars = lit;
            std::vector<int> bar(count, 0);
            // Where 200 rows of 100 pixels are all back wall.
            u32 x0 = 0, y0 = 0;
            for (u32 y = 0; y + 200 < h && !x0; y += 10) {
                for (u32 x = 0; x + 100 < w && !x0; x += 10) {
                    bool wall = true;
                    for (u32 dy = 0; dy < 200 && wall; ++dy) {
                        for (u32 dx = 0; dx < 100 && wall; ++dx) {
                            wall = lit.surface[(y + dy) * w + x + dx] == BackWall;
                        }
                    }
                    if (wall) {
                        x0 = x;
                        y0 = y;
                    }
                }
            }
            assert(x0);
            const u32 widths[4] = {1, 2, 3, 8};
            for (int b = 0; b < 4; ++b) {
                for (u32 dy = 0; dy < 200; ++dy) {
                    for (u32 dx = 0; dx < widths[b]; ++dx) {
                        const u32 i = (y0 + dy) * w + x0 + 10 + 22 * u32(b) + dx;
                        const double t = Near / (1.0 - double(lit.depth[i]));
                        bars.depth[i] = float(1.0 - Near / (0.6 * t));
                        bar[i] = b + 1;
                    }
                }
            }
            const auto out =
                gpu.Run(bars, Words(large, straight, Look::ViewOff, true, false, 0.0f), 1.0f);
            double mean[4] = {}, edge_most = 0.0;
            u32 n[4] = {};
            for (u32 dy = 10; dy < 190; ++dy) {
                for (u32 x = x0; x < x0 + 100; ++x) {
                    const u32 i = (y0 + dy) * w + x;
                    if (bar[i]) {
                        mean[bar[i] - 1] += ratio(bars, out, i);
                        ++n[bar[i] - 1];
                        if (bar[i] == 4 && (bar[i - 1] == 0 || bar[i + 1] == 0)) {
                            edge_most = std::max(edge_most, ratio(bars, out, i));
                        }
                    }
                }
            }
            for (int b = 0; b < 4; ++b) {
                mean[b] /= std::max(n[b], 1u);
            }
            // A full line's darkening: the wide bar's edges'. A thin bar's, over its width, about
            // half of it.
            const double full = 1.0 - edge_most;
            bool half = true;
            for (int b = 0; b < 3; ++b) {
                half &= 1.0 - mean[b] >= 0.3 * full && 1.0 - mean[b] <= 0.6 * full;
            }
            std::printf("thin bars at ink 1: mean brightness 1 px %.3f, 2 px %.3f, 3 px %.3f, 8 px "
                        "%.3f of their own; the 8-pixel bar's edges at %.3f at most (a thin bar "
                        "darkened by %.2f, %.2f and %.2f of a full line)\n",
                        mean[0], mean[1], mean[2], mean[3], edge_most, (1.0 - mean[0]) / full,
                        (1.0 - mean[1]) / full, (1.0 - mean[2]) / full);
            Expect(edge_most <= 0.4, "a wide bar's edges get the full line");
            Expect(half, "a bar 1 to 3 pixels wide is darkened over its width by 0.3 to 0.6 of a "
                         "full line (half the weight)");
        }
    }
"""

# ---- the menu's texts: English and Russian in bbport_overlay.cpp, the rest in
# bbport_menu_i18n.cpp, looked up by the English text ----
# 0 the section, 1 the switch, 2 its hint, 3 the strength, 4 its hint, 5 the ink row, 6 its hint,
# 7..12 the problems vk_drawn_look.cpp names, 13 "Unavailable".
K = ("Drawn look", "Drawn look (in development)",
     "An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, "
     "fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the "
     "HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. "
     "Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Drawn look strength",
     "How much of the brush strokes is laid over the game's picture: 1 is the full look, lower values let more "
     "of the game's own picture through. At 0 there are no strokes; the ink lines stay while they are on. "
     "Applies at once.",
     "Drawn look ink lines",
     "How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies "
     "behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog "
     "covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While "
     "lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the "
     "surface's own colour, darker. Applies at once.",
     "the upscaler is not available (BB_UPSCALER=none, or this GPU cannot run it)",
     "this GPU cannot run the passes",
     "the scene colour is not RGBA16F",
     "not enough video memory at this render size",
     "the reduced scene colour is not a storage image",
     "the scene colour is not a storage image",
     "Unavailable")
RU = {
    0: "Рисованный стиль",
    1: "Рисованный стиль (в разработке)",
    2: "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных стенах и полах, "
       "мелкие там, где есть детали, а по краям форм идут контурные линии. Огонь, свечение, туман, частицы и "
       "интерфейс остаются такими, какими их рисует игра. Цвета не меняются; контурная линия — это собственный "
       "цвет поверхности, только темнее. Применяется сразу. Ещё не сделано: более густые контуры на персонажах, "
       "линии на внутренних рёбрах и рисованные края теней.",
    3: "Сила рисованного стиля",
    4: "Насколько мазки кисти перекрывают изображение игры: 1 — стиль в полную силу, меньшие значения оставляют "
       "больше исходного изображения. При 0 мазков нет; контурные линии остаются, пока они включены. "
       "Применяется сразу.",
    5: "Контурные линии рисованного стиля",
    6: "Насколько темны контурные линии по краям форм: колонны, стены, ступени и фигуры на фоне того, что за "
       "ними. 0 — без линий. С расстоянием линии становятся тоньше и бледнее, а дальше 120 м исчезают; туман "
       "закрывает их так же, как и весь мир. Не рисуются в кадрах, где стиль накладывается прямо перед "
       "апскейлером. Пока линии рисуются, дополнительная резкость апскейлера снижается вплоть до половины. Цвета "
       "сохраняются: линия — это собственный цвет поверхности, только темнее. Применяется сразу.",
    7: "апскейлер недоступен (BB_UPSCALER=none, или эта видеокарта не может его запустить)",
    8: "эта видеокарта не может выполнить проходы",
    9: "цвет сцены не в формате RGBA16F",
    10: "недостаточно видеопамяти при этом разрешении рендеринга",
    11: "цвет уменьшенной сцены не является изображением для записи",
    12: "цвет сцены не является изображением для записи",
    13: "Недоступно",
}
# The constants of bbport_drawn_look_texts.h, one a text of K.
NAMES = ("Section", "Switch", "SwitchHint", "Strength", "StrengthHint", "Ink", "InkHint", "NoUpscaler",
         "NoPasses", "NotHalfFloat", "NoRoom", "ReducedNotStorage", "NotStorage", "Unavailable")
assert len(K) == len(RU) == len(NAMES) == 14
TABLES = {  # table name: (the text after its closing "};", the 14 texts)
 "kSpanish": ("\n\nconstexpr Entry kPortugueseBrazil[] = {\n", (
    "Estilo dibujado", "Estilo dibujado (en desarrollo)",
    "Un estilo dibujado a mano opcional: pinceladas sobre las superficies del mundo, amplias en paredes y suelos "
    "lisos, finas donde hay detalle, y líneas de tinta a lo largo de los bordes de las formas. El fuego, los "
    "brillos, la niebla, las partículas y la interfaz se quedan como los dibuja el juego. Los colores no cambian; "
    "una línea de tinta es el propio color de la superficie, más oscuro. Se aplica al instante. Aún no hecho: "
    "tinta más marcada en los personajes, líneas en los bordes interiores y bordes de sombra pintados.",
    "Intensidad del estilo dibujado",
    "Cuánto de las pinceladas se pone sobre la imagen del juego: 1 es el estilo completo, valores menores dejan "
    "ver más de la imagen original del juego. En 0 no hay pinceladas; las líneas de tinta se mantienen mientras "
    "estén activadas. Se aplica al instante.",
    "Líneas de tinta del estilo dibujado",
    "Qué tan oscuras son las líneas de tinta a lo largo de los bordes de las formas: pilares, paredes, escalones "
    "y figuras frente a lo que hay detrás. 0 es sin líneas. Con la distancia las líneas se vuelven más finas y "
    "más tenues, y desaparecen más allá de 120 m; la niebla las cubre como cubre el mundo. No se dibujan en los "
    "fotogramas que el estilo pinta justo antes del escalador. Mientras se dibujan líneas, la nitidez adicional "
    "del escalador se reduce hasta la mitad. Los colores se mantienen: una línea es el propio color de la "
    "superficie, más oscuro. Se aplica al instante.",
    "el escalador no está disponible (BB_UPSCALER=none, o esta GPU no puede ejecutarlo)",
    "esta GPU no puede ejecutar los pases",
    "el color de la escena no es RGBA16F",
    "no hay suficiente memoria de vídeo a esta resolución de renderizado",
    "el color de la escena reducida no es una imagen de almacenamiento",
    "el color de la escena no es una imagen de almacenamiento",
    "No disponible")),
 "kPortugueseBrazil": ("\n\nconstexpr Entry kFrench[] = {\n", (
    "Estilo desenhado", "Estilo desenhado (em desenvolvimento)",
    "Um estilo desenhado à mão opcional: pinceladas sobre as superfícies do mundo, largas em paredes e pisos "
    "lisos, finas onde há detalhes, e linhas de tinta ao longo das bordas das formas. Fogo, brilhos, névoa, "
    "partículas e a interface ficam como o jogo os desenha. As cores não mudam; uma linha de tinta é a própria "
    "cor da superfície, mais escura. Aplica-se na hora. Ainda não feito: tinta mais forte nos personagens, linhas "
    "nas bordas internas e bordas de sombra pintadas.",
    "Intensidade do estilo desenhado",
    "Quanto das pinceladas é colocado sobre a imagem do jogo: 1 é o estilo completo, valores menores deixam "
    "passar mais da imagem original do jogo. Em 0 não há pinceladas; as linhas de tinta ficam enquanto "
    "estiverem ativadas. Aplica-se na hora.",
    "Linhas de tinta do estilo desenhado",
    "Quão escuras são as linhas de tinta ao longo das bordas das formas: pilares, paredes, degraus e figuras "
    "diante do que está atrás delas. 0 é sem linhas. Com a distância as linhas ficam mais finas e mais fracas, e "
    "somem além de 120 m; a névoa as cobre como cobre o mundo. Não são desenhadas nos quadros que o estilo pinta "
    "logo antes do upscaler. Enquanto há linhas, a nitidez extra do upscaler é reduzida em até metade. As cores "
    "se mantêm: uma linha é a própria cor da superfície, mais escura. Aplica-se na hora.",
    "o upscaler não está disponível (BB_UPSCALER=none, ou esta GPU não consegue executá-lo)",
    "esta GPU não consegue executar as passagens",
    "a cor da cena não é RGBA16F",
    "memória de vídeo insuficiente nesta resolução de renderização",
    "a cor da cena reduzida não é uma imagem de armazenamento",
    "a cor da cena não é uma imagem de armazenamento",
    "Indisponível")),
 "kFrench": ("\n\nconstexpr Entry kGerman[] = {\n", (
    "Style dessiné", "Style dessiné (en développement)",
    "Un style dessiné à la main facultatif : des coups de pinceau posés sur les surfaces du monde, larges sur "
    "les murs et sols unis, fins là où il y a du détail, et des traits d'encre le long des bords des formes. Le "
    "feu, les lueurs, le brouillard, les particules et l'interface restent tels que le jeu les dessine. Les "
    "couleurs ne changent pas ; un trait d'encre est la couleur propre de la surface, plus sombre. S'applique "
    "immédiatement. Pas encore fait : encre plus marquée sur les personnages, traits sur les arêtes intérieures "
    "et bords d'ombre peints.",
    "Intensité du style dessiné",
    "Quelle part des coups de pinceau est posée sur l'image du jeu : 1 donne le style complet, des valeurs plus "
    "basses laissent passer davantage l'image d'origine du jeu. À 0 il n'y a pas de coups de pinceau ; les "
    "traits d'encre restent tant qu'ils sont activés. S'applique immédiatement.",
    "Traits d'encre du style dessiné",
    "La noirceur des traits d'encre le long des bords des formes : piliers, murs, marches et silhouettes devant "
    "ce qui se trouve derrière. 0 signifie aucun trait. Avec la distance les traits s'affinent et pâlissent, et "
    "disparaissent au-delà de 120 m ; le brouillard les recouvre comme il recouvre le monde. Pas de traits sur "
    "les images que le style peint juste avant l'upscaler. Tant que des traits sont dessinés, la netteté "
    "supplémentaire de l'upscaler est réduite de moitié au plus. Les couleurs sont gardées : un trait est la "
    "couleur propre de la surface, plus sombre. S'applique immédiatement.",
    "l'upscaler n'est pas disponible (BB_UPSCALER=none, ou ce GPU ne peut pas l'exécuter)",
    "ce GPU ne peut pas exécuter les passes",
    "la couleur de la scène n'est pas en RGBA16F",
    "mémoire vidéo insuffisante à cette résolution de rendu",
    "la couleur de la scène réduite n'est pas une image de stockage",
    "la couleur de la scène n'est pas une image de stockage",
    "Indisponible")),
 "kGerman": ("\n\nconstexpr Entry kItalian[] = {\n", (
    "Gezeichneter Stil", "Gezeichneter Stil (in Entwicklung)",
    "Ein optionaler handgezeichneter Stil: Pinselstriche auf den Oberflächen der Welt, breit auf glatten Wänden "
    "und Böden, fein, wo es Details gibt, und Tuschelinien entlang der Kanten von Formen. Feuer, Leuchten, Nebel, "
    "Partikel und das HUD bleiben so, wie das Spiel sie zeichnet. Die Farben ändern sich nicht; eine Tuschelinie "
    "ist die eigene Farbe der Fläche, dunkler. Wirkt sofort. Noch nicht gebaut: kräftigere Tusche an Figuren, "
    "Linien an inneren Kanten und gemalte Schattenkanten.",
    "Stärke des gezeichneten Stils",
    "Wie viel der Pinselstriche über das Bild des Spiels gelegt wird: 1 ist der volle Stil, kleinere Werte "
    "lassen mehr vom eigenen Bild des Spiels durch. Bei 0 gibt es keine Pinselstriche; die Tuschelinien bleiben, "
    "solange sie an sind. Wirkt sofort.",
    "Tuschelinien des gezeichneten Stils",
    "Wie dunkel die Tuschelinien entlang der Kanten von Formen sind: Säulen, Wände, Stufen und Figuren vor dem, "
    "was hinter ihnen liegt. 0 heißt keine Linien. Mit der Entfernung werden die Linien dünner und blasser, "
    "jenseits von 120 m verschwinden sie; Nebel deckt sie zu, wie er die Welt zudeckt. Nicht gezeichnet in "
    "Bildern, die der Stil direkt vor dem Upscaler malt. Solange Linien gezeichnet werden, wird die zusätzliche "
    "Schärfung des Upscalers um bis zur Hälfte gesenkt. Die Farben bleiben: eine Linie ist die eigene Farbe der "
    "Fläche, dunkler. Wirkt sofort.",
    "der Upscaler ist nicht verfügbar (BB_UPSCALER=none, oder diese GPU kann ihn nicht ausführen)",
    "diese GPU kann die Durchgänge nicht ausführen",
    "die Szenenfarbe ist nicht RGBA16F",
    "nicht genug Videospeicher bei dieser Renderauflösung",
    "die verkleinerte Szenenfarbe ist kein Speicherbild",
    "die Szenenfarbe ist kein Speicherbild",
    "Nicht verfügbar")),
 "kItalian": ("\n\nconstexpr Entry kPolish[] = {\n", (
    "Stile disegnato", "Stile disegnato (in sviluppo)",
    "Uno stile disegnato a mano facoltativo: pennellate stese sulle superfici del mondo, larghe su pareti e "
    "pavimenti lisci, sottili dove ci sono dettagli, e linee d'inchiostro lungo i bordi delle forme. Fuoco, "
    "bagliori, nebbia, particelle e HUD restano come li disegna il gioco. I colori non cambiano; una linea "
    "d'inchiostro è il colore stesso della superficie, più scuro. Si applica subito. Non ancora fatto: inchiostro "
    "più marcato sui personaggi, linee sugli spigoli interni e bordi d'ombra dipinti.",
    "Intensità dello stile disegnato",
    "Quanto delle pennellate viene steso sull'immagine del gioco: 1 è lo stile completo, valori più bassi "
    "lasciano passare più immagine originale del gioco. A 0 non ci sono pennellate; le linee d'inchiostro "
    "restano finché sono attive. Si applica subito.",
    "Linee d'inchiostro dello stile disegnato",
    "Quanto sono scure le linee d'inchiostro lungo i bordi delle forme: pilastri, muri, gradini e figure davanti "
    "a ciò che sta dietro. 0 significa nessuna linea. Con la distanza le linee si assottigliano e si schiariscono, "
    "e oltre 120 m spariscono; la nebbia le copre come copre il mondo. Non disegnate nei fotogrammi che lo stile "
    "dipinge subito prima dell'upscaler. Finché si disegnano linee, la nitidezza aggiuntiva dell'upscaler è "
    "ridotta fino alla metà. I colori restano: una linea è il colore stesso della superficie, più scuro. Si "
    "applica subito.",
    "l'upscaler non è disponibile (BB_UPSCALER=none, oppure questa GPU non può eseguirlo)",
    "questa GPU non può eseguire i passaggi",
    "il colore della scena non è RGBA16F",
    "memoria video insufficiente a questa risoluzione di rendering",
    "il colore della scena ridotta non è un'immagine di archiviazione",
    "il colore della scena non è un'immagine di archiviazione",
    "Non disponibile")),
 "kPolish": ("\n\nconstexpr Entry kTurkish[] = {\n", (
    "Styl rysowany", "Styl rysowany (w budowie)",
    "Opcjonalny styl rysowany ręcznie: pociągnięcia pędzla na powierzchniach świata, szerokie na gładkich "
    "ścianach i podłogach, drobne tam, gdzie są szczegóły, oraz linie tuszu wzdłuż krawędzi kształtów. Ogień, "
    "poświata, mgła, cząsteczki i interfejs zostają takie, jak rysuje je gra. Kolory się nie zmieniają; linia "
    "tuszu to własny kolor powierzchni, tylko ciemniejszy. Działa od razu. Jeszcze nie zrobione: mocniejszy tusz "
    "na postaciach, linie na wewnętrznych krawędziach i malowane krawędzie cieni.",
    "Siła stylu rysowanego",
    "Jak mocno pociągnięcia pędzla pokrywają obraz gry: 1 to pełny styl, mniejsze wartości przepuszczają więcej "
    "oryginalnego obrazu gry. Przy 0 nie ma pociągnięć; linie tuszu zostają, dopóki są włączone. Działa od razu.",
    "Linie tuszu stylu rysowanego",
    "Jak ciemne są linie tuszu wzdłuż krawędzi kształtów: filary, ściany, stopnie i postacie na tle tego, co "
    "jest za nimi. 0 to brak linii. Z odległością linie stają się cieńsze i bledsze, a dalej niż 120 m znikają; "
    "mgła zakrywa je tak, jak zakrywa świat. Nie są rysowane w klatkach, które styl maluje tuż przed "
    "upscalerem. Gdy linie są rysowane, dodatkowe wyostrzanie upscalera jest zmniejszane maksymalnie o połowę. "
    "Kolory zostają: linia to własny kolor powierzchni, tylko ciemniejszy. Działa od razu.",
    "upscaler jest niedostępny (BB_UPSCALER=none albo ta karta graficzna nie może go uruchomić)",
    "ta karta graficzna nie może uruchomić przebiegów",
    "kolor sceny nie jest w formacie RGBA16F",
    "za mało pamięci wideo przy tej rozdzielczości renderowania",
    "kolor zmniejszonej sceny nie jest obrazem do zapisu",
    "kolor sceny nie jest obrazem do zapisu",
    "Niedostępne")),
 "kTurkish": ("\n\nconstexpr Entry kChinese[] = {\n", (
    "Çizim stili", "Çizim stili (geliştiriliyor)",
    "İsteğe bağlı elle çizilmiş bir görünüm: dünyanın yüzeylerine fırça darbeleri, düz duvar ve zeminlerde "
    "geniş, ayrıntı olan yerlerde ince, ve biçimlerin kenarları boyunca mürekkep çizgileri. Ateş, parıltılar, "
    "sis, parçacıklar ve arayüz oyunun çizdiği gibi kalır. Renkler değişmez; bir mürekkep çizgisi yüzeyin kendi "
    "renginin daha koyusudur. Hemen uygulanır. Henüz yapılmadı: karakterlerde daha belirgin mürekkep, iç "
    "kenarlarda çizgiler ve boyanmış gölge kenarları.",
    "Çizim stili gücü",
    "Fırça darbelerinin oyunun görüntüsünün üzerine ne kadar konduğu: 1 tam stildir, daha düşük değerler oyunun "
    "kendi görüntüsünden daha fazlasını gösterir. 0'da fırça darbesi yoktur; mürekkep çizgileri açık oldukları "
    "sürece kalır. Hemen uygulanır.",
    "Çizim stili mürekkep çizgileri",
    "Biçimlerin kenarları boyunca mürekkep çizgilerinin ne kadar koyu olduğu: sütunlar, duvarlar, basamaklar ve "
    "figürler, arkalarında kalanın önünde. 0 çizgi yok demektir. Çizgiler uzaklıkla incelir ve solar, 120 m'nin "
    "ötesinde kaybolur; sis onları dünyayı örttüğü gibi örter. Stilin ölçekleyiciden hemen önce boyadığı "
    "karelerde çizilmez. Çizgiler çizilirken ölçekleyicinin ek keskinleştirmesi en fazla yarıya kadar azaltılır. "
    "Renkler korunur: bir çizgi yüzeyin kendi renginin daha koyusudur. Hemen uygulanır.",
    "ölçekleyici kullanılamıyor (BB_UPSCALER=none veya bu GPU onu çalıştıramıyor)",
    "bu GPU geçişleri çalıştıramıyor",
    "sahne rengi RGBA16F değil",
    "bu işleme çözünürlüğünde yeterli video belleği yok",
    "küçültülmüş sahne rengi bir depolama görüntüsü değil",
    "sahne rengi bir depolama görüntüsü değil",
    "Kullanılamıyor")),
 "kChinese": ("\n\nusing Table = std::unordered_map<std::string_view, const char*>;\n", (
    # Only characters of the menu font (LanternMenuSC-glyphs.txt): "ink line" is 暗边 (dark edge),
    # "brush stroke" 刷纹.
    "手绘效果", "手绘效果（开发中）",
    "可选的手绘效果：在世界的表面上画上刷纹，平整的大面用大刷纹，细节多处用小刷纹，并在物体的边上画出暗边。火焰、发光、"
    "雾、粒子和界面保持游戏原画。颜色不变；暗边是表面自身的颜色，只是更暗。立即生效。尚未实现：角色身上更重的暗边、内部"
    "的边和手绘的阴影边。",
    "手绘效果强度",
    "刷纹叠在游戏画面上的程度：1 为最强效果，数值更低时，透出的游戏原画更多。为 0 时没有刷纹；暗边开启时仍保留。立即生效。",
    "手绘效果暗边",
    "物体边上暗边的强度：物体、人物与后方景物之间的边。0 为没有暗边。暗边随距离变细变弱，超过 120 m 后不再画出；雾也会遮住"
    "暗边。效果在超分辨率算法之前才叠加的帧上没有暗边。画出暗边时，超分辨率算法的额外锐化最多降低一半。颜色保持不变："
    "暗边是表面自身的颜色，只是更暗。立即生效。",
    "超分辨率算法不可用（BB_UPSCALER=none，或此 GPU 无法运行它）",
    "此 GPU 无法运行这些渲染过程",
    "场景颜色不是 RGBA16F",
    "此渲染分辨率下显存不足",
    "缩小后的场景颜色不是可写入的图像",
    "场景颜色不是可写入的图像",
    None)),  # kChinese has "Unavailable" already
}


def table_entries(texts):
    out = ["    // bbport (r55_drawn-look-lines): the drawn look's texts\n"]
    for en, tr in zip(K, texts):
        if tr is None:
            continue
        assert '"' not in en + tr and "\\" not in en + tr
        if len(en) + len(tr) + 12 <= 100:
            out.append('    {"%s", "%s"},\n' % (en, tr))
        else:
            out.append('    {"%s",\n     "%s"},\n' % (en, tr))
    return "".join(out)


I18N_EDITS = [("\n};" + after, "\n" + table_entries(texts).rstrip("\n") + "\n};" + after)
              for after, texts in TABLES.values()]


def texts_header():
    """bbport_drawn_look_texts.h: K and RU as the constants the overlay and the renderer use."""
    defs = []
    for k, name in enumerate(NAMES):
        assert '"' not in K[k] + RU[k] and "\\" not in K[k] + RU[k]
        one = 'inline constexpr Text %s{"%s", "%s"};' % (name, K[k], RU[k])
        if len(one) <= 100:
            defs.append(one)
        else:
            defs.append("inline constexpr Text %s{\n%s,\n%s};" % (name, lit(K[k], " " * 4), lit(RU[k], " " * 4)))
    problems = ", ".join("&" + n for n in NAMES[7:13])
    every = ", ".join("&" + n for n in NAMES)
    return B(r"""
// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r55_drawn-look-lines): the drawn look's menu texts, English and Russian, in one place.
// bbport_overlay.cpp shows them; renderer_vulkan/vk_drawn_look.cpp names with them why the look
// cannot run (Values::drawn_look_problem). bbport_menu_i18n.cpp's eight tables are looked up by
// the English text, and tests/test_settings.cpp checks that every text here is in all eight: a
// text changed here without its translations fails settings-test.
#pragma once

#include <cstring>

namespace BbSettings::DrawnLookTexts {

struct Text {
    const char* english;
    const char* russian;
};

@DEFS@

/// Why the look cannot run (Values::drawn_look_problem), as the renderer sets it.
@PROBLEMS@
/// Every text of the look's menu rows, the problems included.
@ALL@

/// The Russian of a problem the renderer set; `english` itself when it is none of them.
inline const char* RussianOf(const char* english) {
    for (const Text* text : Problems) {
        if (english && std::strcmp(english, text->english) == 0) {
            return text->russian;
        }
    }
    return english;
}

} // namespace BbSettings::DrawnLookTexts
""").replace("@DEFS@", "\n".join(defs)) \
        .replace("@PROBLEMS@", wrap("inline constexpr const Text* Problems[] = {", problems + "};")) \
        .replace("@ALL@", wrap("inline constexpr const Text* All[] = {", every + "};"))


def wrap(head, items):
    """`head` then the comma-separated `items`, wrapped at 100 columns under the first item."""
    lines, cur = [], head
    for word in items.split(" "):
        if len(cur) + 1 + len(word) > 100 and cur != head:
            lines.append(cur.rstrip())
            cur = " " * len(head) + word
        else:
            cur = cur + ("" if cur == head else " ") + word
    lines.append(cur)
    return "\n".join(lines)


NEW_FILES[S + "bbport_drawn_look_texts.h"] = texts_header()

OVERLAY_OLD = B(r"""
    Section("Drawn look", "Рисованный стиль");
    const char* const drawn_problem = s.drawn_look_problem.load();
    if (const char* label = Item("Drawn look (in development)", "Рисованный стиль (в разработке)")) {
        // While it cannot run it cannot be switched on; switched on, it can always be switched
        // off (the renderer then lets go of what it holds for it).
        ImGui::BeginDisabled(drawn_problem != nullptr && !s.graphics_drawn_look);
        Checkbox(label, s.graphics_drawn_look);
        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "An optional hand-painted look: brush strokes laid on the world's surfaces, bold on plain "
            "walls and floors, fine where there is detail. Fire, glows, fog, particles and the HUD stay "
            "as the game draws them, and colours are not changed. Applies at once. This build paints "
            "the strokes; ink lines and painted shadow edges are not built yet.",
            "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных "
            "стенах и полах, мелкие там, где есть детали. Огонь, свечение, туман, частицы и интерфейс "
            "остаются такими, какими их рисует игра, цвета не меняются. Применяется сразу. В этой "
            "сборке рисуются мазки; контурные линии и рисованные края теней ещё не сделаны."));
        if (drawn_problem) {
            ImGui::TextDisabled("%s: %s", BbSettings::MenuText("Unavailable", "Недоступно"),
                                BbSettings::MenuText(drawn_problem));
        }
    }
    if (const char* label = Item("Drawn look strength", "Сила рисованного стиля")) {
        ImGui::BeginDisabled(drawn_problem != nullptr || !s.graphics_drawn_look);
        Slider(label, s.graphics_drawn_look_strength, 0.0f, 1.0f, "%.2f", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "How much of the strokes is laid over the game's picture: 1 is the full look, lower values "
            "let more of the game's own picture through. At 0 the look does no work at all. Applies at "
            "once.",
            "Насколько мазки перекрывают изображение игры: 1 — стиль в полную силу, меньшие значения "
            "оставляют больше исходного изображения. При 0 стиль вообще не работает. Применяется "
            "сразу."));
    }
}
""")
OVERLAY_NEW = B(r"""
    // bbport (r55_drawn-look-lines): the texts are bbport_drawn_look_texts.h's, which
    // settings-test checks against the eight translation tables.
    namespace DrawnText = BbSettings::DrawnLookTexts;
    const auto drawn_text = [](const DrawnText::Text& text) {
        return BbSettings::MenuText(text.english, text.russian);
    };
    Section(DrawnText::Section.english, DrawnText::Section.russian);
    const char* const drawn_problem = s.drawn_look_problem.load();
    if (const char* label = Item(DrawnText::Switch.english, DrawnText::Switch.russian)) {
        // While it cannot run it cannot be switched on; switched on, it can always be switched
        // off (the renderer then lets go of what it holds for it).
        ImGui::BeginDisabled(drawn_problem != nullptr && !s.graphics_drawn_look);
        Checkbox(label, s.graphics_drawn_look);
        ImGui::EndDisabled();
        Hint(drawn_text(DrawnText::SwitchHint));
        if (drawn_problem) {
            const char* const russian = DrawnText::RussianOf(drawn_problem);
            ImGui::TextDisabled("%s: %s", drawn_text(DrawnText::Unavailable),
                                BbSettings::MenuText(drawn_problem, russian));
        }
    }
    if (const char* label = Item(DrawnText::Strength.english, DrawnText::Strength.russian)) {
        ImGui::BeginDisabled(drawn_problem != nullptr || !s.graphics_drawn_look);
        Slider(label, s.graphics_drawn_look_strength, 0.0f, 1.0f, "%.2f", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        Hint(drawn_text(DrawnText::StrengthHint));
    }
    // bbport (r55_drawn-look-lines): how dark the ink lines are (graphics_drawn_look_ink_world,
    // host_shaders/paint_ink.comp). With the strength at 0 the look draws the lines alone.
    if (const char* label = Item(DrawnText::Ink.english, DrawnText::Ink.russian)) {
        ImGui::BeginDisabled(drawn_problem != nullptr || !s.graphics_drawn_look);
        Slider(label, s.graphics_drawn_look_ink_world, 0.0f, 1.0f, "%.2f", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        Hint(drawn_text(DrawnText::InkHint));
    }
}
""")

EDITS = {
    R + "drawn_look_params.h": [
        ("#include <cstdint>\n\nnamespace Vulkan::DrawnLookParams {\n",
         "#include <cstdint>\n#include <cstdlib>\n\nnamespace Vulkan::DrawnLookParams {\n"),
        (B(r"""
/// The push constants of the drawn look's passes (host_shaders/paint_*.comp). 128 bytes: what
/// every GPU takes, and all of it used. The ink's two knobs (Knobs::outlines, ink_world), which
/// no pass reads yet, gave their places to the camera of the frame before
/// (r45b_drawn-look-fixes).
"""), B(r"""
/// The push constants of the drawn look's passes (host_shaders/paint_*.comp). 128 bytes: what
/// every GPU takes, and all of it used. The ink pass (paint_ink.comp, r55_drawn-look-lines)
/// takes the same block, three of its floats with other meanings (MakeInk).
""")),
        (B(r"""
/// graphics_drawn_look_debug (BB_DRAWN_LOOK_VIEW). 1, 2 and 4 paint every stroke in a flat
/// colour of its own: with the sizes the look mixes, all fine, all bold. 3 is kept for the ink
/// lines' view; until they are built it shows the look, as 0 does.
"""), B(r"""
/// The test view, BB_DRAWN_LOOK_VIEW only (r55_drawn-look-lines: no key in the ini, where a test
/// view would stay on). 1, 2 and 4 paint every stroke in a flat colour of its own: with the sizes
/// the look mixes, all fine, all bold. 3 is the ink page: no strokes, the frame's key as a grey
/// on everything that is not sky, and the ink lines dark on it, every line at weight 1.
""")),
        (B(r"""
    float outlines = 0.35f; ///< the ink is not built: not among the passes' words
    float ink_world = 0.0f; ///< the same
    float characters = 0.5f;
    int view = ViewOff;
"""), B(r"""
    float outlines = 0.35f;  ///< handed to the ink pass (MakeInk), which does not read it yet
    float ink_world = 0.35f; ///< (r55_drawn-look-lines) how dark the ink lines are; 0: none
    float characters = 0.5f;
    float line_scale = 1.0f; ///< BB_DRAWN_LOOK_LINE (LineScaleOf): a factor on the lines' width
    int view = ViewOff;
""")),
        (B(r"""
    return blend && !blend_bypass && !depth_write && depth_test && !depth_always;
}
"""), B(r"""
    return blend && !blend_bypass && !depth_write && depth_test && !depth_always;
}

/// (r55_drawn-look-lines) The look runs on a frame: its switch is on, and it has strokes
/// (`strength`) or ink lines (`ink_world`) to draw. A number that is none counts as 0.
constexpr bool Wanted(bool on, float strength, float ink_world) {
    return on && (strength > 0.0f || ink_world > 0.0f);
}

/// (r55_drawn-look-lines) The passes a painted frame records after the copy, the marks and the
/// key (those run on every painted frame).
struct Passes {
    bool strokes = false; ///< paint_strokes.comp
    bool lock = false;    ///< paint_lock.comp, after the strokes
    bool ink = false;     ///< paint_ink.comp, last
};
/// Strokes with a strength above 0 or in a stroke test view (1, 2, 4); the colour lock after them
/// without a test view (a test view's flat colours have none to keep); ink lines with ink_world
/// above 0 or in the ink page (view 3), which lays no strokes. No ink on a frame painted right
/// before the upscaler (`before_upscaler`): fog and particles are in the scene there, and the
/// lines would be drawn over them where the surfaces behind have edges.
constexpr Passes PassesFor(const Knobs& knobs, bool before_upscaler) {
    const int view = std::clamp(knobs.view, int(ViewOff), int(ViewMax));
    const bool page = view == ViewInk;
    const bool strokes = !page && (knobs.strength > 0.0f || view != ViewOff);
    return {.strokes = strokes,
            .lock = strokes && view == ViewOff,
            .ink = !before_upscaler && (knobs.ink_world > 0.0f || page)};
}

/// BB_DRAWN_LOOK_LINE, a factor on the ink lines' width for the owner's tests (never saved).
inline constexpr float LineScaleMin = 0.5f, LineScaleMax = 2.0f;
/// The variable's text as that factor: 1 without it or without a number in it, else clamped.
inline float LineScaleOf(const char* text) {
    if (!text) {
        return 1.0f;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return 1.0f;
    }
    return std::clamp(value, LineScaleMin, LineScaleMax);
}

/// The ink pass's block: the frame's (Make) with three floats given other meanings
/// (paint_ink.comp's INK_WORLD, INK_CHARS, LINE_SCALE). The ink page (view 3) draws every line
/// at weight 1.
constexpr Params MakeInk(Params look, float ink_world, float outlines, float line_scale) {
    look.strength = ViewOf(look.flags) == std::uint32_t(ViewInk) ? 1.0f : ink_world;
    look.brush = outlines;
    look.characters = line_scale;
    return look;
}

/// The upscaler's extra sharpening (vk_temporal_upscaler.cpp, ExtraSharpenStrength) sharpens the
/// ink lines as it sharpens any edge. `ink`: the weight of the ink lines the frame recorded
/// (BbSettings' drawn_look_ink_drawn, MakeInk's strength; 0 on a frame without them). Above 0
/// the sharpening is multiplied by 1 - InkSharpenShare * ink (ink taken at most 1), else by 1.
inline constexpr float InkSharpenShare = 0.5f;
constexpr float InkSharpen(float ink) {
    return ink > 0.0f ? 1.0f - InkSharpenShare * std::min(ink, 1.0f) : 1.0f;
}
""")),
    ],
    R + "vk_drawn_look.h": [
        (B(r"""
// changed. Off by default: graphics_drawn_look in lantern.ini and the menu's Picture tab. While
// it is off, or its strength is 0, the rasterizer calls nothing here but OnFrameEnd: no
// pipeline, no image, no pass.
//
// Built so far (stages 1 and 2 of the design): the switch, the passes' place in the frame, the
// strokes themselves (host_shaders/paint_strokes.comp), and a test view
// (graphics_drawn_look_debug) that paints every stroke in a flat colour of its own. Not built:
// ink lines, painted shadow edges.
"""), B(r"""
// changed. Off by default: graphics_drawn_look in lantern.ini and the menu's Picture tab. While
// it is off, or its strength and its ink lines are both 0, the rasterizer calls nothing here but
// OnFrameEnd: no pipeline, no image, no pass.
//
// Built so far (stages 1 and 2 of the design, and r55_drawn-look-lines): the switch, the passes'
// place in the frame, the strokes themselves (host_shaders/paint_strokes.comp), ink lines along
// the silhouettes of shapes (host_shaders/paint_ink.comp; with the strength at 0 they are drawn
// alone), and test views (BB_DRAWN_LOOK_VIEW, never saved) that paint every stroke in a flat
// colour of its own or show the ink lines alone on a grey page. Not built: ink on inner edges,
// heavier ink on characters, painted shadow edges.
""")),
        (B(r"""
//   paint_lock.comp     the painted scene's means (a quarter of the size, and their smaller
//                       levels), then every place scaled back to the mean colour it had
"""), B(r"""
//   paint_lock.comp     the painted scene's means (a quarter of the size, and their smaller
//                       levels), then every place scaled back to the mean colour it had
//   paint_ink.comp      the ink lines into the scene colour, after the strokes and the lock or
//                       alone; not on a frame painted right before the upscaler
""")),
        ("    /// The switch is on and the strength is above 0 (the rasterizer asks once a frame).\n",
         "    /// The switch is on and the strength or the ink lines are above 0 (DrawnLookParams::Wanted;\n"
         "    /// the rasterizer asks once a frame).\n"),
        (B(r"""
    /// How a frame went: where its strokes were painted, or why they were not.
    enum Result : u32 { AtBlended, AtComposite, AtBeforeUpscaler, Preview, NoCamera, NoRoom,
                        NotReached, ResultCount };
"""), B(r"""
    /// How a frame went: where it was painted, or why it was not. LinesOnlyLate
    /// (r55_drawn-look-lines): ink lines alone (strength 0), and the frame's place was right
    /// before the upscaler, where no ink is drawn (DrawnLookParams::PassesFor): nothing recorded.
    enum Result : u32 { AtBlended, AtComposite, AtBeforeUpscaler, Preview, NoCamera, NoRoom,
                        NotReached, LinesOnlyLate, ResultCount };
""")),
        ("    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;\n",
         "    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;\n"),
        (B(r"""
    /// BB_DRAWN_LOOK_VIEW: a test view that decides instead of the ini's
    /// graphics_drawn_look_debug while the variable is set; -1 without it.
    int env_view = -1;
"""), B(r"""
    /// BB_DRAWN_LOOK_VIEW: the test view (DrawnLookParams::View), read once; -1 without it.
    int env_view = -1;
    /// BB_DRAWN_LOOK_LINE (r55_drawn-look-lines): a factor on the ink lines' width, read once.
    float env_line = 1.0f;
""")),
        ("    std::array<u32, ResultCount> results{};\n    u32 frames = 0;\n",
         "    std::array<u32, ResultCount> results{};\n    u32 frames = 0;\n"
         "    u32 ink_frames = 0; ///< (r55_drawn-look-lines) frames the ink lines were recorded on\n"
         "    /// (r55_drawn-look-lines) This frame set BbSettings' drawn_look_ink_drawn (OnFrameEnd puts\n"
         "    /// it back to 0).\n"
         "    bool ink_published = false;\n"),
        (B(r"""
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) do: those may come
    /// and go with the place a frame is painted at.
"""), B(r"""
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) or the passes
    /// (strokes, ink) do: those may come and go with the place a frame is painted at.
""")),
    ],
    R + "vk_drawn_look.cpp": [
        ('#include "bbport_settings.h"\n#include "bbport_toggles.h"\n',
         '#include "bbport_drawn_look_texts.h" // bbport (r55_drawn-look-lines)\n'
         '#include "bbport_settings.h"\n#include "bbport_toggles.h"\n'),
        (B(r"""
    BbSettings::Get().drawn_look_problem = "the upscaler is not available (BB_UPSCALER=none, or "
                                           "this GPU cannot run it)";
"""), "    BbSettings::Get().drawn_look_problem = BbSettings::DrawnLookTexts::NoUpscaler.english;\n"),
        ('        Fail("this GPU cannot run the passes");\n',
         "        Fail(BbSettings::DrawnLookTexts::NoPasses.english);\n"),
        ('        Fail("the scene colour is not RGBA16F");\n',
         "        Fail(BbSettings::DrawnLookTexts::NotHalfFloat.english);\n"),
        ('            BbSettings::Get().drawn_look_problem = "not enough video memory at this render size";\n',
         "            BbSettings::Get().drawn_look_problem = BbSettings::DrawnLookTexts::NoRoom.english;\n"),
        ('            Fail("the reduced scene colour is not a storage image");\n',
         "            Fail(BbSettings::DrawnLookTexts::ReducedNotStorage.english);\n"),
        ('            Fail("the scene colour is not a storage image");\n',
         "            Fail(BbSettings::DrawnLookTexts::NotStorage.english);\n"),
        (B(r"""
    frame_pass_count = 0;
    gbuffer_depth = {};
    gbuffer_normal = {};
}
"""), B(r"""
    frame_pass_count = 0;
    gbuffer_depth = {};
    gbuffer_normal = {};
    // (r55_drawn-look-lines) The next frame has no ink lines until it records them.
    if (ink_published) {
        BbSettings::Get().drawn_look_ink_drawn.store(0.0f, std::memory_order_relaxed);
        ink_published = false;
    }
}
""")),
        ('#include "video_core/host_shaders/paint_key_comp.h"\n',
         '#include "video_core/host_shaders/paint_ink_comp.h"\n'
         '#include "video_core/host_shaders/paint_key_comp.h"\n'),
        (B(r"""
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
"""), B(r"""
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
// The knobs' defaults are written twice: for the renderer (DrawnLookParams::Knobs) and for the
// ini (bbport_settings.h).
static_assert(DrawnLookParams::Knobs{}.strength == BbSettings::DrawnLookStrengthDefault &&
              DrawnLookParams::Knobs{}.stroke_size == BbSettings::DrawnLookStrokeSizeDefault &&
              DrawnLookParams::Knobs{}.texture == BbSettings::DrawnLookTextureDefault &&
              DrawnLookParams::Knobs{}.outlines == BbSettings::DrawnLookOutlinesDefault &&
              DrawnLookParams::Knobs{}.ink_world == BbSettings::DrawnLookInkWorldDefault &&
              DrawnLookParams::Knobs{}.characters == BbSettings::DrawnLookCharactersDefault);
""")),
        (B(r"""
                              int(DrawnLookParams::ViewMax));
    }
}
"""), B(r"""
                              int(DrawnLookParams::ViewMax));
    }
    env_line = DrawnLookParams::LineScaleOf(std::getenv("BB_DRAWN_LOOK_LINE"));
}
""")),
        (B(r"""
    return s.graphics_drawn_look.load(std::memory_order_relaxed) &&
           s.graphics_drawn_look_strength.load(std::memory_order_relaxed) > 0.0f;
"""), B(r"""
    return DrawnLookParams::Wanted(s.graphics_drawn_look.load(std::memory_order_relaxed),
                                   s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
                                   s.graphics_drawn_look_ink_world.load(std::memory_order_relaxed));
""")),
        (B(r"""
                   PAINT_LOCK_COMP, "Drawn look lock");
"""), B(r"""
                   PAINT_LOCK_COMP, "Drawn look lock") &&
        CreatePass(ink, {Sampled, SampledImage, StorageImage}, PAINT_INK_COMP, "Drawn look ink");
""")),
        (B(r"""
            BbReport::Printf("Drawn look: of %u frames, strokes painted before the transparents "
                             "on %u, before the fog composite (no transparents) on %u, before "
                             "the upscaler (neither: fog and particles painted too) on %u; not "
                             "painted: %u menu previews, %u without a camera, %u for want of "
                             "video memory, %u without a scene; what moves by itself told "
                             "against the camera of the frame before on %u\n",
                             frames, results[AtBlended], results[AtComposite],
                             results[AtBeforeUpscaler], results[Preview], results[NoCamera],
                             results[NoRoom], results[NotReached], previous_frames);
            results = {};
            frames = 0;
"""), B(r"""
            BbReport::Printf("Drawn look: of %u frames, painted before the transparents on %u, "
                             "before the fog composite (no transparents) on %u, before the "
                             "upscaler (neither: fog and particles painted too, no ink) on %u; "
                             "not painted: %u menu previews, %u without a camera, %u for want of "
                             "video memory, %u without a scene, %u with ink lines alone right "
                             "before the upscaler; ink lines on %u; what moves by itself told "
                             "against the camera of the frame before on %u\n",
                             frames, results[AtBlended], results[AtComposite],
                             results[AtBeforeUpscaler], results[Preview], results[NoCamera],
                             results[NoRoom], results[NotReached], results[LinesOnlyLate],
                             ink_frames, previous_frames);
            results = {};
            frames = 0;
            ink_frames = 0;
""")),
        ("            // Switched off (or the strength set to 0): the images go, the pipelines are kept.\n",
         "            // Switched off (or the strength and the ink lines set to 0): the images go, the\n"
         "            // pipelines are kept.\n"),
        (B(r"""
        frame_result = NoCamera;
        return;
    }
    if (!Ready()) {
"""), B(r"""
        frame_result = NoCamera;
        return;
    }
    const auto& s = BbSettings::Get();
    const DrawnLookParams::Knobs knobs{
        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
        .stroke_size = s.graphics_drawn_look_stroke_size.load(std::memory_order_relaxed),
        .texture = s.graphics_drawn_look_texture.load(std::memory_order_relaxed),
        .outlines = s.graphics_drawn_look_outlines.load(std::memory_order_relaxed),
        .ink_world = s.graphics_drawn_look_ink_world.load(std::memory_order_relaxed),
        .characters = s.graphics_drawn_look_characters.load(std::memory_order_relaxed),
        .line_scale = env_line,
        .view = env_view >= 0 ? env_view : int(DrawnLookParams::ViewOff),
    };
    // (r55_drawn-look-lines) Ink lines alone have nothing to draw right before the upscaler:
    // nothing is recorded, not even the copy.
    const auto passes = DrawnLookParams::PassesFor(knobs, place == AtBeforeUpscaler);
    if (!passes.strokes && !passes.ink) {
        frame_result = LinesOnlyLate;
        return;
    }
    if (!Ready()) {
""")),
        (B(r"""
    frame_result = place;

    const auto& s = BbSettings::Get();
    const DrawnLookParams::Knobs knobs{
        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
        .stroke_size = s.graphics_drawn_look_stroke_size.load(std::memory_order_relaxed),
        .texture = s.graphics_drawn_look_texture.load(std::memory_order_relaxed),
        .characters = s.graphics_drawn_look_characters.load(std::memory_order_relaxed),
        .view = env_view >= 0 ? env_view
                              : s.graphics_drawn_look_debug.load(std::memory_order_relaxed),
    };
    // (r45b_drawn-look-fixes) The camera of the frame before, when that frame was painted: the
"""), B(r"""
    frame_result = place;

    // (r45b_drawn-look-fixes) The camera of the frame before, when that frame was painted: the
""")),
        (B(r"""
    // A test view shows the strokes' places in colours of its own: no colours to lock.
    const bool locked = view == DrawnLookParams::ViewOff || view == DrawnLookParams::ViewInk;
    // The inputs may come and go from frame to frame (a frame painted right before the upscaler
    // has no G-buffer normals): their line is printed a few times, not on every change.
    const u32 inputs = params.flags & (DrawnLookParams::FlagNormals | DrawnLookParams::FlagMotion);
"""), B(r"""
    // A test view shows the strokes' places in colours of its own: no colours to lock.
    const bool locked = passes.lock;
    // (r55_drawn-look-lines) The ink pass's words: the frame's, three of its floats given the
    // ink's meanings (DrawnLookParams::MakeInk).
    const auto ink_params =
        DrawnLookParams::MakeInk(params, knobs.ink_world, knobs.outlines, knobs.line_scale);
    // The inputs may come and go from frame to frame (a frame painted right before the upscaler
    // has no G-buffer normals): their line is printed a few times, not on every change. So may
    // the passes (r55_drawn-look-lines: no ink right before the upscaler).
    const u32 inputs =
        (params.flags & (DrawnLookParams::FlagNormals | DrawnLookParams::FlagMotion)) |
        u32(passes.strokes) << 8 | u32(passes.ink) << 9;
""")),
        (B(r"""
        std::printf("Drawn look: on at %ux%u (%s), stroke cells %.1f and %.1f pixels, normals "
                    "from %s, object motion %s, %s\n",
                    width, height, reduced ? "reduced scene" : "the game's scene",
                    params.cell_bold, params.cell_fine, has_normal ? "the G-buffer" : "the depth",
                    has_motion ? "read" : "not there",
                    view == DrawnLookParams::ViewStrokes  ? "test view 1 (strokes, sizes as mixed)"
                    : view == DrawnLookParams::ViewFine   ? "test view 2 (strokes, all fine)"
                    : view == DrawnLookParams::ViewBold   ? "test view 4 (strokes, all bold)"
                                                          : "no test view");
"""), B(r"""
        char ink_text[64];
        if (passes.ink) {
            std::snprintf(ink_text, sizeof(ink_text), "ink lines %.2f (line scale %.2f)",
                          ink_params.strength, knobs.line_scale);
        } else {
            std::snprintf(ink_text, sizeof(ink_text), "%s",
                          knobs.ink_world > 0.0f ? "no ink lines here (right before the upscaler)"
                                                 : "no ink lines");
        }
        std::printf("Drawn look: on at %ux%u (%s), %sstroke cells %.1f and %.1f pixels, normals "
                    "from %s, object motion %s, %s, %s\n",
                    width, height, reduced ? "reduced scene" : "the game's scene",
                    passes.strokes ? "" : "no strokes, ", params.cell_bold, params.cell_fine,
                    has_normal ? "the G-buffer" : "the depth", has_motion ? "read" : "not there",
                    view == DrawnLookParams::ViewStrokes  ? "test view 1 (strokes, sizes as mixed)"
                    : view == DrawnLookParams::ViewFine   ? "test view 2 (strokes, all fine)"
                    : view == DrawnLookParams::ViewInk    ? "test view 3 (the ink page)"
                    : view == DrawnLookParams::ViewBold   ? "test view 4 (strokes, all bold)"
                                                          : "no test view",
                    ink_text);
""")),
        (B(r"""
    EffectPass::Mark(12, "drawn look strokes and colour lock");
    scheduler.RecordCrumb(
        {.name = "drawn look"},
        [params, width, height, locked, levels,"""), B(r"""
    // (r55_drawn-look-lines) The strokes and the lock when the frame has strokes, then the ink
    // lines in a row of their own.
    auto stroke_pass =
        [params, width, height, locked, levels,""")),
        (B(r"""
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

}
"""), B(r"""
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        };
    if (passes.strokes) {
        EffectPass::Mark(12, "drawn look strokes and colour lock");
        scheduler.RecordCrumb({.name = "drawn look"}, std::move(stroke_pass));
    }
    if (!passes.ink) {
        return;
    }
    ++ink_frames;
    // The upscaler's extra sharpening on this frame (DrawnLookParams::InkSharpen).
    BbSettings::Get().drawn_look_ink_drawn.store(ink_params.strength, std::memory_order_relaxed);
    ink_published = true;
    EffectPass::Mark(13, "drawn look ink");
    scheduler.RecordCrumb(
        {.name = "drawn look ink"},
        [ink_params, width, height, color_view, depth_view, sampler = *sampler,
         prep_view = *prep_copy.view, ink_pipeline = *ink.pipeline,
         ink_layout = *ink.layout](vk::CommandBuffer cmdbuf) {
            // The scene colour (the strokes' crumb) and the key (the masks') are written.
            EffectPass::ComputeBarrier(cmdbuf);
            const std::array infos{Info(prep_view, sampler), Info(depth_view), Info(color_view)};
            const std::array writes{Write(0, Sampled, &infos[0]), Write(1, SampledImage, &infos[1]),
                                    Write(2, StorageImage, &infos[2])};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, ink_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, ink_layout, 0, writes);
            cmdbuf.pushConstants(ink_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                 sizeof(ink_params), &ink_params);
            cmdbuf.dispatch((width + 7) / 8, (height + 7) / 8, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

}
""")),
    ],
    R + "vk_temporal_upscaler.cpp": [
        ('#include "video_core/renderer_vulkan/vk_camera_motion.h"\n',
         '#include "video_core/renderer_vulkan/drawn_look_params.h" // bbport (r55_drawn-look-lines)\n'
         '#include "video_core/renderer_vulkan/vk_camera_motion.h"\n'),
        (B(r"""
    const float extra = std::clamp(settings.sharpness.load(), 0.0f, 2.0f) - own;
    return settings.sharpen && extra > 0.0f ? extra : 0.0f;
"""), B(r"""
    const float extra = std::clamp(settings.sharpness.load(), 0.0f, 2.0f) - own;
    // bbport (r55_drawn-look-lines): this pass sharpens the drawn look's ink lines as it sharpens
    // any edge; on a frame that recorded them it is lowered, by up to half
    // (DrawnLookParams::InkSharpen; drawn_look_ink_drawn is 0 on every other frame).
    const float ink =
        DrawnLookParams::InkSharpen(settings.drawn_look_ink_drawn.load(std::memory_order_relaxed));
    return settings.sharpen && extra > 0.0f ? extra * ink : 0.0f;
""")),
    ],
    S + "bbport_settings.h": [
        (B(r"""
inline constexpr float DrawnLookStrokeSizeMin = 0.6f, DrawnLookStrokeSizeMax = 1.4f;
inline constexpr float DrawnLookTextureMax = 1.2f;
"""), B(r"""
inline constexpr float DrawnLookStrokeSizeMin = 0.6f, DrawnLookStrokeSizeMax = 1.4f,
                       DrawnLookStrokeSizeDefault = 1.0f; // bbport (r55_drawn-look-lines)
inline constexpr float DrawnLookTextureMax = 1.2f, DrawnLookTextureDefault = 1.0f; // (r55)
""")),
        ("inline constexpr int DrawnLookDebugMax = 4; // DrawnLookParams::ViewMax (drawn_look_params.h)\n",
         "inline constexpr float DrawnLookInkWorldDefault = 0.35f; // bbport (r55_drawn-look-lines)\n"),
        ("    std::atomic<float> graphics_drawn_look_stroke_size{1.0f};  // 0.6..1.4, a factor on the strokes' size\n"
         "    std::atomic<float> graphics_drawn_look_texture{1.0f};      // 0..1.2, the brush's marks in a stroke\n",
         "    std::atomic<float> graphics_drawn_look_stroke_size{DrawnLookStrokeSizeDefault}; // 0.6..1.4, a factor on the strokes' size\n"
         "    std::atomic<float> graphics_drawn_look_texture{DrawnLookTextureDefault}; // 0..1.2, the brush's marks in a stroke\n"),
        (B(r"""
    // Why the drawn look cannot run, for the menu; null while it can. Set by the renderer.
    std::atomic<const char*> drawn_look_problem{nullptr};
"""), B(r"""
    // Why the drawn look cannot run, for the menu; null while it can. Set by the renderer.
    std::atomic<const char*> drawn_look_problem{nullptr};
    // bbport (r55_drawn-look-lines): the weight of the ink lines this frame recorded
    // (DrawnLookParams::MakeInk's strength), 0 on a frame without them. Set by the renderer, not
    // a key; the upscaler's extra sharpening reads it (DrawnLookParams::InkSharpen).
    std::atomic<float> drawn_look_ink_drawn{0.0f};
""")),
        (B(r"""
    // vk_drawn_look.h). All live. While the switch is off or the strength is 0 nothing of it
    // runs. The renderer reads the switch, strength, stroke_size, texture, characters and debug
    // so far; the others are parsed, clamped and saved for the parts of the look that are not
    // built yet (ink lines, painted shadow edges).
"""), B(r"""
    // vk_drawn_look.h). All live. While the switch is off, or the strength and ink_world are both
    // 0, nothing of it runs. The renderer reads the switch, strength, stroke_size, texture,
    // characters and (r55_drawn-look-lines) ink_world; outlines is handed to the ink pass, which
    // does not read it yet; the others are parsed, clamped and saved for the parts of the look
    // that are not built yet (painted shadow edges). The test views are BB_DRAWN_LOOK_VIEW only
    // (r55: graphics_drawn_look_debug is no key; a line of it in the ini is kept, not read).
""")),
        ("    std::atomic<float> graphics_drawn_look_strength{DrawnLookStrengthDefault}; // 0..1; 0: no pass\n",
         "    std::atomic<float> graphics_drawn_look_strength{DrawnLookStrengthDefault}; // 0..1; 0: no strokes\n"),
        ("    std::atomic<float> graphics_drawn_look_ink_world{0.0f};    // 0..1, ink on the world\n",
         "    std::atomic<float> graphics_drawn_look_ink_world{DrawnLookInkWorldDefault}; // 0..1, ink lines; 0: none\n"),
        (B(r"""
    std::atomic<int> graphics_drawn_look_quality{1};           // 0 low, 1 high
    // 0 the look; 1, 2, 4 the test view: every stroke in a flat colour of its own (sizes as the
    // look mixes them, all fine, all bold); 3 is kept for the ink lines' view.
    std::atomic<int> graphics_drawn_look_debug{0};
"""), "    std::atomic<int> graphics_drawn_look_quality{1};           // 0 low, 1 high\n"),
    ],
    S + "bbport_settings.cpp": [
        ("        v.graphics_drawn_look_stroke_size =\n"
         "            Clamp(std::isfinite(f) ? f : 1.0f, DrawnLookStrokeSizeMin, DrawnLookStrokeSizeMax);\n",
         "        v.graphics_drawn_look_stroke_size = Clamp(std::isfinite(f) ? f : DrawnLookStrokeSizeDefault,\n"
         "                                                  DrawnLookStrokeSizeMin, DrawnLookStrokeSizeMax);\n"),
        ("        v.graphics_drawn_look_texture = Clamp(std::isfinite(f) ? f : 1.0f, 0.0f, DrawnLookTextureMax);\n",
         "        v.graphics_drawn_look_texture =\n"
         "            Clamp(std::isfinite(f) ? f : DrawnLookTextureDefault, 0.0f, DrawnLookTextureMax);\n"),
        ("        v.graphics_drawn_look_ink_world = Clamp(std::isfinite(f) ? f : 0.0f, 0.0f, 1.0f);\n",
         "        v.graphics_drawn_look_ink_world = Clamp(std::isfinite(f) ? f : DrawnLookInkWorldDefault, 0.0f, 1.0f);\n"),
        (B(r"""
        v.graphics_drawn_look_quality = std::clamp(i, 0, 1);
    } else if (key == "graphics_drawn_look_debug") {
        v.graphics_drawn_look_debug = std::clamp(i, 0, DrawnLookDebugMax);
"""), "        v.graphics_drawn_look_quality = std::clamp(i, 0, 1);\n"),
        (B(r"""
    put("graphics_drawn_look_quality", std::to_string(std::clamp(v.graphics_drawn_look_quality.load(), 0, 1)));
    put("graphics_drawn_look_debug",
        std::to_string(std::clamp(v.graphics_drawn_look_debug.load(), 0, DrawnLookDebugMax)));
"""), "    put(\"graphics_drawn_look_quality\", std::to_string(std::clamp(v.graphics_drawn_look_quality.load(), 0, 1)));\n"),
    ],
    S + "bbport_overlay.cpp": [
        ('#include "bbport_menu_i18n.h"\n#include "bbport_settings.h"\n',
         '#include "bbport_drawn_look_texts.h" // bbport (r55_drawn-look-lines)\n'
         '#include "bbport_menu_i18n.h"\n#include "bbport_settings.h"\n'),
        (OVERLAY_OLD, OVERLAY_NEW),
    ],
    S + "bbport_menu_i18n.cpp": I18N_EDITS,
    HS + "paint_strokes.comp": [
        ("// In the test view (graphics_drawn_look_debug 1, 2 or 4) every dab has a flat colour of its\n",
         "// In the test view (BB_DRAWN_LOOK_VIEW 1, 2 or 4) every dab has a flat colour of its\n"),
    ],
    HS + "paint_common.glsl": [
        ("// paint_key.comp, paint_strokes.comp and paint_lock.comp, recorded by\n",
         "// paint_key.comp, paint_strokes.comp, paint_lock.comp and paint_ink.comp, recorded by\n"),
    ],
    G + "CMakeLists.txt": [
        ("add_host_shader(paint_lock.comp paint_lock_comp)\n",
         "add_host_shader(paint_lock.comp paint_lock_comp)\n"
         "add_host_shader(paint_ink.comp paint_ink_comp) # bbport (r55_drawn-look-lines)\n"),
        ("add_dependencies(drawn-look-test host_shaders)\n",
         "add_dependencies(drawn-look-test host_shaders)\n"
         "# bbport (r55_drawn-look-lines): the drawn look's rules that need no GPU (drawn_look_params.h:\n"
         "# which passes a frame records, the ink pass's words, BB_DRAWN_LOOK_LINE); also in build.sh --test.\n"
         "add_executable(drawn-look-rules-test EXCLUDE_FROM_ALL ../tests/test_drawn_look_rules.cpp)\n"
         "target_compile_options(drawn-look-rules-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(drawn-look-rules-test PRIVATE ..)\n"),
    ],
    E + "build.sh": [
        ("    out/motion-history-test\n",
         "    out/motion-history-test\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_drawn_look_rules.cpp -o out/drawn-look-rules-test\n'
         "    out/drawn-look-rules-test\n"),
    ],
    TESTS + "test_settings.cpp": [
        ('#include "gpu/shim/bbport_settings.h"\n',
         '#include "gpu/shim/bbport_drawn_look_texts.h" // bbport (r55_drawn-look-lines)\n'
         '#include "gpu/shim/bbport_menu_i18n.h"\n'
         '#include "gpu/shim/bbport_settings.h"\n'),
        (B(r"""
    s.menu_language = BbSettings::MenuLanguage::Russian;
    assert(std::string(BbSettings::MenuText("Close", "Закрыть")) == "Закрыть");
"""), B(r"""
    s.menu_language = BbSettings::MenuLanguage::Russian;
    assert(std::string(BbSettings::MenuText("Close", "Закрыть")) == "Закрыть");
    // bbport (r55_drawn-look-lines): every text of the drawn look's rows and problems has its entry
    // in all eight tables (a text changed in bbport_drawn_look_texts.h without them fails here),
    // and a problem the renderer set is shown in Russian too.
    namespace DrawnText = BbSettings::DrawnLookTexts;
    for (const DrawnText::Text* text : DrawnText::All) {
        for (int l = int(BbSettings::MenuLanguage::Spanish); l < BbSettings::MenuLanguageCount;
             ++l) {
            const auto language = BbSettings::MenuLanguage(l);
            if (BbSettings::MenuTranslation(language, text->english) == text->english) {
                std::fprintf(stderr, "no %s entry for \"%s\"\n", BbSettings::MenuLanguageCodes[l],
                             text->english);
                assert(false);
            }
        }
    }
    for (const DrawnText::Text* text : DrawnText::Problems) {
        const char* const russian = DrawnText::RussianOf(text->english);
        assert(std::string(BbSettings::MenuText(text->english, russian)) == text->russian);
    }
    assert(std::string(DrawnText::RussianOf("not a problem")) == "not a problem");
""")),
        (B(r"""
           s.graphics_drawn_look_ink_world == 0.0f && s.graphics_drawn_look_characters == 0.5f &&
           s.graphics_drawn_look_shadow_soft == 0.12f && s.graphics_drawn_look_quality == 1 &&
           s.graphics_drawn_look_debug == 0 && !s.drawn_look_problem.load());
"""), B(r"""
           s.graphics_drawn_look_ink_world == BbSettings::DrawnLookInkWorldDefault &&
           s.graphics_drawn_look_characters == 0.5f && s.graphics_drawn_look_shadow_soft == 0.12f &&
           s.graphics_drawn_look_quality == 1 && !s.drawn_look_problem.load());
    static_assert(BbSettings::DrawnLookInkWorldDefault == 0.35f);
""")),
        (B(r"""
              "graphics_drawn_look_ink_world=0.00\n", "graphics_drawn_look_characters=0.50\n",
              "graphics_drawn_look_shadow_soft=0.12\n", "graphics_drawn_look_quality=1\n",
              "graphics_drawn_look_debug=0\n"}) {
            assert(text.find(line) != std::string::npos);
        }
    }
"""), B(r"""
              "graphics_drawn_look_ink_world=0.35\n", "graphics_drawn_look_characters=0.50\n",
              "graphics_drawn_look_shadow_soft=0.12\n", "graphics_drawn_look_quality=1\n"}) {
            assert(text.find(line) != std::string::npos);
        }
        // (r55_drawn-look-lines) The test views are BB_DRAWN_LOOK_VIEW only: no key.
        assert(text.find("graphics_drawn_look_debug") == std::string::npos);
    }
""")),
        (B(r"""
           s.graphics_drawn_look_shadow_soft == 0.2f && s.graphics_drawn_look_quality == 0 &&
           s.graphics_drawn_look_debug == 4);
    s.graphics_drawn_look_strength = 0.0f; // the menu's slider at its lower end: the look does no work
    s.graphics_drawn_look_debug = 1;
"""), B(r"""
           s.graphics_drawn_look_shadow_soft == 0.2f && s.graphics_drawn_look_quality == 0);
    s.graphics_drawn_look_strength = 0.0f; // the menu's slider at its lower end: no strokes
    s.graphics_drawn_look_ink_world = 0.7f;
""")),
        (B(r"""
        assert(text.find("graphics_drawn_look_debug=1\n") != std::string::npos);
"""), B(r"""
        assert(text.find("graphics_drawn_look_ink_world=0.70\n") != std::string::npos);
        // The old key's line stays as it was, and nothing reads it.
        assert(text.find("graphics_drawn_look_debug=4\n") != std::string::npos);
""")),
        (B(r"""
                                        "graphics_drawn_look_shadow_soft=1\ngraphics_drawn_look_quality=5\n"
                                        "graphics_drawn_look_debug=9\n"; }
"""), B(r"""
                                        "graphics_drawn_look_shadow_soft=1\ngraphics_drawn_look_quality=5\n"; }
""")),
        ("           s.graphics_drawn_look_quality == 1 && s.graphics_drawn_look_debug == BbSettings::DrawnLookDebugMax);\n",
         "           s.graphics_drawn_look_quality == 1);\n"),
        (B(r"""
                                        "graphics_drawn_look_quality=-3\ngraphics_drawn_look_debug=-1\n"; }
"""), B(r"""
                                        "graphics_drawn_look_quality=-3\ngraphics_drawn_look_ink_world=-1\n"; }
""")),
        ("           s.graphics_drawn_look_quality == 0 && s.graphics_drawn_look_debug == 0);\n",
         "           s.graphics_drawn_look_quality == 0 && s.graphics_drawn_look_ink_world == 0.0f);\n"),
        ("           s.graphics_drawn_look_shadow_edges == 1.0f && s.graphics_drawn_look_ink_world == 0.0f &&\n",
         "           s.graphics_drawn_look_shadow_edges == 1.0f &&\n"
         "           s.graphics_drawn_look_ink_world == BbSettings::DrawnLookInkWorldDefault &&\n"),
    ],
    TESTS + "test_effect_pipelines.cpp": [
        ('#include "video_core/host_shaders/paint_key_comp.h"\n',
         '#include "video_core/host_shaders/paint_ink_comp.h"\n'
         '#include "video_core/host_shaders/paint_key_comp.h"\n'),
        (B(r"""
        // bbport (r45_drawn-look): as vk_drawn_look.cpp makes them (DrawnLookParams::Params)
        {"drawn look prep", PAINT_PREP_COMP, {eSampledImage, eSampledImage, eStorageImage}, 112},
        {"drawn look stats", PAINT_STATS_COMP, {eSampledImage, eStorageImage, eStorageImage}, 112},
        {"drawn look mips",
         PAINT_MIPS_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
         112},
        {"drawn look key sums", PAINT_KEY_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look key", PAINT_KEY_LAST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look strokes",
         PAINT_STROKES_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
        {"drawn look lock means", PAINT_LOCK_FIRST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look lock levels",
         PAINT_LOCK_DOWN_COMP,
         {eCombinedImageSampler, eStorageImage},
         112},
        {"drawn look lock",
         PAINT_LOCK_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
"""), B(r"""
        // bbport (r45_drawn-look): as vk_drawn_look.cpp makes them (DrawnLookParams::Params, 128
        // bytes since r45b; r55_drawn-look-lines: the ink pass)
        {"drawn look prep", PAINT_PREP_COMP, {eSampledImage, eSampledImage, eStorageImage}, 128},
        {"drawn look stats", PAINT_STATS_COMP, {eSampledImage, eStorageImage, eStorageImage}, 128},
        {"drawn look mips",
         PAINT_MIPS_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
         128},
        {"drawn look key sums", PAINT_KEY_COMP, {eSampledImage, eStorageImage}, 128},
        {"drawn look key", PAINT_KEY_LAST_COMP, {eSampledImage, eStorageImage}, 128},
        {"drawn look strokes",
         PAINT_STROKES_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         128},
        {"drawn look lock means", PAINT_LOCK_FIRST_COMP, {eSampledImage, eStorageImage}, 128},
        {"drawn look lock levels",
         PAINT_LOCK_DOWN_COMP,
         {eCombinedImageSampler, eStorageImage},
         128},
        {"drawn look lock",
         PAINT_LOCK_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         128},
        {"drawn look ink",
         PAINT_INK_COMP,
         {eCombinedImageSampler, eSampledImage, eStorageImage},
         128},
""")),
    ],
    TESTS + "test_drawn_look.cpp": [
        (B(r"""
//    transparents (DrawnLookParams::SmallTransparent).
//
"""), B(r"""
//    transparents (DrawnLookParams::SmallTransparent);
//  - (r55_drawn-look-lines) the ink lines (paint_ink.comp), the passes recorded as
//    DrawnLookParams::PassesFor says: on the silhouettes, on the near side, not on plain
//    surfaces; a line pixel is its own colour darker; the same at another exposure and under the
//    jitter; on top of the strokes; the ink page (test view 3).
//
""")),
        ('#include "video_core/host_shaders/paint_key_comp.h"\n',
         '#include "video_core/host_shaders/paint_ink_comp.h"\n'
         '#include "video_core/host_shaders/paint_key_comp.h"\n'),
        (B(r"""
                        PAINT_LOCK_COMP);
        sampler = Check(device->createSamplerUnique(
"""), B(r"""
                        PAINT_LOCK_COMP);
        ink = MakePass({eCombinedImageSampler, eSampledImage, eStorageImage}, PAINT_INK_COMP);
        sampler = Check(device->createSamplerUnique(
""")),
        (B(r"""
    /// The scene colour after the passes.
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params) {
        Load(scene);
        Begin();
        RecordMasks(params);
        RecordStrokes(params);
        if (ShowsLook(params)) {
            RecordLock(params);
        }
"""), B(r"""
    /// The scene colour after the passes, recorded as the renderer records them on a frame
    /// painted before the transparents (DrawnLookParams::PassesFor). `ink_world`, `line_scale`:
    /// the ink lines' knobs (r55_drawn-look-lines; 0: no ink, as before).
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params, float ink_world = 0.0f,
                           float line_scale = 1.0f) {
        Look::Knobs knobs;
        knobs.strength = params.strength;
        knobs.ink_world = ink_world;
        knobs.line_scale = line_scale;
        knobs.view = int(Look::ViewOf(params.flags));
        const Look::Passes passes = Look::PassesFor(knobs, false);
        Load(scene);
        Begin();
        RecordMasks(params);
        if (passes.strokes) {
            RecordStrokes(params);
        }
        if (passes.lock) {
            RecordLock(params);
        }
        if (passes.ink) {
            RecordInk(Look::MakeInk(params, ink_world, knobs.outlines, line_scale));
        }
""")),
        (B(r"""
    /// The colour lock runs with the look; a test view has no colours to lock.
    static bool ShowsLook(const Look::Params& params) {
        const u32 view = Look::ViewOf(params.flags);
        return view == Look::ViewOff || view == Look::ViewInk;
    }

    void Load(const Scene& scene) {
"""), "    void Load(const Scene& scene) {\n"),
        (B(r"""
        Dispatch(lock, params, writes, width, height);
    }
"""), B(r"""
        Dispatch(lock, params, writes, width, height);
    }

    /// (r55_drawn-look-lines) As vk_drawn_look.cpp records it, last.
    void RecordInk(const Look::Params& ink_params) {
        using enum vk::DescriptorType;
        const std::array infos{Info(copy.view, true), Info(depth.view), Info(colour.view)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eStorageImage, &infos[2])};
        Dispatch(ink, ink_params, writes, width, height);
    }
""")),
        ("    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;\n",
         "    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;\n"),
        (B(r"""
        Expect(painted > surface * 0.6, "strokes cover most of the surfaces");
        if (view == Look::ViewOff) {
            // The view kept for the ink lines shows the look, as no view does.
            Expect(gpu.Run(scene, Words(lens, straight, Look::ViewInk)) == out,
                   "view 3 (kept for the ink lines) shows the look");
        }
    }
"""), B(r"""
        Expect(painted > surface * 0.6, "strokes cover most of the surfaces");
    }
""")),
        (B(r"""
    if (argc > 1) {
        const Lens half{960, 540};
"""), INK_TEST + B(r"""
    if (argc > 1) {
        const Lens half{960, 540};
""")),
    ],
    ROOT + "README.md": [
        ("| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on "
         "the world's surfaces, bold on plain walls and floors and fine where there is detail. Fire, glows, fog, "
         "particles and the HUD are not painted, colours are not changed. Ink lines and painted shadow edges are not "
         "built yet | off |\n",
         "| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on "
         "the world's surfaces, bold on plain walls and floors and fine where there is detail, and ink lines along "
         "the silhouettes of shapes. Fire, glows, fog, particles and the HUD are not painted, colours are not changed "
         "(an ink line is the surface's own colour, darker). Ink on inner edges, heavier ink on characters and "
         "painted shadow edges are not built yet | off |\n"),
        ("| `graphics_drawn_look_strength` | Drawn look strength, 0 to 1: how much of the strokes is laid over the "
         "game's picture (at 0 the look does no work) | `0.6` |\n",
         "| `graphics_drawn_look_strength` | Drawn look strength, 0 to 1: how much of the strokes is laid over the "
         "game's picture (at 0 no strokes; the ink lines stay while `graphics_drawn_look_ink_world` is above 0) "
         "| `0.6` |\n"),
        ("| `graphics_drawn_look_debug` | Drawn look test view while the look is on: `1` paints every stroke in a flat "
         "colour of its own, bold and fine as the look mixes them, `2` the same with all strokes fine, `4` with all "
         "strokes bold (`3` is kept for the ink lines) | `0` |\n"
         "| `graphics_drawn_look_outlines`, `_shadow_edges`, `_ink_world`, `_shadow_soft`, `_quality` | Drawn look: "
         "kept for parts of the look that are not built yet (character ink, painted shadow edges and world ink 0 to "
         "1, shadow softness 0.05 to 0.3, quality 0 or 1); read, clamped and saved, without effect so far | `0.35`, "
         "`1.0`, `0`, `0.12`, `1` |\n",
         "| `graphics_drawn_look_ink_world` | Drawn look ink lines, 0 to 1: how dark the ink lines along the "
         "silhouettes of shapes are (pillars, walls, steps and figures against what lies behind them); 0 is no "
         "lines. A line is 1.5 pixels of a 1080-line picture wide near the camera and narrows from 4 m on; from "
         "about 9 m it grows fainter (to a third from 16 m), the same at every render size, and it fades out "
         "between 40 and 120 m. A line pixel's colour is multiplied by mix(1, f, weight), f = min(0.3 x its "
         "brightness, 0.05 x the frame's key) / its brightness, so its hue stays. Something nearer than what lies "
         "on both sides of it within about two line widths (a railing, a branch) gets half the weight. Not drawn "
         "on frames the look paints right before the upscaler. On a frame with lines the upscaler's extra "
         "sharpening is multiplied by 1 - 0.5 x the lines' weight (this value; 1 in the ink page). Every save "
         "since the look came wrote this key, then unread, as `0.00`: an existing lantern.ini keeps it at 0 "
         "until the menu row is set. Live; menu row \"Drawn look ink lines\" | `0.35` |\n"
         "| `graphics_drawn_look_outlines`, `_shadow_edges`, `_shadow_soft`, `_quality` | Drawn look: kept for "
         "parts of the look that are not built yet (character ink, painted shadow edges 0 to 1, shadow softness "
         "0.05 to 0.3, quality 0 or 1); read, clamped and saved, without effect so far | `0.35`, `1.0`, `0.12`, "
         "`1` |\n"),
        ("`BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view (as `graphics_drawn_look_debug`) while "
         "the look is on, without writing it to the ini.",
         "`BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view while the look is on: every stroke in "
         "a flat colour of its own, bold and fine as the look mixes them, all fine, all bold; `3` the ink page (no "
         "strokes, a grey page with the ink lines on it at full weight). A test view shows only while the look "
         "runs, that is with its strength or its ink lines above 0. `BB_DRAWN_LOOK_LINE=0.5` to `2` (default `1`) "
         "scales the ink lines' width in pixels (a line under one pixel is drawn one pixel wide, lighter); it does "
         "not change where lines show. Neither is written to the ini; a `graphics_drawn_look_debug` line left in "
         "it is kept and not read."),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def literals(text):
    """Every run of adjacent C++ string literals in `text`, joined (escapes left as written)."""
    out = []
    for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"(?:\s*"(?:[^"\\\n]|\\.)*")*', text):
        out.append("".join(re.findall(r'"((?:[^"\\\n]|\\.)*)"', m.group(0))))
    return out


def text_check(texts):
    """What the patch relies on in the patched text."""
    ok = True
    texts = {p: t.replace("\r\n", "\n") for p, t in texts.items()}
    if any(foreign(p) for p in list(EDITS) + list(NEW_FILES)):
        print("this round would touch another round's file")
        ok = False
    h, cpp = texts[S + "bbport_settings.h"], texts[S + "bbport_settings.cpp"]
    if any(x in h + cpp for x in ("graphics_drawn_look_debug{", '"graphics_drawn_look_debug"',
                                  ".graphics_drawn_look_debug")) or \
            "DrawnLookDebugMax" in h + cpp + texts[TESTS + "test_settings.cpp"]:
        print("bbport_settings: graphics_drawn_look_debug is still a key")
        ok = False
    if h.count("DrawnLookInkWorldDefault") != 2 or cpp.count("DrawnLookInkWorldDefault") != 1:
        print("bbport_settings: the ink default is not the atomic's and the fallback's once each")
        ok = False
    params = texts[R + "drawn_look_params.h"]
    if "float ink_world = 0.35f;" not in params or params.count("constexpr Passes PassesFor(") != 1 or \
            params.count("constexpr bool Wanted(") != 1:
        print("drawn_look_params.h: the ink's rules are not there once")
        ok = False
    look = texts[R + "vk_drawn_look.cpp"]
    if "graphics_drawn_look_debug" in look + texts[R + "vk_drawn_look.h"] + texts[HS + "paint_strokes.comp"]:
        print("the renderer still reads graphics_drawn_look_debug")
        ok = False
    want = look.find("bool DrawnLook::Wanted() {")
    if "DrawnLookParams::Wanted(" not in look[want:want + 400]:
        print("vk_drawn_look.cpp: Wanted() does not ask DrawnLookParams::Wanted")
        ok = False
    # The knobs and the passes come before Ready(), the strokes' crumb before the ink's, and the ink
    # crumb is the last thing Paint records.
    paint = look.find("void DrawnLook::Paint(")
    at = [look.find(x, paint) for x in ("const auto passes = DrawnLookParams::PassesFor(", "    if (!Ready()) {",
                                        "EffectPass::Mark(18,", "EffectPass::Mark(12,", "EffectPass::Mark(13,")]
    if min(at) < 0 or at != sorted(at) or look.count("DrawnLookParams::Knobs knobs{") != 1 or \
            look.count("EffectPass::Mark(13,") != 1 or look.count('PAINT_INK_COMP, "Drawn look ink")') != 1:
        print("vk_drawn_look.cpp: the passes are not recorded in the order strokes, lock, ink")
        ok = False
    cmake, build = texts[G + "CMakeLists.txt"], texts[E + "build.sh"]
    if cmake.count("add_host_shader(paint_ink.comp paint_ink_comp)") != 1 or \
            cmake.count("add_executable(drawn-look-rules-test ") != 1 or \
            build.count("tests/test_drawn_look_rules.cpp -o out/drawn-look-rules-test") != 1 or \
            build.count("    out/drawn-look-rules-test\n") != 1:
        print("the ink shader or the rules test is not registered once (CMakeLists.txt, build.sh)")
        ok = False
    # The menu: every text in each of the eight tables once (kChinese had "Unavailable"), each
    # English and Russian text a constant of bbport_drawn_look_texts.h, which the overlay and the
    # renderer use in place of their own literals (settings-test checks the tables against it).
    i18n = texts[S + "bbport_menu_i18n.cpp"]
    header = NEW_FILES[S + "bbport_drawn_look_texts.h"]
    passed = set(literals(header))
    overlay = texts[S + "bbport_overlay.cpp"]
    for k, en in enumerate(K):
        if i18n.count('    {"%s",' % en) != 8:
            print("bbport_menu_i18n.cpp: %r is not in the eight tables once" % en[:40])
            ok = False
        if en not in passed or RU[k] not in passed or header.count("inline constexpr Text %s{" % NAMES[k]) != 1:
            print("bbport_drawn_look_texts.h: %r is not its constant %s" % (en[:40], NAMES[k]))
            ok = False
        # ("Unavailable" is also a text of other rows of the overlay.)
        if k != 13 and en in set(literals(overlay)) | set(literals(look)):
            print("%r is still a literal of the overlay or the renderer" % en[:40])
            ok = False
        if k in (0, 1, 2, 3, 4, 5, 6, 13) and "DrawnText::%s" % NAMES[k] not in overlay:
            print("bbport_overlay.cpp does not show %s" % NAMES[k])
            ok = False
        if 7 <= k <= 12 and look.count("BbSettings::DrawnLookTexts::%s.english" % NAMES[k]) != 1:
            print("vk_drawn_look.cpp does not name the problem %s once" % NAMES[k])
            ok = False
    if "DrawnText::RussianOf(drawn_problem)" not in overlay or 'Fail("' in look or \
            'drawn_look_problem = "' in look:
        print("a drawn look problem is not one of bbport_drawn_look_texts.h, or not shown in Russian")
        ok = False
    if overlay.count("Item(DrawnText::Ink.english, DrawnText::Ink.russian)") != 1 or \
            overlay.count("Slider(label, s.graphics_drawn_look_ink_world, 0.0f, 1.0f,") != 1:
        print("bbport_overlay.cpp: the ink row is not there once")
        ok = False
    settings_test = texts[TESTS + "test_settings.cpp"]
    if "for (const DrawnText::Text* text : DrawnText::All) {" not in settings_test:
        print("test_settings.cpp does not check the drawn look's texts against the tables")
        ok = False
    # The sharpening follows the ink lines a frame recorded: set where the ink crumb is recorded,
    # put back at the frame's end, read by the upscaler; the knobs' six defaults tied.
    upscaler = texts[R + "vk_temporal_upscaler.cpp"]
    if look.count("drawn_look_ink_drawn.store(ink_params.strength,") != 1 or \
            look.count("drawn_look_ink_drawn.store(0.0f,") != 1 or \
            upscaler.count("InkSharpen(settings.drawn_look_ink_drawn.load(") != 1 or \
            h.count("std::atomic<float> drawn_look_ink_drawn{0.0f};") != 1 or \
            "graphics_drawn_look_ink_world" in upscaler:
        print("the upscaler's sharpening does not follow the ink lines the frame recorded")
        ok = False
    tie = look[look.find("static_assert(DrawnLookParams::Knobs{}"):]
    tie = tie[:tie.find(";")]
    for field, const in (("strength", "Strength"), ("stroke_size", "StrokeSize"), ("texture", "Texture"),
                         ("outlines", "Outlines"), ("ink_world", "InkWorld"), ("characters", "Characters")):
        if "Knobs{}.%s == BbSettings::DrawnLook%sDefault" % (field, const) not in tie:
            print("vk_drawn_look.cpp: the default of %s is not tied" % field)
            ok = False
    for const in ("StrokeSize", "Texture"):
        if h.count("DrawnLook%sDefault" % const) != 2 or cpp.count("DrawnLook%sDefault" % const) != 1:
            print("bbport_settings: DrawnLook%sDefault is not the atomic's and the fallback's" % const)
            ok = False
    glyphs = set()
    if os.path.isfile(GLYPHS):
        glyphs = {int(x.strip()[2:], 16) for x in open(GLYPHS, encoding="utf-8").read().split(",") if x.strip()}
    else:
        print("cannot check the menu's Chinese text: %s is missing" % GLYPHS)
        ok = False
    missing = sorted({c for t in TABLES["kChinese"][1] if t for c in t if ord(c) > 0x7e and ord(c) not in glyphs})
    if glyphs and missing:
        print("the menu's Chinese text uses characters the menu font does not have: %s" % "".join(missing))
        ok = False
    # The C escapes must have kept their backslash on the way into this script.
    bs = chr(92)
    if 'before the upscaler; ink lines on %u; what moves by itself told "' not in look or \
            '"against the camera of the frame before on %u' + bs + 'n",' not in look or \
            '"from %s, object motion %s, %s, %s' + bs + 'n",' not in look or \
            'std::puts("PASS: drawn look rules");' not in NEW_FILES[TESTS + "test_drawn_look_rules.cpp"] or \
            'pixels changed, %u of them not darker, hue moved "' not in texts[TESTS + "test_drawn_look.cpp"] or \
            '"graphics_drawn_look_ink_world=0.70' + bs + 'n"' not in texts[TESTS + "test_settings.cpp"]:
        print("a C escape lost its backslash, or a text is missing")
        ok = False
    ink = NEW_FILES[HS + "paint_ink.comp"]
    if '#include "paint_common.glsl"' not in ink or "layout(binding = 2, rgba16f) uniform image2D scene_img;" not in ink:
        print("paint_ink.comp is not the shader the pass is made for")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
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
            if not a:
                # A deletion reverted: put back before the text that follows it.
                print("internal: an edit with an empty side cannot be reverted")
                return None
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
        elif not os.path.isdir(os.path.dirname(path)):
            if not quiet:
                print("no such directory: %s" % os.path.dirname(path))
            return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r55_drawn-look-lines.py check|apply|revert   (the tree: R55_ROOT, else the current "
              "directory)")
        return 2
    # run() only reads: nothing is written before every text of the mode is made.
    out = run(mode, quiet=True)
    if out is None:
        if mode != "revert" and run("revert", quiet=True) is not None:
            print("already applied (revert would restore the tree)" if mode == "check"
                  else "already applied: nothing written")
        elif mode == "revert" and run("check", quiet=True) is not None:
            print("not applied: nothing to revert")
        else:
            run(mode)  # says which anchor, or what else is wrong
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
