# r100i_sheen-blood-tint: FEATURE fix on top of r100h_sheen-liquid (r100g, r100f, r100e, r100d; branch visual/blood-sheen).
# Applies ON TOP of r100h (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset makes no
# BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test per hook).
#
# Why (build 43, graveyard-blood, zoom _rd_trio.png): r100h made the pool a smooth continuous liquid sheet
# (kept), but the sheet reflected in a neutral white-blue: the wet film's specular colour was one grey root for
# red, green and blue (0.55, f0 0.30), so the moon made a bright blue-white panel and the pool no longer read as
# blood. The owner wants "wet sheen from blood".
# What this patch changes (EDIT pass only; the shape of the sheet, the gloss, the normal levelling, the gap
# fill, the dimming after the lighting are all unchanged):
#  (1) the specular colour of a wet pixel is TINTED by the blood: the root (before the tint) is multiplied by
#      (TINT_R, TINT_G, TINT_B) = (0.85, 0.35, 0.30), a deep red. f0 is the root squared, so red keeps 0.72 of
#      the untinted intensity, green 0.12 and blue 0.09: the moon (blue-white) gives a dark red glossy
#      highlight, a torch (orange) a warm red-orange one. The red channel is never lowered (max with what the
#      ground has, as before); green and blue DO go down to the tinted target on wet pixels (a grey cobble's
#      green/blue specular would otherwise put the white back), by the pixel's wet weight, so the rim and the
#      filled gaps blend.
#  (2) the root is capped lower: 0.45 at strength 1 (was 0.55, f0 0.20 untinted, red f0 0.146 after the tint),
#      cap 0.65 (was 0.75; strength 2: 0.45 * sqrt(2) = 0.636, red f0 0.29): the sheet is a narrower, dimmer
#      highlight, not a lit panel; strength 2 is brighter. (These are r100g's numbers 0.45 and 0.65.)
#  (3) the pool body stays darker and richer red than the dry stone: the dimming after the lighting (r100e/r100g,
#      BB_BLOOD_SHEEN_DARKEN, default 0.5) is unchanged; with the white sheet gone, the body is no longer
#      washed out by the highlight.
# The tint is a constant deep red, not the albedo read per pixel: the gap-filled pixels (stones inside the pool)
# have a grey albedo, and a per-pixel hue would put grey highlights back on them.
#
# Cost: EDIT only: one vec3 multiply and two more mixes per made-wet pixel (a few ALU, no fetch, no new pass,
# no new image, no new memory, no new counter word). Estimate, not measured: far below 0.01 ms.
# Off by default, costs nothing off: no BloodSheen object is made unless BB_BLOOD_SHEEN is on (r100d).
#
# Files (anchored edits on r100h's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp (one log line),
# tests/test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit.
#
# Use: python -I -X utf8 r100i_sheen-blood-tint.py check | apply | revert. Root from R100I_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100i_sheen-blood-tint_backup/ next to this
# script; a mixed state is refused and nothing is written. Revert order: this script, then r100h.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100i_sheen-blood-tint"
BASE = "r100h_sheen-liquid.py"
ROOT_ENV = "R100I_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100itmp"
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
(r'''#define BLOOD_SHEEN_WET_SPEC_ROOT 0.55
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.75
''',
r'''// r100i_sheen-blood-tint: root 0.45 (f0 0.20 before the tint), cap 0.65 (strength 2: 0.636), and the root is
// TINTED by the blood: multiplied per channel by (TINT_R, TINT_G, TINT_B), a deep red (f0 = root squared, so red
// keeps 0.72 of the intensity, green 0.12, blue 0.09): the moon gives a dark red highlight, a torch a warm red
// orange one. Red is never lowered; green and blue go down to the tinted target by the pixel's wet weight.
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65
#define BLOOD_SHEEN_TINT_R 0.85
#define BLOOD_SHEEN_TINT_G 0.35
#define BLOOD_SHEEN_TINT_B 0.30
'''),
],

COMP: [
(r'''            s.rgb = max(s.rgb, mix(s.rgb, vec3(root), w));
''',
r'''            // r100i_sheen-blood-tint: the root is tinted by the blood (deep red). Red is never lowered; green and
            // blue go down to the tinted target by the wet weight (a grey cobble's own green and blue specular
            // would put the white back).
            const vec3 target = vec3(root) * vec3(BLOOD_SHEEN_TINT_R, BLOOD_SHEEN_TINT_G, BLOOD_SHEEN_TINT_B);
            s.r = max(s.r, mix(s.r, target.r, w));
            s.gb = mix(s.gb, target.gb, w);
'''),
],

RULES: [
(r'''root 0.55 * sqrt(strength), at most 0.75);''',
r'''root 0.45 * sqrt(strength), at most 0.65, tinted deep red);'''),
(r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.55 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.75);
''',
r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.45 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.65);
// bbport (r100i_sheen-blood-tint): the specular root's tint (deep red), per channel.
inline constexpr float TintR = float(BLOOD_SHEEN_TINT_R), TintG = float(BLOOD_SHEEN_TINT_G);
inline constexpr float TintB = float(BLOOD_SHEEN_TINT_B);
static_assert(BLOOD_SHEEN_TINT_R == 0.85 && BLOOD_SHEEN_TINT_G == 0.35 && BLOOD_SHEEN_TINT_B == 0.30);
'''),
(r'''    return {gloss + (WetGloss - gloss) * w, std::max(root, root + (target - root) * w)};
}
''',
r'''    return {gloss + (WetGloss - gloss) * w, std::max(root, root + (target - root) * w)};
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
'''),
],

SHEEN: [
(r'''                     k.darken > 0.0f ? "on" : "off: no dimming pass");
}
''',
r'''                     k.darken > 0.0f ? "on" : "off: no dimming pass");
    // bbport (r100i_sheen-blood-tint): the specular root's tint, once.
    {
        const double root = double(std::min(R::WetSpecRoot * std::sqrt(std::max(k.strength, 1.0f)), R::SpecRootMax));
        BbReport::Printf("Blood sheen (r100i): the film's specular is tinted by the blood: root %.3f at this strength "
                         "(cap %.2f) times (%.2f, %.2f, %.2f), so f0 red %.3f, green %.3f, blue %.3f (the red is "
                         "never lowered; green and blue go down to it on wet pixels)\n",
                         root, double(R::SpecRootMax), double(R::TintR), double(R::TintG), double(R::TintB),
                         root * double(R::TintR) * root * double(R::TintR),
                         root * double(R::TintG) * root * double(R::TintG),
                         root * double(R::TintB) * root * double(R::TintB));
    }
}
'''),
],

TEST: [
(r'''    // root is never lowered; strength 1 reaches gloss 0.86 and root 0.55; above 1 the root grows with the
    // square root, at most 0.75; below 1 a share of the way; a weight below 1 is a share again.
''',
r'''    // root is never lowered; strength 1 reaches gloss 0.86 and root 0.45 (r100i_sheen-blood-tint; the root
    // before the tint); above 1 the root grows with the square root, at most 0.65; below 1 a share of the way;
    // a weight below 1 is a share again.
'''),
(r'''        assert(Near(half.gloss, 0.58) && Near(half.root, 0.325));
''',
r'''        assert(Near(half.gloss, 0.58) && Near(half.root, 0.275));
'''),
(r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) && Near(Wet(0.0f, 0.0f, 2.0f).root, SpecRootMax));
        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.55) && Near(SpecRootMax, 0.75));
        assert(Near(Wet(0.0f, 0.0f, 1.5f).root, 0.55 * std::sqrt(1.5)) && Wet(0.0f, 0.0f, 1.5f).root < SpecRootMax);
''',
r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).root, SpecRootMax) &&
               Near(Wet(0.0f, 0.0f, 2.0f).root, WetSpecRoot * std::sqrt(2.0)));
        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.45) && Near(SpecRootMax, 0.65));
        assert(Near(Wet(0.0f, 0.0f, 2.0f).root, 0.45 * std::sqrt(2.0)) && Wet(0.0f, 0.0f, 2.0f).root < SpecRootMax);
'''),
(r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).gloss, WetGloss));
''',
r'''        assert(Near(Wet(0.0f, 0.0f, 4.0f).gloss, WetGloss));
        // bbport (r100i_sheen-blood-tint): the tint. Intensity kept (f0 = root squared) is red 0.6..0.8 of the
        // untinted film, green and blue far less; red is never lowered; green and blue come down on a pale ground.
        assert(Near(TintR, 0.85, 1e-6) && Near(TintG, 0.35, 1e-6) && Near(TintB, 0.30, 1e-6));
        assert(TintR * TintR >= 0.6f && TintR * TintR <= 0.8f && TintG * TintG < 0.2f && TintB * TintB < 0.2f);
        {
            const SpecRoot s = WetSpec(0.0f, 0.0f, 0.0f, 1.0f);
            assert(Near(s.r, 0.45 * 0.85, 1e-4) && Near(s.g, 0.45 * 0.35, 1e-4) && Near(s.b, 0.45 * 0.30, 1e-4));
            assert(s.r > s.g && s.g >= s.b);
            const SpecRoot s2 = WetSpec(0.0f, 0.0f, 0.0f, 2.0f);        // brighter at strength 2
            assert(s2.r > s.r && s2.g > s.g && Near(s2.r, 0.45 * std::sqrt(2.0) * 0.85, 1e-4));
            const SpecRoot hi = WetSpec(0.7f, 0.5f, 0.5f, 1.0f);        // a bright grey ground: red kept, g and b down
            assert(Near(hi.r, 0.7, 1e-6) && Near(hi.g, 0.45 * 0.35, 1e-4) && Near(hi.b, 0.45 * 0.30, 1e-4));
            const SpecRoot rim = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, 0.5f); // half weight: half the way
            assert(Near(rim.g, 0.2 + (0.45 * 0.35 - 0.2) * 0.5, 1e-4) && rim.r > 0.2f);
            const SpecRoot none = WetSpec(0.2f, 0.2f, 0.2f, 1.0f, 0.0f); // weight 0: untouched
            assert(Near(none.r, 0.2, 1e-6) && Near(none.g, 0.2, 1e-6) && Near(none.b, 0.2, 1e-6));
            assert(Near(WetSpec(0.3f, 0.3f, 0.3f, 0.0f).g, 0.3, 1e-6));    // strength 0: untouched
        }
'''),
],

README: [
(r'''the specular colour's square root raised toward 0.55 (f0 0.30), by the strength, never lowered;''',
 r'''the specular colour's square root raised toward 0.45 (f0 0.20 before the tint), by the strength, and tinted by the blood: its red, green and blue are multiplied by 0.85, 0.35 and 0.30 (a deep red: f0 red 0.146, green 0.025, blue 0.018 at strength 1), so the moon gives a dark red highlight and a torch a warm red-orange one; the red is never lowered, the green and blue go down to the tinted value on the wet pixels;'''),
(r'''at most 0.75); `show`''',
 r'''at most 0.65, then the deep red tint); `show`'''),
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
    for want in ("#define BLOOD_SHEEN_WET_GLOSS 0.86\n", "#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45\n",
                 "#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65\n", "#define BLOOD_SHEEN_TINT_R 0.85\n",
                 "#define BLOOD_SHEEN_TINT_G 0.35\n", "#define BLOOD_SHEEN_TINT_B 0.30\n",
                 "#define BLOOD_SHEEN_RING1 14\n", "#define BLOOD_SHEEN_FILL_MIN_HITS 2\n"):
        need(LAYOUT, lay, want)
    need(LAYOUT, lay, "BLOOD_SHEEN_WET_SPEC_ROOT 0.55", 0)
    need(COMP, comp, "s.r = max(s.r, mix(s.r, target.r, w));")
    need(COMP, comp, "s.gb = mix(s.gb, target.gb, w);")
    need(COMP, comp, "vec3(root));", 0)
    need(COMP, comp, "int RingHits(ivec2 p, int ring)")
    need(COMP, comp, "barrier()", 2)  # the counter code's two only
    need(RULES, hdr, "BLOOD_SHEEN_WET_SPEC_ROOT == 0.45")
    need(RULES, hdr, "inline SpecRoot WetSpec(")
    need(RULES, hdr, "inline float FillWeight(float pool_share, float up, int near_hits)")
    need(SHEEN, cpp, "Blood sheen (r100i): the film's specular is tinted")
    need(SHEEN, cpp, "Blood sheen (r100h): the film also levels")
    need(TEST, tst, "WetSpec(0.0f, 0.0f, 0.0f, 1.0f)")
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
