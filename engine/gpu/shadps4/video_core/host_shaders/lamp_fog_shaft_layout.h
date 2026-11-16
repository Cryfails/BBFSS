// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r106_lamp-fog-shaft-cap): the lamp fog shafts' table (VolumetricLight's shaft_table, one
// upload a frame), shared by lamp_fog_shaft_map.comp, point_volumetric.comp's SHAFTS builds and
// lamp_fog_shaft_cap.h. Plain #define lines only: the shaders include this file through
// GL_GOOGLE_include_directive and C++ includes it as it is, so one text holds the numbers both
// sides use (as lamp_wind_layout.h does for the wind words).
#ifndef LAMP_FOG_SHAFT_LAYOUT_H
#define LAMP_FOG_SHAFT_LAYOUT_H

// Words 0-11: the composite camera's view to world matrix, 3x4 rows (the march turns the direction
// from a light to a fog sample into the maps' world directions; the translation is not used).
#define SHAFT_TABLE_TO_WORLD 0u
// Words 16-79: one word per light record k of the lamp fog's list: the map layer in the low 8 bits
// (SHAFT_LAYER_MASK), the shadow's strength 0 to 1 as 16 bits in the high half (0: the record is
// marched unshadowed and reads no map).
#define SHAFT_TABLE_RECORDS 16u
#define SHAFT_LAYER_MASK 255u
// From word 80: the frame's map jobs, SHAFT_JOB_WORDS words each: the light's centre (view space,
// this frame), the reach in metres, the layer to write; the other 3 words are 0.
#define SHAFT_TABLE_JOBS 80u
#define SHAFT_JOB_WORDS 8u
// Words in all: the jobs of 64 maps (LampFogShafts::MaxMaps) after word 80.
#define SHAFT_TABLE_WORDS 592u
// What a texel keeps where its ray hit nothing (the largest finite R16F): free to any distance.
#define SHAFT_FREE 65504.0
// bbport (r106c_shaft-march-cheaper): the fast march (BB_LAMP_FOG_SHAFTS_FAST): a sample whose light
// is under this much of the fog's output (linear, as the march writes it) reads no map and takes the
// answer of the sample before it (1 if none): 1/16384, 0.2 of an 8-bit level near black.
#define SHAFT_FAST_SKIP 6.1035156e-5
// bbport (r80b_shafts-smooth-visible): the bits of the SHAFTS march's push word `shaft_fast`
// (lamp_fog_shaft_smooth.h): bit 0 the fast march (r106c), the smoothing level (0 to 2) from bit
// SHAFT_PUSH_SMOOTH_SHIFT (2 bits), the gain in 1/SHAFT_PUSH_GAIN_UNIT from bit SHAFT_PUSH_GAIN_SHIFT
// (8 bits; 0 reads as 1), a frame counter from bit SHAFT_PUSH_FRAME_SHIFT (the noise's animation).
#define SHAFT_PUSH_SMOOTH_SHIFT 1u
#define SHAFT_PUSH_GAIN_SHIFT 8u
#define SHAFT_PUSH_FRAME_SHIFT 16u
#define SHAFT_PUSH_GAIN_UNIT 32.0

#endif
