# r119_volumetric-clouds: FEATURE patch (clouds work, owner 2026-11-15 23:43: "Also i thought we would add
# volumetric clouds below the skybox?"; their order of 07:00: "Foliage sway and clouds. Fog and wind go by
# cloud direction."). Off by default behind BB_VOLUMETRIC_CLOUDS=1.
#
# What it does: a layer of ray marched clouds between the game's painted sky dome and the world, drawn only
# over sky pixels (depth 1; BB_VOLUMETRIC_CLOUDS_SKYZ lets a far view z count too). A slab of air (default 300 m
# thick, base 700 m above the world's y = 0: high enough that a 100 m cell of the noise reads as a cumulus
# field 7 degrees across overhead, low enough that the painted clouds stay the far backdrop, and above every
# camera height of the game's places) is marched along each sky pixel's view ray in 12 steps at HALF the
# scene's resolution (interleaved gradient noise jitter, changing each frame: the upscaler averages it, no
# history of its own), lit by the sun or moon direction the engine already finds for the sun shadows
# (VolumetricOcclusion::MakeSunLight: forward scattering bright rims toward the light, dark undersides),
# ambient from the painted sky's own colour behind each pixel (the mean of the sky pixels under a march pixel,
# 55% toward its grey) so the layer sits in the painting, thin and partial at the default (an opacity cap of
# 0.70 over the painted clouds), faded out toward the horizon (|ray y| 0.05 to 0.22) and beyond 5 to 10 km. A
# depth-aware (sky-aware) bilinear upsample lays it over the scene: no colour is taken from or put onto a pixel
# that is not sky.
#
# The same field as the cloud shadows (r105/r105b): the layer reads the shadows' noise (r94's lattice, the same
# three octaves, weights, size, edges) at a plane coordinate q = p.xz - slope x Href that lines up with the
# shadow mask's q = g.xz - g.y slope for the ground point g under the light ray of the layer point, with the
# SAME drift state (CloudShadow::ClockState / ClockKnobs, two one-line getters this patch adds to
# vk_cloud_shadow.h) while BB_CLOUD_SHADOWS is on, so heading, speed and offsets are the same objects; with the
# shadows off the layer steps a clock of its own made from the same variables. The wind's "clouds" follower line
# (r116) gets the layer's heading and speed in that case. Details and the proof in cloud_layer_params.h and
# tests/test_cloud_layer.cpp.
#
# Where in the frame: Rasterizer::EffectsBeforeUpscaler at the upscaler's trigger dispatch, on
# upscaler->SceneColor() (RGBA16F, linear light before exposure and tone curve) and camera_motion->Depth()
# (D32, 1 = far), after the sky dome, the opaque world and the drawn look, right before the volumetric fog
# composite (so fog and haze lie over the clouds), the tonemap and the upscaler; the HUD is drawn later and never
# touched. Reads: scene colour (sky tint), depth. Writes: scene colour of sky pixels only.
#
# Off (BB_VOLUMETRIC_CLOUDS unset): CloudLayer::Wanted() is false, so Rasterizer makes no CloudLayer: no
# pipeline, no image, no buffer, no pass; the three hooks (the sun light, the frame end, the upscaler's trigger)
# are `if (cloud_layer)` null pointer tests; no shader of the tree changes (two new builds of a new file; the 26
# volumetric_light builds, cloud_shadow and every other build stay byte-identical, nothing of them is edited).
# On: two pipelines and three small buffers at the start, the march image (8 bytes a march pixel: 4.1 MB at a
# 1920x1080 scene) at the first frame that draws. The knob can be switched off and on in a running game with the
# test tools' live knobs (set:/unset: slot actions); a layer not made at the start cannot be switched on.
#
# Files: new renderer_vulkan/cloud_layer_params.h, vk_cloud_layer.h, vk_cloud_layer.cpp; host_shaders/
# cloud_layer.comp (MARCH and COMPOSITE builds), cloud_layer_layout.h; tests/test_cloud_layer.cpp. Hook lines:
# vk_cloud_shadow.h (two getters), vk_rasterizer.h (include, member), vk_rasterizer.cpp (construction),
# vk_rasterizer_effects.cpp (the light, the frame end, the upscaler's trigger), CMakeLists.txt (the shader's
# includes, the two builds, the test target), build.sh (the test), test_effect_pipelines.cpp (the two passes'
# descriptor lists), README.md (a section before Halation).
#
# Use: python -I -X utf8 r119_volumetric-clouds.py check | apply | revert
# Root: R119_ROOT, else <tree>. Line ends kept (CRLF in the tree; new files are written CRLF). apply backs
# the originals up in r119_backup next to this script; revert takes out exactly this patch's blocks (each found
# by itself, so patches applied later next to them stay) and removes the new files. check applied also ties the
# README's numbers to the header's constants, the shader's constants to the header's, and the cloud field's
# octave terms to cloud_shadow.comp's (rule 10: tied by a check, not by a comment).
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119_backup")
ROOT = os.environ.get("R119_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
PARAMS = R + "cloud_layer_params.h"
SHADER = H + "cloud_layer.comp"
SHADOW_SHADER = H + "cloud_shadow.comp"
LAYOUT_NEW = H + "cloud_layer_layout.h"
SHADOW_PARAMS = R + "cloud_shadow_params.h"
LAYOUT = H + "fog_noise_layout.h"
TMP = ".r119tmp"

NEW = {
    R+"cloud_layer_params.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r119_volumetric-clouds): FEATURE. A layer of ray marched clouds in front of the painted
// sky dome (BB_VOLUMETRIC_CLOUDS=1): the knobs, the slab, the cloud field's CPU twin and the words
// of host_shaders/cloud_layer.comp. Pure: no Vulkan, no settings, no environment
// (vk_cloud_layer.cpp reads the variables once and passes their text to MakeKnobs). Tested by
// tests/test_cloud_layer.cpp. The numbers the shader shares are host_shaders/cloud_layer_layout.h's
// (and r94's fog_noise_layout.h for the noise).
//
// The layer is the cloud shadows' field (cloud_shadow_params.h, r105b) seen from below. The shadow
// mask reads, for a world point p, n at the plane coordinate q = p.xz - p.y slope (Plane), slope =
// L.xz / max(L.y, 0.1), L the direction toward the sun or moon; it is the cloud pattern as it
// lies on the ground, carried along the light. The layer reads the same n (the same three octaves
// of value noise on r94's lattice, the same drift offsets of the cloud shadows' State, the same
// size and edges) at q = p.xz - slope Href, p a point of the slab and Href its reference height
// (the mass of the cloud sits there, RefFraction of the way up). The ground point g and the point
// of the slab's reference plane straight up its light ray, c = g + (slope.x (Href - g.y), Href -
// g.y, slope.y (Href - g.y)), have the same q, so the cloud over c is the cloud whose shadow falls
// on g: tests/test_cloud_layer.cpp checks that Density at c and the shadow's Light at g are the
// same n. A cloud's top and bottom, off the reference height, would cast their shadow along the
// light from the mask's place by slope x the height above or below Href: the top of a full cloud
// (195 m above Href at the defaults) 2.5 x 195 = about 480 m with the light 22 degrees up, the
// top of a thin cloud (near Href) hardly at all.
//
// A column's cloud fills the slab from its flat base up to the fraction 0.35 + 0.65 c of it
// (c = smoothstep(low, high, n), the cloud shadows' own cover) with a rounded top, so small c gives
// low flat puffs and a full cloud the whole slab. The density inside is Sigma x c x h(v), v the
// height in the cloud (0 base, 1 top), h = smoothstep(0, 0.15, v) (1 - smoothstep(0.55, 1, v)).
// Sigma = SigmaScale / thickness x density, so a full column straight up has an optical depth of
// about 2.8 x density; the opacity is then capped (OpacityCap) so that the painted sky shows
// through at the default.
//
// Cover (BB_VOLUMETRIC_CLOUDS_COVER, 0.5 = the shadows' own edges, so the layer and the shadows
// agree) moves both edges of n by (0.5 - cover) CoverShift: more cover, wider clouds than the
// shadows show.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "cloud_shadow_params.h"
#include "../host_shaders/cloud_layer_layout.h"

namespace CloudLayerParams {

inline constexpr float DefaultCover = 0.5f;
inline constexpr float DefaultDensity = 1.0f;
inline constexpr float MinDensity = 0.05f, MaxDensity = 4.0f;  ///< BB_VOLUMETRIC_CLOUDS_DENSITY's clamp
inline constexpr float DefaultHeight = 700.0f;                  ///< m: the slab's base (world y)
inline constexpr float MinHeight = 150.0f, MaxHeight = 3000.0f; ///< BB_VOLUMETRIC_CLOUDS_HEIGHT's clamp
inline constexpr float DefaultThick = 300.0f;                   ///< m: the slab's thickness
inline constexpr float MinThick = 60.0f, MaxThick = 1000.0f;    ///< BB_VOLUMETRIC_CLOUDS_THICK's clamp
inline constexpr int DefaultSteps = 12;
inline constexpr int MinSteps = 6, MaxSteps = 32;               ///< BB_VOLUMETRIC_CLOUDS_STEPS's clamp
inline constexpr float MaxSkyZ = 100000.0f;                     ///< BB_VOLUMETRIC_CLOUDS_SKYZ's clamp
inline constexpr float CoverShift = 0.30f;   ///< n's edges move by (DefaultCover - cover) x this
inline constexpr float RefFraction = 0.35f;  ///< the reference height: base + thickness x this
inline constexpr float TopBase = 0.35f, TopCover = 0.65f; ///< a column's top: TopBase + TopCover c
inline constexpr float SigmaScale = 4.0f;    ///< sigma = SigmaScale / thickness x density (1/m)
inline constexpr float OpacityCap = 0.70f;   ///< the most opacity a ray's cloud gives
inline constexpr float HorizonFrom = 0.05f, HorizonTo = 0.22f; ///< |ray y| the clouds fade in over
inline constexpr float FadeFrom = 5000.0f, FadeTo = 10000.0f;  ///< m: the slab entry's distance fade
inline constexpr float MaxT = 12000.0f;      ///< m: no cloud is marched beyond this distance
inline constexpr float MaxChord = 3000.0f;   ///< m: the longest stretch of a ray marched in the slab
inline constexpr float Ambient = 0.80f;      ///< the sky's brightness x this at a cloud's top (0.4 of it at its base)
inline constexpr float LightGain = 1.0f;     ///< the lit share of a sample x this (x the phase)
inline constexpr float Desaturate = 0.55f;   ///< the sky's tint toward its grey
inline constexpr float Forward = 2.0f;       ///< the forward scatter's gain (phase: 0.45 + this x cos^6)
inline constexpr float LitFrom = -0.02f, LitTo = 0.30f; ///< L.y the light's share rises over
inline constexpr std::uint32_t FramesPeriod = 600; ///< the periodic log line
inline constexpr std::uint32_t FramesNoPlace = 300; ///< frames after which "never reached" is said

/// The layer's knobs (the environment, read once).
struct Knobs {
    bool on = false;
    float cover = DefaultCover;
    float density = DefaultDensity;
    float height = DefaultHeight;
    float thick = DefaultThick;
    int steps = DefaultSteps;
    float sky_z = 0.0f; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only
    bool show = false;
};

/// BB_VOLUMETRIC_CLOUDS: on when the text starts with 1.
inline bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1';
}

inline Knobs MakeKnobs(const char* on, const char* cover, const char* density, const char* height,
                       const char* show, const char* thick = nullptr, const char* steps = nullptr,
                       const char* sky_z = nullptr) {
    Knobs k;
    k.on = ParseOn(on);
    k.cover = std::clamp(CloudShadows::Number(cover, DefaultCover), 0.0f, 1.0f);
    k.density = std::clamp(CloudShadows::Number(density, DefaultDensity), MinDensity, MaxDensity);
    k.height = std::clamp(CloudShadows::Number(height, DefaultHeight), MinHeight, MaxHeight);
    k.thick = std::clamp(CloudShadows::Number(thick, DefaultThick), MinThick, MaxThick);
    k.steps = std::clamp(static_cast<int>(std::lround(CloudShadows::Number(steps, float(DefaultSteps)))),
                         MinSteps, MaxSteps);
    k.sky_z = std::clamp(CloudShadows::Number(sky_z, 0.0f), 0.0f, MaxSkyZ);
    k.show = show != nullptr && show[0] == '1';
    return k;
}

/// The shadow mask's edges (low, high) moved by the cover.
struct Edges {
    float low = 0.0f, high = 0.0f;
};

inline Edges CoverEdges(float low, float high, float cover) {
    const float shift = (DefaultCover - cover) * CoverShift;
    const float lo = std::clamp(low + shift, 0.02f, 0.97f);
    return {lo, std::min(std::max(high + shift, lo + 0.02f), 0.99f)};
}

/// The slab: base y, thickness, the reference height of the cloud's plane coordinate and sigma.
struct Slab {
    float base = DefaultHeight, thick = DefaultThick, reference = 0.0f, sigma = 0.0f;
    float Top() const {
        return base + thick;
    }
};

inline Slab MakeSlab(const Knobs& k) {
    return {k.height, k.thick, k.height + RefFraction * k.thick,
            SigmaScale / k.thick * k.density};
}

/// The distances (t0 < t1, t0 >= 0) of a ray from height cy with y slope dy inside base < y < top
/// (cloud_layer.comp's slab_range); false when it does not meet the slab.
inline bool SlabRange(float cy, float dy, float base, float top, float* t0, float* t1) {
    *t0 = 0.0f;
    *t1 = 0.0f;
    if (std::fabs(dy) < 1e-4f) {
        if (cy < base || cy > top) {
            return false;
        }
        *t1 = MaxT;
        return true;
    }
    const float ta = (base - cy) / dy, tb = (top - cy) / dy;
    *t0 = std::max(std::min(ta, tb), 0.0f);
    *t1 = std::max(ta, tb);
    return *t1 > *t0;
}

/// The light's share (0 without a light, rising to 1 as the light climbs from LitFrom to LitTo).
inline float LightShare(const std::array<float, 3>& light, bool valid) {
    if (!valid || !std::isfinite(light[1])) {
        return 0.0f;
    }
    const float t = std::clamp((light[1] - LitFrom) / (LitTo - LitFrom), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The view z (m) a depth gives (heat_haze.comp's ViewZOf without the sky shortcut).
inline float ViewZ(float depth, float z_scale, float z_offset) {
    return z_offset / std::min(depth - z_scale, -1e-8f);
}

/// cloud_layer.comp's is_sky.
inline bool IsSky(float depth, const std::array<float, 4>& proj, float sky_z) {
    return depth >= 1.0f || (sky_z > 0.0f && ViewZ(depth, proj[2], proj[3]) > sky_z);
}

// ---- the cloud field's CPU twin (fog_noise.glsl's value noise, cloud_layer.comp's cloud_n) ------

/// fog_noise.glsl's fog_noise_corner: lowbias32 of the packed cell plus the seed, in [0, 1).
inline float Corner(std::uint32_t packed) {
    std::uint32_t h = packed + FOG_NOISE_SEED;
    h ^= h >> 16u;
    h *= 0x7feb352du;
    h ^= h >> 15u;
    h *= 0x846ca68bu;
    h ^= h >> 16u;
    return float(h >> 8u) * (1.0f / 16777216.0f);
}

/// fog_noise.glsl's fog_noise_value: 3D value noise in [0, 1) with the quintic fade, repeating
/// every FOG_NOISE_PERIOD cells.
inline float Value(const std::array<float, 3>& x) {
    std::array<std::uint32_t, 3> a{}, b{};
    std::array<float, 3> u{};
    for (std::size_t i = 0; i < 3; ++i) {
        const float f = std::floor(x[i]);
        const float t = x[i] - f;
        u[i] = t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
        a[i] = static_cast<std::uint32_t>(static_cast<std::int32_t>(f) & (FOG_NOISE_PERIOD - 1));
        b[i] = (a[i] + 1u) & static_cast<std::uint32_t>(FOG_NOISE_PERIOD - 1);
    }
    const auto mix = [](float p, float q, float t) { return p * (1.0f - t) + q * t; };
    const std::uint32_t y0 = a[1] << 8u, y1 = b[1] << 8u, z0 = a[2] << 16u, z1 = b[2] << 16u;
    const float x00 = mix(Corner(a[0] | y0 | z0), Corner(b[0] | y0 | z0), u[0]);
    const float x10 = mix(Corner(a[0] | y1 | z0), Corner(b[0] | y1 | z0), u[0]);
    const float x01 = mix(Corner(a[0] | y0 | z1), Corner(b[0] | y0 | z1), u[0]);
    const float x11 = mix(Corner(a[0] | y1 | z1), Corner(b[0] | y1 | z1), u[0]);
    return mix(mix(x00, x10, u[1]), mix(x01, x11, u[1]), u[2]);
}

using Offsets = std::array<std::array<float, 3>, 3>; ///< the octaves' offsets in lattice cells

/// The three octaves' offsets of the cloud shadows' drift (State::Offsets().Cells).
inline Offsets OffsetsOf(const VolumetricFogNoise::Drift& drift) {
    return {drift.Cells(0), drift.Cells(1), drift.Cells(2)};
}

/// fog_noise.glsl's fog_noise_cells: the lattice coordinate x turned by the octave's yaw about the
/// up axis and divided by its ratio.
inline std::array<float, 3> Cells(const std::array<float, 3>& x, std::size_t octave) {
    const float c = VolumetricFogNoise::YawCos[octave], s = VolumetricFogNoise::YawSin[octave];
    const float r = VolumetricFogNoise::Ratio[octave];
    return {(c * x[0] - s * x[2]) / r, x[1] / r, (s * x[0] + c * x[2]) / r};
}

/// cloud_layer.comp's cloud_n (and, with every lod 1, the term sum of cloud_shadow.comp's
/// cloud_light): n at the lattice coordinate x = (q.x, 0, q.y) / size; lod fades an octave toward
/// its mean (0: the octave is left out).
inline float FieldN(const std::array<float, 3>& x, const Offsets& offsets,
                    const std::array<float, 3>& lod = {1.0f, 1.0f, 1.0f}) {
    float n = 0.5f;
    for (std::size_t k = 0; k < 3; ++k) {
        if (k > 0 && !(lod[k] > 0.0f)) {
            continue;
        }
        std::array<float, 3> cell = Cells(x, k);
        for (std::size_t i = 0; i < 3; ++i) {
            cell[i] -= offsets[k][i];
        }
        n += VolumetricFogNoise::Weight[k] * lod[k] * (Value(cell) - 0.5f);
    }
    return n;
}

inline float Smoothstep(float low, float high, float v) {
    const float t = std::clamp((v - low) / (high - low), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// What the density at a point needs: the noise's offsets, 1 / size, the edges, the cloud shadows'
/// slope and the slab.
struct Field {
    Offsets offsets{};
    float inv_size = 0.01f;
    Edges edges{CloudShadows::Low, CloudShadows::High};
    std::array<float, 2> slope{};
    Slab slab{};
};

/// The layer's plane coordinate of world point p: p.xz - slope x the reference height.
inline std::array<float, 2> LayerPlane(const Field& f, const std::array<float, 3>& p) {
    return {p[0] - f.slope[0] * f.slab.reference, p[2] - f.slope[1] * f.slab.reference};
}

/// The cloud cover c = smoothstep(low, high, n) at plane coordinate q (m).
inline float Cover(const Field& f, const std::array<float, 2>& q,
                   const std::array<float, 3>& lod = {1.0f, 1.0f, 1.0f}) {
    const std::array<float, 3> x{q[0] * f.inv_size, 0.0f, q[1] * f.inv_size};
    return Smoothstep(f.edges.low, f.edges.high, FieldN(x, f.offsets, lod));
}

/// cloud_layer.comp's density_at: the density (1/m) at world point p, and in *v the height in the
/// cloud (0 base, 1 top); 0 outside the slab and above a column's top.
inline float Density(const Field& f, const std::array<float, 3>& p, float* v,
                     const std::array<float, 3>& lod = {1.0f, 1.0f, 1.0f}) {
    *v = 0.0f;
    const float u = (p[1] - f.slab.base) / f.slab.thick;
    if (u <= 0.0f || u >= 1.0f) {
        return 0.0f;
    }
    const float c = Cover(f, LayerPlane(f, p), lod);
    if (c <= 0.0f) {
        return 0.0f;
    }
    *v = u / (TopBase + TopCover * c);
    if (*v >= 1.0f) {
        return 0.0f;
    }
    const float h = Smoothstep(0.0f, 0.15f, *v) * (1.0f - Smoothstep(0.55f, 1.0f, *v));
    return f.slab.sigma * c * h;
}

/// The cloud shadows' own cover at ground point g (what cloud_shadow.comp's cloud_light dims by:
/// (1 - Light) / depth): smoothstep(low, high, n) at Plane(g), the plane coordinate q = g.xz - g.y
/// slope.
inline float ShadowCover(const Field& f, const std::array<float, 3>& g) {
    return Cover(f, CloudShadows::Plane(g, f.slope));
}

/// The point of the layer's reference plane straight up the light ray of ground point g (along
/// the sloped direction Slope gives): the cloud over it casts its shadow on g.
inline std::array<float, 3> CloudOver(const Field& f, const std::array<float, 3>& g) {
    const float h = f.slab.reference - g[1];
    return {g[0] + f.slope[0] * h, f.slab.reference, g[2] + f.slope[1] * h};
}

// ---- the Params block -----------------------------------------------------------------------

/// cloud_layer.comp's Params block: 13 vec4, field for field.
struct Params {
    std::array<float, 4> row0{}, row1{}, row2{}; ///< view to world rows; the camera in w
    std::array<float, 4> proj{};                 ///< x scale, y scale, z scale, z offset
    std::array<float, 4> off0{};                 ///< xyz: octave 0's offset; w: 1 / size
    std::array<float, 4> off1{};                 ///< xyz: octave 1's offset; w: low edge
    std::array<float, 4> off2{};                 ///< xyz: octave 2's offset; w: high edge
    std::array<float, 4> light{};                ///< xyz: toward the light; w: its share
    std::array<float, 4> slab{};                 ///< base, thickness, reference height, sigma
    std::array<float, 4> plane{};                ///< slope xy; the jitter xy
    std::array<float, 4> look{};                 ///< steps, opacity cap, horizon from, to
    std::array<float, 4> dist{};                 ///< fade from, to (m); sky view z; unused
    std::array<float, 4> tone{};                 ///< ambient, light, desaturation, forward
};
static_assert(sizeof(Params) == 13 * 16 && offsetof(Params, off0) == 64 &&
                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192,
              "cloud_layer.comp's Params block: 13 vec4");

/// The push constants (16 bytes): the scene's size, the frame, the flags.
struct Push {
    std::uint32_t width = 0, height = 0;
    std::uint32_t frame = 0;
    std::uint32_t flags = 0;
};
static_assert(sizeof(Push) == 16);

/// The counter words (cloud_layer_layout.h).
inline constexpr std::uint32_t CounterWords = CL_WORDS;
static_assert(CL_WORD_STEPS < CL_WORDS && CL_DIV == 2 && CL_WG == 8 && CL_FLAG_SHOW == 1);

/// The block for one frame. `inv_view`: the camera's view to world rows (3x4, translation in [3],
/// [7], [11]); `proj`: x scale, y scale (signed), z scale, z offset; `state` and `shadow`: the
/// cloud shadows' State and Knobs (the drift, size and edges); `slope`: Slope(L) of the last light
/// seen; `jitter`: the viewport's shift this frame in pixels.
inline Params MakeParams(const std::array<float, 12>& inv_view, const std::array<float, 4>& proj,
                         const CloudShadows::State& state, const CloudShadows::Knobs& shadow,
                         const Knobs& knobs, const std::array<float, 3>& light, bool light_valid,
                         const std::array<float, 2>& slope, const std::array<float, 2>& jitter) {
    Params p;
    p.row0 = {inv_view[0], inv_view[1], inv_view[2], inv_view[3]};
    p.row1 = {inv_view[4], inv_view[5], inv_view[6], inv_view[7]};
    p.row2 = {inv_view[8], inv_view[9], inv_view[10], inv_view[11]};
    p.proj = proj;
    const Edges edges = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), knobs.cover);
    const auto c0 = state.Offsets().Cells(0), c1 = state.Offsets().Cells(1),
               c2 = state.Offsets().Cells(2);
    p.off0 = {c0[0], c0[1], c0[2], 1.0f / shadow.scale};
    p.off1 = {c1[0], c1[1], c1[2], edges.low};
    p.off2 = {c2[0], c2[1], c2[2], edges.high};
    p.light = {light_valid ? light[0] : 0.0f, light_valid ? light[1] : 1.0f,
               light_valid ? light[2] : 0.0f, LightShare(light, light_valid)};
    const Slab slab = MakeSlab(knobs);
    p.slab = {slab.base, slab.thick, slab.reference, slab.sigma};
    p.plane = {slope[0], slope[1], jitter[0], jitter[1]};
    p.look = {float(knobs.steps), OpacityCap, HorizonFrom, HorizonTo};
    p.dist = {FadeFrom, FadeTo, knobs.sky_z, 0.0f};
    p.tone = {Ambient, LightGain, Desaturate, Forward};
    return p;
}

// ---- the log ----------------------------------------------------------------------------------

/// The counter words summed over the frames of one log period.
struct Totals {
    std::array<std::uint64_t, CL_WORDS> words{};
    std::uint64_t frames = 0; ///< frames whose counters were added
    void Add(const std::array<std::uint32_t, CL_WORDS>& frame_words) {
        for (std::size_t i = 0; i < words.size(); ++i) {
            words[i] += frame_words[i];
        }
        ++frames;
    }
};

struct Shares {
    double sky = 0.0;     ///< march pixels with sky under them / all march pixels
    double covered = 0.0; ///< sky pixels with an opacity of 1/64 or more / sky pixels
    double opacity = 0.0; ///< the mean opacity over the sky pixels
    double steps = 0.0;   ///< march steps a marched sky pixel took, on average
};

inline Shares SharesOf(const Totals& t) {
    Shares s;
    const double total = double(t.words[CL_WORD_TOTAL]), sky = double(t.words[CL_WORD_SKY]),
                 hit = double(t.words[CL_WORD_HIT]);
    s.sky = total > 0.0 ? sky / total : 0.0;
    s.covered = sky > 0.0 ? double(t.words[CL_WORD_COVERED]) / sky : 0.0;
    s.opacity = sky > 0.0 ? double(t.words[CL_WORD_OPACITY]) / (256.0 * sky) : 0.0;
    s.steps = hit > 0.0 ? double(t.words[CL_WORD_STEPS]) / hit : 0.0;
    return s;
}

} // namespace CloudLayerParams
''',
    R+"vk_cloud_layer.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): FEATURE. A layer of ray marched clouds in front of the painted
// sky dome (BB_VOLUMETRIC_CLOUDS=1; cloud_layer_params.h has the knobs, the slab and the rules,
// host_shaders/cloud_layer.comp the two passes).
//
// What it is: the game paints its sky as one dome with a painted panorama (r104 probe: no time input,
// no cloud layer), so this adds a layer of real clouds between that dome and the world: a slab of
// air (by default 700 to 1000 m above the world's y = 0) marched along the view ray of every sky
// pixel, lit by the sun or moon direction the engine already finds for the sun shadows
// (VolumetricOcclusion::MakeSunLight), tinted by the painted sky behind the pixel, drifting with the
// cloud shadows' own clock. The density is the cloud shadows' field (r105b): the same noise, the
// same offsets, size, edges and direction, so a shadow sweeping the ground belongs to a cloud
// overhead (cloud_layer_params.h says how the two planes line up).
//
// Where in the frame: Rasterizer::EffectsBeforeUpscaler, at the upscaler's trigger dispatch, on the
// scene colour (RGBA16F, linear light before the game's exposure and tone curve) and the scene's
// depth (D32, 1 = far), after the sky dome and the opaque world and the drawn look, before the
// volumetric fog composite (so the fog and its haze lie over the clouds), the tonemap and the
// upscaler; the HUD is drawn later and never touched. Reads: the scene colour (the sky pixels'
// tint), the depth. Writes: the scene colour of the sky pixels only (a pixel that is not sky,
// depth below 1, is never written; BB_VOLUMETRIC_CLOUDS_SKYZ lets a far view z count as sky too).
//
// The passes: MARCH at 1 / CL_DIV of the scene a side (RGBA16F image, premultiplied colour and
// opacity; a pixel with no sky under it is marked), COMPOSITE at the scene's size (a bilinear
// filter over the march pixels that have sky under them, so no colour leaks across a silhouette).
// The march jitter is interleaved gradient noise that changes each frame: the upscaler averages
// it; there is no history of its own. Without the upscaler (BB_UPSCALER=none, or a GPU it cannot
// run on) that place is never reached and nothing is drawn (said after 300 frames).
//
// Off unless BB_VOLUMETRIC_CLOUDS starts with 1 (environment, read at the start; with the test tools'
// live knobs file (gpu/shim/bbport_live_knobs.h) it can be switched off and on again while the game
// runs, for an exact twin in one game; a layer not made at the start cannot be switched on). Off, the rasterizer
// makes no CloudLayer (Wanted), so there is no pipeline, no image, no buffer and no pass, and each
// of its three hooks is one null pointer test. On: two pipelines and three small buffers at the
// start; the march image (8 bytes a march pixel: 4.1 MB at a 1920x1080 scene) at the first frame
// that draws, and again when the scene's size changes.
//
// The clock: while the cloud shadows are on (BB_CLOUD_SHADOWS above 0, or SHOW) the layer reads
// THEIR knobs and state (CloudShadow::ClockKnobs / ClockState) so offsets, heading and speed are the
// same objects; else it keeps a clock of its own made from the same variables (BB_CLOUD_SHADOWS_SCALE,
// BB_CLOUDS_DIR, BB_WIND_DIR, BB_WIND_SPEED, and the wind's direction with BB_WIND=1).
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/cloud_layer_params.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class CloudShadow;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class CloudLayer {
public:
    /// BB_VOLUMETRIC_CLOUDS starts with 1 (read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once.
    CloudLayer(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
               Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion);
    ~CloudLayer();
    CloudLayer(const CloudLayer&) = delete;
    CloudLayer& operator=(const CloudLayer&) = delete;

    /// At each sun shadow resolve: the direction toward the light (world) and whether it is known.
    /// An unknown light leaves the last known one (the layer has no light of its own before one).
    void SetSunLight(const std::array<float, 3>& world, bool valid);
    /// Each frame end: the clock (when the cloud shadows are off), the counters and the log.
    void OnFrameEnd(bool wind_on, float wind_deg);
    /// The upscaler's trigger: the clouds into the sky pixels of `color` (the scene colour), `depth`
    /// the scene's depth, `jitter` the viewport's shift this frame (pixels).
    void Apply(VideoCore::ImageId color, VideoCore::ImageId depth, std::array<float, 2> jitter);
    /// The heading (deg) and speed (m/s) the clouds move at now.
    [[nodiscard]] float Direction() const;
    [[nodiscard]] float Velocity() const;
    /// The layer keeps a clock of its own (the cloud shadows are off).
    [[nodiscard]] bool OwnClock() const {
        return shared == nullptr;
    }

private:
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageAspectFlags aspect{};
        vk::ImageView view{};
        u64 last_use = 0;
    };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    vk::ImageView CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect);
    bool EnsureImage(u32 width, u32 height);
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    [[nodiscard]] const CloudShadows::State& ClockState() const;
    [[nodiscard]] const CloudShadows::Knobs& ClockKnobs() const;
    void Report();
    /// The knob now (a live knob with the test tools' header, else read once); says each change once.
    bool Active();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    const CloudLayerParams::Knobs knobs;
    CloudShadow* shared = nullptr;         ///< the cloud shadows' object when they are on
    CloudShadows::State own_state;         ///< the layer's clock when they are off
    double clock_last = -1.0;              ///< s (steady clock) at the last own step; below 0: none
    bool made = false;
    vk::UniqueDescriptorSetLayout march_set_layout, composite_set_layout;
    vk::UniquePipelineLayout march_layout, composite_layout;
    vk::UniquePipeline march_pipeline, composite_pipeline;
    VideoCore::UniqueImage cloud_image;
    vk::UniqueImageView cloud_view;
    u32 cloud_width = 0, cloud_height = 0;
    u32 refused_width = 0, refused_height = 0; ///< a march size the image found no room at
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    Buffer params_buffer, counter_buffer, counter_host;

    std::array<float, 3> light{};
    std::array<float, 2> slope{};
    bool light_known = false;
    u32 frame_index = 0;
    bool drew_this_frame = false;
    bool told_size = false;
    bool told_no_place = false;
    bool told_on = true; ///< what the live knob said last (the constructor's line says on)

    CloudLayerParams::Totals totals;
    /// The log period's frame counts.
    struct Stats {
        u32 frames = 0;     ///< frame ends
        u32 reached = 0;    ///< frames that reached the place before the upscaler
        u32 drawn = 0;      ///< frames with the passes recorded
        u32 no_camera = 0;  ///< reached, but no camera or a menu's preview
        u32 no_scene = 0;   ///< reached, but the scene colour or depth was not usable
        u32 no_memory = 0;  ///< reached, but no room for the march image
        float camera_y = 0.0f;
    } stats;
};

} // namespace Vulkan
''',
    R+"vk_cloud_layer.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): FEATURE, the volumetric cloud layer (vk_cloud_layer.h says what
// it is and where it runs; cloud_layer_params.h has the numbers, host_shaders/cloud_layer.comp the
// passes).

#include "video_core/renderer_vulkan/vk_cloud_layer.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_CLOUD_LAYER_LIVE 1
#else
#define BB_CLOUD_LAYER_LIVE 0
#endif
#include "video_core/host_shaders/cloud_layer_composite_comp.h"
#include "video_core/host_shaders/cloud_layer_march_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_cloud_shadow.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace CL = CloudLayerParams;

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageBuffer = vk::DescriptorType::eStorageBuffer;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
/// The GPU profile row (BB_GPU_PROFILE=1): "Lighting: volumetric clouds", both passes.
constexpr u64 ProfileRow = 119;

/// The layer's knobs, read once (the first caller: Wanted, at the rasterizer's start).
const CL::Knobs& Load() {
    static const CL::Knobs knobs = CL::MakeKnobs(
        std::getenv("BB_VOLUMETRIC_CLOUDS"), std::getenv("BB_VOLUMETRIC_CLOUDS_COVER"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_DENSITY"), std::getenv("BB_VOLUMETRIC_CLOUDS_HEIGHT"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_SHOW"), std::getenv("BB_VOLUMETRIC_CLOUDS_THICK"),
        std::getenv("BB_VOLUMETRIC_CLOUDS_STEPS"), std::getenv("BB_VOLUMETRIC_CLOUDS_SKYZ"));
    return knobs;
}

/// The clock's knobs when the cloud shadows are off: the same variables, read as their
/// CloudShadows::MakeKnobs reads them (strength 0: only the size, the direction and the wind count).
const CloudShadows::Knobs& OwnKnobs() {
    static const CloudShadows::Knobs knobs = CloudShadows::MakeKnobs(
        nullptr, std::getenv("BB_CLOUD_SHADOWS_SCALE"), nullptr, std::getenv("BB_CLOUDS_DIR"),
        std::getenv("BB_WIND_DIR"), std::getenv("BB_WIND_SPEED"));
    return knobs;
}

/// BB_VOLUMETRIC_CLOUDS now: asked again at every use with the live knobs, else the start's value.
bool LiveOn() {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<bool> on{"BB_VOLUMETRIC_CLOUDS", CL::ParseOn};
    return on.Get();
#else
    return Load().on;
#endif
}

double Seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}

vk::WriteDescriptorSet WriteBuffer(u32 binding, const vk::DescriptorBufferInfo* buffer) {
    return {.dstBinding = binding, .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = buffer};
}
} // namespace

bool CloudLayer::Wanted() {
    return Load().on;
}

CloudLayer::CloudLayer(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{Load()},
      shared{CloudShadow::Active()} {
    // The pipelines and the three small buffers are made here, at the start (no compile in play);
    // the march image at the first frame that draws, at that scene's size.
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, march_set_layout, march_layout, march_pipeline,
                              {StorageImage, StorageImage, SampledImage, StorageBuffer,
                               StorageBuffer},
                              sizeof(CL::Push), CLOUD_LAYER_MARCH_COMP, "Volumetric clouds march") &&
           EffectPass::Create(instance, composite_set_layout, composite_layout, composite_pipeline,
                              {StorageImage, StorageImage, SampledImage, StorageBuffer},
                              sizeof(CL::Push), CLOUD_LAYER_COMPOSITE_COMP,
                              "Volumetric clouds composite") &&
           MakeBuffer(params_buffer, sizeof(CL::Params), false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_buffer, CL::CounterWords * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferSrc |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_host, CL::CounterWords * 4, true,
                      vk::BufferUsageFlagBits::eTransferDst);
    if (made) {
        std::memset(counter_host.mapped, 0, CL::CounterWords * 4);
    }
    const CloudShadows::Knobs& clk = ClockKnobs();
    const CL::Slab slab = CL::MakeSlab(knobs);
    // under 300 characters (the slab runs keep that much of a line)
    BbReport::Printf("Volumetric clouds (r119, BB_VOLUMETRIC_CLOUDS=1): %s; slab %.0f-%.0f m, "
                     "cover %.2f, density %.2f, %d steps at 1/%d resolution, size %.0f m, %.1f m/s, "
                     "clock %s; drawn before the fog and the upscaler%s\n",
                     made ? "on" : "off - the passes could not be made", double(slab.base),
                     double(slab.Top()), double(knobs.cover), double(knobs.density), knobs.steps,
                     CL_DIV, double(clk.scale), double(clk.Velocity()),
                     shared ? "the cloud shadows'" : "its own (cloud shadows off)",
                     knobs.show ? "; SHOW" : "");
}

CloudLayer::~CloudLayer() {
    const auto device = instance.GetDevice();
    FreeBuffer(params_buffer);
    FreeBuffer(counter_buffer);
    FreeBuffer(counter_host);
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool CloudLayer::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void CloudLayer::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}


const CloudShadows::State& CloudLayer::ClockState() const {
    return shared ? shared->ClockState() : own_state;
}

const CloudShadows::Knobs& CloudLayer::ClockKnobs() const {
    return shared ? shared->ClockKnobs() : OwnKnobs();
}

float CloudLayer::Direction() const {
    return ClockState().Direction();
}

float CloudLayer::Velocity() const {
    return ClockKnobs().Velocity();
}

bool CloudLayer::Active() {
    const bool on = LiveOn();
    if (on != told_on) {
        told_on = on;
        std::printf("Volumetric clouds (r119): %s (BB_VOLUMETRIC_CLOUDS, a live knob)\n",
                    on ? "on again" : "off");
    }
    return on;
}

void CloudLayer::SetSunLight(const std::array<float, 3>& world, bool valid) {
    if (!valid || !std::isfinite(world[0]) || !std::isfinite(world[1]) ||
        !std::isfinite(world[2])) {
        return;
    }
    light = world;
    slope = CloudShadows::Slope(world);
    light_known = true;
}

vk::ImageView CloudLayer::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create cloud layer view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool CloudLayer::EnsureImage(u32 width, u32 height) {
    if (cloud_image && cloud_width == width && cloud_height == height) {
        return true;
    }
    if (width == refused_width && height == refused_height) {
        return false;
    }
    const vk::DeviceSize bytes = 8ull * width * height;
    if (!EffectPass::HasRoom(instance, bytes)) {
        refused_width = width;
        refused_height = height;
        std::printf("Volumetric clouds (r119): no room in video memory for its march image of "
                    "%ux%u (%llu bytes); asked again when the scene's size changes\n",
                    width, height, static_cast<unsigned long long>(bytes));
        return false;
    }
    refused_width = refused_height = 0;
    if (cloud_image) {
        scheduler.DeferOperation(
            [image = std::move(cloud_image), view = std::move(cloud_view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    cloud_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    cloud_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(cloud_image), "Volumetric clouds march image");
    cloud_view = Check<"create cloud layer march view">(device.createImageViewUnique({
        .image = vk::Image(cloud_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = ColorRange,
    }));
    cloud_width = width;
    cloud_height = height;
    std::printf("Volumetric clouds (r119): march image %ux%u RGBA16F (%llu bytes), 1/%d of a scene "
                "of %ux%u\n",
                width, height, static_cast<unsigned long long>(bytes), CL_DIV, width * CL_DIV,
                height * CL_DIV);
    return true;
}

void CloudLayer::OnFrameEnd(bool wind_on, float wind_deg) {
    if (!shared) {
        // The layer's own clock, stepped as CloudShadow::OnFrameEnd steps the cloud shadows' (the
        // same variables, so the same heading, speed and drift; the offsets start at 0 here).
        const double now = Seconds();
        const double seconds = clock_last < 0.0 ? 0.0 : now - clock_last;
        clock_last = now;
        own_state.Advance(OwnKnobs(), wind_on, wind_deg, light_known, light, seconds);
    }
    if (!Active()) {
        drew_this_frame = false;
        return;
    }
    ++stats.frames;
    if (drew_this_frame && counter_host.mapped) {
        // The totals the GPU copied after the last passes that finished (a frame or two old; one
        // word is never torn): added once a frame the passes were recorded.
        std::array<u32, CL::CounterWords> words{};
        std::memcpy(words.data(), counter_host.mapped, sizeof(words));
        totals.Add(words);
    }
    drew_this_frame = false;
    if (!told_no_place && stats.reached == 0 && stats.frames >= CL::FramesNoPlace) {
        told_no_place = true;
        std::printf("Volumetric clouds (r119): not drawn - no frame reached the place before the "
                    "upscaler (BB_UPSCALER=none, or this GPU cannot run it)\n");
    }
    if (stats.frames >= CL::FramesPeriod) {
        Report();
    }
}

void CloudLayer::Report() {
    const CL::Shares s = CL::SharesOf(totals);
    const CloudShadows::State& state = ClockState();
    const CloudShadows::Knobs& clk = ClockKnobs();
    // two lines, each under 300 characters
    BbReport::Printf("Volumetric clouds (r119): sky px share %.3f, covered share %.3f, mean opacity "
                     "%.3f, march steps %.1f, heading %.0f deg, drift %.1f m/s (same as the cloud "
                     "shadows: %s)\n",
                     s.sky, s.covered, s.opacity, s.steps, double(state.Direction()),
                     double(clk.Velocity()),
                     shared ? "yes" : "no, they are off: the layer's own clock");
    const CL::Slab slab = CL::MakeSlab(knobs);
    BbReport::Printf("Volumetric clouds (r119): %u of %u frames drawn (%u reached the upscaler; %u "
                     "without a camera, %u without a usable scene, %u without memory), counters of "
                     "%llu frames, slab %.0f-%.0f m, camera y %.0f m, light %s%.0f deg up, "
                     "cover %.2f\n",
                     stats.drawn, stats.frames, stats.reached, stats.no_camera, stats.no_scene,
                     stats.no_memory, static_cast<unsigned long long>(totals.frames),
                     double(slab.base), double(slab.Top()), double(stats.camera_y),
                     light_known ? "" : "unknown, ",
                     light_known ? std::asin(std::clamp(double(light[1]), -1.0, 1.0)) *
                                       57.29577951308232
                                 : 0.0,
                     double(knobs.cover));
    stats = {};
    totals = {};
}

void CloudLayer::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                       std::array<float, 2> jitter) {
    if (!Active()) {
        return;
    }
    ++stats.reached;
    if (!made || !color_id || !depth_id) {
        ++stats.no_scene;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid) {
        ++stats.no_camera;
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.no_scene;
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        ++stats.no_scene;
        return;
    }
    const u32 march_width = (width + CL_DIV - 1) / CL_DIV;
    const u32 march_height = (height + CL_DIV - 1) / CL_DIV;
    if (!EnsureImage(march_width, march_height)) {
        ++stats.no_memory;
        return;
    }
    const SceneUseScope scene_use{"volumetric clouds"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
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
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // Every value is made before the capture list (nothing in it is moved).
    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, ClockState(),
                                             ClockKnobs(), knobs, light, light_known, slope, jitter);
    CL::Push push;
    push.width = width;
    push.height = height;
    push.frame = frame_index++;
    push.flags = knobs.show ? u32(CL_FLAG_SHOW) : 0u;
    stats.camera_y = camera.inv_view[7];
    ++stats.drawn;
    drew_this_frame = true;
    if (!told_size) {
        told_size = true;
        std::printf("Volumetric clouds (r119): first frame drawn at a scene of %ux%u (%s)\n", width,
                    height, reduced ? "reduced scene" : "the game's scene");
    }
    EffectPass::Mark(ProfileRow, "volumetric clouds");
    scheduler.RecordCrumb(
        {.name = "volumetric clouds"},
        [params, push, march_width, march_height, width, height, color_view, depth_view,
         cloud_handle = vk::Image(cloud_image), cloud_image_view = *cloud_view,
         pass_march = *march_pipeline, layout_march = *march_layout,
         pass_composite = *composite_pipeline, layout_composite = *composite_layout,
         block = params_buffer.buffer, counters = counter_buffer.buffer,
         host = counter_host.buffer](vk::CommandBuffer cmdbuf) {
            // the transfer stage waits too: last frame's copy of the counters and last frame's passes'
            // reads of the block come before this frame's clear and update of them
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute | vk::PipelineStageFlagBits2::eTransfer,
                                      ReadWrite | vk::AccessFlagBits2::eTransferWrite);
            // this frame's block, and the counters cleared (a transfer, then the passes read them)
            cmdbuf.updateBuffer(block, 0, sizeof(params), &params);
            cmdbuf.fillBuffer(counters, 0, CL::CounterWords * 4, 0);
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            // The march image is written anew where it is read; what it held before is of no use.
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = ReadWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = cloud_handle,
                .subresourceRange = ColorRange,
            };
            cmdbuf.pipelineBarrier2(
                {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            const std::array infos{Info(cloud_image_view), Info(color_view), Info(depth_view)};
            const vk::DescriptorBufferInfo block_info{block, 0, sizeof(CL::Params)};
            const vk::DescriptorBufferInfo counter_info{counters, 0, CL::CounterWords * 4};
            // the march: the scene's sky into the march image
            {
                const std::array writes{Write(0, StorageImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        WriteBuffer(3, &block_info), WriteBuffer(4, &counter_info)};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_march);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_march, 0, writes);
                cmdbuf.pushConstants(layout_march, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch((march_width + CL_WG - 1) / CL_WG, (march_height + CL_WG - 1) / CL_WG,
                                1);
            }
            EffectPass::ComputeBarrier(cmdbuf);
            // the composite: the march image into the scene's sky pixels
            {
                const std::array writes{Write(0, StorageImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        WriteBuffer(3, &block_info)};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_composite);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_composite, 0,
                                            writes);
                cmdbuf.pushConstants(layout_composite, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(push), &push);
                cmdbuf.dispatch((width + CL_WG - 1) / CL_WG, (height + CL_WG - 1) / CL_WG, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            // the counters' totals into the host copy (the log reads it a frame or two later)
            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, CL::CounterWords * 4});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

} // namespace Vulkan
''',
    H+"cloud_layer.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): FEATURE, BB_VOLUMETRIC_CLOUDS=1 only. A layer of ray marched
// clouds in front of the painted sky dome, made by renderer_vulkan/vk_cloud_layer.cpp (the knobs,
// the numbers and their rules are cloud_layer_params.h's) in two builds of this file:
//  - MARCH: one invocation a pixel of an image 1 / CL_DIV of the scene a side. A pixel with at
//    least one sky pixel under it (depth 1, or a view z beyond Params.dist.z when that is above 0)
//    takes the mean colour of those sky pixels (the painted sky, with the game's own fog on it) as
//    its tint and marches the view ray through the slab. Output: premultiplied cloud colour
//    (rgb) and opacity (a); r < 0 marks a pixel with no sky under it.
//  - COMPOSITE: one invocation a scene pixel. A sky pixel takes the four nearest march pixels that
//    have sky under them (bilinear weights, renormalised over those: no cloud colour leaks from or
//    onto geometry) and blends: scene = scene (1 - a) + premultiplied colour.
// The density is the cloud shadows' field (cloud_shadow.comp: the same value noise on r94's
// lattice with the same offsets, weights and edges): a point p of the layer reads the plane
// coordinate q = p.xz - slope x Href (Href: the layer's reference height) and
// c = smoothstep(low, high, n(q)), where cloud_shadow.comp reads q = p.xz - p.y slope at the
// ground; for a layer point and the ground point along the light below it the two q are equal, so
// the ground is shadowed exactly where this layer has cloud (at the reference height). The slab is
// slab.x to slab.x + slab.y above the world's y = 0 (Params.slab); the cloud at a column fills
// 0.35 + 0.65 c of it from the flat base up, with a rounded top.
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

#include "cloud_layer_layout.h"

layout(local_size_x = CL_WG, local_size_y = CL_WG) in;

#ifdef MARCH
layout(binding = 0, rgba16f) uniform writeonly image2D cloud_img;
layout(binding = 1, rgba16f) uniform readonly image2D scene_img;
#else
layout(binding = 0, rgba16f) uniform readonly image2D cloud_img;
layout(binding = 1, rgba16f) uniform image2D scene_img;
#endif
layout(binding = 2) uniform texture2D depth_tex; // D32, depth 0..1 (D3D projection)

// CloudLayerParams::Params, field for field (13 vec4, written by the engine each frame).
layout(std430, binding = 3) readonly buffer Params {
    vec4 row0, row1, row2; // view to world, 3x4 rows (the camera's pass); the camera at w
    vec4 proj;             // x scale, y scale (signed: ndc +y down), z scale, z offset
    vec4 cloud_off0;       // xyz: octave 0's offset in its lattice cells; w: 1 / size (1/m)
    vec4 cloud_off1;       // xyz: octave 1's offset; w: low edge (n below it: no cloud)
    vec4 cloud_off2;       // xyz: octave 2's offset; w: high edge (n above it: full cloud)
    vec4 light;            // xyz: the direction toward the light (world); w: its share (0: none)
    vec4 slab;             // base y (m), thickness (m), reference height (m), sigma (1/m)
    vec4 plane;            // xy: L.xz / max(L.y, 0.1) (the cloud shadows' slope); zw: the jitter
    vec4 look;             // steps, opacity cap, horizon fade from, to (|ray y|)
    vec4 dist;             // distance fade from, to (m); sky view z (m, 0: depth 1 only); unused
    vec4 tone;             // ambient, light, desaturation of the tint, forward scatter
};

layout(push_constant) uniform Push {
    uvec2 scene; // the scene's size in pixels
    uint frame;  // for the march's jitter
    uint flags;  // CL_FLAG_*
};

const float MAX_T = 12000.0;   // m: no cloud is marched beyond this distance
const float MAX_CHORD = 3000.0; // m: the longest stretch of a ray marched in the slab

// The view z (m) a depth gives (as heat_haze.comp).
float view_z(float depth) {
    return proj.w / min(depth - proj.z, -1e-8);
}

bool is_sky(float depth) {
    return depth >= 1.0 || (dist.z > 0.0 && view_z(depth) > dist.z);
}

// The ray's distances (t0 < t1, t0 >= 0) inside the slab base < y < top for a camera at height cy
// and a ray of y slope dy; false when it does not meet the slab.
bool slab_range(float cy, float dy, float base, float top, out float t0, out float t1) {
    t0 = 0.0;
    t1 = 0.0;
    if (abs(dy) < 1e-4) {
        if (cy < base || cy > top) return false;
        t1 = MAX_T;
        return true;
    }
    float ta = (base - cy) / dy, tb = (top - cy) / dy;
    t0 = max(min(ta, tb), 0.0);
    t1 = max(ta, tb);
    return t1 > t0;
}

// fog_noise.glsl's value noise and lattice turn only (as cloud_shadow.comp)
#define FOG_NOISE_VALUE_ONLY
#include "fog_noise.glsl"

// n at the lattice coordinate x = (q.x, 0, q.y) / size: 0.5 plus the weighted octaves, each
// (N - 0.5) of fog_noise_value on its turned lattice minus its offset; lod (0..1 an octave) fades
// an octave out toward its mean when the march's step is longer than its cells (no aliasing).
// The octaves' terms read as cloud_shadow.comp's cloud_light reads them (the patch's check).
float cloud_n(vec3 x, vec3 lod) {
    float n = 0.5;
    n += float(FOG_NOISE_WEIGHT0) * lod.x *
         (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS0), float(FOG_NOISE_YAW_SIN0),
                                          float(FOG_NOISE_RATIO0)) - cloud_off0.xyz) - 0.5);
    if (lod.y > 0.0) {
        n += float(FOG_NOISE_WEIGHT1) * lod.y *
             (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS1), float(FOG_NOISE_YAW_SIN1),
                                              float(FOG_NOISE_RATIO1)) - cloud_off1.xyz) - 0.5);
    }
    if (lod.z > 0.0) {
        n += float(FOG_NOISE_WEIGHT2) * lod.z *
             (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS2), float(FOG_NOISE_YAW_SIN2),
                                              float(FOG_NOISE_RATIO2)) - cloud_off2.xyz) - 0.5);
    }
    return n;
}

// The cloud's density (1/m) at world point p, and in v the height in the cloud (0 base, 1 top).
float density_at(vec3 p, vec3 lod, out float v) {
    v = 0.0;
    float u = (p.y - slab.x) / slab.y;
    if (u <= 0.0 || u >= 1.0) return 0.0;
    vec2 q = p.xz - plane.xy * slab.z;
    vec3 x = vec3(q.x, 0.0, q.y) * cloud_off0.w;
    if (any(isnan(x)) || any(isinf(x))) return 0.0;
    float c = smoothstep(cloud_off1.w, cloud_off2.w, cloud_n(x, lod));
    if (c <= 0.0) return 0.0;
    float top = 0.35 + 0.65 * c;
    v = u / top;
    if (v >= 1.0) return 0.0;
    float h = smoothstep(0.0, 0.15, v) * (1.0 - smoothstep(0.55, 1.0, v));
    return slab.w * c * h;
}

// Interleaved gradient noise, shifted each frame (the upscaler averages the frames).
float ign(vec2 p) {
    p += 5.588238 * float(frame & 63u);
    return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
}

shared uint group_counts[CL_WORDS];

#ifdef MARCH
layout(std430, binding = 4) buffer Counters {
    uint words[CL_WORDS];
};

vec4 march(ivec2 hp) {
    ivec2 base = hp * CL_DIV;
    vec3 sky_sum = vec3(0.0);
    float sky_n = 0.0;
    for (int j = 0; j < CL_DIV; ++j) {
        for (int i = 0; i < CL_DIV; ++i) {
            ivec2 p = base + ivec2(i, j);
            if (any(greaterThanEqual(p, ivec2(scene)))) continue;
            if (is_sky(texelFetch(depth_tex, p, 0).r)) {
                vec3 c = imageLoad(scene_img, p).rgb;
                if (any(isnan(c)) || any(isinf(c))) c = vec3(0.0);
                sky_sum += clamp(c, vec3(0.0), vec3(10000.0));
                sky_n += 1.0;
            }
        }
    }
    if (sky_n == 0.0) return vec4(-1.0, 0.0, 0.0, 0.0);
    atomicAdd(group_counts[CL_WORD_SKY], 1u);
    // the view ray through the block's centre (ToPixel's inverse: pixel = (ndc / 2 + 0.5) size +
    // jitter)
    vec2 centre = vec2(base) + 0.5 * float(CL_DIV);
    vec2 ndc = (centre - plane.zw) / vec2(scene) * 2.0 - 1.0;
    vec3 dv = vec3(ndc.x / proj.x, ndc.y / proj.y, 1.0);
    vec3 dw = normalize(vec3(dot(row0.xyz, dv), dot(row1.xyz, dv), dot(row2.xyz, dv)));
    vec3 cam = vec3(row0.w, row1.w, row2.w);
    float top_y = slab.x + slab.y;
    float t0, t1;
    if (!slab_range(cam.y, dw.y, slab.x, top_y, t0, t1) || t0 > MAX_T) return vec4(0.0);
    float fade = smoothstep(look.z, look.w, abs(dw.y)) * (1.0 - smoothstep(dist.x, dist.y, t0));
    if (fade <= 0.0) return vec4(0.0);
    t1 = min(t1, t0 + MAX_CHORD);
    int steps = int(look.x);
    float dt = (t1 - t0) / float(steps);
    // the longest move of the plane coordinate in a step, in lattice cells of each octave
    float sh = length(dw.xz - plane.xy * dw.y) * dt * cloud_off0.w;
    vec3 lod = clamp(vec3(1.6) - vec3(sh) / vec3(float(FOG_NOISE_RATIO0), float(FOG_NOISE_RATIO1),
                                                 float(FOG_NOISE_RATIO2)),
                     vec3(0.0), vec3(1.0));
    float cos_l = dot(dw, light.xyz);
    float forward = pow(max(cos_l, 0.0), 6.0);
    float jitter = ign(vec2(hp));
    float T = 1.0, acc = 0.0;
    uint taken = 0u;
    for (int i = 0; i < steps; ++i) {
        ++taken;
        vec3 p = cam + dw * (t0 + (float(i) + jitter) * dt);
        float v;
        float dens = density_at(p, lod, v);
        if (dens <= 0.0) continue;
        float a = 1.0 - exp(-dens * dt);
        float lam = tone.x * mix(0.4, 1.0, v);
        if (light.w > 0.0 && a > 0.004) {
            float lp = min((top_y - p.y) / max(light.y, 0.15), 2.0 * slab.y);
            float unused;
            float dl = density_at(p + light.xyz * (0.5 * lp), lod, unused);
            lam += tone.y * light.w * exp(-dl * lp * 1.2) * (0.45 + tone.w * forward);
        }
        acc += T * a * lam;
        T *= 1.0 - a;
        if (T < 0.03) break;
    }
    vec3 tint = sky_sum / sky_n;
    tint = mix(tint, vec3(dot(tint, vec3(0.2126, 0.7152, 0.0722))), tone.z);
    float scale = fade * look.y;
    float alpha = (1.0 - T) * scale;
    atomicAdd(group_counts[CL_WORD_HIT], 1u);
    atomicAdd(group_counts[CL_WORD_STEPS], taken);
    atomicAdd(group_counts[CL_WORD_OPACITY], uint(alpha * 256.0 + 0.5));
    if (alpha >= 1.0 / 64.0) atomicAdd(group_counts[CL_WORD_COVERED], 1u);
    return vec4(tint * (acc * scale), alpha);
}

void main() {
    if (gl_LocalInvocationIndex < CL_WORDS) {
        group_counts[gl_LocalInvocationIndex] = 0u;
    }
    memoryBarrierShared();
    barrier();
    ivec2 hp = ivec2(gl_GlobalInvocationID.xy);
    if (all(lessThan(hp, imageSize(cloud_img)))) {
        atomicAdd(group_counts[CL_WORD_TOTAL], 1u);
        imageStore(cloud_img, hp, march(hp));
    }
    memoryBarrierShared();
    barrier();
    if (gl_LocalInvocationIndex < CL_WORDS) {
        uint n = group_counts[gl_LocalInvocationIndex];
        if (n != 0u) {
            atomicAdd(words[gl_LocalInvocationIndex], n);
        }
    }
}
#else
void main() {
    ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (any(greaterThanEqual(p, ivec2(scene)))) return;
    if (!is_sky(texelFetch(depth_tex, p, 0).r)) return;
    vec2 h = (vec2(p) + 0.5) / float(CL_DIV) - 0.5;
    ivec2 b = ivec2(floor(h));
    vec2 f = h - vec2(b);
    ivec2 hs = imageSize(cloud_img);
    vec4 sum = vec4(0.0);
    float weights = 0.0;
    for (int j = 0; j < 2; ++j) {
        for (int i = 0; i < 2; ++i) {
            vec4 c = imageLoad(cloud_img, clamp(b + ivec2(i, j), ivec2(0), hs - 1));
            if (c.r < 0.0) continue;
            float w = (i == 0 ? 1.0 - f.x : f.x) * (j == 0 ? 1.0 - f.y : f.y);
            sum += w * c;
            weights += w;
        }
    }
    vec4 clouds = weights > 0.0 ? sum / weights : vec4(0.0);
    vec4 px = imageLoad(scene_img, p);
    if ((flags & CL_FLAG_SHOW) != 0u) {
        // test view: the sky dim green where the layer has no cloud, magenta with the opacity
        float shown = clamp(clouds.a * 1.5, 0.0, 1.0);
        imageStore(scene_img, p, vec4(mix(vec3(0.02, 0.25, 0.06), vec3(2.0, 0.15, 1.6), shown), px.a));
        return;
    }
    if (clouds.a < 1.0 / 1024.0) return;
    vec3 rgb = px.rgb;
    if (any(isnan(rgb)) || any(isinf(rgb))) return;
    imageStore(scene_img, p, vec4(rgb * (1.0 - clouds.a) + clouds.rgb, px.a));
}
#endif
''',
    H+"cloud_layer_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): what the cloud layer's shader (cloud_layer.comp) and the engine
// (renderer_vulkan/cloud_layer_params.h, which ties these to its constants with static_asserts)
// share. Plain #define lines only: the shader includes this file through
// GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds every number both
// sides use.
#ifndef CLOUD_LAYER_LAYOUT_H
#define CLOUD_LAYER_LAYOUT_H

// The march's image is 1 / CL_DIV of the scene along each axis (CL_DIV x CL_DIV scene pixels a
// pixel of it); the composite upsamples it with a depth (sky) aware bilinear filter.
#define CL_DIV 2
// The workgroup's side, both passes.
#define CL_WG 8
// The push word `flags` (CloudLayerParams::Flag*).
#define CL_FLAG_SHOW 1 // BB_VOLUMETRIC_CLOUDS_SHOW=1: the opacity painted in a test colour
// The counter buffer's words (CloudLayerParams::Word*): this frame's totals, cleared before each
// frame's march and copied to the host after the composite. Counted per workgroup in shared
// memory and added once a workgroup.
#define CL_WORD_TOTAL 0u   // march pixels (1 / CL_DIV of the scene a side)
#define CL_WORD_SKY 1u     // of them with at least one sky pixel under them (marched or not)
#define CL_WORD_HIT 2u     // sky pixels whose ray meets the slab and is not faded out
#define CL_WORD_COVERED 3u // sky pixels with an opacity of 1/64 or more
#define CL_WORD_OPACITY 4u // the sum of round(opacity x 256) over the sky pixels
#define CL_WORD_STEPS 5u   // march steps taken
#define CL_WORDS 8u

#endif
''',
    "engine/tests/test_cloud_layer.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r119_volumetric-clouds): checks of gpu/shadps4/video_core/renderer_vulkan/cloud_layer_params.h,
// the cloud layer's knobs, slab, cloud field and Params block (built and run by engine/build.sh --test
// and the CMake target cloud-layer-test).
//  a. The knobs: BB_VOLUMETRIC_CLOUDS starts with 1; every other knob falls back to its default when
//     missing or not a number and is clamped; BB_VOLUMETRIC_CLOUDS_SHOW starts with 1.
//  b. CoverEdges: the shadows' edges at cover 0.5, moved by (0.5 - cover) CoverShift, always apart.
//  c. The slab: the reference height and sigma.
//  d. SlabRange: a camera below, inside and above the slab, rays up, down and level.
//  e. The noise twin: the corner hash, the value noise (reference values worked out with the same
//     arithmetic in python), its period, FieldN with and without offsets and with octaves faded.
//  f. The shadow and the layer read the same density: for ground points g under a light, the cover
//     of the cloud over g (CloudOver) at the layer's plane coordinate is the cloud shadows' own cover
//     at g, and the shadow's Light(n) is 1 - depth x that cover; the density is 0 outside the slab
//     and above a column's top.
//  g. The Params block: its slots, the light without a valid sun, the knobs in their places.
//  h. IsSky, LightShare, and the counters' shares.
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <initializer_list>

#include "gpu/shadps4/video_core/renderer_vulkan/cloud_layer_params.h"

using namespace CloudLayerParams;

namespace {

bool Near(double a, double b, double eps) {
    return std::fabs(a - b) <= eps;
}

std::array<float, 3> Unit(float x, float y, float z) {
    const float n = std::sqrt(x * x + y * y + z * z);
    return {x / n, y / n, z / n};
}

} // namespace

int main() {
    // a.
    {
        const Knobs k = MakeKnobs(nullptr, nullptr, nullptr, nullptr, nullptr);
        assert(!k.on && !k.show && k.cover == DefaultCover && k.density == DefaultDensity &&
               k.height == DefaultHeight && k.thick == DefaultThick && k.steps == DefaultSteps &&
               k.sky_z == 0.0f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr).on);
        assert(MakeKnobs("1x", nullptr, nullptr, nullptr, nullptr).on);
        for (const char* off : {"", "0", "2", "yes", " 1"}) {
            assert(!MakeKnobs(off, nullptr, nullptr, nullptr, nullptr).on);
        }
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, "1").show);
        assert(!MakeKnobs("1", nullptr, nullptr, nullptr, "0").show);
        const Knobs c = MakeKnobs("1", "2", "100", "10", nullptr, "5", "1", "999999");
        assert(c.cover == 1.0f && c.density == MaxDensity && c.height == MinHeight &&
               c.thick == MinThick && c.steps == MinSteps && c.sky_z == MaxSkyZ);
        const Knobs d = MakeKnobs("1", "-1", "0", "99999", nullptr, "99999", "999", "-5");
        assert(d.cover == 0.0f && d.density == MinDensity && d.height == MaxHeight &&
               d.thick == MaxThick && d.steps == MaxSteps && d.sky_z == 0.0f);
        const Knobs e = MakeKnobs("1", "abc", "nan", "", nullptr, "inf", "x", "y");
        assert(e.cover == DefaultCover && e.density == DefaultDensity && e.height == DefaultHeight &&
               e.thick == DefaultThick && e.steps == DefaultSteps && e.sky_z == 0.0f);
        const Knobs f = MakeKnobs("1", "0.8", "2.5", "900", nullptr, "400", "20", "3000");
        assert(Near(f.cover, 0.8, 1e-6) && Near(f.density, 2.5, 1e-6) && f.height == 900.0f &&
               f.thick == 400.0f && f.steps == 20 && f.sky_z == 3000.0f);
    }
    // b.
    {
        const Edges same = CoverEdges(CloudShadows::Low, CloudShadows::High, DefaultCover);
        assert(same.low == CloudShadows::Low && same.high == CloudShadows::High);
        const Edges more = CoverEdges(CloudShadows::Low, CloudShadows::High, 1.0f);
        assert(Near(more.low, CloudShadows::Low - 0.5 * CoverShift, 1e-6) &&
               Near(more.high, CloudShadows::High - 0.5 * CoverShift, 1e-6));
        const Edges less = CoverEdges(CloudShadows::Low, CloudShadows::High, 0.0f);
        assert(Near(less.low, CloudShadows::Low + 0.5 * CoverShift, 1e-6));
        float last = 1.0f;
        for (int i = 0; i <= 20; ++i) {
            const Edges e = CoverEdges(CloudShadows::Low, CloudShadows::High, float(i) / 20.0f);
            assert(e.low >= 0.02f && e.high <= 0.99f && e.high >= e.low + 0.02f - 1e-6f);
            assert(e.low <= last); // more cover: lower edges
            last = e.low;
        }
        // a wide input is held apart too
        const Edges tight = CoverEdges(0.9f, 0.9f, 0.0f);
        assert(tight.high >= tight.low + 0.02f - 1e-6f && tight.high <= 0.99f);
    }
    // c.
    {
        const Knobs k = MakeKnobs("1", nullptr, "2", "600", nullptr, "200");
        const Slab s = MakeSlab(k);
        assert(s.base == 600.0f && s.thick == 200.0f && s.Top() == 800.0f);
        assert(Near(s.reference, 600.0 + RefFraction * 200.0, 1e-4));
        assert(Near(s.sigma, SigmaScale / 200.0 * 2.0, 1e-7));
        // a full column straight up: optical depth about 2.8 x density at the defaults
        const Slab d = MakeSlab(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr));
        assert(Near(d.sigma * d.thick, SigmaScale, 1e-4));
    }
    // d.
    {
        float t0 = -1.0f, t1 = -1.0f;
        // below the slab, looking up at 45 degrees
        assert(SlabRange(100.0f, 0.7071f, 700.0f, 1000.0f, &t0, &t1));
        assert(Near(t0, 600.0 / 0.7071, 0.5) && Near(t1, 900.0 / 0.7071, 0.5));
        // below, looking down or level: no slab
        assert(!SlabRange(100.0f, -0.5f, 700.0f, 1000.0f, &t0, &t1));
        assert(!SlabRange(100.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1));
        // inside, looking up: from the camera to the top; looking down: from the camera to the base
        assert(SlabRange(800.0f, 1.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f &&
               Near(t1, 200.0, 1e-3));
        assert(SlabRange(800.0f, -1.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f &&
               Near(t1, 100.0, 1e-3));
        // inside, level: the whole stretch (up to MaxT); above, level: none
        assert(SlabRange(800.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1) && t0 == 0.0f && t1 == MaxT);
        assert(!SlabRange(1200.0f, 0.0f, 700.0f, 1000.0f, &t0, &t1));
        // above the slab, looking down: it is met at the top
        assert(SlabRange(1200.0f, -1.0f, 700.0f, 1000.0f, &t0, &t1) && Near(t0, 200.0, 1e-3) &&
               Near(t1, 500.0, 1e-3));
        // above, looking up: no slab
        assert(!SlabRange(1200.0f, 0.5f, 700.0f, 1000.0f, &t0, &t1));
    }
    // e.
    {
        assert(Corner(0u) * 16777216.0f == 130277.0f);
        assert(Corner(1u) * 16777216.0f == 10440790.0f);
        assert(Corner(0x0102u) * 16777216.0f == 11616340.0f);
        assert(Corner(0x030201u) * 16777216.0f == 16643622.0f);
        assert(Corner(0xFF00FFu) * 16777216.0f == 4582979.0f);
        assert(Near(Value({3.3f, 0.0f, 7.8f}), 0.41997828, 1e-4));
        assert(Near(Value({-1.25f, 0.0f, -40.5f}), 0.29839898, 1e-4));
        assert(Near(Value({0.0f, 0.0f, 0.0f}), 0.0077651143, 1e-6));
        // the lattice repeats every FOG_NOISE_PERIOD cells
        assert(Near(Value({3.3f + 256.0f, 0.0f, 7.8f}), Value({3.3f, 0.0f, 7.8f}), 1e-4));
        assert(Near(Value({3.3f, 0.0f, 7.8f - 256.0f}), Value({3.3f, 0.0f, 7.8f}), 1e-4));
        for (int i = 0; i < 200; ++i) {
            const float v = Value({0.37f * float(i), 0.11f * float(i), -0.53f * float(i)});
            assert(v >= 0.0f && v < 1.0f);
        }
        const Offsets zero{};
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, zero), 0.50065323, 1e-4));
        assert(Near(FieldN({-3.2f, 0.0f, 5.1f}, zero), 0.76081447, 1e-4));
        const Offsets moved{{{1.5f, 0.25f, 2.0f}, {0.5f, 0.5f, 0.5f}, {10.0f, 0.0f, 3.0f}}};
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, moved), 0.46092598, 1e-4));
        assert(Near(FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.5f, 0.0f}), 0.46809860, 1e-4));
        // an octave left out (lod 0) is the same as a missing term, and a faded one lies between
        const float full = FieldN({1.7f, 0.0f, 2.9f}, moved);
        const float none = FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.0f, 0.0f});
        const float half = FieldN({1.7f, 0.0f, 2.9f}, moved, {1.0f, 0.5f, 0.5f});
        assert(std::fabs(half - none) <= std::fabs(full - none) + 1e-6f);
    }
    // f.
    {
        const CloudShadows::Knobs shadow = CloudShadows::MakeKnobs("1", nullptr, nullptr, "90");
        const std::array<float, 3> light = Unit(0.6f, 0.5f, -0.3f);
        CloudShadows::State state;
        for (int i = 0; i < 80; ++i) {
            state.Advance(shadow, true, 90.0f, true, light, 0.1);
        }
        const Knobs knobs = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        Field f;
        f.offsets = OffsetsOf(state.Offsets());
        f.inv_size = 1.0f / shadow.scale;
        f.edges = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), knobs.cover);
        f.slope = CloudShadows::Slope(light);
        f.slab = MakeSlab(knobs);
        assert(f.edges.low == CloudShadows::Low && f.edges.high == CloudShadows::High);
        int clear = 0, partial = 0, full = 0, dense = 0, total = 0;
        for (int i = -10; i <= 10; ++i) {
            for (int j = -10; j <= 10; ++j) {
                const std::array<float, 3> g{37.0f * float(i) + 3.0f, 2.0f * float((i * j) % 7),
                                             41.0f * float(j) - 5.0f};
                const std::array<float, 3> over = CloudOver(f, g);
                assert(over[1] == f.slab.reference);
                // the cloud over g, read at the layer's plane, is the shadow's cover at g
                const float layer = Cover(f, LayerPlane(f, over));
                const float shade = ShadowCover(f, g);
                assert(Near(layer, shade, 2e-3));
                // the shadow's Light is 1 - depth x that cover (CloudShadows::Light at the same n)
                const std::array<float, 2> q = CloudShadows::Plane(g, f.slope);
                const float n = FieldN({q[0] * f.inv_size, 0.0f, q[1] * f.inv_size}, f.offsets);
                const float depth = shadow.Depth();
                assert(Near(CloudShadows::Light(n, depth, shadow.LowEdge(), shadow.HighEdge()),
                            1.0 - depth * shade, 1e-5));
                // the density where that cloud is: 0 where there is none, else sigma c h
                float v = -1.0f;
                const float dens = Density(f, over, &v);
                if (layer <= 0.0f) {
                    assert(dens == 0.0f);
                    ++clear;
                } else {
                    assert(v >= 0.0f && v < 1.0f + 1e-6f);
                    assert(dens >= 0.0f && dens <= f.slab.sigma * layer + 1e-6f);
                    if (layer >= 1.0f) {
                        ++full;
                    } else {
                        ++partial;
                    }
                    if (dens > 0.0f) {
                        ++dense;
                    }
                }
                ++total;
            }
        }
        // the field has all three kinds of ground, and the reference plane holds cloud
        assert(total == 441 && clear > 40 && partial > 20 && full > 10 && dense > 40);
        // outside the slab: nothing, at any plane coordinate
        float v = 0.0f;
        assert(Density(f, {0.0f, f.slab.base - 1.0f, 0.0f}, &v) == 0.0f);
        assert(Density(f, {0.0f, f.slab.Top() + 1.0f, 0.0f}, &v) == 0.0f);
        assert(Density(f, {0.0f, f.slab.base, 0.0f}, &v) == 0.0f);
        // a thinner cloud is lower: for a small cover the top (v = 1) is under the slab's top
        std::array<float, 3> p{0.0f, 0.0f, 0.0f};
        int low_tops = 0;
        for (int i = 0; i < 300; ++i) {
            p = {11.0f * float(i), f.slab.base + 0.9f * f.slab.thick, 7.0f * float(i)};
            if (Cover(f, LayerPlane(f, p)) < 0.4f) {
                float vv = 0.0f;
                assert(Density(f, p, &vv) == 0.0f); // 0.9 of the slab is above a 0.35 + 0.65 c top
                ++low_tops;
            }
        }
        assert(low_tops > 30);
    }
    // g.
    {
        const CloudShadows::Knobs shadow = CloudShadows::MakeKnobs("1", "120", nullptr, "45");
        CloudShadows::State state;
        const Knobs knobs = MakeKnobs("1", "0.7", "1.5", "800", nullptr, "250", "16", "4000");
        const std::array<float, 12> rows{1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7};
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);
        const std::array<float, 2> slope = CloudShadows::Slope(light);
        const Params p = MakeParams(rows, proj, state, shadow, knobs, light, true, slope, {0.25f, -0.5f});
        assert(p.row0[3] == 5.0f && p.row1[3] == 6.0f && p.row2[3] == 7.0f && p.row0[0] == 1.0f &&
               p.row1[1] == 1.0f && p.row2[2] == 1.0f);
        assert(p.proj == proj);
        assert(Near(p.off0[3], 1.0 / 120.0, 1e-7));
        const Edges e = CoverEdges(shadow.LowEdge(), shadow.HighEdge(), 0.7f);
        assert(p.off1[3] == e.low && p.off2[3] == e.high);
        assert(p.off0[0] == 0.0f && p.off1[1] == 0.0f && p.off2[2] == 0.0f); // a fresh State
        assert(Near(p.light[1], 0.8, 1e-6) && Near(p.light[2], 0.6, 1e-6) && p.light[3] == 1.0f);
        assert(p.slab[0] == 800.0f && p.slab[1] == 250.0f && Near(p.slab[2], 800.0 + 0.35 * 250.0, 1e-3) &&
               Near(p.slab[3], SigmaScale / 250.0 * 1.5, 1e-6));
        assert(Near(p.plane[0], slope[0], 1e-7) && Near(p.plane[1], slope[1], 1e-7) &&
               p.plane[2] == 0.25f && p.plane[3] == -0.5f);
        assert(p.look[0] == 16.0f && p.look[1] == OpacityCap && p.look[2] == HorizonFrom &&
               p.look[3] == HorizonTo);
        assert(p.dist[0] == FadeFrom && p.dist[1] == FadeTo && p.dist[2] == 4000.0f);
        assert(p.tone[0] == Ambient && p.tone[1] == LightGain && p.tone[2] == Desaturate &&
               p.tone[3] == Forward);
        // no valid sun: the light points up with no share (only the sky's ambient lights the cloud)
        const Params dark = MakeParams(rows, proj, state, shadow, knobs, {1.0f, 0.0f, 0.0f}, false,
                                       {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(dark.light[0] == 0.0f && dark.light[1] == 1.0f && dark.light[2] == 0.0f &&
               dark.light[3] == 0.0f);
        // the push block and the layout's numbers
        assert(sizeof(Push) == 16 && CounterWords == CL_WORDS && CL_WORD_STEPS < CL_WORDS);
    }
    // h.
    {
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        assert(IsSky(1.0f, proj, 0.0f) && !IsSky(0.9999f, proj, 0.0f));
        assert(IsSky(1.0f, proj, 500.0f));
        // proj z scale 1, offset 0.1: z = 0.1 / (depth - 1): depth 0.99999 is 10000 m, 0.9 is -1 m
        assert(Near(ViewZ(0.99999f, 1.0f, 0.1f), 0.1 / (0.99999f - 1.0f), 1.0));
        assert(IsSky(0.99999f, proj, 5.0f) == (ViewZ(0.99999f, 1.0f, 0.1f) > 5.0f));
        assert(!IsSky(0.5f, proj, 50.0f));
        assert(LightShare({0.0f, 0.5f, 0.0f}, false) == 0.0f);
        assert(LightShare({0.0f, -0.1f, 0.0f}, true) == 0.0f);
        assert(LightShare({0.0f, 0.3f, 0.0f}, true) == 1.0f && LightShare({0.0f, 0.9f, 0.0f}, true) == 1.0f);
        float last = -1.0f;
        for (int i = 0; i <= 40; ++i) {
            const float s = LightShare({0.0f, -0.1f + 0.0125f * float(i), 0.0f}, true);
            assert(s >= last && s >= 0.0f && s <= 1.0f);
            last = s;
        }
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_TOTAL] = 1000;
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_HIT] = 300;
        frame[CL_WORD_COVERED] = 200;
        frame[CL_WORD_OPACITY] = 400 * 64; // a mean opacity of 0.25
        frame[CL_WORD_STEPS] = 3600;
        t.Add(frame);
        t.Add(frame);
        const Shares s = SharesOf(t);
        assert(t.frames == 2 && Near(s.sky, 0.4, 1e-9) && Near(s.covered, 0.5, 1e-9) &&
               Near(s.opacity, 0.25, 1e-9) && Near(s.steps, 12.0, 1e-9));
        const Shares none = SharesOf(Totals{});
        assert(none.sky == 0.0 && none.covered == 0.0 && none.opacity == 0.0 && none.steps == 0.0);
    }
    std::puts("cloud layer: ok");
    return 0;
}
''',
}

README_BLOCK = r'''### Volumetric clouds (in development)

A layer of ray marched clouds in front of the painted sky. The game's sky is one painted dome whose clouds never move, so this draws real clouds between that dome and the world, only over the pixels where the sky shows (depth 1; `BB_VOLUMETRIC_CLOUDS_SKYZ` can count a far view z too). They are a slab of air 300 m thick whose base is 700 m above the world's y = 0, marched along each sky pixel's view ray in 12 steps at half the scene's resolution and laid over the sky with a bilinear filter that never takes a colour from, or puts one on, a pixel that is not sky. They are lit by the direction of the sun or moon that the engine already finds for the sun shadows (the effects that resolve the sun shadows must be on; without a light known the clouds have only ambient light) and tinted by the painted sky behind them (the dome's own colour with the game's fog on it, turned 55% toward its grey), so they sit in the painting: dark on the underside, with a bright forward-scattered rim toward the light. They are thin and partial at the default (an opacity of at most 0.70), so the painted clouds show through, and they fade out toward the horizon (a ray rising less steeply than 0.05 is not clouded, one above 0.22 is in full) and beyond 5 to 10 km. The density is the cloud shadows' own field (`BB_CLOUD_SHADOWS`, r105b): the same noise, size, edges, offsets, direction and drift, so a shadow sweeping the ground belongs to the cloud overhead (exact for a point of the layer's reference height, 35% of the slab's thickness up; the top of a full cloud, 195 m higher, would cast its shadow about 480 m further along the light with the light 22 degrees up). While the cloud shadows are on the layer reads their clock itself; with them off it keeps a clock of its own made from the same variables (`BB_CLOUD_SHADOWS_SCALE`, `BB_CLOUDS_DIR`, `BB_WIND_DIR`, `BB_WIND_SPEED`, and the wind's direction with `BB_WIND=1`), so the heading and speed are the wind's `clouds` line in both cases. It is drawn at the upscaler's trigger, after the sky, the world and the drawn look and before the volumetric fog composite, the tonemap and the upscaler, so fog and haze lie over the clouds and the HUD is never touched; without the upscaler nothing is drawn (the log says so after 300 frames). Off unless `BB_VOLUMETRIC_CLOUDS` starts with 1: then two pipelines and three small buffers are made at the start and a march image (8 bytes a pixel of half the scene's size: 4.1 MB at a 1920x1080 scene) at the first frame; off, none of it exists and each of the three hooks is one pointer test. The log says the knobs once (`Volumetric clouds (r119, BB_VOLUMETRIC_CLOUDS=1):`) and every 600 frames the share of the march that is sky, the share of the sky that is covered, the mean opacity, the march steps, the heading, the speed and whether they are the cloud shadows' (`Volumetric clouds (r119): sky px share`), with a second line of frame counts and the camera's height. Cost: an estimate of 0.2 to 0.3 ms at 1080p internal with half of the picture sky (12 steps of three hashed noise octaves for each sky pixel of the half size march, and one read and write of every sky pixel of the scene) and about 0.03 ms with no sky in view (a depth read per pixel in each of the two passes), not measured; read it on the `Lighting: volumetric clouds` row of `BB_GPU_PROFILE=1`. These environment variables are read once when the game starts; they are for testing and are part of no look; no ini key yet.

| Variable | Effect | Default |
| --- | --- | --- |
| `BB_VOLUMETRIC_CLOUDS` | `1` (any text starting with `1`) turns the layer on; missing or other text is off | off |
| `BB_VOLUMETRIC_CLOUDS_COVER` | 0 to 1. At `0.5` the layer uses the cloud shadows' own edges (smoothstep(0.47, 0.59, n) of the same n), so the two agree; each 0.1 more or less moves both edges of n by 0.03 (lower edges, more and wider cloud, with more cover; higher edges, less, with less). The shadows keep their own edges | `0.5` |
| `BB_VOLUMETRIC_CLOUDS_DENSITY` | 0.05 to 4: the density, sigma = 4 / thickness x density per metre (a full column straight up has an optical depth of about 2.8 at 1; the opacity of one ray is capped at 0.70 whatever the density) | `1` |
| `BB_VOLUMETRIC_CLOUDS_HEIGHT` | The slab's base in metres above the world's y = 0, 150 to 3000 (the world's y, not the camera's: a camera above the base sees the clouds from above and they fade out) | `700` |
| `BB_VOLUMETRIC_CLOUDS_THICK` | The slab's thickness in metres, 60 to 1000. A column's cloud fills 0.35 + 0.65 c of it from the flat base up (c the cover from the noise) with a rounded top | `300` |
| `BB_VOLUMETRIC_CLOUDS_STEPS` | March steps a ray takes through the slab, 6 to 32 (a ray is marched over at most 3 km of the slab; an octave of the noise finer than a step fades out) | `12` |
| `BB_VOLUMETRIC_CLOUDS_SKYZ` | A pixel whose view z is beyond this many metres counts as sky too (0 to 100000; 0: only depth 1 is sky). For a place whose sky is drawn with a depth short of 1 | `0` |
| `BB_VOLUMETRIC_CLOUDS_SHOW` | Test only: `1` paints every sky pixel dim green and the clouds' opacity in magenta, in place of the clouds | off |

'''

EDITS = {
    R + "vk_cloud_shadow.h": [
        ("    /// Each frame end: the direction and drift move (the wind's direction with BB_WIND=1), the\n"
         "    /// periodic line.\n",
         "    /// bbport (r119_volumetric-clouds): the clock the cloud layer shares: the drift state (offsets,\n"
         "    /// heading) and the knobs (size, edges, speed).\n"
         "    [[nodiscard]] const CloudShadows::State& ClockState() const {\n"
         "        return state;\n"
         "    }\n"
         "    [[nodiscard]] const CloudShadows::Knobs& ClockKnobs() const {\n"
         "        return knobs;\n"
         "    }\n",
         "before"),
    ],
    R + "vk_rasterizer.h": [
        ('#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)\n',
         '#include "video_core/renderer_vulkan/vk_cloud_layer.h" // bbport (r119_volumetric-clouds)\n',
         "after"),
        ("    std::unique_ptr<CloudShadow> cloud_shadow;\n",
         "    /// bbport (r119_volumetric-clouds): made only with BB_VOLUMETRIC_CLOUDS=1 (CloudLayer::Wanted), else\n"
         "    /// null: its hooks are null pointer tests. Declared after cloud_shadow: it reads that one's clock.\n"
         "    std::unique_ptr<CloudLayer> cloud_layer;\n",
         "after"),
    ],
    R + "vk_rasterizer.cpp": [
        ("    if (CloudShadow::Wanted()) {\n"
         "        cloud_shadow = std::make_unique<CloudShadow>(instance, scheduler);\n"
         "    }\n",
         "    // bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (CloudLayer::Wanted, read once);\n"
         "    // otherwise none is made and its hooks are null tests. After the cloud shadows: it shares their\n"
         "    // clock while they are on. Its pipelines are made here, its march image at the first frame it\n"
         "    // draws; it is drawn right before the upscaler (without it, said after 300 frames).\n"
         "    if (CloudLayer::Wanted()) {\n"
         "        cloud_layer = std::make_unique<CloudLayer>(instance, scheduler, texture_cache, runtime,\n"
         "                                                   *scene_targets, *camera_motion);\n"
         "    }\n",
         "after"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("    // bbport (r105_cloud-shadows): the clouds' direction and drift (null when off), after the\n"
         "    // wind's step so that BB_WIND=1 gives this frame's direction\n",
         "    // bbport (r119_volumetric-clouds): the cloud layer (null when off): its own clock while the cloud\n"
         "    // shadows are off (after the wind's step, so that BB_WIND=1 gives this frame's direction; the\n"
         "    // wind's \"clouds\" line then gets its heading and speed), its counters and its log\n"
         "    if (cloud_layer) {\n"
         "        const BbWind::Snapshot w = wind.Get();\n"
         "        cloud_layer->OnFrameEnd(w.on, w.direction_deg);\n"
         "        if (cloud_layer->OwnClock()) {\n"
         "            BbWind::UseHeading(BbWind::Follower::Clouds, w, cloud_layer->Direction(),\n"
         "                               cloud_layer->Velocity(), BbWind::CloudRatio);\n"
         "        }\n"
         "    }\n",
         "before"),
        ("            if (cloud_shadow) {\n"
         "                cloud_shadow->SetSunLight(light.world, light.view_to_world, light.valid);\n"
         "            }\n",
         "            // bbport (r119_volumetric-clouds): the same light for the cloud layer (null when off)\n"
         "            if (cloud_layer) {\n"
         "                cloud_layer->SetSunLight(light.world, light.valid);\n"
         "            }\n",
         "after"),
        ("    if (effects_wanted && compute_hash == upscaler->TriggerHash()) {\n"
         "        const auto camera = camera_motion->PassMatrices();\n",
         "    // bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (off: one null pointer test): the\n"
         "    // clouds over the sky pixels of the scene colour, after the sky, the world and the drawn look,\n"
         "    // before the volumetric fog composite below (the fog lies over them), the tonemap and the upscaler.\n"
         "    if (cloud_layer && compute_hash == upscaler->TriggerHash()) {\n"
         "        cloud_layer->Apply(upscaler->SceneColor(), camera_motion->Depth(), upscaler->Jitter());\n"
         "    }\n",
         "before"),
    ],
    "engine/gpu/CMakeLists.txt": [
        ('    if (FILENAME MATCHES "^cloud_shadow")\n'
         "        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h)\n"
         "    endif()\n",
         "    # bbport (r119_volumetric-clouds): the cloud layer takes the fog noise, its numbers and its own layout\n"
         '    if (FILENAME MATCHES "^cloud_layer")\n'
         "        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h\n"
         "             ${SHADER_SRC}/cloud_layer_layout.h)\n"
         "    endif()\n",
         "after"),
        ("add_host_shader(cloud_shadow.comp cloud_shadow_gate_comp GATE=1)\n",
         "# bbport (r119_volumetric-clouds): BB_VOLUMETRIC_CLOUDS=1 only (both made at the start): the cloud layer's\n"
         "# march (sky pixels into a half size image) and composite (that image into the scene's sky pixels)\n"
         "add_host_shader(cloud_layer.comp cloud_layer_march_comp MARCH=1)\n"
         "add_host_shader(cloud_layer.comp cloud_layer_composite_comp COMPOSITE=1)\n",
         "after"),
        ("target_include_directories(cloud-shadows-test PRIVATE ..)\n",
         "# bbport (r119_volumetric-clouds): the cloud layer's knobs, slab, cloud field and Params block\n"
         "# (cloud_layer_params.h); also built and run by engine/build.sh --test.\n"
         "add_executable(cloud-layer-test EXCLUDE_FROM_ALL ../tests/test_cloud_layer.cpp)\n"
         "target_compile_options(cloud-layer-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(cloud-layer-test PRIVATE ..)\n",
         "after"),
    ],
    "engine/build.sh": [
        ("    out/cloud-shadows-test\n",
         "    # bbport (r119_volumetric-clouds): the cloud layer's knobs, slab, cloud field and Params block\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_cloud_layer.cpp -o out/cloud-layer-test\n'
         "    out/cloud-layer-test\n",
         "after"),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        ('#include "video_core/host_shaders/cloud_shadow_gate_comp.h" // bbport (r105_cloud-shadows)\n',
         '#include "video_core/host_shaders/cloud_layer_composite_comp.h" // bbport (r119_volumetric-clouds)\n'
         '#include "video_core/host_shaders/cloud_layer_march_comp.h"     // bbport (r119_volumetric-clouds)\n',
         "after"),
        ('        {"cloud shadows gate", CLOUD_SHADOW_GATE_COMP, {eStorageBuffer, eStorageBuffer, eStorageImage},\n'
         "         120},\n",
         "        // bbport (r119_volumetric-clouds): CloudLayer's two passes (CloudLayerParams::Push, 16 bytes)\n"
         '        {"cloud layer march", CLOUD_LAYER_MARCH_COMP,\n'
         "         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer, eStorageBuffer}, 16},\n"
         '        {"cloud layer composite", CLOUD_LAYER_COMPOSITE_COMP,\n'
         "         {eStorageImage, eStorageImage, eSampledImage, eStorageBuffer}, 16},\n",
         "after"),
    ],
    "README.md": [("### Halation (in development)\n", README_BLOCK, "before")],
}

# README numbers tied to the header's constants: (file, constant text, row start, value text).
TIES = [
    ("DefaultHeight = 700.0f", "| `BB_VOLUMETRIC_CLOUDS_HEIGHT` |", "| `700` |"),
    ("MinHeight = 150.0f, MaxHeight = 3000.0f", "| `BB_VOLUMETRIC_CLOUDS_HEIGHT` |", "150 to 3000"),
    ("DefaultHeight = 700.0f", "A layer of ray marched clouds", "base is 700 m"),
    ("DefaultThick = 300.0f", "A layer of ray marched clouds", "slab of air 300 m thick"),
    ("DefaultThick = 300.0f", "| `BB_VOLUMETRIC_CLOUDS_THICK` |", "| `300` |"),
    ("MinThick = 60.0f, MaxThick = 1000.0f", "| `BB_VOLUMETRIC_CLOUDS_THICK` |", "60 to 1000"),
    ("TopBase = 0.35f, TopCover = 0.65f", "| `BB_VOLUMETRIC_CLOUDS_THICK` |", "0.35 + 0.65 c"),
    ("DefaultSteps = 12", "A layer of ray marched clouds", "in 12 steps"),
    ("DefaultSteps = 12", "| `BB_VOLUMETRIC_CLOUDS_STEPS` |", "| `12` |"),
    ("MinSteps = 6, MaxSteps = 32", "| `BB_VOLUMETRIC_CLOUDS_STEPS` |", "6 to 32"),
    ("MaxChord = 3000.0f", "| `BB_VOLUMETRIC_CLOUDS_STEPS` |", "at most 3 km"),
    ("OpacityCap = 0.70f", "A layer of ray marched clouds", "at most 0.70"),
    ("OpacityCap = 0.70f", "| `BB_VOLUMETRIC_CLOUDS_DENSITY` |", "capped at 0.70"),
    ("HorizonFrom = 0.05f, HorizonTo = 0.22f", "A layer of ray marched clouds", "less steeply than 0.05"),
    ("HorizonFrom = 0.05f, HorizonTo = 0.22f", "A layer of ray marched clouds", "above 0.22 is in full"),
    ("FadeFrom = 5000.0f, FadeTo = 10000.0f", "A layer of ray marched clouds", "beyond 5 to 10 km"),
    ("Desaturate = 0.55f", "A layer of ray marched clouds", "turned 55% toward its grey"),
    ("RefFraction = 0.35f", "A layer of ray marched clouds", "35% of the slab's thickness up"),
    ("CoverShift = 0.30f", "| `BB_VOLUMETRIC_CLOUDS_COVER` |", "by 0.03"),
    ("DefaultCover = 0.5f", "| `BB_VOLUMETRIC_CLOUDS_COVER` |", "| `0.5` |"),
    ("MinDensity = 0.05f, MaxDensity = 4.0f", "| `BB_VOLUMETRIC_CLOUDS_DENSITY` |", "0.05 to 4"),
    ("SigmaScale = 4.0f", "| `BB_VOLUMETRIC_CLOUDS_DENSITY` |", "sigma = 4 / thickness"),
    ("MaxSkyZ = 100000.0f", "| `BB_VOLUMETRIC_CLOUDS_SKYZ` |", "0 to 100000"),
    ("FramesPeriod = 600", "A layer of ray marched clouds", "every 600 frames"),
    ("FramesNoPlace = 300", "A layer of ray marched clouds", "after 300 frames"),
]

# The shader's constants tied to the header's: (file with the text, its text, the text in cloud_layer_params.h).
SHADER_TIES = [
    (SHADER, "const float MAX_T = 12000.0;", "MaxT = 12000.0f"),
    (SHADER, "const float MAX_CHORD = 3000.0;", "MaxChord = 3000.0f"),
    (SHADER, "float top = 0.35 + 0.65 * c;", "TopBase = 0.35f, TopCover = 0.65f"),
    (SHADER, "smoothstep(0.0, 0.15, v) * (1.0 - smoothstep(0.55, 1.0, v))",
     "Smoothstep(0.0f, 0.15f, *v) * (1.0f - Smoothstep(0.55f, 1.0f, *v))"),
    (SHADER, "mix(0.4, 1.0, v)", "(0.4 of it at its base)"),
    (SHADER, "(0.45 + tone.w * forward)", "0.45 + this x cos^6"),
    (SHADER, "pow(max(cos_l, 0.0), 6.0)", "0.45 + this x cos^6"),
    (LAYOUT_NEW, "#define CL_DIV 2", "CL_DIV == 2"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def insert(text, anchor, block, where):
    return text.replace(anchor, anchor + block if where == "after" else block + anchor)


def squash(text):
    return re.sub(r"\s+", "", text)


def text_checks(texts):
    for path, edits in EDITS.items():
        for anchor, block, where in edits:
            if texts[path].count(block) != 1 or texts[path].count(anchor) != 1:
                raise SystemExit("text check: %s: block or anchor not found exactly once: %r"
                                 % (path, block[:70]))
    readme = texts["README.md"].split("\n")
    params = NEW[PARAMS]
    for const, row, value in TIES:
        line = [l for l in readme if l.startswith(row)]
        if params.count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    shader = NEW[SHADER]
    for path, s_text, h_text in SHADER_TIES:
        if NEW[path].count(s_text) != 1 or params.count(h_text) < 1:
            raise SystemExit("tie check: %r in %s against the header's %r" % (s_text, path, h_text))
    # the cloud field's octave terms are cloud_shadow.comp's (rule 10): the same lattice turn, offset and
    # weight on each octave, read from the tree (whitespace ignored)
    shadow = squash(load(SHADOW_SHADER)[2])
    mine = squash(shader)
    for k in range(3):
        core = ("fog_noise_value(fog_noise_cells(x,float(FOG_NOISE_YAW_COS%d),float(FOG_NOISE_YAW_SIN%d),"
                "float(FOG_NOISE_RATIO%d))-cloud_off%d.xyz)-0.5)" % (k, k, k, k))
        weight = "float(FOG_NOISE_WEIGHT%d)*" % k
        if shadow.count(core) != 1 or mine.count(core) != 1 or shadow.count(weight) != 1 or mine.count(weight) != 1:
            raise SystemExit("tie check: octave %d's term differs between cloud_layer.comp and cloud_shadow.comp" % k)
    for text in ("#defineFOG_NOISE_VALUE_ONLY", '#include"fog_noise.glsl"'):
        if shadow.count(text) != 1 or mine.count(text) != 1:
            raise SystemExit("tie check: %s is not in both shaders" % text)
    # the layer's edges are the shadows': README's 0.47 and 0.59 against cloud_shadow_params.h (the tree's)
    sp = load(SHADOW_PARAMS)[2]
    if "Low = 0.47f, High = 0.59f;" not in sp:
        raise SystemExit("tie check: cloud_shadow_params.h edges are not 0.47 and 0.59 any more")
    row = [l for l in readme if l.startswith("| `BB_VOLUMETRIC_CLOUDS_COVER` |")]
    if len(row) != 1 or "smoothstep(0.47, 0.59, n)" not in row[0]:
        raise SystemExit("tie check: README cover row against the shadows' edges")
    layout = load(LAYOUT)[2]
    for define in ("#define FOG_NOISE_WEIGHT0 0.55\n", "#define FOG_NOISE_RATIO1 0.43\n"):
        if layout.count(define) != 1:
            raise SystemExit("tie check: %s changed (the header's tests quote the noise's numbers)" % define.strip())
    for path, text in list(NEW.items()) + [("README block", README_BLOCK)]:
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(block) == 1 for anchor, block, where in edits)
        todo = sum(cur.count(anchor) == 1 and cur.count(block) == 0 for anchor, block, where in edits)
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d blocks in place, %d anchors found once without their block"
                             % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == new_bytes(text):
            state = "applied"
        else:
            raise SystemExit("%s exists and is not this patch's file" % path)
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
                for anchor, block, where in edits:
                    cur = insert(cur, anchor, block, where)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for anchor, block, where in edits:
                cur = insert(cur, anchor, block, where)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + TMP
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d new)" % (len(edited), len(NEW)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path, edits, raw, eol, cur, _ in edited:
        for anchor, block, where in reversed(edits):
            if cur.count(block) != 1:
                raise SystemExit("%s: block not found exactly once: %r" % (path, block[:70]))
            cur = cur.replace(block, "", 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(edited), len(NEW)))


main()
