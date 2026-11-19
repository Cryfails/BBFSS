// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r131a_foliage-translucency): the pure parts of the foliage translucency: the knobs (rules and tuning), the share of light a
// leaf passes and its hue (the CPU mirror of rt_cards.glsl's cardLeafPass and of the CARD_TRANSMIT rule in cardTraceShadow), and the
// zero-luma hue term of the sun. No Vulkan: tests/test_foliage_translucency.cpp builds this header alone. The functions at the end
// (On, LightThrough, ...) are made by vk_foliage_glow.cpp, which reads the environment, lantern.ini and the cards' own knobs once.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <span>

#include "rt_card_layers.h"
#include "../host_shaders/foliage_glow_layout.h"

namespace Vulkan::FoliageTranslucency {

using Rgb = std::array<float, 3>;

/// The ini key graphics_foliage_translucency: bit 1 light through leaves (A), bit 2 the back-lit glow (B).
inline constexpr int SettingOff = 0, SettingLight = 1, SettingGlow = 2, SettingBoth = 3;

/// The tuning knobs (BB_FOLIAGE_*), with their defaults and limits.
struct Tune {
    float pass = 0.25f;     ///< BB_FOLIAGE_PASS: T, the luma share a leaf lets through
    float tint = 1.0f;      ///< BB_FOLIAGE_TINT: how much of the leaf's hue the light takes, 0 grey, 1 all of it
    float floor = 0.02f;    ///< BB_FOLIAGE_FLOOR: a product below this is blocked
    float strength = 1.0f;  ///< BB_FOLIAGE_GLOW_STRENGTH
    float wrap = 0.3f;      ///< BB_FOLIAGE_WRAP: how far past the edge the back-lit term reaches
    float sun_k = 0.318f;   ///< BB_FOLIAGE_SUN_K: the game's diffuse scale for the sun (a guess)
    bool glow_view = false; ///< BB_FOLIAGE_GLOW_VIEW: TOOL, the added term x8 over a dim scene
};
inline constexpr float PassMin = 0.05f, PassMax = 0.5f, TintMax = 1.0f, FloorMin = 0.001f, FloorMax = 0.5f;
inline constexpr float StrengthMax = 8.0f, WrapMax = 1.0f, SunKMin = 0.05f, SunKMax = 2.0f;

[[nodiscard]] inline bool EnvGiven(const char* text) noexcept {
    return text != nullptr && text[0] != '\0';
}
/// Exactly "1" is on; anything else that is given is off.
[[nodiscard]] inline bool ExactOne(const char* text) noexcept {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}
/// A number in [lo, hi]; unset, empty, text or not finite: `fallback`; outside: the nearest end.
[[nodiscard]] inline float ReadFloat(const char* text, float fallback, float lo, float hi) noexcept {
    if (!EnvGiven(text)) {
        return fallback;
    }
    char* end = nullptr;
    const double v = std::strtod(text, &end);
    if (end == text || *end != '\0' || !std::isfinite(v)) {
        return fallback;
    }
    return std::clamp(float(v), lo, hi);
}
/// The tuning from a getter (std::getenv in the engine, a table in the test).
template <typename Getter>
[[nodiscard]] inline Tune ReadTune(Getter get) noexcept {
    Tune t;
    t.pass = ReadFloat(get("BB_FOLIAGE_PASS"), t.pass, PassMin, PassMax);
    t.tint = ReadFloat(get("BB_FOLIAGE_TINT"), t.tint, 0.0f, TintMax);
    t.floor = ReadFloat(get("BB_FOLIAGE_FLOOR"), t.floor, FloorMin, FloorMax);
    t.strength = ReadFloat(get("BB_FOLIAGE_GLOW_STRENGTH"), t.strength, 0.0f, StrengthMax);
    t.wrap = ReadFloat(get("BB_FOLIAGE_WRAP"), t.wrap, 0.0f, WrapMax);
    t.sun_k = ReadFloat(get("BB_FOLIAGE_SUN_K"), t.sun_k, SunKMin, SunKMax);
    t.glow_view = ExactOne(get("BB_FOLIAGE_GLOW_VIEW"));
    return t;
}

/// What the knobs decide before the cards' own switches: master (the foliage translucency at all), light (A), glow (B).
struct Decision {
    bool master = false;
    bool light = false;
    bool glow = false;
    const char* why = "off"; ///< when the master is off: the reason
};
/// BB_FOLIAGE_TRANSLUCENCY (exactly "1" on, other text off) wins over the ini setting (0 off, 1 A, 2 B, 3 both: any above 0 is on); a
/// master that is on without a sub-switch has both on from the variable, and from the setting the bits it names. BB_FOLIAGE_LIGHT_THROUGH
/// and BB_FOLIAGE_GLOW, when given, decide for their part (exactly "1" on). The master needs the alpha layers (BB_RT_CARD_ALPHA=2).
[[nodiscard]] inline Decision Decide(const char* master_env, const char* light_env, const char* glow_env, int setting,
                                     bool alpha_layers) noexcept {
    Decision d;
    const int s = std::clamp(setting, SettingOff, SettingBoth);
    const bool env = EnvGiven(master_env);
    const bool on = env ? ExactOne(master_env) : s > 0;
    if (!on) {
        d.why = env ? "off (BB_FOLIAGE_TRANSLUCENCY is not 1)" : "off";
        return d;
    }
    if (!alpha_layers) {
        d.why = "off: needs BB_RT_CARD_ALPHA=2";
        return d;
    }
    const int bits = env ? SettingBoth : s;
    d.master = true;
    d.light = EnvGiven(light_env) ? ExactOne(light_env) : (bits & SettingLight) != 0;
    d.glow = EnvGiven(glow_env) ? ExactOne(glow_env) : (bits & SettingGlow) != 0;
    d.why = "";
    return d;
}

[[nodiscard]] inline float Luma(const Rgb& c) noexcept {
    return 0.299f * c[0] + 0.587f * c[1] + 0.114f * c[2];
}
[[nodiscard]] inline float Max3(const Rgb& c) noexcept {
    return std::max(std::max(c[0], c[1]), c[2]);
}

/// cardLeafPass: the light a leaf texel passes. `stored` is the colour layer's rgb (the square root of the linear leaf colour). T is the
/// luma share; the leaf sets the hue (leaf / luma(leaf), each channel at most 3), `tint` mixes it with grey.
[[nodiscard]] inline Rgb LeafPass(const Rgb& stored, float share, float tint) noexcept {
    Rgb leaf{stored[0] * stored[0], stored[1] * stored[1], stored[2] * stored[2]};
    const float l = std::max(Luma(leaf), 1e-3f);
    Rgb out{};
    for (int i = 0; i < 3; ++i) {
        const float hue = std::min(leaf[i] / l, 3.0f);
        out[i] = share * (1.0f + (hue - 1.0f) * tint);
    }
    return out;
}

/// What a traversal hands the loop, in its order. kind: CARD_NO_DATA, CARD_DROPPED, CARD_KEPT (a leaf texel) or CardRayOpaque.
struct Event {
    std::uint32_t kind = CARD_DROPPED;
    Rgb colour{1.0f, 1.0f, 1.0f}; ///< a kept texel's stored colour layer value
    bool grey = false;            ///< a kept texel of a layer without colour (a mask texture): passes grey
};
struct PassResult {
    std::uint32_t how = CARD_RAY_FREE;
    std::uint32_t seen = 0, tested = 0, no_data = 0;
    Rgb product{1.0f, 1.0f, 1.0f}; ///< the light that got through the leaves passed
    std::uint32_t passed = 0, floor_ended = 0, grey = 0;
};
/// cardTraceShadow's loop with the CARD_TRANSMIT rule: a kept texel with a share above 0 multiplies the product by what it passes and the
/// ray goes on, unless the product falls below `floor` (then the texel blocks as before). Share 0 is CardRayRun, bit for bit. Opaque hits
/// end the ray; the cap and the guard count as in CardRayRun (a passed leaf is a tested one).
[[nodiscard]] inline PassResult PassRun(std::span<const Event> events, std::uint32_t cap, float share, float tint, float floor) noexcept {
    PassResult r;
    for (const Event& e : events) {
        if (e.kind == CardRayOpaque) {
            r.how = CARD_RAY_OPAQUE;
            return r;
        }
        ++r.seen;
        if (r.tested >= cap || r.seen > cap * CARD_RAY_GUARD) {
            r.how = CARD_RAY_CAP;
            return r;
        }
        if (e.kind == CARD_NO_DATA) {
            ++r.no_data;
            continue;
        }
        ++r.tested;
        if (e.kind == CARD_KEPT) {
            if (share > 0.0f) {
                Rgb pass{share, share, share};
                if (e.grey) {
                    ++r.grey;
                } else {
                    pass = LeafPass(e.colour, share, tint);
                }
                for (int i = 0; i < 3; ++i) {
                    r.product[i] *= pass[i];
                }
                ++r.passed;
                if (Max3(r.product) >= floor) {
                    continue;
                }
                ++r.floor_ended;
            }
            r.how = CARD_RAY_KEPT;
            return r;
        }
    }
    return r;
}

/// The lamp's reading of a ray that ended free: the grey it dims the lamp by and the hue it gives (point_shadow_ray.comp lampVisibility).
struct LampLight {
    float grey = 1.0f;
    Rgb hue{1.0f, 1.0f, 1.0f};
};
[[nodiscard]] inline LampLight LampLightOf(const Rgb& product) noexcept {
    LampLight l;
    const float g = Luma(product);
    l.grey = std::min(g, 1.0f);
    if (g > 1e-4f) {
        l.hue = {product[0] / g, product[1] / g, product[2] / g};
    }
    return l;
}

/// The sun trace's hue image texel (rt_shadow.comp FOLIAGE builds): rgb = half the mean hue of the rays that passed a leaf (0 to 2 stored in
/// 0 to 1), a = the share of the full sun that came through leaves. `hue_sum` is the sum of those rays' products, `leaf` the sum of their luma,
/// `rays` the sun rays of the pixel.
struct SunHueTexel {
    Rgb rgb{0.5f, 0.5f, 0.5f};
    float a = 0.0f;
};
[[nodiscard]] inline SunHueTexel SunHueStore(const Rgb& hue_sum, float leaf, float rays) noexcept {
    SunHueTexel t;
    const float d = std::max(leaf, 1e-4f);
    for (int i = 0; i < 3; ++i) {
        t.rgb[i] = 0.5f * hue_sum[i] / d;
    }
    t.a = rays > 0.0f ? leaf / rays : 0.0f;
    return t;
}
/// The composite's term (foliage_glow.comp): (2 rgb - 1) times a. Its luma is 0 when the mean hue has luma 1, so only the colour of the
/// light changes, never its brightness.
[[nodiscard]] inline Rgb SunHueTerm(const SunHueTexel& t) noexcept {
    return {(2.0f * t.rgb[0] - 1.0f) * t.a, (2.0f * t.rgb[1] - 1.0f) * t.a, (2.0f * t.rgb[2] - 1.0f) * t.a};
}

/// The back-lit factor (foliage_glow.comp): how far the light lies behind the leaf. `n_dot_l` is the dot of the camera-facing normal with the
/// direction toward the light; 0 when the light is in front.
[[nodiscard]] inline float BackLit(float n_dot_l, float wrap) noexcept {
    return std::clamp((-n_dot_l + wrap) / (1.0f + wrap), 0.0f, 1.0f);
}

/// The specialization constants of the lamp pass's FOLIAGE builds (vk_point_shadow.cpp MakeCardBuild): 16 share, 17 tint, 18 floor, 19 hue.
struct LampSpec {
    float pass = 0.25f, tint = 1.0f, floor = 0.02f;
    std::uint32_t hue = 0; ///< the lamps keep their own hue as well (BB_LAMP_SHADOW_COLOUR=1)
};

static_assert(CARD_COLOUR_SIZE == 64 && FG_MAX_LAMPS == 32 && FG_DATA_WORDS == 8 + FG_MAX_LAMPS * 8);
static_assert(FG_PUSH_BYTES == 112 && FG_COUNTER_WORDS == 8);

// Made by vk_foliage_glow.cpp (read once; the first call prints the start line). On: the master is on and the alpha layers exist.
// LightThrough: A, which needs the colour layers. LampThrough: A for the lamp rays (needs BB_RT_CARD_LAMPS=1). SunThrough: A for the sun
// and moon (needs BB_RT_CARD_SUN=1). Glow: B (needs BB_RT_CARD_LAMPS=1: the cards in the scene).
[[nodiscard]] bool On();
[[nodiscard]] bool LightThrough();
[[nodiscard]] bool LampThrough();
[[nodiscard]] bool SunThrough();
[[nodiscard]] bool Glow();
[[nodiscard]] const Tune& Tuning();
// LightNow and GlowNow: A and B as they are now: the start value (LightThrough, Glow), switched off or on again live by BB_FOLIAGE_LIGHT_THROUGH and
// BB_FOLIAGE_GLOW in the test tools' live knobs file where the build has it (a slot run: set:BB_FOLIAGE_GLOW=0). A part that was off at the start
// stays off (its builds and layers were not made). The lamp pass hands LampFlagOn to its FOLIAGE builds in word 16 of a pass's data.
[[nodiscard]] bool LightNow();
[[nodiscard]] bool GlowNow();
inline constexpr std::uint32_t LampFlagOn = 256u; // point_shadow_ray.comp FOLIAGE_FLAG_ON

} // namespace Vulkan::FoliageTranslucency
