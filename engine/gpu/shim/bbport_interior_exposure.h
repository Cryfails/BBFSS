// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r99_interior-exposure, r99b_interior-brightness): a brighten-only exposure lift for dark
// interiors, part of the lamp work. A meter (Vulkan::InteriorExposure::Meter,
// host_shaders/interior_meter.comp) takes GridX x GridY samples of the HDR scene colour and depth
// at the upscaler, before the tone curve: the log-average of their Rec.709 luminance, each clamped
// to [LumMin, LumMax], leaving out the sky (depth 1, the clear value), and how many samples are
// "open": at depth 1, or farther than the open distance (BB_INTERIOR_EXPOSURE_OPEN_M, view depth
// from the camera's projection). Want() turns one reading into a lift in stops; Step() eases the
// applied lift toward it in real time; the lift, as a factor, multiplies the GT7/ACES exposure
// pushed to the game's final composite (Pipeline::BindResources). The game's own curve
// (graphics_tonemapper=original) and the HDR curve extension take no exposure, so with them it
// changes nothing.
//
// The rule (Want): gap = log2(target / metered), at least 0; wanted = min(max_ev, strength * gap)
// * indoor, indoor = 1 - smoothstep(SkyOpen, SkyGone, eased open share). The open share is eased
// in real time (StepOpen): it follows a rise within OpenRiseSeconds and a fall over
// OpenFallSeconds, so a view with SkyGone or more open samples stops the lift almost at once,
// while the lift comes only after a few seconds of a view with fewer (walking into a room). A
// reading metered without the open distance (no usable camera) does not move the eased share. So
// a scene metered at or above the target, or one that showed SkyGone or more open samples lately,
// gets no lift, and the lift never darkens. Whether a dark street shows that many samples at the
// open distance is not known: the log line measures it. A reading metered below BlackFrame (a
// black or fading frame) or without a number keeps the lift as it is. Pure: no Vulkan, no
// settings; tested by tests/test_interior_exposure.cpp.
//
// The far gate (r99d_interior-open-gate): a deep outdoor courtyard (the graveyard at night, ringed by
// tall walls) shows almost no sky and nothing 80 m away, so the open gate alone lifted it by the full
// 0.75 stops. The reading also counts the samples at least a quarter of the open distance away (20 m
// at 80 m). FarShare = (sky + that count) / all samples, eased like the open share (StepFar: FarRise
// 0.15 s, FarFall 2 s, from OpenStart), and the lift is multiplied by FarGate = 1 - smoothstep(FarFull
// 0.18, FarNone 0.40, eased far share): the church's long hall (11.3% at 20 m, measured) keeps the
// full lift, the graveyard (64.0%) gets none, the library and the dream house (0 to 3%) are unchanged.
// Lift::indoor = open gate x far gate.
//
// The followed target (r99e_interior-slider-works): with the target fixed at 0.02 the slider only capped a
// zero in a room metered above it (build 72: the library with the hand lantern out metered 0.02246 and
// every slider position gave "applied +0.000 EV"). EffectiveTarget = target * 2^(TargetPerStop * max_ev), at
// most TargetFollowCeiling, never below the target: 0.034 at the default 0.75, 0.04 at 1, 0.08 at 2, 0.16
// at 3. The lift is min(max_ev, strength * log2(effective target / metered)) times the gates as before, so
// the lift rises with the slider in every room that meters under the target. Resolve() sets
// Config::follow; SHOW and BB_INTERIOR_EXPOSURE_FOLLOW=0 keep the fixed target (r99d's numbers).
//
// Knobs (r99c_interior-default): ON by default, the largest lift 0.75 stops. The setting
// graphics_interior_brightness (BbSettings, 0..3 stops, default 0.75, 0 = off) is the largest lift;
// the meter reads it at every call, so a slider acts at once. The environment is read once
// (Environment()) and wins over the setting: BB_INTERIOR_EXPOSURE set and not empty: 0 off, 1 on
// (at the setting's lift, DefaultMaxEv when the setting is 0), 2 SHOW (the Show* values for every
// number not set), any other text off; unset or empty: the setting decides. BB_INTERIOR_EXPOSURE_MAX_EV
// (a number; an unreadable one is as unset) is the largest lift in place of the setting.
// BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _OPEN_M (0: only depth 1 counts as open, r99's rule) have
// no setting. A missing, unreadable or non-finite number takes the default, then the range. Resolve()
// puts the two together. r99's exact behaviour: OPEN_M=0 MAX_EV=1.5 (the open share is then eased too).
//
// Measured 2026-11-15 (hero light off, log-average before the tone curve; no measured view had any
// sample at depth 1): the library 0.014 (looking up 0.011; 0.0011-0.0055 with the BB PC Remaster
// mod), church-candles 0.040 (0.0053-0.012 with the mod), the dream house 0.018-0.052 (0.030 with
// the mod, hero light kept), the dark alley 0.025 (0.0097 with the mod). The defaults (target 0.02,
// strength 1, at most 0.75 stops: the owner's pick, 2026-11-16) lift the library +0.5 EV without the
// mod (log2(0.02 / 0.014)) and the full +0.75 with it, church-candles with the mod +0.7 to +0.75 EV,
// the dream house at most +0.15 EV (at 0.018; 0 from 0.02 up), church-candles without the mod
// nothing. Open places rely on the open share (the graveyard at night showed 100 % open samples and
// no lift).

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>

namespace BbInteriorExposure {

inline constexpr float DefaultTarget = 0.02f;  ///< log-average luminance aimed at
inline constexpr float DefaultStrength = 1.0f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 0.75f;   ///< the largest lift, stops (= BbSettings::InteriorBrightnessDefault)
inline constexpr float DefaultOpenMeters = 80.0f; ///< view depth from which a sample is open
inline constexpr float ShowTarget = 0.15f;     ///< BB_INTERIOR_EXPOSURE=2 (test): exaggerated
inline constexpr float ShowStrength = 1.0f;
inline constexpr float ShowMaxEv = 3.0f;
inline constexpr float TargetMin = 0.005f, TargetMax = 1.0f;
inline constexpr float MaxEvLimit = 3.0f;
inline constexpr float OpenMetersMax = 1000.0f; ///< BB_INTERIOR_EXPOSURE_OPEN_M range 0..this
inline constexpr float SkyOpen = 0.03f;    ///< eased open share where the lift starts to fade
inline constexpr float SkyGone = 0.15f;    ///< eased open share from which there is no lift
inline constexpr float FarFull = 0.18f;    ///< eased far share (depth 1 or 20 m+) up to which the lift is full
inline constexpr float FarNone = 0.40f;    ///< eased far share from which there is no lift
inline constexpr float FarRiseSeconds = 0.15f; ///< time constant while the far share grows
inline constexpr float FarFallSeconds = 2.0f;  ///< time constant while it shrinks
static_assert(FarFull > SkyOpen && FarFull < FarNone && FarNone <= 1.0f && FarRiseSeconds > 0.0f &&
              FarFallSeconds > 0.0f);
inline constexpr float TargetPerStop = 1.0f;        ///< r99e: stops the target rises per stop of the largest lift
inline constexpr float TargetFollowCeiling = 0.25f; ///< r99e: the followed target never passes this
static_assert(TargetPerStop >= 0.0f && TargetFollowCeiling > DefaultTarget);
inline constexpr float BlackFrame = 4e-4f; ///< metered below this: a black or fading frame, hold
inline constexpr float RiseSeconds = 1.0f; ///< time constant while the lift grows
inline constexpr float FallSeconds = 0.4f; ///< time constant while it shrinks
inline constexpr float OpenRiseSeconds = 0.15f; ///< time constant while the open share grows
inline constexpr float OpenFallSeconds = 1.5f;  ///< time constant while it shrinks
inline constexpr float OpenStart = 1.0f;   ///< the eased open share before the first reading
inline constexpr float MaxStep = 0.25f;    ///< s: the longest step one Step takes
inline constexpr unsigned GridX = 64, GridY = 36; ///< the meter's samples across, down
inline constexpr float LumMin = 1e-4f, LumMax = 64.0f; ///< each sample's luminance clamp (pushed)

enum Mode : int { Off = 0, On = 1, Show = 2 };

struct Config {
    int mode = Off;
    float target = DefaultTarget;
    float strength = DefaultStrength;
    float max_ev = DefaultMaxEv;
    float open_m = DefaultOpenMeters; ///< 0: only depth 1 is open
    bool follow = false;              ///< r99e: the target rises with max_ev (EffectiveTarget); Resolve() sets it
};

inline float Number(const char* text, float fallback, float lo, float hi) {
    float value = fallback;
    if (text && *text) {
        char* end = nullptr;
        const float read = std::strtof(text, &end);
        if (end != text && *end == '\0' && std::isfinite(read)) {
            value = read;
        }
    }
    return std::clamp(value, lo, hi);
}

inline Config Parse(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m = nullptr) {
    Config c;
    if (mode && mode[0] && !mode[1]) {
        c.mode = mode[0] == '1' ? On : mode[0] == '2' ? Show : Off;
    }
    const bool show = c.mode == Show;
    c.target = Number(target, show ? ShowTarget : DefaultTarget, TargetMin, TargetMax);
    c.strength = Number(strength, show ? ShowStrength : DefaultStrength, 0.0f, 1.0f);
    c.max_ev = Number(max_ev, show ? ShowMaxEv : DefaultMaxEv, 0.0f, MaxEvLimit);
    c.open_m = Number(open_m, DefaultOpenMeters, 0.0f, OpenMetersMax);
    return c;
}

/// The target Want() aims at (r99e). Not following (SHOW, BB_INTERIOR_EXPOSURE_FOLLOW=0, a Config from
/// Parse): c.target. Following: c.target * 2^(TargetPerStop * max_ev), at most TargetFollowCeiling and never
/// below c.target, so a bigger slider value also lifts the rooms that meter a little above the plain target.
inline float EffectiveTarget(const Config& c) {
    if (!c.follow) {
        return c.target;
    }
    const float raised = c.target * std::exp2(TargetPerStop * std::max(c.max_ev, 0.0f));
    return std::max(c.target, std::min(raised, TargetFollowCeiling));
}

/// A number that Number() reads from `text`: not null, not empty, all of it a finite number.
inline bool Readable(const char* text) {
    if (!text || !*text) {
        return false;
    }
    char* end = nullptr;
    const float read = std::strtof(text, &end);
    return end != text && *end == '\0' && std::isfinite(read);
}

/// What the environment says (read once, Environment()); the setting is Resolve()'s other half.
struct Env {
    Config config;           ///< Parse of the variables (mode Off unless BB_INTERIOR_EXPOSURE is 1 or 2)
    bool mode_set = false;   ///< BB_INTERIOR_EXPOSURE is set and not empty: it decides on, off or SHOW
    bool max_ev_set = false; ///< BB_INTERIOR_EXPOSURE_MAX_EV is a number: the largest lift
    bool follow = true;      ///< r99e: BB_INTERIOR_EXPOSURE_FOLLOW is not 0: the target follows the largest lift
};

inline Env ParseEnv(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m, const char* follow = nullptr) {
    Env e;
    e.config = Parse(mode, target, strength, max_ev, open_m);
    e.mode_set = mode != nullptr && mode[0] != '\0';
    e.max_ev_set = Readable(max_ev);
    e.follow = !(follow && follow[0] == '0' && follow[1] == '\0');
    return e;
}

/// The knobs of one frame: the environment's where it says something, else `setting`
/// (graphics_interior_brightness, stops; not finite: DefaultMaxEv; clamped to 0..MaxEvLimit), whose
/// 0 is off. SHOW keeps its own values (the variable's number for the largest lift when set).
/// BB_INTERIOR_EXPOSURE=1 with a setting of 0 and no number is on at DefaultMaxEv. Without the mode
/// variable a largest lift of 0 (the setting, or the number) is off, so nothing is made.
inline Config Resolve(const Env& env, float setting) {
    Config c = env.config;
    if (c.mode == Show) {
        return c;
    }
    const float stops = std::isfinite(setting) ? std::clamp(setting, 0.0f, MaxEvLimit) : DefaultMaxEv;
    float max_ev = env.max_ev_set ? c.max_ev : stops;
    if (env.mode_set) {
        if (c.mode != Off && !env.max_ev_set && !(max_ev > 0.0f)) {
            max_ev = DefaultMaxEv;
        }
    } else {
        c.mode = max_ev > 0.0f ? On : Off;
    }
    c.max_ev = max_ev;
    c.follow = env.follow;
    return c;
}

/// Where Resolve()'s largest lift comes from, for the log.
inline const char* MaxSource(const Env& env, float setting) {
    if (env.max_ev_set) {
        return "BB_INTERIOR_EXPOSURE_MAX_EV";
    }
    if (env.config.mode == Show) {
        return "the SHOW value";
    }
    return std::isfinite(setting) && setting > 0.0f ? "graphics_interior_brightness" : "the default";
}

/// The environment, read at the first call.
inline const Env& Environment() {
    static const Env env =
        ParseEnv(std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
                 std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"),
                 std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"), std::getenv("BB_INTERIOR_EXPOSURE_FOLLOW"));
    return env;
}

/// One meter reading (interior_meter.comp's slot): the sum of log2 luminance over the ground
/// samples, their number, the sky samples (depth 1), all samples, and the ground samples whose
/// view depth is at least a quarter, half, one and two times the open distance.
struct Reading {
    float log_sum = 0, samples = 0, sky = 0, total = 0;
    float quarter = 0, halfway = 0, open = 0, twice = 0;
};

struct Lift {
    bool valid = false;   ///< false: hold the applied lift
    float metered = 0;    ///< log-average luminance of the ground samples (0 without any)
    float sky_share = 0;  ///< sky samples / all samples
    float indoor = 0;     ///< open_gate * far_gate
    float open_gate = 0;  ///< 1 - smoothstep(SkyOpen, SkyGone, the eased open share)
    float far_gate = 0;   ///< 1 - smoothstep(FarFull, FarNone, the eased far share), r99d
    float target = 0;     ///< EffectiveTarget of the config this reading was wanted with, r99e
    float wanted_ev = 0;  ///< the lift this reading asks for, stops, 0..max_ev
};

inline float Smoothstep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// The reading's numbers are usable.
inline bool Usable(const Reading& r) {
    return r.total > 0.0f && std::isfinite(r.log_sum) && std::isfinite(r.samples) &&
           std::isfinite(r.sky) && std::isfinite(r.total) && std::isfinite(r.open) &&
           r.samples >= 0.0f && r.sky >= 0.0f && r.open >= 0.0f;
}

/// The share of open samples (depth 1, or at least the open distance away) in one reading; 0 for
/// an unusable one.
inline float OpenShare(const Reading& r) {
    return Usable(r) ? std::clamp((r.sky + r.open) / r.total, 0.0f, 1.0f) : 0.0f;
}

/// The share of far samples (depth 1, or at least a quarter of the open distance away: 20 m at the
/// default) in one reading; 0 for an unusable one. Without a distance (open_m 0) the quarter count is
/// 0 and this is the sky share.
inline float FarShare(const Reading& r) {
    if (!Usable(r)) {
        return 0.0f;
    }
    const float near_count = std::isfinite(r.quarter) && r.quarter > 0.0f ? r.quarter : 0.0f;
    return std::clamp((r.sky + near_count) / r.total, 0.0f, 1.0f);
}

/// The far gate: 1 up to FarFull of the eased far share, 0 from FarNone, a smoothstep between; not a
/// number: 0 (taken as far).
inline float FarGate(float far_eased) {
    return 1.0f - Smoothstep(FarFull, FarNone, std::isfinite(far_eased) ? far_eased : 1.0f);
}

/// `open_eased`: the open share after easing (StepOpen); the reading's own share when not eased.
/// `far_eased`: the far share after easing (StepFar); the default 0 is no far gate (the pre-r99d
/// rule), the meter always passes its eased one.
inline Lift Want(const Config& c, const Reading& r, float open_eased, float far_eased = 0.0f) {
    Lift l;
    if (!Usable(r)) {
        return l;
    }
    l.sky_share = std::clamp(r.sky / r.total, 0.0f, 1.0f);
    l.open_gate = 1.0f - Smoothstep(SkyOpen, SkyGone, std::isfinite(open_eased) ? open_eased : 1.0f);
    l.far_gate = FarGate(far_eased);
    l.target = EffectiveTarget(c);
    l.indoor = l.open_gate * l.far_gate;
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open or far: no lift
        return l;
    }
    if (r.samples < 1.0f || !(l.metered >= BlackFrame)) {
        return l; // nothing to meter, or a black frame: hold
    }
    l.valid = true;
    const float gap = std::max(0.0f, std::log2(l.target / l.metered));
    l.wanted_ev = std::min(c.max_ev, c.strength * gap) * l.indoor;
    return l;
}

inline Lift Want(const Config& c, const Reading& r) {
    return Want(c, r, OpenShare(r), FarShare(r));
}

inline float Ease(float value, float toward, float dt, float rise, float fall) {
    dt = std::isfinite(dt) ? std::clamp(dt, 0.0f, MaxStep) : 0.0f;
    const float tau = toward > value ? rise : fall;
    return value + (toward - value) * (1.0f - std::exp(-dt / tau));
}

/// The applied lift after `dt` seconds (clamped to 0..MaxStep; not a number: 0) of easing toward
/// `wanted`: exponential, RiseSeconds while it grows, FallSeconds while it shrinks. Never passes
/// `wanted`.
inline float Step(float applied, float wanted, float dt) {
    return Ease(applied, wanted, dt, RiseSeconds, FallSeconds);
}

/// The eased open share after `dt` seconds toward `share`: OpenRiseSeconds while it grows (an
/// open view stops the lift almost at once), OpenFallSeconds while it shrinks (a closed view
/// brings the lift after a few seconds).
inline float StepOpen(float eased, float share, float dt) {
    return Ease(eased, share, dt, OpenRiseSeconds, OpenFallSeconds);
}

/// The eased far share after `dt` seconds toward `share`: FarRiseSeconds while it grows (a far view
/// stops the lift almost at once), FarFallSeconds while it shrinks (a closed view brings the lift
/// after a few seconds, no sooner than the open share lets it).
inline float StepFar(float eased, float share, float dt) {
    return Ease(eased, share, dt, FarRiseSeconds, FarFallSeconds);
}

/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 until the meter has applied a
/// lift, and again once it is switched off (the setting at 0, no variable): only
/// Vulkan::InteriorExposure::Meter writes it.
inline std::atomic<float> applied_scale{1.0f};
inline float Scale() {
    return applied_scale.load(std::memory_order_relaxed);
}

} // namespace BbInteriorExposure
