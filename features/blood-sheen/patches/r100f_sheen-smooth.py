# r100f_sheen-smooth: FEATURE fix on top of r100e_blood-sheen-visible (branch visual/blood-sheen).
# Applies ON TOP of r100e (refuses a tree without it). Off by default: BB_BLOOD_SHEEN unset makes no
# BloodSheen, so nothing of this runs and the frame stays bit-identical (r100d's null pointer test per hook).
#
# Why r100e's highlights were square patches (build 30, graveyard-blood, 107055 px made wet, pictures
# slot_r100e-gbab_on1/on2): the EDIT pass pulled each picked pixel's normal 85% of the way to the mean
# normal of the picked pixels of its own 8x8 workgroup. Every block therefore got ONE normal and, with the
# sharp lobe (gloss 0.82, exponent 1660), one highlight value: blocks whose mirror direction met the moon
# or a torch flashed, their neighbours did not: a regular grid of 8x8 to 16x16 squares.
# What this patch changes (EDIT pass only; no new pass, no new image, no new memory):
#  - NO per-group flattening. A picked pixel's unit normal goes toward the world UP vector (0, 1, 0: the
#    world is Y up, as the footprints and SSGI passes read it) by BLOOD_SHEEN_NORMAL_SMOOTH (0.93, was 0.85)
#    x the strength (at most 1) x a per-pixel weight smoothstep(0.6, 0.9, normal.y): a liquid film lies
#    level, and a pixel that does not face up already (a wall, a step edge, a splash on a stone) is left
#    alone, softly, with no threshold. The result is a continuous function of the pixel's own normal and
#    of nothing else: no block, no neighbour, no group edge can show. The pool becomes one level mirror
#    surface; its highlights are the sheets of the moon's and the torches' reflection, shaped by the pool
#    mask. Fail-safe: if the normal target were not world Y up, the weight stays near 0 on the ground and
#    the film shows the cobbles' speckle (r100d's look), never blocks.
#  - the shared memory and both barriers of r100e are gone (the EDIT pass is cheaper than r100e's).
#  - the film's gloss stays 0.82 (exponent 1660): on a level surface the lobe is a sheet, not a speckle;
#    if the owner finds the highlights too sharp, BLOOD_SHEEN_WET_GLOSS is the one number to lower.
#
# Cost: EDIT is cheaper than r100e (no shared memory, no barrier, no 64-term sum); one extra normalize and
# smoothstep per picked pixel. Estimate, not measured: below 0.03 ms at 1080p internal. No new memory.
#
# Files (anchored edits on r100e's text; each edit must be found exactly once): host_shaders/
# blood_sheen_layout.h, blood_sheen.comp, renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp (one log
# text), tests/test_blood_sheen.cpp, README.md. CMakeLists.txt and build.sh need no edit.
#
# Use: python -I -X utf8 r100f_sheen-smooth.py check | apply | revert. Root from R100F_ROOT, else
# <tree>. Line ends kept; apply keeps the originals in r100f_sheen-smooth_backup/ next to this
# script; a mixed state is refused and nothing is written. Revert order: this script, then r100e.
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "r100f_sheen-smooth"
BASE = "r100e_blood-sheen-visible.py"
ROOT_ENV = "R100F_ROOT"
ROOT = os.environ.get(ROOT_ENV) or "<tree>"
BACKUP = os.path.join(HERE, NAME + "_backup")
TMP = ".r100ftmp"
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
(r'''// EDIT, the normal (target 0, xyz*2-1): a picked pixel's unit normal goes this share (times the
// strength, at most 1) of the way to the mean normal of the picked pixels of its group (one 8x8
// workgroup), where the group has at least BLOOD_SHEEN_NORMAL_MIN of them and the mean vector's length
// is at least BLOOD_SHEEN_NORMAL_COHERENT of their count (else a slab edge or a step is in the group).
#define BLOOD_SHEEN_NORMAL_SMOOTH 0.85
#define BLOOD_SHEEN_NORMAL_MIN 8.0
#define BLOOD_SHEEN_NORMAL_COHERENT 0.5
''',
r'''// EDIT, the normal (target 0, xyz*2-1, world space, Y up): a picked pixel's unit normal goes this share
// (times the strength, at most 1, times smoothstep(UP_LO, UP_HI, its own normal.y)) of the way to the
// world up vector: a liquid film lies level. The weight is a function of the pixel's own normal only,
// so no group, block or neighbour shows in it (r100f_sheen-smooth; r100e flattened toward the mean of
// each 8x8 workgroup and left a square highlight per block).
#define BLOOD_SHEEN_NORMAL_SMOOTH 0.93
#define BLOOD_SHEEN_NORMAL_UP_LO 0.6
#define BLOOD_SHEEN_NORMAL_UP_HI 0.9
'''),
],

COMP: [
(r'''// The picked pixels' unit normals of the group, and their sum (w: how many). r100e_blood-sheen-visible.
shared vec4 group_normal[BLOOD_SHEEN_GROUP * BLOOD_SHEEN_GROUP];
shared vec4 group_mean;
''',
r'''// r100f_sheen-smooth: the normal is levelled per pixel; nothing is shared between pixels or groups.
'''),
(r'''    // The picked pixels' mean normal of this group (the flag is a push constant: every invocation
    // takes the barriers or none does).
    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;
    vec4 normal = vec4(0.0);
    if (do_normal) {
        vec4 mine = vec4(0.0);
        if (picked) {
            normal = imageLoad(normal_img, p);
            const vec3 n = normal.xyz * 2.0 - 1.0;
            const float len = length(n);
            if (len > 0.5) {
                mine = vec4(n / len, 1.0);
            }
        }
        group_normal[gl_LocalInvocationIndex] = mine;
        memoryBarrierShared();
        barrier();
        if (gl_LocalInvocationIndex == 0u) {
            vec4 sum = vec4(0.0);
            for (uint i = 0u; i < BLOOD_SHEEN_GROUP * BLOOD_SHEEN_GROUP; ++i) {
                sum += group_normal[i];
            }
            group_mean = sum;
        }
        memoryBarrierShared();
        barrier();
    }
''',
r'''    // The normal flag (a push constant). r100f_sheen-smooth: no barrier, no shared memory, no group mean.
    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;
'''),
(r'''            if (do_normal && group_mean.w >= BLOOD_SHEEN_NORMAL_MIN) {
                const float mean_len = length(group_mean.xyz);
                const vec3 n = normal.xyz * 2.0 - 1.0;
                const float len = length(n);
                if (len > 0.5 && mean_len >= BLOOD_SHEEN_NORMAL_COHERENT * group_mean.w) {
                    const vec3 flat_n = normalize(mix(n / len, group_mean.xyz / mean_len, BLOOD_SHEEN_NORMAL_SMOOTH * w));
                    imageStore(normal_img, p, vec4(flat_n * 0.5 + 0.5, normal.a)); // .a as it was
                }
            }
''',
r'''            if (do_normal) {
                // A liquid film lies level: toward world up, weighted by how much the pixel faces up
                // already (a continuous function of this pixel's own normal: no block can show).
                const vec4 normal = imageLoad(normal_img, p);
                const vec3 n = normal.xyz * 2.0 - 1.0;
                const float len = length(n);
                if (len > 0.5) {
                    const vec3 unit = n / len;
                    const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *
                                        smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y);
                    const vec3 flat_n = normalize(mix(unit, vec3(0.0, 1.0, 0.0), level));
                    imageStore(normal_img, p, vec4(flat_n * 0.5 + 0.5, normal.a)); // .a as it was
                }
            }
'''),
],

RULES: [
(r'''static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 0.85 && BLOOD_SHEEN_NORMAL_MIN == 8.0 && BLOOD_SHEEN_NORMAL_COHERENT == 0.5);
''',
r'''static_assert(BLOOD_SHEEN_NORMAL_SMOOTH == 0.93 && BLOOD_SHEEN_NORMAL_UP_LO == 0.6 && BLOOD_SHEEN_NORMAL_UP_HI == 0.9);
// bbport (r100f_sheen-smooth): the share of the way to world up that a picked pixel whose unit normal has
// the y component `up` goes, at film strength `strength` (the shader's arithmetic: it depends on nothing
// but the pixel's own normal, so no block of the picture can show in it).
inline float LevelShare(float up, float strength) {
    const float t = std::clamp((up - float(BLOOD_SHEEN_NORMAL_UP_LO)) /
                                   float(BLOOD_SHEEN_NORMAL_UP_HI - BLOOD_SHEEN_NORMAL_UP_LO),
                               0.0f, 1.0f);
    return NormalSmooth * std::clamp(strength, 0.0f, 1.0f) * (t * t * (3.0f - 2.0f * t));
}
'''),
],

SHEEN: [
(r'''    BbReport::Printf("Blood sheen (r100e): the film also flattens the normal toward the mean of the picked pixels "
                     "of an 8x8 block (weight %.2f) and, after the lighting, dims and reddens the picked pixels' "
''',
r'''    BbReport::Printf("Blood sheen (r100f): the film also levels the normal toward world up, per pixel and only "
                     "where it faces up already (largest weight %.2f) and, after the lighting, dims and reddens the picked pixels' "
'''),
],

TEST: [
(r'''        assert((FlagNormal & (FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear)) == 0u);
''',
r'''        assert((FlagNormal & (FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear)) == 0u);
        // h. bbport (r100f_sheen-smooth): the level share is per pixel, from its own normal only.
        assert(Near(LevelShare(1.0f, 1.0f), 0.93) && Near(LevelShare(0.9f, 1.0f), 0.93));
        assert(LevelShare(0.6f, 1.0f) == 0.0f && LevelShare(0.0f, 1.0f) == 0.0f && LevelShare(-1.0f, 1.0f) == 0.0f);
        assert(Near(LevelShare(0.75f, 1.0f), 0.93 * 0.5));          // smoothstep's middle
        assert(Near(LevelShare(1.0f, 0.5f), 0.465) && Near(LevelShare(1.0f, 3.0f), 0.93) && LevelShare(1.0f, 0.0f) == 0.0f);
        for (float y = 0.0f; y < 1.0f; y += 0.01f) { // never decreases as the pixel faces up more
            assert(LevelShare(y + 0.01f, 1.0f) >= LevelShare(y, 1.0f));
        }
'''),
],

README: [
(r'''the pixel's normal also goes 85% of the way, times the strength (at most 1), to the mean normal of the picked pixels of its 8x8 block when the block holds at least 8 of them and their normals agree, so the film is a smooth surface and its highlights are sheets, not the speckle of the cobbles' bumps)''',
 r'''the pixel's normal also goes 93% of the way, times the strength (at most 1), to world up, weighted by how much that pixel's own normal faces up already (none below 0.6, all above 0.9), so the film is a level surface and its highlights are smooth sheets, not the speckle of the cobbles' bumps; the weight comes from the pixel alone, so no block or neighbour shows in it)'''),
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
    for gone in ("group_normal", "group_mean", "BLOOD_SHEEN_NORMAL_MIN", "BLOOD_SHEEN_NORMAL_COHERENT"):
        need(COMP, comp, gone, 0)
    for gone in ("BLOOD_SHEEN_NORMAL_MIN", "BLOOD_SHEEN_NORMAL_COHERENT"):
        need(LAYOUT, lay, gone, 0)
        need(RULES, hdr, gone, 0)
    need(LAYOUT, lay, "#define BLOOD_SHEEN_NORMAL_SMOOTH 0.93\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_NORMAL_UP_LO 0.6\n")
    need(LAYOUT, lay, "#define BLOOD_SHEEN_NORMAL_UP_HI 0.9\n")
    need(COMP, comp, "barrier()", 2)  # the counter code's two; r100e's four in the normal block are gone
    need(COMP, comp, "smoothstep(BLOOD_SHEEN_NORMAL_UP_LO, BLOOD_SHEEN_NORMAL_UP_HI, unit.y)")
    need(RULES, hdr, "BLOOD_SHEEN_NORMAL_UP_LO == 0.6 && BLOOD_SHEEN_NORMAL_UP_HI == 0.9")
    need(SHEEN, cpp, "8x8", 0)
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
