# r80b_shafts-smooth-visible: FEATURE patch (feature "lamp and torch shafts through fog", order item 3;
# branch visual/lamp-fog-shafts, on top of r80, r106 and r106c). The lamp fog shafts smoother and somewhat
# stronger. Off by default: it acts only with BB_LAMP_FOG_SHAFTS set (r80's knob, same meaning).
#
# The owner (2026-11-16, hand test of build 72, 4K DLSS): "Light shafts seem to be working, but just a bit
# hard see and maybe a little blocky like our shadows used to be."
# Cause (point_volumetric.comp, SHAFTS builds): each lamp's shadow map is 128x128 octahedral (a texel is
# 1.4 to 2.8 degrees of the sphere around the lamp), and the march read the four texels around a sample
# with a step each and took their mean: a quarter-step staircase one texel wide; and the 6 samples a half
# chord, each at the middle of its segment, give the lit and dark slices a rhythm (bands across the beam).
# Brightness: the lamp fog is the glow of r80's units (0.35 x intensity); the beams between lit and
# blocked air are low in contrast.
#
# What (all inside #ifdef SHAFTS of point_volumetric.comp; the default and WIND builds do not change):
# 1. BB_LAMP_FOG_SHAFTS_SMOOTH (0, 1, 2; default 2). ShaftTaps() replaces the two lines "textureGather +
#    step + mean" of Lit() and LitFast(): level 0 is those lines; level 1 weights the same four gathered
#    hit tests bilinearly by fract(uv * mapSize - 0.5) (the gather's own texel grid): a soft straight edge,
#    exactly a bilinear filter of the hit tests (percentage-closer filtering), the same texture read;
#    level 2 adds a per-pixel, per-light, per-sample jitter: the lookup moves up to half a texel each way
#    and the sample moves along its segment (0.15 to 0.85 of the segment's angle in place of 0.5), by three
#    interleaved gradient noise values of the pixel (a new pattern every frame, frame counter in the pushed
#    word) walked along the 3D R sequence per light and sample. DLSS and the temporal pass integrate it over
#    frames (the lamp shadows' own move); the bilinear weights keep the single-frame noise small. The
#    jitter is not a depth-aware blur: no extra reads at all.
# 2. BB_LAMP_FOG_SHAFTS_GAIN (0.25 to 4; default 1.35): every shafts-march light's contribution is
#    multiplied by it (shadowed or not, so a lamp does not jump when it falls out of r106's ray budget). The
#    debug view (BB_LAMP_FOG_SHAFTS=3) is not multiplied.
# 3. The two values travel in the existing push word shaft_fast (r106c; bit 0 is still the fast march):
#    smoothing bits 1-2, gain bits 8-15 (1/32 units; 0 reads as 1), a frame counter bits 16-31. The push
#    block stays 24 bytes: no pass, descriptor, test_effect_pipelines.cpp or CMake shader line changes.
#    SHAFT_PUSH_* in lamp_fog_shaft_layout.h are shared by the shader and lamp_fog_shaft_smooth.h.
# 4. No rays, no map reads more: the lamp fog's ray count is r106's (log: 'this frame 64 lights, 1048576
#    map rays' of r80 is the uncapped number; r106's cap line is unchanged) and the textureGathers per sample
#    are the same; per sample a few ALU operations more (noise, one textureSize, the weights). A frame
#    counter and a few stores more on the host.
# 5. Log: a once-line "Volumetric lighting (r80b): shaft smoothing S ..., shaft gain G ..." at the first
#    shafts frame and at each change; with r106c's 600-frame line one of its own "shaft smoothing over N
#    frames: level 0 in A, 1 in B, 2 in C; gain now G; extra map rays 0, extra map reads 0".
#
# Off (BB_LAMP_FOG_SHAFTS unset): the host code is VolumetricLight::RecordShafts's (reached only with the
# knob and a ray traced scene) and the PrintLine in the shafts' 600-frame block; every shader line is inside
# #ifdef SHAFTS (checked by this script's text check), so the default and WIND builds come out
# byte-identical (proved on a private copy; the report says how). With SMOOTH=0 and GAIN=1 the shader
# computes what r106c computed (ShaftAngle returns the old 0.5 * (previous + angle) and ShaftTaps the old
# four-texel mean).
#
# Files: point_volumetric.comp, lamp_fog_shaft_layout.h (SHAFT_PUSH_*), vk_volumetric_light.cpp (one
# wrapper around r106c's Frame() call, one PrintLine call), vk_volumetric_light.h (one include), new
# lamp_fog_shaft_smooth.h (knobs, pushed word, once-line, counters), new tests/test_lamp_fog_shaft_smooth.cpp
# (+ a build.sh line and a gpu/CMakeLists.txt target), README.md (two rows before BB_LAMP_FOG_SHAFTS_FAST).
#
# Use: python -I -X utf8 r80b_shafts-smooth-visible.py check | apply | revert
# Root: R80B_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r80b_backup next to this script; each edit refuses unless its anchor / old text is found exactly once;
# new files are removed by revert.
import os, sys

ROOT = os.environ.get("R80B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r80b_backup")
H = "engine/gpu/shadps4/video_core/host_shaders/"
R = "engine/gpu/shadps4/video_core/renderer_vulkan/"
P = H + "point_volumetric.comp"
L = H + "lamp_fog_shaft_layout.h"
C = R + "vk_volumetric_light.cpp"
V = R + "vk_volumetric_light.h"
B = "engine/build.sh"
K = "engine/gpu/CMakeLists.txt"
D = "README.md"
SMOOTH_H = R + "lamp_fog_shaft_smooth.h"
SMOOTH_T = "engine/tests/test_lamp_fog_shaft_smooth.cpp"

# ("ins", anchor, before, after): the anchor stays; before goes in front of it, after behind it.
# ("rep", old, new): old is replaced by new (neither holds the other).
EDITS = {
L: [
("ins", "#define SHAFT_FAST_SKIP 6.1035156e-5\n", "",
 "// bbport (r80b_shafts-smooth-visible): the bits of the SHAFTS march's push word `shaft_fast`\n"
 "// (lamp_fog_shaft_smooth.h): bit 0 the fast march (r106c), the smoothing level (0 to 2) from bit\n"
 "// SHAFT_PUSH_SMOOTH_SHIFT (2 bits), the gain in 1/SHAFT_PUSH_GAIN_UNIT from bit SHAFT_PUSH_GAIN_SHIFT\n"
 "// (8 bits; 0 reads as 1), a frame counter from bit SHAFT_PUSH_FRAME_SHIFT (the noise's animation).\n"
 "#define SHAFT_PUSH_SMOOTH_SHIFT 1u\n"
 "#define SHAFT_PUSH_GAIN_SHIFT 8u\n"
 "#define SHAFT_PUSH_FRAME_SHIFT 16u\n"
 "#define SHAFT_PUSH_GAIN_UNIT 32.0\n"),
],
P: [
("ins", "vec3 shaft_to_world0, shaft_to_world1, shaft_to_world2;\n", "",
 "// bbport (r80b_shafts-smooth-visible): this pixel's and light's noise in [0,1)^3 (main); the jitter of\n"
 "// the march's samples at smoothing level 2 (ShaftNoise)\n"
 "vec3 shaft_seed;\n"),
("ins", "// How much of light `layer` reaches the fog at p (view space): the share of the four map texels\n",
 r"""// bbport (r80b_shafts-smooth-visible): BB_LAMP_FOG_SHAFTS_SMOOTH, the push word's bits 1-2
// (lamp_fog_shaft_smooth.h): 0 the four-texel steps of r106c, 1 a bilinear filter of them, 2 that plus
// a jitter of the samples
uint shaftSmooth() { return (shaft_fast >> SHAFT_PUSH_SMOOTH_SHIFT) & 3u; }

// Noise in [0,1)^3 for the n-th sample of this light at this pixel: the seed moved along the 3D R
// sequence by n (spread along a half chord).
vec3 ShaftNoise(uint n) {
    return fract(shaft_seed + vec3(0.8191725134, 0.6710436067, 0.5497004779) * float(n + 1u));
}

// The angle at which sample n of a segment (end angles `previous`, `angle`) is taken: the middle (r80's
// exact energy split) below level 2; level 2 moves it between 0.15 and 0.85 of the segment.
float ShaftAngle(float previous, float angle, uint n) {
    if (shaftSmooth() < 2u) return 0.5 * (previous + angle);
    return mix(previous, angle, mix(0.15, 0.85, ShaftNoise(n).z));
}

// The share of the four map texels around uv (the gather's texel grid) whose free distance reaches
// `limit`. Level 0: their mean (quarter steps, r106c). Level 1: the same four tests weighted
// bilinearly by where uv lies between their centres (the gather's order is (i0,j1), (i1,j1), (i1,j0),
// (i0,j0)); level 2: uv first moved by up to half a texel each way (ShaftNoise(n).xy).
float ShaftTaps(vec2 uv, uint layer, float limit, uint n) {
    uint level = shaftSmooth();
    if (level == 0u) {
        return dot(step(vec4(limit), textureGather(shaft_maps, vec3(uv, float(layer)), 0)),
                   vec4(0.25));
    }
    vec2 size = vec2(textureSize(shaft_maps, 0).xy);
    if (level >= 2u) uv += (ShaftNoise(n).xy - 0.5) / size;
    vec2 f = fract(uv * size - 0.5);
    vec4 hit = step(vec4(limit), textureGather(shaft_maps, vec3(uv, float(layer)), 0));
    vec4 weight = vec4((1.0 - f.x) * f.y, f.x * f.y, f.x * (1.0 - f.y), (1.0 - f.x) * (1.0 - f.y));
    // four equal tests: exactly that answer (the weights sum to 1 only within rounding, and the fast
    // march compares answers to decide whether an odd sample reads the map)
    if (hit.x == hit.y && hit.y == hit.z && hit.z == hit.w) return hit.x;
    return dot(hit, weight);
}

""", ""),
("rep", "float Lit(vec3 p, vec3 centre, float radius, uint layer) {",
 "float Lit(vec3 p, vec3 centre, float radius, uint layer, uint sn) {"),
("rep",
 "    vec4 free_distance = textureGather(shaft_maps, vec3(uv, float(layer)), 0);\n"
 "    return dot(step(vec4(d - shaft_bias * radius), free_distance), vec4(0.25));\n",
 "    return ShaftTaps(uv, layer, d - shaft_bias * radius, sn); // bbport (r80b_shafts-smooth-visible)\n"),
("rep", "float LitFast(vec3 p, vec3 centre, float radius, uint layer) {",
 "float LitFast(vec3 p, vec3 centre, float radius, uint layer, uint sn) {"),
("rep",
 "    vec4 free_distance = textureGather(shaft_maps, vec3(e * 0.5 + 0.5, float(layer)), 0);\n"
 "    return dot(step(vec4(d - shaft_bias * radius), free_distance), vec4(0.25));\n",
 "    return ShaftTaps(e * 0.5 + 0.5, layer, d - shaft_bias * radius, sn); // bbport (r80b)\n"),
("rep",
 "                float middle = along + q * tan(0.5 * (previous + angle));\n"
 "                energy += segment * Lit(ray * middle, centre, radius, layer);\n",
 "                float middle = along + q * tan(ShaftAngle(previous, angle, i)); // bbport (r80b)\n"
 "                energy += segment * Lit(ray * middle, centre, radius, layer, i);\n"),
("rep",
 "                lit = LitFast(ray * (along + q * tan(0.5 * (previous + angle))), centre, radius,\n"
 "                              layer);\n",
 "                lit = LitFast(ray * (along + q * tan(ShaftAngle(previous, angle, i))), centre, radius,\n"
 "                              layer, i); // bbport (r80b_shafts-smooth-visible)\n"),
("rep",
 "                                     : LitFast(ray * pend_middle, centre, radius, layer);\n",
 "                                     : LitFast(ray * pend_middle, centre, radius, layer, pend_n);\n"),
("ins", "    float pend_segment = 0.0, pend_middle = 0.0;\n", "",
 "    uint pend_n = 0u; // bbport (r80b_shafts-smooth-visible): the pending sample's index (its noise)\n"),
("rep",
 "            pend_middle = along + q * tan(0.5 * (previous + angle));\n",
 "            pend_middle = along + q * tan(ShaftAngle(previous, angle, i)); // bbport (r80b)\n"
 "            pend_n = i;\n"),
("rep", "if (shadowed && shaft_fast != 0u) {",
 "if (shadowed && (shaft_fast & 1u) != 0u) { // bbport (r80b): bit 0 of the push word"),
("ins", "    shaft_to_world2 = shaftRow(SHAFT_TABLE_TO_WORLD + 8u);\n", "",
 r"""    // bbport (r80b_shafts-smooth-visible): this pixel's noise (interleaved gradient noise, three
    // patterns, a new one each frame: the push word's frame counter) and the gain (1/32 units; 0: 1)
    vec2 shaft_px = vec2(px) + 5.588238 * float((shaft_fast >> SHAFT_PUSH_FRAME_SHIFT) & 63u);
    const vec2 ign_scale = vec2(0.06711056, 0.00583715);
    vec3 shaft_seed0 = vec3(fract(52.9829189 * fract(dot(shaft_px, ign_scale))),
                            fract(52.9829189 * fract(dot(shaft_px.yx + 31.0, ign_scale))),
                            fract(52.9829189 * fract(dot(shaft_px + vec2(57.0, 11.0), ign_scale))));
    uint shaft_gain_bits = (shaft_fast >> SHAFT_PUSH_GAIN_SHIFT) & 255u;
    float shaft_gain =
        shaft_gain_bits == 0u ? 1.0 : float(shaft_gain_bits) * (1.0 / SHAFT_PUSH_GAIN_UNIT);
"""),
("ins", "        bool shadowed = strength > 0.0;\n", "",
 "        // bbport (r80b_shafts-smooth-visible): this light's noise (the pixel's, walked on per light)\n"
 "        shaft_seed = fract(shaft_seed0 + vec3(0.7548776662, 0.5698402909, 0.618034) * float(k));\n"),
("rep", "        scattering += rgb * weight * lit;\n",
 "        scattering += rgb * weight * lit * shaft_gain; // bbport (r80b_shafts-smooth-visible)\n"),
],
V: [
("ins", '#include "video_core/renderer_vulkan/lamp_fog_shaft_fast.h" // bbport (r106c_shaft-march-cheaper)\n', "",
 '#include "video_core/renderer_vulkan/lamp_fog_shaft_smooth.h" // bbport (r80b_shafts-smooth-visible)\n'),
],
C: [
("rep", "LampFogShaftFast::Frame(count, shaft_segments, w, h)};\n",
 "LampFogShaftSmooth::Pack(LampFogShaftFast::Frame(count, shaft_segments, w, h))};\n"),
("ins",
 "            LampFogShaftFast::PrintLine(); // bbport (r106c_shaft-march-cheaper): a line of its own\n", "",
 "            LampFogShaftSmooth::PrintLine(); // bbport (r80b_shafts-smooth-visible): a line of its own\n"),
],
B: [
("ins", "    out/lamp-fog-shaft-fast-test\n", "",
 "    # bbport (r80b_shafts-smooth-visible): the shafts' smoothing and gain knobs, the pushed word, a mirror of the bilinear taps\n"
 "    \"${CXX:-clang++}\" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_lamp_fog_shaft_smooth.cpp -o out/lamp-fog-shaft-smooth-test\n"
 "    out/lamp-fog-shaft-smooth-test\n"),
],
K: [
("ins", "target_include_directories(lamp-fog-shaft-fast-test PRIVATE ..)\n", "",
 "# bbport (r80b_shafts-smooth-visible): the shafts' smoothing and gain knobs and the pushed word\n"
 "# (lamp_fog_shaft_smooth.h); also built and run by engine/build.sh --test.\n"
 "add_executable(lamp-fog-shaft-smooth-test EXCLUDE_FROM_ALL ../tests/test_lamp_fog_shaft_smooth.cpp)\n"
 "target_compile_options(lamp-fog-shaft-smooth-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(lamp-fog-shaft-smooth-test PRIVATE ..)\n"),
],
D: [
("ins", "| `BB_LAMP_FOG_SHAFTS_FAST` | With `BB_LAMP_FOG_SHAFTS` on: the cheaper march",
 "| `BB_LAMP_FOG_SHAFTS_SMOOTH` | With `BB_LAMP_FOG_SHAFTS` on: how smooth the shafts' shadow edges are. The shadow maps are 128x128 octahedral (a texel is 1.4 to 2.8 degrees around the lamp) and the march read the four texels around a sample with a step each. `0`: as before (quarter steps one map texel wide; every sample at the middle of its segment). `1`: the same four texels weighted bilinearly by where the sample lies between their centres (a soft straight edge). `2` (the default; any other text is 2): 1 plus a jitter, new at every pixel and every frame, of the sample's place along its segment (0.15 to 0.85 of the segment's angle) and of the map lookup (up to half a texel each way), which DLSS or the temporal pass integrates. No extra rays and no extra map reads (the same four-texel gather); a few more arithmetic operations a sample (not measured: read it on the `Lighting: lamp fog` row of `BB_GPU_PROFILE=1`, `0` against `2`). Read again every frame while the test tools' live knobs are in the build. The log says once, and at each change, the level and the gain (`Volumetric lighting (r80b): shaft smoothing`), and every 600 lamp fog frames the frames at each level. |\n"
 "| `BB_LAMP_FOG_SHAFTS_GAIN` | With `BB_LAMP_FOG_SHAFTS` on: the brightness of the lamp fog while the shafts run, a decimal number from 0.25 to 4 (default 1.35: a bit above the 1 of before; other text is 1.35, a number outside the range is clamped). Every light of the shafts' march is multiplied by it, shadowed or not, so a lamp does not jump when it falls out of the ray budget; the debug view (`BB_LAMP_FOG_SHAFTS=3`) is not multiplied. Read again every frame while the test tools' live knobs are in the build. |\n",
 ""),
],
}

NEW_FILES = {
SMOOTH_H: r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r80b_shafts-smooth-visible): the lamp fog shafts smoother and stronger (point_volumetric.comp's
// SHAFTS builds; BB_LAMP_FOG_SHAFTS on only). The owner (2026-11-16, build 72): the shafts "just a bit hard
// see and maybe a little blocky like our shadows used to be". The maps are 128x128 octahedral, one hit
// distance a texel, and the march took the four texels around a sample with a step each: a quarter-step
// staircase one map texel (1.4 to 2.8 degrees) wide, and 6 samples a half chord whose lit/dark slices
// showed as bands. No Vulkan here: this header holds the two knobs, the word that carries them to the
// shader, the log lines and counters (tests/test_lamp_fog_shaft_smooth.cpp builds it alone).
//
// BB_LAMP_FOG_SHAFTS_SMOOTH (one digit; unset, empty or other text: 2):
//   0  the march of r106c (four texels, a step each, the sample at the middle of its segment)
//   1  the same four texels weighted bilinearly (the share of lit texels by the sample's place between
//      the texel centres: a straight soft edge, not a staircase); the same texture reads
//   2  1 plus a per-pixel, per-frame jitter (interleaved gradient noise, a new pattern each frame) of the
//      sample's place along its segment (0.15 to 0.85 of the segment's angle) and of the map lookup by
//      up to half a texel each way; DLSS / the temporal pass integrate it over frames
// BB_LAMP_FOG_SHAFTS_GAIN (decimal number, 0.25 to 4; unset, empty or other text: 1.35): the lamp fog's
// brightness while the shafts run (multiplied onto every shafts-march light's contribution, shadowed
// or not, so a lamp does not jump when it falls out of the ray budget); 1 is r106c's brightness.
// Nothing here casts a ray or reads a map texel more than the march read before.
//
// The word: point_volumetric.comp's push constant `shaft_fast` (r106c, was 0 or 1) now carries, with
// bit 0 unchanged, the smoothing level (bits 1-2), the gain in 1/32 (bits 8-15) and the frame counter
// (bits 16-31; the shader uses 6 bits): the push block keeps its 24 bytes. With SMOOTH=0 and GAIN=1
// the shader computes what r106c computed (the gain bits 0 also read as 1).
// With the test tools' live knobs (BB_LIVE_KNOBS_FILE; gpu/shim/bbport_live_knobs.h, test tools only)
// both knobs are read again at every call, so one running game can compare them at one camera; without
// them each is read once.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "../host_shaders/lamp_fog_shaft_layout.h"
// A test that does not link the runtime defines BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE before this include.
#if !defined(BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE) && __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_FOG_SHAFT_SMOOTH_LIVE 1
#else
#define BB_LAMP_FOG_SHAFT_SMOOTH_LIVE 0
#endif

namespace Vulkan::LampFogShaftSmooth {

inline constexpr std::uint32_t DefaultSmooth = 2;
inline constexpr float DefaultGain = 1.35f;
inline constexpr float MinGain = 0.25f;
inline constexpr float MaxGain = 4.0f;

/// The smoothing knob's text: one digit 0 to 2; anything else (also not set) is DefaultSmooth.
inline std::uint32_t ParseSmooth(const char* text) {
    if (text && text[0] >= '0' && text[0] <= '2' && text[1] == '\0') {
        return std::uint32_t(text[0] - '0');
    }
    return DefaultSmooth;
}

/// The gain knob's text: a finite decimal number, clamped to MinGain..MaxGain; anything else
/// (also not set) is DefaultGain.
inline float ParseGain(const char* text) {
    if (!text || !text[0]) {
        return DefaultGain;
    }
    char* end = nullptr;
    const double value = std::strtod(text, &end);
    if (end == text || *end != '\0' || !std::isfinite(value)) {
        return DefaultGain;
    }
    return float(std::clamp(value, double(MinGain), double(MaxGain)));
}

/// BB_LAMP_FOG_SHAFTS_SMOOTH now.
inline std::uint32_t Smooth() {
#if BB_LAMP_FOG_SHAFT_SMOOTH_LIVE
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_FOG_SHAFTS_SMOOTH", ParseSmooth};
    return knob.Get();
#else
    static const std::uint32_t value = ParseSmooth(std::getenv("BB_LAMP_FOG_SHAFTS_SMOOTH"));
    return value;
#endif
}

/// BB_LAMP_FOG_SHAFTS_GAIN now.
inline float Gain() {
#if BB_LAMP_FOG_SHAFT_SMOOTH_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_LAMP_FOG_SHAFTS_GAIN", ParseGain};
    return knob.Get();
#else
    static const float value = ParseGain(std::getenv("BB_LAMP_FOG_SHAFTS_GAIN"));
    return value;
#endif
}

/// The gain as the shader's 8 bits (units of 1/SHAFT_PUSH_GAIN_UNIT; never 0, which the shader reads as 1).
inline std::uint32_t GainBits(float gain) {
    const long bits = std::lround(double(gain) * SHAFT_PUSH_GAIN_UNIT);
    return std::uint32_t(std::clamp(bits, 8L, 255L));
}

/// The shader's word (see the header's text).
inline std::uint32_t PackWord(std::uint32_t fast, std::uint32_t smooth, float gain,
                              std::uint32_t frame) {
    return (fast & 1u) | ((smooth & 3u) << SHAFT_PUSH_SMOOTH_SHIFT) |
           (GainBits(gain) << SHAFT_PUSH_GAIN_SHIFT) | ((frame & 0xFFFFu) << SHAFT_PUSH_FRAME_SHIFT);
}

/// The period of PrintLine's line, in lamp fog frames (RecordLampFog's own 600).
inline constexpr std::uint32_t LinePeriod = 600;

/// The counts since the last PrintLine.
struct Totals {
    std::uint64_t frames = 0;    ///< frames that ran the shafts' march
    std::uint64_t level[3] = {}; ///< of them at each smoothing level
};
inline Totals totals;
inline std::uint32_t frame_counter = 0;
inline int told_smooth = -1; ///< the level the last once-line said; -1: none yet
inline float told_gain = -1.0f;

/// One frame of the shafts' march (VolumetricLight::RecordShafts), given r106c's flag (1 fast, 0 old):
/// the once-line when a value is new, the counts, the pushed word.
inline std::uint32_t Pack(std::uint32_t fast) {
    const std::uint32_t smooth = Smooth();
    const float gain = Gain();
    if (told_smooth != int(smooth) || told_gain != gain) {
        told_smooth = int(smooth);
        told_gain = gain;
        std::printf("Volumetric lighting (r80b): shaft smoothing %u (BB_LAMP_FOG_SHAFTS_SMOOTH: 0 "
                    "four-texel steps as before, 1 bilinear map filter, 2 bilinear plus per-pixel "
                    "per-frame jitter of the samples), shaft gain %.2f (BB_LAMP_FOG_SHAFTS_GAIN); no "
                    "extra rays, no extra map reads\n",
                    smooth, double(gain));
    }
    ++totals.frames;
    ++totals.level[std::min<std::uint32_t>(smooth, 2u)];
    return PackWord(fast, smooth, gain, frame_counter++);
}

/// The counts' line (every LinePeriod lamp fog frames, beside the r106c line), then the counts reset.
inline void PrintLine() {
    std::printf("Volumetric lighting (r80b): shaft smoothing over %llu frames: level 0 in %llu, 1 in "
                "%llu, 2 in %llu; gain now %.2f; extra map rays 0, extra map reads 0\n",
                static_cast<unsigned long long>(totals.frames),
                static_cast<unsigned long long>(totals.level[0]),
                static_cast<unsigned long long>(totals.level[1]),
                static_cast<unsigned long long>(totals.level[2]), double(Gain()));
    totals = {};
}

} // namespace Vulkan::LampFogShaftSmooth
""",
SMOOTH_T: r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r80b_shafts-smooth-visible): the shafts' smoothing and gain knobs, the pushed word and counters
// (lamp_fog_shaft_smooth.h) and a C++ mirror of point_volumetric.comp's ShaftTaps (the bilinear share of
// the four gathered texels): the gather's component order, the weights, and that level 0 is r106c's
// quarter steps.
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
// the pure test links no runtime: the knobs are read from the environment
#define BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE 1
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_fog_shaft_smooth.h"

using namespace Vulkan::LampFogShaftSmooth;

namespace {

constexpr int N = 8; // texels a side in the mirror's map

struct Vec4 {
    float x, y, z, w;
};

/// A map of N x N free distances (row j grows with v); clamp to edge.
struct Map {
    float t[N][N];
    float At(int i, int j) const {
        return t[std::clamp(j, 0, N - 1)][std::clamp(i, 0, N - 1)];
    }
};

/// textureGather(map, uv, 0): (i0,j1), (i1,j1), (i1,j0), (i0,j0) with i0 = floor(u N - 0.5).
Vec4 Gather(const Map& m, float u, float v) {
    const int i0 = int(std::floor(u * N - 0.5f)), j0 = int(std::floor(v * N - 0.5f));
    return {m.At(i0, j0 + 1), m.At(i0 + 1, j0 + 1), m.At(i0 + 1, j0), m.At(i0, j0)};
}

float Step(float limit, float value) { return limit <= value ? 1.0f : 0.0f; } // GLSL step(edge, x)

/// ShaftTaps at levels 0 and 1 (no jitter): the shader's statements.
float Taps(const Map& m, float u, float v, float limit, int level) {
    const Vec4 g = Gather(m, u, v);
    const float hx = Step(limit, g.x), hy = Step(limit, g.y), hz = Step(limit, g.z),
                hw = Step(limit, g.w);
    if (level == 0) {
        return 0.25f * (hx + hy + hz + hw);
    }
    const float fx = u * N - 0.5f - std::floor(u * N - 0.5f);
    const float fy = v * N - 0.5f - std::floor(v * N - 0.5f);
    if (hx == hy && hy == hz && hz == hw) {
        return hx; // four equal tests: exactly that answer
    }
    return hx * ((1 - fx) * fy) + hy * (fx * fy) + hz * (fx * (1 - fy)) + hw * ((1 - fx) * (1 - fy));
}

/// The straightforward bilinear filter of the hit grid at (u, v).
float Bilinear(const Map& m, float u, float v, float limit) {
    const float x = u * N - 0.5f, y = v * N - 0.5f;
    const int i0 = int(std::floor(x)), j0 = int(std::floor(y));
    const float fx = x - i0, fy = y - j0;
    const auto h = [&](int i, int j) { return Step(limit, m.At(i, j)); };
    return (1 - fx) * (1 - fy) * h(i0, j0) + fx * (1 - fy) * h(i0 + 1, j0) +
           (1 - fx) * fy * h(i0, j0 + 1) + fx * fy * h(i0 + 1, j0 + 1);
}

} // namespace

int main() {
    // the knobs
    assert(ParseSmooth(nullptr) == 2 && ParseSmooth("") == 2 && ParseSmooth("3") == 2 &&
           ParseSmooth("11") == 2 && ParseSmooth("x") == 2);
    assert(ParseSmooth("0") == 0 && ParseSmooth("1") == 1 && ParseSmooth("2") == 2);
    assert(ParseGain(nullptr) == DefaultGain && ParseGain("") == DefaultGain &&
           ParseGain("abc") == DefaultGain && ParseGain("1.5x") == DefaultGain &&
           ParseGain("nan") == DefaultGain && ParseGain("inf") == DefaultGain);
    assert(ParseGain("1") == 1.0f && ParseGain("2.5") == 2.5f);
    assert(ParseGain("0") == MinGain && ParseGain("100") == MaxGain && ParseGain("-3") == MinGain);
    assert(DefaultGain > 1.0f && DefaultGain < 2.0f);
    // the word: bit 0 as r106c's flag, the rest decodes back
    assert(GainBits(1.0f) == 32u && GainBits(1.35f) == 43u && GainBits(0.0f) == 8u &&
           GainBits(99.0f) == 255u);
    {
        const std::uint32_t w = PackWord(1u, 2u, 1.0f, 0x12345u);
        assert((w & 1u) == 1u);
        assert(((w >> SHAFT_PUSH_SMOOTH_SHIFT) & 3u) == 2u);
        assert(((w >> SHAFT_PUSH_GAIN_SHIFT) & 255u) == 32u);
        assert((w >> SHAFT_PUSH_FRAME_SHIFT) == 0x2345u);
        // smoothing 0, gain 1, frame 0: the shader's old inputs (bit 0 and a gain of 1) and nothing else
        assert(PackWord(0u, 0u, 1.0f, 0u) == (32u << SHAFT_PUSH_GAIN_SHIFT));
        assert((PackWord(7u, 7u, 1.0f, 0u) & 0xFFu) == (1u | (3u << SHAFT_PUSH_SMOOTH_SHIFT)));
    }
    // counters: Pack() counts, says the first values, keeps r106c's flag, counts the frame up
    {
        const std::uint32_t a = Pack(1u);
        const std::uint32_t b = Pack(0u);
        assert((a & 1u) == 1u && (b & 1u) == 0u);
        assert((b >> SHAFT_PUSH_FRAME_SHIFT) == ((a >> SHAFT_PUSH_FRAME_SHIFT) + 1u));
        assert(totals.frames == 2 && totals.level[Smooth()] == 2);
        PrintLine();
        assert(totals.frames == 0 && totals.level[0] + totals.level[1] + totals.level[2] == 0);
    }
    // the gather's order and the bilinear weights: levels 1 equals a plain bilinear filter of the hits,
    // over a map with a diagonal edge, at many (u, v); level 0 is quarter steps
    {
        Map m;
        for (int j = 0; j < N; ++j) {
            for (int i = 0; i < N; ++i) {
                m.t[j][i] = (i + 2 * j < 9) ? 100.0f : 3.0f; // lit (free 100 m) beyond a diagonal edge
            }
        }
        double worst = 0.0;
        int in_between = 0, steps_in_between = 0;
        for (int a = 0; a <= 256; ++a) {
            for (int b = 0; b <= 256; ++b) {
                const float u = (a + 0.37f) / 257.0f, v = (b + 0.61f) / 257.0f;
                const float smooth = Taps(m, u, v, 50.0f, 1), plain = Bilinear(m, u, v, 50.0f);
                worst = std::fmax(worst, std::fabs(smooth - plain));
                assert(smooth >= 0.0f && smooth <= 1.0f);
                const float quarter = Taps(m, u, v, 50.0f, 0);
                assert(std::fabs(quarter * 4.0f - std::round(quarter * 4.0f)) < 1e-6f);
                if (smooth > 0.001f && smooth < 0.999f) {
                    ++in_between;
                    if (std::fabs(smooth * 4.0f - std::round(smooth * 4.0f)) < 1e-3f) {
                        ++steps_in_between;
                    }
                }
            }
        }
        assert(worst < 1e-5);
        // every texel reaches the limit: exactly 1 at any place (not 0.99999994), as the fast march compares
        for (int a = 0; a <= 100; ++a) {
            assert(Taps(m, (a + 0.3f) / 101.0f, (a * 7 % 101 + 0.6f) / 101.0f, 1.0f, 1) == 1.0f);
        }
        // the smoothed edge takes many values between 0 and 1, the old one only the quarters
        assert(in_between > 1000 && steps_in_between * 4 < in_between);
    }
    // a vertical edge along the map: the share rises linearly with u across one texel (left lit)
    {
        Map m;
        for (int j = 0; j < N; ++j) {
            for (int i = 0; i < N; ++i) {
                m.t[j][i] = (i < 4) ? 100.0f : 3.0f;
            }
        }
        float last = 2.0f;
        for (int a = 0; a <= 100; ++a) {
            const float u = (3.0f + a / 100.0f) / N; // from 3/N to 4/N, across the texel centres 3.5/N
            const float s = Taps(m, u, 0.5f, 50.0f, 1);
            assert(s <= last + 1e-6f); // never rises as u goes from lit to dark
            last = s;
        }
        assert(Taps(m, 3.5f / N, 0.5f, 50.0f, 1) == 1.0f && Taps(m, 4.5f / N, 0.5f, 50.0f, 1) == 0.0f);
        assert(std::fabs(Taps(m, 4.0f / N, 0.5f, 50.0f, 1) - 0.5f) < 1e-5f);
    }
    std::printf("lamp fog shaft smooth: ok\n");
    return 0;
}
""",
}

CHECKS = {
P: [("shaft_seed", 5), ("float ShaftTaps(", 1), ("ShaftAngle(previous, angle, i)", 3),
    ("ShaftAngle(", 4), ("shaft_gain", 5), ("uint layer, uint sn) {", 2), ("pend_n", 3),
    ("(shaft_fast & 1u) != 0u", 1), ("shaft_fast != 0u", 0), ("textureGather(", 2)],
L: [("#define SHAFT_PUSH_GAIN_UNIT 32.0\n", 1), ("#define SHAFT_PUSH_SMOOTH_SHIFT 1u\n", 1)],
C: [("LampFogShaftSmooth::Pack(LampFogShaftFast::Frame(count, shaft_segments, w, h))", 1),
    ("LampFogShaftSmooth::PrintLine();", 1), ("static_assert(sizeof(PointParams) == 24);", 1)],
V: [('lamp_fog_shaft_smooth.h"', 1)],
B: [("test_lamp_fog_shaft_smooth.cpp", 1)],
K: [("lamp-fog-shaft-smooth-test", 3)],
D: [("`BB_LAMP_FOG_SHAFTS_SMOOTH`", 1), ("`BB_LAMP_FOG_SHAFTS_GAIN`", 1)],
}


def shafts_only(text):
    """Every r80b line of point_volumetric.comp lies inside an #ifdef SHAFTS (the default and WIND
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
        elif ("r80b" in line or "shaft_seed" in line or "ShaftTaps" in line or "ShaftAngle" in line or
              "ShaftNoise" in line or "shaft_gain" in line or "shaftSmooth" in line or
              "SHAFT_PUSH" in line or "pend_n" in line) and not any(stack):
            raise SystemExit("text check: r80b shader line outside #ifdef SHAFTS: %r" % line)


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    shafts_only(texts[P])
    s = texts[P]
    # the helpers come before their users, the old marches stay, main is last
    if not (s.find("float ShaftTaps(") < s.find("float Lit(") < s.find("float LitFast(") <
            s.find("float inscatterShadowed(") < s.find("float inscatterShadowedFast(") <
            s.find("void main()")):
        raise SystemExit("text check: shader functions out of order")
    # the knobs' names, the shift numbers the shader and the header share, the sample ranges
    h = texts[SMOOTH_H]
    if h.count('"BB_LAMP_FOG_SHAFTS_SMOOTH"') != 2 or h.count('"BB_LAMP_FOG_SHAFTS_GAIN"') != 2:
        raise SystemExit("text check: the knobs' names")
    if "SHAFT_PUSH_GAIN_UNIT" not in h or "SHAFT_PUSH_FRAME_SHIFT" not in h:
        raise SystemExit("text check: the header does not use the layout's push numbers")
    if "0.15" not in s or "0.85" not in s or "0.15 to 0.85" not in texts[D]:
        raise SystemExit("text check: the jitter range is not named in shader and README")
    if "1.35" not in h or "1.35" not in texts[D]:
        raise SystemExit("text check: the default gain is not named in header and README")
    # the push block stays 24 bytes
    if texts[C].count("u32 shaft_fast;") != 1:
        raise SystemExit("text check: the push struct changed")


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
        raise SystemExit("%s is not a source tree root (set R80B_ROOT)" % ROOT)
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
            tmp = full + ".r80btmp"
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
        tmp = full + ".r80btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    for path, text, _ in news:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()

