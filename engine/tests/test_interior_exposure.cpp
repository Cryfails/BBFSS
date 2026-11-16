// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure, r99b_interior-brightness): the interior exposure lift's knobs,
// rule and easing (gpu/shim/bbport_interior_exposure.h). Built and run by engine/build.sh --test
// and the CMake target interior-exposure-test.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "gpu/shim/bbport_interior_exposure.h"

using namespace BbInteriorExposure;

static bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}

// A reading of `ground` samples all at luminance `lum`, `sky` sky samples, and `open` of the
// ground samples at the open distance or farther.
static Reading Scene(float lum, float ground, float sky, float open = 0.0f) {
    Reading r;
    r.log_sum = std::log2(lum) * ground;
    r.samples = ground;
    r.sky = sky;
    r.total = ground + sky;
    r.quarter = r.halfway = r.open = open;
    r.twice = 0.0f;
    return r;
}

// 60 frames a second of `seconds` toward `share` (open share) at luminance `lum`; returns the
// largest applied lift on the way; `eased` and `applied` carry over.
static float Walk(const Config& c, float lum, float share, float seconds, float& eased,
                  float& applied) {
    const float all = float(GridX * GridY);
    const Reading r = Scene(lum, all, 0.0f, share * all);
    float peak = applied;
    for (int i = 0; i < int(seconds * 60.0f + 0.5f); ++i) {
        eased = StepOpen(eased, OpenShare(r), 1.0f / 60.0f);
        const Lift l = Want(c, r, eased);
        assert(l.valid);
        applied = Step(applied, l.wanted_ev, 1.0f / 60.0f);
        peak = std::max(peak, applied);
    }
    return peak;
}

int main() {
    const float all = float(GridX * GridY);
    // a. Knobs: off unless exactly "1" or "2"; defaults; SHOW's defaults; set values win; ranges.
    {
        const Config off = Parse(nullptr, nullptr, nullptr, nullptr);
        assert(off.mode == Off && off.target == DefaultTarget && off.strength == DefaultStrength &&
               off.max_ev == DefaultMaxEv && off.open_m == DefaultOpenMeters);
        for (const char* m : {"", "0", "3", "12", "on", "1 ", "-1"}) {
            assert(Parse(m, nullptr, nullptr, nullptr).mode == Off);
        }
        const Config on = Parse("1", nullptr, nullptr, nullptr, nullptr);
        assert(on.mode == On && on.target == DefaultTarget && on.strength == DefaultStrength &&
               on.max_ev == DefaultMaxEv && on.open_m == DefaultOpenMeters);
        const Config show = Parse("2", nullptr, nullptr, nullptr);
        assert(show.mode == Show && show.target == ShowTarget && show.strength == ShowStrength &&
               show.max_ev == ShowMaxEv && show.open_m == DefaultOpenMeters);
        const Config set = Parse("2", "0.02", "0.25", "1", "40");
        assert(set.target == 0.02f && set.strength == 0.25f && set.max_ev == 1.0f &&
               set.open_m == 40.0f);
        const Config high = Parse("1", "9", "-1", "7", "5000");
        assert(high.target == TargetMax && high.strength == 0.0f && high.max_ev == MaxEvLimit &&
               high.open_m == OpenMetersMax);
        const Config low = Parse("1", "0", "2", "-3", "-5");
        assert(low.target == TargetMin && low.strength == 1.0f && low.max_ev == 0.0f &&
               low.open_m == 0.0f);
        const Config junk = Parse("1", "abc", "0.5x", "nan", "80m");
        assert(junk.target == DefaultTarget && junk.strength == DefaultStrength &&
               junk.max_ev == DefaultMaxEv && junk.open_m == DefaultOpenMeters);
        assert(Parse("1", "inf", "", nullptr).target == DefaultTarget);
        assert(DefaultMaxEv <= MaxEvLimit && ShowMaxEv <= MaxEvLimit && SkyOpen < SkyGone);
        assert(DefaultOpenMeters <= OpenMetersMax && OpenRiseSeconds < OpenFallSeconds);
    }
    // b. The rule at the study's measured scenes (2026-11-15, hero light off unless said, sky
    //    masked), seen as closed views (no open samples).
    // r99b's numbers (target 0.05, strength 0.5, at most 1.5 EV) as explicit values: the scenes below
    // were derived with them; r99c's defaults are tested in section h.
    const Config on = Parse("1", "0.05", "0.5", "1.5");
    const Config show = Parse("2", nullptr, nullptr, nullptr);
    {
        const Lift level = Want(on, Scene(0.01425f, all, 0)); // library, level
        assert(level.valid && Near(level.metered, 0.01425f, 1e-5f) && level.indoor == 1.0f);
        assert(Near(level.wanted_ev, 0.5f * std::log2(0.05f / 0.01425f), 1e-4f));
        assert(level.wanted_ev > 0.88f && level.wanted_ev < 0.93f);
        const Lift up = Want(on, Scene(0.01098f, all, 0)); // library, looking up
        assert(up.valid && up.wanted_ev > 1.07f && up.wanted_ev < 1.12f);
        const Lift mod = Want(on, Scene(0.00546f, all, 0)); // library, BB PC Remaster mod on
        assert(mod.valid && mod.wanted_ev == on.max_ev);
        const Lift church_mod = Want(on, Scene(0.01234f, all, 0)); // church-candles, mod on
        assert(church_mod.valid && church_mod.wanted_ev > 0.98f && church_mod.wanted_ev < 1.04f);
        const Lift church = Want(on, Scene(0.04016f, all, 0)); // church-candles, mod off
        assert(church.valid && church.wanted_ev > 0.14f && church.wanted_ev < 0.18f);
        const Lift house_mod = Want(on, Scene(0.02982f, all, 0)); // dream house, mod on
        assert(house_mod.valid && house_mod.wanted_ev > 0.35f && house_mod.wanted_ev < 0.40f);
        const Lift house = Want(on, Scene(0.05192f, all, 0)); // dream house, mod off
        assert(house.valid && house.wanted_ev == 0.0f);
        // Rooms keep their order: lifted, the library stays darker than the church and the house.
        const float lib_after = 0.01425f * std::exp2(level.wanted_ev);
        assert(lib_after < 0.04016f * std::exp2(church.wanted_ev) && lib_after < 0.05192f);
        // The dark alley (outdoors, mod off): luminance alone would lift it; open samples stop it.
        const Lift alley_closed = Want(on, Scene(0.02509f, all, 0));
        assert(alley_closed.valid && alley_closed.wanted_ev > 0.45f && alley_closed.wanted_ev < 0.55f);
        const Lift alley_open = Want(on, Scene(0.02509f, all, 0, 0.2f * all));
        assert(alley_open.valid && alley_open.indoor == 0.0f && alley_open.wanted_ev == 0.0f);
        const Lift at = Want(on, Scene(on.target, all, 0));
        assert(at.valid && Near(at.wanted_ev, 0.0f, 1e-5f));
        const Lift bright = Want(on, Scene(0.5f, all, 0)); // never darkens
        assert(bright.valid && bright.wanted_ev == 0.0f);
        const Lift house_show = Want(show, Scene(0.05192f, all, 0)); // SHOW lifts the house
        assert(Near(house_show.wanted_ev, std::log2(0.15f / 0.05192f), 1e-4f));
        assert(Want(show, Scene(0.01425f, all, 0)).wanted_ev == ShowMaxEv);
        assert(Want(Parse("1", nullptr, "0", nullptr), Scene(0.001f, all, 0)).wanted_ev == 0.0f);
        // r99's numbers with r99's values.
        const Config r99 = Parse("1", "0.02", "1", nullptr, "0");
        assert(Near(Want(r99, Scene(0.01425f, all, 0)).wanted_ev, std::log2(0.02f / 0.01425f), 1e-4f));
    }
    // c. The open gate: up to SkyOpen full, from SkyGone none, half way between half; sky and far
    //    samples count alike; the eased share decides, not the reading's own.
    {
        const Lift full = Want(on, Scene(0.01425f, 97, 3));
        assert(full.valid && Near(full.indoor, 1.0f, 1e-5f) && full.wanted_ev > 0.85f);
        const Lift full_far = Want(on, Scene(0.01425f, 100, 0, 3));
        assert(Near(full_far.indoor, 1.0f, 1e-5f) && Near(full_far.wanted_ev, full.wanted_ev, 1e-4f));
        const Lift half = Want(on, Scene(0.01425f, 91, 9));
        assert(half.valid && Near(half.indoor, 0.5f, 1e-3f));
        assert(Near(half.wanted_ev, 0.25f * std::log2(0.05f / 0.01425f), 2e-3f));
        const Lift half_far = Want(on, Scene(0.01425f, 100, 4, 5)); // 9 of 104 open
        assert(half_far.indoor > 0.4f && half_far.indoor < 0.6f);
        const Lift street = Want(on, Scene(0.01f, 80, 20));
        assert(street.valid && street.indoor == 0.0f && street.wanted_ev == 0.0f);
        const Lift sky_only = Want(on, Scene(1.0f, 0, all));
        assert(sky_only.valid && sky_only.metered == 0.0f && sky_only.wanted_ev == 0.0f);
        assert(Near(OpenShare(Scene(0.01f, 90, 10, 20)), 0.3f, 1e-6f));
        // A closed view right after an open one: no lift yet.
        assert(Want(on, Scene(0.01425f, all, 0), 0.2f).wanted_ev == 0.0f);
        // An open reading while the eased share is still closed: lifted (the easing decides).
        assert(Want(on, Scene(0.01425f, 80, 20), 0.0f).wanted_ev > 0.85f);
        // Not a number: taken as open.
        assert(Want(on, Scene(0.01425f, all, 0), std::nanf("")).wanted_ev == 0.0f);
    }
    // d. Readings that hold the lift: a black frame, nothing read, numbers that are not numbers.
    {
        assert(!Want(on, Scene(LumMin, all, 0)).valid);
        assert(!Want(on, Scene(BlackFrame * 0.5f, all, 0)).valid);
        assert(Want(on, Scene(BlackFrame * 2.0f, all, 0)).valid);
        assert(!Want(on, Reading{}).valid);
        assert(OpenShare(Reading{}) == 0.0f);
        Reading nan = Scene(0.01f, all, 0);
        nan.log_sum = std::nanf("");
        assert(!Want(on, nan).valid);
        Reading negative = Scene(0.01f, all, 0);
        negative.sky = -1.0f;
        assert(!Want(on, negative).valid && OpenShare(negative) == 0.0f);
        Reading open_nan = Scene(0.01f, all, 0);
        open_nan.open = std::nanf("");
        assert(!Usable(open_nan) && !Want(on, open_nan).valid);
    }
    // e. Easing: RiseSeconds up, FallSeconds down, steps clamped, never past the wanted lift; the
    //    open share up over OpenRiseSeconds, down over OpenFallSeconds.
    {
        assert(Near(Step(0.0f, 1.0f, 0.2f), 1.0f - std::exp(-0.2f / RiseSeconds), 1e-6f));
        assert(Near(Step(1.0f, 0.0f, 0.2f), std::exp(-0.2f / FallSeconds), 1e-6f));
        assert(Step(0.0f, 1.0f, 5.0f) == Step(0.0f, 1.0f, MaxStep));
        assert(Step(0.5f, 1.0f, -1.0f) == 0.5f && Step(0.5f, 1.0f, std::nanf("")) == 0.5f);
        assert(Near(StepOpen(0.0f, 1.0f, 0.1f), 1.0f - std::exp(-0.1f / OpenRiseSeconds), 1e-6f));
        assert(Near(StepOpen(1.0f, 0.0f, 0.2f), std::exp(-0.2f / OpenFallSeconds), 1e-6f));
        float a = 0.0f;
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 1.2f, 1.0f / 60.0f);
            assert(b >= a && b <= 1.2f);
            a = b;
        }
        assert(Near(a, 1.2f, 1e-3f));
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 0.0f, 1.0f / 60.0f);
            assert(b <= a && b >= 0.0f);
            a = b;
        }
        assert(Near(a, 0.0f, 1e-3f));
    }
    // f. Walking (60 frames a second): into the library with the mod from a street showing 40 %
    //    open samples, the lift reaches 90 % of +1.5 EV after 4-5.5 s; back out it is under
    //    +0.15 EV within 1.2 s; a 1 s look at the ground of a dark street lifts nothing.
    {
        float eased = 0.4f, applied = 0.0f;
        Walk(on, 0.00546f, 0.4f, 2.0f, eased, applied);
        assert(applied == 0.0f);
        Walk(on, 0.00546f, 0.0f, 4.0f, eased, applied);
        assert(applied < 0.9f * on.max_ev);
        Walk(on, 0.00546f, 0.0f, 1.5f, eased, applied);
        assert(applied > 0.9f * on.max_ev);
        Walk(on, 0.03f, 0.4f, 1.2f, eased, applied);
        assert(applied < 0.15f);
        float e2 = 0.4f, a2 = 0.0f;
        assert(Walk(on, 0.0097f, 0.0f, 1.0f, e2, a2) < 0.05f);
        // The start: taken as open until readings say otherwise.
        assert(OpenStart >= SkyGone);
    }
    // g. The factor is exactly 1 until the meter writes it, so x * Scale() is x bit for bit.
    {
        assert(Scale() == 1.0f);
        for (const float x : {1.0f, 0.25f, 4.0f, 1.41f, 0.3333333f}) {
            const float y = x * Scale();
            assert(std::memcmp(&x, &y, sizeof x) == 0);
        }
        assert(std::exp2(0.0f) == 1.0f);
    }
    // h. r99c: the defaults (on, target 0.02, strength 1, at most 0.75 EV), the setting
    //    graphics_interior_brightness (0..3 stops, 0 = off) and the environment, resolved per frame.
    {
        static_assert(DefaultTarget == 0.02f && DefaultStrength == 1.0f && DefaultMaxEv == 0.75f);
        const Env none = ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr);
        assert(!none.mode_set && !none.max_ev_set && none.config.mode == Off);
        // No variable: the setting decides, 0.75 is on at 0.75, 0 is off, 2 is on at 2.
        const Config d = Resolve(none, DefaultMaxEv);
        assert(d.mode == On && d.max_ev == DefaultMaxEv && d.target == DefaultTarget &&
               d.strength == DefaultStrength && d.open_m == DefaultOpenMeters);
        assert(Resolve(none, 0.0f).mode == Off && Resolve(none, -1.0f).mode == Off);
        assert(Resolve(none, 2.0f).mode == On && Resolve(none, 2.0f).max_ev == 2.0f);
        assert(Resolve(none, 9.0f).max_ev == MaxEvLimit && Resolve(none, 0.25f).max_ev == 0.25f);
        assert(Resolve(none, std::nanf("")).mode == On && Resolve(none, std::nanf("")).max_ev == DefaultMaxEv);
        assert(Resolve(none, INFINITY).max_ev == DefaultMaxEv);
        // The variables win. An empty one is as unset.
        const Env empty = ParseEnv("", "", "", "", "");
        assert(!empty.mode_set && !empty.max_ev_set && Resolve(empty, 0.75f).mode == On &&
               Resolve(empty, 0.0f).mode == Off);
        const Env off = ParseEnv("0", nullptr, nullptr, nullptr, nullptr);
        assert(off.mode_set && Resolve(off, 0.75f).mode == Off);
        const Env junk = ParseEnv("x", nullptr, nullptr, nullptr, nullptr);
        assert(junk.mode_set && Resolve(junk, 0.75f).mode == Off);
        const Env force = ParseEnv("1", nullptr, nullptr, nullptr, nullptr);
        assert(Resolve(force, 0.0f).mode == On && Resolve(force, 0.0f).max_ev == DefaultMaxEv);
        assert(Resolve(force, 2.0f).mode == On && Resolve(force, 2.0f).max_ev == 2.0f);
        const Env sho = ParseEnv("2", nullptr, nullptr, nullptr, nullptr);
        const Config c_show = Resolve(sho, 0.75f);
        assert(c_show.mode == Show && c_show.max_ev == ShowMaxEv && c_show.target == ShowTarget &&
               Resolve(sho, 0.0f).mode == Show);
        const Env cap = ParseEnv(nullptr, nullptr, nullptr, "1.5", nullptr);
        assert(cap.max_ev_set && !cap.mode_set);
        assert(Resolve(cap, 0.75f).mode == On && Resolve(cap, 0.75f).max_ev == 1.5f);
        assert(Resolve(cap, 0.0f).mode == On && Resolve(cap, 0.0f).max_ev == 1.5f);
        const Env cap0 = ParseEnv(nullptr, nullptr, nullptr, "0", nullptr);
        assert(cap0.max_ev_set && Resolve(cap0, 0.75f).mode == Off);
        const Env cap_on = ParseEnv("1", nullptr, nullptr, "0", nullptr);
        assert(Resolve(cap_on, 0.75f).mode == On && Resolve(cap_on, 0.75f).max_ev == 0.0f);
        const Env cap_show = ParseEnv("2", nullptr, nullptr, "1", nullptr);
        assert(Resolve(cap_show, 0.0f).mode == Show && Resolve(cap_show, 0.0f).max_ev == 1.0f);
        const Env cap_high = ParseEnv(nullptr, nullptr, nullptr, "7", nullptr);
        assert(Resolve(cap_high, 0.5f).max_ev == MaxEvLimit);
        const Env cap_bad = ParseEnv(nullptr, nullptr, nullptr, "1.5x", nullptr); // unreadable: unset
        assert(!cap_bad.max_ev_set && Resolve(cap_bad, 0.5f).max_ev == 0.5f);
        const Env cap_nan = ParseEnv(nullptr, nullptr, nullptr, "nan", nullptr);
        assert(!cap_nan.max_ev_set && Resolve(cap_nan, 0.0f).mode == Off);
        const Env other = ParseEnv(nullptr, "0.05", "0.5", nullptr, "40");
        assert(Resolve(other, 0.75f).target == 0.05f && Resolve(other, 0.75f).strength == 0.5f &&
               Resolve(other, 0.75f).open_m == 40.0f && Resolve(other, 0.75f).max_ev == 0.75f);
        assert(Readable("1") && Readable("-0.5") && !Readable("") && !Readable(nullptr) &&
               !Readable("1x") && !Readable("nan") && !Readable("inf"));
        // Where the largest lift comes from.
        assert(std::strcmp(MaxSource(none, 0.75f), "graphics_interior_brightness") == 0);
        assert(std::strcmp(MaxSource(none, 0.0f), "the default") == 0);
        assert(std::strcmp(MaxSource(cap, 0.75f), "BB_INTERIOR_EXPOSURE_MAX_EV") == 0);
        assert(std::strcmp(MaxSource(sho, 0.75f), "the SHOW value") == 0);
        // The measured scenes at the defaults: the library without the mod +0.5, with it the full
        // 0.75, church-candles with the mod just under it, the dream house and church-candles
        // without the mod nothing worth seeing, open places nothing.
        const float lib = Want(d, Scene(0.014f, all, 0)).wanted_ev;
        assert(lib == DefaultMaxEv); // r99e: the target follows the slider (0.034 at 0.75), the gap 1.26 passes the cap
        assert(Want(d, Scene(0.01425f, all, 0)).wanted_ev == DefaultMaxEv);
        assert(Want(d, Scene(0.01098f, all, 0)).wanted_ev == DefaultMaxEv); // library, looking up
        assert(Want(d, Scene(0.0055f, all, 0)).wanted_ev == DefaultMaxEv);
        assert(Want(d, Scene(0.0011f, all, 0)).wanted_ev == DefaultMaxEv);
        const float church_mod = Want(d, Scene(0.01234f, all, 0)).wanted_ev;
        assert(church_mod == DefaultMaxEv);
        assert(Want(d, Scene(0.0053f, all, 0)).wanted_ev == DefaultMaxEv);
        assert(Want(d, Scene(0.04016f, all, 0)).wanted_ev == 0.0f);
        assert(Want(d, Scene(0.018f, all, 0)).wanted_ev == DefaultMaxEv); // the dream house, r99e
        // the gap here is 0.75 only up to float rounding (target 0.02 x 2^0.75, metered ~0.02): not ==
        assert(Near(Want(d, Scene(0.02f, all, 0)).wanted_ev, DefaultMaxEv, 1e-4f));
        assert(Near(Want(d, Scene(0.025f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.025f), 1e-4f));
        assert(Near(Want(d, Scene(0.02982f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.02982f), 1e-4f));
        assert(Want(d, Scene(0.05192f, all, 0)).wanted_ev == 0.0f);
        assert(Near(Want(d, Scene(0.02509f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.02509f), 1e-4f));
        // (the dark alley without the mod: held back outdoors by the far gate, section i)
        assert(Want(d, Scene(0.0097f, all, 0)).wanted_ev == DefaultMaxEv); // with the mod: a closed view lifts
        assert(Want(d, Scene(0.0097f, all, 0, 0.2f * all)).wanted_ev == 0.0f); // 20 % open: nothing
        assert(Want(d, Scene(0.01f, 0, all)).wanted_ev == 0.0f); // the graveyard at night: all sky
        // The setting scales the lift's cap only: at 0.25 the library asks 0.25, at 3 its full gap.
        assert(Want(Resolve(none, 0.25f), Scene(0.0011f, all, 0)).wanted_ev == 0.25f);
        assert(Want(Resolve(none, 3.0f), Scene(0.0055f, all, 0)).wanted_ev == 3.0f); // target 0.16: gap 4.9, cap 3
    }
    // i. r99d: the far gate. The five measured views of build 31 (hero light off, the mod as noted;
    //    shares of 2304 samples as the log lines gave them, at least 20/40/80/160 m), at the defaults.
    {
        static_assert(FarFull == 0.18f && FarNone == 0.40f && FarFallSeconds == 2.0f);
        const Env none = ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr);
        const Config d = Resolve(none, DefaultMaxEv);
        // A reading from a log line: metered luminance, shares in percent of all samples.
        const auto measured = [&](float lum, float depth1, float q20, float q40, float q80, float q160) {
            Reading r;
            r.sky = std::round(all * depth1 / 100.0f);
            r.samples = all - r.sky;
            r.total = all;
            r.log_sum = std::log2(lum) * r.samples;
            r.quarter = std::round(all * q20 / 100.0f);
            r.halfway = std::round(all * q40 / 100.0f);
            r.open = std::round(all * q80 / 100.0f);
            r.twice = std::round(all * q160 / 100.0f);
            return r;
        };
        // 1. library WITH the mod: metered 0.00110, nothing far: the full lift.
        const Reading lib = measured(0.00110f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f);
        const Lift lib_l = Want(d, lib);
        assert(lib_l.valid && lib_l.far_gate == 1.0f && lib_l.open_gate == 1.0f && lib_l.wanted_ev == DefaultMaxEv);
        // 2. church hall WITH the mod: metered 0.00482, 11.3% at 20 m: still the full lift.
        const Reading church = measured(0.00482f, 0.0f, 11.3f, 0.0f, 0.0f, 0.0f);
        const Lift church_l = Want(d, church);
        assert(Near(FarShare(church), 0.113f, 1e-3f) && church_l.far_gate == 1.0f &&
               church_l.wanted_ev == DefaultMaxEv);
        assert(Want(d, measured(0.00482f, 0.0f, 15.0f, 0.0f, 0.0f, 0.0f)).wanted_ev == DefaultMaxEv); // margin
        // 3. library WITHOUT the mod: metered 0.01024, nothing far: capped at +0.75.
        const Lift nomod_l = Want(d, measured(0.01024f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f));
        assert(nomod_l.valid && nomod_l.wanted_ev == DefaultMaxEv && nomod_l.far_gate == 1.0f);
        // 4. dream house: metered 0.01732, 0% far (3.3% while it settled): the same +0.21 as before.
        const Lift house_l = Want(d, measured(0.01732f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f));
        assert(house_l.wanted_ev == DefaultMaxEv && house_l.far_gate == 1.0f); // r99e: 0.034 target, was +0.21
        assert(Want(d, measured(0.01732f, 0.0f, 3.3f, 1.5f, 1.5f, 1.5f)).far_gate == 1.0f);
        // 5. graveyard at night, OUTDOORS: metered 0.00951, 1.0% open, 64.0% at 20 m. The open gate
        //    alone (r99c) lifted it by the full 0.75; the far gate gives none.
        const Reading yard = measured(0.00951f, 0.0f, 64.0f, 15.4f, 1.0f, 0.0f);
        assert(Near(FarShare(yard), 0.640f, 1e-3f) && Near(OpenShare(yard), 0.010f, 1e-3f));
        assert(Want(d, yard, OpenShare(yard)).wanted_ev == DefaultMaxEv); // before r99d: the fault
        const Lift yard_l = Want(d, yard);
        assert(yard_l.valid && yard_l.open_gate == 1.0f && yard_l.far_gate == 0.0f &&
               yard_l.indoor == 0.0f && yard_l.wanted_ev == 0.0f);
        // The gate's shape: full to FarFull, none from FarNone, half in the middle, monotone, not a
        // number is far.
        assert(FarGate(0.0f) == 1.0f && FarGate(0.113f) == 1.0f && FarGate(FarFull) == 1.0f);
        assert(FarGate(FarNone) == 0.0f && FarGate(0.64f) == 0.0f && FarGate(1.0f) == 0.0f);
        assert(Near(FarGate(0.5f * (FarFull + FarNone)), 0.5f, 1e-6f));
        assert(FarGate(std::nanf("")) == 0.0f && FarGate(INFINITY) == 0.0f);
        for (float x = 0.0f; x < 1.0f; x += 0.01f) {
            assert(FarGate(x + 0.01f) <= FarGate(x) + 1e-6f);
        }
        // A view 30% far gets 0.43 of its lift: the soft part, an outdoor place that is half open.
        assert(Near(FarGate(0.30f), 0.43f, 0.02f));
        // FarShare counts sky and the 20 m samples; unusable readings are 0; without a distance only sky.
        assert(Near(FarShare(Scene(0.01f, 90, 10, 20)), 0.3f, 1e-6f));
        assert(FarShare(Reading{}) == 0.0f);
        assert(Near(FarShare(Scene(0.01f, 0, all)), 1.0f, 1e-6f));
        Reading no_distance = Scene(0.01f, 90, 10);
        no_distance.quarter = 0.0f;
        assert(Near(FarShare(no_distance), 0.1f, 1e-6f));
        Reading quarter_nan = Scene(0.01f, 90, 10);
        quarter_nan.quarter = std::nanf("");
        assert(Near(FarShare(quarter_nan), 0.1f, 1e-6f));
        // The 4-argument Want without a far share is the old rule (what the tests above b-h pin).
        assert(Want(d, yard, OpenShare(yard), 0.0f).wanted_ev == DefaultMaxEv);
        assert(Want(d, yard, OpenShare(yard), std::nanf("")).wanted_ev == 0.0f);
        // StepFar: FarRiseSeconds up, FarFallSeconds down, 2 s is slower than the open share's fall.
        assert(Near(StepFar(0.0f, 1.0f, 0.1f), 1.0f - std::exp(-0.1f / FarRiseSeconds), 1e-6f));
        assert(Near(StepFar(1.0f, 0.0f, 0.2f), std::exp(-0.2f / FarFallSeconds), 1e-6f));
        // Walks at 60 frames a second, from the start (both shares at OpenStart = 1).
        const auto walk = [&](const Reading& r, float seconds, float& open_e, float& far_e, float& applied) {
            float peak = applied;
            for (int i = 0; i < int(seconds * 60.0f + 0.5f); ++i) {
                open_e = StepOpen(open_e, OpenShare(r), 1.0f / 60.0f);
                far_e = StepFar(far_e, FarShare(r), 1.0f / 60.0f);
                const Lift l = Want(d, r, open_e, far_e);
                assert(l.valid);
                applied = Step(applied, l.wanted_ev, 1.0f / 60.0f);
                peak = std::max(peak, applied);
            }
            return peak;
        };
        {   // the graveyard for 20 s from the start: never a lift
            float oe = OpenStart, fe = OpenStart, ap = 0.0f;
            assert(walk(yard, 20.0f, oe, fe, ap) == 0.0f && ap == 0.0f);
            // then looking up at a vault with nothing 20 m away for 1.2 s: nothing visible
            const Reading vault = measured(0.0097f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f);
            const float peak = walk(vault, 1.2f, oe, fe, ap);
            assert(peak < 0.15f);
            // and held for a further 3 s it is taken as the ceiling it is
            walk(vault, 3.0f, oe, fe, ap);
            assert(ap > 0.4f);
        }
        {   // the church hall from the start: the lift arrives with the open gate, not later
            float oe = OpenStart, fe = OpenStart, ap = 0.0f;
            walk(church, 10.0f, oe, fe, ap);
            assert(ap > 0.9f * DefaultMaxEv);
            float oe2 = OpenStart, fe2 = OpenStart, ap2 = 0.0f;
            walk(lib, 10.0f, oe2, fe2, ap2);
            assert(ap > ap2 - 0.02f); // the far gate adds no delay at this share
        }
        {   // out of the church into the yard (far share up): the lift is gone within about a second
            float oe = OpenStart, fe = OpenStart, ap = 0.0f;
            walk(church, 10.0f, oe, fe, ap);
            walk(yard, 1.5f, oe, fe, ap);
            assert(ap < 0.2f);
        }
    }
    // j. r99e: the target follows the largest lift, so the slider works in a room above the plain target.
    {
        const Env none = ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr);
        assert(none.follow && ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr, "").follow &&
               ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr, "1").follow &&
               !ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr, "0").follow);
        const Env fixed = ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr, "0");
        const Config d = Resolve(none, DefaultMaxEv);
        assert(d.follow && Near(EffectiveTarget(d), 0.02f * std::exp2(0.75f), 1e-6f));
        assert(!Resolve(fixed, 0.75f).follow && EffectiveTarget(Resolve(fixed, 0.75f)) == DefaultTarget);
        assert(!Resolve(ParseEnv("2", nullptr, nullptr, nullptr, nullptr), 0.75f).follow);
        assert(!Parse("1", nullptr, nullptr, nullptr).follow);
        // The owner's build-72 library: metered 0.02246, above the plain target 0.02. The fixed target gave
        // nothing at any slider position; the followed one gives a lift that rises with the slider.
        const Reading lib = Scene(0.02246f, all, 0);
        for (int k = 1; k <= 12; ++k) {
            assert(Want(Resolve(fixed, 0.25f * float(k)), lib).wanted_ev == 0.0f);
        }
        float prev = 0.0f;
        for (int k = 1; k <= 12; ++k) {
            const float ev = Want(Resolve(none, 0.25f * float(k)), lib).wanted_ev;
            assert(ev >= prev - 1e-6f && ev <= 0.25f * float(k) + 1e-6f);
            prev = ev;
        }
        const float at075 = Want(Resolve(none, 0.75f), lib).wanted_ev;
        assert(Near(at075, std::log2(EffectiveTarget(d) / 0.02246f), 1e-4f) && at075 > 0.55f && at075 < 0.62f);
        assert(Want(Resolve(none, 1.0f), lib).wanted_ev > 0.80f);
        assert(Want(Resolve(none, 2.0f), lib).wanted_ev > 1.75f);
        assert(Want(Resolve(none, 3.0f), lib).wanted_ev > 2.75f);
        // A dark room keeps the whole slider value; a bright one gets nothing at every value.
        for (int k = 1; k <= 12; ++k) {
            assert(Want(Resolve(none, 0.25f * float(k)), Scene(0.0011f, all, 0)).wanted_ev == 0.25f * float(k));
            assert(Want(Resolve(none, 0.25f * float(k)), Scene(0.30f, all, 0)).wanted_ev == 0.0f);
        }
        // The ceiling and the floor of the followed target.
        assert(EffectiveTarget(Resolve(ParseEnv(nullptr, "0.1", nullptr, nullptr, nullptr), 3.0f)) ==
               TargetFollowCeiling);
        assert(Near(EffectiveTarget(Resolve(ParseEnv(nullptr, "0.4", nullptr, nullptr, nullptr), 1.0f)), 0.4f, 1e-6f));
        // Outdoors: the gates multiply as before, at any slider value.
        assert(Want(Resolve(none, 3.0f), Scene(0.0097f, all, 0, 0.2f * all)).wanted_ev == 0.0f);
        assert(Want(Resolve(none, 3.0f), Scene(0.01f, 0, all)).wanted_ev == 0.0f);
        assert(Want(Resolve(none, 3.0f), Scene(0.02246f, all, 0), 0.0f, 0.64f).wanted_ev == 0.0f); // far gate shut
        // Off stays off: a setting of 0 is not a lift at any target.
        assert(Resolve(none, 0.0f).mode == Off);
        // Lift::target is the effective one.
        assert(Near(Want(d, lib).target, EffectiveTarget(d), 1e-9f));
    }
    std::puts("interior-exposure-test: all checks passed");
    return 0;
}
