# r88_wind-lamp-fog: FEATURE patch. Wind, next user of the shared wind (r82): the LAMP fog (the
# glow around street lamps, torches and the hand lantern, effect_point_fog, point_volumetric.comp)
# drifts with the same world-pinned noise as the sun fog, so lamp glows show slow denser and
# thinner patches moving downwind, together with the sun fog's patches. Off by default: it acts
# only with BB_WIND=1 (r82's switch); its strength is BB_WIND_LAMP_FOG (0-2, default 1; 0 = the
# lamp fog's pass without wind).
#
# Why: the owner could not see the sun fog drift in play (r82, even at contrast 2) and asked for
# more things to follow the wind so that it can be told. A lamp glow is bright and near, so a
# drifting density shows there.
#
# What:
#  1. host_shaders/point_volumetric.comp, only inside #ifdef WIND: includes wind_noise.glsl (r82's
#     GLSL noise, the same file the sun fog includes: shared, not copied); reads the composite
#     camera's view to world rows, the noise offsets and the contrast from the constants buffer's
#     words 16-35 (bytes 64-143 of fog_data, free: the inverse projection is bytes 0-63, the lights
#     start at 256); each half chord of a light's inscatter() (and of r80's inscatterShadowed(),
#     per segment, so the debug view's lost light gets it too) is multiplied by m =
#     wind_factor_rows(...) taken ONCE per half chord, at the point that splits that half's exact
#     inverse-square energy in two (along + q tan of the mean of its end angles; r80's
#     EnergyMiddle). The ctx plan named the per-segment window term; one sample per segment would
#     be 12 noise fields a light per pixel (about 6x the cost), and a CPU probe (Python copy of the
#     noise, a 6 m glow 10 m away and a 3 m glow 4 m away) gave an rms difference of 2.6-3.0% (6 m)
#     and 0.4-0.8% (3 m) between the two rules at contrast 1-1.5 (20% at contrast 2-3 only where m
#     is clipped to 0). The lamp fog's fixed fade exp(-0.025 t) stays (no extinction change).
#  2. CMakeLists.txt: three builds point_volumetric_wind_comp (WIND), _shafts_wind_comp (SHAFTS
#     WIND) and _shafts_view_wind_comp (SHAFTS VIEW WIND); wind_noise.glsl and lamp_wind_layout.h
#     (new: the wind words' place, read by the shader and by C++) as their INCLUDES dependency.
#     The three plain builds compile to the same SPIR-V words as before.
#  3. vk_volumetric_light.h/.cpp: SetWind (r82, before every Integrate with BB_WIND=1) also keeps
#     the offsets for the lamp fog; RecordLampFog asks LampWindDrift (BB_WIND=1, strength above 0,
#     fog_camera valid, the WIND build made), writes the 20 wind words into the uploaded fog_data
#     and widens the constants range from 64 to 144 bytes only then, and binds the WIND build;
#     RecordShafts (r80) binds the SHAFTS WIND build (VIEW for level 3) while drifting. Builds are
#     made lazily at the first drifting lamp fog (never with BB_WIND unset or strength 0); a build
#     that cannot be made leaves that lamp fog even and says so once. Same bindings and push
#     constants as the plain builds (the wind words travel in the constants buffer, not the push).
#  4. bbport_wind.h: DefaultLampFog 1, MaxLampFog 2, LampFogGain 1.5, SanitizeLampFog,
#     LampFogContrast (contrast = strength x 1.5, so strength 1 = contrast 1.5, 2 = contrast 3);
#     test_wind.cpp: the clamp, the gain and the clipped mean at the strongest contrast (in g).
#  5. test_effect_pipelines.cpp: the three builds made with their bindings and push sizes.
#  6. wind_noise.glsl: its header comment names the new includer (comment only).
#  7. README.md: the BB_WIND row's "The lamp fog does not drift yet." now says it does, and a new
#     row BB_WIND_LAMP_FOG after r82's BB_WIND_FOG row (anchored on the wind feature's own rows).
#
# r80 (BB_LAMP_FOG_SHAFTS, already in the tree) also edits point_volumetric.comp and RecordShafts:
# both knobs on together are built and bound (SHAFTS WIND, SHAFTS VIEW WIND), not refused. This
# script replaces r80's capture lines in RecordShafts (`pipeline = *point_shafts.pipeline,` /
# `layout = *point_shafts.layout]`) and two plain lines of RecordLampFog (the constants range
# `{buffer, 0, 64}` and the plain capture `pipeline = *point.pipeline, layout = *point.layout]`);
# every other edit keeps its anchor text. Revert r88 before r80.
#
# Knobs (environment, read once; no ini key or menu row: the wind plan adds keys in W5 once the
# owner accepts the look; rule 4 allows env for work in progress):
#   BB_WIND=1 (r82's switch) turns the lamp fog drift on with it. BB_WIND_LAMP_FOG: 0-2, default 1
#   (missing, unreadable or non-finite: 1; then clamped). BB_WIND_DIR/SPEED/GUSTS (r82) move it.
#   BB_WIND_FOG (r82, the sun fog's contrast) does not touch the lamp fog.
# Log (lines start with "Wind", which the slot worker's evidence pattern collects):
#   once, at the first lamp fog with lights and BB_WIND=1: "Wind lamp fog (r88, BB_WIND=1): the
#   lamp fog drifts with the sun fog's noise, strength 1.00 (BB_WIND_LAMP_FOG; contrast 1.50), ..."
#   (or "... strength 0 ...: the lamp fog stays even"); once "Wind lamp fog (r88): drift build
#   made" (and "... shafts drift build made" with BB_LAMP_FOG_SHAFTS); at the 120th lamp fog frame
#   and every 600th after: "Wind lamp fog (r88): N of M lamp fog frames drifted (S of them with
#   shafts), C without a camera, E even (strength 0 or no drift build); this frame L lights".
# Profiler: no new pass. The WIND build runs in place of the plain lamp fog under the pinned row
#   "Lighting: lamp fog" (EffectPass::Mark 9), so its cost is that row's difference.
#
# Cost (NOT MEASURED): off: nothing on the GPU (plain builds, same 64-byte range, the WIND builds
#   never made); on the CPU one bool test per lamp fog frame and per shafts frame. On: 2 noise
#   fields (32 hashed corners) per light a pixel at internal resolution: with 1-4 lamp glows over
#   a pixel 4-16 M fields at 1080p internal against the sun fog drift's up to 16.6 M, so an
#   estimate of 0.05-0.3 ms at 1080p internal, about 4x at 2160p internal. Read "Lighting: lamp
#   fog" with BB_GPU_PROFILE=1, BB_WIND=1 against BB_WIND=1 BB_WIND_LAMP_FOG=0 (same build, spot).
# Motion vectors and the ray traced scene: untouched (the pass writes only the lamp fog image,
#   composited before the upscaler like the plain lamp fog; nothing is captured or drawn).
#
# Use: cd <tree> && python -I -X utf8 r88_wind-lamp-fog.fixed.py check | apply | revert (root from
# R88_ROOT, else the current directory). Files keep their line ends (CRLF in the tree). Originals
# are kept in r88_backup/ next to this script. One new file (CRLF), removed by revert:
# host_shaders/lamp_wind_layout.h. Needs r80 and r82 applied (the anchors hold their text); r87
# (TOOL) is not needed and not touched.
#
# Review fixes (2026-11-15 20:3x, against the draft r88_wind-lamp-fog.py):
#  - maintainer rule 10 (numbers written twice are tied by code, not by a comment): the wind words'
#    place in fog_data was written twice, as LampWindAt/LampWindWords in C++ and as the literals
#    row(16u) ... row(32u) in the shader. Both now read host_shaders/lamp_wind_layout.h (the house
#    pattern of volumetric_area_layout.h: plain #define lines, included by GLSL and C++), with
#    static_asserts on the C++ side; the shader includes it only inside #ifdef WIND, so the plain
#    builds' SPIR-V stays word for word.
#  - LampWindDrift's static `strength` hid the member VolumetricLight::strength (the sun fog's
#    0.08): renamed lamp_strength.
#  - README (rule 7, the exact rule): the sample point splits the half chord's inverse-square
#    light, not its light (the window and the fade with distance are left out of that split).
# Second review (2026-11-15 20:4x):
#  - the new README row was anchored on the whole BB_WIND_FOG row, which r94_fog-noise (pending)
#    rewrites, so r88 refused after r94. It is now inserted before the start of the BB_WIND_VIEW
#    row (r82's, the row after BB_WIND_FOG; r94 leaves it as it is), so r88 and r94 apply in either
#    order; an order check keeps BB_WIND_FOG, BB_WIND_LAMP_FOG, BB_WIND_VIEW in that order.
#  - test_effect_pipelines.cpp: the three includes and rows were anchored on r82's wind view lines,
#    right after which r94 inserts its own, so after r94 r88's check said "mixed". They now follow
#    r80's lamp fog shafts view include and row (the lamp fog's builds side by side).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r88_backup")
ROOT = os.environ.get("R88_ROOT") or os.getcwd()
TMP = ".r88tmp"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    H + "lamp_wind_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r88_wind-lamp-fog): where the lamp fog's wind words sit in its constants buffer
// (VolumetricLight's fog_data), shared by point_volumetric.comp's WIND builds and
// VolumetricLight::RecordLampFog. Plain #define lines only: the shader includes this file through
// GL_GOOGLE_include_directive (inside #ifdef WIND) and C++ includes it as it is, so one text holds
// the numbers both sides use (as volumetric_area_layout.h does for the area gate).
#ifndef LAMP_WIND_LAYOUT_H
#define LAMP_WIND_LAYOUT_H

// The first wind word: after the game's inverse projection (words 0-15), before the lights (byte
// 256 on). From there five rows of LAMP_WIND_ROW words: the composite camera's view to world
// matrix (rows 0-2, 3x4, the translation in .w), the fog noise's octave 1 offsets in cells with
// the contrast in .w (row 3), and its octave 2 offsets with 0 in .w (row 4).
#define LAMP_WIND_AT 16u
#define LAMP_WIND_ROW 4u
#define LAMP_WIND_WORDS 20u

#endif
''',
}

EDITS = {
    H + "point_volumetric.comp": [
        (r'''#version 450
#extension GL_EXT_scalar_block_layout : require
''', r'''#version 450
#extension GL_EXT_scalar_block_layout : require
#ifdef WIND
// bbport (r88_wind-lamp-fog): BB_WIND=1 only: the lamp fog takes the sun fog's noise from the same
// file (wind_noise.glsl), so the patches of both are the same and drift together
#extension GL_GOOGLE_include_directive : require
#endif
'''),
        (r'''bool finite3(vec3 v) { return !any(isnan(v)) && !any(isinf(v)); }
''', r'''bool finite3(vec3 v) { return !any(isnan(v)) && !any(isinf(v)); }
#ifdef WIND
#include "wind_noise.glsl"
#include "lamp_wind_layout.h"

// bbport (r88_wind-lamp-fog): BB_WIND=1 only (VolumetricLight::RecordLampFog): the constants'
// wind words (lamp_wind_layout.h, words 16-35): the composite camera's view to world matrix (3x4
// rows, translation in .w), the fog noise's offsets in cells (BbWind::Snapshot off1, off2) and the
// contrast in wind_off1.w (BbWind::LampFogContrast of BB_WIND_LAMP_FOG). Read once in main().
vec4 wind_row0, wind_row1, wind_row2, wind_off1, wind_off2;

// The wind's fog density factor m for the half chord from `begin` to `end` (wind_noise.glsl's
// wind_factor_rows, the sun fog march's own), taken once at the point that splits the half's exact
// inverse-square energy in two (along + q tan of the mean of its end angles, as lamp_fog_shafts.h
// EnergyMiddle), not once a segment: 2 noise samples a light per pixel, not 12. Patches smaller
// than a half chord (the noise's cells are 4.5 m and 12 m across) are not resolved along it.
float lamp_wind(vec3 ray, float along, float q, float begin, float end) {
    float middle = along + q * tan(0.5 * (atan((begin - along) / q) + atan((end - along) / q)));
    return wind_factor_rows(wind_row0, wind_row1, wind_row2, ray * middle, wind_off1.xyz,
                            wind_off2.xyz, wind_off1.w);
}
#endif
'''),
        (r'''    return energy * 0.025;
''', r'''#ifdef WIND
    // bbport (r88_wind-lamp-fog): this half chord's fog drifts with the wind (lamp_wind)
    energy *= lamp_wind(ray, along, q, begin, end);
#endif
    return energy * 0.025;
'''),
        (r'''    float ds = (end - begin) / float(segments);
    float energy = 0.0;
    float previous = atan((begin - along) / q);
''', r'''    float ds = (end - begin) / float(segments);
    float energy = 0.0;
    float previous = atan((begin - along) / q);
#ifdef WIND
    // bbport (r88_wind-lamp-fog): this half chord's fog drifts with the wind (lamp_wind), the same
    // factor for the light that reaches the fog and for the light the maps cut off
    float wind_m = lamp_wind(ray, along, q, begin, end);
#endif
'''),
        (r'''        float segment = (angle - previous) * window * window * exp(-0.025 * t) * 0.025;
''', r'''        float segment = (angle - previous) * window * window * exp(-0.025 * t) * 0.025;
#ifdef WIND
        segment *= wind_m; // bbport (r88_wind-lamp-fog)
#endif
'''),
        (r'''    vec3 scattering = vec3(0.0);
''', r'''    vec3 scattering = vec3(0.0);
#ifdef WIND
    // bbport (r88_wind-lamp-fog): the wind words (lamp_wind_layout.h; lamp_wind)
    wind_row0 = row(LAMP_WIND_AT);
    wind_row1 = row(LAMP_WIND_AT + LAMP_WIND_ROW);
    wind_row2 = row(LAMP_WIND_AT + 2u * LAMP_WIND_ROW);
    wind_off1 = row(LAMP_WIND_AT + 3u * LAMP_WIND_ROW);
    wind_off2 = row(LAMP_WIND_AT + 4u * LAMP_WIND_ROW);
#endif
'''),
    ],
    H + "wind_noise.glsl": [
        (r'''// by volumetric_light.comp (WIND) and wind_noise_test.comp.
''', r'''// by volumetric_light.comp (WIND), point_volumetric.comp (WIND; bbport (r88_wind-lamp-fog)) and
// wind_noise_test.comp.
'''),
    ],
    "engine/gpu/shim/bbport_wind.h": [
        (r'''inline float SanitizeContrast(float contrast) {
    return std::clamp(FiniteOr(contrast, DefaultContrast), 0.0f, MaxContrast);
}
''', r'''inline float SanitizeContrast(float contrast) {
    return std::clamp(FiniteOr(contrast, DefaultContrast), 0.0f, MaxContrast);
}

/// bbport (r88_wind-lamp-fog): the lamp fog's drift strength (BB_WIND_LAMP_FOG): 0 an even lamp
/// fog, DefaultLampFog the default, MaxLampFog the most. The lamp fog multiplies its density by
/// Density at the contrast LampFogContrast(strength) = strength * LampFogGain. The gain is there
/// because a lamp's glow is smaller than the noise's cells (Lambda2, Lambda1XZ), so the same
/// contrast shows less in it than in the sun fog. CPU estimate (Python copy of Field; a 6 m glow
/// 10 m away, wind 1.5 m/s): a pixel's lamp fog light varies over time by 13% (sd) at contrast 1,
/// 20% at 1.5, 26% at 2; a 3 m glow 4 m away by 8%, 11% and 15%. At MaxLampFog (contrast 3) m is 0
/// where N < 1/3 (about 14% of space), which raises the mean of m a few percent (wind-test g).
inline constexpr float DefaultLampFog = 1.0f, MaxLampFog = 2.0f, LampFogGain = 1.5f;

/// The lamp fog's strength: non-finite gives DefaultLampFog, then clamped to 0-MaxLampFog.
inline float SanitizeLampFog(float strength) {
    return std::clamp(FiniteOr(strength, DefaultLampFog), 0.0f, MaxLampFog);
}

/// The contrast the lamp fog gives Density (wind_noise.glsl's wind_density) for a strength.
inline float LampFogContrast(float strength) {
    return strength * LampFogGain;
}
'''),
    ],
    "engine/tests/test_wind.cpp": [
        (r'''               "the contrast clamps to 0-MaxContrast, NaN gives DefaultContrast");
''', r'''               "the contrast clamps to 0-MaxContrast, NaN gives DefaultContrast");
        // bbport (r88_wind-lamp-fog): the lamp fog's strength (BB_WIND_LAMP_FOG) and its contrast
        Expect(SanitizeLampFog(nan) == DefaultLampFog && SanitizeLampFog(inf) == DefaultLampFog &&
                   SanitizeLampFog(5.0f) == MaxLampFog && SanitizeLampFog(-1.0f) == 0.0f &&
                   SanitizeLampFog(MaxLampFog) == MaxLampFog,
               "the lamp fog's strength clamps to 0-MaxLampFog, NaN and inf give DefaultLampFog");
        Expect(LampFogContrast(0.0f) == 0.0f && LampFogContrast(DefaultLampFog) == LampFogGain &&
                   LampFogContrast(MaxLampFog) == 2.0f * LampFogGain,
               "the lamp fog's contrast is the strength times LampFogGain");
'''),
        (r'''        Random random{5};
        double field = 0.0, density = 0.0;
''', r'''        Random random{5};
        double field = 0.0, density = 0.0;
        double lamp = 0.0; // bbport (r88_wind-lamp-fog): at the lamp fog's strongest contrast
'''),
        (r'''            density += Density(p, o1, o2, 0.4f);
''', r'''            density += Density(p, o1, o2, 0.4f);
            lamp += Density(p, o1, o2, LampFogContrast(MaxLampFog)); // bbport (r88_wind-lamp-fog)
'''),
        (r'''        Expect(flat, "contrast 0 gives exactly 1, and N lies in [0, 1)");
''', r'''        Expect(flat, "contrast 0 gives exactly 1, and N lies in [0, 1)");
        // bbport (r88_wind-lamp-fog): the lamp fog at its strongest (contrast
        // LampFogContrast(MaxLampFog) = 3) clips m at 0 where N < 1/3, which only adds: its mean
        // lies above the unclipped 1 + C (2 mean(N) - 1) by a few percent (CPU estimate 0.05)
        lamp /= count;
        const double unclipped = 1.0 + double(LampFogContrast(MaxLampFog)) * (2.0 * field - 1.0);
        std::printf("wind-test: the lamp fog's density at contrast %.2f has the mean %.4f (%.4f "
                    "without the clip at 0)\n",
                    double(LampFogContrast(MaxLampFog)), lamp, unclipped);
        Expect(lamp >= unclipped && lamp - unclipped <= 0.08,
               "the lamp fog's strongest contrast raises the mean density by 0-0.08 (clip at 0)");
'''),
    ],
    R + "vk_volumetric_light.h": [
        (r'''    } wind_fog;
''', r'''    } wind_fog;
    // bbport (r88_wind-lamp-fog): BB_WIND=1 only: the lamp fog's WIND builds (point_wind; with
    // r80's shadow maps point_shafts_wind, SHAFTS or SHAFTS VIEW as ShaftsReady's level), made at
    // the first lamp fog that drifts (LampWindPasses; false: that lamp fog stays even);
    // LampWindDrift: this frame's decision with its once-line and the 120/600-frame line; the
    // offsets SetWind gave, the contrast, and the counts of that line
    bool LampWindPasses(bool shafts, u32 level);
    bool LampWindDrift(u32 lights);
    Pass point_wind, point_shafts_wind;
    struct LampWind {
        bool wanted = false, drift = false, said = false;
        bool tried = false, failed = false, shafts_tried = false, shafts_failed = false;
        std::array<float, 3> off1{}, off2{};
        float contrast = 0.0f;
        u32 lines = 0;
        u64 frames = 0, drifted = 0, shafts_drifted = 0, no_camera = 0, even = 0;
    } lamp_wind;
'''),
    ],
    R + "vk_volumetric_light.cpp": [
        (r'''#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
''', r'''#include "video_core/host_shaders/volumetric_light_wind_view_comp.h"
// bbport (r88_wind-lamp-fog): the lamp fog's WIND builds (BB_WIND=1 only)
#include "video_core/host_shaders/point_volumetric_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_wind_comp.h"
#include "../host_shaders/lamp_wind_layout.h"
'''),
        (r'''static_assert(FogBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
''', r'''static_assert(FogBytes <= 65536, "vkCmdUpdateBuffer takes at most 64 KiB");
// bbport (r88_wind-lamp-fog): BB_WIND=1 only: where the lamp fog's wind words sit in fog_data
// (host_shaders/lamp_wind_layout.h, which point_volumetric.comp's WIND builds include too: five
// rows from word LAMP_WIND_AT) and the bytes the constants range then covers
constexpr u32 LampWindAt = LAMP_WIND_AT * 4;
constexpr u32 LampWindBytes = LampWindAt + LAMP_WIND_WORDS * 4;
static_assert(LampWindAt >= 16 * 4 && LampWindBytes <= FogLightsAt,
              "the wind words lie after the inverse projection and before the lights");
static_assert(LAMP_WIND_WORDS == 5 * LAMP_WIND_ROW &&
                  sizeof(LampFog::Camera::view_to_world) == 3 * LAMP_WIND_ROW * sizeof(float),
              "three view to world rows, then off1 and off2");
'''),
        (r'''    wind_fog.on = camera_valid && !wind_fog.failed;
''', r'''    wind_fog.on = camera_valid && !wind_fog.failed;
    // bbport (r88_wind-lamp-fog): the lamp fog (Composite, later in this frame) drifts with the
    // same offsets; its camera is the composite's (SetCamera), so it takes no matrix here
    lamp_wind.wanted = true;
    lamp_wind.off1 = off1;
    lamp_wind.off2 = off2;
'''),
        (r'''    EffectPass::Mark(80, "lamp fog shafts", true);
''', r'''    // bbport (r88_wind-lamp-fog): drifting (RecordLampFog's decision), the SHAFTS build with WIND
    // (the same bindings and push constants; the wind words are in `constants`). If it cannot be
    // made, these shafts stay even (counted as even in the "Wind lamp fog (r88)" line).
    const bool shafts_drift = lamp_wind.drift && LampWindPasses(true, LampFogShafts::Level());
    lamp_wind.drifted += shafts_drift ? 1 : 0;
    lamp_wind.shafts_drifted += shafts_drift ? 1 : 0;
    lamp_wind.even += (lamp_wind.drift && !shafts_drift) ? 1 : 0;
    EffectPass::Mark(80, "lamp fog shafts", true);
'''),
        (r'''        [params, constants, records, depth, out, maps_in, w, h, pipeline = *point_shafts.pipeline,
         layout = *point_shafts.layout](vk::CommandBuffer cmd) {
''', r'''        [params, constants, records, depth, out, maps_in, w, h,
         pipeline = shafts_drift ? *point_shafts_wind.pipeline // bbport (r88_wind-lamp-fog)
                                 : *point_shafts.pipeline,
         layout = shafts_drift ? *point_shafts_wind.layout
                               : *point_shafts.layout](vk::CommandBuffer cmd) {
'''),
        (r'''    std::copy(fog_matrix.begin(), fog_matrix.end(), data.begin());
''', r'''    std::copy(fog_matrix.begin(), fog_matrix.end(), data.begin());
    // bbport (r88_wind-lamp-fog): BB_WIND=1: whether this lamp fog drifts (LampWindDrift); if it
    // does, the wind words of fog_data (lamp_wind_layout.h: words 16-35, free: the lights start at
    // FogLightsAt) carry the composite camera's view to world rows (fog_camera, as LampFog::Memory
    // uses it), the noise offsets in cells and the contrast in off1's .w, for the WIND builds of
    // point_volumetric.comp; the constants range below then takes them too. Off: nothing written,
    // range 64.
    lamp_wind.drift = LampWindDrift(u32(lights.size()));
    if (lamp_wind.drift) {
        u32* const words = data.data() + LAMP_WIND_AT;
        for (u32 i = 0; i < 3 * LAMP_WIND_ROW; ++i) {
            words[i] = std::bit_cast<u32>(fog_camera.view_to_world[i]);
        }
        for (u32 i = 0; i < 3; ++i) {
            words[3 * LAMP_WIND_ROW + i] = std::bit_cast<u32>(lamp_wind.off1[i]);
            words[4 * LAMP_WIND_ROW + i] = std::bit_cast<u32>(lamp_wind.off2[i]);
        }
        words[3 * LAMP_WIND_ROW + 3] = std::bit_cast<u32>(lamp_wind.contrast);
        words[4 * LAMP_WIND_ROW + 3] = 0;
    }
'''),
        (r'''    const vk::DescriptorBufferInfo constants{buffer, 0, 64};
''', r'''    // bbport (r88_wind-lamp-fog): drifting, the WIND build reads the wind words too
    const vk::DescriptorBufferInfo constants{buffer, 0, lamp_wind.drift ? LampWindBytes : 64u};
'''),
        (r'''    EffectPass::Mark(9, "lamp fog");
    scheduler.RecordCrumb(
        {.name = "Lamp fog"},
''', r'''    lamp_wind.drifted += lamp_wind.drift ? 1 : 0; // bbport (r88_wind-lamp-fog): the counts' line
    EffectPass::Mark(9, "lamp fog");
    scheduler.RecordCrumb(
        {.name = "Lamp fog"},
'''),
        (r'''         pipeline = *point.pipeline, layout = *point.layout](vk::CommandBuffer cmd) {
''', r'''         pipeline = lamp_wind.drift ? *point_wind.pipeline : *point.pipeline, // bbport (r88)
         layout = lamp_wind.drift ? *point_wind.layout : *point.layout](vk::CommandBuffer cmd) {
'''),
        (r'''    wind_fog.next_line = now + std::chrono::seconds(2);
    wind_fog.frames = wind_fog.no_camera = wind_fog.compared = 0;
    wind_fog.gap = 0.0f;
}
''', r'''    wind_fog.next_line = now + std::chrono::seconds(2);
    wind_fog.frames = wind_fog.no_camera = wind_fog.compared = 0;
    wind_fog.gap = 0.0f;
}

// bbport (r88_wind-lamp-fog): with BB_WIND=1 (SetWind ran before this frame's march), at each lamp
// fog with lights: whether it drifts this frame. It does with a strength above 0, the plain WIND
// build made (LampWindPasses) and a camera from SetCamera (fog_camera); the SHAFTS one is asked
// for in RecordShafts. The first call reads BB_WIND_LAMP_FOG (BbWind::SanitizeLampFog: 0 to
// MaxLampFog; missing or not a number: DefaultLampFog) and says it once; at the 120th lamp fog
// frame and then every 600th a line of what the drift did. Without BB_WIND=1: false at once.
bool VolumetricLight::LampWindDrift(u32 lights) {
    if (!lamp_wind.wanted) {
        return false;
    }
    static const float lamp_strength = [] {
        const char* text = std::getenv("BB_WIND_LAMP_FOG");
        float value = BbWind::DefaultLampFog;
        if (text != nullptr && text[0] != 0) {
            char* end = nullptr;
            const float parsed = std::strtof(text, &end);
            value = end != text ? parsed : BbWind::DefaultLampFog;
        }
        return BbWind::SanitizeLampFog(value);
    }();
    lamp_wind.contrast = BbWind::LampFogContrast(lamp_strength);
    if (!std::exchange(lamp_wind.said, true)) {
        if (lamp_strength > 0.0f) {
            std::printf("Wind lamp fog (r88, BB_WIND=1): the lamp fog drifts with the sun fog's "
                        "noise, strength %.2f (BB_WIND_LAMP_FOG; contrast %.2f), one noise sample "
                        "per half chord of each light; lamp fog shafts %s\n",
                        double(lamp_strength), double(lamp_wind.contrast),
                        LampFogShafts::Level() == LampFogShafts::Off ? "off" : "on (both apply)");
        } else {
            std::printf("Wind lamp fog (r88, BB_WIND=1): strength 0 (BB_WIND_LAMP_FOG): the lamp "
                        "fog stays even (its pass without wind)\n");
        }
    }
    if (lamp_wind.frames == (lamp_wind.lines == 0 ? 120u : 600u)) {
        std::printf("Wind lamp fog (r88): %llu of %llu lamp fog frames drifted (%llu of them with "
                    "shafts), %llu without a camera, %llu even (strength 0 or no drift build); "
                    "this frame %u lights\n",
                    static_cast<unsigned long long>(lamp_wind.drifted),
                    static_cast<unsigned long long>(lamp_wind.frames),
                    static_cast<unsigned long long>(lamp_wind.shafts_drifted),
                    static_cast<unsigned long long>(lamp_wind.no_camera),
                    static_cast<unsigned long long>(lamp_wind.even), lights);
        ++lamp_wind.lines;
        lamp_wind.frames = lamp_wind.drifted = lamp_wind.shafts_drifted = 0;
        lamp_wind.no_camera = lamp_wind.even = 0;
    }
    ++lamp_wind.frames;
    if (!(lamp_strength > 0.0f) || !LampWindPasses(false, LampFogShafts::Off)) {
        ++lamp_wind.even;
        return false;
    }
    if (!fog_camera.valid) {
        ++lamp_wind.no_camera;
        return false;
    }
    return true;
}

// bbport (r88_wind-lamp-fog): the lamp fog's WIND builds, made at the first lamp fog that drifts
// (the SHAFTS one at the first drifting lamp fog with r80's shadow maps, VIEW for level 3), so a
// game without BB_WIND=1 or with strength 0 never makes them. If the plain one cannot be made the
// lamp fog stays even; if the SHAFTS one cannot, shadowed lamp fog does. Bindings and push
// constants are the plain builds' (RecordLampFog's pass, ShaftsReady's point_shafts).
bool VolumetricLight::LampWindPasses(bool shafts, u32 level) {
    using enum vk::DescriptorType;
    if (!lamp_wind.tried) {
        lamp_wind.tried = true;
        lamp_wind.failed =
            !CreatePass(point_wind,
                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
                        POINT_VOLUMETRIC_WIND_COMP, 3 * sizeof(u32), "Point volumetric (wind)");
        std::printf(lamp_wind.failed ? "Wind lamp fog (r88): the drift build could not be made; "
                                       "the lamp fog stays even\n"
                                     : "Wind lamp fog (r88): drift build made\n");
    }
    if (lamp_wind.failed) {
        return false;
    }
    if (shafts && !lamp_wind.shafts_tried) {
        lamp_wind.shafts_tried = true;
        const std::span<const u32> march =
            level == LampFogShafts::View
                ? std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP)
                : std::span<const u32>(POINT_VOLUMETRIC_SHAFTS_WIND_COMP);
        lamp_wind.shafts_failed =
            !CreatePass(point_shafts_wind,
                        {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
                         eCombinedImageSampler},
                        march, 5 * sizeof(u32), "Point volumetric (shafts, wind)");
        std::printf(lamp_wind.shafts_failed
                        ? "Wind lamp fog (r88): the shafts drift build could not be made; the "
                          "shadowed lamp fog stays even\n"
                        : "Wind lamp fog (r88): shafts drift build made\n");
    }
    return !shafts || !lamp_wind.shafts_failed;
}
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''    if (FILENAME MATCHES "^volumetric_light|^wind_noise")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl)
    endif()
''', r'''    if (FILENAME MATCHES "^volumetric_light|^wind_noise")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl)
    endif()
    # bbport (r88_wind-lamp-fog): and the lamp fog's WIND builds, with the wind words' layout.
    if (FILENAME MATCHES "^point_volumetric")
        list(APPEND INCLUDES ${SHADER_SRC}/wind_noise.glsl ${SHADER_SRC}/lamp_wind_layout.h)
    endif()
'''),
        (r'''add_host_shader(point_volumetric.comp point_volumetric_shafts_view_comp SHAFTS=1 VIEW=1)
''', r'''add_host_shader(point_volumetric.comp point_volumetric_shafts_view_comp SHAFTS=1 VIEW=1)
# bbport (r88_wind-lamp-fog): BB_WIND=1 with BB_WIND_LAMP_FOG above 0 only (made at the first lamp
# fog that drifts): the lamp fog with the wind's fog density, plain and with r80's shadow maps;
# the builds above are unchanged
add_host_shader(point_volumetric.comp point_volumetric_wind_comp WIND=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_wind_comp SHAFTS=1 WIND=1)
add_host_shader(point_volumetric.comp point_volumetric_shafts_view_wind_comp SHAFTS=1 VIEW=1 WIND=1)
'''),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        # anchored on r80's lamp fog lines, not on r82's wind view lines, after which r94_fog-noise
        # (pending) inserts its own
        (r'''#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
''', r'''#include "video_core/host_shaders/point_volumetric_shafts_view_comp.h"
// bbport (r88_wind-lamp-fog): the lamp fog's BB_WIND=1 builds
#include "video_core/host_shaders/point_volumetric_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_wind_comp.h"
#include "video_core/host_shaders/point_volumetric_shafts_view_wind_comp.h"
'''),
        (r'''        {"point volumetric (shafts view)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
''', r'''        {"point volumetric (shafts view)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
        // bbport (r88_wind-lamp-fog): as VolumetricLight::LampWindPasses makes them: the bindings
        // and push sizes of the plain lamp fog and of r80's shafts builds
        {"point volumetric (wind)",
         POINT_VOLUMETRIC_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage},
         12},
        {"point volumetric (shafts, wind)",
         POINT_VOLUMETRIC_SHAFTS_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
        {"point volumetric (shafts view, wind)",
         POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eStorageImage,
          eCombinedImageSampler},
         20},
'''),
    ],
    "README.md": [
        (r'''The lamp fog does not drift yet. ''',
         r'''The lamp fog (`effect_point_fog`) drifts with the same noise (`BB_WIND_LAMP_FOG`). '''),
        # anchored on the start of r82's BB_WIND_VIEW row (the row after BB_WIND_FOG), not on the
        # BB_WIND_FOG row, which r94_fog-noise (pending) rewrites
        (r'''| `BB_WIND_VIEW` | Debug only: ''', r'''| `BB_WIND_LAMP_FOG` | Strength of the drift in the lamp fog (`effect_point_fog`: the glow around lamps, torches and the hand lantern), 0 to 2. The lamp fog's density is multiplied by the same m as the sun fog's (the same noise at the same world points, so both drift together), with C = 1.5 times this strength: a glow is smaller than the noise's 4.5 m and 12 m cells, so it needs more contrast than the sun fog to show (a CPU estimate: a 6 m glow's light at a pixel varies over time by 20% at C = 1.5, 13% at C = 1). At 2 (C = 3) a glow has holes where N < 1/3. m is taken once for each half of a lamp's chord along the view ray, at the point that splits that half's inverse-square light in two (its window and the fade with distance left out of that split), so 2 noise samples per lamp a pixel; the lamp fog's fade with distance stays. `0` is the lamp fog's pass without wind. With `BB_LAMP_FOG_SHAFTS` both apply. The log says once whether it drifts and, at the 120th lamp fog frame and every 600th after, how many lamp fog frames drifted (`Wind lamp fog (r88)`). Cost: an estimate of 0.05 to 0.3 ms at 1080p internal, growing with the number of lamp glows over a pixel, about four times that at 2160p internal, not measured; read it on the `Lighting: lamp fog` row of `BB_GPU_PROFILE=1` | `1` |
| `BB_WIND_VIEW` | Debug only: '''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "point_volumetric.comp": [("#ifdef WIND\n", 6), ('#include "wind_noise.glsl"', 1),
                                  ("#extension GL_GOOGLE_include_directive : require", 1),
                                  ("lamp_wind(ray, along, q, begin, end);", 2),
                                  ("energy *= lamp_wind(", 1), ("segment *= wind_m;", 1),
                                  ('#include "lamp_wind_layout.h"', 1),
                                  ("wind_row0 = row(LAMP_WIND_AT);", 1),
                                  ("wind_off2 = row(LAMP_WIND_AT + 4u * LAMP_WIND_ROW);", 1),
                                  ("row(16u)", 0), ("row(32u)", 0),
                                  # the plain lines stay as they were (r80's and before)
                                  ("energy += (angle - previous) * window * window * exp(-0.025 * t);", 1),
                                  ("    return energy * 0.025;\n", 1), ("    return energy;\n", 1),
                                  ("float lit = inscatterShadowed(", 1)],
    H + "wind_noise.glsl": [("point_volumetric.comp (WIND", 1)],
    "engine/gpu/shim/bbport_wind.h": [("inline constexpr float DefaultLampFog = 1.0f, MaxLampFog = 2.0f, LampFogGain = 1.5f;", 1),
                                      ("inline float SanitizeLampFog(", 1), ("inline float LampFogContrast(", 1)],
    "engine/tests/test_wind.cpp": [("SanitizeLampFog(", 5), ("LampFogContrast(MaxLampFog)", 5),
                                   ("double lamp = 0.0;", 1), ("lamp /= count;", 1)],
    R + "vk_volumetric_light.h": [("bool LampWindPasses(bool shafts, u32 level);", 1),
                                  ("bool LampWindDrift(u32 lights);", 1),
                                  ("Pass point_wind, point_shafts_wind;", 1), ("} lamp_wind;", 1)],
    R + "vk_volumetric_light.cpp": [("POINT_VOLUMETRIC_WIND_COMP", 1),
                                    ("POINT_VOLUMETRIC_SHAFTS_WIND_COMP", 1),
                                    ("POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP", 1),
                                    ('std::getenv("BB_WIND_LAMP_FOG")', 1),
                                    ('#include "../host_shaders/lamp_wind_layout.h"', 1),
                                    ("u32* const words = data.data() + LAMP_WIND_AT;", 1),
                                    ("static const float lamp_strength", 1),
                                    ("(lamp_strength > 0.0f)", 2),
                                    ("lamp_wind.drift = LampWindDrift(u32(lights.size()));", 1),
                                    ("const vk::DescriptorBufferInfo constants{buffer, 0, 64};", 0),
                                    ("constants{buffer, 0, lamp_wind.drift ? LampWindBytes : 64u};", 1),
                                    ("pipeline = *point.pipeline, layout = *point.layout]", 0),
                                    ("pipeline = *point_shafts.pipeline", 0),
                                    ("const bool shafts_drift =", 1), ("lamp_wind.wanted = true;", 1),
                                    # r82's SetWind and r80's RecordShafts stay as they were around it
                                    ("wind_fog.on = camera_valid && !wind_fog.failed;", 1),
                                    ('EffectPass::Mark(9, "lamp fog");', 2),
                                    ("RecordShafts(shaft_scene, params.count, params.intensity, params.glow_size,", 1),
                                    ("Wind lamp fog (r88", 8)],
    "engine/gpu/CMakeLists.txt": [(" WIND=1)", 7), ('if (FILENAME MATCHES "^point_volumetric")', 1),
                                  ("${SHADER_SRC}/lamp_wind_layout.h", 1),
                                  ("point_volumetric_wind_comp WIND=1)", 1),
                                  ("point_volumetric_shafts_wind_comp SHAFTS=1 WIND=1)", 1),
                                  ("point_volumetric_shafts_view_wind_comp SHAFTS=1 VIEW=1 WIND=1)", 1)],
    "engine/tests/test_effect_pipelines.cpp": [("POINT_VOLUMETRIC_WIND_COMP,", 1),
                                               ("POINT_VOLUMETRIC_SHAFTS_WIND_COMP,", 1),
                                               ("POINT_VOLUMETRIC_SHAFTS_VIEW_WIND_COMP,", 1)],
    "README.md": [("| `BB_WIND_LAMP_FOG` |", 1), ("The lamp fog does not drift yet.", 0),
                  ("drifts with the same noise (`BB_WIND_LAMP_FOG`)", 1), ("`Wind lamp fog (r88)`", 1)],
}

# README numbers tied to the header's constants (rule 10: defaults written twice).
HEADER = "engine/gpu/shim/bbport_wind.h"
TIES = [("DefaultLampFog = 1.0f", "| `BB_WIND_LAMP_FOG` |", "| `1` |"),
        ("MaxLampFog = 2.0f", "| `BB_WIND_LAMP_FOG` |", "0 to 2."),
        ("LampFogGain = 1.5f", "| `BB_WIND_LAMP_FOG` |", "C = 1.5 times this strength"),
        ("LampFogGain = 1.5f", "| `BB_WIND_LAMP_FOG` |", "At 2 (C = 3)")]

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    "engine/tests/test_effect_pipelines.cpp": ['point_volumetric_shafts_view_comp.h"',
                                               'point_volumetric_wind_comp.h"',
                                               'point_volumetric_shafts_view_wind_comp.h"',
                                               '{"point volumetric (shafts view)",',
                                               '{"point volumetric (wind)",',
                                               '{"point volumetric (shafts view, wind)",',
                                               '{"volumetric integrate (wind)",'],
    "README.md": ["| `BB_WIND` |", "The lamp fog (`effect_point_fog`) drifts with the same noise",
                  "| `BB_WIND_FOG` |", "| `BB_WIND_LAMP_FOG` |", "| `BB_WIND_VIEW` |"],
    H + "point_volumetric.comp": ["#extension GL_EXT_scalar_block_layout", "#extension GL_GOOGLE_include_directive",
                                  "layout(push_constant) uniform Params", "bool finite3(",
                                  '#include "wind_noise.glsl"', '#include "lamp_wind_layout.h"',
                                  "float lamp_wind(", "float inscatter(",
                                  "energy *= lamp_wind(", "return energy * 0.025;", "float inscatterShadowed(",
                                  "float wind_m = lamp_wind(", "float segment =", "segment *= wind_m;",
                                  "void main()", "vec3 scattering = vec3(0.0);", "wind_row0 = row(LAMP_WIND_AT);",
                                  "for (uint k = 0u; k < count; ++k)"],
    R + "vk_volumetric_light.cpp": ['#include "../host_shaders/lamp_wind_layout.h"',
                                    "constexpr u32 FogLightsAt = 256", "constexpr u32 LampWindAt = LAMP_WIND_AT * 4",
                                    "void VolumetricLight::RecordShafts(", "const bool shafts_drift =",
                                    'EffectPass::Mark(80, "lamp fog shafts", true);',
                                    "shafts_drift ? *point_shafts_wind.pipeline",
                                    "void VolumetricLight::RecordLampFog(",
                                    "lamp_wind.drift = LampWindDrift(", "constants{buffer, 0, lamp_wind.drift",
                                    "RecordShafts(shaft_scene,", "lamp_wind.drifted += lamp_wind.drift",
                                    "lamp_wind.drift ? *point_wind.pipeline",
                                    "void VolumetricLight::SetWind(", "lamp_wind.wanted = true;",
                                    "void VolumetricLight::WindFogCheck()",
                                    "bool VolumetricLight::LampWindDrift(", "bool VolumetricLight::LampWindPasses("],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")

def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i
    for const, row, value in TIES:
        line = [l for l in texts["README.md"].split("\n") if l.startswith(row)]
        if texts[HEADER].count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    for path, edits in EDITS.items():
        for old, new in edits:
            if not all(ord(c) < 128 for c in new) or "\r" in new:
                raise SystemExit("%s: edit text must be ASCII with LF in the script" % path)
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text or max(map(len, text.split("\n"))) > 100:
            raise SystemExit("%s: new file text must be ASCII with LF, lines <= 100" % path)
    # The layout header holds the numbers the shader and RecordLampFog share (rule 10).
    layout = NEW[H + "lamp_wind_layout.h"]
    for define in ("#define LAMP_WIND_AT 16u\n", "#define LAMP_WIND_ROW 4u\n", "#define LAMP_WIND_WORDS 20u\n"):
        if layout.count(define) != 1:
            raise SystemExit("layout check: lamp_wind_layout.h lacks %r" % define)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R88_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else:
            bad = [old.split("\n")[0][:70] for old, new in edits
                   if not (cur.count(new) == 1 or (cur.count(old) == 1 and cur.count(new) == 0))]
            raise SystemExit("%s: %d of %d edits applied, %d anchors found once; refused at: %s"
                             % (path, done, len(edits), todo, bad))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full): state = "clean"
        elif open(full, "rb").read() == new_bytes(text): state = "applied"
        else: raise SystemExit("%s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in edited:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in edited:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")

main()
