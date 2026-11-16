# r72_lamp-window-default: BB_LAMP_SHADOW_WINDOW=2 (r60's centred window, made cheaper by r61)
# becomes the default. The one line that flips it is LampWindowDefault in lamp_shadow_tune.h; the
# other edits are the texts that said "1 is the default" (the places r61's header lists under THE
# FLIP), and the README's row of the variable (not in r61's list; it names the default). No logic
# changes besides the one constant: 0 and 1 stay reachable with BB_LAMP_SHADOW_WINDOW=0 / =1.
# test_lamp_shadow_tune.cpp needs no edit (written against LampWindowDefault; its asserts hold for
# 1 and for 2). The torch lab's checks (`checked`) leave the window out, so they already ran with 2
# in r61_lab_w2.txt (rt-shadow-test --lamps with BB_LAMP_SHADOW_WINDOW=2, exit 0); after this patch
# its plain run gives that lab, and BB_LAMP_SHADOW_WINDOW=1 gives the old default lab.
#
# Why (2026-11-15, game, HQ GTAO, torch, DLSS Performance 4K, BB_GPU_PROFILE=1, sq7_cost.txt,
# 3 repeats of 20 s standing, medians of the pairs): point shadow rows (trace + resolve) of 2 over 1
# +0.007 ms at full resolution (pairs +0.047 +0.007 +0.005) and +0.080 ms at half resolution (pairs
# +0.080 +0.138 +0.061); bar about +0.10 ms. Walk test (sq7_wake, half 1): the moving torch shadow's
# edge shows 8 px stair steps with 1 and a smooth edge with 2. Left open: in the torch lab, runs of 2
# do not repeat bit for bit where runs of 1 do (about 800 to 1550 of 2.07 M pixels, at most 0.0156).
#
# On top of <tree> with r61 applied (and r65, which makes the half-resolution builds at start).
# Use: cd <tree> && python -I -X utf8 r72_lamp-window-default.py check | apply | revert
# (root from R72_ROOT, else the current directory). Files keep their line ends (all CRLF). Originals
# are kept in r72_backup/ next to this script; revert applies the edits backwards, new for old, and
# gives the files back byte for byte.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r72_backup")
ROOT = os.environ.get("R72_ROOT") or os.getcwd()
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"

EDITS = {
    RV + "lamp_shadow_tune.h": [(
'''/// needs the tune test's r57 asserts changed (they hold for a default with the window: 1 or 2).
inline constexpr std::uint32_t LampWindowDefault = 1;
''',
'''/// needs the tune test's r57 asserts changed (they hold for a default with the window: 1 or 2).
/// bbport (r72_lamp-window-default): 2 since r72 (in the game +0.01 ms over 1 at full and +0.08 ms
/// at half resolution, and no squares behind the moving torch shadow); 1 was the default before.
inline constexpr std::uint32_t LampWindowDefault = 2;
''')],
    HS + "point_shadow_ray.comp": [(
'''    //    BB_LAMP_SHADOW_WINDOW=0 (word 0 bit 21 clear; the default is 1, the window) no answer
''',
'''    //    BB_LAMP_SHADOW_WINDOW=0 (word 0 bit 21 clear; the default is 2, the centred window, since
    //    r72; 1 before) no answer
''')],
    RV + "vk_point_shadow.cpp": [(
'''%s; 1 (the default) = the 5x5 "''',
'''%s; 1 = the 5x5 "''')],
    "engine/docs/renderer-performance-0.9.43.md": [
        ('''  (`ReadLampShadowTune`, `LampShadowTune::window`), default 1, sets tuning word 0 bit 21
''',
         '''  (`ReadLampShadowTune`, `LampShadowTune::window`), default 1 (2 since r72), sets tuning word 0 bit 21
'''),
        ('''which is why 1 stays the default.''',
         '''which is why 0 is not the default (1 was until r72, 2 is since).'''),
        ('''  `lamp_shadow_tune.h`, 1), sets tuning word 0 bits 21 and 22''',
         '''  `lamp_shadow_tune.h`, 2 since r72, 1 before), sets tuning word 0 bits 21 and 22'''),
        ('''The default stays
  `LampWindowDefault` = 1. No experiment bit gates it, so the switch does not change it.
''',
         '''The default stayed
  `LampWindowDefault` = 1 here (r72 makes it 2). No experiment bit gates it, so the switch does not change it.
- **Centred lamp window as the default (r72).** `LampWindowDefault` in `lamp_shadow_tune.h` is 2, so
  without `BB_LAMP_SHADOW_WINDOW` the ray traced lamp pass runs r60's centred window with r61's resolve
  builds; `BB_LAMP_SHADOW_WINDOW=1` gives the pass of before (r57's window, confined to the 8x8
  workgroup), 0 the window-free one. Measured in the game (HQ GTAO, torch, DLSS Performance 4K,
  `BB_GPU_PROFILE=1`, 20 s standing, 3 repeats, medians of paired runs): the point shadow rows (trace
  and resolve together) +0.007 ms over 1 at full resolution and +0.080 ms at half resolution (pairs
  +0.061 to +0.138). In a 1.5 s walk test the 8 px stair steps along the moving torch shadow's edge
  seen with 1 are gone with 2. The answers image (8 bytes a pixel, 16.6 MB at 1920x1080) and the
  centred and resolve builds are now made by default. Left open: in the torch lab, runs of 2 do not
  always repeat bit for bit where runs of 1 do (about 800 to 1550 of 2.07 M pixels, at most 0.0156,
  two steps of the 11-bit light); not visible, its cause (a race or carried state) not yet found.
'''),
    ],
    "engine/tests/test_rt_shadows.cpp": [
        ('''            // checks below are made for the defaults (checked) and left out otherwise.
''',
         '''            // checks below are made for the defaults (checked) and left out otherwise.
            // bbport (r72_lamp-window-default): the defaults have BB_LAMP_SHADOW_WINDOW=2 since r72;
            // `checked` leaves the window out, so the checks run with 1 or 0 set as well.
'''),
        ('''                // BB_LAMP_SHADOW_WINDOW=1 (the default) and =0 (to try), whatever the environment says.
''',
         '''                // BB_LAMP_SHADOW_WINDOW=1 (the default until r72) and =0 (to try), whatever the environment says.
'''),
        ('''                // engine runs it; printed beside the default's bounds, not yet checked)
''',
         '''                // engine runs it; printed beside the default's bounds, not yet checked)
                // bbport (r72_lamp-window-default): the default is 2 since r72, so 0 and 2 run it
                // (without MODE_APART) and 4 and 5 run it again with MODE_APART.
'''),
    ],
    "README.md": [(
'''| `BB_LAMP_SHADOW_WINDOW` | `1`: the history is bound by the 5x5 answers around the pixel and, under a moving lamp, capped by their far blockers' swing; `0` (to try): by the pixel's own last frames and one fixed swing, which removes squares fixed to the screen behind moving shadows but lets a shadow that is gone linger longer. With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap keep the 5x5 window either way | `1` |
''',
'''| `BB_LAMP_SHADOW_WINDOW` | `2`: the history is bound by the 5x5 answers centred on every pixel and, under a moving lamp, capped by their far blockers' swing, which leaves no squares fixed to the screen behind moving shadows (one dispatch more: about 0.01 ms, 0.08 ms with `graphics_lamp_shadow_half=1`); `1`: the same, with the 5x5 window confined to the pixel's 8x8 workgroup (the default before r72); `0` (to try): by the pixel's own last frames and one fixed swing, which also removes the squares but lets a shadow that is gone linger longer. With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap keep the 5x5 window either way | `2` |
''')],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 and cur.count(old) == (1 if old in new else 0) for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if cmd == "check":
        print("applied" if state == "applied" else "not applied; would apply (%d files)" % len(plan)); return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        os.makedirs(BACKUP, exist_ok=True)
        out = []
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
            for old, new in edits: cur = cur.replace(old, new)
            out.append((path, cur.replace("\n", eol).encode("utf-8")))
        for path, data in out:
            open(os.path.join(ROOT, path), "wb").write(data)
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    out = []
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        out.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in out:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted")

main()
