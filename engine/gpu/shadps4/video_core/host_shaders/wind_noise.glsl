// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r82_wind-stage1): the GLSL copy of the fog noise, the march step and the view helpers of
// gpu/shim/bbport_wind.h (BbWind::Hash3, Unit, Fade, Lerp, Noise3, Field, Density, MarchStep,
// ViewToWorld, ViewShade). It repeats the C++ operation for operation, so that both compute the
// same formula: as the header asks, a lerp is a + (b - a) t (not mix()), the field DIVIDES the
// world point by 12, 6 and 4.5 m, and a cell is int(floor(x)) & 255 (the same value mod 256 as
// BbWind::Cell for |x| < 2^31). The floats are not bit for bit the CPU's: Vulkan lets a GPU
// division be 2.5 ulp off and a driver may turn x / 12 into a multiply, which can move floor() at
// a cell edge; the value noise is continuous there, so N changes only by that rounding.
// tests/test_wind_noise.cpp runs this file on the GPU: the pinned values within 1e-6, Field
// within 1e-4 of the C++ elsewhere. Only 32-bit unsigned integer and float operations. Included
// by volumetric_light.comp (WIND), point_volumetric.comp (WIND; bbport (r88_wind-lamp-fog)) and
// wind_noise_test.comp.

// PCG3D of the cell, each component & 255 (the lattice repeats every 256 cells); its first
// component.
uint wind_hash3(ivec3 cell) {
    uvec3 v = uvec3(cell & 255) * 1664525u + 1013904223u;
    v.x += v.y * v.z;
    v.y += v.z * v.x;
    v.z += v.x * v.y;
    v ^= v >> 16u;
    return v.x + v.y * v.z;
}

// A hash's top 24 bits as a float in [0, 1).
float wind_unit(uint h) {
    return float(h >> 8u) * (1.0 / 16777216.0);
}

// Quintic fade u^3 (u (6u - 15) + 10).
float wind_fade(float u) {
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0);
}

float wind_lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

// 3D value noise in [0, 1): the eight corners' wind_unit(wind_hash3), trilinear with the quintic
// fade. 0.5 for a non-finite input.
float wind_noise3(vec3 x) {
    if (any(isnan(x)) || any(isinf(x))) return 0.5;
    vec3 f = floor(x);
    ivec3 i = ivec3(f);
    float ux = wind_fade(x.x - f.x), uy = wind_fade(x.y - f.y), uz = wind_fade(x.z - f.z);
    float x00 = wind_lerp(wind_unit(wind_hash3(i)), wind_unit(wind_hash3(i + ivec3(1, 0, 0))), ux);
    float x10 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 1, 0))),
                          wind_unit(wind_hash3(i + ivec3(1, 1, 0))), ux);
    float x01 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 0, 1))),
                          wind_unit(wind_hash3(i + ivec3(1, 0, 1))), ux);
    float x11 = wind_lerp(wind_unit(wind_hash3(i + ivec3(0, 1, 1))),
                          wind_unit(wind_hash3(i + ivec3(1, 1, 1))), ux);
    return wind_lerp(wind_lerp(x00, x10, uy), wind_lerp(x01, x11, uy), uz);
}

// The fog noise N at world point p (m), in [0, 1): 0.65 of octave 1 (12 m across, 6 m up) plus
// 0.35 of octave 2 (4.5 m), each shifted by its offset (cells, BbWind::Snapshot off1 and off2).
float wind_field(vec3 p, vec3 off1, vec3 off2) {
    float n1 = wind_noise3(vec3(p.x / 12.0 - off1.x, p.y / 6.0 - off1.y, p.z / 12.0 - off1.z));
    float n2 = wind_noise3(vec3(p.x / 4.5 - off2.x, p.y / 4.5 - off2.y, p.z / 4.5 - off2.z));
    return 0.65 * n1 + 0.35 * n2;
}

// The fog density factor m = max(0, 1 + contrast (2N - 1)); exactly 1 at contrast 0.
float wind_density(vec3 p, vec3 off1, vec3 off2, float contrast) {
    return max(0.0, 1.0 + contrast * (2.0 * wind_field(p, off1, off2) - 1.0));
}

// A view space point to world space with the 3x4 view to world matrix as rows (translation in
// .w; CameraMotion::PassMatrices().inv_view).
vec3 wind_view_to_world(vec4 r0, vec4 r1, vec4 r2, vec3 v) {
    vec4 h = vec4(v, 1.0);
    return vec3(dot(r0, h), dot(r1, h), dot(r2, h));
}

// m at view space point v: wind_density at its world point (offsets in cells, the contrast).
float wind_factor_rows(vec4 r0, vec4 r1, vec4 r2, vec3 v, vec3 off1, vec3 off2, float contrast) {
    return wind_density(wind_view_to_world(r0, r1, r2, v), off1, off2, contrast);
}

// One step of the sun fog march through a fog of density `density` * m: in-scatter at t (m) seen
// through the optical depth density * (t + excess + (m - 1) jitter ds), then excess += (m - 1) ds.
// That is the plan's tau + s jitter ds with tau = the sum of s ds before this step (s = density m),
// written so that at m = 1 every added term is +0: in IEEE arithmetic the step then gives the
// floats of the march without wind, exp(-density * t) * density * ds * vis (BbWind::MarchStep,
// wind-test m). A GPU driver may fuse the multiply-adds of the two expressions differently, so on
// the GPU it is within 1e-6 (relative) of them, not bit for bit (wind-noise-test).
void wind_march_step(inout float energy, inout float excess, float density, float t, float ds,
                     float jitter, float m, float vis) {
    energy += exp(-density * (t + excess + (m - 1.0) * jitter * ds)) * (density * m) * ds * vis;
    excess += (m - 1.0) * ds;
}

// The march step at view space distance t along the unit view ray `ray`: m taken at ray * t,
// the point the step's light is taken at (volumetric_light.comp passes visibility(ray * t)).
void wind_ray_step(inout float energy, inout float excess, float density, vec3 ray, float t,
                   float ds, float jitter, float vis, vec4 r0, vec4 r1, vec4 r2, vec3 off1,
                   vec3 off2, float contrast) {
    wind_march_step(energy, excess, density, t, ds, jitter,
                    wind_factor_rows(r0, r1, r2, ray * t, off1, off2, contrast), vis);
}

// The grey of the BB_WIND_VIEW=1 test view, 0-1: m stretched over 1 - contrast to 1 + contrast
// (N where m is not clipped at 0); 0.5 at contrast 0.
float wind_view_shade(float m, float contrast) {
    if (!(contrast > 0.0)) return 0.5;
    return clamp((m - (1.0 - contrast)) / (2.0 * contrast), 0.0, 1.0);
}
