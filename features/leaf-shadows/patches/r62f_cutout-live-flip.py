# r62f_cutout-live-flip: TOOL patch (test aid; never a feature branch or a pull request). Needs r84
# (live knobs), r87 (its clearance block is the anchor of edit 2), r63 and r62e (the cut-out lamp
# shadows). Because it needs the cut-out feature's code, it rides with that feature's test builds
# (the build tree), not alone on dev/test-tools.
#
# What it does: one running test game can show the same view with the cut-out lamp shadows on and
# then off (and in test view 7), so a before/after picture needs no second game and no camera turn.
#  1. BB_RT_CARD_LAMPS is asked again at every lamp pass (PointShadow::CardLampSet) through the r84
#     live knobs file. A game STARTED with BB_RT_CARD_LAMPS=1 and BB_RT_CARD_ALPHA=2 (so its CARDS
#     builds were made at start, RtShadow::CardLampsWanted, read once, unchanged) binds, while the
#     file sets BB_RT_CARD_LAMPS to anything but 1, the build of before for its lamp pass. That is
#     the switch the pass already makes on its own whenever the TLAS holds no card with
#     CARD_LAMP_MASK, so the plain builds are made and bound in every such game anyway.
#     Why it is the cheapest safe switch: no pipeline is made or rebuilt, no descriptor set is made
#     (the check comes before CardLampReadersNow and the set code), no shader changes, and the TLAS
#     is not touched: the pass is still noted as a card user (NoteCardLampUser above the check), so
#     the cards keep CARD_LAMP_MASK and FORCE_NO_OPAQUE and no mask flip forces a full TLAS build.
#     The build of before traces mask 0x04 with gl_RayFlagsOpaqueEXT, and no card instance carries
#     0x04 (vk_rt_shadow.cpp: card ? 0 : LampMask), so its rays pass every cut-out as in a game with
#     the knob off. CARD_LAMP_MASK (0x08) is read by no other shader (grep), so the sun, the fog,
#     the glass and every other ray see the same scene in both states: the lamp pass alone differs.
#     The value is taken on the host when the pass is recorded and decides the pipeline, the layout
#     and the set together (card_bind), so a flip cannot split one pass; the GPU sees one whole
#     pass of either kind. When it comes back on, the set of before is bound again (same handles).
#  2. BB_LAMP_SHADOW_VIEW is asked again at every Flush (just above r87's clearance block), by
#     ReadLampShadowTune's rule (not set, empty or not a whole number: 0; clamped to 0-7). Every use
#     of the view is per pass (LampTuneWords' bits 8-10; the centred window's split, which views 2,
#     3 and 7 turn off for that pass); the history and the half-resolution answers never hold a
#     view (point_shadow_ray.comp: "The history and the half-resolution answers hold the ratio as
#     always"), so going back to 0 shows the settled picture at once. View 7 colours the cards only
#     in a pass that binds a CARDS build (a pass of before shows 7 as 1).
# Log: "Ray traced lamps (r62f): cut-out lamp shadows now off (live)" / "... now on (live)" and
# "Ray traced lamps (r62f): view N now (BB_LAMP_SHADOW_VIEW, live)", each once at each change taken
# (the slot worker keeps "^Ray traced lamps \(r" lines); nothing periodic. While off, the r63
# 600-frame line counts the passes among those "without (no card with data in the scene)".
#
# Default path (no BB_LIVE_KNOBS_FILE, the players' case): BbLiveKnobs::Knob::Get() then parses the
# environment's text once (Generation() stays 0) and returns it at every call: for BB_RT_CARD_LAMPS
# that is "1" (a game that reaches the check has CardLampsWanted() true, which needs exactly "1"),
# so CardLampSet goes on as before; for BB_LAMP_SHADOW_VIEW the same text and rule the constructor's
# ReadLampShadowTune used, so tune.view is not changed and nothing is said. Cost: one relaxed atomic
# load and a compare per lamp pass (two with the cards), as r87's clearance knob. A game without
# BB_RT_CARD_LAMPS=1 returns from CardLampSet before the new check (no CARDS build: card_set_layout
# null): the card knob is never even read. No shader is changed: every SPIR-V build stays the same.
#
# Limits: the live knob turns the cut-out lamp shadows OFF in a game started with them on, and on
# again; it cannot turn them on in a game started without them (no CARDS builds were made: rule 3
# of bbport_live_knobs.h). BB_RT_CARD_ALPHA stays read once. With BB_LAMP_SHADOW_COLOUR=1 the
# builds of before are COLOUR builds and the CARDS builds are not: the off picture would also be
# coloured; do not combine the two in a before/after.
# After a flip the lamp history needs frames to settle: a pixel's ratio is a running mean holding at
# most LampHistoryFrames = 0.9 / (1 - 0.9) = 9 frames (BB_LAMP_SHADOW_HISTORY 0.9), so a share of
# 1/10 of the new answer comes in each frame: 0.9^22 = 10 %, 0.9^44 = 1 % left of the old shadow
# where the change is small; where it is large (a leaf's full shadow gone) the reject
# (BB_LAMP_SHADOW_REJECT 0.5, fast mean FAST_KEEP 0.6) drops the history within 2-3 frames. With the
# upscaler's own history on top (not measured) about 60 frames; the jobs wait 4 s (120 frames at the
# slot games' 30 FPS cap).
#
# Order: apply after r87 and r62e. Revert this one FIRST, before r87 (whose revert writes its whole
# backup back) and before r63 (edit 1 sits inside r63's CardLampSet text, so r63's own check counts
# one more of its pairs as changed while this is applied).
#
# Files: engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp only (2 inserts; it has
# included bbport_live_knobs.h since r87). README.md is not touched (r84 and r87, the other live
# test knobs, have no rows either: TOOL); the BB_RT_CARD_LAMPS row's "Read at start" stays true for
# every game without a live knobs file.
#
# Use: python -I -X utf8 r62f_cutout-live-flip.py check | apply | revert
# Root: R62F_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the original up
# in r62f_backup next to this script; revert takes out exactly what apply inserted: each inserted
# text is found by itself (exactly once), so a later patch's text between it and its anchor stays.
import os, sys

ROOT = os.environ.get("R62F_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62f_backup")
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
TAG = ".r62ftmp"

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
CARD_ANCHOR = (
    "    if (card_set || card_sets_made < CardSetsMost) {\n"
    "        rt_shadow.NoteCardLampUser();\n"
    "    }\n")
CARD_AFTER = (
    "    // bbport (r62f_cutout-live-flip): TOOL (test aid; needs r84): BB_RT_CARD_LAMPS asked again at\n"
    "    // every pass through the live knobs file, so that one running game shows one view with the\n"
    "    // cut-out lamp shadows and without them. Only a game whose CARDS builds were made (started with\n"
    "    // BB_RT_CARD_LAMPS=1 and BB_RT_CARD_ALPHA=2) gets here. While the file sets it to anything but\n"
    "    // 1, the pass binds its build of before, as it does whenever the TLAS holds no card: no pipeline\n"
    "    // or set is made, and the TLAS is not touched (the pass is noted above, so the cards keep\n"
    "    // CARD_LAMP_MASK); the build of before traces 0x04 alone, which no card carries. The r63\n"
    "    // 600-frame line counts such passes among those without cards. Without BB_LIVE_KNOBS_FILE the\n"
    "    // value is the environment's 1 and nothing changes. Said once at each change.\n"
    "    {\n"
    "        static BbLiveKnobs::Knob<bool> lamps_live{\n"
    "            \"BB_RT_CARD_LAMPS\",\n"
    "            [](const char* text) -> bool { return text != nullptr && std::strcmp(text, \"1\") == 0; }};\n"
    "        static bool told_on = true;\n"
    "        const bool on = lamps_live.Get();\n"
    "        if (on != told_on) {\n"
    "            told_on = on;\n"
    "            std::printf(\"Ray traced lamps (r62f): cut-out lamp shadows now %s (live)\\n\", on ? \"on\" : \"off\");\n"
    "        }\n"
    "        if (!on) {\n"
    "            return {};\n"
    "        }\n"
    "    }\n")

# Before r87's clearance block, not after it: r87's check looks for its whole inserted text, which
# runs from this comment line to the `tune.radius_m = ...` line; text put inside it would make r87
# read as not applied (and its apply would add the block twice).
VIEW_ANCHOR = (
    "    // bbport (r87_live-flip-knobs): TOOL: BB_LAMP_SHADOW_CLEARANCE asked again at every pass (a live\n")
VIEW_BEFORE = (
    "    // bbport (r62f_cutout-live-flip): TOOL (test aid; needs r84): BB_LAMP_SHADOW_VIEW asked again at\n"
    "    // every pass through the live knobs file, by ReadLampShadowTune's rule (not set, empty or not a\n"
    "    // whole number: 0; else clamped to 0-7). Every use of the view is per pass (LampTuneWords, the\n"
    "    // centred window's split below); the history and the half-resolution answers never hold a view.\n"
    "    // Without BB_LIVE_KNOBS_FILE it is the environment's value, which the constructor read: nothing\n"
    "    // changes. Said once at each change.\n"
    "    {\n"
    "        static BbLiveKnobs::Knob<u32> view_knob{\n"
    "            \"BB_LAMP_SHADOW_VIEW\", [](const char* text) -> u32 {\n"
    "                const u32 fallback = LampShadowTune{}.view;\n"
    "                if (text == nullptr || text[0] == 0) {\n"
    "                    return fallback;\n"
    "                }\n"
    "                char* end = nullptr;\n"
    "                const long value = std::strtol(text, &end, 10);\n"
    "                return end != text && LampTuneDetail::Ends(end)\n"
    "                           ? u32(std::clamp(value, 0l, long(LampTuneViewMax)))\n"
    "                           : fallback;\n"
    "            }};\n"
    "        const u32 view_now = view_knob.Get();\n"
    "        if (view_now != tune.view) {\n"
    "            tune.view = view_now;\n"
    "            std::printf(\"Ray traced lamps (r62f): view %u now (BB_LAMP_SHADOW_VIEW, live)\\n\", view_now);\n"
    "        }\n"
    "    }\n")

EDITS = {
    C: [
        (CARD_ANCHOR, "", CARD_AFTER),
        (VIEW_ANCHOR, VIEW_BEFORE, ""),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    c = texts[C]
    for want, n in (('static BbLiveKnobs::Knob<bool> lamps_live{', 1), ('"BB_RT_CARD_LAMPS",', 1),
                    ('static BbLiveKnobs::Knob<u32> view_knob{', 1), ('"BB_LAMP_SHADOW_VIEW", [](const char* text)', 1),
                    ('#include "bbport_live_knobs.h"', 1), ("cut-out lamp shadows now %s (live)", 1),
                    ("view %u now (BB_LAMP_SHADOW_VIEW, live)", 1)):
        if c.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (C, want, c.count(want), n))
    # the card check lies inside CardLampSet: after the user note, before the readers and the set code
    f = c.find("vk::DescriptorSet PointShadow::CardLampSet(bool half) {")
    a = c.find("        rt_shadow.NoteCardLampUser();\n", f)
    b = c.find('static BbLiveKnobs::Knob<bool> lamps_live{', f)
    d = c.find("    const auto r = rt_shadow.CardLampReadersNow();\n", f)
    e = c.find("device.allocateDescriptorSets(", f)
    if not (0 <= f < a < b < d < e):
        raise SystemExit("text check: the live card check is not between NoteCardLampUser and CardLampReadersNow")
    # the view is read before the pass copies the tune (pass_tune) and before LampTuneWords and the split
    v = c.find('static BbLiveKnobs::Knob<u32> view_knob{')
    p = c.find("    LampShadowTune pass_tune = tune;\n")
    w = c.find("LampTuneWords(pass_tune,")
    s = c.find("pass_tune.view != 2 && pass_tune.view != 3")
    if not (0 <= v < p < w and p < s):
        raise SystemExit("text check: the live view is not read before pass_tune, LampTuneWords and the split")
    # the view rule is the one of ReadLampShadowTune (Whole with the default as its fallback, 0..LampTuneViewMax)
    t = open(os.path.join(ROOT, "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"),
             "rb").read().decode("utf-8").replace("\r\n", "\n")
    if t.count('tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, LampTuneViewMax);') != 1 or \
            t.count("std::uint32_t view = 0;") != 1 or "inline bool Ends(const char* end) {" not in t or \
            "return std::uint32_t(std::clamp(value, 0l, long(hi)));" not in t:
        raise SystemExit("text check: ReadLampShadowTune's view rule changed; recheck the live view parse")
    # the card rule is the one of CardLampsWanted (exactly "1")
    r = open(os.path.join(ROOT, "engine/gpu/shadps4/video_core/renderer_vulkan/vk_rt_shadow.cpp"),
             "rb").read().decode("utf-8").replace("\r\n", "\n")
    if r.count('const bool one = std::strcmp(env, "1") == 0;') != 1:
        raise SystemExit("text check: CardLampsWanted's rule changed; recheck the live card parse")
    # no inserted line is wider than 110 columns (the log lines are about 60 characters)
    for line in (CARD_AFTER + VIEW_BEFORE).split("\n"):
        if len(line) > 110:
            raise SystemExit("text check: line longer than 110 columns: %r" % line)


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62F_ROOT)" % ROOT)
    plan = []
    for path in EDITS:
        raw, eol, cur = load(path)
        eds = EDITS[path]
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d file, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            raise SystemExit("REFUSED: already applied; nothing written")
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + TAG
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + TAG
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
