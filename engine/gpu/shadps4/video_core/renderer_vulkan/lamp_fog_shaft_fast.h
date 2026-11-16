// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r106c_shaft-march-cheaper): the lamp fog shafts' cheaper march (point_volumetric.comp's
// inscatterShadowedFast; BB_LAMP_FOG_SHAFTS on only). Each pixel, each light whose sphere the view ray
// crosses, 2 halves x Segments samples (lamp_fog_shafts.h), each a 4-texel textureGather of the
// light's map. The fast march reads the map at every second sample of a half (and the last), at an odd
// sample between two only where the two answers differ, and not at all where the sample's light is
// under SHAFT_FAST_SKIP (lamp_fog_shaft_layout.h) of the fog's output. No Vulkan here: this header
// holds the knob, its log lines and counters (tests/test_lamp_fog_shaft_fast.cpp builds it alone).
//
// BB_LAMP_FOG_SHAFTS_FAST: "0" is the march of r106 (every sample reads the map); unset, empty or any
// other text is on (the default: it is an optimization). With the test tools' live knobs
// (BB_LIVE_KNOBS_FILE; gpu/shim/bbport_live_knobs.h, test tools only) it is read again at every call,
// so one running game can compare the two marches at one camera; without them it is read once.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "../host_shaders/lamp_fog_shaft_layout.h"
// A test that does not link the runtime defines BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE before this include.
#if !defined(BB_LAMP_FOG_SHAFTS_FAST_NO_LIVE) && __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_FOG_SHAFTS_FAST_LIVE 1
#else
#define BB_LAMP_FOG_SHAFTS_FAST_LIVE 0
#endif

namespace Vulkan::LampFogShaftFast {

/// The knob's text: exactly "0" is off, anything else (also not set) is on.
inline bool ParseFast(const char* text) {
    return !(text && text[0] == '0' && text[1] == '\0');
}

/// BB_LAMP_FOG_SHAFTS_FAST now.
inline bool Fast() {
#if BB_LAMP_FOG_SHAFTS_FAST_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_LAMP_FOG_SHAFTS_FAST", ParseFast};
    return knob.Get();
#else
    static const bool value = ParseFast(std::getenv("BB_LAMP_FOG_SHAFTS_FAST"));
    return value;
#endif
}

/// The period of PrintLine's line, in lamp fog frames (RecordLampFog's own 600).
inline constexpr std::uint32_t LinePeriod = 600;

/// An upper bound on the map reads of one frame: every light over every pixel, 2 halves of
/// `segments` samples (the lights whose sphere the view ray misses read none; the fast march reads
/// fewer).
inline std::uint64_t TapsBound(std::uint32_t lights, std::uint32_t segments, std::uint32_t w,
                               std::uint32_t h) {
    return std::uint64_t(lights) * 2u * segments * w * h;
}

/// The counts since the last PrintLine.
struct Totals {
    std::uint64_t frames = 0;  ///< frames that ran the shafts' march
    std::uint64_t fast = 0;    ///< of them with the fast march
    std::uint64_t bound = 0;   ///< sum of TapsBound over them
    std::uint32_t lights_most = 0, segments = 0, width = 0, height = 0;
};
inline Totals totals;
inline int told = -1; ///< the value the last once-line said (1 fast, 0 old); -1: none yet

/// One frame of the shafts' march (VolumetricLight::RecordShafts): the pushed flag (1 fast, 0 old),
/// the once-line when the value is new, the counts.
inline std::uint32_t Frame(std::uint32_t lights, std::uint32_t segments, std::uint32_t w,
                           std::uint32_t h) {
    const bool fast = Fast();
    if (told != (fast ? 1 : 0)) {
        told = fast ? 1 : 0;
        if (fast) {
            std::printf("Volumetric lighting (r106c): shaft march fast (BB_LAMP_FOG_SHAFTS_FAST): the "
                        "maps are read at every second sample, at the others only where the two "
                        "beside differ; light under 1/16384 reads none; 2 halves x %u samples a "
                        "light and pixel, %ux%u pixels, %u lights now\n",
                        segments, w, h, lights);
        } else {
            std::printf("Volumetric lighting (r106c): shaft march old (BB_LAMP_FOG_SHAFTS_FAST=0): "
                        "every sample reads the maps, as r106; 2 halves x %u samples a light and "
                        "pixel, %ux%u pixels, %u lights now\n",
                        segments, w, h, lights);
        }
    }
    ++totals.frames;
    totals.fast += fast ? 1 : 0;
    totals.bound += TapsBound(lights, segments, w, h);
    totals.lights_most = std::max(totals.lights_most, lights);
    totals.segments = segments;
    totals.width = w;
    totals.height = h;
    return fast ? 1u : 0u;
}

/// The counts' line (every LinePeriod lamp fog frames, beside the r106 lines), then the counts reset.
inline void PrintLine() {
    const double frames = double(std::max<std::uint64_t>(totals.frames, 1));
    std::printf("Volumetric lighting (r106c): shaft march over %llu frames: fast in %llu; map reads a "
                "frame at most %.0f on average (lights x 2 halves x %u samples x %ux%u pixels, up to "
                "%u lights; lights off the ray and skipped samples read less, not counted)\n",
                static_cast<unsigned long long>(totals.frames),
                static_cast<unsigned long long>(totals.fast), double(totals.bound) / frames,
                totals.segments, totals.width, totals.height, totals.lights_most);
    totals = {};
}

} // namespace Vulkan::LampFogShaftFast
