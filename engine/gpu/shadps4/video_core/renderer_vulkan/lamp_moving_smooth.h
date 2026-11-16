// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r60c_moving-shadow-steps): BB_LAMP_SHADOW_MOVING_SMOOTH, one knob for the three moving-edge
// fixes of the lamp shadows. Behind a moving shadow the lamp pass's guards against trails give a
// pixel's history up and it shows this frame's bare ray, 0 or 1, for a frame or two (blocky, hatched
// edges that travel with the shadow; at half resolution also 2x2 squares). r93 (BB_LAMP_SHADOW_SPATIAL),
// r103 (BB_LAMP_SHADOW_YOUNG, with r103b's standing rule) and r101 (BB_LAMP_SHADOW_MOVING_EDGE) smooth
// that without a new ray; each has its own knob, off by default. 0 or not set (the default): nothing
// here does anything. 1 (any whole number but 0): the three knobs that the environment has not set (or
// has set to nothing) are set to 1 before PointShadow reads them. A knob the environment set is left as
// it is, so BB_LAMP_SHADOW_MOVING_SMOOTH=1 BB_LAMP_SHADOW_YOUNG=0 turns the other two on only.
// No Vulkan here.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#include <stdlib.h> // _putenv_s
#endif

namespace Vulkan {

namespace LampMovingSmoothDetail {
inline bool on = false;                 ///< the knob is on
inline std::uint32_t set_by_preset = 0; ///< knobs this preset set
inline std::uint32_t left_to_env = 0;   ///< knobs the environment had set (left as they were)
inline std::uint32_t lines = 0;         ///< periodic lines printed

inline bool Parse(const char* text) {
    if (!text || !text[0]) {
        return false;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    return end != text && *end == '\0' && value != 0;
}

inline void Set(const char* name, const char* value) {
    if (const char* have = std::getenv(name); have && have[0]) {
        ++left_to_env;
        return;
    }
#ifdef _WIN32
    const bool ok = _putenv_s(name, value) == 0;
#else
    const bool ok = setenv(name, value, 1) == 0;
#endif
    if (ok) {
        ++set_by_preset;
    }
}
} // namespace LampMovingSmoothDetail

/// PointShadow's constructor calls this first, before the lamp knobs are read: with the knob on, it sets
/// BB_LAMP_SHADOW_SPATIAL, BB_LAMP_SHADOW_YOUNG and BB_LAMP_SHADOW_MOVING_EDGE to 1 where they are not
/// set, and says so once. With the knob off or not set it reads one variable, once, and does nothing else.
inline void LampMovingSmoothApply() {
    static const bool done = [] {
        namespace D = LampMovingSmoothDetail;
        D::on = D::Parse(std::getenv("BB_LAMP_SHADOW_MOVING_SMOOTH"));
        if (!D::on) {
            return true;
        }
        D::Set("BB_LAMP_SHADOW_SPATIAL", "1");
        D::Set("BB_LAMP_SHADOW_YOUNG", "1");
        D::Set("BB_LAMP_SHADOW_MOVING_EDGE", "1");
        std::printf("Ray traced lamps (r60c): moving shadow smoothing on (BB_LAMP_SHADOW_MOVING_SMOOTH): "
                    "BB_LAMP_SHADOW_SPATIAL, _YOUNG and _MOVING_EDGE (r93, r103 + r103b, r101) set to 1 "
                    "where the environment had not set them (%u set here, %u left as the environment "
                    "has them); no new rays; the r93, r103 and r101 lines say what each does\n",
                    unsigned(D::set_by_preset), unsigned(D::left_to_env));
        return true;
    }();
    (void)done;
}

/// PointShadow's periodic lamp line (every 600 frames), a short line of its own, only with the knob on.
inline void LampMovingSmoothLine() {
    namespace D = LampMovingSmoothDetail;
    if (!D::on) {
        return;
    }
    ++D::lines;
    std::printf("Ray traced lamps (r60c): moving shadow smoothing on, %u knobs set by it and %u left to the "
                "environment, line %u\n",
                unsigned(D::set_by_preset), unsigned(D::left_to_env), unsigned(D::lines));
}

} // namespace Vulkan
