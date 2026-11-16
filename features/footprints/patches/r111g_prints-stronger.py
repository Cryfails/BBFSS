# r111g_prints-stronger: FEATURE fix on top of r111 to r111f (b43: the prints are placed and drawn; the graveyard shows
# small dark red boot prints 3-5 m away, the church wet prints show as pale bright grey shapes on the glossy floor,
# the r111c line's "read-backs ... 0 of them with print pixels" counts the G-buffer band and says 0 while the
# post stamp stamped 2000+ px, and only 5 of the 7 prints were in frame). Still off unless BB_FOOTPRINTS is set and
# still costs nothing when off (every edit is inside Footprints, which is not made without the knob, or inside the
# two shaders of its passes). Branch: visual/footprints.
# Owner (2026-11-15): "the grave yard doesn't have a bloody coat just blood on the ground" (the prints come from
# the blood on the ground).
#
# WHAT CHANGES
#  (1) Blood prints stronger and boot-shaped at the default (footprints_layout.h, footprints_flat.comp): the post
#      stamp recolours the lit pixel to a deeper, more saturated red (tint 3.90 0.22 0.19, luminance 1.0002, was
#      3.272 0.393 0.327: red share 94%, was 88%) at 0.70 of the pixel's own luminance (was 1.00: darker than the
#      stone, so the print is a dark red mark, not a recoloured one), cover 95% (was 85%), and the print's weight
#      is rounded 1 - (1 - w)^2 (a faded print, 0.42 at the trail's tail, reads 0.66; the full ones stay 1; the
#      sole's edge widens by a few mm): the boot's outline reads at 3 to 5 m. The fade over the trail is the coat's
#      (r111d: 4 full prints, then 0.75, 0.56, 0.42 ...: the first prints, at the pool, are the strongest); it is
#      unchanged and now has a unit test for its order.
#  (2) Wet prints darken the stone and add no light (footprints.comp, footprints_layout.h): the G-buffer change of a
#      wet print is the albedo multiply only (no gloss raised toward 0.8, no specular colour raised: on the church's
#      glossy floor both made the print a pale bright shape); the post stamp's darken of a wet or mud print 40%
#      (was 25%) so it reads at a distance. Blood keeps its gloss.
#  (3) The r111c line's print pixel counter counts the post stamp's pixels too (vk_footprints.cpp): the read-back
#      of the post stamp adds its frame and its pixels to "frames with print pixels (G-buffer band or post stamp),
#      the most N px"; and a new line once, early: "Footprints (r111g): first post stamp read back at frame N: X
#      stamped px, P prints on the pass, camera ..." (a zero copy of it comes at construction so the slot runner,
#      which keeps the first 30 feature lines, has the kind) plus a look line once at the start.
#  (4) The jobs' camera: after the turn the capture is taken at two framings (A as b43; B: a further 0.2 s tilt
#      down and 0.1 s turn right, so the trail's end under the hunter and its far end beyond the right edge come
#      into the picture); the flat view's markers say how many of the 7 prints are in frame.
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made, its
# hook is one null pointer test, and nothing here is reached. The shader changes run only inside the existing
# passes (the G-buffer pass has fewer instructions for a wet print, the post stamp two more ALU ops for a blood
# pixel). Memory: none added (one bool). GPU cost: no measurable change (a handful of ALU ops on the pixels of a
# print's box).
#
# Files edited (the text r111f left; each old text found exactly once): footprints_layout.h, footprints.comp,
# footprints_flat.comp, footprints.h (two comment lines), vk_footprints.h, vk_footprints.cpp,
# engine/tests/test_footprints.cpp, README.md (rows BB_FOOTPRINTS and BB_FOOTPRINTS_POST).
#
# Order: needs r111f applied (refused otherwise). To take r111f out, revert r111g first.
# Use: python -I -X utf8 r111g_prints-stronger.py check | apply | revert
# Root: R111G_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111g_backup next to this script; revert puts each old text back (each new text found by itself, exactly once).
import os, re, sys

ROOT = os.environ.get("R111G_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111g_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
GBUF = HS + "footprints.comp"
FLAT = HS + "footprints_flat.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, GBUF, FLAT, RULES, VKH, VKC, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_POST_WET_DARKEN 0.25
#define FOOTPRINTS_POST_BLOOD_TINT_R 3.272
#define FOOTPRINTS_POST_BLOOD_TINT_G 0.393
#define FOOTPRINTS_POST_BLOOD_TINT_B 0.327
#define FOOTPRINTS_POST_BLOOD_LUM 1.0
#define FOOTPRINTS_POST_BLOOD_COVER 0.85
''',
         r'''// (r111g) Stronger at the default: a wet or mud print darkens the lit pixel 40% (was 25%); the blood tint is a
// deeper, more saturated red (3.90 0.22 0.19, luminance 1.0002; was 3.272 0.393 0.327), laid at 0.70 of the pixel's
// own luminance (was 1.00: a dark red mark on the stone, not a recoloured one), cover 95% (was 85%).
#define FOOTPRINTS_POST_WET_DARKEN 0.40
#define FOOTPRINTS_POST_BLOOD_TINT_R 3.90
#define FOOTPRINTS_POST_BLOOD_TINT_G 0.22
#define FOOTPRINTS_POST_BLOOD_TINT_B 0.19
#define FOOTPRINTS_POST_BLOOD_LUM 0.70
#define FOOTPRINTS_POST_BLOOD_COVER 0.95
'''),
    ],
    GBUF: [
        (r'''                if (wet > 0.0) {
                    a.rgb *= 1.0 - FOOTPRINTS_WET_DARKEN * wet;
                    m.r = max(m.r, mix(m.r, FOOTPRINTS_WET_GLOSS, wet));
                    s.rgb = max(s.rgb, mix(s.rgb, vec3(FOOTPRINTS_WET_SPEC_ROOT), wet));
                }
''',
         r'''                if (wet > 0.0) {
                    // (r111g) darkens the stone only: no gloss and no specular colour are added (on a glossy
                    // floor they made the wet print a pale bright shape instead of a darker one)
                    a.rgb *= 1.0 - FOOTPRINTS_WET_DARKEN * wet;
                }
'''),
    ],
    FLAT: [
        (r'''    const float blood = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * gain, 0.0, 1.0);
    if (max(wet, max(mud, blood)) <= 1.0 / 64.0) {
''',
         r'''    // (r111g) the blood weight is rounded, 1 - (1 - w)^2: the full prints stay 1, a faded one (0.42 at the tail
    // of a trail) reads 0.66, and the sole's soft edge is a little firmer: the boot's outline reads at 3 to 5 m
    const float blood_w = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * gain, 0.0, 1.0);
    const float blood = 1.0 - (1.0 - blood_w) * (1.0 - blood_w);
    if (max(wet, max(mud, blood)) <= 1.0 / 64.0) {
'''),
    ],
    RULES: [
        (r'''//                       luminance, wet and mud darkened a further 25%); 0: the G-buffer change alone (Post()).
''',
         r'''//                       luminance, wet and mud darkened a further 40%, r111g); 0: the G-buffer change alone (Post()).
'''),
        (r'''a wet print darkens the albedo by up to 65%, gloss 0.8; the sole is a
''',
         r'''a wet print darkens the albedo by up to 65% (r111g: no gloss or specular added); the sole is a
'''),
    ],
    VKH: [
        (r'''        u32 told = 0;         ///< probes told, at most FlatProbeMax
''',
         r'''        u32 told = 0;         ///< probes told, at most FlatProbeMax
        bool told_stamp = false; ///< (r111g) the first stamped pixels were told
'''),
        (r'''    void LogFlat() const;
''',
         r'''    void LogFlat() const;
    void LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const; // (r111g)
'''),
    ],
    VKC: [
        (r'''        LogFlat();
    }
    if (!camera_motion.Enabled()) {
''',
         r'''        LogFlat();
        LogStamp(0, 0, 0, std::array<float, 3>{}); // (r111g)
    }
    BbReport::Printf("Footprints (r111g): look: blood prints dark red at %.2f of the lit luminance (tint %.2f %.2f %.2f, "
                     "cover %.0f%%, weight 1 - (1 - w)^2); wet prints darken the stone %.0f%% (G-buffer) and %.0f%% "
                     "(post), no gloss or specular added\n",
                     double(FOOTPRINTS_POST_BLOOD_LUM), double(FOOTPRINTS_POST_BLOOD_TINT_R),
                     double(FOOTPRINTS_POST_BLOOD_TINT_G), double(FOOTPRINTS_POST_BLOOD_TINT_B),
                     double(FOOTPRINTS_POST_BLOOD_COVER) * 100.0, double(FOOTPRINTS_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_POST_WET_DARKEN) * 100.0);
    if (!camera_motion.Enabled()) {
'''),
        (r'''void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
''',
         r'''/// (r111g) Told once, when the first post stamp's pixels are read back (a zero copy at construction).
void Footprints::LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const {
    BbReport::Printf("Footprints (r111g): first post stamp read back at frame %llu: %u stamped px, %u prints on "
                     "the pass, camera %.1f %.1f %.1f\n",
                     static_cast<unsigned long long>(at_frame), px, prints, double(cam[0]), double(cam[1]),
                     double(cam[2]));
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
'''),
        (r'''    ++flat.read_back;
    flat.groups_ok += counts[R::WordFlatGroups] == snap.groups ? 1u : 0u;
''',
         r'''    ++flat.read_back;
    flat.groups_ok += counts[R::WordFlatGroups] == snap.groups ? 1u : 0u;
    { // (r111g) the post stamp's pixels are print pixels too (the r111c counter had the G-buffer band only)
        const u32 px = counts[R::WordFlatPostPx];
        stats.print_px_frames += px != 0u ? 1u : 0u;
        stats.print_px_max = std::max(stats.print_px_max, px);
        if (px != 0u && !flat_probe.told_stamp) {
            flat_probe.told_stamp = true;
            LogStamp(frame, px, snap.count, snap.camera);
        }
    }
'''),
        (r'''"from the camera, the largest box %d x %d px; read-backs %u, %u of them with print pixels, "
                     "the most %u px; gain %.2f\n",
''',
         r'''"from the camera, the largest box %d x %d px; read-backs %u, %u frames with print pixels (G-buffer "
                     "band or post stamp), the most %u px; gain %.2f\n",
'''),
    ],
    TEST: [
        (r'''    // Pack.
    {
        float out[PrintFloats];
''',
         r'''    // (r111g) The look: a deeper, more saturated red at less than the pixel's luminance, firmer cover, a stronger
    // wet darken; the blood trail's strengths never rise (the first prints, at the pool, are the strongest); the
    // stamp's arithmetic (the shader's, in doubles) turns a lit grey pixel into a dark red one.
    {
        const double tr = FOOTPRINTS_POST_BLOOD_TINT_R, tg = FOOTPRINTS_POST_BLOOD_TINT_G,
                     tb = FOOTPRINTS_POST_BLOOD_TINT_B;
        assert(Near(0.2126 * tr + 0.7152 * tg + 0.0722 * tb, 1.0, 2e-3));
        assert((tr - std::max(tg, tb)) / tr > 0.92); // r111f: 0.88
        assert(FOOTPRINTS_POST_BLOOD_LUM < 1.0 && FOOTPRINTS_POST_BLOOD_LUM > 0.3);
        assert(FOOTPRINTS_POST_BLOOD_COVER > 0.9 && FOOTPRINTS_POST_BLOOD_COVER <= 1.0);
        assert(FOOTPRINTS_POST_WET_DARKEN > 0.25 && FOOTPRINTS_POST_WET_DARKEN < 0.6);
        // a lit grey pixel (0.2) under a full blood print: darker than before, red by more than 8 to 1
        const double lum = 0.2, w = 1.0;
        const double dark = lum * FOOTPRINTS_POST_BLOOD_LUM;
        const double r = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tr * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double g = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tg * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double b = 0.2 * (1.0 - FOOTPRINTS_POST_BLOOD_COVER * w) + tb * dark * FOOTPRINTS_POST_BLOOD_COVER * w;
        const double out_lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        assert(out_lum < lum * 0.8 && r > 8.0 * g && r > 8.0 * b);
        // the rounded weight: 1 stays 1, 0.42 reads 0.66, order kept
        const auto round_w = [](double v) { return 1.0 - (1.0 - v) * (1.0 - v); };
        assert(Near(round_w(1.0), 1.0) && Near(round_w(0.42), 0.6636, 1e-3) && round_w(0.3) < round_w(0.4));
        // the trail of a full blood coat: no print is stronger than the one before
        const Knobs k = Read("1", nullptr);
        Coat c;
        Kind kind = Kind::Wet;
        assert(Soak(c, k, false, false, 200, 120));
        float last = 2.0f;
        int n = 0;
        while (n < 24) {
            const float s = TakeStep(c, k, false, kind);
            if (s == 0.0f) {
                break;
            }
            assert(s <= last && kind == Kind::Blood);
            last = s;
            ++n;
        }
        assert(n == 13);
    }
    // Pack.
    {
        float out[PrintFloats];
'''),
    ],
    README: [
        (r'''raises the gloss toward 0.8 and the specular colour toward f0 0.0625 (never lowered); a mud print''',
         r'''and (r111g) adds neither gloss nor specular colour (it first raised both, and on a glossy floor the print read as a pale bright shape), so it reads as darker stone; a mud print'''),
        (r'''(the stone's texture and the game's shading stay), a wet or mud print darkens the lit pixel a further 25%; times''',
         r'''(the stone's texture and the game's shading stay; r111g: a deeper, more saturated red at 0.7 of that luminance, cover 95%, the print's weight rounded as 1 - (1 - w)^2 so a faded print of a trail's tail stays readable), a wet or mud print darkens the lit pixel a further 40% (r111g, was 25%); times'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; is r111f applied, and is this patch's own earlier version reverted?): %r" %
                             (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def split_args(text):
    """The top-level comma separated arguments of a call's text after its format string."""
    out, depth, cur, quote = [], 0, "", False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\":
                cur += text[i + 1]
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def define(lay, name):
    m = re.search(r"#define %s ([0-9.]+)\n" % name, lay)
    if not m:
        raise SystemExit("text check: layout lacks %s" % name)
    return float(m.group(1))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if not fmt.startswith("Footprints (r111g)"):
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111g line (kinds fold on digits only): %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = wide.replace("%%", "%")
        print("  r111g log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 2:
        raise SystemExit("text check: %d r111g log lines (2 expected)" % n_new)
    if "read-backs %u, %u of them with print pixels" in cpp:
        raise SystemExit("text check: the old r111c counter wording is still there")
    if "LogStamp(0, 0, 0, std::array<float, 3>{});" not in cpp or "LogStamp(frame, px, snap.count, snap.camera);" not in cpp:
        raise SystemExit("text check: LogStamp calls missing")
    lay = texts[LAYOUT]
    tr, tg, tb = (define(lay, "FOOTPRINTS_POST_BLOOD_TINT_" + c) for c in "RGB")
    lum = 0.2126 * tr + 0.7152 * tg + 0.0722 * tb
    if abs(lum - 1.0) > 2e-3:
        raise SystemExit("text check: the blood tint's luminance is %.4f, not 1" % lum)
    print("  blood tint luminance %.4f, red share %.3f" % (lum, (tr - max(tg, tb)) / tr))
    if not (0.3 < define(lay, "FOOTPRINTS_POST_BLOOD_LUM") < 1.0 and 0.9 < define(lay, "FOOTPRINTS_POST_BLOOD_COVER") <= 1.0):
        raise SystemExit("text check: the blood lum or cover is out of range")
    if not (0.25 < define(lay, "FOOTPRINTS_POST_WET_DARKEN") < 0.6):
        raise SystemExit("text check: the post wet darken is out of range")
    g = texts[GBUF]
    if "m.r = max(m.r, mix(m.r, FOOTPRINTS_WET_GLOSS, wet));" in g or "FOOTPRINTS_WET_SPEC_ROOT), wet))" in g:
        raise SystemExit("text check: the wet branch still raises gloss or specular")
    if "FOOTPRINTS_WET_SPEC_ROOT), blood))" not in g:
        raise SystemExit("text check: the blood branch lost its specular")
    flat = texts[FLAT]
    if "const float blood = 1.0 - (1.0 - blood_w) * (1.0 - blood_w);" not in flat:
        raise SystemExit("text check: the flat shader lacks the rounded blood weight")
    if "FlatWords == 36u" not in texts[TEST]:
        raise SystemExit("text check: the unit test lost its word count")
    for needle in ("(r111g) adds neither gloss nor specular colour", "a further 40% (r111g, was 25%)"):
        if texts[README].count(needle) != 1:
            raise SystemExit("text check: README lacks %r once" % needle)
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111g_prints-stronger.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111G_ROOT)" % ROOT)
    if "GroupWork(p);" not in load(FLAT)[2]:
        raise SystemExit("REFUSED: r111f is not applied (%s lacks GroupWork)" % FLAT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (%d files edited; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)" %
                  (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111gtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111gtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
