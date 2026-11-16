# r128a_lrt-moving-shadows: FEATURE patch (lamp work, task LRT-T02; owner goals LRT-G011, LRT-G028, LRT-G037, LRT-G040:
# "Moving shadow only really works on a one 4k run", "The square edges are only from shadows in motion", "I see that the
# blocky edges of moving shadows still is there", build 72 at 4K "still look blocky or choppy during movement"). Off by
# default behind BB_LAMP_SHADOW_JITTER=1 (environment, read once).
#
# The third of the three open causes of the blocky moving edge (notes lrt-t02, r60c header): the lamp term carries no
# sub-pixel jitter. The engine draws the scene with a viewport shifted by the upscaler's jitter (Rasterizer: dc.draw_jitter,
# TemporalUpscaler::Jitter(), render pixels, x right, y down; camera_motion.comp reads the depth back as
# scene_uv = uv - jitter / size and a previous pixel as prev_uv * size + previous_jitter). The lamp pass reads that depth but
# rebuilds the surface point P at the pixel's CENTRE (viewPosAt(uv, depth) with uv = (px + 0.5) / size), so it answers "is
# this point in shadow" at the same place of the screen every frame while the colour the upscaler is fed was drawn at a
# jittered place: the shadow edge is a fixed staircase of render pixels that the upscaler can never average into a smooth
# edge, and where a shadow moves it drops its history (nothing in the motion vectors moved) and shows that staircase, 2x2
# output pixels per render pixel at DLSS Performance. A geometry edge does not have this: it is rasterised at the jittered
# place, so the upscaler resolves it.
#
# With the knob on, a pass that averages (HISTORY_BLEND) is told this frame's and the last frame's jitter (4 words at the
# end of its history block, 34 to 37, and the flag HISTORY_JITTER = 32 in the history block's word 0) and
#   (1) viewPosAt builds P at uv - jitter / size: the point the depth value really belongs to (so the lamp's ray starts from,
#       and its answer is the shadow of, the sample the upscaler jitters to; every neighbour read of the pass (the normal,
#       spatialMean's and youngMean's plane tests) goes through viewPosAt and shifts with it, so they stay consistent);
#   (2) the history is looked up at the reprojected place + the previous frame's jitter (the history texel q holds the sample
#       that lay at q + 0.5 - previous jitter): the same rule as camera_motion.comp's previous pixel. A still camera with a
#       jitter that changed lands between two texels, so the bilinear lookup that was exact before now blurs a still shadow
#       by up to the jitter step (at most 1 px; the upscaler's own resolve takes it from there). This is the one cost of the
#       change in the picture, named in the README row; the guards, the frames and the follow state are untouched.
# It does nothing where the jitter is zero (no upscaler, DLSS jitter fade during a fast camera: the words carry 0 and the
# shader's `uv - 0` and `* size + 0` are exact), on a pass that does not average (point lamps), and only a still frame at 4K
# DLSS Performance can show it: judge it as the owner does, a 4K clip of a moving shadow with the knob off and on.
#
# Off (the default): LampJitterAdd reads one static bool (set once from the environment) and returns before it pushes a
# word or sets a flag, so no host word, no flag and no log line differs. The shader's added work with the flag clear: one
# AND on a word it already loaded, `uv -= jit_uv` (two exact subtractions of 0) in viewPosAt, `+ jit_prev_px` (0) in two
# history lookups: no new load, ray, image or memory. On: 4 words a pass that averages (16 bytes, uploaded with the others).
# Cost estimate: ALU only, below the timer's noise (the pass is ray bound: 24 viewPosAt calls of the 5x5 mean add 2 FADD
# each); no measured number (nothing was run). Do not set it with BB_LAMP_SHADOW_JITTER when the upscaler is off: it is then
# 0 and nothing changes.
#
# Files: NEW renderer_vulkan/lamp_jitter.h; host_shaders/point_shadow_ray.comp (all builds; HISTORY_JITTER, two globals, one
# line in viewPosAt, two `was` lines, one block in main); renderer_vulkan/vk_point_shadow.cpp (an include, one call after the
# history block's tail words, one line after r60c's in the periodic lamp lines); renderer_vulkan/vk_camera_motion.h (a getter
# for the jitter after SetJitter); README.md (a row after the BB_LAMP_SHADOW_MOVING_SMOOTH row).
# Not verified (nothing was built or run): the C++ (lamp_jitter.h as a whole, the three call lines); that the lamp pass's
# targets are the render size (the shift is in pixels of the pass, so a pass allocated larger than the viewport is right to
# first order); that every scene depth draw is jittered (a 6-index full-screen draw is not: its surfaces are misplaced by up
# to 1 px, as in any jittered renderer); whether the owner sees it help at 4K. The same file's r60c, r93, r101, r103 and r113/
# r114 edits are untouched (anchors lie on lines of no other patch, bar r60c's include and call lines).
#
# Use: python -I -X utf8 r128a_lrt-moving-shadows.py check | apply | revert
# Root: R128A_ROOT, else <tree>. Line ends kept. apply backs the originals up in r128a_backup next to this script;
# revert takes out exactly what apply put in (each inserted or replaced text is found by itself, once) and removes the header.
import os, sys

ROOT = os.environ.get("R128A_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r128a_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
C = RV + "vk_point_shadow.cpp"
CM = RV + "vk_camera_motion.h"
NEW = RV + "lamp_jitter.h"
R = "README.md"

HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r128a_lrt-moving-shadows): BB_LAMP_SHADOW_JITTER. The lamp pass answers "is this point in shadow" at the
// pixel's centre while the scene the upscaler is fed was drawn through a viewport shifted by its sub-pixel jitter, so a
// lamp shadow's edge is a fixed staircase of render pixels that the upscaler cannot average out and shows where the
// shadow moves (blocky moving edges, 4K DLSS). With the knob on, a pass that averages its history is told this frame's
// and the last frame's jitter (4 words after its history block's tail, word 0 of the block gets HISTORY_JITTER) and
// builds the surface point where the depth value really lies and looks its history up where the last frame's jittered
// sample lay (point_shadow_ray.comp). 0 or not set (the default): nothing here pushes a word or sets a flag. 1 (any
// whole number but 0): on. The jitter is zero without an upscaler: nothing changes then. No Vulkan here.

#include <array>
#include <bit>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

namespace Vulkan {

inline constexpr std::uint32_t LampJitterWords = 4;        ///< the history block's words 34 to 37
inline constexpr std::uint32_t LampHistoryJitterFlag = 32; ///< point_shadow_ray.comp HISTORY_JITTER

namespace LampJitterDetail {
inline std::uint32_t carried = 0;  ///< passes that carried the words since the last periodic line
inline std::uint32_t shifted = 0;  ///< of them, with a shift that is not 0
inline std::uint32_t no_room = 0;  ///< passes the 4 words did not fit after (the data buffer was full)
inline std::uint32_t lines = 0;    ///< periodic lines printed
inline bool have_frame = false;
inline std::uint32_t frame = 0;    ///< the frame the two shifts below belong to
inline std::array<float, 2> now{}; ///< this frame's jitter, render pixels
inline std::array<float, 2> before{}; ///< the jitter of the frame before the last one that had a pass

inline bool Parse(const char* text) {
    if (!text || !text[0]) {
        return false;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    return end != text && *end == '\0' && value != 0;
}
} // namespace LampJitterDetail

/// BB_LAMP_SHADOW_JITTER, read once; says so once when on.
inline bool LampJitterOn() {
    static const bool on = [] {
        const bool value = LampJitterDetail::Parse(std::getenv("BB_LAMP_SHADOW_JITTER"));
        if (value) {
            std::printf("Ray traced lamps (r128a): sample jitter on (BB_LAMP_SHADOW_JITTER): a lamp pass that "
                        "averages its history builds each pixel's surface point where the upscaler's jittered "
                        "scene depth really lies and looks its history up where the last frame's jittered "
                        "sample lay; nothing changes where the jitter is 0 (no upscaler)\n");
        }
        return value;
    }();
    return on;
}

/// vk_point_shadow.cpp calls this right after it pushed the history block (its word 0 is at `history_at`, the tail words
/// 30 to 33 are the last pushed): with the knob on and `blend` (the pass averages) it adds the four words (this frame's
/// jitter x, y; the jitter of the frame before, x, y: one pass of a frame has the same as the others, and the frame before
/// is the last frame that had a pass) and sets the flag in word 0. Off, or no room: does nothing at all.
inline void LampJitterAdd(std::vector<std::uint32_t>& data, std::uint32_t history_at, std::uint32_t limit_words,
                          bool blend, std::uint32_t frame_index, const std::array<float, 2>& jitter) {
    namespace D = LampJitterDetail;
    if (!blend || !LampJitterOn()) {
        return;
    }
    if (data.size() + LampJitterWords > limit_words) {
        ++D::no_room;
        return;
    }
    if (!D::have_frame || D::frame != frame_index) {
        D::before = D::have_frame ? D::now : jitter; // the very first frame has no earlier one (its history is not read)
        D::now = jitter;
        D::frame = frame_index;
        D::have_frame = true;
    }
    data.push_back(std::bit_cast<std::uint32_t>(D::now[0]));
    data.push_back(std::bit_cast<std::uint32_t>(D::now[1]));
    data.push_back(std::bit_cast<std::uint32_t>(D::before[0]));
    data.push_back(std::bit_cast<std::uint32_t>(D::before[1]));
    data[history_at] |= LampHistoryJitterFlag;
    ++D::carried;
    if (D::now[0] != 0.0f || D::now[1] != 0.0f) {
        ++D::shifted;
    }
}

/// PointShadow's periodic lamp lines: a short line of its own, only with the knob on.
inline void LampJitterLine() {
    namespace D = LampJitterDetail;
    if (!LampJitterOn()) {
        return;
    }
    ++D::lines;
    std::printf("Ray traced lamps (r128a): sample jitter carried by %u lamp passes since the last line, %u of them "
                "with a shift that is not 0 (last shift %.2f, %.2f px; before it %.2f, %.2f), %u without room, "
                "line %u\n",
                unsigned(D::carried), unsigned(D::shifted), double(D::now[0]), double(D::now[1]),
                double(D::before[0]), double(D::before[1]), unsigned(D::no_room), unsigned(D::lines));
    D::carried = D::shifted = D::no_room = 0;
}

} // namespace Vulkan
'''

ROW = ("| `BB_LAMP_SHADOW_JITTER` | Lamp shadows that move, at 4K with an upscaler (DLSS). `1`: the lamp pass builds each "
       "pixel's surface point where the scene depth really lies (the depth is drawn through a viewport shifted by the "
       "upscaler's sub-pixel jitter; the pass used the pixel's centre) and looks its history up where the last frame's "
       "jittered sample lay, so the shadow is sampled where the upscaler samples the colour and it can average a shadow "
       "edge into a smooth edge instead of showing a fixed staircase of render pixels where a shadow moves. The cost in "
       "the picture: a still shadow is blurred by up to the size of the jitter step (at most one render pixel) by the "
       "history's bilinear lookup. It does nothing without an upscaler (the jitter is 0), with `BB_LAMP_SHADOW_WINDOW` "
       "0 or 1 only as far as the passes that average run, and not on a pass that averages nothing (sharp lamps). No "
       "extra ray, image or memory (4 words a pass). Part of the moving shadow work: judge it in a 4K clip of a moving "
       "shadow, on against off. `0`: as before | `0` |\n")

B = "\n"  # (edits below are written with \n; the file's line ends are put back on write)

# insert edits: (anchor, before, after); the anchor stays, `before` goes in front of it, `after` behind it.
# replace edits: ("R", old, new); revert puts old back.
EDITS = {
S: [
("shared mat4 shared_inverse;\n",
 "",
 "// bbport (r128a_lrt-moving-shadows): BB_LAMP_SHADOW_JITTER=1 (lamp_jitter.h): HISTORY_JITTER, set in the history block's word 0\n"
 "// by vk_point_shadow.cpp only on a pass that averages, says words 34 to 37 hold this frame's jitter and the last frame's\n"
 "// (render pixels, x right, y down: Rasterizer's viewport shift, TemporalUpscaler::Jitter). The scene depth was rasterised\n"
 "// through that shifted viewport, so the point a depth texel holds lies at uv - jit_uv, not at the pixel's centre (as in\n"
 "// camera_motion.comp); a history texel holds the sample that lay at its centre - the last frame's jitter, so a reprojected\n"
 "// place is looked up at + jit_prev_px. Both stay 0 without the flag: `uv - 0` and `+ 0` are exact.\n"
 "const uint HISTORY_JITTER = 32u;\n"
 "vec2 jit_uv = vec2(0.0);\n"
 "vec2 jit_prev_px = vec2(0.0);\n"),
("vec3 viewPosAt(vec2 uv, float depth) {\n",
 "",
 "    uv -= jit_uv; // bbport (r128a_lrt-moving-shadows): where the depth value really lies (0 unless HISTORY_JITTER)\n"),
("R",
 "        return false;\n    }\n    const vec2 ndc = clip.xy / clip.w;\n"
 "    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size;\n",
 "        return false;\n    }\n    const vec2 ndc = clip.xy / clip.w;\n"
 "    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size + jit_prev_px; // bbport (r128a_lrt-moving-shadows)\n"),
("R",
 "        return;\n    }\n    const vec2 ndc = clip.xy / clip.w;\n"
 "    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size;\n",
 "        return;\n    }\n    const vec2 ndc = clip.xy / clip.w;\n"
 "    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size + jit_prev_px; // bbport (r128a_lrt-moving-shadows)\n"),
("    const uint history_flags = history_at != 0u ? data.d[history_at] : 0u;\n",
 "",
 "    if ((history_flags & HISTORY_JITTER) != 0u) { // bbport (r128a_lrt-moving-shadows): BB_LAMP_SHADOW_JITTER (before any viewPosAt)\n"
 "        jit_uv = vec2(word(history_at + 34u), word(history_at + 35u)) / size;\n"
 "        jit_prev_px = vec2(word(history_at + 36u), word(history_at + 37u));\n"
 "    }\n"),
],
C: [
('#include "video_core/renderer_vulkan/lamp_moving_smooth.h" // bbport (r60c_moving-shadow-steps)\n',
 "",
 '#include "video_core/renderer_vulkan/lamp_jitter.h" // bbport (r128a_lrt-moving-shadows)\n'),
("        data.insert(data.end(), tail.begin(), tail.end());\n",
 "",
 "        LampJitterAdd(data, history_at, DataWords, blend, frame_index, camera_motion.Jitter()); // bbport (r128a_lrt-moving-shadows): 0 words with the knob off\n"),
("    LampMovingSmoothLine(); // bbport (r60c_moving-shadow-steps): a short line after r103's, only with the knob on\n",
 "",
 "    LampJitterLine(); // bbport (r128a_lrt-moving-shadows): a short line after r60c's, only with the knob on\n"),
],
CM: [
("    void SetJitter(std::array<float, 2> value) noexcept {\n        previous_jitter = jitter;\n        jitter = value;\n    }\n",
 "",
 "    /// bbport (r128a_lrt-moving-shadows): this frame's jitter (render pixels, x right, y down), as SetJitter took it.\n"
 "    [[nodiscard]] std::array<float, 2> Jitter() const noexcept {\n        return jitter;\n    }\n"),
],
}


def readme_edit(text):
    """The README row goes after the BB_LAMP_SHADOW_MOVING_SMOOTH row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_MOVING_SMOOTH` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_MOVING_SMOOTH row is there %d times, wanted 1" % len(lines))
    return (lines[0] + "\n", "", ROW)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == R:
        return [readme_edit(text)]
    return EDITS[path]


def is_rep(e):
    return e[0] == "R"


def state_of(cur, eds, path):
    """'applied', 'clean' or refuse. Insert: anchor once and the inserted texts once (applied) or never (clean).
    Replace: the new text once and the old none (applied), or the old once and the new none (clean)."""
    done = todo = 0
    for e in eds:
        if is_rep(e):
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: replaced text found %d times, new text %d times: %r" % (path, no, nn, old[:70]))
            continue
        anchor, before, after = e
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


def apply_text(cur, eds):
    for e in eds:
        if is_rep(e):
            cur = cur.replace(e[1], e[2], 1)
        else:
            anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after, 1)
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if is_rep(e):
            cur = cur.replace(e[2], e[1], 1)
        else:
            for part in (e[2], e[1]):
                if part:
                    cur = cur.replace(part, "", 1)
    return cur


def text_checks(texts, header):
    s = texts[S]
    for want, n in (("const uint HISTORY_JITTER = 32u;", 1), ("vec2 jit_uv = vec2(0.0);", 1),
                    ("vec2 jit_prev_px = vec2(0.0);", 1), ("uv -= jit_uv;", 1), ("+ jit_prev_px;", 2),
                    ("history_at + 34u", 1), ("history_at + 35u", 1), ("history_at + 36u", 1), ("history_at + 37u", 1),
                    ("(history_flags & HISTORY_JITTER) != 0u", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # the globals come before viewPosAt (GLSL declares before use) and the flag read comes before the first use in main
    if not (s.find("vec2 jit_uv = vec2(0.0);") < s.find("vec3 viewPosAt(vec2 uv, float depth) {")):
        raise SystemExit("text check: jit_uv is declared after viewPosAt")
    k = s.find("(history_flags & HISTORY_JITTER) != 0u")
    first_use = min(i for i in (s.find("P = viewPosAt(uv, depth);"), s.find("blendHistory(P"), s.find("historyAt(P")) if i > 0)
    if not k < first_use:
        raise SystemExit("text check: the jitter words are read after the first viewPosAt of main")
    # the shader's flag value equals the header's, and the words 34 to 37 are the history block's words after the tail (30 to 33)
    if "LampHistoryJitterFlag = 32;" not in header or "LampJitterWords = 4;" not in header:
        raise SystemExit("text check: header flag or word count differs from the shader (32, 4 words: 34 to 37)")
    if "constexpr u32 HistoryWords = 2 + 12 + 16 + LampHistoryTailWords;" not in texts[C]:
        raise SystemExit("text check: HistoryWords changed: words 34 to 37 are no longer the words after the tail")
    # the call comes after the tail words are pushed and before pending_view (the block is complete when it adds its flag)
    c = texts[C]
    a, b = c.find("data.insert(data.end(), tail.begin(), tail.end());"), c.find("LampJitterAdd(data, history_at")
    d = c.find("pending_view = camera.view;")
    if not (0 <= a < b < d):
        raise SystemExit("text check: LampJitterAdd is not between the tail words and pending_view")
    if c.count("LampJitterAdd(") != 1 or c.count("LampJitterLine();") != 1 or c.count("lamp_jitter.h") != 1:
        raise SystemExit("text check: vk_point_shadow.cpp hook lines are not once each")
    row = [l for l in texts[R].split("\n") if l.startswith("| `BB_LAMP_SHADOW_JITTER` |")]
    if len(row) != 1 or "at most one render pixel" not in row[0]:
        raise SystemExit("text check: README row")
    if texts[CM].count("std::array<float, 2> Jitter() const noexcept") != 1:
        raise SystemExit("text check: CameraMotion::Jitter")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R128A_ROOT)" % ROOT)
    plan = []
    eol_of = None
    for path in (S, C, CM, R):
        raw, eol, cur = load(path)
        eol_of = eol_of or eol
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    newfull = os.path.join(ROOT, NEW)
    new_state = "applied" if os.path.exists(newfull) else "clean"
    states = {p[5] for p in plan} | {new_state}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", %s %s" % (NEW, new_state))
    state = states.pop()
    header_eol = HEADER.replace("\n", eol_of)

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            if open(newfull, "rb").read().decode("utf-8").replace("\r\n", "\n") != HEADER:
                raise SystemExit("text check: %s differs from the script's header" % NEW)
            text_checks({p[0]: p[4] for p in plan}, HEADER)
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts(), HEADER)
            print("not applied; would apply (%d files and 1 new, %d edits; text checks on the result pass)"
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
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r128atmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        open(newfull, "wb").write(header_eol.encode("utf-8"))
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r128atmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    os.remove(newfull)
    print("reverted")


main()
