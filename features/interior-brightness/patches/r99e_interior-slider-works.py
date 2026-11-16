# r99e_interior-slider-works: FEATURE fix (lamp work, "dim interiors"), on top of r99, r99b, r99c and r99d
# (all applied; revert this one before them). Owner, build 72, 4K by hand: "Interior brightness I couldn't
# get it to work or change with the slider." The log said why: "Interior exposure (r99b): applied +0.000 EV,
# wanted +0.00 EV, metered 0.02246; ... indoor 1.00" with the target 0.020. The library (hand lantern out,
# so more light than the slot runs with the hero light off) meters ABOVE the fixed target 0.02, so the rule
# gap = log2(target / metered) is 0 and the slider (graphics_interior_brightness, the largest lift) only
# capped a zero: every slider position gave +0.000 EV.
#
# What it does: the target FOLLOWS the largest lift (the slider). EffectiveTarget = target * 2^(TargetPerStop
# * max_ev), at most TargetFollowCeiling (0.25), never below the target. At the default 0.75 the target is
# 0.034, at 1 0.040, at 2 0.080, at 3 0.160 (one stop of target per stop of slider).
# A room that meters under it is lifted by min(max_ev, strength * log2(effective target / metered)), so: a
# dark room (sewer, library with the mod, 0.001 to 0.015) still gets the whole slider value; the owner's
# 0.022 library gets +0.58 at 0.75, +0.83 at 1, +1.83 at 2, +2.83 at 3 (before: 0 at all of them); a bright
# room (0.2) gets nothing at any slider value (0.16 at 3 is still under 0.2). The lift is monotone in
# the slider: both the cap and the target rise with it. 0 is off as before. Outdoors does nothing: the open
# gate and the far gate (r99b, r99d) multiply the lift as before and are not touched. Nothing else changes:
# strength 1, the easing, the setting, the log.
#
# Side effect, by design: the dream house (metered 0.018 to 0.030) now gets +0.75 to +0.17 at the default
# where r99c/r99d gave +0.1 (the owner asked that interiors brighten; if the house is too bright the
# slider takes it down: at 0.25 the target is 0.024). The dark alley is held by the far gate as before.
#
# Knobs: nothing new for a player. Test only: BB_INTERIOR_EXPOSURE_FOLLOW=0 keeps r99d's fixed target (the
# off twin of this patch; r99's exact rule is that plus OPEN_M=0 MAX_EV=1.5); SHOW (BB_INTERIOR_EXPOSURE=2)
# keeps its own fixed numbers. Unset or any other value: the target follows.
#
# Files: engine/gpu/shim/bbport_interior_exposure.h (constants, Config::follow, EffectiveTarget, Env::follow,
# ParseEnv's 6th parameter, Lift::target, Want), renderer_vulkan/vk_interior_exposure.cpp (the once-line, the
# "largest lift is now" line and the periodic line print the effective target), engine/tests/test_interior_
# exposure.cpp (eight asserts of sections h and i updated, section j added), README.md (six short edits and
# one new table row). No shader, CMake, build.sh or settings change; the meter's dispatch is the same.
#
# Cost: nothing on the GPU (the meter is as before: one 256-thread group); on the CPU one exp2 per read
# reading (a few ns). Memory: none. Setting 0 and no variable: unchanged (Meter returns before anything here
# runs, the factor stays exactly 1.0).
#
# Use: python -I -X utf8 r99e_interior-slider-works.py check | apply | revert
# Root: R99E_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r99e_backup
# next to this script. Each edit replaces an old text found exactly once with a new one; revert puts each old
# text back where its new text is found exactly once. Needs r99d applied.
import os, re, sys

ROOT = os.environ.get("R99E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r99e_backup")
HDR = "engine/gpu/shim/bbport_interior_exposure.h"
VK_C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_interior_exposure.cpp"
T_IE = "engine/tests/test_interior_exposure.cpp"
README = "README.md"

# ------------------------------------------------------------------ header
H_DOC_ANCHOR = '''// Knobs (r99c_interior-default): ON by default'''
H_DOC_BLOCK = '''// The followed target (r99e_interior-slider-works): with the target fixed at 0.02 the slider only capped a
// zero in a room metered above it (build 72: the library with the hand lantern out metered 0.02246 and
// every slider position gave "applied +0.000 EV"). EffectiveTarget = target * 2^(TargetPerStop * max_ev), at
// most TargetFollowCeiling, never below the target: 0.034 at the default 0.75, 0.04 at 1, 0.08 at 2, 0.16
// at 3. The lift is min(max_ev, strength * log2(effective target / metered)) times the gates as before, so
// the lift rises with the slider in every room that meters under the target. Resolve() sets
// Config::follow; SHOW and BB_INTERIOR_EXPOSURE_FOLLOW=0 keep the fixed target (r99d's numbers).
//
'''

H_CONST_ANCHOR = '''              FarFallSeconds > 0.0f);
'''
H_CONST_BLOCK = '''inline constexpr float TargetPerStop = 1.0f;        ///< r99e: stops the target rises per stop of the largest lift
inline constexpr float TargetFollowCeiling = 0.25f; ///< r99e: the followed target never passes this
static_assert(TargetPerStop >= 0.0f && TargetFollowCeiling > DefaultTarget);
'''

H_CFG_ANCHOR = '''    float open_m = DefaultOpenMeters; ///< 0: only depth 1 is open
'''
H_CFG_BLOCK = '''    bool follow = false;              ///< r99e: the target rises with max_ev (EffectiveTarget); Resolve() sets it
'''

H_EFF_ANCHOR = '''/// A number that Number() reads from `text`: not null, not empty, all of it a finite number.
'''
H_EFF_BLOCK = '''/// The target Want() aims at (r99e). Not following (SHOW, BB_INTERIOR_EXPOSURE_FOLLOW=0, a Config from
/// Parse): c.target. Following: c.target * 2^(TargetPerStop * max_ev), at most TargetFollowCeiling and never
/// below c.target, so a bigger slider value also lifts the rooms that meter a little above the plain target.
inline float EffectiveTarget(const Config& c) {
    if (!c.follow) {
        return c.target;
    }
    const float raised = c.target * std::exp2(TargetPerStop * std::max(c.max_ev, 0.0f));
    return std::max(c.target, std::min(raised, TargetFollowCeiling));
}

'''

H_ENV_ANCHOR = '''    bool max_ev_set = false; ///< BB_INTERIOR_EXPOSURE_MAX_EV is a number: the largest lift
'''
H_ENV_BLOCK = '''    bool follow = true;      ///< r99e: BB_INTERIOR_EXPOSURE_FOLLOW is not 0: the target follows the largest lift
'''

H_PE_OLD = '''inline Env ParseEnv(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m) {
'''
H_PE_NEW = '''inline Env ParseEnv(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m, const char* follow = nullptr) {
'''
H_PE2_ANCHOR = '''    e.max_ev_set = Readable(max_ev);
'''
H_PE2_BLOCK = '''    e.follow = !(follow && follow[0] == '0' && follow[1] == '\\0');
'''

H_RES_OLD = '''    c.max_ev = max_ev;
    return c;
'''
H_RES_NEW = '''    c.max_ev = max_ev;
    c.follow = env.follow;
    return c;
'''

H_ENVR_OLD = '''                 std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"));
'''
H_ENVR_NEW = '''                 std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"), std::getenv("BB_INTERIOR_EXPOSURE_FOLLOW"));
'''

H_LIFT_ANCHOR = '''    float far_gate = 0;   ///< 1 - smoothstep(FarFull, FarNone, the eased far share), r99d
'''
H_LIFT_BLOCK = '''    float target = 0;     ///< EffectiveTarget of the config this reading was wanted with, r99e
'''

H_WANT_ANCHOR = '''    l.far_gate = FarGate(far_eased);
'''
H_WANT_BLOCK = '''    l.target = EffectiveTarget(c);
'''

H_GAP_OLD = '''    const float gap = std::max(0.0f, std::log2(c.target / l.metered));
'''
H_GAP_NEW = '''    const float gap = std::max(0.0f, std::log2(l.target / l.metered));
'''

# ------------------------------------------------------------------ C++
C_SAY_OLD = '''                "target %.3f, strength %.2f, at most %+.2f EV (from %s); open samples: %s; no lift with %.0f%% "
'''
C_SAY_NEW = '''                "target %.3f (%s: %.4f at the largest lift), strength %.2f, at most %+.2f EV (from %s); open samples: %s; no lift with %.0f%% "
'''
C_SAYARGS_OLD = '''                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev, max_from, open,
'''
C_SAYARGS_NEW = '''                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.follow ? "followed" : "fixed",
                Policy::EffectiveTarget(knobs), knobs.strength, knobs.max_ev, max_from, open,
'''
C_NOW_OLD = '''            std::printf("Interior exposure (r99c): the largest lift is now %+.2f EV (from %s)\\n",
                        knobs.max_ev, Policy::MaxSource(env, setting));
'''
C_NOW_NEW = '''            std::printf("Interior exposure (r99c): the largest lift is now %+.2f EV (from %s), target now %.4f\\n",
                        knobs.max_ev, Policy::MaxSource(env, setting), Policy::EffectiveTarget(knobs));
'''
C_LINE_OLD = '''                    "%.5f; open %.1f%%, eased %.1f%%, far (depth 1 or %.0f m+) %.1f%%, eased "
'''
C_LINE_NEW = '''                    "%.5f (target %.4f); open %.1f%%, eased %.1f%%, far (depth 1 or %.0f m+) %.1f%%, eased "
'''
C_LINEARGS_OLD = '''                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered,
'''
C_LINEARGS_NEW = '''                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered, s.last.target,
'''

# ------------------------------------------------------------------ tests
T_REPL = [
    ('''        assert(lib > 0.50f && lib < 0.53f && Near(lib, std::log2(0.02f / 0.014f), 1e-4f));
''', '''        assert(lib == DefaultMaxEv); // r99e: the target follows the slider (0.034 at 0.75), the gap 1.26 passes the cap
'''),
    ('''        assert(Want(d, Scene(0.01425f, all, 0)).wanted_ev > 0.48f && Want(d, Scene(0.01425f, all, 0)).wanted_ev < 0.50f);
''', '''        assert(Want(d, Scene(0.01425f, all, 0)).wanted_ev == DefaultMaxEv);
'''),
    ('''        assert(church_mod > 0.69f && church_mod < 0.71f);
''', '''        assert(church_mod == DefaultMaxEv);
'''),
    ('''        assert(Want(d, Scene(0.018f, all, 0)).wanted_ev > 0.14f && Want(d, Scene(0.018f, all, 0)).wanted_ev < 0.16f);
''', '''        assert(Want(d, Scene(0.018f, all, 0)).wanted_ev == DefaultMaxEv); // the dream house, r99e
'''),
    ('''        assert(Want(d, Scene(0.02f, all, 0)).wanted_ev < 1e-4f && Want(d, Scene(0.025f, all, 0)).wanted_ev == 0.0f);
''', '''        // the gap here is 0.75 only up to float rounding (target 0.02 x 2^0.75, metered ~0.02): not ==
        assert(Near(Want(d, Scene(0.02f, all, 0)).wanted_ev, DefaultMaxEv, 1e-4f));
        assert(Near(Want(d, Scene(0.025f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.025f), 1e-4f));
'''),
    ('''        assert(Want(d, Scene(0.02982f, all, 0)).wanted_ev == 0.0f && Want(d, Scene(0.05192f, all, 0)).wanted_ev == 0.0f);
''', '''        assert(Near(Want(d, Scene(0.02982f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.02982f), 1e-4f));
        assert(Want(d, Scene(0.05192f, all, 0)).wanted_ev == 0.0f);
'''),
    ('''        assert(Want(d, Scene(0.02509f, all, 0)).wanted_ev == 0.0f); // the dark alley without the mod
''', '''        assert(Near(Want(d, Scene(0.02509f, all, 0)).wanted_ev, std::log2(EffectiveTarget(d) / 0.02509f), 1e-4f));
        // (the dark alley without the mod: held back outdoors by the far gate, section i)
'''),
    ('''        assert(Near(Want(Resolve(none, 3.0f), Scene(0.0055f, all, 0)).wanted_ev, std::log2(0.02f / 0.0055f), 1e-4f));
''', '''        assert(Want(Resolve(none, 3.0f), Scene(0.0055f, all, 0)).wanted_ev == 3.0f); // target 0.16: gap 4.9, cap 3
'''),
    ('''        assert(Near(house_l.wanted_ev, std::log2(0.02f / 0.01732f), 1e-4f) && house_l.far_gate == 1.0f);
''', '''        assert(house_l.wanted_ev == DefaultMaxEv && house_l.far_gate == 1.0f); // r99e: 0.034 target, was +0.21
'''),
]

T_ANCHOR = '''    std::puts("interior-exposure-test: all checks passed");
'''
T_BLOCK = '''    // j. r99e: the target follows the largest lift, so the slider works in a room above the plain target.
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
'''

# ------------------------------------------------------------------ README
R1_OLD = '''It lifts only dark views (target 0.02, strength 1: a view metered at 0.02 or above gets nothing) and none that show'''
R1_NEW = '''It lifts only dark views (strength 1; the target is not fixed since r99e: it is 0.02 times 2 to the power of the largest lift, at most 0.25, so it is 0.034 at the default 0.75, 0.08 at 2 and 0.16 at 3, and the slider moves both the cap and how bright a room may be and still be lifted; before r99e the target stayed 0.02 and a room metered above it, the library with the hand lantern out at 0.022 in the owner's build-72 run, got +0.000 EV at every slider position; a view metered at the target or above gets nothing) and none that show'''
R2_OLD = '''**without the BB PC Remaster mod the library meters about 0.014 and gets about +0.5 stops (log2(0.02 / 0.014)), so it is brightened a little even without the mod**'''
R2_NEW = '''**without the BB PC Remaster mod the library meters about 0.014 and gets the full +0.75 at the default (+0.58 when it meters 0.022, with the hand lantern out; +0.83, +1.83 and +2.83 at slider values 1, 2 and 3)**'''
R3_OLD = '''The Hunter's Dream house meters 0.018 to 0.025 (0.030 with the mod) and gets no lift worth seeing (at most +0.15 EV at the dark end of that range, 0 from 0.02 up).'''
R3_NEW = '''The Hunter's Dream house meters 0.018 to 0.025 (0.030 with the mod) and gets +0.75 (0.018) to +0.43 (0.025) at the default, +0.17 at 0.030, nothing from 0.034 up (before r99e: at most +0.15 EV, 0 from 0.02 up; a lower slider value takes it down).'''
R4_OLD = '''The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off'''
R4_NEW = '''The target L, a log-average luminance before the tone curve, 0.005 to 1; since r99e the target in use is L times 2 to the power of the largest lift, at most 0.25 and never below L (0.034 at the default; the log lines say it), unless `BB_INTERIOR_EXPOSURE_FOLLOW=0` or SHOW (measured with the hero light off'''
R5_OLD = '''The lift in stops is min(max, strength x log2(target / L)), never below 0,'''
R5_NEW = '''The lift in stops is min(max, strength x log2(target / L)) (the followed target, r99e), never below 0,'''
R6_OLD = '''the largest lift in stops, 0 to 3, read every frame'''
R6_NEW = '''the largest lift in stops, 0 to 3 (it also raises the target in use, r99e), read every frame'''
R7_ANCHOR = '''| `BB_INTERIOR_EXPOSURE_OPEN_M` | The open distance in metres of view depth, 0 to 1000; 0 counts only depth 1 as open | `80` (`80`) |
'''
R7_BLOCK = '''| `BB_INTERIOR_EXPOSURE_FOLLOW` | Test only (r99e): `0` keeps the target fixed at `BB_INTERIOR_EXPOSURE_TARGET` (the rule before r99e, in which a room metered above 0.02 got no lift at any slider value); unset, empty or anything else: the target follows the largest lift (L times 2 to the power of it, at most 0.25, never below L). Read once. SHOW keeps its fixed numbers. Costs nothing | follows |
'''

EDITS = []  # (path, old, new, block): block is None for a replacement, else the inserted text


def REPL(path, old, new):
    EDITS.append((path, old, new, None))


def INS_AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, anchor, block + anchor, block))


INS_BEFORE(HDR, H_DOC_ANCHOR, H_DOC_BLOCK)
INS_AFTER(HDR, H_CONST_ANCHOR, H_CONST_BLOCK)
INS_AFTER(HDR, H_CFG_ANCHOR, H_CFG_BLOCK)
INS_BEFORE(HDR, H_EFF_ANCHOR, H_EFF_BLOCK)
INS_AFTER(HDR, H_ENV_ANCHOR, H_ENV_BLOCK)
REPL(HDR, H_PE_OLD, H_PE_NEW)
INS_AFTER(HDR, H_PE2_ANCHOR, H_PE2_BLOCK)
REPL(HDR, H_RES_OLD, H_RES_NEW)
REPL(HDR, H_ENVR_OLD, H_ENVR_NEW)
INS_AFTER(HDR, H_LIFT_ANCHOR, H_LIFT_BLOCK)
INS_AFTER(HDR, H_WANT_ANCHOR, H_WANT_BLOCK)
REPL(HDR, H_GAP_OLD, H_GAP_NEW)
REPL(VK_C, C_SAY_OLD, C_SAY_NEW)
REPL(VK_C, C_SAYARGS_OLD, C_SAYARGS_NEW)
REPL(VK_C, C_NOW_OLD, C_NOW_NEW)
REPL(VK_C, C_LINE_OLD, C_LINE_NEW)
REPL(VK_C, C_LINEARGS_OLD, C_LINEARGS_NEW)
for _o, _n in T_REPL:
    REPL(T_IE, _o, _n)
INS_BEFORE(T_IE, T_ANCHOR, T_BLOCK)
REPL(README, R1_OLD, R1_NEW)
REPL(README, R2_OLD, R2_NEW)
REPL(README, R3_OLD, R3_NEW)
REPL(README, R4_OLD, R4_NEW)
REPL(README, R5_OLD, R5_NEW)
REPL(README, R6_OLD, R6_NEW)
INS_AFTER(README, R7_ANCHOR, R7_BLOCK)


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
                     "(is r99d applied? is the file changed by someone else?): %r"
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
    """index of the ')' that closes the first '(' at or after start (strings skipped)."""
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
    for t in ("TargetPerStop = 1.0f;", "TargetFollowCeiling = 0.25f;", "inline float EffectiveTarget(const Config& c) {",
              "c.follow = env.follow;", "l.target = EffectiveTarget(c);",
              "std::log2(l.target / l.metered)", 'std::getenv("BB_INTERIOR_EXPOSURE_FOLLOW")'):
        if header.count(t) != 1:
            raise SystemExit("header check: %r not once" % t)
    if "std::log2(c.target / l.metered)" in header:
        raise SystemExit("header check: the fixed target is still used in Want")
    for t in ("0.034 at the default 0.75", "`BB_INTERIOR_EXPOSURE_FOLLOW`", "(the followed target, r99e)"):
        if readme.count(t) != 1:
            raise SystemExit("README check: %r not once" % t)
    if not all(ord(c) < 128 for c in R1_NEW + R2_NEW + R3_NEW + R4_NEW + R5_NEW + R6_NEW + R7_BLOCK):
        raise SystemExit("README text must be ASCII")
    if test.count("// j. r99e: the target follows the largest lift") != 1:
        raise SystemExit("test check: section j not once")
    if "std::log2(0.02f / 0.014f)" in test or "std::log2(0.02f / 0.01732f)" in test:
        raise SystemExit("test check: an old number is left")
    for start in ('std::printf("Interior exposure (r99c, on by', 'std::printf("Interior exposure (r99b): applied',
                  'std::printf("Interior exposure (r99c): the largest lift is now'):
        at = cpp.find(start)
        if at < 0 or cpp.count(start) != 1:
            raise SystemExit("C++ check: %r not once" % start)
        i = cpp.find("(", at)
        j = balanced(cpp, at)
        specs, args = printf_args(cpp[i + 1:j])
        if specs != args:
            raise SystemExit("C++ check: printf %r has %d specifiers and %d arguments" % (start, specs, args))
        print("  printf %-45r %d specifiers, %d arguments" % (start[:44], specs, args))
    for t in ("Policy::EffectiveTarget(knobs)", "s.last.target,"):
        if cpp.count(t) < 1:
            raise SystemExit("C++ check: %r missing" % t)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R99E_ROOT)" % ROOT)
    paths = []
    for e in EDITS:
        if e[0] not in paths:
            paths.append(e[0])
    if "r99d_interior-open-gate" not in load(HDR)[2]:
        raise SystemExit("REFUSED: r99d_interior-open-gate is not applied in this tree: apply r99b, r99c and "
                         "r99d first, then this script")
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
                tmp = full + ".r99etmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r99etmp"
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
