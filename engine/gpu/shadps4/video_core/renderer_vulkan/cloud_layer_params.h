// SPDX-License-Identifier: GPL-3.0-or-later
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
// about 5.6 x density (r119d; 2.8 before); the opacity is then capped (OpacityCap, 0.92) so that a core is dense
// and only the thin edges show the painted sky through.
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
inline constexpr float DefaultSkyZ = 500.0f; ///< m: view z beyond which a pixel is sky (the dome: 1500 m and more)
// bbport (r119c_clouds-gaps): the layer's own size, speed and edges (the shadows' 100 m cells and edges made one
// even blanket of a sky: the r119c script's header says why).
inline constexpr float DefaultSize = 800.0f;  ///< m: BB_VOLUMETRIC_CLOUDS_SIZE, the biggest octave's cell
inline constexpr float MinSize = 100.0f, MaxSize = 8000.0f; ///< BB_VOLUMETRIC_CLOUDS_SIZE's clamp
inline constexpr float DefaultSpeed = 1.5f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed (r119d: was 1; r119i: was 6, 15 to 48 m/s read too fast: 3.75 to 12 m/s now)
inline constexpr float MinSpeed = 0.25f, MaxSpeed = 60.0f; ///< BB_VOLUMETRIC_CLOUDS_SPEED's clamp
// bbport (r119d_clouds-contrast): the one wind's cloud speed is held between these (m/s) before the knob: the
// weather's calm state (1.6 m/s) would drift 0.1 degrees a second, too slow to see; 15 to 48 m/s at the default.
inline constexpr float DriftFloor = 2.5f, DriftCeil = 8.0f;
// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_CONTRAST pushes the dark undersides and the lit rims apart: the
// march's shade colour is divided by it and its lit colour multiplied by its square root (1: the r119d look).
inline constexpr float DefaultContrast = 1.25f;
inline constexpr float MinContrast = 0.5f, MaxContrast = 3.0f; ///< BB_VOLUMETRIC_CLOUDS_CONTRAST's clamp
static_assert(DefaultContrast >= MinContrast && DefaultContrast <= MaxContrast);
// bbport (r119g_clouds-smear-and-cover): the smear fix (cloud_layer.comp's header says what it does) and the tint.
// BB_VOLUMETRIC_CLOUDS_SMEAR=0 turns the fix off (the r119f look), BB_VOLUMETRIC_CLOUDS_TINT 0 to 1 takes the sky's
// own colour into the clouds; BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR are live knobs with the test tools' file.
inline constexpr float DefaultTint = 0.7f; // bbport (r119i_clouds-behind-painted-sky): was 0 (grey, cool clouds over a warm dome)
inline constexpr int LightTaps = 2;         ///< density taps toward the light with the fix on (1 with it off)
inline constexpr float ShadeBase = 0.45f;   ///< the shade at a cloud's base, of its top's, with the fix on
inline constexpr float OldShadeBase = 0.25f; ///< ... with the fix off (r119f)
inline constexpr float HorizonGlow = 0.30f; ///< the shade floor x opacity for rays near the horizon, with the fix on
// bbport (r119i_clouds-behind-painted-sky): the clouds sit behind the painted sky's own shapes (cloud_layer.comp's header says how).
// BB_VOLUMETRIC_CLOUDS_PAINTED (0 to 1: how much of the opacity a painted shape takes back; 0 = off), _GLOWMAX (0 to 8: the
// cloud's own colour at most this times the sky's brightness behind it; 0 = off) and _HORIZON (degrees 0 to 60: the clouds are in
// full from this elevation up; 0 = off, the fade over 0.05 to 0.22 of the ray's slope) are live knobs with the test tools' file.
inline constexpr float DefaultPainted = 0.8f;
inline constexpr float RingNear = 12.0f, RingFar = 40.0f; ///< pixels at a 1080 line scene: the two rings' radii
inline constexpr float DefaultGlow = 1.6f, MaxGlow = 8.0f;
inline constexpr float DefaultHorizon = 30.0f, MaxHorizon = 60.0f;
inline constexpr float HorizonFromShare = 0.4f; ///< the fade-in starts at this share of the full elevation
// bbport (r119j_clouds-banding): BB_VOLUMETRIC_CLOUDS_SMOOTH (a live knob with the test tools' file): 0 to 15, a sum of the
// CL_SMOOTH_* bits (cloud_layer_layout.h); 0 is the r119i march, the default is every fix. It rides in bits 4 to 7 of the push word.
inline constexpr std::uint32_t DefaultSoften = CL_SMOOTH_ALL;
inline std::uint32_t ParseSoften(const char* text) {
    return static_cast<std::uint32_t>(
        std::lround(std::clamp(CloudShadows::Number(text, float(DefaultSoften)), 0.0f, float(CL_SMOOTH_ALL))));
}
inline std::uint32_t SoftenFlags(std::uint32_t bits) {
    return (bits & CL_SMOOTH_ALL) << CL_FLAG_SMOOTH_SHIFT;
}
inline float ParsePainted(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultPainted), 0.0f, 1.0f);
}
inline float ParseGlow(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultGlow), 0.0f, MaxGlow);
}
inline float ParseHorizon(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultHorizon), 0.0f, MaxHorizon);
}
inline float ParseCover(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultCover), 0.0f, 1.0f);
}
inline float ParseTint(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultTint), 0.0f, 1.0f);
}
/// The smear fix is on unless the text starts with 0.
inline bool ParseSmear(const char* text) {
    return text == nullptr || text[0] != '0';
}
// bbport (r119h_clouds-freeze-sheet): TOOL. BB_VOLUMETRIC_CLOUDS_FREEZE (a live knob with the test tools' header): 1
// holds the layer's cloud offsets exactly (advect and morph), anything else lets them move. BB_VOLUMETRIC_CLOUDS_MARK:
// a sheet mark, a whole number 1 to 999999 (else 0, none): a change of it makes the layer say one line with the
// counters of the MarkFrames frames that follow MarkSkipFrames frames (the counters are a frame or two old); after
// MarkTimeoutFrames frame ends it says what it has.
inline bool ParseFreeze(const char* text) {
    return text != nullptr && text[0] == '1';
}
inline constexpr std::uint32_t MarkMost = 999999u;
inline constexpr std::uint32_t MarkSkipFrames = 4, MarkFrames = 12, MarkTimeoutFrames = 240;
inline std::uint32_t ParseMark(const char* text) {
    if (text == nullptr || text[0] == '\0') return 0;
    std::uint32_t v = 0;
    for (const char* p = text; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9') return 0;
        v = v * 10u + std::uint32_t(*p - '0');
        if (v > MarkMost) return 0;
    }
    return v;
}
/// The one wind's cloud speed (m/s) held between DriftFloor and DriftCeil (a speed that is not a number counts as the
/// floor), before the SPEED knob: LayerSpeed(c, k) = HeldSpeed(c) * k.speed.
inline float HeldSpeed(float cloud_speed) {
    return cloud_speed > DriftFloor ? std::min(cloud_speed, DriftCeil) : DriftFloor;
}
inline constexpr float LayerLow = 0.51f, LayerHigh = 0.57f; ///< n's edges at cover 0.5 (clear below, full above; r119d: a band of 0.06, was 0.49 / 0.65)
inline constexpr float CoverShift = 0.30f;   ///< n's edges move by (DefaultCover - cover) x this
inline constexpr float RefFraction = 0.35f;  ///< the reference height: base + thickness x this
inline constexpr float TopBase = 0.35f, TopCover = 0.65f; ///< a column's top: TopBase + TopCover c
inline constexpr float SigmaScale = 8.0f;    ///< sigma = SigmaScale / thickness x density (1/m) (r119d: was 4)
inline constexpr float OpacityCap = 0.92f;   ///< the most opacity a ray's cloud gives (r119d: was 0.70)
inline constexpr float HorizonFrom = 0.05f, HorizonTo = 0.22f; ///< |ray y| the clouds fade in over
/// bbport (r119i): the |ray y| the clouds fade in over for a full elevation of `degrees` (from sin(0.4 x it) to sin(it)); 0 (or
/// not a number): the old HorizonFrom to HorizonTo.
inline std::array<float, 2> HorizonEdges(float degrees) {
    if (!(degrees > 0.0f)) {
        return {HorizonFrom, HorizonTo};
    }
    const float rad = degrees * 0.017453292519943295f;
    return {std::sin(HorizonFromShare * rad), std::sin(rad)};
}
inline constexpr float FadeFrom = 5000.0f, FadeTo = 10000.0f;  ///< m: the slab entry's distance fade
inline constexpr float MaxT = 12000.0f;      ///< m: no cloud is marched beyond this distance
inline constexpr float MaxChord = 3000.0f;   ///< m: the longest stretch of a ray marched in the slab
inline constexpr float Ambient = 0.50f;      ///< the sky's brightness x this at a cloud's top (0.3 of it at its base)
inline constexpr float LightGain = 3.0f;     ///< the lit share of a sample x this (x the phase) (r119d: was 2.2)
inline constexpr float Desaturate = 0.55f;   ///< the sky's tint toward its grey
inline constexpr float Forward = 3.0f;       ///< the forward scatter's gain (phase: 0.45 + this x (0.7 cos^4 + 0.3 cos^32)) (r119d: was 2.5)
inline constexpr float LitFrom = -0.02f, LitTo = 0.30f; ///< L.y the light's share rises over
inline constexpr std::uint32_t FramesPeriod = 600; ///< the periodic log line
inline constexpr std::uint32_t FramesFirst = 200;  ///< the first log line of a run (r119d: a slow place never reached 600)
inline constexpr std::uint32_t FramesNoPlace = 300; ///< frames after which "never reached" is said

/// bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT = frames between the periodic log lines, the first
/// one included (so a walk in a test gets a 'sky px share' line a step). 0 = not set or not valid: FramesFirst
/// then FramesPeriod. Whole decimal numbers only, 30 to 3000.
inline constexpr std::uint32_t ReportFramesLeast = 30, ReportFramesMost = 3000;
inline std::uint32_t ReportFramesFrom(const char* text) {
    if (text == nullptr || text[0] == '\0') return 0;
    std::uint32_t v = 0;
    for (const char* p = text; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9') return 0;
        v = v * 10u + std::uint32_t(*p - '0');
        if (v > ReportFramesMost) return 0;
    }
    return v >= ReportFramesLeast ? v : 0;
}

/// The layer's knobs (the environment, read once).
struct Knobs {
    bool on = false;
    float cover = DefaultCover;
    float density = DefaultDensity;
    float height = DefaultHeight;
    float thick = DefaultThick;
    int steps = DefaultSteps;
    float sky_z = DefaultSkyZ; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only
    float size = DefaultSize;   ///< m: the biggest octave's cell (r119c)
    float speed = DefaultSpeed; ///< times the one wind's cloud speed (r119c)
    float contrast = DefaultContrast; ///< bbport (r119e): the march's shade divided by it, its lit light times its square root
    float tint = DefaultTint;         ///< bbport (r119g): 0 to 1, how much the clouds take the painted sky's own colour
    bool smear = true;                ///< bbport (r119g): the smear fix (two light taps, shade base, horizon glow)
    float painted = DefaultPainted;   ///< bbport (r119i): the share of the opacity a painted shape takes back (0: off)
    float horizon = DefaultHorizon;   ///< bbport (r119i): degrees up where the clouds are in full (0: the old fade)
    float glow = DefaultGlow;         ///< bbport (r119i): the cloud's colour at most this x the sky's brightness (0: off)
    std::uint32_t soften = DefaultSoften; ///< bbport (r119j): the banding fixes' bits (CL_SMOOTH_*; 0: the r119i march)
    bool show = false;
};

/// BB_VOLUMETRIC_CLOUDS: on when the text starts with 1.
inline bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1';
}

/// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST from their text (the live knobs ask these
/// again every frame): a number is clamped, anything else is the default.
inline float ParseSpeed(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultSpeed), MinSpeed, MaxSpeed);
}
inline float ParseContrast(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultContrast), MinContrast, MaxContrast);
}
/// What a contrast does to the march's two colours (cloud_layer.comp): the shade side divided, the lit side times the
/// square root.
inline float ShadeScale(float contrast) {
    return 1.0f / contrast;
}
inline float LitScale(float contrast) {
    return std::sqrt(contrast);
}

inline Knobs MakeKnobs(const char* on, const char* cover, const char* density, const char* height,
                       const char* show, const char* thick = nullptr, const char* steps = nullptr,
                       const char* sky_z = nullptr, const char* size = nullptr,
                       const char* speed = nullptr, const char* contrast = nullptr,
                       const char* tint = nullptr, const char* smear = nullptr,
                       const char* painted = nullptr, const char* horizon = nullptr,
                       const char* glow = nullptr, const char* soften = nullptr) {
    Knobs k;
    k.on = ParseOn(on);
    k.cover = std::clamp(CloudShadows::Number(cover, DefaultCover), 0.0f, 1.0f);
    k.density = std::clamp(CloudShadows::Number(density, DefaultDensity), MinDensity, MaxDensity);
    k.height = std::clamp(CloudShadows::Number(height, DefaultHeight), MinHeight, MaxHeight);
    k.thick = std::clamp(CloudShadows::Number(thick, DefaultThick), MinThick, MaxThick);
    k.steps = std::clamp(static_cast<int>(std::lround(CloudShadows::Number(steps, float(DefaultSteps)))),
                         MinSteps, MaxSteps);
    k.sky_z = std::clamp(CloudShadows::Number(sky_z, DefaultSkyZ), 0.0f, MaxSkyZ);
    k.size = std::clamp(CloudShadows::Number(size, DefaultSize), MinSize, MaxSize); // bbport (r119c)
    k.speed = ParseSpeed(speed);
    k.contrast = ParseContrast(contrast); // bbport (r119e_clouds-real-sky)
    k.tint = ParseTint(tint);             // bbport (r119g_clouds-smear-and-cover)
    k.smear = ParseSmear(smear);
    k.painted = ParsePainted(painted); // bbport (r119i_clouds-behind-painted-sky)
    k.horizon = ParseHorizon(horizon);
    k.glow = ParseGlow(glow);
    k.soften = ParseSoften(soften); // bbport (r119j_clouds-banding)
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

/// cloud_layer.comp's Params block: 14 vec4 (r119g: extra), field for field.
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
    std::array<float, 4> dist{};                 ///< fade from, to (m); sky view z; contrast (r119e)
    std::array<float, 4> tone{};                 ///< ambient, light, desaturation (tint applied), forward
    std::array<float, 4> extra{};                ///< bbport (r119g): tint, light taps, shade base, horizon glow
    std::array<float, 4> paint{};                ///< bbport (r119i): painted share taken back, ring near, ring far (px at 1080 lines), glow cap
};
static_assert(sizeof(Params) == 15 * 16 && offsetof(Params, off0) == 64 &&
                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192 &&
                  offsetof(Params, extra) == 208 && offsetof(Params, paint) == 224,
              "cloud_layer.comp's Params block: 15 vec4 (r119i: paint)");

/// The push constants (16 bytes): the scene's size, the frame, the flags.
struct Push {
    std::uint32_t width = 0, height = 0;
    std::uint32_t frame = 0;
    std::uint32_t flags = 0;
};
static_assert(sizeof(Push) == 16);
static_assert(CL_FLAG_SMOOTH_SHIFT == 4 && CL_SMOOTH_JITTER == 1u && CL_SMOOTH_EDGE == 2u && CL_SMOOTH_PAINT == 4u &&
              CL_SMOOTH_GLOW == 8u && CL_SMOOTH_ALL == 15u &&
              ((CL_SMOOTH_ALL << CL_FLAG_SMOOTH_SHIFT) & CL_FLAG_SHOW) == 0u); // bbport (r119j_clouds-banding)

/// The counter words (cloud_layer_layout.h).
inline constexpr std::uint32_t CounterWords = CL_WORDS;
static_assert(CL_WORD_STEPS < CL_WORDS && CL_DIV == 2 && CL_WG == 8 && CL_FLAG_SHOW == 1);
static_assert(CL_WORD_Z_SKY == CL_WORD_STEPS + 1u && CL_WORD_Z_LAST < CL_WORDS && CL_Z_EDGE0 == 1500.0 &&
              CL_Z_EDGE1 == 1000.0 && CL_Z_EDGE2 == 500.0 && CL_Z_EDGE3 == 250.0 && CL_Z_EDGE4 == 100.0);
static_assert(CL_WORD_VISIBLE == CL_WORD_Z_LAST + 1u && CL_WORD_VISIBLE < CL_WORDS && CL_VISIBLE_ALPHA == 0.25);
static_assert(CL_WORD_DARK == CL_WORD_VISIBLE + 1u && CL_WORD_BRIGHT == CL_WORD_DARK + 1u &&
              CL_WORD_BRIGHT < CL_WORDS && CL_DARK_RATIO == 0.7 && CL_BRIGHT_RATIO == 1.4); // bbport (r119d)
static_assert(CL_WORD_PAINTED == CL_WORD_BRIGHT + 1u && CL_WORD_PAINTED < CL_WORDS && CL_WORDS == 17u &&
              CL_PAINTED_SHARE == 0.25); // bbport (r119i_clouds-behind-painted-sky)

/// The block for one frame. `inv_view`: the camera's view to world rows (3x4, translation in [3],
/// [7], [11]); `proj`: x scale, y scale (signed), z scale, z offset; `drift`: the layer's own
/// offsets (r119c; its size and edges are the knobs' and LayerLow / LayerHigh); `slope`: Slope(L) of the last light
/// seen; `jitter`: the viewport's shift this frame in pixels.
inline Params MakeParams(const std::array<float, 12>& inv_view, const std::array<float, 4>& proj,
                         const VolumetricFogNoise::Drift& drift,
                         const Knobs& knobs, const std::array<float, 3>& light, bool light_valid,
                         const std::array<float, 2>& slope, const std::array<float, 2>& jitter) {
    Params p;
    p.row0 = {inv_view[0], inv_view[1], inv_view[2], inv_view[3]};
    p.row1 = {inv_view[4], inv_view[5], inv_view[6], inv_view[7]};
    p.row2 = {inv_view[8], inv_view[9], inv_view[10], inv_view[11]};
    p.proj = proj;
    const Edges edges = CoverEdges(LayerLow, LayerHigh, knobs.cover); // bbport (r119c_clouds-gaps)
    const auto c0 = drift.Cells(0), c1 = drift.Cells(1), c2 = drift.Cells(2);
    p.off0 = {c0[0], c0[1], c0[2], 1.0f / knobs.size};
    p.off1 = {c1[0], c1[1], c1[2], edges.low};
    p.off2 = {c2[0], c2[1], c2[2], edges.high};
    p.light = {light_valid ? light[0] : 0.0f, light_valid ? light[1] : 1.0f,
               light_valid ? light[2] : 0.0f, LightShare(light, light_valid)};
    const Slab slab = MakeSlab(knobs);
    p.slab = {slab.base, slab.thick, slab.reference, slab.sigma};
    p.plane = {slope[0], slope[1], jitter[0], jitter[1]};
    const std::array<float, 2> horizon = HorizonEdges(knobs.horizon); // bbport (r119i_clouds-behind-painted-sky)
    p.look = {float(knobs.steps), OpacityCap, horizon[0], horizon[1]};
    p.dist = {FadeFrom, FadeTo, knobs.sky_z, knobs.contrast};
    p.tone = {Ambient, LightGain, Desaturate * (1.0f - knobs.tint), Forward}; // bbport (r119g): the tint
    p.extra = {knobs.tint, knobs.smear ? float(LightTaps) : 1.0f, knobs.smear ? ShadeBase : OldShadeBase,
               knobs.smear ? HorizonGlow : 0.0f};
    p.paint = {knobs.painted, RingNear, RingFar, knobs.glow}; // bbport (r119i)
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
    double visible = 0.0; ///< sky pixels with an opacity of CL_VISIBLE_ALPHA or more / sky pixels (r119c)
    double dark = 0.0;    ///< of the visible ones: picture darker than CL_DARK_RATIO of the sky behind (r119d)
    double bright = 0.0;  ///< of the visible ones: picture brighter than CL_BRIGHT_RATIO of the sky behind (r119d)
    double painted = 0.0; ///< of the marched sky pixels: those whose opacity the painted sky took CL_PAINTED_SHARE or more of (r119i)
};

inline Shares SharesOf(const Totals& t) {
    Shares s;
    const double total = double(t.words[CL_WORD_TOTAL]), sky = double(t.words[CL_WORD_SKY]),
                 hit = double(t.words[CL_WORD_HIT]);
    s.sky = total > 0.0 ? sky / total : 0.0;
    s.covered = sky > 0.0 ? double(t.words[CL_WORD_COVERED]) / sky : 0.0;
    s.opacity = sky > 0.0 ? double(t.words[CL_WORD_OPACITY]) / (256.0 * sky) : 0.0;
    s.steps = hit > 0.0 ? double(t.words[CL_WORD_STEPS]) / hit : 0.0;
    s.visible = sky > 0.0 ? double(t.words[CL_WORD_VISIBLE]) / sky : 0.0;
    const double vis = double(t.words[CL_WORD_VISIBLE]);
    s.dark = vis > 0.0 ? double(t.words[CL_WORD_DARK]) / vis : 0.0; // bbport (r119d_clouds-contrast)
    s.bright = vis > 0.0 ? double(t.words[CL_WORD_BRIGHT]) / vis : 0.0;
    s.painted = hit > 0.0 ? double(t.words[CL_WORD_PAINTED]) / hit : 0.0; // bbport (r119i_clouds-behind-painted-sky)
    return s;
}

// ---- the depth probe (r119b) -------------------------------------------------------------------

/// The depth probe's bands (cloud_layer_layout.h CL_WORD_Z_SKY..CL_WORD_Z_LAST): the first pixel of each
/// march block is counted by depth 1, then by view z (m) at or over each of DepthEdges, then the rest.
inline constexpr std::size_t DepthBands = CL_WORD_Z_LAST - CL_WORD_Z_SKY + 1;
inline constexpr std::array<float, 5> DepthEdges{CL_Z_EDGE0, CL_Z_EDGE1, CL_Z_EDGE2, CL_Z_EDGE3,
                                                 CL_Z_EDGE4};
static_assert(DepthBands == DepthEdges.size() + 2);

/// Each band's share of the march blocks (the picture's depth: where a place's sky lies).
inline std::array<double, DepthBands> DepthShares(const Totals& t) {
    std::array<double, DepthBands> out{};
    const double total = double(t.words[CL_WORD_TOTAL]);
    for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = total > 0.0 ? double(t.words[CL_WORD_Z_SKY + i]) / total : 0.0;
    }
    return out;
}

// ---- the size, the drift and the octaves' lod (r119c) --------------------------------------------

/// cloud_layer.comp's octave lod: an octave fades out as the march's step (in cells of the biggest octave)
/// nears its own cell (Ratio[octave] of that). At the shadows' 100 m size a 100 m step gave 0.60, 0.00, 0.00
/// (an even blanket); at the layer's 800 m it gives 1.00, 1.00, 0.94.
inline float Lod(float step_cells, std::size_t octave) {
    return std::clamp(1.6f - step_cells / VolumetricFogNoise::Ratio[octave], 0.0f, 1.0f);
}

/// bbport (r119d_clouds-contrast): the layer's speed (m/s): the one wind's cloud speed held between DriftFloor and
/// DriftCeil, times BB_VOLUMETRIC_CLOUDS_SPEED (a speed that is not a number counts as the floor).
inline float LayerSpeed(float cloud_speed, const Knobs& k) {
    return (cloud_speed > DriftFloor ? std::min(cloud_speed, DriftCeil) : DriftFloor) * k.speed;
}

/// The layer's drift "wind" for VolumetricFogNoise::Drift::Advance: the one wind's cloud speed (m/s) times
/// BB_VOLUMETRIC_CLOUDS_SPEED toward `heading_deg`, with the morph of the lattice's third axis for the layer's
/// size (one cell of the biggest octave in CloudShadows::MorphSeconds, whatever the speed).
inline std::array<float, 3> LayerWind(float heading_deg, float cloud_speed, const Knobs& k) {
    return CloudShadows::DriftVelocity(heading_deg, LayerSpeed(cloud_speed, k), k.size);
}

} // namespace CloudLayerParams
