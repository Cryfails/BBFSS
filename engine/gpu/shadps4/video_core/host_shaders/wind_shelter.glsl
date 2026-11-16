// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r117_wind-shelter): THE reader of the wind shelter field, for every compute shader that
// takes the wind (stage 1: wind_shelter.comp's counters and test view; the sun fog's march and the
// particles read it with this function in later stages). gpu/shim/bbport_wind_shelter.h's
// BbWindShelter::At is this function in C++, operation for operation (a lerp is a + (b - a) t), and
// the two plant shader emitters (emit_spirv_special.cpp, lift_stage.cpp) emit the same operations.
//
// The field lives in the sway region's buffer (wind_shelter_layout.h says where and how): `r` is a
// buffer reference to the region's first word (the sway words' base address, which is the motion
// params buffer's address + MotionVectors::ParamsCapacity * 32 bytes). The shader declares nothing
// else. Needs GL_EXT_buffer_reference and wind_shelter_layout.h.
//
// wind_shelter_at(r, p): the share (0-1) of the outside wind that is taken away at the world point
// p: 0 in the open, outside the field (further than half of WS_N cells from the camera) or where
// the field was never written; 1 indoors. It is the field's bilinear value times the vertical band
// (the field is a map at the camera's level: full within WS_BAND - WS_BAND_SOFT m of the camera's
// height, 0 beyond WS_BAND) times the strength BB_WIND_SHELTER. The wind there is
// (1 - wind_shelter_at) times the open wind.

layout(buffer_reference, std430, buffer_reference_align = 4) buffer WindShelterRegion {
    uint w[];
};

float wind_shelter_lerp(float a, float b, float t) {
    return a + (b - a) * t;
}

float wind_shelter_at(WindShelterRegion r, vec3 p) {
    const uint at = WS_BLOCK_WORD;
    if (!(uintBitsToFloat(r.w[at]) > 0.5)) {
        return 0.0;
    }
    const float ox = uintBitsToFloat(r.w[at + 1u]);
    const float oz = uintBitsToFloat(r.w[at + 2u]);
    const float inv_cell = uintBitsToFloat(r.w[at + 3u]);
    const float n = float(WS_N); // (header word 4 holds the same number; not read)
    const float ref_y = uintBitsToFloat(r.w[at + 5u]);
    const float strength = uintBitsToFloat(r.w[at + 6u]);
    const float band = uintBitsToFloat(r.w[at + 7u]);
    float fx = (p.x - ox) * inv_cell - 0.5;
    float fz = (p.z - oz) * inv_cell - 0.5;
    const float x0 = floor(fx);
    const float z0 = floor(fz);
    if (!(x0 >= 0.0 && z0 >= 0.0 && x0 < n - 1.0 && z0 < n - 1.0)) {
        return 0.0;
    }
    fx -= x0;
    fz -= z0;
    const uint cell = at + WS_HEADER_WORDS + uint(z0) * uint(n) + uint(x0);
    const float a = uintBitsToFloat(r.w[cell]);
    const float b = uintBitsToFloat(r.w[cell + 1u]);
    const float c = uintBitsToFloat(r.w[cell + uint(n)]);
    const float d = uintBitsToFloat(r.w[cell + uint(n) + 1u]);
    const float s = wind_shelter_lerp(wind_shelter_lerp(a, b, fx), wind_shelter_lerp(c, d, fx), fz);
    const float level = clamp((band - abs(p.y - ref_y)) * (1.0 / WS_BAND_SOFT), 0.0, 1.0);
    return s * level * strength;
}
