# r106c_shaft-march-cheaper: FEATURE patch (an optimization of the lamp fog shafts' march; sits on r80,
# r88, r106; the owner's order item 3 "Lamp and torch shafts through fog" and the standing rule that every
# pass through changed code looks for a cheaper way, never at the cost of looks).
#
# Why: the 4K cost runs of 2026-11-16 04:30-04:45 (DLSS, BB_GPU_PROFILE=1, 3 interleaved repeats) put
# the shafts' cost in the march: 'Lighting: lamp fog' 0.212 -> 0.430 ms (+0.218) at dark-alley, 0.266 ->
# 0.461 (+0.195) at church-candles (52 lamps); the capped map pass is only +0.026. Each pixel, each lamp
# whose sphere the view ray crosses, 2 halves x Segments samples (6 at BB_LAMP_FOG_SHAFTS=1, 12 at 2): each
# sample atan, tan, a matrix, an octahedral encode and one 4-texel textureGather of the lamp's map.
#
# What it does (point_volumetric.comp, the builds made with SHAFTS only; push constant shaft_fast = 1):
#  1. Map reads at every second sample. A half chord's samples 0, 2, 4, ... and the last one read the
#     map (the "direct" samples). An odd sample between two direct ones reads it only where the two
#     direct neighbours' answers differ (lit shares are multiples of 0.25, so equal means equal); where
#     they are equal the odd sample takes that answer. A shadow's edge, where it matters, is therefore
#     resolved as before; the cost is a blocker thinner than one sample step, passing between two
#     samples that are both lit (or both dark), which the old march also only caught where a sample fell
#     inside it. Modelled (scratch r106c_mirror2.py, 4000 random rays with 0-4 occluders and a soft
#     texel-wide edge): the error against a 48-sample march is 8.5e-5 (fast, 6 samples) against 8.4e-5
#     (old, 6): the old march's own sampling error; at 12 samples 3.4e-5 against 3.0e-5; map reads 54% of
#     the old at 6 samples, 43% at 12 (a model with many occluders; open scenes read fewer).
#  2. A sample whose light is under SHAFT_FAST_SKIP = 1/16384 of the fog's output (its energy times the
#     lamp's colour peak, weight and 0.35 x intensity) reads no map: it takes the answer of the sample
#     before (1 if none), so it is wrong by under 1/16384 (0.2 of an 8-bit level near black) at most. Its
#     neighbours then read, never interpolate across it.
#  3. Lit() without the direction's normalisation (the octahedral map divides by its own |x|+|y|+|z|):
#     one length and one divide fewer for the same four texels and the same test.
# Not changed: the maps, the table, the cap, the wind, the strength fade, the unshadowed sum, the debug
# view (it takes the same lit value). The old march stays in the shader, chosen by the push constant.
#
# Knob: BB_LAMP_FOG_SHAFTS_FAST, default ON whenever BB_LAMP_FOG_SHAFTS is on (it is an optimization);
# "0" is the old march of r106 for comparison (anything else is on). A live knob where the test tools
# (BB_LIVE_KNOBS_FILE, r84) are in the tree: one running game can set it to 0 and unset it, same camera.
#
# Off (BB_LAMP_FOG_SHAFTS unset, the default of the feature chain): nothing here runs; the only host
# code is inside VolumetricLight::RecordShafts, which runs only with the shafts on, and every new shader
# line is inside #ifdef SHAFTS, so the builds without SHAFTS (the plain lamp fog and the WIND build) come
# out byte-identical (proved on a private copy, see the final report). The push block of the SHAFTS builds
# grows from 20 to 24 bytes (host PointParams, CreatePass, tests/test_effect_pipelines.cpp).
#
# Files: point_volumetric.comp, lamp_fog_shaft_layout.h (SHAFT_FAST_SKIP), vk_volumetric_light.cpp (the
# push struct, the pass's push size, Frame() in RecordShafts, PrintLine() beside the 600-frame lines),
# vk_volumetric_light.h (one include), new lamp_fog_shaft_fast.h (knob, once-lines, counters),
# test_effect_pipelines.cpp (push size 20 -> 24, four entries), new tests/test_lamp_fog_shaft_fast.cpp (+ a
# build.sh line and a gpu/CMakeLists.txt target), README.md (a row after BB_LAMP_FOG_SHAFTS_RAYS).
#
# Use: python -I -X utf8 r106c_shaft-march-cheaper.py check | apply | revert
# Root: R106C_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r106c_backup next to this script; each edit refuses unless its anchor / old text is found exactly once;
# new files are removed by revert.
import os, sys

ROOT = os.environ.get("R106C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r106c_backup")
H = "engine/gpu/shadps4/video_core/host_shaders/"
R = "engine/gpu/shadps4/video_core/renderer_vulkan/"
P = H + "point_volumetric.comp"
L = H + "lamp_fog_shaft_layout.h"
C = R + "vk_volumetric_light.cpp"
V = R + "vk_volumetric_light.h"
E = "engine/tests/test_effect_pipelines.cpp"
B = "engine/build.sh"
K = "engine/gpu/CMakeLists.txt"
D = "README.md"
FAST_H = R + "lamp_fog_shaft_fast.h"
FAST_T = "engine/tests/test_lamp_fog_shaft_fast.cpp"

# ("ins", anchor, before, after): the anchor stays; before goes in front of it, after behind it.
# ("rep", old, new): old is replaced by new (neither holds the other).
EDITS = {
L: [
("ins", "#define SHAFT_FREE 65504.0\n", "",
 "// bbport (r106c_shaft-march-cheaper): the fast march (BB_LAMP_FOG_SHAFTS_FAST): a sample whose light\n"
 "// is under this much of the fog's output (linear, as the march writes it) reads no map and takes the\n"
 "// answer of the sample before it (1 if none): 1/16384, 0.2 of an 8-bit level near black.\n"
 "#define SHAFT_FAST_SKIP 6.1035156e-5\n"),
],
P: [
("rep",
 "    uint shaft_segments;\n#endif\n};",
 "    uint shaft_segments;\n"
 "    // bbport (r106c_shaft-march-cheaper): 1: the fast march (inscatterShadowedFast), 0: the march of\n"
 "    // r106 (BB_LAMP_FOG_SHAFTS_FAST, lamp_fog_shaft_fast.h)\n"
 "    uint shaft_fast;\n"
 "#endif\n};"),
("ins", "// inscatter() with shaft_segments segments (1 to 32; lamp_fog_shafts.h Segments) and each\n",
 r"""// bbport (r106c_shaft-march-cheaper): Lit() for the fast march: the same four texels and the same
// test. The direction is not scaled to length 1 first (the octahedral map divides by its own
// |x| + |y| + |z|): one length and one divide fewer.
float LitFast(vec3 p, vec3 centre, float radius, uint layer) {
    vec3 v = p - centre;
    float d = length(v);
    if (!(d > 0.0)) return 1.0;
    vec3 w = vec3(dot(shaft_to_world0, v), dot(shaft_to_world1, v), dot(shaft_to_world2, v));
    float sum = abs(w.x) + abs(w.y) + abs(w.z);
    if (!(sum > 0.0)) return 1.0;
    vec3 n = w / sum;
    vec2 e = n.xy;
    if (n.z < 0.0) {
        e = (1.0 - abs(n.yx)) * vec2(n.x >= 0.0 ? 1.0 : -1.0, n.y >= 0.0 ? 1.0 : -1.0);
    }
    vec4 free_distance = textureGather(shaft_maps, vec3(e * 0.5 + 0.5, float(layer)), 0);
    return dot(step(vec4(d - shaft_bias * radius), free_distance), vec4(0.25));
}

""", ""),
("ins", "#endif\n\nvoid main() {\n",
 r"""
// bbport (r106c_shaft-march-cheaper): inscatterShadowed() for BB_LAMP_FOG_SHAFTS_FAST on: the same
// segments, weights and sample points, the map read at fewer of them. A half chord's samples 0, 2, 4,
// ... and the last read the map ("direct"). An odd sample between two direct ones waits (pend_*) for
// the next direct sample: its map is read only if the two direct neighbours' answers differ (the
// answers are multiples of 0.25, so equal means equal), else it takes that answer. A direct sample
// whose segment is under skip_below (lamp_fog_shaft_layout.h SHAFT_FAST_SKIP over the fog's output
// scale; main) reads nothing and takes the answer of the direct sample before (1 if none), and
// leaves lit_prev at -1 so the odd sample before it reads for itself.
float inscatterShadowedFast(vec3 ray, vec3 centre, float radius, float along, float q, float begin,
                            float end, uint layer, inout float unshadowed, float skip_below) {
    if (end <= begin) return 0.0;
    uint segments = clamp(shaft_segments, 1u, 32u);
    float ds = (end - begin) / float(segments);
    float energy = 0.0;
    float previous = atan((begin - along) / q);
#ifdef WIND
    // bbport (r88_wind-lamp-fog): as inscatterShadowed
    float wind_m = lamp_wind(ray, along, q, begin, end);
#endif
    float lit_prev = -1.0;
    float pend_segment = 0.0, pend_middle = 0.0;
    for (uint i = 0u; i < segments; ++i) {
        float t0 = begin + float(i) * ds;
        float angle = atan((t0 + ds - along) / q);
        float t = t0 + 0.5 * ds;
        float x = length(ray * t - centre) / radius;
        float window = clamp(1.0 - x * x * x * x, 0.0, 1.0);
        float segment = (angle - previous) * window * window * exp(-0.025 * t) * 0.025;
#ifdef WIND
        segment *= wind_m;
#endif
        if (segment > 0.0) unshadowed += segment;
        float carried = lit_prev >= 0.0 ? lit_prev : 1.0;
        if ((i & 1u) == 0u || i + 1u == segments) {
            float lit = -1.0;
            if (segment > skip_below) {
                lit = LitFast(ray * (along + q * tan(0.5 * (previous + angle))), centre, radius,
                              layer);
            }
            if (pend_segment > 0.0) {
                float lit_pend = (lit >= 0.0 && lit == lit_prev)
                                     ? lit
                                     : LitFast(ray * pend_middle, centre, radius, layer);
                energy += pend_segment * lit_pend;
                pend_segment = 0.0;
            }
            if (segment > 0.0) energy += segment * (lit >= 0.0 ? lit : carried);
            lit_prev = lit;
        } else if (segment > skip_below) {
            pend_segment = segment;
            pend_middle = along + q * tan(0.5 * (previous + angle));
        } else if (segment > 0.0) {
            energy += segment * carried;
        }
        previous = angle;
    }
    return energy;
}
""", ""),
("rep",
 "        float lit = inscatterShadowed(ray, centre, radius, along, q, begin, nearest, layer,\n"
 "                                      shadowed, unshadowed) +\n"
 "                    inscatterShadowed(ray, centre, radius, along, q, nearest, end, layer,\n"
 "                                      shadowed, unshadowed);\n"
 "        lit = mix(unshadowed, lit, strength);\n"
 "        float weight = ENERGY * core * core / q;\n",
 "        float weight = ENERGY * core * core / q;\n"
 "        float lit;\n"
 "        if (shadowed && shaft_fast != 0u) {\n"
 "            // bbport (r106c_shaft-march-cheaper): the fast march; skip_below is a segment's energy\n"
 "            // under which its light is under SHAFT_FAST_SKIP of the fog's output (the lamp's colour\n"
 "            // peak x weight x 0.35 x intensity, as written below)\n"
 "            float skip_below = SHAFT_FAST_SKIP /\n"
 "                               max(max(rgb.r, max(rgb.g, rgb.b)) * weight * (0.35 * intensity), 1e-12);\n"
 "            lit = inscatterShadowedFast(ray, centre, radius, along, q, begin, nearest, layer,\n"
 "                                        unshadowed, skip_below) +\n"
 "                  inscatterShadowedFast(ray, centre, radius, along, q, nearest, end, layer,\n"
 "                                        unshadowed, skip_below);\n"
 "        } else {\n"
 "            lit = inscatterShadowed(ray, centre, radius, along, q, begin, nearest, layer,\n"
 "                                    shadowed, unshadowed) +\n"
 "                  inscatterShadowed(ray, centre, radius, along, q, nearest, end, layer,\n"
 "                                    shadowed, unshadowed);\n"
 "        }\n"
 "        lit = mix(unshadowed, lit, strength);\n"),
],
V: [
("ins", '#include "video_core/renderer_vulkan/lamp_fog_shaft_cap.h" // bbport (r106_lamp-fog-shaft-cap)\n', "",
 '#include "video_core/renderer_vulkan/lamp_fog_shaft_fast.h" // bbport (r106c_shaft-march-cheaper)\n'),
],
C: [
("rep",
 "                   march, 5 * sizeof(u32), \"Point volumetric (shafts)\");",
 "                   march, 6 * sizeof(u32), \"Point volumetric (shafts)\"); // bbport (r106c): + shaft_fast"),
("rep",
 "                        march, 5 * sizeof(u32), \"Point volumetric (shafts, wind)\");",
 "                        march, 6 * sizeof(u32), // bbport (r106c): + shaft_fast\n"
 "                        \"Point volumetric (shafts, wind)\");"),
("rep",
 "        u32 shaft_segments;\n    };\n    static_assert(sizeof(PointParams) == 20);\n",
 "        u32 shaft_segments;\n"
 "        u32 shaft_fast; // bbport (r106c_shaft-march-cheaper): 1 the fast march, 0 r106's\n"
 "    };\n"
 "    static_assert(sizeof(PointParams) == 24);\n"),
("rep",
 "    const PointParams params{count, intensity, glow_size, LampFogShafts::Bias,\n"
 "                             LampFogShafts::Segments(LampFogShafts::Level())};\n",
 "    // bbport (r106c_shaft-march-cheaper): BB_LAMP_FOG_SHAFTS_FAST, asked again each frame (a live\n"
 "    // knob with the test tools); Frame() says it when it changes and counts the frame\n"
 "    const u32 shaft_segments = LampFogShafts::Segments(LampFogShafts::Level());\n"
 "    const PointParams params{count, intensity, glow_size, LampFogShafts::Bias, shaft_segments,\n"
 "                             LampFogShaftFast::Frame(count, shaft_segments, w, h)};\n"),
("ins", "            shaft_totals = {};\n", "",
 "            LampFogShaftFast::PrintLine(); // bbport (r106c_shaft-march-cheaper): a line of its own\n"),
],
E: [
("ins", '        {"point volumetric (shafts)",\n',
 "        // bbport (r106c_shaft-march-cheaper): the four shafts builds push 24 bytes now (shaft_fast\n"
 "        // after the segment count)\n", ""),
("rep",
 "         POINT_VOLUMETRIC_SHAFTS_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         20},\n",
 "         POINT_VOLUMETRIC_SHAFTS_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         24},\n"),
("rep",
 "         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         20},\n",
 "         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         24},\n"),
("rep",
 "         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         20},\n",
 "         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         24},\n"),
("rep",
 "         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         20},\n",
 "         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,\n"
 "         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,\n"
 "          eCombinedImageSampler, eStorageBuffer},\n"
 "         24},\n"),
],
B: [
("ins", "    out/lamp-fog-shaft-cap-test\n", "",
 "    # bbport (r106c_shaft-march-cheaper): the fast march's knob, counters and a mirror of its sampling\n"
 '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_lamp_fog_shaft_fast.cpp -o out/lamp-fog-shaft-fast-test\n'
 "    out/lamp-fog-shaft-fast-test\n"),
],
K: [
("ins", "target_include_directories(lamp-fog-shaft-cap-test PRIVATE ..)\n", "",
 "# bbport (r106c_shaft-march-cheaper): the fast march's knob, counters and a mirror of its sampling\n"
 "# (lamp_fog_shaft_fast.h); also built and run by engine/build.sh --test.\n"
 "add_executable(lamp-fog-shaft-fast-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_fast.cpp)\n"
 "target_compile_options(lamp-fog-shaft-fast-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(lamp-fog-shaft-fast-test PRIVATE ..)\n"),
],
D: [
("ins",
 "A log line every 600 lamp fog frames, `Volumetric lighting (r106): shaft cap`, gives the rays a frame and the lights with a fresh map, reusing a map and over budget | 8 maps |\n",
 "",
 "| `BB_LAMP_FOG_SHAFTS_FAST` | With `BB_LAMP_FOG_SHAFTS` on: the cheaper march of the lamp fog's shafts. Each pixel, each light whose sphere the view ray crosses is marched in 2 halves of 6 samples (12 at `BB_LAMP_FOG_SHAFTS=2`), each sample reading the light's 4-texel shadow map neighbourhood. On (the default): the map is read at every second sample of a half and at the last one; a sample between two of them reads it only where those two answers differ, else it takes their (equal) answer; a sample whose light is under 1/16384 of the fog's output reads none and takes the answer of the sample before it. The same texels and the same test, so the picture matches the old march within the sampling error the old march has itself (a blocker thinner than one sample step that falls between two samples with equal answers is missed, as the old march misses it when no sample falls inside it). `0`: the march of before (every sample reads the map); any other text is on. Read again every frame while the test tools' live knobs are in the build. The log says once, and at each change, which march runs (`Volumetric lighting (r106c): shaft march`), and every 600 lamp fog frames the frames with each, the most lights and an upper bound on the map reads a frame (not counted on the GPU). Cost: the saving is not measured; read it on the `Lighting: lamp fog` row of `BB_GPU_PROFILE=1` with the knob `1` against `0` (before this patch the row went 0.212 to 0.430 ms at dark-alley with the shafts on, 4K DLSS) | on |\n"),
],
}

NEW_FILES = {
FAST_H: r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r106c_shaft-march-cheaper): the lamp fog shafts' cheaper march (point_volumetric.comp's
// inscatterShadowedFast; BB_LAMP_FOG_SHAFTS on only). Each pixel, each light whose sphere the view ray
// crosses, 2 halves x Segments samples (lamp_fog_shafts.h), each a 4-texel textureGather of the
// light's map. The fast march reads the map at every second sample of a half (and the last), at an odd
// sample between two only where the two answers differ, and not at all where the sample's light is
// under SHAFT_FAST_SKIP (lamp_fog_shaft_layout.h) of the fog's output. No Vulkan here: this header
// holds the knob, its log lines and counters (tests/test_lamp_fog_shaft_fast.cpp builds it alone).
//
// BB_LAMP_FOG_SHAFTS_FAST: "0" is the march of r106 (every sample reads the map); unset, empty or any
// other text is on (the default: it is an optimization). With the test tools' live knobs
// (BB_LIVE_KNOBS_FILE; gpu/shim/bbport_live_knobs.h, test tools only) it is read again at every call,
// so one running game can compare the two marches at one camera; without them it is read once.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "../host_shaders/lamp_fog_shaft_layout.h"
// A test that does not link the runtime defines BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE before this include.
#if !defined(BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE) && __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_FOG_SHAFTS_FAST_LIVE 1
#else
#define BB_LAMP_FOG_SHAFTS_FAST_LIVE 0
#endif

namespace Vulkan::LampFogShaftFast {

/// The knob's text: exactly "0" is off, anything else (also not set) is on.
inline bool ParseFast(const char* text) {
    return !(text && text[0] == '0' && text[1] == '\0');
}

/// BB_LAMP_FOG_SHAFTS_FAST now.
inline bool Fast() {
#if BB_LAMP_FOG_SHAFTS_FAST_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_LAMP_FOG_SHAFTS_FAST", ParseFast};
    return knob.Get();
#else
    static const bool value = ParseFast(std::getenv("BB_LAMP_FOG_SHAFTS_FAST"));
    return value;
#endif
}

/// The period of PrintLine's line, in lamp fog frames (RecordLampFog's own 600).
inline constexpr std::uint32_t LinePeriod = 600;

/// An upper bound on the map reads of one frame: every light over every pixel, 2 halves of
/// `segments` samples (the lights whose sphere the view ray misses read none; the fast march reads
/// fewer).
inline std::uint64_t TapsBound(std::uint32_t lights, std::uint32_t segments, std::uint32_t w,
                               std::uint32_t h) {
    return std::uint64_t(lights) * 2u * segments * w * h;
}

/// The counts since the last PrintLine.
struct Totals {
    std::uint64_t frames = 0;  ///< frames that ran the shafts' march
    std::uint64_t fast = 0;    ///< of them with the fast march
    std::uint64_t bound = 0;   ///< sum of TapsBound over them
    std::uint32_t lights_most = 0, segments = 0, width = 0, height = 0;
};
inline Totals totals;
inline int told = -1; ///< the value the last once-line said (1 fast, 0 old); -1: none yet

/// One frame of the shafts' march (VolumetricLight::RecordShafts): the pushed flag (1 fast, 0 old),
/// the once-line when the value is new, the counts.
inline std::uint32_t Frame(std::uint32_t lights, std::uint32_t segments, std::uint32_t w,
                           std::uint32_t h) {
    const bool fast = Fast();
    if (told != (fast ? 1 : 0)) {
        told = fast ? 1 : 0;
        if (fast) {
            std::printf("Volumetric lighting (r106c): shaft march fast (BB_LAMP_FOG_SHAFTS_FAST): the "
                        "maps are read at every second sample, at the others only where the two "
                        "beside differ; light under 1/16384 reads none; 2 halves x %u samples a "
                        "light and pixel, %ux%u pixels, %u lights now\n",
                        segments, w, h, lights);
        } else {
            std::printf("Volumetric lighting (r106c): shaft march old (BB_LAMP_FOG_SHAFTS_FAST=0): "
                        "every sample reads the maps, as r106; 2 halves x %u samples a light and "
                        "pixel, %ux%u pixels, %u lights now\n",
                        segments, w, h, lights);
        }
    }
    ++totals.frames;
    totals.fast += fast ? 1 : 0;
    totals.bound += TapsBound(lights, segments, w, h);
    totals.lights_most = std::max(totals.lights_most, lights);
    totals.segments = segments;
    totals.width = w;
    totals.height = h;
    return fast ? 1u : 0u;
}

/// The counts' line (every LinePeriod lamp fog frames, beside the r106 lines), then the counts reset.
inline void PrintLine() {
    const double frames = double(std::max<std::uint64_t>(totals.frames, 1));
    std::printf("Volumetric lighting (r106c): shaft march over %llu frames: fast in %llu; map reads a "
                "frame at most %.0f on average (lights x 2 halves x %u samples x %ux%u pixels, up to "
                "%u lights; lights off the ray and skipped samples read less, not counted)\n",
                static_cast<unsigned long long>(totals.frames),
                static_cast<unsigned long long>(totals.fast), double(totals.bound) / frames,
                totals.segments, totals.width, totals.height, totals.lights_most);
    totals = {};
}

} // namespace Vulkan::LampFogShaftFast
""",
FAST_T: r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106c_shaft-march-cheaper): the fast march's knob and counters (lamp_fog_shaft_fast.h) and a
// mirror of point_volumetric.comp's inscatterShadowedFast sampling (the C++ twin of the Python mirror
// scratch r106c_mirror.py): where a half chord's samples read the map, and what that does to the
// energy against the old march that reads every sample.
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <vector>
// the pure test links no runtime: the knob is read from the environment
#define BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE 1
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_fast.h"

using namespace Vulkan::LampFogShaftFast;

namespace {

struct Seg {
    float energy; ///< the segment's light before the map
    float at;     ///< where its map sample lies (any number: the scene function takes it)
};

/// inscatterShadowed's loop over one half chord: every segment with light reads the map.
float OldHalf(const std::vector<Seg>& segs, const std::function<float(float)>& lit, int& reads) {
    float energy = 0.0f;
    for (const Seg& s : segs) {
        if (s.energy > 0.0f) {
            energy += s.energy * lit(s.at);
            ++reads;
        }
    }
    return energy;
}

/// inscatterShadowedFast's loop, statement for statement.
float FastHalf(const std::vector<Seg>& segs, const std::function<float(float)>& lit_at,
               float skip_below, int& reads) {
    const std::size_t n = segs.size();
    float energy = 0.0f, lit_prev = -1.0f, pend_segment = 0.0f, pend_middle = 0.0f;
    for (std::size_t i = 0; i < n; ++i) {
        const float segment = segs[i].energy;
        const float carried = lit_prev >= 0.0f ? lit_prev : 1.0f;
        if ((i & 1u) == 0u || i + 1u == n) {
            float lit = -1.0f;
            if (segment > skip_below) {
                lit = lit_at(segs[i].at);
                ++reads;
            }
            if (pend_segment > 0.0f) {
                float lit_pend;
                if (lit >= 0.0f && lit == lit_prev) {
                    lit_pend = lit;
                } else {
                    lit_pend = lit_at(pend_middle);
                    ++reads;
                }
                energy += pend_segment * lit_pend;
                pend_segment = 0.0f;
            }
            if (segment > 0.0f) {
                energy += segment * (lit >= 0.0f ? lit : carried);
            }
            lit_prev = lit;
        } else if (segment > skip_below) {
            pend_segment = segment;
            pend_middle = segs[i].at;
        } else if (segment > 0.0f) {
            energy += segment * carried;
        }
    }
    return energy;
}

std::vector<Seg> Uniform(std::size_t n) {
    std::vector<Seg> segs;
    for (std::size_t i = 0; i < n; ++i) {
        segs.push_back({1.0f, float(i)});
    }
    return segs;
}

} // namespace

int main() {
    // the knob: exactly "0" is the old march
    assert(ParseFast(nullptr) && ParseFast("") && ParseFast("1") && ParseFast("2") &&
           ParseFast("00") && ParseFast("off"));
    assert(!ParseFast("0"));
    // the skip level is 1/16384 (the README and the shader comment say so)
    assert(std::fabs(SHAFT_FAST_SKIP - 1.0 / 16384.0) < 1e-9);
    // the bound: 3 lights x 2 halves x 6 samples x 1920 x 1080
    assert(TapsBound(3, 6, 1920, 1080) == 3ull * 2 * 6 * 1920 * 1080);
    assert(TapsBound(64, 12, 3840, 2160) == 64ull * 2 * 12 * 3840 * 2160); // no 32-bit overflow
    // counters: Frame() counts, says the first value, returns the flag; PrintLine resets
    {
        const std::uint32_t flag = Frame(5, 6, 640, 360);
        assert(flag == (Fast() ? 1u : 0u));
        assert(totals.frames == 1 && totals.bound == TapsBound(5, 6, 640, 360));
        assert(totals.lights_most == 5);
        Frame(9, 6, 640, 360);
        assert(totals.frames == 2 && totals.lights_most == 9);
        PrintLine();
        assert(totals.frames == 0 && totals.bound == 0);
    }
    // 1. all lit: the same energy; 4 reads of 6 at 6 samples, 7 of 12 at 12
    for (const std::size_t n : {std::size_t(6), std::size_t(12)}) {
        const auto segs = Uniform(n);
        int ro = 0, rf = 0;
        const auto lit = [](float) { return 1.0f; };
        assert(OldHalf(segs, lit, ro) == float(n) && FastHalf(segs, lit, 0.0f, rf) == float(n));
        assert(ro == int(n) && rf == (n == 6 ? 4 : 7));
    }
    // 2. a shadow's edge between samples: the odd sample at the edge reads and the energy is exact
    {
        const auto segs = Uniform(6);
        int ro = 0, rf = 0;
        const auto lit = [](float at) { return at < 3.5f ? 1.0f : 0.0f; };
        assert(OldHalf(segs, lit, ro) == FastHalf(segs, lit, 0.0f, rf));
        assert(rf == 5); // 0, 2, 4, 5 and the odd sample 3 (its neighbours 1 and 0 differ)
    }
    // 3. a thin blocker on an odd sample between two lit ones is missed (the documented limit)
    {
        const auto segs = Uniform(6);
        int ro = 0, rf = 0;
        const auto lit = [](float at) { return at == 1.0f ? 0.0f : 1.0f; };
        assert(OldHalf(segs, lit, ro) == 5.0f && FastHalf(segs, lit, 0.0f, rf) == 6.0f);
    }
    // 4. a sample under skip_below reads nothing and takes the answer before it
    {
        std::vector<Seg> segs = Uniform(6);
        for (Seg& s : segs) {
            s.energy = 1e-3f;
        }
        int rf = 0;
        const auto lit = [](float) { return 0.5f; };
        const float e = FastHalf(segs, lit, 1e-2f, rf); // everything under the level: no reads
        assert(rf == 0 && std::fabs(e - 6e-3f) < 1e-7f); // no answer known: 1 (unshadowed)
    }
    // 5. a randomised comparison: many soft shadows; the fast march's energy stays within a sample's
    // worth of the old march's, and its reads stay under the old march's
    {
        std::uint32_t seed = 12345;
        const auto next = [&seed]() {
            seed = seed * 1664525u + 1013904223u;
            return float((seed >> 8) & 0xFFFF) / 65535.0f;
        };
        long reads_old = 0, reads_fast = 0;
        double worst = 0.0;
        for (int trial = 0; trial < 2000; ++trial) {
            const float edge1 = next() * 6.0f, edge2 = edge1 + next() * 3.0f;
            const auto lit = [=](float at) {
                return at < edge1 ? 1.0f : (at < edge2 ? 0.25f * std::floor((edge2 - at) / (edge2 - edge1) * 4.0f) : 0.0f);
            };
            auto segs = Uniform(12);
            for (Seg& s : segs) {
                s.energy = 0.5f + next();
            }
            int ro = 0, rf = 0;
            const float old_energy = OldHalf(segs, lit, ro);
            const float fast_energy = FastHalf(segs, lit, 0.0f, rf);
            reads_old += ro;
            reads_fast += rf;
            worst = std::fmax(worst, std::fabs(fast_energy - old_energy) / old_energy);
        }
        assert(reads_fast < reads_old);
        assert(worst < 0.5); // one odd sample of 12 of unit energy wrong at most (1/12 of 1.5 each)
    }
    std::printf("lamp fog shaft fast: ok\n");
    return 0;
}
""",
}

CHECKS = {
P: [("uint shaft_fast;", 1), ("float inscatterShadowedFast(", 1), ("inscatterShadowedFast(ray,", 2),
    ("SHAFT_FAST_SKIP", 3), ("float LitFast(", 1), ("shaft_fast != 0u", 1)],
L: [("#define SHAFT_FAST_SKIP 6.1035156e-5\n", 1)],
C: [("u32 shaft_fast;", 1), ("static_assert(sizeof(PointParams) == 24);", 1),
    ("march, 6 * sizeof(u32),", 2), ("LampFogShaftFast::Frame(count, shaft_segments, w, h)", 1),
    ("LampFogShaftFast::PrintLine();", 1), ("march, 5 * sizeof(u32)", 0)],
V: [('lamp_fog_shaft_fast.h"', 1)],
E: [("         20},\n", 0), ("         24},\n", 4)],
B: [("test_lamp_fog_shaft_fast.cpp", 1)],
K: [("lamp-fog-shaft-fast-test", 3)],
D: [("`BB_LAMP_FOG_SHAFTS_FAST`", 1)],
}


def shafts_only(text):
    """Every r106c line of point_volumetric.comp lies inside an #ifdef SHAFTS (the default and WIND
    builds keep their bytes)."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifdef SHAFTS")
        elif st.startswith("#else"):
            stack[-1] = False
        elif st.startswith("#endif"):
            stack.pop()
        elif ("r106c" in line or "shaft_fast" in line or "LitFast" in line or "SHAFT_FAST" in line or
              "inscatterShadowedFast" in line) and not any(stack):
            raise SystemExit("text check: r106c shader line outside #ifdef SHAFTS: %r" % line)


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    shafts_only(texts[P])
    # the knob's name, the skip level in the README, the 300-character log lines of the slot runs
    if texts[FAST_H].count('"BB_LAMP_FOG_SHAFTS_FAST"') != 2:
        raise SystemExit("text check: the knob's name")
    if "1/16384" not in texts[D] or "1/16384" not in texts[FAST_H] or "1/16384" not in texts[L]:
        raise SystemExit("text check: the skip level is not named in README, header and layout")
    # the half chord loop's order: the old march stays after the fast one's call in main
    s = texts[P]
    if not (s.find("float LitFast(") < s.find("float inscatterShadowed(") < s.find(
            "float inscatterShadowedFast(") < s.find("void main()")):
        raise SystemExit("text check: shader functions out of order")


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def parts(edit):
    return [t for t in (edit[2], edit[3]) if t] if edit[0] == "ins" else [edit[2]]


def state_of(cur, eds, path):
    """'applied' or 'clean' for the whole file, else refuse. ins: anchor once and each inserted text
    once (applied) or none (clean). rep: new once and old none (applied), old once and new none
    (clean)."""
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            na, counts = cur.count(e[1]), [cur.count(t) for t in parts(e)]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s "
                                 "times: %r" % (path, na, counts, e[1][:70]))
        else:
            no, nn = cur.count(e[1]), cur.count(e[2])
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %d times: %r"
                                 % (path, no, nn, e[1][:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def new_state(path, text):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    if load(path)[2] == text:
        return "applied"
    raise SystemExit("%s exists and is not this patch's text" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R106C_ROOT)" % ROOT)
    for path, eds in EDITS.items():
        for e in eds:
            if e[0] == "rep" and (e[1] in e[2] or e[2] in e[1]):
                raise SystemExit("script fault: %s: a replacement holds its old text" % path)
    plan = []
    for path, eds in EDITS.items():
        raw, eol, cur = load(path)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    news = [(path, text, new_state(path, text)) for path, text in NEW_FILES.items()]
    states = {p[5] for p in plan} | {n[2] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                     ["%s %s" % (n[0], n[2]) for n in news]))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for e in eds:
                if e[0] == "ins":
                    cur = cur.replace(e[1], e[2] + e[1] + e[3])
                else:
                    cur = cur.replace(e[1], e[2])
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        out.update({n[0]: n[1] for n in news})
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            texts.update({n[0]: n[1] for n in news})
            text_checks(texts)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on "
                  "the result pass)" % (len(plan), sum(len(p[1]) for p in plan), len(news)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        outs = [(path, texts[path].replace("\n", eol).encode("utf-8")) for path, *_ in plan]
        outs += [(path, text.replace("\n", "\r\n").encode("utf-8")) for path, text, _ in news]
        for path, data in outs:
            full = os.path.join(ROOT, path)
            tmp = full + ".r106ctmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    # all files are worked out before any is written
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for e in reversed(eds):
            if e[0] == "ins":
                for part in (e[3], e[2]):
                    if part:
                        cur = cur.replace(part, "", 1)
            else:
                cur = cur.replace(e[2], e[1], 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r106ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path, text, _ in news:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
