# r100j_sheen-clean-rim: FEATURE fix on top of r100i_sheen-blood-tint (r100h, r100g, r100f, r100e, r100d; branch
# visual/blood-sheen). Applies ON TOP of r100i (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset
# makes no BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test per
# hook).
#
# Why (build 46, graveyard-blood, zoom _rd_blood_pair.png): the pool body reads as dark red wet blood (kept
# exactly), but the gravel at the pool's rim shows red-pink glints, worse at strength 2. Those pixels are the
# gap-fill zone of r100h: ground pixels that are NOT dark red themselves, made wet by the fill weight
# (smoothstep(0.5, 0.8, share of 24 ring taps) times the up weight). They got the body's full specular tint and
# gloss times that weight, and their own bumpy gravel albedo/normal under a glossy red lobe sparkles.
# What this patch changes (EDIT pass only; the body, the normal levelling, the gap-fill weight itself and the
# dimming after the lighting are unchanged, so a pixel that passes the albedo rule is bit-identical to b46):
#  a gap-fill pixel's specular colour AND gloss weight is its wet weight w times a rim share
#      k = mix(FILL_SPEC, 1, smoothstep(FILL_HI, 1, pool_share)),   FILL_SPEC = 0.5,
#  so at the pool's rim (share 0.5..0.8) the tint and gloss are at most 0.5 of the body's, falling smoothly to
#  0 with the fill weight, and a stone deep inside the pool (share toward 1) climbs back to the body's value
#  with no step. Every term is a continuous function of the pixel's own 24-tap share: no block, no group, no
#  neighbour result. Pixels that pass the albedo rule have k = 1 (the body, exactly as b46).
#
# Cost: EDIT only: one mix and one smoothstep per FILLED pixel (the few at the pool's rim), nothing for any
# other pixel; no fetch, no pass, no image, no memory, no new counter word (the wet count and the albedo-rule
# count are unchanged, so "filled" = wet minus rule still reads). Estimate, not measured: far below 0.01 ms.
# Off by default, costs nothing off: no BloodSheen object is made unless BB_BLOOD_SHEEN is on (r100d).
#
# Files (anchored edits on r100i's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp (one log line),
# tests/test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit. No new knob: the rim share
# is a constant (BLOOD_SHEEN_FILL_SPEC), strength and BB_BLOOD_SHEEN_DARKEN work as before.
#
# Use: python -I -X utf8 r100j_sheen-clean-rim.py check | apply | revert. Root from R100J_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100j_sheen-clean-rim_backup/ next to this
# script; a mixed state is refused and nothing is written. Revert order: this script, then r100i.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100j_sheen-clean-rim"
BASE = "r100i_sheen-blood-tint.py"
ROOT_ENV = "R100J_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100jtmp"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
LAYOUT = HS + "blood_sheen_layout.h"
COMP = HS + "blood_sheen.comp"
RULES = RV + "blood_sheen.h"
SHEEN = RV + "vk_blood_sheen.cpp"
TEST = "engine/tests/test_blood_sheen.cpp"
README = "README.md"

EDITS = {
LAYOUT: [
(r'''#define BLOOD_SHEEN_FILL_MIN_HITS 2
''',
r'''#define BLOOD_SHEEN_FILL_MIN_HITS 2
// r100j_sheen-clean-rim: a gap-fill pixel's specular colour and gloss weight is its wet weight times
// mix(FILL_SPEC, 1, smoothstep(FILL_HI, 1, share)): at the pool's rim at most FILL_SPEC (0.5) of the body's,
// back to the body's value deep inside the pool. A pixel that passes the albedo rule is not a gap: share 1.
#define BLOOD_SHEEN_FILL_SPEC 0.5
'''),
],

COMP: [
(r'''            const float w = clamp(strength, 0.0, 1.0) * wet;
''',
r'''            const float w = clamp(strength, 0.0, 1.0) * wet;
            // r100j_sheen-clean-rim: the rim's gap-fill pixels (not dark red themselves) get a smaller specular
            // tint and gloss than the body, smoothly: half at the rim, the body's value deep inside the pool.
            const float rim_k = filled ? mix(BLOOD_SHEEN_FILL_SPEC, 1.0, smoothstep(BLOOD_SHEEN_FILL_HI, 1.0, pool_share))
                                       : 1.0;
            const float ws = w * rim_k;
'''),
(r'''            m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, w); // r100h:''',
r'''            m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws); // r100h (r100j: rim weight):'''),
(r'''            s.r = max(s.r, mix(s.r, target.r, w));
            s.gb = mix(s.gb, target.gb, w);
''',
r'''            s.r = max(s.r, mix(s.r, target.r, ws));
            s.gb = mix(s.gb, target.gb, ws);
'''),
],

RULES: [
(r'''static_assert(BLOOD_SHEEN_FILL_LO == 0.5 && BLOOD_SHEEN_FILL_HI == 0.8 && BLOOD_SHEEN_FILL_MIN_HITS == 2);
''',
r'''static_assert(BLOOD_SHEEN_FILL_LO == 0.5 && BLOOD_SHEEN_FILL_HI == 0.8 && BLOOD_SHEEN_FILL_MIN_HITS == 2);
inline constexpr float FillSpec = float(BLOOD_SHEEN_FILL_SPEC); ///< r100j_sheen-clean-rim: the rim's share of the body's specular
static_assert(BLOOD_SHEEN_FILL_SPEC == 0.5);
'''),
(r'''    return {std::max(ground_r, ground_r + (tr - ground_r) * w), ground_g + (tg - ground_g) * w,
            ground_b + (tb - ground_b) * w};
}
''',
r'''    return {std::max(ground_r, ground_r + (tr - ground_r) * w), ground_g + (tg - ground_g) * w,
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
'''),
],

SHEEN: [
(r'''                         root * double(R::TintB) * root * double(R::TintB));
    }
}
''',
r'''                         root * double(R::TintB) * root * double(R::TintB));
    }
    // bbport (r100j_sheen-clean-rim): the rim rule, once.
    BbReport::Printf("Blood sheen (r100j): the pool's rim (gap-fill pixels, not dark red themselves) gets at most %.2f "
                     "of the body's specular tint and gloss, rising smoothly to the body's value where 80-100%% of "
                     "its ring taps are dark red; pixels that pass the albedo rule are as before\n",
                     double(R::FillSpec));
}
'''),
],

TEST: [
(r'''            assert(FilledLevelShare(1.0f, f + 0.01f, 1.0f, 8) >= FilledLevelShare(1.0f, f, 1.0f, 8));
        }
''',
r'''            assert(FilledLevelShare(1.0f, f + 0.01f, 1.0f, 8) >= FilledLevelShare(1.0f, f, 1.0f, 8));
        }
        // j. bbport (r100j_sheen-clean-rim): the rim's share of the body's specular. A pixel that passes the
        // albedo rule is the body (1); a gap-fill pixel gets half at the rim and in the fill's range up to
        // FILL_HI, then climbs smoothly to 1 at share 1; it never decreases with the share, never steps.
        assert(Near(FillSpec, 0.5, 1e-6));
        assert(RimSpecShare(false, 0.0f) == 1.0f && RimSpecShare(false, 0.6f) == 1.0f && RimSpecShare(false, 1.0f) == 1.0f);
        assert(Near(RimSpecShare(true, 0.5f), 0.5) && Near(RimSpecShare(true, 0.65f), 0.5) && Near(RimSpecShare(true, 0.8f), 0.5));
        assert(Near(RimSpecShare(true, 0.9f), 0.75) && Near(RimSpecShare(true, 1.0f), 1.0));
        for (float f = 0.0f; f < 1.0f; f += 0.005f) {
            const float a = RimSpecShare(true, f), b = RimSpecShare(true, f + 0.005f);
            assert(b >= a && b - a < 0.03f && a >= 0.5f - 1e-6f && b <= 1.0f + 1e-6f);
        }
        {
            // the rim: a gap pixel at share 0.8, full fill weight (up 1), strength 1: tint and gloss half of the body's.
            const float fill = FillWeight(0.8f, 1.0f, 8);
            const float k = RimSpecShare(true, 0.8f);
            const SpecRoot body = WetSpec(0.2f, 0.2f, 0.2f, 1.0f);
            const SpecRoot rim = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, fill * k);
            assert(Near(fill, 1.0) && Near(k, 0.5));
            assert(Near(rim.g, 0.2 + (body.g - 0.2) * 0.5, 1e-4) && Near(rim.b, 0.2 + (body.b - 0.2) * 0.5, 1e-4));
            assert(rim.r >= 0.2f && Near(Wet(0.3f, 0.2f, 1.0f, fill * k).gloss, 0.3 + (WetGloss - 0.3) * 0.5, 1e-4));
            // deep inside (share 1) a gap pixel is the body exactly; strength 2: the rim stays at half of its body.
            const SpecRoot deep = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, FillWeight(1.0f, 1.0f, 8) * RimSpecShare(true, 1.0f));
            assert(Near(deep.g, body.g, 1e-6) && Near(deep.b, body.b, 1e-6) && Near(deep.r, body.r, 1e-6));
            const SpecRoot body2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f);
            const SpecRoot rim2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f, 0.5f);
            assert(Near(rim2.g, body2.g * 0.5, 1e-4) && Near(rim2.r, body2.r * 0.5, 1e-4));
        }
'''),
],

README: [
(r'''the red is never lowered, the green and blue go down to the tinted value on the wet pixels;''',
 r'''the red is never lowered, the green and blue go down to the tinted value on the wet pixels; the pool's rim (the gap-fill pixels that are not dark red themselves) gets at most half of that tint and gloss (BLOOD_SHEEN_FILL_SPEC 0.5, rising smoothly to the full value where 80-100% of the ring taps are dark red) so the gravel at the edge reads as a soft wet edge without red sparkle;'''),
],
}

ORDER = list(EDITS)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("REFUSED %s: missing" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def one_state(cur, old, new):
    """An edit's state: a replacement (old not in new) or an insertion (new holds old)."""
    o, n = cur.count(old), cur.count(new)
    inner = new.count(old)
    if n == 1 and o == inner:
        return "applied"
    if n == 0 and o == 1:
        return "clean"
    return None


def edit_state(path, cur):
    states = [one_state(cur, old, new) for old, new in EDITS[path]]
    if None in states:
        bad = EDITS[path][states.index(None)]
        raise SystemExit("REFUSED %s: an edit's text is not found exactly once (before: %d times, after: %d "
                         "times; %s must be applied): %r" % (path, cur.count(bad[0]), cur.count(bad[1]), BASE,
                                                              bad[0][:70]))
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, states.count("applied"), len(states)))


def need(path, text, want, n=1):
    if text.count(want) != n:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), n))


def text_checks(t):
    comp, lay, hdr, cpp, tst = t[COMP], t[LAYOUT], t[RULES], t[SHEEN], t[TEST]
    need(LAYOUT, lay, "#define BLOOD_SHEEN_FILL_SPEC 0.5\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_TINT_R 0.85\n")  # r100i is under this
    need(COMP, comp, "const float ws = w * rim_k;")
    need(COMP, comp, "m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws);")
    need(COMP, comp, "s.r = max(s.r, mix(s.r, target.r, ws));")
    need(COMP, comp, "s.gb = mix(s.gb, target.gb, ws);")
    need(COMP, comp, ", w);", 0)                          # no gloss/spec mix left on the bare weight
    need(COMP, comp, "const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *")  # the levelling keeps w (unchanged)
    need(COMP, comp, "barrier()", 2)                      # the counter code's two only
    need(RULES, hdr, "static_assert(BLOOD_SHEEN_FILL_SPEC == 0.5);")
    need(RULES, hdr, "inline float RimSpecShare(bool filled, float pool_share)")
    need(RULES, hdr, "inline SpecRoot WetSpec(")
    need(SHEEN, cpp, "Blood sheen (r100j): the pool's rim")
    need(SHEEN, cpp, "Blood sheen (r100i): the film's specular is tinted")
    need(TEST, tst, "RimSpecShare(true, 0.9f)")
    for line in cpp.split("\n"):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line:
            raise SystemExit("text check: a log line without its prefix: %r" % line)
    added = [new for eds in EDITS.values() for old, new in eds]
    if any(ord(ch) > 127 for text in added for ch in text):
        raise SystemExit("text check: a new text is not plain ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 %s.py check | apply | revert" % NAME)
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set %s)" % (ROOT, ROOT_ENV))
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, edit_state(path, cur)))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()

    def result(forward):
        out = {}
        for path, raw, eol, cur, _ in plan:
            for old, new in EDITS[path]:
                cur = cur.replace(old, new) if forward else cur.replace(new, old)
            want = "applied" if forward else "clean"
            if edit_state(path, cur) != want:
                raise SystemExit("%s: the result does not read as %s; nothing written" % (path, want))
            out[path] = cur
        return out

    def write(texts):
        for path, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            open(full + TMP, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(full + TMP, full)

    edits = sum(len(e) for e in EDITS.values())
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (%d edits in %d files; text checks pass)" % (edits, len(EDITS)))
        else:
            text_checks(result(True))
            print("not applied; would apply (%d edits in %d files; text checks on the result pass)" % (edits, len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = result(True)
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write(texts)
        print("applied (%d edits in %d files)" % (edits, len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    write(result(False))
    print("reverted (%d edits taken out of %d files)" % (edits, len(EDITS)))


main()
