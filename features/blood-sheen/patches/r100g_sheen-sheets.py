# r100g_sheen-sheets: FEATURE fix on top of r100f_sheen-smooth (r100e, r100d; branch visual/blood-sheen).
# Applies ON TOP of r100f (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset makes no
# BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test per hook).
#
# Why r100f's highlights were still fine speckle (build 35, graveyard-blood, pictures _rd_ab_off1/_rd_ab_on1):
# r100f pulled a picked pixel's normal only 93% of the way to world up, and only where the pixel already faced
# up (smoothstep 0.6..0.9 of normal.y). The film's lobe is sharp (gloss 0.82, exponent 1660, about 1.4 degrees
# wide): a cobble bump tilted 20 degrees keeps 7% of its tilt (1.4 degrees), which moves the mirror direction by
# 2.8 degrees, twice the lobe: the moon and the torches still hit or missed per bump. Bumps tilted past 26
# degrees were not touched at all.
# What this patch changes (EDIT pass only; no new pass, no new image, no new memory):
#  - the normal goes ALL the way (weight 1.0 at strength 1; the strength still scales it below 1) to world up
#    inside the pool: weight = strength x mix(EDGE 0.3, 1, cover) x smoothstep(0.35, 0.6, normal.y). `cover` is
#    smoothstep(0.45, 0.95, f) where f is the share of 16 taps around the pixel (8 directions at 4 px and 8 at
#    10 px, scaled by height/1080) whose ALBEDO passes the dark red rule (the albedo target is not written by
#    this pass: no race, no group, no block). Deep in the pool f = 1: an exactly level surface, so the moon and
#    the torches give broad continuous sheets; at the pool's edge f falls to about 0.5: the weight falls to
#    EDGE (0.3), so the edge still follows the stones. Without the albedo rule (draw key only) cover is 1.
#    The up gate is wider (0.35..0.6, was 0.6..0.9): a bump on the pool's floor is levelled, a wall or a
#    step's side (normal.y below 0.35) is not.
#  - gloss 0.82 -> 0.86 (exponent 2^(13 g): 1660 -> 2320, a stronger peak) and specular root 0.3 -> 0.45
#    (f0 0.09 -> 0.20), root cap 0.55 -> 0.65 (strength 2: 0.45 x sqrt 2 = 0.64; strength 4: 0.65): a wet film
#    of dark blood reflects more than the dry cobble. A TRADE: on a level surface a higher gloss makes each
#    sheet more concentrated (a narrower lobe), a lower one broader; BLOOD_SHEEN_WET_GLOSS is the one number to
#    lower if the owner finds the sheets too narrow.
#  - dry cobbles (not picked) and the dream house (nothing picked) are untouched.
#
# Cost: EDIT only, for PICKED pixels with the normal flag: 16 more albedo texel fetches and a few ALU ops each
# (about 100000 to 300000 picked pixels at the graveyard). Estimate, not measured: below 0.05 ms at 1080p
# internal. No new memory, no new pass, no new counter word.
#
# Files (anchored edits on r100f's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp (one log text),
# tests/test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit.
#
# Use: python -I -X utf8 r100g_sheen-sheets.py check | apply | revert. Root from R100G_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100g_sheen-sheets_backup/ next to this
# script; a mixed state is refused and nothing is written. Revert order: this script, then r100f.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100g_sheen-sheets"
BASE = "r100f_sheen-smooth.py"
ROOT_ENV = "R100G_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100gtmp"
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
(r'''#define BLOOD_SHEEN_WET_GLOSS 0.82
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.3
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.55
''',
r'''// r100g_sheen-sheets: gloss 0.86 (exponent 1660 -> 2320), root 0.45 (f0 0.20 at strength 1), cap 0.65
// (the numbers above name r100e's 0.82 and 0.3).
#define BLOOD_SHEEN_WET_GLOSS 0.86
#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45
#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65
'''),
(r'''#define BLOOD_SHEEN_NORMAL_SMOOTH 0.93
#define BLOOD_SHEEN_NORMAL_UP_LO 0.6
#define BLOOD_SHEEN_NORMAL_UP_HI 0.9
''',
r'''// r100g_sheen-sheets: the pixel goes ALL the way (SMOOTH 1.0) where the pool's dark red covers its
// surroundings (cover: the share of 16 taps, 8 directions at NEAR and 8 at FAR pixels at 1080p, scaled by
// height/1080, whose albedo is dark red; cover = smoothstep(COVER_LO, COVER_HI, share)); the weight is
// mix(EDGE, 1, cover) at the pool's edge so the edge follows the stones; the up gate is 0.35..0.6.
#define BLOOD_SHEEN_NORMAL_SMOOTH 1.0
#define BLOOD_SHEEN_NORMAL_UP_LO 0.35
#define BLOOD_SHEEN_NORMAL_UP_HI 0.6
#define BLOOD_SHEEN_NORMAL_EDGE 0.3
#define BLOOD_SHEEN_COVER_LO 0.45
#define BLOOD_SHEEN_COVER_HI 0.95
#define BLOOD_SHEEN_COVER_NEAR 4
#define BLOOD_SHEEN_COVER_FAR 10
'''),
],

COMP: [
(r'''// r100f_sheen-smooth: the normal is levelled per pixel; nothing is shared between pixels or groups.
''',
r'''// r100f_sheen-smooth: the normal is levelled per pixel; nothing is shared between pixels or groups.
// r100g_sheen-sheets: how much of the pixel's surroundings is dark red (the pool): the share of 16 taps,
// 8 directions at NEAR and 8 at FAR pixels (1080p; scaled by height/1080), whose albedo passes DarkRed.
// The albedo target is read only in this pass, so the taps race with nothing.
float PoolShare(ivec2 p) {
    const float scale = size.y / 1080.0;
    const ivec2 hi = ivec2(size) - ivec2(1);
    const ivec2 dirs[8] = ivec2[8](ivec2(1, 0), ivec2(1, 1), ivec2(0, 1), ivec2(-1, 1),
                                   ivec2(-1, 0), ivec2(-1, -1), ivec2(0, -1), ivec2(1, -1));
    int radii[2];
    radii[0] = max(1, int(float(BLOOD_SHEEN_COVER_NEAR) * scale + 0.5));
    radii[1] = max(1, int(float(BLOOD_SHEEN_COVER_FAR) * scale + 0.5));
    float hit = 0.0;
    for (int r = 0; r < 2; ++r) {
        for (int d = 0; d < 8; ++d) {
            const ivec2 q = clamp(p + dirs[d] * radii[r], ivec2(0), hi);
            hit += DarkRed(texelFetch(albedo_tex, q, 0).rgb) ? 1.0 : 0.0;
        }
    }
    return hit * (1.0 / 16.0);
}
'''),
(r'''                    const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *
                                        smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);
''',
r'''                    // r100g_sheen-sheets: all the way inside the pool, EDGE at its rim (a draw key without
                    // the albedo rule has no rim to find: cover 1).
                    const float cover = (flags & BLOOD_SHEEN_FLAG_RULE_ALBEDO) != 0u
                        ? smoothstep(BLOOD_SHEEN_COVER_LO, BLOOD_SHEEN_COVER_HI, PoolShare(p)) : 1.0;
                    const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w * mix(BLOOD_SHEEN_NORMAL_EDGE, 1.0, cover) *
                                        smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);
'''),
],

RULES: [
(r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.82 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.3 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.55);
''',
r'''static_assert(BLOOD_SHEEN_WET_GLOSS == 0.86 && BLOOD_SHEEN_WET_SPEC_ROOT == 0.45 && BLOOD_SHEEN_SPEC_ROOT_MAX == 0.65);
'''),
(r'''static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 0.93 && BLOOD_SHEEN_NORMAL_UP_LO == 0.6 && BLOOD_SHEEN_NORMAL_UP_HI == 0.9);
// bbport (r100f_sheen-smooth): the share of the way to world up that a picked pixel whose unit normal has
// the y component `up` goes, at film strength `strength` (the shader's arithmetic: it depends on nothing
// but the pixel's own normal, so no block of the picture can show in it).
inline float LevelShare(float up, float strength) {
    const float t = std::clamp((up - float(BLOOD_SHEEN_NORMAL_UP_LO)) /
                                   float(BLOOD_SHEEN_NORMAL_UP_HI - BLOOD_SHEEN_NORMAL_UP_LO),
                               0.0f, 1.0f);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * (t * t * (3.0f - 2.0f * t));
}
''',
r'''static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 1.0 && BLOOD_SHEEN_NORMAL_UP_LO == 0.35 && BLOOD_SHEEN_NORMAL_UP_HI == 0.6);
static_assert(BLOOD_SHEEN_NORMAL_EDGE == 0.3 && BLOOD_SHEEN_COVER_LO == 0.45 && BLOOD_SHEEN_COVER_HI == 0.95);
static_assert(BLOOD_SHEEN_COVER_NEAR == 4 && BLOOD_SHEEN_COVER_FAR == 10);
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
'''),
],

SHEEN: [
(r'''    BbReport::Printf("Blood sheen (r100f): the film also levels the normal toward world up, per pixel and only "
                     "where it faces up already (largest weight %.2f) and, after the lighting, dims and reddens the picked pixels' "
                     "dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
                     double(R::NormalSmooth * std::min(k.strength, 1.0f)), double(k.darken),
''',
r'''    BbReport::Printf("Blood sheen (r100g): the film also levels the normal to world up, per pixel: all the way "
                     "inside the pool, weight %.2f at its rim (largest weight %.2f; gloss %.2f), and, after the "
                     "lighting, dims and reddens the picked pixels' dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
                     double(R::NormalEdge * std::min(k.strength, 1.0f)),
                     double(R::NormalSmooth * std::min(k.strength, 1.0f)), double(R::WetGloss), double(k.darken),
'''),
],

TEST: [
(r'''    // e. The wet film: never lowered; strength 1 reaches gloss 0.82 and root 0.3; above 1 the root
    // grows with the square root, at most 0.55; below 1 a share of the way.
''',
r'''    // e. The wet film: never lowered; strength 1 reaches gloss 0.86 and root 0.45; above 1 the root
    // grows with the square root, at most 0.65; below 1 a share of the way.
'''),
(r'''        assert(Near(half.gloss, 0.56) && Near(half.root, 0.2));
''',
r'''        assert(Near(half.gloss, 0.58) && Near(half.root, 0.275));
'''),
(r'''        assert(Near(WetGloss, 0.82) && Near(WetSpecRoot, 0.3) && Near(SpecRootMax, 0.55));
''',
r'''        assert(Near(WetGloss, 0.86) && Near(WetSpecRoot, 0.45) && Near(SpecRootMax, 0.65));
        assert(Near(Wet(0.0f, 0.0f, 2.0f).root, 0.45 * std::sqrt(2.0)) && Wet(0.0f, 0.0f, 2.0f).root < SpecRootMax);
'''),
(r'''        // h. bbport (r100f_sheen-smooth): the level share is per pixel, from its own normal only.
        assert(Near(LevelShare(1.0f, 1.0f), 0.93) && Near(LevelShare(0.9f, 1.0f), 0.93));
        assert(LevelShare(0.6f, 1.0f) == 0.0f && LevelShare(0.0f, 1.0f) == 0.0f && LevelShare(-1.0f, 1.0f) == 0.0f);
        assert(Near(LevelShare(0.75f, 1.0f), 0.93 * 0.5));          // smoothstep's middle
        assert(Near(LevelShare(1.0f, 0.5f), 0.465) && Near(LevelShare(1.0f, 3.0f), 0.93) && LevelShare(1.0f, 0.0f) == 0.0f);
        for (float y = 0.0f; y < 1.0f; y += 0.01f) { // never decreases as the pixel faces up more
            assert(LevelShare(y + 0.01f, 1.0f) >= LevelShare(y, 1.0f));
        }
''',
r'''        // h. bbport (r100g_sheen-sheets): the level share: all the way (1) deep in the pool, EDGE (0.3) at its
        // rim, none for a pixel that does not face up (a wall); the strength scales it up to 1.
        assert(Near(LevelShare(1.0f, 1.0f, 1.0f), 1.0) && Near(LevelShare(0.6f, 1.0f, 1.0f), 1.0));
        assert(LevelShare(0.35f, 1.0f, 1.0f) == 0.0f && LevelShare(0.0f, 1.0f, 1.0f) == 0.0f && LevelShare(-1.0f, 1.0f, 1.0f) == 0.0f);
        assert(Near(LevelShare(0.475f, 1.0f, 1.0f), 0.5));                 // the up gate's middle
        assert(Near(LevelShare(1.0f, 0.0f, 1.0f), 0.3) && Near(LevelShare(1.0f, 0.45f, 1.0f), 0.3));
        assert(Near(LevelShare(1.0f, 0.95f, 1.0f), 1.0) && Near(LevelShare(1.0f, 0.7f, 1.0f), 0.3 + 0.7 * 0.5));
        assert(Near(LevelShare(1.0f, 1.0f, 0.5f), 0.5) && Near(LevelShare(1.0f, 1.0f, 3.0f), 1.0));
        assert(LevelShare(1.0f, 1.0f, 0.0f) == 0.0f);
        for (float y = 0.0f; y < 1.0f; y += 0.01f) { // never decreases as the pixel faces up more
            assert(LevelShare(y + 0.01f, 0.8f, 1.0f) >= LevelShare(y, 0.8f, 1.0f));
        }
        for (float f = 0.0f; f < 1.0f; f += 0.01f) { // never decreases as more of its surroundings is pool
            assert(LevelShare(1.0f, f + 0.01f, 1.0f) >= LevelShare(1.0f, f, 1.0f));
        }
'''),
],

README: [
(r'''gloss raised toward 0.82, the specular colour's square root toward 0.3 (f0 0.09), by the strength;''',
 r'''gloss raised toward 0.86, the specular colour's square root toward 0.45 (f0 0.20), by the strength;'''),
(r'''the pixel's normal also goes 93% of the way, times the strength (at most 1), to world up, weighted by how much that pixel's own normal faces up already (none below 0.6, all above 0.9), so the film is a level surface and its highlights are smooth sheets, not the speckle of the cobbles' bumps; the weight comes from the pixel alone, so no block or neighbour shows in it)''',
 r'''the pixel's normal also goes all the way, times the strength (at most 1), to world up inside the pool (the share of 16 taps around the pixel, 4 and 10 pixels out at 1080p, whose albedo is dark red is at least 0.95; the weight falls to 0.3 where it is 0.45 or less, at the pool's rim, so the rim follows the stones; with a draw key and no albedo rule there is no rim), weighted by how much the pixel's own normal faces up (none below 0.35, all above 0.6), so the film is a level surface and its highlights are smooth sheets, not the speckle of the cobbles' bumps; the weight comes from the pixel and fixed taps of the albedo, which this pass does not write, so no block shows in it; 16 more texel fetches for each picked pixel)'''),
(r'''at most 0.55); `show`''',
 r'''at most 0.65); `show`'''),
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
    comp, lay, hdr, cpp = t[COMP], t[LAYOUT], t[RULES], t[SHEEN]
    for want in ("#define BLOOD_SHEEN_WET_GLOSS 0.86\n", "#define BLOOD_SHEEN_WET_SPEC_ROOT 0.45\n",
                 "#define BLOOD_SHEEN_SPEC_ROOT_MAX 0.65\n", "#define BLOOD_SHEEN_NORMAL_SMOOTH 1.0\n",
                 "#define BLOOD_SHEEN_NORMAL_UP_LO 0.35\n", "#define BLOOD_SHEEN_NORMAL_UP_HI 0.6\n",
                 "#define BLOOD_SHEEN_NORMAL_EDGE 0.3\n", "#define BLOOD_SHEEN_COVER_LO 0.45\n",
                 "#define BLOOD_SHEEN_COVER_HI 0.95\n", "#define BLOOD_SHEEN_COVER_NEAR 4\n",
                 "#define BLOOD_SHEEN_COVER_FAR 10\n"):
        need(LAYOUT, lay, want)
    need(COMP, comp, "float PoolShare(ivec2 p)")
    need(COMP, comp, "PoolShare(p)")  # the definition has "PoolShare(ivec2 p)": this counts the one call
    need(COMP, comp, "mix(BLOOD_SHEEN_NORMAL_EDGE, 1.0, cover)")
    need(COMP, comp, "barrier()", 2)  # the counter code's two only
    need(RULES, hdr, "inline float LevelShare(float up, float pool_share, float strength)")
    need(RULES, hdr, "BLOOD_SHEEN_WET_GLOSS == 0.86")
    need(SHEEN, cpp, "Blood sheen (r100g): the film also levels")
    need(SHEEN, cpp, "Blood sheen (r100f)", 0)
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
