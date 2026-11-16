# r119f_clouds-open-sky: FEATURE aid on top of r119e_clouds-real-sky.fixed.py and r119 to r119d (BB_VOLUMETRIC_CLOUDS=1
# only; still off by default, still costs nothing when off: nothing here runs without the CloudLayer object, which
# Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# Why (b46): the layer looks right where there is sky (lamp-test-spot arch: off = smooth glow, on = textured dark masses
# with lit edges) but sky is only 5-8% of every test picture, so drift and look cannot be judged. This is mostly a
# TEST-CAMERA task, and the answer is in the job file (slot_jobs_r119f_clouds-open-sky.json): the game's follow camera
# cannot look higher than its own pitch limit and has no free camera (camera mode F3/F4/F6 turn the camera around the
# hunter inside the same pitch limits), so a bigger sky needs the HUNTER out from under cover: the jobs walk out of the
# lamp-test-spot arcade and the church-puddles passage in 1.5 s steps, tilt up after each step and take a picture.
#
# What the code change is (small, one knob): the layer's log lines come every 600 frames (the first after 200), which at
# a slot game's frame rate is 10 to 20 s and averages over a whole walk, so the 'sky px share' line could not say
# which picture had the open sky. BB_VOLUMETRIC_CLOUDS_REPORT=<frames> (30 to 3000; unset, empty, or anything else = the
# old 200 then 600) sets the period of ALL the layer's periodic lines (the first one too), so each step of a walk gets
# a line of its own ("sky px share" over about 3 s). Read once, at the first use; nothing on the GPU changes (no shader,
# no push, no buffer: shader builds byte-identical). The once-line says the period when it is set.
# Look: NOT changed. No big sky was seen yet; the look constants stay as r119e has them (moderate); the do-nothing of the
# library stays (the layer is never made without BB_VOLUMETRIC_CLOUDS=1 and draws nothing where no pixel is sky).
# Cost: none (one static read at the start, one integer compare a frame while the layer is on). Memory: none.
# Off guarantee: the new function runs inside CloudLayer (made only with BB_VOLUMETRIC_CLOUDS=1); the static read is
# reached from the constructor and the frame hook of that object only.
#
# TOOL or FEATURE: FEATURE (the debug knob of r119, stays with it). No new file, no shared hook, no CMake change.
# Edits r119's own files: cloud_layer_params.h, vk_cloud_layer.cpp, tests/test_cloud_layer.cpp, README.md.
# Apply after r119e; revert BEFORE r119e (its check ties to text near these lines).
#
# Use: python -I -X utf8 r119f_clouds-open-sky.py check | apply | revert
# Root: R119F_ROOT, else <tree>. Line ends kept. Backups in r119f_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119f_backup")
ROOT = os.environ.get("R119F_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
TMP = ".r119ftmp"

PARAMS = R + "cloud_layer_params.h"
CPP = R + "vk_cloud_layer.cpp"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

EDITS = [
    (PARAMS,
     "inline constexpr std::uint32_t FramesNoPlace = 300; ///< frames after which \"never reached\" is said\n",
     "inline constexpr std::uint32_t FramesNoPlace = 300; ///< frames after which \"never reached\" is said\n"
     "\n"
     "/// bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT = frames between the periodic log lines, the first\n"
     "/// one included (so a walk in a test gets a 'sky px share' line a step). 0 = not set or not valid: FramesFirst\n"
     "/// then FramesPeriod. Whole decimal numbers only, 30 to 3000.\n"
     "inline constexpr std::uint32_t ReportFramesLeast = 30, ReportFramesMost = 3000;\n"
     "inline std::uint32_t ReportFramesFrom(const char* text) {\n"
     "    if (text == nullptr || text[0] == '\\0') return 0;\n"
     "    std::uint32_t v = 0;\n"
     "    for (const char* p = text; *p != '\\0'; ++p) {\n"
     "        if (*p < '0' || *p > '9') return 0;\n"
     "        v = v * 10u + std::uint32_t(*p - '0');\n"
     "        if (v > ReportFramesMost) return 0;\n"
     "    }\n"
     "    return v >= ReportFramesLeast ? v : 0;\n"
     "}\n"),
    (CPP,
     "/// BB_VOLUMETRIC_CLOUDS now: asked again at every use with the live knobs, else the start's value.\n",
     "/// bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT, read once: the frames between the periodic log\n"
     "/// lines (0: the defaults, FramesFirst then FramesPeriod).\n"
     "u32 ReportFrames() {\n"
     "    static const u32 frames = CL::ReportFramesFrom(std::getenv(\"BB_VOLUMETRIC_CLOUDS_REPORT\"));\n"
     "    return frames;\n"
     "}\n"
     "\n"
     "/// BB_VOLUMETRIC_CLOUDS now: asked again at every use with the live knobs, else the start's value.\n"),
    (CPP,
     "                     double(CL::LitScale(knobs.contrast)), LiveText);\n",
     "                     double(CL::LitScale(knobs.contrast)), LiveText);\n"
     "    if (ReportFrames() != 0) { // bbport (r119f_clouds-open-sky)\n"
     "        BbReport::Printf(\"Volumetric clouds (r119f, BB_VOLUMETRIC_CLOUDS_REPORT): the log lines come every %u frames\\n\",\n"
     "                         ReportFrames());\n"
     "    }\n"),
    (CPP,
     "    if (stats.frames >= (reported_once ? CL::FramesPeriod : CL::FramesFirst)) { // bbport (r119d): a first line early\n",
     "    const u32 report_every = ReportFrames(); // bbport (r119f_clouds-open-sky): BB_VOLUMETRIC_CLOUDS_REPORT\n"
     "    if (stats.frames >= (report_every != 0 ? report_every\n"
     "                                           : (reported_once ? CL::FramesPeriod : CL::FramesFirst))) { // bbport (r119d): a first line early\n"),
    (TEST,
     "    std::puts(\"cloud layer: ok\");\n",
     "    // m. (r119f_clouds-open-sky) BB_VOLUMETRIC_CLOUDS_REPORT: whole numbers 30 to 3000, else 0 (the defaults).\n"
     "    {\n"
     "        assert(ReportFramesFrom(nullptr) == 0u && ReportFramesFrom(\"\") == 0u);\n"
     "        assert(ReportFramesFrom(\"30\") == 30u && ReportFramesFrom(\"90\") == 90u && ReportFramesFrom(\"3000\") == 3000u);\n"
     "        assert(ReportFramesFrom(\"29\") == 0u && ReportFramesFrom(\"3001\") == 0u && ReportFramesFrom(\"0\") == 0u);\n"
     "        assert(ReportFramesFrom(\"9x\") == 0u && ReportFramesFrom(\"-90\") == 0u && ReportFramesFrom(\"1.5\") == 0u);\n"
     "        assert(ReportFramesFrom(\"99999999999999999999\") == 0u && ReportFramesFrom(\" 90\") == 0u);\n"
     "        assert(ReportFramesLeast == 30u && ReportFramesMost == 3000u && FramesFirst < FramesPeriod);\n"
     "    }\n"
     "    std::puts(\"cloud layer: ok\");\n"),
    (README,
     "| `BB_VOLUMETRIC_CLOUDS_THICK` | The slab's thickness",
     "| `BB_VOLUMETRIC_CLOUDS_REPORT` | A test aid: the frames between the layer's periodic log lines (the first one too), 30 to 3000, whole numbers. Without it the first set comes after 200 frames and then every 600, which averages the sky share over a whole walk; with `90` a test gets a `sky px share` line every few seconds. The start says `Volumetric clouds (r119f, ...)` when it is set | unset |\n"
     "| `BB_VOLUMETRIC_CLOUDS_THICK` | The slab's thickness"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the header, the code and the test agree."""
    params, cpp, readme, test = texts[PARAMS], texts[CPP], texts[README], texts[TEST]
    for text in ("ReportFramesLeast = 30, ReportFramesMost = 3000;", "return v >= ReportFramesLeast ? v : 0;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_REPORT` |")]
    if len(rows) != 1 or "30 to 3000" not in rows[0] or "200 frames" not in rows[0] or "every 600" not in rows[0]:
        raise SystemExit("tie check: README REPORT row against ReportFramesLeast / Most and the defaults")
    if "FramesFirst = 200;" not in params or "FramesPeriod = 600;" not in params:
        raise SystemExit("tie check: the README's 200 and 600")
    if cpp.count('std::getenv("BB_VOLUMETRIC_CLOUDS_REPORT")') != 1 or cpp.count("ReportFrames()") != 4:
        raise SystemExit("tie check: cpp ReportFrames uses (definition, once-line twice, hook)")
    if "ReportFramesFrom(\"3000\") == 3000u" not in test or "ReportFramesFrom(\"29\") == 0u" not in test:
        raise SystemExit("tie check: the test's bounds")
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119F_ROOT)" % ROOT)
    files = []
    for path, _, _ in EDITS:
        if path not in files:
            files.append(path)
    plan, texts_now = {}, {}
    for path in files:
        raw, eol, cur = load(path)
        mine = [e for e in EDITS if e[0] == path]
        done = sum(cur.count(new) == 1 for _, old, new in mine)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for _, old, new in mine)
        if done == len(mine):
            state = "applied"
        elif todo == len(mine):
            state = "clean"
        else:
            bad = [old[:60] for _, old, new in mine if not (cur.count(new) == 1 or (cur.count(old) == 1 and cur.count(new) == 0))]
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (is r119e applied? "
                             "is another patch editing the same text?) first failing anchor: %r"
                             % (path, done, len(mine), todo, bad[:1]))
        plan[path] = (raw, eol, cur, state)
        texts_now[path] = cur
    states = {p[3] for p in plan.values()}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (k, v[3]) for k, v in plan.items()))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks(texts_now)
            print("applied (text checks pass)")
        else:
            after = {}
            for path in files:
                cur = plan[path][2]
                for p, old, new in EDITS:
                    if p == path:
                        cur = cur.replace(old, new, 1)
                after[path] = cur
            text_checks(after)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(files), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        outs, after = [], {}
        for path in files:
            raw, eol, cur, _ = plan[path]
            for p, old, new in EDITS:
                if p == path:
                    cur = cur.replace(old, new, 1)
            after[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(after)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                open(full + TMP, "wb").write(data)
                os.replace(full + TMP, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                if os.path.exists(os.path.join(ROOT, path) + TMP):
                    os.remove(os.path.join(ROOT, path) + TMP)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(files), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path in files:
        raw, eol, cur, _ = plan[path]
        for p, old, new in reversed(EDITS):
            if p == path:
                if cur.count(new) != 1:
                    raise SystemExit("%s: edit not found exactly once: %r" % (path, new[:70]))
                cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files edited back)" % len(files))


main()
