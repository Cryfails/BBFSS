// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r94_fog-noise): the sun fog's world anchored noise, for the NOISE builds of
// volumetric_light.comp (BB_FOG_NOISE above 0 only). Included after that file's push block: it
// reads noise_row0-2 (the G-buffer pass's view to world matrix at the Integrate call, 3x4 rows)
// and noise_off0-2 (each octave's offset in lattice cells in xyz; in w the amplitude, the gain and
// 1 / scale), the words of VolumetricFogNoise::Tail. The numbers are fog_noise_layout.h's, shared
// with renderer_vulkan/volumetric_fog_noise.h, which moves the offsets with the wind (Drift) and
// makes the amplitude and gain; its Factor is fog_noise_m's last line and its LatticePoint is
// fog_noise_cells applied to the scaled world point. No texture: a 32-bit integer hash per lattice
// corner, value noise with a quintic fade.
#include "fog_noise_layout.h"

// lowbias32 of a corner's packed cell (x | y << 8 | z << 16, each & 255) plus the seed, its top 24
// bits as a float in [0, 1).
float fog_noise_corner(uint packed) {
    uint h = packed + FOG_NOISE_SEED;
    h ^= h >> 16u;
    h *= 0x7feb352du;
    h ^= h >> 15u;
    h *= 0x846ca68bu;
    h ^= h >> 16u;
    return float(h >> 8u) * (1.0 / 16777216.0);
}

// 3D value noise in [0, 1): the eight corners of x's cell, trilinear with the quintic fade
// u^3 (u (6u - 15) + 10). The lattice repeats every FOG_NOISE_PERIOD cells along each axis.
float fog_noise_value(vec3 x) {
    vec3 f = floor(x);
    vec3 u = x - f;
    u = u * u * u * (u * (u * 6.0 - 15.0) + 10.0);
    uvec3 a = uvec3(ivec3(f) & (FOG_NOISE_PERIOD - 1));
    uvec3 b = (a + 1u) & uint(FOG_NOISE_PERIOD - 1);
    uint y0 = a.y << 8u, y1 = b.y << 8u, z0 = a.z << 16u, z1 = b.z << 16u;
    float x00 = mix(fog_noise_corner(a.x | y0 | z0), fog_noise_corner(b.x | y0 | z0), u.x);
    float x10 = mix(fog_noise_corner(a.x | y1 | z0), fog_noise_corner(b.x | y1 | z0), u.x);
    float x01 = mix(fog_noise_corner(a.x | y0 | z1), fog_noise_corner(b.x | y0 | z1), u.x);
    float x11 = mix(fog_noise_corner(a.x | y1 | z1), fog_noise_corner(b.x | y1 | z1), u.x);
    return mix(mix(x00, x10, u.y), mix(x01, x11, u.y), u.z);
}

// An octave's lattice point of q (the world point times 1 / scale, its y also times
// FOG_NOISE_SQUASH): turned by the octave's yaw about the up axis, divided by its ratio.
vec3 fog_noise_cells(vec3 q, float c, float s, float ratio) {
    return vec3(c * q.x - s * q.z, q.y, s * q.x + c * q.z) / ratio;
}

// bbport (r105_cloud-shadows): cloud_shadow.comp defines FOG_NOISE_VALUE_ONLY to take the value
// noise and the lattice turn above without the two functions below, which read r94's push
// words; the NOISE builds of volumetric_light.comp never define it.
#ifndef FOG_NOISE_VALUE_ONLY
// m, the fog density factor at view space point v, t metres from the camera along the march's
// ray: 1 + a clamp(2 g d, -1, 1), d the octaves' weighted sum of (N - 0.5) at their lattice points
// minus their offsets, the finest octave faded out from FOG_NOISE_FINE_FROM to FOG_NOISE_FINE_TO
// scales away. m is odd in d around 1 and d is symmetric around 0, so the mean of m is 1. A point
// that is not finite gives 1.
float fog_noise_m(vec3 v, float t) {
    vec4 h = vec4(v, 1.0);
    float inv_scale = noise_off2.w;
    vec3 q = vec3(dot(noise_row0, h), dot(noise_row1, h) * float(FOG_NOISE_SQUASH),
                  dot(noise_row2, h)) * inv_scale;
    if (any(isnan(q)) || any(isinf(q))) return 1.0;
    float d = float(FOG_NOISE_WEIGHT0) *
              (fog_noise_value(fog_noise_cells(q, float(FOG_NOISE_YAW_COS0), float(FOG_NOISE_YAW_SIN0),
                                               float(FOG_NOISE_RATIO0)) - noise_off0.xyz) - 0.5);
    d += float(FOG_NOISE_WEIGHT1) *
         (fog_noise_value(fog_noise_cells(q, float(FOG_NOISE_YAW_COS1), float(FOG_NOISE_YAW_SIN1),
                                          float(FOG_NOISE_RATIO1)) - noise_off1.xyz) - 0.5);
    float fine = clamp((float(FOG_NOISE_FINE_TO) - t * inv_scale) /
                       float(FOG_NOISE_FINE_TO - FOG_NOISE_FINE_FROM), 0.0, 1.0);
    if (fine > 0.0) {
        d += float(FOG_NOISE_WEIGHT2) * fine *
             (fog_noise_value(fog_noise_cells(q, float(FOG_NOISE_YAW_COS2),
                                              float(FOG_NOISE_YAW_SIN2), float(FOG_NOISE_RATIO2)) -
                              noise_off2.xyz) - 0.5);
    }
    // bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 (marked by a gain below 0; r94's
    // gain is 2 or more): banks, m = A + B smoothstep(FOG_NOISE_BANK_FROM, FOG_NOISE_BANK_TO, d)
    // with A = noise_off0.w (the clear air's m) and B = -noise_off1.w (C++: BankFactor)
    if (noise_off1.w < 0.0) {
        return noise_off0.w -
               noise_off1.w * smoothstep(float(FOG_NOISE_BANK_FROM), float(FOG_NOISE_BANK_TO), d);
    }
    return 1.0 + noise_off0.w * clamp(2.0 * noise_off1.w * d, -1.0, 1.0);
}

// The factor of a march sample's in-scattered light: m at the sample's point p (view space), t
// metres along the ray, where the sample is lit (v > 0); 1 elsewhere, where it adds no light, so m
// is not taken there. The march keeps its extinction at the mean density (exp(-density t)), so
// the mean light of the fog stays the plain march's.
float fog_noise_weight(float v, vec3 p, float t) {
    if (!(v > 0.0)) return 1.0;
    return fog_noise_m(p, t);
}
#endif // FOG_NOISE_VALUE_ONLY (bbport r105_cloud-shadows)
