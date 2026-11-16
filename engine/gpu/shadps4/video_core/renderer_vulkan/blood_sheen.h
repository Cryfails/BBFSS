// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r100_blood-sheen, r100d_blood-sheen-gbuffer): a wet film on the game's blood pool, lit by
// the game's own lights. r100 took the pool for a forward draw (1ea84d9a:bd1d09f0); the r100b run
// showed that draw to be a small object at the hunter's hip, and the r100c probe (b21) found the pool
// in the G-buffer: at graveyard-blood the albedo's last writer under the pool is the G-buffer pair
// c829ee58:dbb222eb, the same pair as on the plain cobbles beside it. So the pool is either painted
// in the ground's texture or a decal mesh drawn with the ground's shaders. Both are met here, in the
// G-buffer, before the game's lights read it (vk_blood_sheen.cpp records the passes,
// host_shaders/blood_sheen.comp is the shader):
//   SNAPSHOT/MARK  around each keyed G-buffer draw (BB_BLOOD_SHEEN_DRAW): the pixels whose albedo or
//                  depth the draw changed are tagged with what it wrote;
//   EDIT           at the first light draw after the G-buffer pass (the shadow resolve, the sun or
//                  moon, or a lamp of the light grid; not while a lamps-apart batch is open): a pixel is
//                  picked where a keyed draw was the last to write it (with a key) and its albedo is
//                  dark red (with BB_BLOOD_SHEEN_RULE=albedo); its gloss and specular colour are raised
//                  toward a water film's (gloss 0.86, f0 0.30 at strength 1, its normal levelled, gaps of the pool filled (r100h); its gloss goes to it, the specular colour is never lowered; the
//                  lighting record in target 3's alpha untouched). The game's sun or moon, every lamp
//                  of its light grid (with the engine's ray traced lamp shadow when that is on) and the
//                  hunter's light then put a sharp highlight on it; dark places stay dark;
//   SHOW           BB_BLOOD_SHEEN=show: over the lit scene, picked pixels red-magenta, keyed pixels the
//                  albedo rule left out cyan, so what else the rule would wet can be judged.
//
// Knobs (environment, read once at start):
//   BB_BLOOD_SHEEN        unset, empty, 0, a negative number or other text: off (no BloodSheen is
//                         made: nothing of it runs); 1: on, strength 1; a number: the strength, put into
//                         0.25..4 (up to 1 the share of the way to the wet film; above 1 also a brighter
//                         specular colour, root 0.45 * sqrt(strength), at most 0.65, tinted deep red); "show": strength 1
//                         and the test view
//   BB_BLOOD_SHEEN_DRAW   the keyed G-buffer draws: "vs:ps" (every draw of that hex pair) or
//                         "vs:ps:N" (only its draws of N indices, decimal), at most MaxKeys, separated by
//                         ';', ',' or spaces. No default: unset, only the albedo rule can pick
//   BB_BLOOD_SHEEN_RULE   "draw" (or unset): every pixel a keyed draw wrote last; "albedo": of those
//                         (or, with no key, of every G-buffer pixel) the dark red ones: linear red at
//                         least RedMin, at least Ratio times green and blue, luminance (0.2126 r +
//                         0.7152 g + 0.0722 b) at most LumMax; "albedo:R" and "albedo:R:L" set Ratio
//                         (1..16) and LumMax (0..1). Other text: "draw" (said in the log).
//   BB_BLOOD_SHEEN_DARKEN bbport (r100e): 0..1, default 0.5: how far the lit scene's dark picked pixels are
//                         dimmed and reddened after the lighting (times the strength, at most 1); 0: that
//                         pass does not run (the test view "show" never dims). Unset or other text:
//                         the default.
//   BB_BLOOD_SHEEN_PEAK   bbport (r100k): 0..8, default 0.7: the lit scene's luminance ceiling for the picked
//                         pixels (a soft roll-off above half of it: a near light's highlight cannot blow
//                         out); 0: no ceiling. Unset or other text: the default.
// No Vulkan here: tests/test_blood_sheen.cpp builds it alone.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/blood_sheen_layout.h"

namespace Vulkan::BloodSheenRules {

inline constexpr float MinStrength = 0.25f, MaxStrength = 4.0f;
inline constexpr std::uint32_t MaxKeys = 4;
/// At most this many keyed draws a G-buffer pass get SNAPSHOT and MARK (two passes over the scene
/// each); the rest are counted, and their pixels are not taken.
inline constexpr std::uint32_t MaxKeyedDraws = 32;
/// The albedo rule's defaults (linear albedo, as the G-buffer's sRGB target reads).
inline constexpr float DefaultRatio = 2.0f, DefaultLumMax = 0.06f, RedMin = 0.008f;
inline constexpr float MinRatio = 1.0f, MaxRatio = 16.0f;
inline constexpr std::uint32_t Group = BLOOD_SHEEN_GROUP;
inline constexpr std::uint32_t SlotWords = BLOOD_SHEEN_SLOT_WORDS, Slots = 2;
inline constexpr std::uint32_t FlagShow = BLOOD_SHEEN_FLAG_SHOW, FlagSlot = BLOOD_SHEEN_FLAG_SLOT;
inline constexpr std::uint32_t FlagKeyed = BLOOD_SHEEN_FLAG_KEYED;
inline constexpr std::uint32_t FlagRuleAlbedo = BLOOD_SHEEN_FLAG_RULE_ALBEDO;
inline constexpr std::uint32_t FlagClear = BLOOD_SHEEN_FLAG_CLEAR;
inline constexpr std::uint32_t FlagNormal = BLOOD_SHEEN_FLAG_NORMAL; ///< EDIT: the normal target is bound
static_assert(Group == 8u && SlotWords == 8u);
static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal) == 63u);
inline constexpr std::uint32_t WordKeyed = BLOOD_SHEEN_WORD_KEYED, WordKept = BLOOD_SHEEN_WORD_KEPT;
inline constexpr std::uint32_t WordLost = BLOOD_SHEEN_WORD_LOST, WordRule = BLOOD_SHEEN_WORD_RULE;
inline constexpr std::uint32_t WordWet = BLOOD_SHEEN_WORD_WET;
static_assert(WordKeyed == 0 && WordKept == 1 && WordLost == 2 && WordRule == 3 && WordWet == 4);
// bbport (r100e_blood-sheen-visible): what the made-wet pixels had before the film.
inline constexpr std::uint32_t WordGlossSum = BLOOD_SHEEN_WORD_GLOSS_SUM, WordRootSum = BLOOD_SHEEN_WORD_ROOT_SUM;
inline constexpr std::uint32_t WordGlossy = BLOOD_SHEEN_WORD_GLOSSY;
static_assert(WordGlossSum == 5 && WordRootSum == 6 && WordGlossy == 7 && WordGlossy < SlotWords);
static_assert(WordWet < SlotWords);
static_assert(BLOOD_SHEEN_TAG_WET == 1u && BLOOD_SHEEN_TAG_LEFT_OUT == 2u);
// The wet film's numbers, as the shader and the README name them.
inline constexpr float WetGloss = float(BLOOD_SHEEN_WET_GLOSS), WetSpecRoot = float(BLOOD_SHEEN_WET_SPEC_ROOT);
inline constexpr float SpecRootMax = float(BLOOD_SHEEN_SPEC_ROOT_MAX);
static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.45 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.65);
// bbport (r100i_sheen-blood-tint): the specular root's tint (deep red), per channel.
inline constexpr float TintR = float(BLOOD_SHEEN_TINT_R), TintG = float(BLOOD_SHEEN_TINT_G);
inline constexpr float TintB = float(BLOOD_SHEEN_TINT_B);
static_assert(BLOOD_SHEEN_TINT_R == 0.85 && BLOOD_SHEEN_TINT_G == 0.35 && BLOOD_SHEEN_TINT_B == 0.30);
// bbport (r100e_blood-sheen-visible): the normal's flattening and the dimming, as the shader and the README name them.
inline constexpr float NormalSmooth = float(BLOOD_SHEEN_NORMAL_SMOOTH);
inline constexpr float DarkenRed = float(BLOOD_SHEEN_DARKEN_RED), DarkenOther = float(BLOOD_SHEEN_DARKEN_OTHER);
inline constexpr float DarkenLumaLo = float(BLOOD_SHEEN_DARKEN_LUMA_LO), DarkenLumaHi = float(BLOOD_SHEEN_DARKEN_LUMA_HI);
inline constexpr float DefaultDarken = 0.5f;
static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 1.0 && BLOOD_SHEEN_NORMAL_UP_LO == 0.35 && BLOOD_SHEEN_NORMAL_UP_HI == 0.6);
static_assert(BLOOD_SHEEN_NORMAL_EDGE == 0.3 && BLOOD_SHEEN_COVER_LO == 0.25 && BLOOD_SHEEN_COVER_HI == 0.65);
static_assert(BLOOD_SHEEN_RING0 == 6 && BLOOD_SHEEN_RING1 == 14 && BLOOD_SHEEN_RING2 == 28);
static_assert(BLOOD_SHEEN_FILL_LO == 0.5 && BLOOD_SHEEN_FILL_HI == 0.8 && BLOOD_SHEEN_FILL_MIN_HITS == 2);
inline constexpr float FillSpec = float(BLOOD_SHEEN_FILL_SPEC); ///< r100j_sheen-clean-rim: the rim's share of the body's specular
static_assert(BLOOD_SHEEN_FILL_SPEC == 0.35);
inline constexpr float PeakDefault = float(BLOOD_SHEEN_PEAK_DEFAULT); ///< r100k: BB_BLOOD_SHEEN_PEAK's default
inline constexpr float PeakKnee = float(BLOOD_SHEEN_PEAK_KNEE);       ///< r100k: the knee, as a share of the peak
inline constexpr float MaxPeak = 8.0f;                                ///< r100k: the largest BB_BLOOD_SHEEN_PEAK
static_assert(BLOOD_SHEEN_PEAK_DEFAULT == 0.7 && BLOOD_SHEEN_PEAK_KNEE == 0.5);
inline constexpr float NormalEdge = float(BLOOD_SHEEN_NORMAL_EDGE);
// bbport (r100g_sheen-sheets): GLSL's smoothstep.
inline float SmoothStep(float lo, float hi, float x) {
    const float t = std::clamp((x - lo) / (hi - lo), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}
// bbport (r100g_sheen-sheets): the share of the way to world up that a picked pixel goes (the shader's
// arithmetic): `up` is its unit normal's y component, `pool_share` the share of its 16 taps whose albedo is
// dark red (pass 1.0 without the albedo rule), at film strength `strength`. Everything it depends on is the
// pixel itself and fixed taps around it, never a group or an earlier pixel's result: no block can show.
inline float LevelShare(float up, float pool_share, float strength) {
    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);
    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * (edge + (1.0f - edge) * cover) *
           SmoothStep(float(BLOOD_SHEEN_NORMAL_UP_LO), float(BLOOD_SHEEN_NORMAL_UP_HI), up);
}
// bbport (r100h_sheen-liquid): the share of the 24 taps (three rings of 8) that are dark red.
inline float PoolShareOf(int hits0, int hits1, int hits2) {
    return float(hits0 + hits1 + hits2) * (1.0f / 24.0f);
}
// bbport (r100h_sheen-liquid): the film weight of a ground pixel that is NOT dark red itself (a gap of the
// pool; the shader's arithmetic): 0 unless `near_hits` (of the 8 taps of the middle ring) reach the minimum,
// else smoothstep(FILL_LO, FILL_HI, pool_share) times the up weight of its own normal `up`.
inline float FillWeight(float pool_share, float up, int near_hits) {
    if (near_hits < BLOOD_SHEEN_FILL_MIN_HITS) {
        return 0.0f;
    }
    return SmoothStep(float(BLOOD_SHEEN_FILL_LO), float(BLOOD_SHEEN_FILL_HI), pool_share) *
           SmoothStep(float(BLOOD_SHEEN_NORMAL_UP_LO), float(BLOOD_SHEEN_NORMAL_UP_HI), up);
}
// bbport (r100h_sheen-liquid): the share of the way to world up of such a gap pixel (the weight already
// holds the up gate): the film weight times mix(EDGE, 1, cover).
inline float FilledLevelShare(float up, float pool_share, float strength, int near_hits) {
    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);
    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * FillWeight(pool_share, up, near_hits) *
           (edge + (1.0f - edge) * cover);
}
static_assert(BLOOD_SHEEN_DARKEN_RED == 0.7 && BLOOD_SHEEN_DARKEN_OTHER == 0.4);
static_assert(BLOOD_SHEEN_DARKEN_LUMA_LO == 0.1 && BLOOD_SHEEN_DARKEN_LUMA_HI == 0.6);

struct Key {
    std::uint64_t vs = 0, ps = 0;
    std::uint32_t indices = 0; ///< 0: every draw of the pair
};

enum class Rule : std::uint32_t { Draw, Albedo };

struct Knobs {
    float strength = 0.0f; ///< 0: off
    bool show = false;
    std::array<Key, MaxKeys> keys{};
    std::uint32_t key_count = 0;
    std::uint32_t keys_bad = 0; ///< tokens of BB_BLOOD_SHEEN_DRAW that were not a readable key
    Rule rule = Rule::Draw;
    bool rule_bad = false; ///< BB_BLOOD_SHEEN_RULE was other text (taken as "draw")
    float ratio = DefaultRatio, lum_max = DefaultLumMax;
    float darken = DefaultDarken; ///< BB_BLOOD_SHEEN_DARKEN, 0..1 (0: no dimming pass)
};

/// BB_BLOOD_SHEEN's text: the strength (0: off) and the test view.
inline Knobs ReadStrength(const char* text) {
    Knobs k;
    if (text == nullptr || text[0] == '\0') {
        return k;
    }
    const char* t = text;
    while (*t == ' ') {
        ++t;
    }
    if (t[0] == 's' && t[1] == 'h' && t[2] == 'o' && t[3] == 'w') {
        const char* rest = t + 4;
        while (*rest == ' ') {
            ++rest;
        }
        if (*rest == '\0') {
            k.strength = 1.0f;
            k.show = true;
        }
        return k;
    }
    char* end = nullptr;
    const float value = std::strtof(t, &end);
    if (end == t || !std::isfinite(value)) {
        return k;
    }
    while (*end == ' ') {
        ++end;
    }
    if (*end != '\0' || !(value > 0.0f)) {
        return k;
    }
    k.strength = std::clamp(value, MinStrength, MaxStrength);
    return k;
}

/// One hex number of 1 to 16 digits ("0x" optional) from `p` up to `end`; false if not one.
inline bool Hex(const char* p, const char* end, std::uint64_t& out) {
    if (end - p >= 2 && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
    }
    if (p == end || end - p > 16) {
        return false;
    }
    std::uint64_t v = 0;
    for (; p != end; ++p) {
        const int c = static_cast<unsigned char>(*p);
        int d = -1;
        if (c >= '0' && c <= '9') {
            d = c - '0';
        } else if (c >= 'a' && c <= 'f') {
            d = c - 'a' + 10;
        } else if (c >= 'A' && c <= 'F') {
            d = c - 'A' + 10;
        }
        if (d < 0) {
            return false;
        }
        v = (v << 4) | std::uint64_t(d);
    }
    out = v;
    return true;
}

/// A decimal count 1..2^31 from `p` up to `end`; false if not one.
inline bool Count(const char* p, const char* end, std::uint32_t& out) {
    if (p == end || end - p > 10) {
        return false;
    }
    std::uint64_t v = 0;
    for (; p != end; ++p) {
        if (*p < '0' || *p > '9') {
            return false;
        }
        v = v * 10 + std::uint64_t(*p - '0');
    }
    if (v == 0 || v > (1ull << 31)) {
        return false;
    }
    out = std::uint32_t(v);
    return true;
}

/// BB_BLOOD_SHEEN_DRAW into `k`.
inline void ReadKeys(Knobs& k, const char* text) {
    k.key_count = 0;
    k.keys_bad = 0;
    const char* p = text ? text : "";
    while (*p != '\0') {
        while (*p == ';' || *p == ',' || *p == ' ') {
            ++p;
        }
        const char* start = p;
        while (*p != '\0' && *p != ';' && *p != ',' && *p != ' ') {
            ++p;
        }
        if (start == p) {
            continue;
        }
        const char* c1 = start;
        while (c1 != p && *c1 != ':') {
            ++c1;
        }
        const char* c2 = c1 == p ? p : c1 + 1;
        while (c2 != p && *c2 != ':') {
            ++c2;
        }
        Key key;
        const bool read = c1 != p && Hex(start, c1, key.vs) && Hex(c1 + 1, c2, key.ps) &&
                          (c2 == p || Count(c2 + 1, p, key.indices));
        if (!read || k.key_count == MaxKeys) {
            ++k.keys_bad;
            continue;
        }
        k.keys[k.key_count++] = key;
    }
}

/// BB_BLOOD_SHEEN_RULE into `k`.
inline void ReadRule(Knobs& k, const char* text) {
    k.rule = Rule::Draw;
    k.rule_bad = false;
    k.ratio = DefaultRatio;
    k.lum_max = DefaultLumMax;
    const char* t = text ? text : "";
    while (*t == ' ') {
        ++t;
    }
    const char* end = t;
    while (*end != '\0') {
        ++end;
    }
    while (end > t && end[-1] == ' ') {
        --end;
    }
    const auto is = [&](const char* word) {
        const char* a = t;
        while (*word != '\0' && a != end && *a == *word) {
            ++a;
            ++word;
        }
        return *word == '\0' ? a : nullptr;
    };
    if (t == end) {
        return;
    }
    if (const char* a = is("draw"); a == end) {
        return;
    }
    const char* a = is("albedo");
    if (a == nullptr || (a != end && *a != ':')) {
        k.rule_bad = true;
        return;
    }
    float values[2] = {DefaultRatio, DefaultLumMax};
    for (int i = 0; i < 2 && a != end; ++i) {
        ++a; // the ':'
        const char* stop = a;
        while (stop != end && *stop != ':') {
            ++stop;
        }
        char number[24] = {};
        if (stop == a || stop - a >= static_cast<std::ptrdiff_t>(sizeof(number))) {
            k.rule_bad = true;
            return;
        }
        std::copy(a, stop, number);
        char* used = nullptr;
        const float v = std::strtof(number, &used);
        if (used != number + (stop - a) || !std::isfinite(v)) {
            k.rule_bad = true;
            return;
        }
        values[i] = v;
        a = stop;
    }
    if (a != end || values[0] < MinRatio || values[0] > MaxRatio || !(values[1] > 0.0f) || values[1] > 1.0f) {
        k.rule_bad = true;
        return;
    }
    k.rule = Rule::Albedo;
    k.ratio = values[0];
    k.lum_max = values[1];
}

inline Knobs Read(const char* sheen, const char* draw, const char* rule) {
    Knobs k = ReadStrength(sheen);
    ReadKeys(k, draw);
    ReadRule(k, rule);
    return k;
}

/// BB_BLOOD_SHEEN_DARKEN's text: a number into 0..1; unset, empty or other text: the default.
inline float ReadDarken(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return DefaultDarken;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return DefaultDarken;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, 1.0f) : DefaultDarken;
}

/// BB_BLOOD_SHEEN_PEAK's text (r100k_sheen-no-hot-spot): a number into 0..MaxPeak (0: no ceiling); unset, empty or
/// other text: the default. Never a pure function of anything but its text, so the live knobs can call it.
inline float ReadPeak(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return PeakDefault;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return PeakDefault;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, MaxPeak) : PeakDefault;
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs = [] {
        Knobs k = Read(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_DRAW"),
                       std::getenv("BB_BLOOD_SHEEN_RULE"));
        k.darken = ReadDarken(std::getenv("BB_BLOOD_SHEEN_DARKEN"));
        return k;
    }();
    return knobs;
}

/// A draw is keyed: a key names its pair and (when the key has a count) its index count.
inline bool Matches(const Knobs& k, std::uint64_t vs, std::uint64_t ps, std::uint32_t indices) {
    for (std::uint32_t i = 0; i < k.key_count; ++i) {
        const Key& key = k.keys[i];
        if (key.vs == vs && key.ps == ps && (key.indices == 0 || key.indices == indices)) {
            return true;
        }
    }
    return false;
}

/// The knobs can pick a pixel at all: a key, or the albedo rule (alone it looks at every pixel).
inline bool CanPick(const Knobs& k) {
    return k.key_count != 0 || k.rule == Rule::Albedo;
}

/// The shader's albedo rule, the same arithmetic (linear albedo).
inline bool DarkRed(const Knobs& k, float r, float g, float b) {
    const float lum = 0.2126f * r + 0.7152f * g + 0.0722f * b;
    return r >= RedMin && r >= k.ratio * g && r >= k.ratio * b && lum <= k.lum_max;
}

/// The shader's wet film, the same arithmetic: the gloss and the specular colour's root after EDIT.
struct Film {
    float gloss = 0.0f, root = 0.0f;
};
inline Film Wet(float gloss, float root, float strength, float weight = 1.0f) {
    // r100h_sheen-liquid: the gloss goes TO the film's (the ground's may go down), the root never lowered;
    // `weight` is the pixel's share of the film (1; a gap of the pool: FillWeight).
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    const float target = std::min(WetSpecRoot * std::sqrt(std::max(strength, 1.0f)), SpecRootMax);
    return {gloss + (WetGloss - gloss) * w, std::max(root, root + (target - root) * w)};
}
/// bbport (r100i_sheen-blood-tint): a wet pixel's specular root, three channels (the shader's arithmetic): the
/// film's root (Wet's target, before the tint) times the tint per channel; red is never lowered, green and blue
/// move to their target by the wet share (they may go down).
struct SpecRoot {
    float r = 0.0f, g = 0.0f, b = 0.0f;
};
inline SpecRoot WetSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f) {
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    const float root = std::min(WetSpecRoot * std::sqrt(std::max(strength, 1.0f)), SpecRootMax);
    const float tr = root * TintR, tg = root * TintG, tb = root * TintB;
    return {std::max(ground_r, ground_r + (tr - ground_r) * w), ground_g + (tg - ground_g) * w,
            ground_b + (tb - ground_b) * w};
}
/// bbport (r100j_sheen-clean-rim): the share of the body's specular tint and gloss a made-wet pixel gets (the
/// shader's arithmetic; multiply it into the weight given to Wet and WetSpec): 1 for a pixel that passes the
/// albedo rule (`filled` false), else mix(FillSpec, 1, smoothstep(FILL_HI, 1, pool_share)) for a gap-fill pixel:
/// half at the pool's rim, the body's value deep inside, continuous in the share.
inline float RimSpecShare(bool filled, float pool_share) {
    if (!filled) {
        return 1.0f;
    }
    const float t = SmoothStep(float(BLOOD_SHEEN_FILL_HI), 1.0f, pool_share);
    return FillSpec + (1.0f - FillSpec) * t;
}
/// bbport (r100k_sheen-no-hot-spot): the weight a made-wet pixel gives its specular tint and gloss (the shader's
/// `ws`): w (strength, at most 1, times the fill weight `wet`) for a pixel that passes the albedo rule; for a
/// gap-fill pixel w times its fill weight AGAIN (squared falloff) times RimSpecShare: never above FillSpec (0.35)
/// x w where the share is at most FILL_HI, never above w.
inline float SpecWeight(float w, float wet, bool filled, float pool_share) {
    return w * (filled ? wet : 1.0f) * RimSpecShare(filled, pool_share);
}
/// bbport (r100k_sheen-no-hot-spot): the SHOW pass's luminance after the soft ceiling `peak` (> 0): unchanged up to
/// the knee (PeakKnee x peak), above it knee + span x (1 - exp(-(luma - knee) / span)), span = peak - knee:
/// continuous, slope 1 at the knee, increasing, never above peak. The pixel's colour is scaled by this / luma.
inline float PeakRoll(float luma, float peak) {
    const float knee = PeakKnee * peak;
    const float span = peak - knee;
    return luma <= knee ? luma : knee + span * (1.0f - std::exp(-(luma - knee) / span));
}

/// SHOW's dimming share of a pixel of luminance `luma` (the shader's arithmetic): `darken` where it is
/// dark (at or below DarkenLumaLo), 0 where it is bright (at or above DarkenLumaHi); the pixel is then
/// multiplied by (1 - share) + share x (DarkenRed, DarkenOther, DarkenOther).
inline float DimShare(float luma, float darken) {
    const float t = std::clamp((luma - DarkenLumaLo) / (DarkenLumaHi - DarkenLumaLo), 0.0f, 1.0f);
    return std::clamp(darken, 0.0f, 1.0f) * (1.0f - t * t * (3.0f - 2.0f * t));
}

/// blood_sheen.comp's push block, word for word (8 words).
struct Push {
    std::array<float, 2> size{};
    float strength = 0.0f;
    float ratio = DefaultRatio, lum_max = DefaultLumMax, red_min = RedMin;
    std::uint32_t flags = 0;
    float darken = 0.0f; ///< SHOW (not the test view): the share of the dimming, 0..1
};
static_assert(sizeof(Push) == 32);

/// The flags of a pass of frame slot `slot`.
inline std::uint32_t Flags(const Knobs& k, std::uint32_t slot) {
    return (k.show ? FlagShow : 0u) | ((slot & 1u) != 0 ? FlagSlot : 0u) | (k.key_count != 0 ? FlagKeyed : 0u) |
           (k.rule == Rule::Albedo ? FlagRuleAlbedo : 0u);
}

} // namespace Vulkan::BloodSheenRules
