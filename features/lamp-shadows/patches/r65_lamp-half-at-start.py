# r65_lamp-half-at-start: the ray traced lamp pass's pipelines, the half-resolution build among
# them, are made at start (in PointShadow's constructor) instead of during play. No change of any
# picture. check|apply|revert (revert restores byte for byte). On top of <tree> as it is on
# 2026-11-15 (r53, r57 and r60 applied). The tree: the one the environment variable R65_ROOT names;
# without it the current directory. Nothing is changed in place: every new text is written beside
# its target and moved over it, and a failure puts back what was already moved. Every edit is an
# exact text that must be found exactly once (no whole-file hash: r61 may land on these files
# before or after this one; no hunk here touches LampWindowDefault or the lines around its use).
# Files keep their line ends (all three are CRLF). The original files are in r65_orig beside this
# script, the patched ones in r65_work. r54 and r62 do not touch these three files.
#
# WHY. PointShadow::Ready (vk_point_shadow.cpp) made the pass's pipelines (the screen-space point
# shadow build, the ray traced build or its centred form of r60, the sampler, the 1 MB light
# buffer) the first time OnLightDraw saw a lamp draw, and PointShadow::HalfReady made the
# half-resolution build (its plain or centred form, the counters and their readback) the first
# time Flush ran a lamps-apart pass with graphics_lamp_shadow_half=1 or BB_LAMP_SHADOW_HALF=1.
# Both are during play, on the draw thread, and both call EffectPass::Create, which compiles at
# once (vkCreateComputePipelines with no VkPipelineCache and no compile thread: every effect pass
# of this engine does the same; the game's own pipelines have their own cache and threads, which
# effect passes do not use). The sun's ray traced pipelines are made in RtShadow's constructor
# (RtShadow::Setup), at start. So the lamp pass now does the same: the cost moves to start and the
# stall in play goes. Its size is a guess, not measured: tens to a few hundred ms for a ray query
# build with a cold driver cache (the first run of every new build), a few ms with a warm one. The
# new log lines measure it.
#
# WHAT.
#  vk_point_shadow.cpp:
#   - PointShadow::PointShadow, at its end: unless BB_LAMP_SHADOW_AT_START=0, when the lamp pass
#     is wanted at start (the test OnLightDraw makes: the point shadow effect on, or RaysWanted),
#     Ready() runs here with at_start set. Else one line says the pipelines are made on first use.
#     Ready reads nothing that is not fixed by then: RtShadow::Capturing (set in RtShadow's
#     constructor, which runs just before this one in Rasterizer::Rasterizer), this constructor's
#     knobs (tune, half_env), lantern.ini (loaded in bbgpu_init before the renderer). No other
#     thread sees this object yet (the rasterizer is bound to the GPU later in its constructor).
#   - PointShadow::HalfWanted (new): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half;
#     Flush's half_on now calls it (the same expression as before, moved), so Ready and Flush
#     cannot disagree.
#   - PointShadow::Ready, at its end: when it runs at start (at_start), HalfReady() when
#     ray_pipeline && RaysWanted() && HalfWanted() (Flush makes it only for a ray traced pass:
#     use_rays needs ray_pipeline, and RaysWanted or an apart batch, which needs RaysWanted). Ready
#     run later (BB_LAMP_SHADOW_AT_START=0, or the lamp pass switched on in play) does not: the
#     build is then made by Flush on first use exactly as before, and so is a switch to the half
#     resolution later (menu). Then a log line with the time Ready took.
#   - Flush: half_asked set where HalfReady was first called before r65 (a lamps-apart ray traced
#     pass with the half resolution on); OnFrameEnd's 600-frame counters line waits for it, as it
#     waited for HalfReady before (else a build made at start would print lines of zeros every
#     600 frames from the title screen on). Log only.
#   - PointShadow::HalfReady: a log line with the time it took and whether at start or during play.
#   - Comments that said "made the first time a pass wants it" now also say "or at start".
#  vk_point_shadow.h: bool at_start (Ready runs from the constructor: its log lines say so);
#   bool half_asked (above);
#   HalfWanted() declared; the comment on the half resolution says when the build is made.
#  docs/renderer-performance-0.9.43.md: a bullet under "Not restored by the switch" for the
#   env-only knob BB_LAMP_SHADOW_AT_START (no experiment bit).
# THE SWITCH: BB_LAMP_SHADOW_AT_START, read once at start; 0 (only "0") = the old timing, on first
# use (Ready at the first lamp draw, HalfReady at the first half-resolution pass; only the new log
# lines differ). Picture: the same either way (the same objects, made by the same code).
# COST: at start, the time of the builds (now in the log); 1 MB of device memory and the pipelines
# from start rather than from the first lamp draw, only when the lamp pass is on at start. In play:
# none added; the first-use stall goes. Per frame: nothing (HalfWanted is the old expression).
#
# OTHER FIRST-USE WORK OF THE LAMP PASS (looked at, not changed here):
#  - lamp[2] images and their clear (BeginApart: EnsureImage, then a clear with a layout change at
#    the first apart batch and after each size change): KEEP LAZY. Their size is the game's light
#    target (or its proxy at reduced resolution), known only at the first lamp draw; the first
#    frame clears them anyway; creating an image is far cheaper than a pipeline compile (guess:
#    well under 1 ms) and HasRoom must see the real size.
#  - history[2] and follow[2] (Flush, made at the pass's size; laid out and the follow images
#    zeroed in the first pass's commands; history_fresh starts the history again): KEEP LAZY, same
#    reason (size), and a new history must start empty at a new size anyway.
#  - answers (r60, only with BB_LAMP_SHADOW_WINDOW=2; made in Flush, laid out on first use, never
#    cleared): KEEP LAZY: size, and 16.6 MB at 1920x1080 should not be held when 2 is not used.
#  - half_answers (Flush, half the pass's size, laid out on first use): KEEP LAZY (size).
#  - half_counts zeroed by fillBuffer in the first half pass's commands (half_clear): KEEP: 64
#    bytes on the GPU, no CPU stall; the buffer itself is now made at start with HalfReady.
#  - half_readback (host memory, zeroed in HalfReady): MOVED TO START with HalfReady. The
#    600-frame counter line (OnFrameEnd) starts at the first pass that asks, as before (half_asked).
#  - snapshot[2] images (only when lamps are not apart): KEEP LAZY (size; not the default path).
#  - First-call getenv of BB_RT_LAMP_APART, BB_RT_LAMP_SNAPSHOT, BB_RT_LAMP_TRACE (function-local
#    statics) and the one-time "Point shadows: WxH ..." line: KEEP: microseconds.
#  - Not first use but every pass, noted for a later look: the non-reduced path creates two target
#    views and a depth view per pass and destroys them deferred (Flush; cost per pass not measured,
#    guess a few microseconds of CPU), and `data` is moved into each pass's command lambda, so
#    every batch grows a new vector from empty (a few reallocations, up to 1 MB). CANNOT TELL
#    whether either is worth a change without a CPU profile of stage B.
#  - Same pattern outside this file: RtShadow::R25HalfWanted (vk_rt_shadow.cpp) makes the sun's
#    half-resolution trace (graphics_rt_sun_half) on first use during play. Not changed here:
#    vk_rt_shadow.cpp is r62's file (pending); a later patch can call it from RtShadow::Setup.
#
# REVIEWED (adversarial, 2026-11-15): HalfReady from Ready only at start (with
# BB_LAMP_SHADOW_AT_START=0 it ran at the first lamp draw, which was not the old timing);
# half_asked (above); Ready's line says "could not be made" when HalfReady failed.
# NOTHING HAS BEEN BUILT IN THE TREE OR RUN ON A GPU: no game test, no timing. Checked here:
# clang++ -fsyntax-only of the patched vk_point_shadow.cpp (and header) with the tree's flags from
# engine/out/gpu/build.ninja (compile_commands.json does not exist there): passes, and -Wall -Wextra
# gives no new warning; the script's check/apply/revert on a copy of the three files.
#
# HOW TO SEE IT IN A GAME RUN (graphics_lamp_shadow_half=1, HQ GTAO as usual):
#  - In the log, before the first frame (with the other start lines, after "Ray tracing: on ..."):
#      "Ray traced lamps (r32): half resolution (graphics_lamp_shadow_half=1) ready; ..."
#      "Ray traced lamps (r65): the half-resolution build made at start in N ms"
#      "Ray traced lamps (r65): the pass's pipelines made at start in M ms (ray traced yes, half
#       resolution yes); ..."
#    M is the stall that left play (N is part of it).
#  - A/B: BB_LAMP_SHADOW_AT_START=0 gives "made at the first lamp draw (during play) in M ms" and
#    "half-resolution build made during play in N ms": those are the stalls of before. In play they
#    also show as one frame-time spike at the first frame with lamps (frame report, overlay graph);
#    BB_GPU_PROFILE's "point shadows" row does not show them (CPU time, not GPU time).
#  - The picture: identical with 0 and unset (same pipelines, same passes).

import os
import sys

ROOT = os.environ.get("R65_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
R = ROOT + "engine/gpu/shadps4/video_core/renderer_vulkan/"
HDR = R + "vk_point_shadow.h"
CPP = R + "vk_point_shadow.cpp"
DOC = ROOT + "engine/docs/renderer-performance-0.9.43.md"

TMP = ".r65tmp"  # a new text waits under this name beside its target (main)


def B(s):
    """A block written from the line after the opening quotes."""
    return s[1:] if s.startswith("\n") else s


# Every (old, new) pair must match exactly once in the text it is applied to, in the order given;
# revert applies them backwards, new for old. Written with LF; the file's CRLF is put in.
EDITS = {
    HDR: [
        (B(r"""
    bool failed = false;
    // bbport (r32_lamp-half, r37_menu-options): the lamps-apart pass traces pixel (2x, 2y) of
"""), B(r"""
    bool failed = false;
    // bbport (r65_lamp-half-at-start): Ready is running from the constructor (only its log
    // lines differ: they say "at start")
    bool at_start = false;
    // bbport (r32_lamp-half, r37_menu-options): the lamps-apart pass traces pixel (2x, 2y) of
""")),
        (B(r"""
    // set: the full-resolution pass, as before.
    // bbport (r44_half-area-lamp): the half-resolution pass has the area lamp too, averaged in
"""), B(r"""
    // set: the full-resolution pass, as before.
    // bbport (r65_lamp-half-at-start): Ready runs at start (the constructor) when the lamp pass
    // is wanted then and BB_LAMP_SHADOW_AT_START is not 0, else at the first lamp draw; at start
    // it also calls HalfReady when HalfWanted and ray traced lamps are wanted then. Otherwise,
    // and for a switch to the half resolution later, the build is made on first use, as before.
    // bbport (r44_half-area-lamp): the half-resolution pass has the area lamp too, averaged in
""")),
        (B(r"""
    bool HalfReady();
    bool half_laid_out = false;
"""), B(r"""
    bool HalfReady();
    /// bbport (r65_lamp-half-at-start): BB_LAMP_SHADOW_HALF when set, else
    /// graphics_lamp_shadow_half as it is now (Flush's test and Ready's, so they cannot differ)
    bool HalfWanted() const;
    /// bbport (r65_lamp-half-at-start): a pass has asked for the half resolution (Flush). The
    /// counters line (OnFrameEnd) waits for it, as it waited for HalfReady before r65, so a build
    /// made at start does not print lines of zeros from the title screen on.
    bool half_asked = false;
    bool half_laid_out = false;
""")),
    ],
    CPP: [
        (B(r"""
#include <bit>
#include <cmath>
"""), B(r"""
#include <bit>
#include <chrono> // bbport (r65_lamp-half-at-start): how long the pipelines took
#include <cmath>
""")),
        (B(r"""
                    "resolution)\n");
    }
}
"""), B(r"""
                    "resolution)\n");
    }
    // bbport (r65_lamp-half-at-start): the pass's pipelines were made at the first lamp draw
    // (Ready, from OnLightDraw) and the half-resolution build at the first pass that wanted it
    // (HalfReady, from Flush): both during play, each a one-time stall of the draw thread while
    // the driver compiles them (EffectPass::Create, as every effect pass here: no pipeline cache
    // of ours, no compile thread). Now, when the pass is wanted at start (the test OnLightDraw
    // makes), they are made here, at start, as RtShadow's constructor makes the sun's. Ready
    // makes the same objects as it would later and reads only what is fixed by now (RtShadow's
    // setup, this constructor's knobs, lantern.ini), so the picture does not change. Not wanted
    // at start, or BB_LAMP_SHADOW_AT_START=0: on first use, as before.
    const char* const at_start_env = std::getenv("BB_LAMP_SHADOW_AT_START");
    const bool early = !at_start_env || at_start_env[0] != '0';
    if (early && (BbSettings::Get().effects[BbSettings::EffectPointShadows].load(std::memory_order_relaxed) ||
                  RaysWanted())) {
        at_start = true;
        Ready();
        at_start = false;
    } else {
        std::printf("Ray traced lamps (r65): the pass's pipelines are made on first use (%s)\n",
                    early ? "lamp shadows are off at start" : "BB_LAMP_SHADOW_AT_START=0");
    }
}

// bbport (r65_lamp-half-at-start): one test for Flush and Ready (see the header)
bool PointShadow::HalfWanted() const {
    return half_env >= 0 ? half_env == 1
                         : BbSettings::Get().graphics_lamp_shadow_half.load(std::memory_order_relaxed);
}
""")),
        (B(r"""
    tried = true;
    using enum vk::DescriptorType;
"""), B(r"""
    tried = true;
    const auto r65_began = std::chrono::steady_clock::now(); // bbport (r65_lamp-half-at-start)
    using enum vk::DescriptorType;
""")),
        (B(r"""
    // bbport (r37_menu-options): the half-resolution build is made by HalfReady, when first wanted.
    constexpr auto Drawn = vk::FormatFeatureFlagBits::eColorAttachment |
"""), B(r"""
    // bbport (r37_menu-options): the half-resolution build is made by HalfReady, when first wanted.
    // bbport (r65_lamp-half-at-start): or at the end of this function, at start, when wanted then.
    constexpr auto Drawn = vk::FormatFeatureFlagBits::eColorAttachment |
""")),
        (B(r"""
        instance, 0, DataWords * sizeof(u32), VideoCore::MemoryType::DeviceLocal, "Point shadow lights");
    return true;
"""), B(r"""
        instance, 0, DataWords * sizeof(u32), VideoCore::MemoryType::DeviceLocal, "Point shadow lights");
    // bbport (r65_lamp-half-at-start): at start, the half-resolution build with the others when a
    // pass would take it now (Flush also needs the ray pass and ray traced lamps wanted), so that
    // the first half-resolution pass does not make it during play. Not at start
    // (BB_LAMP_SHADOW_AT_START=0, or the lamp pass switched on later) or not wanted now: made by
    // the first pass that wants it, as before.
    if (at_start && ray_pipeline && RaysWanted() && HalfWanted()) {
        HalfReady();
    }
    const double r65_ms =
        std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r65_began).count();
    std::printf("Ray traced lamps (r65): the pass's pipelines made %s in %.1f ms (ray traced %s, half "
                "resolution %s); BB_LAMP_SHADOW_AT_START=0 = at the first lamp draw\n",
                at_start ? "at start" : "at the first lamp draw (during play)", r65_ms,
                ray_pipeline ? "yes" : "no",
                half_made ? "yes" : half_tried ? "could not be made" : "not now");
    return true;
""")),
        (B(r"""
// bbport (r52_follow-soft): then the follow state (11, 12).
bool PointShadow::HalfReady() {
"""), B(r"""
// bbport (r52_follow-soft): then the follow state (11, 12).
// bbport (r65_lamp-half-at-start): or by Ready when it runs at start and it is wanted then.
bool PointShadow::HalfReady() {
""")),
        (B(r"""
    half_tried = true;
    using enum vk::DescriptorType;
"""), B(r"""
    half_tried = true;
    const auto r65_began = std::chrono::steady_clock::now(); // bbport (r65_lamp-half-at-start)
    using enum vk::DescriptorType;
""")),
        (B(r"""
                half_made ? "ready" : "ignored - no pipeline");
    return half_made;
"""), B(r"""
                half_made ? "ready" : "ignored - no pipeline");
    // bbport (r65_lamp-half-at-start): what this build cost, and when (during play it is a stall)
    std::printf("Ray traced lamps (r65): the half-resolution build made %s in %.1f ms\n",
                at_start ? "at start" : "during play",
                std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - r65_began).count());
    return half_made;
""")),
        (B(r"""
    // pass's counters, which then fall in the next line). half_readback: made by HalfReady
    // (bbport r37_menu-options), the first time a pass wants the half resolution.
    if (half_made && half_readback && ++half_frames >= 600) {
"""), B(r"""
    // pass's counters, which then fall in the next line). half_readback: made by HalfReady
    // (bbport r37_menu-options), the first time a pass wants the half resolution (bbport
    // r65_lamp-half-at-start: or at start, by Ready; the line still waits for the first pass that
    // asks for it, half_asked, as before).
    if (half_made && half_asked && half_readback && ++half_frames >= 600) {
""")),
        (B(r"""
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    const bool half_on = half_env >= 0 ? half_env == 1
                                       : BbSettings::Get().graphics_lamp_shadow_half.load(
                                             std::memory_order_relaxed);
    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
"""), B(r"""
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    // bbport (r65_lamp-half-at-start): HalfWanted, the test Ready makes at start too.
    const bool half_on = HalfWanted();
    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
""")),
        (B(r"""
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
"""), B(r"""
    // bbport (r65_lamp-half-at-start): where HalfReady was first called before r65; from here
    // the counters line runs (OnFrameEnd), as it did then.
    half_asked = half_asked || (use_rays && batch_apart && half_on);
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
""")),
    ],
    DOC: [
        (B(r"""
- **Startup-only items.** The motion store size and thread pinning are read once at start.
"""), B(r"""
- **Lamp shadow pipelines made at start (r65).** `BB_LAMP_SHADOW_AT_START`, read once in the
  `PointShadow` constructor, default on; `0` (and only `0`) gives the old timing. On: when the lamp
  pass is wanted at start (the point shadow effect on, or ray traced lamps wanted: the test
  `PointShadow::OnLightDraw` makes), the constructor calls `PointShadow::Ready`, which makes the
  pass's pipelines and light buffer, and there `Ready` calls `PointShadow::HalfReady` when the ray
  traced pass exists, ray traced lamps are wanted and `PointShadow::HalfWanted` is true
  (`BB_LAMP_SHADOW_HALF` when set, else `graphics_lamp_shadow_half`). Before, `Ready` ran at the
  first lamp draw and `HalfReady` at the first half-resolution pass, both during play: a one-time
  stall of the draw thread while the driver compiles them (not measured; the new log line
  "Ray traced lamps (r65): ... made ... in N ms" gives it). Off, or not wanted at start: on first
  use, as before. The same objects are made either way, so the picture does not change; the cost
  moves to start. No experiment bit gates it, so the switch does not change it.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
""")),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the new texts must hold; False (with the reason printed) when one does not."""
    ok = True

    def bad(msg):
        nonlocal ok
        ok = False
        print("check: " + msg)

    for path, pairs in EDITS.items():
        for old, new in pairs:
            if not new.isascii():
                bad("a new text with a character that is not ASCII in %s" % path)
    c = texts[CPP].replace("\r\n", "\n")
    # the definition, Ready's call and Flush's: no other test of the half resolution's setting
    if c.count("HalfWanted()") != 3 or c.count("graphics_lamp_shadow_half.load(") != 1:
        bad("vk_point_shadow.cpp: the half resolution is not tested by HalfWanted alone")
    if c.count("half_asked = half_asked ||") != 1 or c.count("half_made && half_asked &&") != 1:
        bad("vk_point_shadow.cpp: half_asked is not set once and tested once")
    if c.count("if (at_start && ray_pipeline && RaysWanted() && HalfWanted())") != 1:
        bad("vk_point_shadow.cpp: Ready's call of HalfReady is not at start only")
    if c.count("at_start = true;\n        Ready();\n        at_start = false;") != 1:
        bad("vk_point_shadow.cpp: the constructor's call of Ready is not there once")
    h = texts[HDR]
    if h.count("bool HalfWanted() const;") != 1 or h.count("bool at_start = false;") != 1 or \
            h.count("bool half_asked = false;") != 1:
        bad("vk_point_shadow.h: HalfWanted or at_start not declared once")
    if texts[DOC].count("`BB_LAMP_SHADOW_AT_START`") != 1:
        bad("the doc does not name BB_LAMP_SHADOW_AT_START once")
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed. Only reads."""
    out = {}
    forward = mode != "revert"
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        start = t
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if forward else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if forward else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        # The way back must give exactly the text we started from.
        back = t
        for old, new in (reversed(pairs) if forward else pairs):
            a, b = (fix(new, nl), fix(old, nl)) if forward else (fix(old, nl), fix(new, nl))
            if back.count(a) != 1:
                back = None
                break
            back = back.replace(a, b)
        if back != start:
            if not quiet:
                print("%s: the edits could not be taken back byte for byte" % path)
            return None
        out[path] = t
    if forward and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r65_lamp-half-at-start.py check|apply|revert   (the tree: R65_ROOT, else the "
              "current directory)")
        return 2
    if not os.path.isfile(CPP):
        print("not a source tree: %s (set R65_ROOT)" % ROOT)
        return 2
    # run() only reads: nothing is written before every text of the mode is made.
    out = run(mode, quiet=True)
    if out is None:
        if mode != "revert" and run("revert", quiet=True) is not None:
            if mode == "check":
                print("applied in %s (revert would restore the tree)" % ROOT)
                return 0
            print("already applied in %s: nothing written" % ROOT)
            return 1
        if mode == "revert" and run("check", quiet=True) is not None:
            print("not applied in %s: nothing to revert" % ROOT)
            return 1
        run(mode)  # says which anchor, or what else is wrong
        print("neither applied nor not applied in %s: nothing written" % ROOT)
        return 1
    if mode == "check":
        print("not applied in %s; the anchors are found once each (applies cleanly)" % ROOT)
        return 0
    # Every new text goes to a file beside its target first, then each is moved over its target
    # (one rename a file). If a step fails, what was already moved is put back from the bytes
    # read at the start, so the tree is never left half patched.
    before = {}
    for path in out:
        before[path] = open(path, "rb").read()
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed in %s (%s); putting back what was changed" % (ROOT, e))
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("%s in %s" % ("applied" if mode == "apply" else "reverted", ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
