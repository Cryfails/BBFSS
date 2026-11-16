# r60c_moving-shadow-steps: FEATURE patch (lamp work; owner, build 72, 2026-11-16: "The shadows still look
# blocky or choppy during movement, but it's not as noticeable."). Off by default behind
# BB_LAMP_SHADOW_MOVING_SMOOTH=1 (environment, read once). NO shader change, no new ray, no new memory.
#
# Finding (read-only study of the tree and of the owner's log owner_b72_run1.log): the owner's build 72 run
# had the lamp shadows at the r42 defaults (half resolution, centred window 2, soft follow, history 0.90)
# and NONE of the three built moving-edge fixes: r93 (BB_LAMP_SHADOW_SPATIAL, a 3x3 same-surface pre-filter
# of the answer the history takes in), r103 + r103b (BB_LAMP_SHADOW_YOUNG, a 5x5 same-surface mean for
# pixels whose history the guards just cut) and r101 (BB_LAMP_SHADOW_MOVING_EDGE, a half-resolution 2x2
# block's answer is shared only once it has settled). The log holds no r93, r101 or r103 line, and the
# "lampshadow" row of Feature-BBFSSLive.ps1 sets only BB_LAMP_SHADOW_FLAME and BB_LAMP_SHADOW_LAYERS. Those
# three fixes are the joint bilateral filter this task asks for (the weights are depth plane tests: 1 cm +
# 0.5% of the distance; the share is the history's age, so it acts only while the shadow moves), the
# variance-free "clamp, do not reset" is r103's young share, and none needs a new ray. So the owner saw the
# moving edge without any of them. The smallest change is one knob that turns the three on together, each
# only where the environment has not set it (an explicit BB_LAMP_SHADOW_SPATIAL=0 etc. wins), so that the
# Feature script, the menu and a slot job carry ONE name.
#
# What stays open after the three (not drafted: each needs shader work that cannot be judged without a
# 4K run, and the owner's rule is one change at a time): (1) TAKEN pixels (half resolution, the second
# pass's block sharing) skip the blend, so r93 and r103 never touch them; r101 keeps them off young
# blocks only; (2) the first pass's windows are 2 px apart (a stride-2 lattice: 1 pixel in 4 differs);
# (3) DLSS: the lamp term has no sub-pixel jitter and the surface's motion vectors make DLSS drop its
# history where a shadow moves against them (a 1080p step shows as 2x2 output pixels): a DLSS-side
# bias mask, not a lamp-pass change.
#
# Off (the default): LampMovingSmoothApply reads one environment variable once, finds it unset or 0 and
# returns before it writes anything: no environment variable is set, nothing else in the program differs
# (no shader, no uniform, no word). On: it calls _putenv_s (Windows) or setenv (else) for the knobs of the
# three patches that are unset or empty, BEFORE PointShadow's constructor reads them (ReadLampShadowTune
# and the first calls of LampYoungValue and LampMovingEdgeValue come after it), prints one line and
# counts; the three patches then behave as with their own knobs set.
#
# Files: NEW renderer_vulkan/lamp_moving_smooth.h; vk_point_shadow.cpp (an include, one call before the
# constructor's ReadLampShadowTune, one line after r103's LampYoungLine in the periodic lamp line);
# README.md (a row before the BB_LAMP_SHADOW_MOVING_EDGE row).
# Needs r93, r101, r103 applied for the knob to do anything (the header only sets their environment
# variables; the other patches read them as before). Cost: the three patches' (r93 +0.02 to +0.06 ms
# estimated, r103 about the same, r101 more second-pass rays while moving, at most the full-resolution pass
# there; none measured as a bundle). Memory: none beyond theirs.
#
# Use: python -I -X utf8 r60c_moving-shadow-steps.py check | apply | revert
# Root: R60C_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r60c_backup next to this script; revert takes out exactly what apply inserted (each inserted text is
# found by itself, once) and removes the new header.
import os, sys

ROOT = os.environ.get("R60C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r60c_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
C = RV + "vk_point_shadow.cpp"
NEW = RV + "lamp_moving_smooth.h"
R = "README.md"

HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r60c_moving-shadow-steps): BB_LAMP_SHADOW_MOVING_SMOOTH, one knob for the three moving-edge
// fixes of the lamp shadows. Behind a moving shadow the lamp pass's guards against trails give a
// pixel's history up and it shows this frame's bare ray, 0 or 1, for a frame or two (blocky, hatched
// edges that travel with the shadow; at half resolution also 2x2 squares). r93 (BB_LAMP_SHADOW_SPATIAL),
// r103 (BB_LAMP_SHADOW_YOUNG, with r103b's standing rule) and r101 (BB_LAMP_SHADOW_MOVING_EDGE) smooth
// that without a new ray; each has its own knob, off by default. 0 or not set (the default): nothing
// here does anything. 1 (any whole number but 0): the three knobs that the environment has not set (or
// has set to nothing) are set to 1 before PointShadow reads them. A knob the environment set is left as
// it is, so BB_LAMP_SHADOW_MOVING_SMOOTH=1 BB_LAMP_SHADOW_YOUNG=0 turns the other two on only.
// No Vulkan here.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#ifdef _WIN32
#include <stdlib.h> // _putenv_s
#endif

namespace Vulkan {

namespace LampMovingSmoothDetail {
inline bool on = false;                 ///< the knob is on
inline std::uint32_t set_by_preset = 0; ///< knobs this preset set
inline std::uint32_t left_to_env = 0;   ///< knobs the environment had set (left as they were)
inline std::uint32_t lines = 0;         ///< periodic lines printed

inline bool Parse(const char* text) {
    if (!text || !text[0]) {
        return false;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    return end != text && *end == '\0' && value != 0;
}

inline void Set(const char* name, const char* value) {
    if (const char* have = std::getenv(name); have && have[0]) {
        ++left_to_env;
        return;
    }
#ifdef _WIN32
    const bool ok = _putenv_s(name, value) == 0;
#else
    const bool ok = setenv(name, value, 1) == 0;
#endif
    if (ok) {
        ++set_by_preset;
    }
}
} // namespace LampMovingSmoothDetail

/// PointShadow's constructor calls this first, before the lamp knobs are read: with the knob on, it sets
/// BB_LAMP_SHADOW_SPATIAL, BB_LAMP_SHADOW_YOUNG and BB_LAMP_SHADOW_MOVING_EDGE to 1 where they are not
/// set, and says so once. With the knob off or not set it reads one variable, once, and does nothing else.
inline void LampMovingSmoothApply() {
    static const bool done = [] {
        namespace D = LampMovingSmoothDetail;
        D::on = D::Parse(std::getenv("BB_LAMP_SHADOW_MOVING_SMOOTH"));
        if (!D::on) {
            return true;
        }
        D::Set("BB_LAMP_SHADOW_SPATIAL", "1");
        D::Set("BB_LAMP_SHADOW_YOUNG", "1");
        D::Set("BB_LAMP_SHADOW_MOVING_EDGE", "1");
        std::printf("Ray traced lamps (r60c): moving shadow smoothing on (BB_LAMP_SHADOW_MOVING_SMOOTH): "
                    "BB_LAMP_SHADOW_SPATIAL, _YOUNG and _MOVING_EDGE (r93, r103 + r103b, r101) set to 1 "
                    "where the environment had not set them (%u set here, %u left as the environment "
                    "has them); no new rays; the r93, r103 and r101 lines say what each does\n",
                    unsigned(D::set_by_preset), unsigned(D::left_to_env));
        return true;
    }();
    (void)done;
}

/// PointShadow's periodic lamp line (every 600 frames), a short line of its own, only with the knob on.
inline void LampMovingSmoothLine() {
    namespace D = LampMovingSmoothDetail;
    if (!D::on) {
        return;
    }
    ++D::lines;
    std::printf("Ray traced lamps (r60c): moving shadow smoothing on, %u knobs set by it and %u left to the "
                "environment, line %u\n",
                unsigned(D::set_by_preset), unsigned(D::left_to_env), unsigned(D::lines));
}

} // namespace Vulkan
'''

ROW = ("| `BB_LAMP_SHADOW_MOVING_SMOOTH` | Lamp shadows that move. `1`: turns on `BB_LAMP_SHADOW_SPATIAL`, "
       "`BB_LAMP_SHADOW_YOUNG` (with its standing rule) and `BB_LAMP_SHADOW_MOVING_EDGE` together, each one "
       "only where the environment has not set it, so the blocky or choppy edge of a shadow that moves "
       "(a walking torch or lantern, an enemy under a street lamp) is filtered by this frame's answers "
       "on the pixel's own surface where its history was just given up, with no new ray; a knob set "
       "in the environment wins. Needs those three patches built in | `0` |\n")

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
C: [
('#include "video_core/renderer_vulkan/lamp_young_pixels.h" // bbport (r103_lamp-young-pixels)\n',
 "",
 '#include "video_core/renderer_vulkan/lamp_moving_smooth.h" // bbport (r60c_moving-shadow-steps)\n'),
("    tune = ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); });\n",
 "    LampMovingSmoothApply(); // bbport (r60c_moving-shadow-steps): BB_LAMP_SHADOW_MOVING_SMOOTH, before the knobs below are read\n",
 ""),
("    LampYoungLine(); // bbport (r103_lamp-young-pixels): a short line after the r42 line, only with the knob set\n",
 "",
 "    LampMovingSmoothLine(); // bbport (r60c_moving-shadow-steps): a short line after r103's, only with the knob on\n"),
],
}


def readme_edit(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_MOVING_EDGE` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_MOVING_EDGE row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", ROW, "")


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return [readme_edit(text)] if path == R else EDITS[path]


def text_checks(texts, header):
    for want in ("LampMovingSmoothApply();", "LampMovingSmoothLine();", "lamp_moving_smooth.h"):
        if texts[C].count(want) != 1:
            raise SystemExit("text check: %s holds %r %d times, wanted 1" % (C, want, texts[C].count(want)))
    c = texts[C]
    # the preset runs before the tune is read (the knobs are read at the constructor's next line)
    if not c.find("LampMovingSmoothApply();") < c.find("tune = ReadLampShadowTune("):
        raise SystemExit("text check: the preset does not run before ReadLampShadowTune")
    # the three knob names the header sets are the ones the three patches read
    for name in ("BB_LAMP_SHADOW_SPATIAL", "BB_LAMP_SHADOW_YOUNG", "BB_LAMP_SHADOW_MOVING_EDGE"):
        if header.count('"%s"' % name) != 1:
            raise SystemExit("text check: header does not set %s once" % name)
    row = [l for l in texts[R].split("\n") if l.startswith("| `BB_LAMP_SHADOW_MOVING_SMOOTH` |")]
    if len(row) != 1:
        raise SystemExit("text check: README row count %d" % len(row))


def state_of(cur, eds, path):
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
        raise SystemExit("%s is not a source tree root (set R60C_ROOT)" % ROOT)
    # the three patches this one switches on must be in the tree (their knobs are read there)
    for what, path, key in (("r93", RV + "lamp_shadow_tune.h", "BB_LAMP_SHADOW_SPATIAL"),
                            ("r103", RV + "lamp_young_pixels.h", "BB_LAMP_SHADOW_YOUNG"),
                            ("r101", RV + "lamp_moving_edge.h", "BB_LAMP_SHADOW_MOVING_EDGE")):
        try:
            ok = key in open(os.path.join(ROOT, path), "rb").read().decode("utf-8")
        except OSError:
            ok = False
        if not ok:
            raise SystemExit("%s is not applied (%s does not read %s)" % (what, path, key))
    new_full = os.path.join(ROOT, NEW)
    new_present = os.path.exists(new_full)
    plan = []
    for path in (C, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if (state == "applied") != new_present:
        raise SystemExit("mixed state: edits %s but %s %s" % (state, NEW, "exists" if new_present else "is missing"))
    if new_present:
        eol_new = open(new_full, "rb").read()
        if eol_new.decode("utf-8").replace("\r\n", "\n") != HEADER.lstrip("\n"):
            raise SystemExit("%s differs from this script's header" % NEW)

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
            text_checks({p[0]: p[4] for p in plan}, HEADER)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), HEADER)
            print("not applied; would apply (1 new file, %d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts, HEADER)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        eol0 = plan[0][3]
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r60ctmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        open(new_full, "wb").write(HEADER.lstrip("\n").replace("\n", eol0).encode("utf-8"))
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
        tmp = full + ".r60ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    os.remove(new_full)
    print("reverted")


main()
