// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r80b_shafts-smooth-visible): the lamp fog shafts smoother and stronger (point_volumetric.comp's
// SHAFTS builds; BB_LAMP_FOG_SHAFTS on only). The owner (2026-11-16, build 72): the shafts "just a bit hard
// see and maybe a little blocky like our shadows used to be". The maps are 128x128 octahedral, one hit
// distance a texel, and the march took the four texels around a sample with a step each: a quarter-step
// staircase one map texel (1.4 to 2.8 degrees) wide, and 6 samples a half chord whose lit/dark slices
// showed as bands. No Vulkan here: this header holds the two knobs, the word that carries them to the
// shader, the log lines and counters (tests/test_lamp_fog_shaft_smooth.cpp builds it alone).
//
// BB_LAMP_FOG_SHAFTS_SMOOTH (one digit; unset, empty or other text: 2):
//   0  the march of r106c (four texels, a step each, the sample at the middle of its segment)
//   1  the same four texels weighted bilinearly (the share of lit texels by the sample's place between
//      the texel centres: a straight soft edge, not a staircase); the same texture reads
//   2  1 plus a per-pixel, per-frame jitter (interleaved gradient noise, a new pattern each frame) of the
//      sample's place along its segment (0.15 to 0.85 of the segment's angle) and of the map lookup by
//      up to half a texel each way; DLSS / the temporal pass integrate it over frames
// BB_LAMP_FOG_SHAFTS_GAIN (decimal number, 0.25 to 4; unset, empty or other text: 1.35): the lamp fog's
// brightness while the shafts run (multiplied onto every shafts-march light's contribution, shadowed
// or not, so a lamp does not jump when it falls out of the ray budget); 1 is r106c's brightness.
// Nothing here casts a ray or reads a map texel more than the march read before.
//
// The word: point_volumetric.comp's push constant `shaft_fast` (r106c, was 0 or 1) now carries, with
// bit 0 unchanged, the smoothing level (bits 1-2), the gain in 1/32 (bits 8-15) and the frame counter
// (bits 16-31; the shader uses 6 bits): the push block keeps its 24 bytes. With SMOOTH=0 and GAIN=1
// the shader computes what r106c computed (the gain bits 0 also read as 1).
// With the test tools' live knobs (BB_LIVE_KNOBS_FILE; gpu/shim/bbport_live_knobs.h, test tools only)
// both knobs are read again at every call, so one running game can compare them at one camera; without
// them each is read once.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "../host_shaders/lamp_fog_shaft_layout.h"
// A test that does not link the runtime defines BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE before this include.
#if !defined(BB_LAMP_FOG_SHAFT_SMOOTH_NO_LIVE) && __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_FOG_SHAFT_SMOOTH_LIVE 1
#else
#define BB_LAMP_FOG_SHAFT_SMOOTH_LIVE 0
#endif

namespace Vulkan::LampFogShaftSmooth {

inline constexpr std::uint32_t DefaultSmooth = 2;
inline constexpr float DefaultGain = 1.35f;
inline constexpr float MinGain = 0.25f;
inline constexpr float MaxGain = 4.0f;

/// The smoothing knob's text: one digit 0 to 2; anything else (also not set) is DefaultSmooth.
inline std::uint32_t ParseSmooth(const char* text) {
    if (text && text[0] >= '0' && text[0] <= '2' && text[1] == '\0') {
        return std::uint32_t(text[0] - '0');
    }
    return DefaultSmooth;
}

/// The gain knob's text: a finite decimal number, clamped to MinGain..MaxGain; anything else
/// (also not set) is DefaultGain.
inline float ParseGain(const char* text) {
    if (!text || !text[0]) {
        return DefaultGain;
    }
    char* end = nullptr;
    const double value = std::strtod(text, &end);
    if (end == text || *end != '\0' || !std::isfinite(value)) {
        return DefaultGain;
    }
    return float(std::clamp(value, double(MinGain), double(MaxGain)));
}

/// BB_LAMP_FOG_SHAFTS_SMOOTH now.
inline std::uint32_t Smooth() {
#if BB_LAMP_FOG_SHAFT_SMOOTH_LIVE
    static BbLiveKnobs::Knob<std::uint32_t> knob{"BB_LAMP_FOG_SHAFTS_SMOOTH", ParseSmooth};
    return knob.Get();
#else
    static const std::uint32_t value = ParseSmooth(std::getenv("BB_LAMP_FOG_SHAFTS_SMOOTH"));
    return value;
#endif
}

/// BB_LAMP_FOG_SHAFTS_GAIN now.
inline float Gain() {
#if BB_LAMP_FOG_SHAFT_SMOOTH_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_LAMP_FOG_SHAFTS_GAIN", ParseGain};
    return knob.Get();
#else
    static const float value = ParseGain(std::getenv("BB_LAMP_FOG_SHAFTS_GAIN"));
    return value;
#endif
}

/// The gain as the shader's 8 bits (units of 1/SHAFT_PUSH_GAIN_UNIT; never 0, which the shader reads as 1).
inline std::uint32_t GainBits(float gain) {
    const long bits = std::lround(double(gain) * SHAFT_PUSH_GAIN_UNIT);
    return std::uint32_t(std::clamp(bits, 8L, 255L));
}

/// The shader's word (see the header's text).
inline std::uint32_t PackWord(std::uint32_t fast, std::uint32_t smooth, float gain,
                              std::uint32_t frame) {
    return (fast & 1u) | ((smooth & 3u) << SHAFT_PUSH_SMOOTH_SHIFT) |
           (GainBits(gain) << SHAFT_PUSH_GAIN_SHIFT) | ((frame & 0xFFFFu) << SHAFT_PUSH_FRAME_SHIFT);
}

/// The period of PrintLine's line, in lamp fog frames (RecordLampFog's own 600).
inline constexpr std::uint32_t LinePeriod = 600;

/// The counts since the last PrintLine.
struct Totals {
    std::uint64_t frames = 0;    ///< frames that ran the shafts' march
    std::uint64_t level[3] = {}; ///< of them at each smoothing level
};
inline Totals totals;
inline std::uint32_t frame_counter = 0;
inline int told_smooth = -1; ///< the level the last once-line said; -1: none yet
inline float told_gain = -1.0f;

/// One frame of the shafts' march (VolumetricLight::RecordShafts), given r106c's flag (1 fast, 0 old):
/// the once-line when a value is new, the counts, the pushed word.
inline std::uint32_t Pack(std::uint32_t fast) {
    const std::uint32_t smooth = Smooth();
    const float gain = Gain();
    if (told_smooth != int(smooth) || told_gain != gain) {
        told_smooth = int(smooth);
        told_gain = gain;
        std::printf("Volumetric lighting (r80b): shaft smoothing %u (BB_LAMP_FOG_SHAFTS_SMOOTH: 0 "
                    "four-texel steps as before, 1 bilinear map filter, 2 bilinear plus per-pixel "
                    "per-frame jitter of the samples), shaft gain %.2f (BB_LAMP_FOG_SHAFTS_GAIN); no "
                    "extra rays, no extra map reads\n",
                    smooth, double(gain));
    }
    ++totals.frames;
    ++totals.level[std::min<std::uint32_t>(smooth, 2u)];
    return PackWord(fast, smooth, gain, frame_counter++);
}

/// The counts' line (every LinePeriod lamp fog frames, beside the r106c line), then the counts reset.
inline void PrintLine() {
    std::printf("Volumetric lighting (r80b): shaft smoothing over %llu frames: level 0 in %llu, 1 in "
                "%llu, 2 in %llu; gain now %.2f; extra map rays 0, extra map reads 0\n",
                static_cast<unsigned long long>(totals.frames),
                static_cast<unsigned long long>(totals.level[0]),
                static_cast<unsigned long long>(totals.level[1]),
                static_cast<unsigned long long>(totals.level[2]), double(Gain()));
    totals = {};
}

} // namespace Vulkan::LampFogShaftSmooth
