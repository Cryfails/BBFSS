// SPDX-License-Identifier: GPL-3.0-or-later
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
