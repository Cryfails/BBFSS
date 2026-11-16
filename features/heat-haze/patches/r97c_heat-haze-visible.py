# r97c_heat-haze-visible: FEATURE fix of r97_heat-haze (apply AFTER r97 and r97b_heat-haze-paths.fixed,
# revert BEFORE them). Off by default as r97: nothing of it runs unless BB_HEAT_HAZE is above 0 (no
# HeatHaze object, no pass, no buffer; the code of the knob-off path is not touched).
#
# Why (2026-11-15 23:50, from the b23 slot run of r97b): the haze pass WRITES its pixels and the writes
# reach the picture (the 2-pixel magenta frames of BB_HEAT_HAZE_SHOW=2 are in both the faithful 1080p and
# the quick 640x360 stills; quick counters: 1,028,020 of 1,028,020 tested pixels written, 14% would fail
# the depth tests, the torch's flame pixel reads view z 4.48 m against the lamp's 4.58 m). What is wrong
# is the SIZE of the shimmer: the model of the shader's noise (r97c_model.py, a Python copy of the
# noise, the weight and the column) gives for the hand torch 4.58 m ahead at 1080 rows (faithful, and the
# 4K DLSS run's 1920x1080 scene) a root mean square move of 0.64 px, 69% of the column's pixels moved by
# under half a pixel, the largest move 2.9 px; for a flame 10 m away 0.33 px rms, 88% under half a
# pixel; for the quick scene (360 rows) 0.21 px rms and 96% under half a pixel. A move under half a
# pixel on the smooth dark fog and wall above a torch changes no visible pixel, and a temporal
# upscaler's history averages what is left away. (At 4K output the same render pixels are 2 output
# pixels each, over a bigger picture, and the plants behind the torch there give the shimmer something
# to bend: the b23 slot place has smooth fog.) The causes in the numbers: the noise's rms is 0.3 of
# AmplitudeM's maximum, the weight 1.5 power of (1 - t) and the 0.12 fade-in keep the mean weight of the
# column at about 0.25, and the shimmer falls with distance (4.1 px at 10 m).
#
# (Review fix: MinAmplitudePx 0.6 -> 0.9, i.e. times 1.5 with AmplitudeM, so the same flames get a
# column as before: unit test j pins the cut at 19 m, and at 0.6 a 20 m flame (0.68 px) was drawn.)
# What changes (4 numbers, all inside the haze's own look):
#  - AmplitudeM 0.03 -> 0.045 m, MaxAmplitudePx 8 -> 10 (per 1080 rows): the largest move.
#  - the noise's offset is scaled by 1/0.45 instead of 1/0.75 and clamped to -1..1 (so the largest move
#    is still the amplitude): rms 0.49 of it instead of 0.30.
#  - the column's weight: 1 - t instead of (1 - t)^1.5 and a fade-in of 0.06 instead of 0.12 of its
#    length: the shimmer reaches higher and starts closer to the flame (the bright glow is what shows
#    a move).
# Numbers with the model (1080 rows): torch 4.58 m: rms 0.64 -> 1.7 px, under half a pixel 69% -> 41%,
# 2 px or more 2% -> 21%, largest 2.9 -> 6.7; flame 10 m: rms 0.33 -> 1.0 px, 2 px or more 0% -> 6%.
# (The test view BB_HEAT_HAZE_SHOW=1 or 2 was 3 times the old shimmer, rms 1.9 px at the torch: the
# new default is about as large as the old test view, which the owner saw at 4K; the strength setting
# BB_HEAT_HAZE=0.5 halves it.) A drawing frame costs the same (same passes, same pixels, a larger pad of
# a few pixels at most on each rectangle).
#
# Files: heat_haze.h (the two numbers and their comments), host_shaders/heat_haze.comp (two lines),
# vk_heat_haze.cpp (one once-line after r97b's), tests/test_heat_haze.cpp (a block), README.md (r97's
# BB_HEAT_HAZE row: the shimmer's numbers).
#
# Use: python -I -X utf8 r97c_heat-haze-visible.py check | apply | revert
# Root: R97C_ROOT, else <tree>. Line ends kept. apply backs the originals up in r97c_backup next
# to this script; revert puts back exactly what apply changed (each replaced or inserted text is found
# by itself, exactly once).
import hashlib, os, sys

ROOT = os.environ.get("R97C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r97c_backup")
VC = "engine/gpu/shadps4/video_core/"
SH = VC + "host_shaders/heat_haze.comp"
HH = VC + "renderer_vulkan/heat_haze.h"
VCPP = VC + "renderer_vulkan/vk_heat_haze.cpp"
UT = "engine/tests/test_heat_haze.cpp"
RM = "README.md"

# ("replace", old, new) swaps one text for another; ("insert", anchor, before, after) keeps the anchor.
EDITS = {
SH: [
("replace",
 "    const float weight = smoothstep(0.0, 0.12, t) * pow(1.0 - t, 1.5) * side * side * field.z;\n",
 "    // (r97c) fading in over the first 6% of the column and out linearly: the shimmer starts at the\n"
 "    // flame's glow, which is what shows a move, and reaches the top\n"
 "    const float weight = smoothstep(0.0, 0.06, t) * (1.0 - t) * side * side * field.z;\n"),
("replace",
 "    const vec2 d = vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.75);\n",
 "    // (r97c) scaled by 1/0.45 and clamped: the noise's rms across is 0.49 of the amplitude, the largest move\n"
 "    // the amplitude itself (r97: 1/0.75, rms 0.30)\n"
 "    const vec2 d = clamp(vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.45), vec2(-1.0), vec2(1.0));\n"),
],
HH: [
("replace",
 "/// m: the most the shimmer moves a pixel at strength 1, at the flame's distance (the noise's\n"
 "/// root mean square is 0.3 of it, the column's weight at most 0.83 of that, just above the flame).\n"
 "inline constexpr float AmplitudeM = 0.03f;\n",
 "/// m: the most the shimmer moves a pixel at strength 1, at the flame's distance (r97c: the noise's\n"
 "/// root mean square is 0.49 of it, the column's weight at most 0.94 of that, just above the flame;\n"
 "/// 0.03 and 0.3 before, which left 69% of a torch's column under half a pixel of move).\n"
 "inline constexpr float AmplitudeM = 0.045f;\n"),
("replace",
 "inline constexpr float MaxAmplitudePx = 8.0f, MinAmplitudePx = 0.6f;\n",
 "inline constexpr float MaxAmplitudePx = 10.0f, MinAmplitudePx = 0.9f; // r97c: 8 and 0.6 before\n"),
],
VCPP: [
("insert", '                knobs.outline ? "on" : "off");\n', "",
 "    // bbport (r97c_heat-haze-visible)\n"
 "    std::printf(\"Heat haze (r97c): shimmer up to %.3f m at the flame's distance (at most %.0f pixels per \"\n"
 "                \"1080 rows) at strength 1, the noise's root mean square 0.49 of that, the weight 1 - t \"\n"
 "                \"above the flame (r97: 0.03 m, 8 pixels, 0.30, (1 - t)^1.5)\\n\",\n"
 "                double(BbHeatHaze::AmplitudeM), double(BbHeatHaze::MaxAmplitudePx));\n"),
],
UT: [
("replace",
 "            assert(full == (z < 19.0f)); // 18.5 m: 0.74 px per 1080 rows; 20 m: 0.46 px\n",
 "            assert(full == (z < 19.0f)); // 18.5 m: 1.11 px per 1080 rows; 20 m: 0.68 px (r97c: 0.9 least)\n"),
("insert",
 "            assert(std::string_view(Verdict(v)).size() < 250); // a slot log keeps 300 characters\n"
 "        }\n"
 "    }\n", "",
 "    // l. bbport (r97c_heat-haze-visible): the shimmer is big enough to show at 1080 rows.\n"
 "    {\n"
 "        const Camera camera = Straight();\n"
 "        const auto near_torch = MakeColumn(Torch(0, 0, 4.6f), camera, 1.0f, false, still);\n"
 "        const auto far_torch = MakeColumn(Torch(0, 0, 10.0f), camera, 1.0f, false, still);\n"
 "        assert(near_torch && far_torch);\n"
 "        // (this camera's y scale 1.7 is a narrower view than the game's 2.54: 200 and 92 pixels a metre)\n"
 "        assert(near_torch->push.shape[2] >= 8.0f && far_torch->push.shape[2] >= 4.0f);\n"
 "        assert(AmplitudeM >= 0.04f && MaxAmplitudePx >= 9.0f);\n"
 "        // The same share of the screen at 4K rows: twice the pixels.\n"
 "        const auto big = MakeColumn(Torch(0, 0, 4.6f), Straight(3840, 2160), 1.0f, false, still);\n"
 "        assert(big && Near(big->push.shape[2], 2.0f * near_torch->push.shape[2], 0.05f));\n"
 "    }\n"),
],
}

README_OLD = ("at strength 1 by up to 0.03 m at the flame's distance (at most 8 pixels per 1080 rows; the root mean "
              "square of the noise is 0.3 of that), most just above the flame, fading to the top and the sides. "
              "A column whose largest move would stay under 0.6 pixels per 1080 rows is not drawn.")
README_NEW = ("at strength 1 by up to 0.045 m at the flame's distance (at most 10 pixels per 1080 rows; r97c: the root "
              "mean square of the noise is 0.49 of that, so 1.7 pixels for a torch 4.6 m ahead, 1.0 pixel at 10 m, "
              "with moves up to 6 pixels at the torch; modelled, 1080 rows), most just above the flame, fading "
              "linearly to the top and fading out to the sides. A column whose largest move would stay under 0.9 "
              "pixels per 1080 rows is not drawn (the same flames as before r97c).")
EDITS[RM] = [("replace", README_OLD, README_NEW)]
PATHS = (SH, HH, VCPP, UT, RM)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("%s is missing (are r97 and r97b applied?)" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:70]))
        else:
            _, old, new = ed
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, its new text %d times: %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_edits(cur, eds):
    for ed in eds:
        if ed[0] == "insert":
            _, anchor, before, after = ed
            cur = cur.replace(anchor, before + anchor + after, 1)
        else:
            cur = cur.replace(ed[1], ed[2], 1)
    return cur


def revert_edits(cur, eds):
    for ed in reversed(eds):
        if ed[0] == "insert":
            _, anchor, before, after = ed
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(ed[2], ed[1], 1)
    return cur


def text_checks(t):
    s = t[SH]
    if s.count("smoothstep(0.0, 0.06, t) * (1.0 - t) * side * side * field.z") != 1 or \
       s.count("clamp(vec2(n1 - 0.75, 0.5 * (n2 - 0.75)) * (1.0 / 0.45), vec2(-1.0), vec2(1.0))") != 1:
        raise SystemExit("text check: the shader's two lines")
    if "pow(1.0 - t, 1.5)" in s or "(1.0 / 0.75)" in s:
        raise SystemExit("text check: an old shader line is left")
    h = t[HH]
    if "AmplitudeM = 0.045f;" not in h or "MaxAmplitudePx = 10.0f, MinAmplitudePx = 0.9f;" not in h:
        raise SystemExit("text check: heat_haze.h numbers")
    c = t[VCPP]
    if c.find("Heat haze (r97b): depth tests %s") > c.find("Heat haze (r97c): shimmer up to") or \
       c.count("Heat haze (r97c): shimmer up to") != 1:
        raise SystemExit("text check: the once-line is not after r97b's")
    u = t[UT]
    if u.find("// k. bbport (r97b") > u.find("// l. bbport (r97c") or \
       u.find("// l. bbport (r97c") > u.find('std::printf("heat-haze-test: all checks passed'):
        raise SystemExit("text check: the unit test block is out of place")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R97C_ROOT)" % ROOT)
    plan, states = [], []
    for path in PATHS:
        raw, eol, cur = load(path)
        if path in (VCPP,) and "Heat haze (r97b)" not in cur:
            raise SystemExit("%s: r97b is not applied" % path)
        states.append((path, state_of(cur, EDITS[path], path)))
        plan.append((path, EDITS[path], raw, eol, cur))
    kinds = {s for _, s in states}
    if len(kinds) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % p for p in states))
    state = kinds.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur in plan:
            res = apply_edits(cur, eds)
            if state_of(res, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = res
        return out

    def write(items):
        for path, data in items:
            full = os.path.join(ROOT, path)
            tmp = full + ".r97ctmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, full)

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        write([(p[0], texts[p[0]].replace("\n", p[3]).encode("utf-8")) for p in plan])
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = []
    for path, eds, raw, eol, cur in plan:
        res = revert_edits(cur, eds)
        if state_of(res, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out.append((path, res.replace("\n", eol).encode("utf-8")))
    write(out)
    print("reverted")


main()
