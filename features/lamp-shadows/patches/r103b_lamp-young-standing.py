# r103b_lamp-young-standing: follow-up to r103_lamp-young-pixels (FEATURE, lamp work). Needs r103 (and so
# r93) applied. ORDER: revert THIS patch BEFORE r103: with r103b in, r103's own check reports a mixed state
# (r103b changes three of r103's lines: the young share's line in the shader, LampYoungBits' return and
# the half line's function and call), and r103's revert would refuse; after r103b's revert r103 reads
# "applied" again, byte for byte.
#
# Fault (game runs 2026-11-15): standing next to the held torch with BB_LAMP_SHADOW_YOUNG=1, the torch's
# shadows (a vine on the ground, the shadow at the hunter's feet) were paler and softer than with the knob
# off, and the log counted about 52,500 young pixels per half-size pass while only the torch moved. In a
# 4K walk r103 had removed the hatched edge of the hunter's moving shadow (keep that).
#
# Where the lightening comes from (point_shadow_ray.comp main, the centred window's resolve; shown in the
# model S/r103b_model.py with the tree's constants): the young pixels were mostly on the shadow's DARK side.
# Under a lamp that steps 2 mm or more (a swaying, flickering torch: 1 to 4 mm a frame) the soft follow
# looks a pixel's history up where the lamp's step puts it, weighted by the pixel's follow state, and that
# state rises only where the pixel's own ray is blocked near the lamp (castEvidence +1): so only shadowed
# pixels take most of their history from the moved place, and near a still shadow's edge that place holds
# fewer frames (frames are "times the part found") or another surface. 47 % of the young pixels in the
# model's standing torch were of this kind (the rest: reject 16 %, clamp 10 %, mixed 27 %), and 3.6 times
# as many young pixels lay on the dark side as on the lit side. A young pixel then took the 5x5 same-surface
# mean, which beside a thin or contact shadow takes in lit answers (the shadow is narrower than the window;
# the caster's own pixels are left out by the plane test): +0.034 over the pixel's own answer on average on
# the dark side. The mean itself is not biased against the truth on average (walking caster: +0.010 dark,
# -0.012 lit); the selection by the lamp's sway made the standing shadows lighter.
#
# What (all inside #ifdef CENTRED; word 0 bit 29, set with bit 27 by LampYoungBits unless
# BB_LAMP_SHADOW_YOUNG_STILL=0): under a strongest lamp that stepped less than YOUNG_SWAY_STEP = 0.01 m since
# the frame before (record word 15: 0 below 2 mm), a pixel's young share is at most
#   1 - smoothstep(0.5, 2, own x (own > 1.5 ? reject's share : 1) x (1 - clamp's taken)),
#   own = min(frames found where the surface was (historyAt's, times the part found; without the soft
#         follow, the history's own frames), the history's limit),
# i.e. only what the reject and the window clamp cut (something on the surface changed: a caster or the
# camera moved) makes a pixel young; what the lamp's own small step cuts (the follow's look-up, the trail
# cap, the unsure cut) does not, and such a pixel shows its own guarded ratio as with
# BB_LAMP_SHADOW_YOUNG=0. A pixel with no history whose surface's own place had 2 frames or more (the
# follow lost it) is treated the same. Under a lamp that steps 0.01 m or more (carried by someone walking,
# 0.6 m/s at 60 frames a second, or new) and under a lamp that stands, the share is r103's (with a lamp
# that stands no lamp guard acts, and the bound above equals r103's share exactly).
#  - Guards and trails: nothing here changes `frames`, `held_ratio`, `fast`, the follow state or any
#    stored value but through the shown/stored ratio's young share; every guard (reject, window clamp and
#    its own-answer widening, trail cap, unsure cut, cast codes) runs and cuts exactly as before. A young
#    pixel takes this frame's mean (r103) or its own guarded ratio (r103b's sway case, as with the knob
#    off): neither carries the old shadow, so no trail can come back. BB_LAMP_SHADOW_YOUNG=2's kept clamp
#    frame is unchanged (still a test setting).
#  - Counter: half_counts word 15 (unused before; HALF_SLOTS 15 bounds the shared counters only, the buffer
#    and its readback hold HalfSlots = 16 words): one atomicAdd per pixel of one 2x2 block in four whose
#    share the rule cut, in every half-resolution resolve (as r103's word 13). The r103 half line then ends
#    "; r103b: about N a pass had their share cut as sway (lamp step under 0.01 m)". Full resolution has no
#    pixel counter (no buffer there), as r103.
#  - Once-line after r103's: "Ray traced lamps (r103b): standing rule on|off (BB_LAMP_SHADOW_YOUNG_STILL=...".
#
# Options weighed (model numbers in the 2026-11-15 r103b section of the lamp backlog):
#  (a) an edge-preserving young estimate: with one 0/1 ray a pixel, a pixel's own answer against its
#      neighbours' mean and spread cannot tell a hard edge from a noisy penumbra; a median turns a moving
#      penumbra into 0/1 blotches (hatching again); a least-squares plane at the window's centre is the
#      mean. Not taken.
#  (b) young only where the reprojection or the lamp record says something moved: TAKEN, in the form
#      above (the lamp record's step; the camera's motion needs no test, its cuts are the reject's and the
#      clamp's). The "keep the clamped history with a floor of frames" variant: modelled, lighter than
#      r103b standing (it keeps the follow's displaced history longer), not taken.
#  (c) 3x3 instead of 5x5: modelled; standing the same as r103b once the gate is in, the walking cure
#      smaller (W1 0.1223 against 0.1191). Not taken.
#  (d) energy: the cause is the selection above, fixed at its source; a variant that keeps the young mean
#      out of the stored history (display only) was modelled: standing a little closer still to off, but
#      it loses about a fifth of the walking cure (W1 0.1253) and needs more code; not taken.
#
# Off: BB_LAMP_SHADOW_YOUNG=0 -> no bit 27 or 29 -> nothing of r103 or r103b runs (r103's own off path).
# BB_LAMP_SHADOW_YOUNG_STILL=0 -> no bit 29 -> t_young_still false -> the new lines are dead (the
# captures are stores nothing reads, young_sway stays 0): the CENTRED builds optimise to r103's (proven
# with spirv-opt on a copy). No image, buffer, binding, push constant or dispatch is added.
#
# Use: python -I -X utf8 r103b_lamp-young-standing.py check | apply | revert
# Root: R103_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r103b_backup next to this script; revert takes out exactly what apply put in (each text found by itself,
# exactly once) and puts r103's three lines back.
import os, re, sys

ROOT = os.environ.get("R103_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r103b_backup")
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
Y = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_young_pixels.h"
U = "engine/tests/test_lamp_shadow_tune.cpp"
R = "README.md"
FILES = (S, C, Y, U, R)

SWAY_M = "0.01"  # YOUNG_SWAY_STEP; the texts below say it in these words


def before(anchor, text):
    return ("before", anchor, text)


def after(anchor, text):
    return ("after", anchor, text)


def replace(old, new):
    return ("replace", old, new)


YOUNG_LINE_OLD = "            const float young = held ? 1.0 - smoothstep(YOUNG_FROM, YOUNG_ALL, frames) : 1.0;\n"
YOUNG_LINE_NEW = r"""            float young = held ? 1.0 - smoothstep(YOUNG_FROM, YOUNG_ALL, frames) : 1.0;
            // bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL (bit 29). Under a strongest lamp
            // that only sways (its step since the frame before below YOUNG_SWAY_STEP, 0.01 m; 0 below 2 mm)
            // the share is at most what the reject and the window clamp alone leave young of the history
            // found where the surface was (young_own: historyAt's frames there, times the part found; the
            // history's own frames without the soft follow): 1 - smoothstep(YOUNG_FROM, YOUNG_ALL, that).
            // What the lamp's own small step takes no longer makes a pixel young: the soft follow's look-up
            // where the step puts the history (weighted by the follow state, which only a ray blocked near
            // the lamp raises, so on a shadow's dark side), the trail cap and the unsure cut. Under a
            // swaying, flickering torch those dropped the history at standing shadows' dark edges, and the
            // 5x5 mean, which takes in the lit answers beside a thin or contact shadow, made the shadows
            // paler and softer. Such a pixel shows its own guarded ratio, as without BB_LAMP_SHADOW_YOUNG.
            // A pixel without history whose own place held 2 frames or more (the follow lost it) the same.
            // A lamp that steps 0.01 m or more (carried by someone walking, or new), a lamp that stands
            // (no lamp guard acts: this bound is r103's share) and every cut of the reject or the clamp (a
            // caster or the camera moved) keep r103's share. No guard, frame or stored value moves here.
            float young_sway = 0.0;
            if (t_young_still && top_step < YOUNG_SWAY_STEP) {
                const float own = min(young_own >= 0.0 ? young_own : (held ? held_frames : 0.0), word(history_at + 30u));
                const float content = own * (own > 1.5 ? young_rej : 1.0) * (1.0 - young_taken);
                const float kept = min(young, 1.0 - smoothstep(YOUNG_FROM, YOUNG_ALL, content));
                young_sway = young - kept;
                young = kept;
            }
#ifdef HALF
            if (young_sway > 0.0 && (held || !t_spatial) && ((px.x | px.y) & 2) == 0) {
                atomicAdd(half_counts.n[YOUNG_SWAY_SLOT], 1u); // the pixels of one 2x2 block in four, for the log
            }
#endif
"""

EDITS = {
S: [
    after("bool t_young_keep = false;      // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG=2 (bit 28)\n",
          "bool t_young_still = false;     // bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL (bit 29)\n"),
    after("    t_young_keep = (f & (1u << 28u)) != 0u;  // bbport (r103_lamp-young-pixels)\n",
          "    t_young_still = (f & (1u << 29u)) != 0u; // bbport (r103b_lamp-young-standing)\n"),
    before("#endif\n\n#ifdef HALF\n// bbport (r32_lamp-half): more bits of `mode` (vk_point_shadow.cpp ModeHalf*).\n",
           r"""// bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL (word 0 bit 29, set only with bit 27;
// read in main's young block). YOUNG_SWAY_STEP: a strongest lamp whose step since the frame before (word
// 15 of its record; 0 below LampTrack::Still, 2 mm) is below this only sways (a held torch's idle motion
// and flicker, 1 to 4 mm a frame in the logs; a hip lantern standing, 5 to 13 mm); from it on the lamp is
// carried by someone walking (0.6 m/s at 60 frames a second) or is new. YOUNG_SWAY_SLOT: half_counts word
// 15 (unused before; HALF_SLOTS bounds only the shared counters, the buffer holds 16 words): the young
// pixels of one 2x2 block in four whose share the standing rule cut, added by every half-resolution
// resolve (vk_point_shadow.cpp: lamp_young_pixels.h LampYoungHalfLine).
const float YOUNG_SWAY_STEP = 0.01;
#ifdef HALF
const uint YOUNG_SWAY_SLOT = 15u;
#endif
"""),
    after("        float lam_kept = 0.0;\n",
          "#ifdef CENTRED\n"
          "        // bbport (r103b_lamp-young-standing): for the standing rule (the young block below): young_own,\n"
          "        // the frames of history found where the surface was (historyAt's, times the part found; below\n"
          "        // 0: not looked up apart, the history's own frames count); young_rej, the reject's share of\n"
          "        // them; young_taken, what the window clamp cut.\n"
          "        float young_own = -1.0, young_rej = 1.0, young_taken = 0.0;\n"
          "#endif\n"),
    before("                const float got = (1.0 - w_f) * fa + w_f * ff;\n",
           "#ifdef CENTRED\n"
           "                young_own = sa.y; // bbport (r103b_lamp-young-standing): the frames found where the surface was\n"
           "#endif\n"),
    before("            if (t_reject > 0.0 && frames > 1.5) {\n",
           "#ifdef CENTRED\n"
           "            if (t_young_still && t_reject > 0.0) { // bbport (r103b_lamp-young-standing): the reject's share\n"
           "                young_rej = 1.0 - smoothstep(REJECT_FROM * t_reject, t_reject, abs(fast - held_ratio));\n"
           "            }\n"
           "#endif\n"),
    after("                if (young_keep > 0.0) { // bbport (r103_lamp-young-pixels)\n"
          "                    frames = max(frames, young_keep);\n"
          "                }\n"
          "#endif\n",
          "#ifdef CENTRED\n"
          "                young_taken = taken; // bbport (r103b_lamp-young-standing): the window clamp's cut\n"
          "#endif\n"),
    replace(YOUNG_LINE_OLD, YOUNG_LINE_NEW),
],
C: [
    replace("        LampYoungHalfLine(d[13] * counted, half_line_passes, half_frames); // bbport (r103_lamp-young-pixels)\n",
            "        LampYoungHalfLine(d[13] * counted, half_line_passes, half_frames, d[15] * counted); // bbport (r103_lamp-young-pixels; r103b: d[15])\n"),
],
Y: [
    after("              \"bbport (r103_lamp-young-pixels): word 0 bits 27 and 28 must be free\");\n",
          r"""// bbport (r103b_lamp-young-standing): bit 29, BB_LAMP_SHADOW_YOUNG_STILL, the standing rule; set only with
// bit 27 (LampYoungBits), read only by the CENTRED builds' resolve (point_shadow_ray.comp, main's young block).
inline constexpr std::uint32_t LampTuneYoungStill = 1u << 29;
static_assert((LampTuneYoungStill &
               (LampTuneYoung | LampTuneYoungKeep | LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |
                LampTuneWindow | LampTuneCentred | LampTuneSpatial | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) | (1u << 24) | (1u << 25))) == 0,
              "bbport (r103b_lamp-young-standing): word 0 bit 29 must be free");
"""),
    before("/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).\n",
           r"""/// bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL: on (the default) unless it is the whole
/// number 0, which keeps r103's young pixels as they were (for comparison); text that is not a whole
/// number, or nothing: on.
inline bool LampYoungStillParse(const char* text) {
    if (!text || !text[0]) {
        return true;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !LampTuneDetail::Ends(end)) {
        return true;
    }
    return value != 0;
}

/// bbport (r103b_lamp-young-standing): the standing rule's knob, read once (the first call).
inline bool LampYoungStillValue() {
    static const bool value = LampYoungStillParse(std::getenv("BB_LAMP_SHADOW_YOUNG_STILL"));
    return value;
}

"""),
    replace("    return LampYoungBitsFor(LampYoungValue(), tune);\n",
            "    const std::uint32_t bits = LampYoungBitsFor(LampYoungValue(), tune);\n"
            "    // bbport (r103b_lamp-young-standing): bit 29 with bit 27, unless BB_LAMP_SHADOW_YOUNG_STILL=0\n"
            "    return bits != 0u && LampYoungStillValue() ? bits | LampTuneYoungStill : bits;\n"),
    before("/// PointShadow::Ready, once, when the knob is set: on or off and why first (the slot runs keep 300\n",
           r"""/// bbport (r103b_lamp-young-standing): PointShadow::Ready, once, right after r103's line (so only with
/// BB_LAMP_SHADOW_YOUNG set): the standing rule, on or off first. centred: as LampYoungStartLine's.
inline void LampYoungStillStartLine(bool centred) {
    std::printf("Ray traced lamps (r103b): standing rule %s (BB_LAMP_SHADOW_YOUNG_STILL=%u; 0: r103 as it was): "
                "under a lamp that stepped under 0.01 m only the reject's and the clamp's cut of the history found "
                "where the surface was makes a pixel young, not the follow, trail cap or unsure cut\n",
                centred && LampYoungStillValue() ? "on" : "off", LampYoungStillValue() ? 1u : 0u);
}

"""),
    after("                       : \"the clamp's cut stays as it was\");\n",
          "    LampYoungStillStartLine(centred); // bbport (r103b_lamp-young-standing)\n"),
    replace(r"""inline void LampYoungHalfLine(double young, std::uint32_t passes, std::uint32_t frames) {
    if (LampYoungValue() == 0) {
        return;
    }
    std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames)\n",
                passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames));
}
""", r"""inline void LampYoungHalfLine(double young, std::uint32_t passes, std::uint32_t frames, double sway = -1.0) {
    if (LampYoungValue() == 0) {
        return;
    }
    // bbport (r103b_lamp-young-standing): sway = the rise of half_counts word 15, the young pixels of one 2x2
    // block in four whose share the standing rule cut (fully: not in `young`; partly: in both); said only
    // with the rule's knob on
    if (LampYoungStillValue() && sway >= 0.0) {
        std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                    "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames); r103b: "
                    "about %.0f a pass had their share cut as sway (lamp step under 0.01 m)\n",
                    passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames),
                    passes != 0 ? 4.0 * sway / double(passes) : 0.0);
        return;
    }
    std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames)\n",
                passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames));
}
"""),
],
U: [
    after("        assert((LampTuneWords(d, true, 0.05f, nullptr, 9u)[0] & (LampTuneYoung | LampTuneYoungKeep)) == 0u);\n"
          "    }\n",
          r"""    // bbport (r103b_lamp-young-standing): BB_LAMP_SHADOW_YOUNG_STILL is on unless it is the whole number 0;
    // its bit 29 is free and never in LampTuneWords (LampYoungBits ORs it in with bit 27).
    {
        static_assert(LampTuneYoungStill == 1u << 29 && (LampTuneYoungStill & (LampTuneYoung | LampTuneYoungKeep)) == 0u);
        assert(LampYoungStillParse(nullptr) && LampYoungStillParse("") && LampYoungStillParse("1"));
        assert(!LampYoungStillParse("0") && !LampYoungStillParse(" 0 ") && !LampYoungStillParse("-0"));
        assert(LampYoungStillParse("2") && LampYoungStillParse("yes") && LampYoungStillParse("0x"));
        const LampShadowTune d{};
        assert((LampTuneWords(d, true, 0.05f, nullptr, 9u)[0] & LampTuneYoungStill) == 0u);
    }
"""),
],
# README.md: readme_edit (the row after the BB_LAMP_SHADOW_YOUNG row)
}

ROW = ("| `BB_LAMP_SHADOW_YOUNG_STILL` | With `BB_LAMP_SHADOW_YOUNG` 1 or 2: the standing rule, on unless `0`. Where a "
       "pixel's strongest lamp moved less than 0.01 m since the frame before (a held torch or lantern that sways and "
       "flickers; a step under 2 mm counts as 0), a pixel counts as young only by what the reject and the window clamp "
       "cut from the history found where its surface was (that is, something on the surface changed: a caster or the "
       "camera moved). What the lamp's own small step cuts no longer makes it young: the look-up where the soft follow "
       "moves the history with the lamp (which only pixels whose ray is blocked near the lamp take, so only on a "
       "shadow's dark side), the trail cap and the unsure cut; such a pixel shows its own averaged ratio as with "
       "`BB_LAMP_SHADOW_YOUNG=0`, instead of the 5x5 mean that made standing torch shadows paler and softer. A pixel "
       "without history whose own place held 2 frames or more is treated the same. Under a lamp that moves 0.01 m or "
       "more a frame (carried by someone walking: 0.6 m/s at 60 frames a second) or stands, and wherever the reject "
       "or the clamp cut, the young pixels are r103's. No guard and no stored frame changes. At half resolution the "
       "r103 line adds how many young pixels a pass had their share cut as sway. `0`: r103 as it was (for "
       "comparison). Read at start. Log: \"(r103b)\" | `1` |\n")


def readme_edit(text):
    """The row goes after the BB_LAMP_SHADOW_YOUNG row (r103's; the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_YOUNG` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_YOUNG row is there %d times, wanted 1 (r103 first)" % len(lines))
    return after(lines[0] + "\n", ROW)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        raise SystemExit("REFUSED %s is missing%s" % (path, " (r103 first)" if path == Y else ""))
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return [readme_edit(text)] if path == R else EDITS[path]


def edit_state(cur, ed, path):
    kind, a, t = ed
    na, nt = cur.count(a), cur.count(t)
    if kind == "replace":
        if na == 1 and nt == 0:
            return "clean"
        if na == 0 and nt == 1:
            return "applied"
    else:
        if na == 1 and nt == 0:
            return "clean"
        if na == 1 and nt == 1:
            return "applied"
    raise SystemExit("REFUSED %s: %s anchor found %d times, its text %d times (wanted 1/0 or %s): %r"
                     % (path, kind, na, nt, "0/1" if kind == "replace" else "1/1", a[:70]))


def state_of(cur, eds, path):
    st = [edit_state(cur, ed, path) for ed in eds]
    if all(s == "applied" for s in st):
        return "applied"
    if all(s == "clean" for s in st):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied (mixed state)" % (path, st.count("applied"), len(st)))


def apply_one(cur, ed):
    kind, a, t = ed
    if kind == "replace":
        return cur.replace(a, t, 1)
    return cur.replace(a, t + a if kind == "before" else a + t, 1)


def revert_one(cur, ed):
    kind, a, t = ed
    if kind == "replace":
        return cur.replace(t, a, 1)
    return cur.replace(t, "", 1)


def text_checks(texts):
    """The ties a compiler cannot check, on the applied texts."""
    s = texts[S]
    for want, n in (("(1u << 29u)", 1), ("const float YOUNG_SWAY_STEP = " + SWAY_M + ";", 1),
                    ("const uint YOUNG_SWAY_SLOT = 15u;", 1), ("half_counts.n[YOUNG_SWAY_SLOT]", 1),
                    ("young_own = sa.y;", 1), ("young_taken = taken;", 1), ("float young_sway = 0.0;", 1),
                    ("const uint YOUNG_SLOT = 13u;", 1), ("const uint HALF_SLOTS = 15u;", 1),
                    ("float young = held ? 1.0 - smoothstep(YOUNG_FROM, YOUNG_ALL, frames) : 1.0;", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    if "half_counts.n[15" in s or "half_n[15" in s:
        raise SystemExit("text check: half_counts word 15 is written by someone else")
    # every r103b shader line lies inside #ifdef CENTRED (the plain, half, cards, half cards, colour and half
    # colour builds keep their SPIR-V words)
    mine = re.compile(r"r103b|\b(t_young_still|young_own|young_rej|young_taken|young_sway|YOUNG_SWAY_STEP|YOUNG_SWAY_SLOT)\b")
    stack = []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifdef CENTRED")
        elif st.startswith("#else") or st.startswith("#elif"):
            stack[-1] = False
        elif st.startswith("#endif"):
            stack.pop()
        elif mine.search(line) and not any(stack):
            raise SystemExit("text check: r103b shader line outside #ifdef CENTRED: %r" % line)
    # order in main: the declarations, the own place's frames, the reject's share, the reject, the clamp's
    # cut, the young block, r93's blend, the store
    order = [s.find("float young_own = -1.0, young_rej = 1.0, young_taken = 0.0;"), s.find("young_own = sa.y;"),
             s.find("const float got = (1.0 - w_f) * fa + w_f * ff;"), s.find("young_rej = 1.0 - smoothstep("),
             s.find("if (t_reject > 0.0 && frames > 1.5) {"), s.find("young_taken = taken;"),
             s.find("float young_sway = 0.0;"), s.find("mix(answer, spatial, spatial_u)"),
             s.find("        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));")]
    if not all(0 <= order[i] < order[i + 1] for i in range(len(order) - 1)):
        raise SystemExit("text check: the r103b lines in main are out of order: %r" % order)
    if s.find("const float YOUNG_SWAY_STEP") < s.find("const float YOUNG_ALL = 2.0;"):
        raise SystemExit("text check: YOUNG_SWAY_STEP is not after r103's constants")
    y = texts[Y]
    if y.count("1u << 29") != 1 or y.count("LampYoungStillStartLine(centred);") != 1:
        raise SystemExit("text check: %s: bit 29 or the once-line call is not there once" % Y)
    # the texts say the shader's step in its own words
    for path in (Y, R):
        if "0.01 m" not in (texts[path] if path != R else ROW):
            raise SystemExit("text check: %s does not name the step 0.01 m" % path)
    if "under 0.01 m" not in YOUNG_LINE_NEW and "0.01 m" not in YOUNG_LINE_NEW:
        raise SystemExit("text check: the shader comment does not name the step")
    c = texts[C]
    if "constexpr u32 HalfSlots = 16;" not in c or c.count("d[15] * counted") != 1:
        raise SystemExit("text check: %s: HalfSlots is not 16 or d[15] is not passed once" % C)
    # the slot runner keeps 300 characters of a line: the r103 half line with r103b's part, at its widest
    line = ("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the same-surface mean "
            "(4 x those of one 2x2 block in four; %u passes in %u frames); r103b: about %.0f a pass had their share "
            "cut as sway (lamp step under 0.01 m)" % (9999999, 4294967295, 4294967295, 9999999))
    once = ("Ray traced lamps (r103b): standing rule off (BB_LAMP_SHADOW_YOUNG_STILL=1; 0: r103 as it was): under a "
            "lamp that stepped under 0.01 m only the reject's and the clamp's cut of the history found where the "
            "surface was makes a pixel young, not the follow, trail cap or unsure cut")
    for name, l in (("half line", line), ("once-line", once)):
        if len(l) > 300:
            raise SystemExit("text check: the %s is %d characters (the slot runner keeps 300)" % (name, len(l)))
        if l.split(": ")[0] not in y:
            raise SystemExit("text check: the %s's start is not in the header" % name)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R103_ROOT)" % ROOT)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for ed in eds:
                cur = apply_one(cur, ed)
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
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r103btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for ed in reversed(eds):
            cur = revert_one(cur, ed)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r103btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
