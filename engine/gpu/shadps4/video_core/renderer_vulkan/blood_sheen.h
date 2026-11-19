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
//                         bbport (r128d_lrt-sheen-interior): unset or empty, the lantern.ini key graphics_blood_sheen
//                         (0..4, 0: off, read once at the start) gives the strength; set and not empty this wins
//                         (0 or text there is off, whatever the key says)
//   BB_BLOOD_SHEEN_DRAW   the keyed G-buffer draws: "vs:ps" (every draw of that hex pair) or
//                         "vs:ps:N" (only its draws of N indices, decimal), at most MaxKeys, separated by
//                         ';', ',' or spaces. bbport (r128d_lrt-sheen-interior): when neither this nor
//                         BB_BLOOD_SHEEN_RULE is set (not even empty) the default is "c829ee58:dbb222eb", the
//                         graveyard pool's own ground draw (with the albedo rule); one of the two set: no default
//   BB_BLOOD_SHEEN_RULE   "draw" (or unset): every pixel a keyed draw wrote last; "albedo": of those
//                         (or, with no key, of every G-buffer pixel) the dark red ones: linear red at
//                         least RedMin, at least Ratio times green and blue, luminance (0.2126 r +
//                         0.7152 g + 0.0722 b) at most LumMax; "albedo:R" and "albedo:R:L" set Ratio
//                         (1..16) and LumMax (0..1). Other text: "draw" (said in the log).
//   BB_BLOOD_SHEEN_DARKEN bbport (r100e): 0..1, default 0.5: how far the lit scene's dark picked pixels are
//                         dimmed and reddened after the lighting (times the strength, at most 1); 0: that
//                         pass does not run (the test view "show" never dims). Unset or other text:
//                         the default.
//   BB_BLOOD_SHEEN_PEAK   bbport (r100k): 0..64, default 6: the lit scene's ceiling for the picked pixels (a soft
//                         roll-off above half of it: a near light's highlight cannot blow out); 0: no ceiling.
//                         bbport (r129b_sheen-no-glow): a MULTIPLE of the dry scene's reference (the geometric mean of the
//                         max channel of the untagged pixels, measured on the GPU one frame late; 0.25 absolute
//                         before the first), applied to the max channel (r100k: 0..8 absolute luminance, default 0.7).
//                         Unset or other text: the default.
//   BB_BLOOD_SHEEN_RIM_FULL bbport (r129b): a live test knob (live knobs header only; else 0): 1: the pool's rim
//                         (gap-fill) pixels level their normal by the fill weight as r100h-r100k did; 0 or unset:
//                         by their specular weight (fill squared times the rim share)
//   BB_BLOOD_SHEEN_TINT   bbport (r130a): a live test knob (live knobs header only; else 1): 1, unset or other text: the
//                         r100i red specular tint; 0: no tint (the same root in all channels, f0 0.20 grey); 2: clear film
//                         (grey f0 0.0225, and the after-lighting dimming acts by the pixel's redness only)
//   BB_BLOOD_SHEEN_GLOSS  bbport (r130a): a live test knob, 0..1, default 1: the share of the way the gloss goes to the
//                         film's (0: the ground's own gloss)
//   BB_BLOOD_SHEEN_LEVEL  0..1: normal levelling (0 keeps the ground's relief). Defaults to 0.25 in clear film and 1
//                         in the other tint modes. A valid startup or live value overrides the default.
//   BB_BLOOD_SHEEN_DARKEN is live as well (r130a, live knobs header only)
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
inline constexpr std::uint32_t FlagRimFull = BLOOD_SHEEN_FLAG_RIM_FULL;     ///< r129b EDIT: rim pixels level by the fill weight
inline constexpr std::uint32_t FlagTintOff = BLOOD_SHEEN_FLAG_TINT_OFF;       ///< r130a EDIT: the specular target is untinted
inline constexpr std::uint32_t FlagTintClear = BLOOD_SHEEN_FLAG_TINT_CLEAR;   ///< r130a EDIT: clear film; SHOW: dim by redness
inline constexpr std::uint32_t FlagAutoGround = BLOOD_SHEEN_FLAG_AUTO_GROUND; ///< EDIT: default ground selector
static_assert(Group == 8u && SlotWords == 8u);
static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull) == 127u);
static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull | FlagTintOff |
               FlagTintClear | FlagAutoGround) == 1023u);
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
// bbport (r130a_sheen-colour): the clear film's specular root (grey, f0 0.0225).
inline constexpr float ClearRoot = float(BLOOD_SHEEN_CLEAR_ROOT);
static_assert(BLOOD_SHEEN_CLEAR_ROOT == 0.15);
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
inline constexpr float MaxPeak = 64.0f;                               ///< r100k: the largest BB_BLOOD_SHEEN_PEAK (r129b: 64)
static_assert(BLOOD_SHEEN_PEAK_DEFAULT == 6.0 && BLOOD_SHEEN_PEAK_KNEE == 0.5 && BLOOD_SHEEN_PEAK_FALLBACK == 0.25);
// bbport (r129b_sheen-no-glow): the dry-scene reference the ceiling is relative to (blood_sheen_layout.h has the words).
inline constexpr float PeakFallback = float(BLOOD_SHEEN_PEAK_FALLBACK); ///< the absolute max-channel ceiling before a reference
inline constexpr std::uint32_t RefBase = BLOOD_SHEEN_REF_BASE, RefSlotWords = BLOOD_SHEEN_REF_SLOT_WORDS;
inline constexpr float RefBias = float(BLOOD_SHEEN_REF_BIAS), RefScale = float(BLOOD_SHEEN_REF_SCALE);
inline constexpr float RefMaxCode = float(BLOOD_SHEEN_REF_MAX_CODE), RefMin = float(BLOOD_SHEEN_REF_MIN);
static_assert(RefBase == Slots * SlotWords && RefSlotWords == 3u && BLOOD_SHEEN_REF_BIAS == 16.0 && BLOOD_SHEEN_REF_SCALE == 64.0);
static_assert(BLOOD_SHEEN_REF_MAX_CODE == 2047.0 && BLOOD_SHEEN_REF_MIN == 0.000244140625);
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
// bbport (r129b_sheen-no-glow): times the fill weight once more and the rim's specular share (FILL_SPEC at the rim, 1 deep
// inside the pool: RimSpecShare(true, share)), so the rim stones keep their relief; `rim_full` (BB_BLOOD_SHEEN_RIM_FULL):
// the r100h-r100k value, the film weight alone.
inline float FilledLevelShare(float up, float pool_share, float strength, int near_hits, bool rim_full = false) {
    const float cover = SmoothStep(float(BLOOD_SHEEN_COVER_LO), float(BLOOD_SHEEN_COVER_HI), pool_share);
    const float edge = float(BLOOD_SHEEN_NORMAL_EDGE);
    const float fill = FillWeight(pool_share, up, near_hits);
    const float rim = FillSpec + (1.0f - FillSpec) * SmoothStep(float(BLOOD_SHEEN_FILL_HI), 1.0f, pool_share);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * fill * (edge + (1.0f - edge) * cover) *
           (rim_full ? 1.0f : fill * rim);
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
    bool from_ini = false;     ///< bbport (r128d): the strength came from graphics_blood_sheen
    bool default_pick = false; ///< bbport (r128d): the pool's own draw and the albedo rule are the defaults taken
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

// bbport (r128d_lrt-sheen-interior): the draw and the rule the pool was tested with (r100c/r100d probes, every
// graveyard job since b52), taken when neither BB_BLOOD_SHEEN_DRAW nor BB_BLOOD_SHEEN_RULE is set.
inline constexpr const char* DefaultDrawText = "c829ee58:dbb222eb";
inline constexpr const char* DefaultRuleText = "albedo";

/// bbport (r128d): the strength lantern.ini's graphics_blood_sheen gives (0: none), handed over once by the engine
/// (BloodSheen::Wanted) before the first Load.
inline float& IniStrength() {
    static float strength = 0.0f;
    return strength;
}

/// bbport (r128d): Read, plus the ini strength and the defaults. `sheen` set and not empty decides alone (0 or other
/// text: off); else `ini` (finite and above 0, put into MinStrength..MaxStrength) gives the strength. `draw` and
/// `rule` both nullptr (unset): the pool's draw and the albedo rule; one of them set, even empty: as Read.
inline Knobs ReadUsable(const char* sheen, const char* draw, const char* rule, float ini) {
    const bool env = sheen != nullptr && sheen[0] != '\0';
    const bool from_ini = !env && std::isfinite(ini) && ini > 0.0f;
    const bool defaults = draw == nullptr && rule == nullptr;
    Knobs k = Read(env ? sheen : nullptr, defaults ? DefaultDrawText : draw, defaults ? DefaultRuleText : rule);
    if (from_ini) {
        k.strength = std::clamp(ini, MinStrength, MaxStrength);
    }
    k.from_ini = from_ini;
    k.default_pick = defaults && k.strength > 0.0f;
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
        Knobs k = ReadUsable(std::getenv("BB_BLOOD_SHEEN"), std::getenv("BB_BLOOD_SHEEN_DRAW"),
                             std::getenv("BB_BLOOD_SHEEN_RULE"), IniStrength()); // bbport (r128d)
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
inline SpecRoot WetSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f,
                        bool tint_off = false) { // r130a: tint_off = BB_BLOOD_SHEEN_TINT 0 (FlagTintOff)
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    const float root = std::min(WetSpecRoot * std::sqrt(std::max(strength, 1.0f)), SpecRootMax);
    const float tr = root * (tint_off ? 1.0f : TintR), tg = root * (tint_off ? 1.0f : TintG),
                tb = root * (tint_off ? 1.0f : TintB);
    return {std::max(ground_r, ground_r + (tr - ground_r) * w), ground_g + (tg - ground_g) * w,
            ground_b + (tb - ground_b) * w};
}
/// bbport (r130a_sheen-colour): BB_BLOOD_SHEEN_TINT's text: 0, 1 or 2 (spaces around it allowed); unset, empty or other text: 1.
inline int ReadTint(const char* text) {
    if (text == nullptr) {
        return 1;
    }
    while (*text == ' ') {
        ++text;
    }
    if (text[0] < '0' || text[0] > '2') {
        return 1;
    }
    const char* end = text + 1;
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? text[0] - '0' : 1;
}
/// bbport (r131b_lrt-settings): BB_BLOOD_SHEEN_TINT as the variable half of the setting rule: unset or empty: -1 (the setting decides),
/// else ReadTint (a variable that is set decides, also with text: 1).
inline int ReadTintEnv(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : ReadTint(text);
}
/// The tint in force: the variable's (0..2) when it is set and not empty (env >= 0), else the setting graphics_blood_sheen_tint into 0..2.
constexpr int TintOf(int env, int setting) {
    return env >= 0 ? env : std::clamp(setting, 0, 2);
}
/// A finite share clamped to 0..1, or fallback if the text is absent or invalid.
inline float ReadShareOr(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return fallback;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, 1.0f) : fallback;
}

/// BB_BLOOD_SHEEN_GLOSS has the same default in every mode.
inline float ReadShare(const char* text) {
    return ReadShareOr(text, 1.0f);
}

constexpr float LevelOf(int tint, float override_share) {
    return override_share >= 0.0f ? override_share : (tint == 2 ? 0.25f : 1.0f);
}
/// bbport (r130a_sheen-colour): the EDIT push word: the gloss share in the low 16 bits, the level share in the high 16, each
/// a unorm16 (GLSL unpackUnorm2x16: x low half); (1, 1) is 0xFFFFFFFF, which unpacks to exactly (1.0, 1.0).
inline std::uint32_t PackScales(float gloss, float level) {
    const auto unorm = [](float v) {
        return static_cast<std::uint32_t>(std::lround(std::clamp(v, 0.0f, 1.0f) * 65535.0f));
    };
    return unorm(gloss) | (unorm(level) << 16);
}
/// bbport (r130a_sheen-colour): a wet pixel's specular after the clear film (the shader's arithmetic): every channel moves to
/// ClearRoot by the wet weight (strength, at most 1, times `weight`); it may go down.
inline SpecRoot ClearSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f) {
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    return {ground_r + (ClearRoot - ground_r) * w, ground_g + (ClearRoot - ground_g) * w,
            ground_b + (ClearRoot - ground_b) * w};
}
/// bbport (r130a_sheen-colour): the redness of a lit pixel (the SHOW shader's red_share): 0 for a light-coloured highlight
/// (blue or green at least red), up to 1 for pure red.
inline float RedShare(float r, float g, float b) {
    return std::clamp((r - std::max(g, b)) / std::max(r, 1e-6f), 0.0f, 1.0f);
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

/// bbport (r129b_sheen-no-glow): a dry pixel's reference code (the shader's arithmetic): the log2 of its max channel (at
/// least RefMin) on a scale of RefScale steps a stop from -RefBias, clamped to 0..RefMaxCode, truncated.
inline std::uint32_t RefCode(float r, float g, float b) {
    const float top = std::max(std::max(r, g), std::max(b, RefMin));
    return static_cast<std::uint32_t>(std::clamp((std::log2(top) + RefBias) * RefScale, 0.0f, RefMaxCode));
}
/// A dry pixel is counted only when all three channels are finite (the shader skips a NaN or an Inf).
inline bool RefUsable(float r, float g, float b) {
    return std::isfinite(r) && std::isfinite(g) && std::isfinite(b);
}
/// The dry scene's reference of a show's slot: the geometric mean of the max channel, 2^(sum / n / RefScale - RefBias); 0 when
/// n (the samples) is 0.
inline float RefMean(std::uint32_t sum, std::uint32_t n) {
    return n == 0 ? 0.0f : std::exp2(float(sum) / float(n) / RefScale - RefBias);
}
/// The ceiling (max channel) of a show: `rel` (BB_BLOOD_SHEEN_PEAK; 0: none, 0 out) times the reference of the other slot
/// (sum, n); PeakFallback while that slot holds no sample.
inline float PeakOf(float rel, std::uint32_t sum, std::uint32_t n) {
    if (!(rel > 0.0f)) {
        return 0.0f;
    }
    return n == 0 ? PeakFallback : rel * RefMean(sum, n);
}
/// A wet pixel's colour after the ceiling `peak` (> 0; else unchanged), the shader's arithmetic: the max channel through
/// PeakRoll, the colour scaled by it (hue kept).
inline std::array<float, 3> CapRgb(std::array<float, 3> rgb, float peak) {
    const float top = std::max(rgb[0], std::max(rgb[1], rgb[2]));
    if (peak > 0.0f && top > PeakKnee * peak) {
        const float scale = PeakRoll(top, peak) / top;
        for (float& c : rgb) {
            c *= scale;
        }
    }
    return rgb;
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
