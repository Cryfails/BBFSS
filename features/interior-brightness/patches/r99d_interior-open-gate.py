# r99d_interior-open-gate: FEATURE fix (lamp work, "dim interiors"), on top of r99_interior-exposure,
# r99b_interior-brightness and r99c_interior-default (all applied; apply them first, revert this one
# before them). The interior brightness lift is ON by default (r99c), so it must stay out of outdoor
# places. Build 31 (2026-11-16 00:30) showed it does not: the graveyard at night (OUTDOORS, the
# do-nothing place) got the full +0.750 EV ("metered 0.00951; open 1.0%, eased 1.0%, indoor 1.00 (depth 1
# 0.0%; at least 20/40/80/160 m: 64.0/15.4/1.0/0.0%)"). The graveyard sits in a deep courtyard ringed
# by tall cathedral walls: the sky (depth 1) covers almost no samples and almost nothing is 80 m away,
# so r99's open rule (depth 1 or >= 80 m) never fired. The 20 m share is the telling number: library
# 0.0%, church hall 11.3%, dream house 0.0-3.3%, graveyard 64.0%.
#
# What it does: a second gate, the FAR gate, beside the open gate. "Far" = a sample at depth 1 (sky) or
# at least a quarter of the open distance away (20 m at the default 80 m: the meter already counts
# this, Reading::quarter, nothing changes on the GPU). The far share of a reading, FarShare(r) =
# (sky + quarter) / total, is eased in real time like the open share (StepFar: 0.15 s while it grows,
# 2 s while it shrinks, starting at 1 = no lift until readings say closed) and the lift is multiplied by
# FarGate = 1 - smoothstep(FarFull 0.18, FarNone 0.40, eased far share). Lift.indoor is now the product
# open gate x far gate (both logged). Nothing else changes: target 0.02, strength 1, the cap from the
# setting, the lift easing, the slider, the environment knobs, the open gate with its 0.03 / 0.15.
#
# Why 0.18 / 0.40 (measured 20 m shares of build 31, level views): library 0.0 and library without the
# mod 0.0, dream house 0.0 (3.3 in the first, still settling line), church hall 11.3, graveyard 64.0.
# The church's long hall must keep the full lift, so full lift reaches up to 0.18 (6.7 points of margin
# over the hall, other hall views may reach further); the graveyard must get nothing, none from 0.40
# (24 points of margin under it; at 0.64 the gate is 0, an outdoor view at 30% still gets 43% of the
# lift). Half way (0.29) = 0.5. These are two measured-by-one-place numbers: the log line now says the
# far share, so other places can correct them.
#
# Looking up (the graveyard "up" view, dark vault or sky behind roofs): sky samples (depth 1) count as
# far AND as open, so a view that is mostly sky gets no lift from either gate. A vault or ceiling
# closer than 20 m that fills the view with no sky counts as an interior and is lifted, as the
# library's ceiling is: the lift needs the eased far share to fall under 0.40 first, so from a steady
# outdoor view (far 64%) a look at such a ceiling lifts nothing visible within 1.2 s (peak 0.009 EV in
# the Python mirror) and reaches 0.55 EV after 3 s of looking; the log line's far numbers show which
# way the real up view goes (b31's up view line was not captured).
#
# Files: engine/gpu/shim/bbport_interior_exposure.h (constants, FarShare, FarGate, StepFar, Lift.open_gate
# and far_gate, Want takes the eased far share), renderer_vulkan/vk_interior_exposure.cpp (the eased far
# share in State, Rest and the reading step; the once-line and the periodic line carry the new numbers),
# engine/tests/test_interior_exposure.cpp (section i, the five measured cases and the eased walks),
# README.md (three sentences of the Interior exposure section). No shader, CMake, build.sh or settings
# change; the meter's output is the same (Reading::quarter was already read back).
#
# Cost: nothing on the GPU; on the CPU one more smoothstep and one exp per read reading (a few ns).
# Memory: none. Setting 0 and no variable: unchanged (Meter returns before anything here runs).
#
# Use: python -I -X utf8 r99d_interior-open-gate.py check | apply | revert
# Root: R99D_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in
# r99d_backup next to this script. Each edit replaces an old text found exactly once with a new one;
# revert puts each old text back where its new text is found exactly once. Needs r99c applied.
import os, re, sys

ROOT = os.environ.get("R99D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r99d_backup")
HDR = "engine/gpu/shim/bbport_interior_exposure.h"
VK_C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_interior_exposure.cpp"
T_IE = "engine/tests/test_interior_exposure.cpp"
README = "README.md"

# ------------------------------------------------------------------ header
H_DOC_ANCHOR = '''// settings; tested by tests/test_interior_exposure.cpp.
'''
H_DOC_BLOCK = '''//
// The far gate (r99d_interior-open-gate): a deep outdoor courtyard (the graveyard at night, ringed by
// tall walls) shows almost no sky and nothing 80 m away, so the open gate alone lifted it by the full
// 0.75 stops. The reading also counts the samples at least a quarter of the open distance away (20 m
// at 80 m). FarShare = (sky + that count) / all samples, eased like the open share (StepFar: FarRise
// 0.15 s, FarFall 2 s, from OpenStart), and the lift is multiplied by FarGate = 1 - smoothstep(FarFull
// 0.18, FarNone 0.40, eased far share): the church's long hall (11.3% at 20 m, measured) keeps the
// full lift, the graveyard (64.0%) gets none, the library and the dream house (0 to 3%) are unchanged.
// Lift::indoor = open gate x far gate.
'''

H_CONST_ANCHOR = '''inline constexpr float SkyGone = 0.15f;    ///< eased open share from which there is no lift
'''
H_CONST_BLOCK = '''inline constexpr float FarFull = 0.18f;    ///< eased far share (depth 1 or 20 m+) up to which the lift is full
inline constexpr float FarNone = 0.40f;    ///< eased far share from which there is no lift
inline constexpr float FarRiseSeconds = 0.15f; ///< time constant while the far share grows
inline constexpr float FarFallSeconds = 2.0f;  ///< time constant while it shrinks
static_assert(FarFull > SkyOpen && FarFull < FarNone && FarNone <= 1.0f && FarRiseSeconds > 0.0f &&
              FarFallSeconds > 0.0f);
'''

H_LIFT_OLD = '''    float indoor = 0;     ///< 1 - smoothstep(SkyOpen, SkyGone, the eased open share)
'''
H_LIFT_NEW = '''    float indoor = 0;     ///< open_gate * far_gate
    float open_gate = 0;  ///< 1 - smoothstep(SkyOpen, SkyGone, the eased open share)
    float far_gate = 0;   ///< 1 - smoothstep(FarFull, FarNone, the eased far share), r99d
'''

H_WANT_OLD = '''/// `open_eased`: the open share after easing (StepOpen); the reading's own share when not eased.
inline Lift Want(const Config& c, const Reading& r, float open_eased) {
    Lift l;
    if (!Usable(r)) {
        return l;
    }
    l.sky_share = std::clamp(r.sky / r.total, 0.0f, 1.0f);
    l.indoor = 1.0f - Smoothstep(SkyOpen, SkyGone, std::isfinite(open_eased) ? open_eased : 1.0f);
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open: no lift
        return l;
    }
'''
H_WANT_NEW = '''/// The share of far samples (depth 1, or at least a quarter of the open distance away: 20 m at the
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
    l.indoor = l.open_gate * l.far_gate;
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open or far: no lift
        return l;
    }
'''

H_WANT2_OLD = '''inline Lift Want(const Config& c, const Reading& r) {
    return Want(c, r, OpenShare(r));
}
'''
H_WANT2_NEW = '''inline Lift Want(const Config& c, const Reading& r) {
    return Want(c, r, OpenShare(r), FarShare(r));
}
'''

H_STEP_ANCHOR = '''    return Ease(eased, share, dt, OpenRiseSeconds, OpenFallSeconds);
}
'''
H_STEP_BLOCK = '''
/// The eased far share after `dt` seconds toward `share`: FarRiseSeconds while it grows (a far view
/// stops the lift almost at once), FarFallSeconds while it shrinks (a closed view brings the lift
/// after a few seconds, no sooner than the open share lets it).
inline float StepFar(float eased, float share, float dt) {
    return Ease(eased, share, dt, FarRiseSeconds, FarFallSeconds);
}
'''

# ------------------------------------------------------------------ vk_interior_exposure.cpp
C_STATE_ANCHOR = '''    float open_eased = Policy::OpenStart;
'''
C_STATE_BLOCK = '''    float far_eased = Policy::OpenStart; ///< r99d: the far share after easing
'''
C_REST_ANCHOR = '''    s.open_eased = Policy::OpenStart;
'''
C_REST_BLOCK = '''    s.far_eased = Policy::OpenStart;
'''
C_STEP_OLD = '''        if (Policy::Usable(reading) && full) {
            s.open_eased = Policy::StepOpen(s.open_eased, Policy::OpenShare(reading), dt);
        }
        const Policy::Lift lift = Policy::Want(knobs, reading, s.open_eased);
'''
C_STEP_NEW = '''        if (Policy::Usable(reading) && full) {
            s.open_eased = Policy::StepOpen(s.open_eased, Policy::OpenShare(reading), dt);
            s.far_eased = Policy::StepFar(s.far_eased, Policy::FarShare(reading), dt);
        }
        const Policy::Lift lift = Policy::Want(knobs, reading, s.open_eased, s.far_eased);
'''
C_SAY_OLD = '''                "open or more (fading from %.0f%%), the open share eased up over %.2f s and down "
                "over %.1f s; the lift rises over %.1f s, falls over %.1f s; acts through the "
'''
C_SAY_NEW = '''                "open or more (fading from %.0f%%) or with %.0f%% far (depth 1 or %.0f m or farther) "
                "or more (fading from %.0f%%), the open share eased up over %.2f s and down "
                "over %.1f s, the far share over %.2f s and %.1f s; the lift rises over %.1f s, "
                "falls over %.1f s; acts through the "
'''
C_SAYARGS_OLD = '''                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::OpenRiseSeconds,
                Policy::OpenFallSeconds, Policy::RiseSeconds, Policy::FallSeconds, ToneName(tone));
'''
C_SAYARGS_NEW = '''                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::FarNone * 100.0f,
                0.25f * knobs.open_m, Policy::FarFull * 100.0f, Policy::OpenRiseSeconds,
                Policy::OpenFallSeconds, Policy::FarRiseSeconds, Policy::FarFallSeconds,
                Policy::RiseSeconds, Policy::FallSeconds, ToneName(tone));
'''
C_LINE_OLD = '''        std::printf("Interior exposure (r99b): applied %+.3f EV (x%.4f), wanted %+.2f EV, metered "
                    "%.5f; open %.1f%%, eased %.1f%%, indoor %.2f (depth 1 %.1f%%; at least "
                    "%.0f/%.0f/%.0f/%.0f m: %.1f/%.1f/%.1f/%.1f%%); GT7/ACES exposure %.2f -> %.3f "
                    "(%s); %u meters, %u read, %u held, %u busy, %u no camera\\n",
                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered,
                    Policy::OpenShare(r) * 100.0f, s.open_eased * 100.0f, s.last.indoor,
                    Percent(r.sky), 0.25f * m, 0.5f * m, m, 2.0f * m, Percent(r.quarter),
'''
C_LINE_NEW = '''        std::printf("Interior exposure (r99b): applied %+.3f EV (x%.4f), wanted %+.2f EV, metered "
                    "%.5f; open %.1f%%, eased %.1f%%, far (depth 1 or %.0f m+) %.1f%%, eased "
                    "%.1f%%, indoor %.2f = open gate %.2f x far gate %.2f (depth 1 %.1f%%; at least "
                    "%.0f/%.0f/%.0f/%.0f m: %.1f/%.1f/%.1f/%.1f%%); GT7/ACES exposure %.2f -> %.3f "
                    "(%s); %u meters, %u read, %u held, %u busy, %u no camera\\n",
                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered,
                    Policy::OpenShare(r) * 100.0f, s.open_eased * 100.0f, 0.25f * m,
                    Policy::FarShare(r) * 100.0f, s.far_eased * 100.0f, s.last.indoor,
                    s.last.open_gate, s.last.far_gate,
                    Percent(r.sky), 0.25f * m, 0.5f * m, m, 2.0f * m, Percent(r.quarter),
'''

# ------------------------------------------------------------------ the unit test
T_ANCHOR = '''    std::puts("interior-exposure-test: all checks passed");
'''
T_BLOCK = r'''    // i. r99d: the far gate. The five measured views of build 31 (hero light off, the mod as noted;
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
        assert(Near(house_l.wanted_ev, std::log2(0.02f / 0.01732f), 1e-4f) && house_l.far_gate == 1.0f);
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
'''

# ------------------------------------------------------------------ README
R1_OLD = "and none that show 15% or more samples at depth 1 or at the open distance (80 m) or farther."
R1_NEW = ("and none that show 15% or more samples at depth 1 or at the open distance (80 m) or farther. "
          "**A second gate (r99d) keeps it out of deep outdoor courtyards**: the graveyard at night, ringed by tall "
          "cathedral walls, showed 1% open samples but 64% at 20 m and with the open gate alone got the full +0.75 "
          "outdoors. Now the lift also fades with the far share (samples at depth 1 or a quarter of the open distance, "
          "20 m, or farther): full up to 18%, none from 40%, half at 29% (the church's long hall, 11.3%, keeps the "
          "full lift; the library and the dream house, 0 to 3%, are unchanged). Sky samples count as open and as far, "
          "so a view that is mostly sky gets nothing; a ceiling or vault closer than 20 m with no sky in the view "
          "is taken as an interior after about 3 s")
R2_OLD = "times 1 - smoothstep(0.03, 0.15, eased open share): no lift at or above the target,"
R2_NEW = ("times 1 - smoothstep(0.03, 0.15, eased open share) times 1 - smoothstep(0.18, 0.40, eased far share) "
          "(far: depth 1, or at a quarter of the open distance, 20 m, or farther; eased 0.15 s while it grows and "
          "2 s while it shrinks, starting at 1): no lift at or above the target,")
R3_OLD = "open ...%, eased ...%, indoor ... (depth 1 ...%;"
R3_NEW = "open ...%, eased ...%, far (depth 1 or 20 m+) ...%, eased ...%, indoor ... = open gate ... x far gate ... (depth 1 ...%;"

# ------------------------------------------------------------------ the edit list
EDITS = []  # (path, old, new, block): block is None for a replacement, else the inserted text


def REPL(path, old, new):
    EDITS.append((path, old, new, None))


def INS_AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, anchor, block + anchor, block))


INS_AFTER(HDR, H_DOC_ANCHOR, H_DOC_BLOCK)
INS_AFTER(HDR, H_CONST_ANCHOR, H_CONST_BLOCK)
REPL(HDR, H_LIFT_OLD, H_LIFT_NEW)
REPL(HDR, H_WANT_OLD, H_WANT_NEW)
REPL(HDR, H_WANT2_OLD, H_WANT2_NEW)
INS_AFTER(HDR, H_STEP_ANCHOR, H_STEP_BLOCK)
INS_AFTER(VK_C, C_STATE_ANCHOR, C_STATE_BLOCK)
INS_AFTER(VK_C, C_REST_ANCHOR, C_REST_BLOCK)
REPL(VK_C, C_STEP_OLD, C_STEP_NEW)
REPL(VK_C, C_SAY_OLD, C_SAY_NEW)
REPL(VK_C, C_SAYARGS_OLD, C_SAYARGS_NEW)
REPL(VK_C, C_LINE_OLD, C_LINE_NEW)
INS_BEFORE(T_IE, T_ANCHOR, T_BLOCK)
REPL(README, R1_OLD, R1_NEW)
REPL(README, R2_OLD, R2_NEW)
REPL(README, R3_OLD, R3_NEW)


# ------------------------------------------------------------------ machinery
def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_of(path):
    return [e for e in EDITS if e[0] == path]


def edit_state(text, e):
    path, old, new, block = e
    if block is not None:
        if text.count(block) == 1:
            return "applied"
        return "clean" if text.count(block) == 0 and text.count(old) == 1 else "broken"
    if text.count(new) == 1 and text.count(old) == (1 if old in new else 0):
        return "applied"
    return "clean" if text.count(new) == 0 and text.count(old) == 1 else "broken"


def state_of(path, text):
    states = [edit_state(text, e) for e in edits_of(path)]
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    bad = [e[1][:60] for e, s in zip(edits_of(path), states) if s == "broken"]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d clean; old or new text not found as expected "
                     "(is r99c applied? is the file changed by someone else?): %r"
                     % (path, states.count("applied"), len(states), states.count("clean"), bad))


def apply_text(path, text):
    for p, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(block if block is not None else new) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:60]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, old, new, block in reversed(EDITS):
        if p != path:
            continue
        what = block if block is not None else new
        if text.count(what) != 1:
            raise SystemExit("REFUSED: %s: new text found %d times: %r" % (path, text.count(what), what[:60]))
        text = text.replace(what, "" if block is not None else old, 1)
    return text


def printf_args(call):
    """(specifier count, argument count) of one printf call's text between its parentheses."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(call):
        ch = call[i]
        if ch == '"':
            j = i + 1
            while call[j] != '"':
                j += 2 if call[j] == "\\" else 1
            cur += call[i:j + 1]
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[0])).replace("%%", "")
    return len(re.findall(r"%[-+ #0-9.]*[a-zA-Z]", fmt)), len(parts) - 1


def balanced(text, start):
    """index just after the ')' that closes the first '(' at or after start (strings skipped)."""
    depth, j = 0, text.find("(", start)
    while True:
        c = text[j]
        if c == '"':
            j += 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1


def text_checks(texts):
    header, cpp, readme, test = texts[HDR], texts[VK_C], texts[README], texts[T_IE]
    # the constants, the README and the test agree
    for t in ("FarFull = 0.18f;", "FarNone = 0.40f;", "FarRiseSeconds = 0.15f;", "FarFallSeconds = 2.0f;"):
        if header.count(t) != 1:
            raise SystemExit("header check: %r not once" % t)
    for t in ("full up to 18%, none from 40%, half at 29%", "smoothstep(0.18, 0.40, eased far share)",
              "eased 0.15 s while it grows and 2 s while it shrinks", "far (depth 1 or 20 m+)"):
        if readme.count(t) != 1:
            raise SystemExit("README check: %r not once" % t)
    if "Knobs()" in header or "FarShare(" not in cpp or "StepFar(" not in cpp:
        raise SystemExit("header or C++ check")
    if not all(ord(c) < 128 for c in R1_NEW + R2_NEW + R3_NEW):
        raise SystemExit("README text must be ASCII")
    if test.count("// i. r99d: the far gate.") != 1:
        raise SystemExit("test check: section i not once")
    # the printf counts of the two lines this patch changes
    for start in ('std::printf("Interior exposure (r99c, on by', 'std::printf("Interior exposure (r99b): applied'):
        at = cpp.find(start)
        if at < 0 or cpp.count(start) != 1:
            raise SystemExit("C++ check: %r not once" % start)
        i = cpp.find("(", at)
        j = balanced(cpp, at)
        specs, args = printf_args(cpp[i + 1:j])
        if specs != args:
            raise SystemExit("C++ check: printf %r has %d specifiers and %d arguments" % (start, specs, args))
        print("  printf %-45r %d specifiers, %d arguments" % (start[:44], specs, args))
    for t in ("s.far_eased = Policy::OpenStart;", "Policy::Want(knobs, reading, s.open_eased, s.far_eased);",
              "s.far_eased = Policy::StepFar(s.far_eased, Policy::FarShare(reading), dt);"):
        if cpp.count(t) != 1:
            raise SystemExit("C++ check: %r not once" % t)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R99D_ROOT)" % ROOT)
    paths = []
    for e in EDITS:
        if e[0] not in paths:
            paths.append(e[0])
    if "r99c_interior-default" not in load(HDR)[2]:
        raise SystemExit("REFUSED: r99c_interior-default is not applied in this tree: apply r99b and r99c "
                         "first, then this script")
    plan = []
    for path in paths:
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, state_of(path, cur)))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED: mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks({p[0]: apply_text(p[0], p[3]) for p in plan})
            print("not applied; would apply (%d files edited, %d edits; every old text found once; text "
                  "checks on the result pass)" % (len(plan), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, raw, eol, cur, _ in plan:
            texts[path] = apply_text(path, cur)
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r99dtmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r99dtmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(plan), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = [(path, revert_text(path, cur).replace("\n", eol).encode("utf-8")) for path, raw, eol, cur, _ in plan]
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files edited back)" % len(outs))


main()
