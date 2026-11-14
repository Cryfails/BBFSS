// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass
// (point_shadow_ray.comp with MODE_REPAIR): the knobs, read once from the environment, the
// sixteen words PointShadow::Flush appends to the pass's data, and the weight of a lamp as the
// shader works it out. No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it alone.

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace Vulkan {

struct LampShadowTune {
    bool weights = true;         ///< BB_LAMP_SHADOW_WEIGHTS: the game's falloff times N.L; 0: as before
    float wrap = 0.15f;          ///< BB_LAMP_SHADOW_WRAP, 0..1: N.L tolerance; 1: no N.L
    float facing_floor = 0.05f;  ///< BB_LAMP_SHADOW_FLOOR, 0..1: least facing factor; 0: none
    float radius_m = 0.05f;      ///< BB_LAMP_SHADOW_SOFT, 0..0.3: the lamp's radius; 0: a point
    std::uint32_t rim = 3;       ///< BB_LAMP_SHADOW_RIM, 0..4: rays to the lamp's rim
    float share = 0.25f;         ///< BB_LAMP_SHADOW_SHARE, 0..1: least weight share for rim rays
    float near_part = 0.5f;      ///< BB_LAMP_SHADOW_NEAR, 0.05..1: rim rays for casters this near
                                 ///< the lamp (share of the way to the receiver); 1: everywhere
    float clearance_m = 0.35f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp
    float bias_m = 0.03f;        ///< BB_LAMP_SHADOW_BIAS, 0.005..0.2: ray start offset (the push block)
    float self_m = 0.06f;        ///< BB_LAMP_SHADOW_SELF, 0..0.3: grazing self skip
    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..3: debug view
    float view_gain = 0.5f;      ///< BB_LAMP_SHADOW_VIEW_GAIN, 0.01..16
};

inline constexpr std::uint32_t LampTuneWordCount = 16;
// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 4-6 rim rays, bits 8-9 the view. Words 1-9, floats: clearance,
// radius, share, self skip, wrap, the inverse-square curve's core squared, view gain, facing
// floor, near part. Words 10-12 and 13-15: two axes of the world in view space, unit length and
// square to each other (the rim pattern's frame): world +x (horizontal) and world +y (up).
inline constexpr std::uint32_t LampTuneNewWeights = 1, LampTuneInverseSquare = 2;
inline constexpr std::uint32_t LampTuneRimShift = 4, LampTuneViewShift = 8;

using LampTuneGet = const char* (*)(const char*);

namespace LampTuneDetail {
// The text up to trailing blanks must be a number; anything else leaves the default.
inline bool Ends(const char* end) {
    while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n') {
        ++end;
    }
    return *end == '\0';
}

inline float Number(LampTuneGet get, const char* name, float fallback, float lo, float hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !Ends(end) || !std::isfinite(value)) {
        return fallback;
    }
    return std::clamp(value, lo, hi);
}

inline std::uint32_t Whole(LampTuneGet get, const char* name, std::uint32_t fallback,
                           std::uint32_t hi) {
    const char* text = get(name);
    if (!text || !text[0]) {
        return fallback;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !Ends(end)) {
        return fallback;
    }
    return std::uint32_t(std::clamp(value, 0l, long(hi)));
}
} // namespace LampTuneDetail

/// The knobs as `get` (std::getenv) has them: a value out of range is clamped, one that is not
/// a number leaves the default.
inline LampShadowTune ReadLampShadowTune(LampTuneGet get) {
    using namespace LampTuneDetail;
    LampShadowTune tune;
    tune.weights = Whole(get, "BB_LAMP_SHADOW_WEIGHTS", tune.weights ? 1u : 0u, 1u) != 0;
    tune.wrap = Number(get, "BB_LAMP_SHADOW_WRAP", tune.wrap, 0.0f, 1.0f);
    tune.facing_floor = Number(get, "BB_LAMP_SHADOW_FLOOR", tune.facing_floor, 0.0f, 1.0f);
    tune.radius_m = Number(get, "BB_LAMP_SHADOW_SOFT", tune.radius_m, 0.0f, 0.3f);
    tune.rim = Whole(get, "BB_LAMP_SHADOW_RIM", tune.rim, 4u);
    tune.share = Number(get, "BB_LAMP_SHADOW_SHARE", tune.share, 0.0f, 1.0f);
    tune.near_part = Number(get, "BB_LAMP_SHADOW_NEAR", tune.near_part, 0.05f, 1.0f);
    tune.clearance_m = Number(get, "BB_LAMP_SHADOW_CLEARANCE", tune.clearance_m, 0.05f, 2.0f);
    tune.bias_m = Number(get, "BB_LAMP_SHADOW_BIAS", tune.bias_m, 0.005f, 0.2f);
    tune.self_m = Number(get, "BB_LAMP_SHADOW_SELF", tune.self_m, 0.0f, 0.3f);
    tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, 3u);
    tune.view_gain = Number(get, "BB_LAMP_SHADOW_VIEW_GAIN", tune.view_gain, 0.01f, 16.0f);
    return tune;
}

/// The core of the game's inverse-square curve as LocalFalloff::Patch takes it.
inline float LampTuneCore(float core) {
    return std::isfinite(core) && core > 0.0f ? core : 0.0f;
}

/// The world's +x and +y axes in view space (six floats) from `view`, the pass's world-to-view
/// matrix as 12 floats in rows of four (CameraMotion::Matrices::view, a VkTransformMatrixKHR):
/// its first two columns, made unit length. No matrix, or columns that are not finite, not of
/// about unit length or not square to each other: the view's own x and y axes (the rim pattern
/// then turns with the camera, as it did before the axes were handed over).
inline std::array<float, 6> LampTuneAxes(const float* view) {
    constexpr std::array<float, 6> Own{1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
    if (!view) {
        return Own;
    }
    std::array<float, 6> axes{view[0], view[4], view[8], view[1], view[5], view[9]};
    for (int k = 0; k < 2; ++k) {
        float* a = axes.data() + k * 3;
        const float length = std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
        if (!std::isfinite(length) || !(length > 0.5f) || !(length < 2.0f)) {
            return Own;
        }
        for (int c = 0; c < 3; ++c) {
            a[c] /= length;
        }
    }
    const float dot = axes[0] * axes[3] + axes[1] * axes[4] + axes[2] * axes[5];
    return std::abs(dot) < 0.05f ? axes : Own;
}

/// What the shader reads at the place the mode word names. inverse_square, core: the lamp
/// falloff the game's shaders were patched to (startup_local_inverse_square,
/// startup_local_light_core). view: see LampTuneAxes.
inline std::array<std::uint32_t, LampTuneWordCount> LampTuneWords(const LampShadowTune& tune,
                                                                  bool inverse_square, float core,
                                                                  const float* view = nullptr) {
    const auto bits = [](float v) { return std::bit_cast<std::uint32_t>(v); };
    core = LampTuneCore(core);
    const auto axes = LampTuneAxes(view);
    const std::uint32_t flags = (tune.weights ? LampTuneNewWeights : 0u) |
                                (inverse_square ? LampTuneInverseSquare : 0u) |
                                std::min<std::uint32_t>(tune.rim, 7u) << LampTuneRimShift |
                                std::min<std::uint32_t>(tune.view, 3u) << LampTuneViewShift;
    return {flags,
            bits(tune.clearance_m),
            bits(tune.radius_m),
            bits(tune.share),
            bits(tune.self_m),
            bits(tune.wrap),
            bits(core * core),
            bits(tune.view_gain),
            bits(tune.facing_floor),
            bits(tune.near_part),
            bits(axes[0]),
            bits(axes[1]),
            bits(axes[2]),
            bits(axes[3]),
            bits(axes[4]),
            bits(axes[5])};
}

/// A lamp's weight at a pixel as point_shadow_ray.comp's lampWeight works it out. t2: distance
/// squared over radius squared (below 1); facing: the cosine between the surface normal and the
/// direction to the lamp; has_normal false: the pass found no normal there (no facing term);
/// luma: of the lamp's colour.
inline float LampWeight(const LampShadowTune& tune, bool inverse_square, float core, float t2,
                        float facing, bool has_normal, float luma) {
    if (!tune.weights) {
        float w = 1.0f - t2;
        w *= w * luma;
        return w;
    }
    float f = 1.0f - std::sqrt(t2);
    f *= f;
    if (inverse_square) {
        core = LampTuneCore(core);
        f = std::max(0.0f, 1.0f / std::max(t2 + core * core, 1e-6f) - 1.0f / (1.0f + core * core));
    }
    float faced = 1.0f;
    if (tune.wrap < 1.0f && has_normal) {
        // Never below the floor: the facing ranks the lamps, it does not remove one.
        faced = std::clamp((facing + tune.wrap) / (1.0f + tune.wrap), tune.facing_floor, 1.0f);
    }
    return f * faced * luma;
}

} // namespace Vulkan
