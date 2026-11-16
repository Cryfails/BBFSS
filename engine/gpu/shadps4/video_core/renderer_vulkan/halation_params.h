// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r95_halation): film halation, the soft red-orange glow that bleeds from very bright
// small sources (lamps, candles, the torch flame, bright windows, the moon) into the dark around
// them. Unlike the game's own bloom (wide, the colour of its light, added in the game's final
// composite) it is tight and red-orange, as light that passed the film and came back from its base
// into the red layer. The pass (vk_halation.cpp, host_shaders/halation.comp) runs on the scene
// colour right before the upscaler, at the scene's render size, after the fog. This header holds
// the knobs and the push words; no Vulkan here: tests/test_halation.cpp builds it alone.
//
// The strength a frame uses (bbport r109a_strength-settings-engine; StrengthOf): BB_HALATION when
// it is set and not empty (read once; a text that is not a number above 0 is 0, more than 2 is 2),
// else the setting graphics_halation_strength (0..2, DefaultStrength 1, read every frame). At 0
// nothing is drawn; the rasterizer makes its Halation at the first frame above 0 and keeps it.
// Knobs (environment, read once at the first use; Load):
//   BB_HALATION            Knobs::strength by the same rule (the frame's strength replaces it)
//   BB_HALATION_RADIUS     0.5..3, factor on the glow's width (DefaultRadius 1: a Gaussian blur
//                          of SigmaAt1080 pixels at 1080 lines, the same share at any size)
//   BB_HALATION_THRESHOLD  1..8 stops over the frame's key a pixel must pass to glow (3.5)
//   BB_HALATION_SHOW       test only: 1 the glow ShowGain times as strong and the threshold
//                          ShowThresholdDrop stops lower; 2 as 1, the glow alone on black
// A missing or unreadable radius or threshold takes the default; then the range is applied.
//
// The passes (HalationParams::Mode, one shader build):
//   Down   a quarter of the size: each texel the mean of its 4x4 scene pixels' excess over the
//          threshold T = key * 2^threshold, each pixel's excess e soft-capped as e / (1 + e / C)
//          with C = T * 2^CapStops (so a single spark adds at most C / 16 to its texel, a window or
//          a flame its full excess), in the pixel's own colour. The key is the log-mean luminance
//          of the frame BEFORE (its sums in the key buffer's other slot), this frame's sums go into
//          its slot (fixed point, KeyScale and KeyBias, also in the push words).
//   BlurX, BlurY  a separable Gaussian of sigma Sigma() quarter texels, Taps() texels a side
//          (two texels a bilinear read).
//   Add    every scene pixel: + gain * (luma(g) * tint * (1 - HueKeep) + g * HueKeep), g the
//          blurred texel read bilinearly; a pixel whose glow is below 1e-6 is not written.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/halation_layout.h"
#include "strength_knob.h" // bbport (r109a_strength-settings-engine)

namespace Vulkan::HalationParams {

inline constexpr float MaxStrength = 2.0f;
/// bbport (r109a_strength-settings-engine): graphics_halation_strength's default (tied to
/// BbSettings::HalationStrengthDefault by a static_assert in vk_halation.cpp).
inline constexpr float DefaultStrength = 1.0f;
inline constexpr float DefaultRadius = 1.0f, MinRadius = 0.5f, MaxRadius = 3.0f;
inline constexpr float DefaultThreshold = 3.5f, MinThreshold = 1.0f, MaxThreshold = 8.0f;
/// The blur's sigma in scene pixels at radius 1 and 1080 lines (about 1.1% of the height).
inline constexpr float SigmaAt1080 = 12.0f;
/// The glow added per unit of the blurred, capped excess at strength 1.
inline constexpr float Gain = 0.40f;
/// The soft cap of a pixel's excess, in stops over the threshold.
inline constexpr float CapStops = 6.0f;
/// The share of the glow that keeps the source's own colour; the rest is the film's tint.
inline constexpr float HueKeep = 0.25f;
/// The film's red-orange (1, 0.36, 0.14), scaled to a Rec. 709 luminance of 1.
inline constexpr float TintLuma = 0.2126f * 1.0f + 0.7152f * 0.36f + 0.0722f * 0.14f;
inline constexpr float TintR = 1.0f / TintLuma, TintG = 0.36f / TintLuma, TintB = 0.14f / TintLuma;
/// BB_HALATION_SHOW 1 and 2.
inline constexpr float ShowGain = 4.0f, ShowThresholdDrop = 1.5f;
/// The blur reads at most this many texels a side.
inline constexpr std::uint32_t MaxTaps = 64;
/// The key's fixed point: (clamp(log2(max(mean, KeyFloor)), -KeyBias, KeyBias) + KeyBias) * KeyScale
/// a quarter texel, summed with 32-bit atomics.
inline constexpr float KeyScale = 64.0f, KeyBias = 16.0f, KeyFloor = 1e-4f;
/// One slot of the key buffer: sum, count, pixels over the threshold, unused (4 words). Two slots:
/// this frame's and the frame before's.
inline constexpr std::uint32_t KeySlotWords = 4, KeySlotBytes = KeySlotWords * 4, KeySlots = 2;

enum Mode : std::uint32_t { Down = 0, BlurX = 1, BlurY = 2, Add = 3, ModeCount = 4 };
enum Show : std::uint32_t { ShowOff = 0, ShowStrong = 1, ShowGlowOnly = 2 };
// The shader's numbers (halation_layout.h) are these, tied here.
static_assert(Down == HALATION_MODE_DOWN && BlurX == HALATION_MODE_BLUR_X &&
              BlurY == HALATION_MODE_BLUR_Y && Add == HALATION_MODE_ADD);
static_assert(ShowGlowOnly == HALATION_SHOW_GLOW_ONLY);
static_assert(KeySlotWords == HALATION_SLOT_WORDS);
/// Pixels or texels a side of one workgroup (the dispatches' rounding).
inline constexpr std::uint32_t Group = HALATION_GROUP;

struct Knobs {
    float strength = 0.0f; ///< 0: off
    float radius = DefaultRadius;
    float threshold = DefaultThreshold;
    std::uint32_t show = ShowOff;
};

/// What halation.comp's push block holds, word for word (20 words).
struct Push {
    std::uint32_t mode, slot, scene_w, scene_h;
    std::uint32_t quarter_w, quarter_h, taps, show;
    float sigma, threshold_stops, cap_stops, gain;
    float tint_r, tint_g, tint_b, hue_keep;
    float key_scale, key_bias, key_floor, pad0;
};
static_assert(sizeof(Push) == 80);

/// A number from the environment's text; `fallback` when unset, empty, unreadable or not finite.
inline float Number(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

inline Knobs Read(const char* strength, const char* radius, const char* threshold,
                  const char* show) {
    Knobs k;
    const float s = Number(strength, 0.0f);
    k.strength = s > 0.0f ? std::min(s, MaxStrength) : 0.0f;
    k.radius = std::clamp(Number(radius, DefaultRadius), MinRadius, MaxRadius);
    k.threshold = std::clamp(Number(threshold, DefaultThreshold), MinThreshold, MaxThreshold);
    k.show = show && (show[0] == '1' || show[0] == '2') && show[1] == '\0'
                 ? std::uint32_t(show[0] - '0')
                 : ShowOff;
    return k;
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs =
        Read(std::getenv("BB_HALATION"), std::getenv("BB_HALATION_RADIUS"),
             std::getenv("BB_HALATION_THRESHOLD"), std::getenv("BB_HALATION_SHOW"));
    return knobs;
}

/// bbport (r109a_strength-settings-engine): the strength a frame uses: BB_HALATION's (`env`,
/// StrengthKnob::ReadEnv(BB_HALATION's text, MaxStrength), read once by the caller) when it is
/// set, else `setting` (graphics_halation_strength) clamped to 0..MaxStrength (not finite:
/// DefaultStrength).
inline StrengthKnob::Value StrengthOf(const StrengthKnob::Env& env, float setting) {
    return StrengthKnob::Pick(env, setting, MaxStrength, DefaultStrength);
}

/// bbport (r109a_strength-settings-engine): a pass clears both key slots, as the first one does,
/// when it is the first (`runs` 0) or when more than KeyStaleFrames frame ends went by since the
/// last pass (`frame_ends` now, `ran_at_end` then; the strength was 0, or menu previews): the
/// frame before's key would be that of a scene long gone, so that frame draws no glow instead.
inline constexpr std::uint64_t KeyStaleFrames = 30;
inline constexpr bool ClearsKey(std::uint64_t runs, std::uint64_t frame_ends,
                                std::uint64_t ran_at_end) {
    return runs == 0 || frame_ends - ran_at_end > KeyStaleFrames;
}

/// The quarter image's side for a scene side (a texel per 4x4 pixels, the last one partial).
inline constexpr std::uint32_t Quarter(std::uint32_t n) {
    return (n + 3) / 4;
}

/// The blur's sigma in quarter texels for a scene `height` pixels high.
inline float Sigma(const Knobs& k, std::uint32_t height) {
    return SigmaAt1080 / 4.0f * k.radius * float(height) / 1080.0f;
}

/// Texels a side the blur reads: three sigmas, at least 1, at most MaxTaps.
inline std::uint32_t Taps(float sigma) {
    return std::clamp(std::uint32_t(std::ceil(3.0f * sigma)), 1u, MaxTaps);
}

/// The key's sums of a frame stay below 2^32 (every texel at most 2 * KeyBias * KeyScale).
inline constexpr bool KeyFits(std::uint32_t quarter_w, std::uint32_t quarter_h) {
    return double(quarter_w) * double(quarter_h) * double(2.0f * KeyBias * KeyScale) <
           4294967296.0;
}

/// The key (log-mean scene luminance) a slot's sum and count stand for; 0 without texels.
inline double KeyOf(std::uint32_t sum, std::uint32_t count) {
    return count ? std::exp2(double(sum) / double(count) / double(KeyScale) - double(KeyBias))
                 : 0.0;
}

inline float ThresholdStops(const Knobs& k) {
    return k.threshold - (k.show != ShowOff ? ShowThresholdDrop : 0.0f);
}

inline float GainOf(const Knobs& k) {
    return Gain * k.strength * (k.show != ShowOff ? ShowGain : 1.0f);
}

/// The push words of pass `mode` for a scene of width x height; `slot` is this frame's key slot.
inline Push Make(const Knobs& k, std::uint32_t width, std::uint32_t height, std::uint32_t slot,
                 Mode mode) {
    const float sigma = Sigma(k, height);
    return Push{
        .mode = mode,
        .slot = slot & 1u,
        .scene_w = width,
        .scene_h = height,
        .quarter_w = Quarter(width),
        .quarter_h = Quarter(height),
        .taps = Taps(sigma),
        .show = k.show,
        .sigma = sigma,
        .threshold_stops = ThresholdStops(k),
        .cap_stops = CapStops,
        .gain = GainOf(k),
        .tint_r = TintR,
        .tint_g = TintG,
        .tint_b = TintB,
        .hue_keep = HueKeep,
        .key_scale = KeyScale,
        .key_bias = KeyBias,
        .key_floor = KeyFloor,
        .pad0 = 0.0f,
    };
}

} // namespace Vulkan::HalationParams
