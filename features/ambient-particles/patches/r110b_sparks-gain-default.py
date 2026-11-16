# r110b_sparks-gain-default: FEATURE patch on top of r110_weapon-sparks (which must be applied).
# Owner 2026-11-15 23:13: "The spark explosion from transforming weapons is too big, but I like the
# particles". So with BB_WEAPON_SPARKS set, the default of BB_WEAPON_SPARKS_GAIN (how many extra times
# the game's transform effect draw is drawn again) goes from 2 (3 times as bright) to 0: the game's own
# burst stays as the game draws it, and the falling copies (BB_WEAPON_SPARKS=2) stay as they are.
# BB_WEAPON_SPARKS_GAIN set explicitly (0 to 6) works as before.
#
# What it changes (replace edits: each old text must be found exactly once, as r110 leaves it):
#  - vk_weapon_sparks.cpp: SparksDefaultGain = 2 -> 0 (SparksConfig::gain and the BB_WEAPON_SPARKS_GAIN
#    read both take this constant; the once-line prints cfg.gain, so it says "0 times more").
#  - README.md: the BB_WEAPON_SPARKS row (the repeat is now "as many times as BB_WEAPON_SPARKS_GAIN
#    says, default 0") and the BB_WEAPON_SPARKS_GAIN row (default `0`).
# Why gain 0 draws nothing extra for the burst: WeaponSparksAfterDraw returns at "if (gain == 0 &&
# copy_count == 0)" before recording anything; with copies, the recorded loop runs gain + copy_count
# times and the first `gain` (none) are the repeats, the rest the moved copies (i >= gain).
# NOTE: r110's own text check ties the code constant to the README row text ("2 ... | `2` |"), so with
# r110b applied r110's check reports a disagreement: revert r110b before reverting or re-checking r110.
#
# Use: python -I -X utf8 r110b_sparks-gain-default.py check | apply | revert
# Root: R110B_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up
# in r110b_backup next to this script; revert puts the old texts back (each new text found exactly once).
import os, sys

ROOT = os.environ.get("R110B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r110b_backup")
N = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_weapon_sparks.cpp"
D = "README.md"
ORDER = (N, D)

# (old, new): the old text is replaced by the new one (applied when the new is there once, the old not).
EDITS = {
N: [
("constexpr std::uint32_t SparksDefaultGain = 2, SparksMaxGain = 6;\n",
 "constexpr std::uint32_t SparksDefaultGain = 0, SparksMaxGain = 6; // r110b: 0, the game's burst stays as it is drawn\n"),
],
D: [
("right after themselves, so the transform's sparks and glint are brighter (the game's own bloom spreads them). A pair",
 "right after themselves as many times as `BB_WEAPON_SPARKS_GAIN` says (default `0`: not at all, the game's "
 "own burst stays as the game draws it; more makes the transform's sparks and glint brighter, the game's "
 "own bloom spreads them). A pair"),
("how many times more such a draw is drawn, 0 to 6 (`2` makes the effect 3 times as bright) | `2` |",
 "how many times more such a draw is drawn, 0 to 6 (`0`: the game's own burst is left as it is drawn, "
 "also with `BB_WEAPON_SPARKS=2`, whose falling copies stay; `2` makes the effect 3 times as bright) | `0` |"),
],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'clean' (old once, new none), 'applied' (new once, old none), else refuse."""
    done = todo = 0
    for old, new in eds:
        no, nn = cur.count(old), cur.count(new)
        if no == 1 and nn == 0:
            todo += 1
        elif no == 0 and nn == 1:
            done += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1; "
                             "r110 must be applied): %r" % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def text_checks(texts):
    n = texts[N]
    for want in ("constexpr std::uint32_t SparksDefaultGain = 0, SparksMaxGain = 6;",
                 "std::uint32_t gain = SparksDefaultGain;",
                 'c.gain = SparksNumber("BB_WEAPON_SPARKS_GAIN", SparksDefaultGain, 0, SparksMaxGain);',
                 "    if (gain == 0 && copy_count == 0) {\n        return;\n    }\n",
                 "        for (u32 i = 0; i < gain + copy_count; ++i) {\n            if (i >= gain) {\n"):
        if n.count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times, wanted 1" % (N, want[:60], n.count(want)))
    if "SparksDefaultGain = 2" in n:
        raise SystemExit("text check: the old default 2 is still in %s" % N)
    gain_row = [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS_GAIN` |")]
    main_row = [l for l in texts[D].split("\n") if l.startswith("| `BB_WEAPON_SPARKS` |")]
    if len(gain_row) != 1 or not gain_row[0].endswith("| `0` |") or "0 to 6" not in gain_row[0]:
        raise SystemExit("text check: the BB_WEAPON_SPARKS_GAIN row does not say default 0 and 0 to 6")
    if len(main_row) != 1 or "(default `0`:" not in main_row[0] or "for 1500 ms after" not in main_row[0]:
        raise SystemExit("text check: the BB_WEAPON_SPARKS row does not say default 0")
    if "so the transform's sparks and glint are brighter" in main_row[0]:
        raise SystemExit("text check: the BB_WEAPON_SPARKS row still says the effect is brighter by default")
    # the clamp stays 0..6 in code, as the row says
    if n.count("SparksMaxGain = 6;") != 1:
        raise SystemExit("text check: the gain maximum is no longer 6")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R110B_ROOT)" % ROOT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def swapped(forward):
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1) if forward else cur.replace(new, old, 1)
            if state_of(cur, eds, path) != ("applied" if forward else "clean"):
                raise SystemExit("%s: the result does not read as %s" % (path, "applied" if forward else "clean"))
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(swapped(True))
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = swapped(True)
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r110btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = swapped(False)
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r110btmp"
        open(tmp, "wb").write(out[path].replace("\n", eol).encode("utf-8"))
        os.replace(tmp, full)
    print("reverted")


main()
