// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r81_sun-fog-no-rt): what the sun fog's area light gate shares between its shaders
// (volumetric_area_gate.comp, the AREA builds of volumetric_light.comp) and the engine
// (renderer_vulkan/volumetric_area_gate.h, VolumetricLight::AreaGate). Plain #define lines only:
// the shaders include this file through GL_GOOGLE_include_directive and C++ includes it as it is,
// so one text holds every number both sides use.
#ifndef VOLUMETRIC_AREA_LAYOUT_H
#define VOLUMETRIC_AREA_LAYOUT_H

// The camera pass: one workgroup, a thread per record of the game's directional lighting table
// (the table has 225; VolumetricLight::Tint reads at most 256) and per point of a 16x16 grid over
// the screen.
#define AREA_GROUP 256u
#define AREA_GRID_X 16u
#define AREA_GRID_Y 16u
#define AREA_RECORDS 256u
// A record of the table: 18 vec4 (72 floats, 288 bytes). Rows 0-3: direction and width of lights
// 0-3; rows 4-7: their diffuse colours. The sun share is read from light 0's colour (dwords 16-18),
// the colour VolumetricLight::Tint's TINT build takes for the fog.
#define AREA_RECORD_FLOATS 72u
#define AREA_RECORD_COLOUR 16u
// The rows the probe copies of each record: 0-7 (directions and diffuse colours), 32 floats.
#define AREA_PROBE_ROW_FLOATS 32u

// A record's weight: smoothstep(AREA_SUN_LO, AREA_SUN_HI, its light 0 luminance over the
// brightest record's), the fallback record (the built-in white one) left out of the brightest and
// weighed 1. A record as bright as half the brightest or more weighs 1 (no change).
#define AREA_SUN_LO 0.15
#define AREA_SUN_HI 0.5
// The beam test: the mean atlas visibility along the march (the share of its samples in sun).
// At AREA_BEAM_LO or less the lit air is a beam between shadows and is kept whatever the light
// set; at AREA_BEAM_HI or more it is air the atlas has no roof over and only the light set keeps
// it; in between a smooth mix.
#define AREA_BEAM_LO 0.35
#define AREA_BEAM_HI 0.65
// The far part of a ray: its samples in the march's last this many metres (the march ends at the
// surface, at the reach or at the shadow distance, whichever is nearest); they take the weight of
// the light set of the surface the pixel shows, the nearer ones the camera's. A ray to the sky
// takes the camera's for all of it.
#define AREA_FAR_METRES 6.0
// The camera's weight: the grid points' record weights, each weighed by 1 - depth (about the
// inverse of its distance); with less than this summed weight (all sky) the camera weighs 1.
#define AREA_CAMERA_EPS 1e-6

// Push word `flags`: the lighting table and texture 0 of the directional draw are there; the
// camera pass also writes the probe's words (counts and rows).
#define AREA_FLAG_RECORDS 1u
#define AREA_FLAG_PROBE 2u
// bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE=2. With bit AREA_NEAR_MARK of the march's
// push word `cascades` its AREA builds mark a surface nearer than AREA_NEAR_METRES by b's sign,
// b = -(b + AREA_NEAR_FLOOR) (the smallest normal half float, so a b of 0 stays negative in the fog
// image); with AREA_FLAG_NEAR the camera pass leaves those points out of the camera's weight (all
// of them near: every point counts) and the apply pass weighs their rays with the camera's weight.
// AREA_FLAG_DUAL: the march was a DUAL build (b is the energy the ray traced gate's wider answer
// lets through, kept whole; no beam test).
#define AREA_FLAG_NEAR 4u
#define AREA_FLAG_DUAL 8u
#define AREA_NEAR_METRES 4.0
#define AREA_NEAR_FLOOR 6.103515625e-05
#define AREA_NEAR_MARK 0x1000000u

// The state buffer, 32-bit words. Read by the apply pass: AREA_STATE_CAMERA and the weights.
#define AREA_STATE_CAMERA 0u        // float: the camera's weight, faded (VolumetricLight::Tint's fade)
#define AREA_STATE_CAMERA_NOW 1u    // float: this frame's, before the fade
#define AREA_STATE_BEST 2u          // float: the brightest record's light 0 luminance
#define AREA_STATE_SURFACE 3u       // uint: grid points on a surface (probe)
#define AREA_STATE_SKY 4u           // uint: grid points at the sky (probe)
#define AREA_STATE_BEFORE 5u        // float: the grid's fog before the gate (probe)
#define AREA_STATE_AFTER 6u         // float: and after it (probe)
#define AREA_STATE_LIT 7u           // float: the grid's lit share along the view, fog-weighted (probe)
#define AREA_STATE_RECORD_COUNT 8u  // uint: records weighed
#define AREA_STATE_NEAR 9u          // uint: grid surface points left out as near (r115, probe)
#define AREA_STATE_WEIGHTS 16u      // AREA_RECORDS floats: each record's weight
#define AREA_STATE_COUNTS 272u      // AREA_RECORDS uints: grid points on each record (probe)
#define AREA_STATE_ROWS 528u        // AREA_RECORDS x AREA_PROBE_ROW_FLOATS floats (probe)
#define AREA_STATE_WORDS 8720u

#endif
