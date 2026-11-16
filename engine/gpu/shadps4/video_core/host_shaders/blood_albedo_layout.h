// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r111b_footprints-pickup): the numbers of the blood rule (renderer_vulkan/blood_albedo.h
// explains it and holds the C++ function; host_shaders/footprints.comp holds the GLSL one). Plain
// #define lines only: shaders include this file through GL_GOOGLE_include_directive and C++ includes it
// as it is, so one text holds the numbers both sides use.
#ifndef BLOOD_ALBEDO_LAYOUT_H
#define BLOOD_ALBEDO_LAYOUT_H

// Linear red of a blood pixel: from BLOOD_ALBEDO_R_MIN to BLOOD_ALBEDO_R_MAX.
#define BLOOD_ALBEDO_R_MIN 0.01
#define BLOOD_ALBEDO_R_MAX 0.12
// Red is at least this many times green, and this many times blue.
#define BLOOD_ALBEDO_RED_OVER_GREEN 2.5
#define BLOOD_ALBEDO_RED_OVER_BLUE 2.5

#endif
