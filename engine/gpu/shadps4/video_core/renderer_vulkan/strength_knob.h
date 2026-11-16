// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r109a_strength-settings-engine): a feature's strength that is a lantern.ini setting (the
// renderer reads it every frame, so a slider acts at once) and that an environment variable
// overrides for tests (read once by the caller). Used by the halation (graphics_halation_strength,
// BB_HALATION) and the lamp flicker (graphics_lamp_flicker_strength, BB_LAMP_FLICKER;
// graphics_lamp_flicker_on_game_strength, BB_LAMP_FLICKER_ON_GAME). Pure: the unit tests build it
// alone (tests/test_halation.cpp, tests/test_lamp_flicker.cpp).

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace StrengthKnob {

/// An environment variable's text as a strength.
struct Env {
    bool set = false;   ///< not null and not empty: it decides, whatever the setting says
    float value = 0.0f; ///< 0..max; a text that does not begin with a number, or whose number is
                        ///< not finite or not above 0, is 0
};

inline Env ReadEnv(const char* text, float max) {
    Env env;
    if (text == nullptr || text[0] == '\0') {
        return env;
    }
    env.set = true;
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    env.value = end != text && std::isfinite(v) && v > 0.0f ? std::min(v, max) : 0.0f;
    return env;
}

/// A strength and where it came from.
struct Value {
    float value = 0.0f;
    bool from_env = false;
};

/// The variable's strength when it is set, else the setting's clamped to 0..max (a setting that is
/// not finite: `fallback`, the setting's default).
inline Value Pick(const Env& env, float setting, float max, float fallback) {
    if (env.set) {
        return {env.value, true};
    }
    return {std::clamp(std::isfinite(setting) ? setting : fallback, 0.0f, max), false};
}

/// "environment" or "setting".
inline const char* SourceName(const Value& v) {
    return v.from_env ? "environment" : "setting";
}

/// When a feature's strength line is due. Due is called once a frame with the frame's strengths
/// (one or two): true at the first call, then when a value or its source differs from those of the
/// last line and at least `every` calls have passed since that line (so a slider being dragged
/// gives one line, with the value it stopped at, at most `every` frames after the last one).
class Line {
public:
    bool Due(std::uint32_t every, const Value& a, const Value& b = {}) {
        if (since < every) {
            ++since;
        }
        const bool same = said && Same(a, last_a) && Same(b, last_b);
        if (same || (said && since < every)) {
            return false;
        }
        said = true;
        last_a = a;
        last_b = b;
        since = 0;
        return true;
    }

private:
    static bool Same(const Value& x, const Value& y) {
        return x.value == y.value && x.from_env == y.from_env;
    }

    Value last_a{}, last_b{};
    std::uint32_t since = 0;
    bool said = false;
};

} // namespace StrengthKnob
