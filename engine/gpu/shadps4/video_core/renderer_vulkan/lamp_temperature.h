// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r123_lamp-colour-temperature): lamps of different kinds burn at different colour
// temperatures. BB_LAMP_TEMPERATURE (0 = off, the default, to 1) is the strength, BB_LAMP_TEMPERATURE_SPREAD
// (kelvin, default 150) the size of a small steady difference between lamps of one kind. With the
// test tools' live knobs (BB_LIVE_KNOBS_FILE; gpu/shim/bbport_live_knobs.h, test tools only) both are
// asked again at every frame end, so one running game can change them; without that header the
// environment is read once. Pure C++; lamp_flicker.h's Tracker calls Tint for each flame lamp of a
// light draw (the same lamp-record copy as the flicker, so no new pass, buffer or descriptor).
//
// Which lamps: the ones LampFlicker::Flame takes (red the strongest, green 0.15 to 0.97 of red, blue at
// most 0.8 of red, reach at most 40 m). Moonlight fill, magic and other cold lights are not flame
// coloured and are left alone.
//
// What tells the kinds apart in a lamp record (words 0-2 view space place, 3 = 1 / reach squared,
// 4-6 colour; the game's own numbers, 2026-11-15/16 probe lists of nine places, see the context file):
//  - blue / red of the colour: the game's hand torch and lantern (2.7-2.9, 1.5-1.6, 0.7) and (1.3,
//    0.75, 0.34) are 0.25, braziers and bonfires 0.12-0.25, wall lanterns and church lamps 0.33-0.40,
//    street lamp posts exactly (1.0, 0.74, 0.50), 0.50, and big pale ones (1.5, 1.12, 0.75), 0.50;
//  - reach: candles reach 2 to 3.5 m (church), lamps 5 to 10 m;
//  - not usable: luminance (the artists set 0.15 to 4.7 for every kind), words 7-11 (a record keeps
//    values there whose meaning is not known; the probe saw ranges only).
// The game flickers only the torch and the hand lantern itself (they also have the lowest blue /
// red); that state is not an input here, because a lamp's kind must not change with the game's
// flicker. The kelvin a lamp gets is a continuous function of the lamp's own record, so a lamp whose
// colour the game changes slightly from frame to frame does not jump between kinds:
//   K_chroma = 1850 + 700 * smoothstep(0.28, 0.45, blue / red)         (fire 1850 .. pale lamp 2550)
//   K = K_chroma + (1850 - K_chroma) * smoothstep(4.4, 3.2, reach)     (reach 3.2 m or less: candle 1850)
// then K += o * spread, o in -1..1 from a hash of the lamp's seed (the place where it was first seen,
// LampFlicker::Tracker), so a row of street lamps is not identical and a lamp keeps its own number.
//
// How the colour changes: the game's colour c is multiplied by g = (B(K) / B(KRef)) ^ (Calibration *
// strength) per channel, B(K) the colour of a blackbody at K in linear sRGB (Kang et al. fit of
// the Planckian locus, 1700 to 4000 K, blue at least 3% of red), KRef = 3300 K the temperature that
// changes nothing; then all three channels by one number that gives the colour exactly the
// luminance (0.299, 0.587, 0.114) the game made it with. So a lamp at 3300 K keeps the game's colour,
// a warmer one gets redder (green and blue lowered), a cooler one yellower, and the lamp's light
// (what lampWeight of point_shadow_ray.comp and the lamp fog read) stays what the game made it.
// Calibration 0.5: the game's lamp colours are paler than a blackbody's (a church candle (1, 0.62,
// 0.36) has the green / red of a 3800 K blackbody, the street lamp (1, 0.74, 0.50) that of 4000 K
// or more, the hunter torch (0.56) of 3400 K), so the full physical ratio would be far redder
// than anything the game ships (the torch's green / red 0.56 would become 0.23); an exponent of
// 0.5 at strength 1 takes the torch to 0.36 and the dim candle (1, 0.62, 0.36) to 0.40 (model,
// offset 0), a street lamp to 0.63 with blue / red 0.30 (was 0.50), and strength 0 is the game's
// colour.
// r123b: KRef was 2600 K and Calibration 0.4. A street lamp (2550 K) then changed by 3% and a
// candle's blue by 24%, and a lamp's light is only a fifth of what a lit pixel shows (the rest is
// sun, sky, GI, fog and the flames' own glow), so build 75's pictures did not move (blue / red of
// the church 0.929 -> 0.920). KRef above every kind (3300 K is more than 2550 K plus the largest
// spread, 400 K) moves all lamps toward orange, the street lamps least; BB_LAMP_TEMPERATURE_SHOW=1
// is the test view with the exponent ShowScale (4) times larger.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_LAMP_TEMPERATURE_LIVE 1
#else
#define BB_LAMP_TEMPERATURE_LIVE 0
#endif

namespace LampTemperature {

inline constexpr float DefaultSpread = 150.0f; ///< K: BB_LAMP_TEMPERATURE_SPREAD when not set
inline constexpr float MaxSpread = 400.0f;     ///< K: the spread never goes past this
inline constexpr float KFire = 1850.0f;  ///< K: candles, torches, braziers (blue / red 0.28 or less)
inline constexpr float KPale = 2550.0f;  ///< K: street lamps (blue / red 0.45 or more)
inline constexpr float FireBlue = 0.28f; ///< blue / red up to this: KFire
inline constexpr float PaleBlue = 0.45f; ///< blue / red from this: KPale
inline constexpr float CandleReach = 3.2f; ///< m: a lamp reaching this far or less is a candle
inline constexpr float NotCandleReach = 4.4f; ///< m: one reaching this far or more is not
inline constexpr float KRef = 3300.0f;   ///< K: the temperature whose ratio is 1 (the game's colour)
inline constexpr float Calibration = 0.5f; ///< exponent of the blackbody ratio at strength 1
inline constexpr float ShowScale = 4.0f;  ///< BB_LAMP_TEMPERATURE_SHOW=1: the exponent times this
inline constexpr float BlueFloor = 0.03f;  ///< a blackbody's blue is at least this of its red
inline constexpr float MinKelvin = 1700.0f, MaxKelvin = 4000.0f; ///< the locus fit's range used
inline constexpr double RampSeconds = 1.0; ///< s for the strength to go from 0 to 1 (and back)
inline constexpr std::array<float, 3> Luma{0.299f, 0.587f, 0.114f}; ///< lampWeight's weights

/// What a lamp is, by the rules above (counted in the log; the number is the index of the counters).
enum class Kind : std::uint8_t { Candle, Fire, Lantern, Street };
inline constexpr std::size_t KindCount = 4;
inline constexpr const char* KindNames[KindCount] = {"candles", "torches and fires", "wall lanterns",
                                                     "street lamps"};

/// The strength and spread of a frame.
struct Setting {
    float strength = 0.0f;
    float spread = DefaultSpread;
    bool show = false; ///< r123b: BB_LAMP_TEMPERATURE_SHOW=1, the test view (exponent x ShowScale)
    // r123b: constructors keep Setting{strength, spread} valid without a missing-initializer warning
    constexpr Setting() = default;
    constexpr Setting(float strength_, float spread_, bool show_ = false)
        : strength(strength_), spread(spread_), show(show_) {}
    [[nodiscard]] bool On() const {
        return strength > 0.0f;
    }
};

/// BB_LAMP_TEMPERATURE's text: a number above 0, at most 1; anything else (null, empty, not a
/// number, not finite, 0 or less) is 0 (off).
inline float ParseStrength(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return 0.0f;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    return end != text && std::isfinite(v) && v > 0.0f ? std::min(v, 1.0f) : 0.0f;
}

/// BB_LAMP_TEMPERATURE_SPREAD's text: kelvin, 0 to MaxSpread; null, empty, not a number or not
/// finite is DefaultSpread, a negative number 0.
inline float ParseSpread(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return DefaultSpread;
    }
    char* end = nullptr;
    const float v = std::strtof(text, &end);
    return end != text && std::isfinite(v) ? std::clamp(v, 0.0f, MaxSpread) : DefaultSpread;
}

/// BB_LAMP_TEMPERATURE_SHOW's text: exactly `1` is on (r123b, the test view); anything else is off.
inline bool ParseShow(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}

/// The setting now (live knobs: asked again each call; else read once). Called once a frame end.
inline Setting Read() {
#if BB_LAMP_TEMPERATURE_LIVE
    static BbLiveKnobs::Knob<float> strength{"BB_LAMP_TEMPERATURE", ParseStrength};
    static BbLiveKnobs::Knob<float> spread{"BB_LAMP_TEMPERATURE_SPREAD", ParseSpread};
    static BbLiveKnobs::Knob<bool> show{"BB_LAMP_TEMPERATURE_SHOW", ParseShow};
    return {strength.Get(), spread.Get(), show.Get()};
#else
    static const Setting setting{ParseStrength(std::getenv("BB_LAMP_TEMPERATURE")),
                                 ParseSpread(std::getenv("BB_LAMP_TEMPERATURE_SPREAD")),
                                 ParseShow(std::getenv("BB_LAMP_TEMPERATURE_SHOW"))};
    return setting;
#endif
}

/// Hermite step from `a` to `b` (a may be larger than b: a falling step), 0 before a, 1 after b.
inline float Smooth(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The colour of a blackbody at `kelvin` (clamped to MinKelvin..MaxKelvin) in linear sRGB, scaled
/// to luminance 1 (Luma), blue at least BlueFloor of red. Kang et al. (2002) fit of the Planckian
/// locus: x(T), y(T), then XYZ with Y = 1 and the sRGB matrix.
inline std::array<float, 3> Blackbody(float kelvin) {
    const double t = std::clamp(double(kelvin), double(MinKelvin), double(MaxKelvin));
    const double t2 = t * t, t3 = t2 * t;
    const double x = -0.2661239e9 / t3 - 0.2343589e6 / t2 + 0.8776956e3 / t + 0.179910;
    const double y = t < 2222.0
                         ? -1.1063814 * x * x * x - 1.34811020 * x * x + 2.18555832 * x - 0.20219683
                         : -0.9549476 * x * x * x - 1.37418593 * x * x + 2.09137015 * x - 0.16748867;
    const double cx = x / y, cz = (1.0 - x - y) / y;
    double r = 3.2406 * cx - 1.5372 - 0.4986 * cz;
    double g = -0.9689 * cx + 1.8758 + 0.0415 * cz;
    double b = 0.0557 * cx - 0.2040 + 1.0570 * cz;
    r = std::max(r, 1e-3);
    g = std::max(g, 1e-3);
    b = std::max(b, double(BlueFloor) * r);
    const double luma = double(Luma[0]) * r + double(Luma[1]) * g + double(Luma[2]) * b;
    return {float(r / luma), float(g / luma), float(b / luma)};
}

/// The kind of a flame lamp and its kelvin before the spread: see the rules at the top. `colour`
/// is the game's, with a red above 0 (LampFlicker::Flame), `reach` in metres.
struct Class {
    float kelvin = KFire;
    Kind kind = Kind::Fire;
};

inline Class Classify(const std::array<float, 3>& colour, float reach) {
    const float blue = colour[0] > 0.0f ? colour[2] / colour[0] : 0.0f;
    const float pale = Smooth(FireBlue, PaleBlue, blue);
    const float candle = Smooth(NotCandleReach, CandleReach, reach);
    Class c;
    c.kelvin = KFire + pale * (KPale - KFire);
    c.kelvin += (KFire - c.kelvin) * candle;
    c.kind = candle >= 0.5f ? Kind::Candle
             : pale < 0.25f ? Kind::Fire
             : pale < 0.75f ? Kind::Lantern
                            : Kind::Street;
    return c;
}

/// A lamp's colour at the kelvin and strength, and what it was counted as.
struct Tinted {
    std::array<float, 3> colour{};
    float kelvin = 0.0f; ///< with the spread
    Kind kind = Kind::Fire;
};

/// (r123b) The colour `colour` with the tint of a blackbody at `kelvin` (against KRef) to the power
/// `exponent`, the three channels then scaled to the game's luminance; the colour itself when it has
/// no luminance or the numbers are not finite.
inline std::array<float, 3> TintToKelvin(const std::array<float, 3>& colour, float kelvin, float exponent) {
    const std::array<float, 3> warm = Blackbody(kelvin);
    static const std::array<float, 3> ref = Blackbody(KRef);
    std::array<float, 3> g{};
    float lit = 0.0f, base = 0.0f;
    for (std::size_t i = 0; i < 3; ++i) {
        g[i] = std::pow(warm[i] / ref[i], exponent);
        lit += Luma[i] * colour[i] * g[i];
        base += Luma[i] * colour[i];
    }
    if (!(lit > 0.0f) || !(base > 0.0f) || !std::isfinite(lit) || !std::isfinite(base)) {
        return colour;
    }
    const float scale = base / lit;
    std::array<float, 3> out{};
    for (std::size_t i = 0; i < 3; ++i) {
        out[i] = colour[i] * g[i] * scale;
    }
    return out;
}

/// The tinted colour of the flame lamp `colour` (the game's, as a record has it) with `reach`:
/// `offset` in -1..1 is the lamp's own place in the spread (the caller hashes its seed), `spread`
/// in K, `strength` 0..1, `show` (r123b) the exponent times ShowScale. At strength 0 the colour
/// comes back unchanged; always the game's
/// luminance (the three channels share one scale; a colour with no luminance or not finite stays).
inline Tinted Tint(const std::array<float, 3>& colour, float reach, float offset, float strength,
                   float spread, bool show = false) {
    const Class cls = Classify(colour, reach);
    Tinted out;
    out.colour = colour;
    out.kind = cls.kind;
    out.kelvin = cls.kelvin + std::clamp(offset, -1.0f, 1.0f) * std::clamp(spread, 0.0f, MaxSpread);
    if (!(strength > 0.0f)) {
        return out;
    }
    const float e = Calibration * std::min(strength, 1.0f) * (show ? ShowScale : 1.0f);
    out.colour = TintToKelvin(colour, out.kelvin, e);
    return out;
}

} // namespace LampTemperature
