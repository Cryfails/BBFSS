# r68_lamp-target-mismatch: a light draw whose two light targets do not fit the lamp shadow pass
# (other format, no storage or transfer-source use, not eligible for the reduced path, or two
# sizes) used to switch lamp shadows off for the whole session with one line that did not say
# which. Seen at the save copy "dark-interior": after that line the ray traced lamp pass counted
# 0 passes. Now only that light draw is skipped (the game's own draw goes ahead as before), the
# next one is tried again, and the line names the target, its format, uses and sizes (at the
# first skip and then at every 600th).
#
# Use: cd <tree> && python -I -X utf8 r68_lamp-target-mismatch.py check | apply | revert
# (root from R68_ROOT, else the current directory). Files keep their line ends. Originals are
# kept in r68_backup/ next to this script. Independent of r61, r62c, r64, r64b, r65 (its header
# anchor is the line before "bool tried", which r65 does not touch).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r68_backup")
ROOT = os.environ.get("R68_ROOT") or os.getcwd()
DIR = "engine/gpu/shadps4/video_core/renderer_vulkan/"

EDITS = {
    DIR + "vk_point_shadow.h": [('''    void TrackLamps(u32 end, bool blend, bool read, bool line);
    bool tried = false;
''', '''    void TrackLamps(u32 end, bool blend, bool read, bool line);
    // bbport (r68_lamp-target-mismatch): light draws skipped because their targets did not fit
    u64 target_mismatches = 0;
    bool tried = false;
''')],
    DIR + "vk_point_shadow.cpp": [('''            info.size.height != targets[0]->info.size.height) {
            failed = true;
            std::printf("Point shadows: the light targets are not matching B10G11R11 storage "
                        "images; off\\n");
            return;
        }
''', '''            info.size.height != targets[0]->info.size.height) {
            // bbport (r68_lamp-target-mismatch): this used to switch the pass off for the whole
            // session. Only this light draw is skipped now (the game's own draw goes ahead) and
            // the next one is tried again; the line says what did not fit.
            if (target_mismatches++ % 600 == 0) {
                std::printf("Point shadows: light target %d does not fit (format %d, wanted %d; "
                            "uses %08x; %ux%u against %ux%u; reduced path %d, eligible %d); this "
                            "light draw is skipped, %llu so far\\n",
                            i, static_cast<int>(info.pixel_format), static_cast<int>(TargetFormat),
                            static_cast<u32>(static_cast<VkImageUsageFlags>(targets[i]->usage_flags)),
                            info.size.width, info.size.height, targets[0]->info.size.width,
                            targets[0]->info.size.height, reduced ? 1 : 0,
                            scene_targets.Eligible(*targets[i]) ? 1 : 0,
                            static_cast<unsigned long long>(target_mismatches));
            }
            return;
        }
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
        done = sum(cur.count(new) == 1 for old, new in edits)
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
        for path, edits, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
            for old, new in edits: cur = cur.replace(old, new)
            open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in edits: cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")

main()
