# r93_lamp-shadow-spatial: FEATURE patch (lamp work, proposal R3 of the 2026-11-15 layered shadows
# study, approved by the owner with R1 and R2). Off by default behind BB_LAMP_SHADOW_SPATIAL=1.
#
# What it does: in the centred window's resolve (BB_LAMP_SHADOW_WINDOW=2, the default; the builds made
# with CENTRED, at full and at half resolution) the answer this frame's rays gave a pixel is taken into
# the history as its mix with the mean of it and the answers of its 3x3 neighbours (the 5x5 answers
# are already in the resolve's tile) that have an answer and lie on the pixel's surface: within
# SPATIAL_PLANE_M (1 cm) + SPATIAL_PLANE_REL (0.5%) x distance of the plane through the pixel with its
# normal from depth. The mean's share u (reviewed version, see below): 1 where no history was found;
# 0 where the mean of the pixel's last few frames (held_fast, raw answers) lies within SPATIAL_SETTLED
# (1e-4) of 0 or 1 (about 15 to 17 frames of one answer: a settled hard edge or contact shadow keeps
# its own answer, so it is not blurred at all once settled); else min(8 r (1 - r), 1), r the history's
# ratio as found (held_ratio before the guards move it): all of the mean for r between about 0.15 and
# 0.85 (a penumbra). A new or moving edge is blurred by at most one tap (1 px; at half resolution the
# first pass's pixels, one in four, have taps 2 px apart).
# Every guard against trails (the 5x5 bound and its own-answer widening, the reject's fast mean, the
# soft follow's fit, the follow evidence, the trail cap) takes the raw answer exactly as before; `fast`
# stays the raw answers' mean. Only the sample blended into the history (and so the ratio shown) is
# the filtered one.
# REVIEW (2026-11-15): the draft's u = min(8 f (1 - f), 1) with f = held_fast was biased: the shader's
# per-pixel R2 walk makes the pixel's next answer anticorrelated with its last few (after a lit frame
# f is high and the next answer is likely dark), so u was high when the raw answer was the rare one
# and the mean replaced it then. A one-lamp model of the walk (scratch r93_sim_bias.py) gave a ramp pulled
# toward 0.5 by up to 0.044 (0.2 -> 0.244, 0.8 -> 0.756). The gate above gives at most 0.011 there
# (0.05 -> 0.061); a model, not measured in the game.
#
# Off (the default): bit 26 of tune word 0 is never set (LampTuneSpatialBit), the shader's t_spatial
# stays false, `spatial` stays -1 and the inserted branches are skipped (spatial_u is computed only
# with spatial >= 0): every statement of before runs on the same values (bit-identical picture). The
# builds without CENTRED (plain, half, cards, half cards) compile to the same SPIR-V words (all new
# shader text is inside #ifdef CENTRED).
#
# Files: point_shadow_ray.comp (t_spatial, loadTune, spatialMean, the resolve's mean, the mean's
# share, the blend), lamp_shadow_tune.h (LampShadowTune::spatial, ReadLampShadowTune, LampTuneSpatial,
# LampTuneSpatialBit), vk_point_shadow.cpp (Ready: a once-line; Flush: data[tune_at] |=
# LampTuneSpatialBit, the count; TrackLamps: a short r93 line after the r42 line, because the slot runs
# keep only 300 characters of a log line and the r42 line is longer than that before its lamps),
# vk_point_shadow.h (line_spatial), test_lamp_shadow_tune.cpp, README.md (a row after
# BB_LAMP_SHADOW_CLAMP).
#
# Every edit only inserts text before or after an anchor that it keeps whole, so the parallel
# patches R1 (bit 24, record word 10) and R2 (bit 25) can anchor on the same lines in any order.
#
# Use: python -I -X utf8 r93_lamp-shadow-spatial.fixed.py check | apply | revert
# Root: R93_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up
# in r93_backup next to this script; revert takes out exactly what apply inserted: each inserted
# text is found by itself (exactly once), not next to its anchor, so check and revert also work when
# a patch applied later (r92) inserted its own text between this one's and the anchor.
import os, sys

ROOT = os.environ.get("R93_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r93_backup")
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
T = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
H = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.h"
U = "engine/tests/test_lamp_shadow_tune.cpp"
R = "README.md"

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
S: [
("bool t_centred = false;         // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 (with t_window)\n",
 "",
 "bool t_spatial = false;         // bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL (bit 26; the resolve)\n"),
("    t_centred = (f & (1u << 22u)) != 0u;     // bbport (r60_lamp-centred-window)\n",
 "",
 "    t_spatial = (f & (1u << 26u)) != 0u;     // bbport (r93_lamp-shadow-spatial)\n"),
("        loadCell(i, lo, apart);\n    }\n}\n",
 "",
 r"""
// bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL=1 (word 0 bit 26, read by the resolve
// only). The mean of this frame's answers of the pixel and of its 3x3 neighbours in the tile (cell:
// the pixel's own cell; apart: as loadTile, so the neighbours are 2 full pixels apart in the
// half-resolution build's first pass) that have an answer and lie on the pixel's surface: within
// SPATIAL_PLANE_M + SPATIAL_PLANE_REL times its distance of the plane through P with the normal n
// (zero: worked out here from depth, as surfaceNormal does; none: -1, no mean). A plane, not the
// history's depth test (3% + 2 cm): a caster a few centimetres off a wall (a hand, a contact) is
// left out, and a floor seen at a flat angle, whose depth changes fast from pixel to pixel, is kept.
// 1 cm + 0.5% (1.75 cm at 1.5 m, 6 cm at 10 m) holds the depth normal's error of several degrees
// over a tap two pixels away (not measured in the game). A tap with an answer was traced this
// frame, so its depth was valid there (the trace's tests). (In the second half-resolution pass a
// tap whose pixel took its block's answer holds that block's averaged ratio, as in the 5x5 window.)
// SPATIAL_SETTLED: the mean of the pixel's last few frames (held_fast) this close to 0 or 1 counts as
// all dark or all lit, and the history takes the pixel's own answer (main): fast keeps 0.6 of itself
// a frame (FAST_KEEP), so one other answer k frames ago leaves 0.4 x 0.6^k (below 1e-4 after 17
// frames; at 1 the rgba16f history rounds to 1 after about 15).
const float SPATIAL_PLANE_M = 0.01;
const float SPATIAL_PLANE_REL = 0.005;
const float SPATIAL_SETTLED = 1e-4;
float spatialMean(ivec2 cell, ivec2 px, vec3 P, vec3 n, float answer, int apart) {
    const vec3 nn = n != vec3(0.0) ? n : surfaceNormal((vec2(px) + 0.5) / size, P);
    if (nn == vec3(0.0)) {
        return -1.0;
    }
    const float tol = SPATIAL_PLANE_M + SPATIAL_PLANE_REL * P.z;
    float sum = answer, count = 1.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            const float a = tile_answer[(cell.y + y) * TILE_SIDE + cell.x + x];
            if ((x | y) == 0 || !(a >= 0.0)) {
                continue;
            }
            const vec2 uv_q = (vec2(px + apart * ivec2(x, y)) + 0.5) / size;
            const vec3 Q = viewPosAt(uv_q, textureLod(depth_tex, uv_q, 0.0).x);
            if (abs(dot(nn, Q - P)) < tol) {
                sum += a;
                count += 1.0;
            }
        }
    }
    return sum / count;
}
"""),
("        float count = 0.0, sum = 0.0, sum2 = 0.0, near_n = 0.0, far_n = 0.0, swing = 0.0;\n",
 "",
 "#ifdef CENTRED\n"
 "        float spatial = -1.0; // bbport (r93_lamp-shadow-spatial): spatialMean's; below 0: none\n"
 "#endif\n"),
("        } else\n#endif\n        if (t_window || !t_follow_soft) {\n",
 "            if (t_spatial) { // bbport (r93_lamp-shadow-spatial): from the raw answers in the tile\n"
 "                spatial = spatialMean(own, px, P, n, answer, resolve_apart);\n"
 "            }\n",
 ""),
("        if (held) {\n            fast = mix(answer, held_fast, FAST_KEEP);\n",
 "#ifdef CENTRED\n"
 "        // bbport (r93_lamp-shadow-spatial): the 3x3 mean's share in the sample the history takes in\n"
 "        // (below), from the history as it was found, before the guards below move it toward this\n"
 "        // frame's answers: all of it where no history was found; none where the pixel's last few\n"
 "        // frames were all dark or all lit (held_fast within SPATIAL_SETTLED of 0 or 1: a settled hard\n"
 "        // edge or contact shadow keeps its own answer); else 8 r (1 - r) up to 1, r the history's\n"
 "        // ratio (all of it for r between about 0.15 and 0.85, a penumbra). Not from held_fast alone:\n"
 "        // the pixel's R2 walk (samplePoint) makes its next answer anticorrelated with its last few, so\n"
 "        // a share from them pulled the ramp toward 0.5 (by up to 0.044 in a one-lamp model; this one\n"
 "        // by up to 0.011, not measured in the game).\n"
 "        float spatial_u = 1.0;\n"
 "        if (spatial >= 0.0 && held) {\n"
 "            spatial_u = min(held_fast, 1.0 - held_fast) > SPATIAL_SETTLED\n"
 "                            ? min(8.0 * held_ratio * (1.0 - held_ratio), 1.0)\n"
 "                            : 0.0;\n"
 "        }\n"
 "#endif\n",
 ""),
("        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));\n",
 "#ifdef CENTRED\n"
 "        if (spatial >= 0.0) {\n"
 "            // bbport (r93_lamp-shadow-spatial): the sample the history takes in is this frame's answer\n"
 "            // mixed with its 3x3 mean by spatial_u (above), with the frames the guards left. Every guard\n"
 "            // above took the raw answer, and `fast` (stored below) is still the raw answers' mean.\n"
 "            const float sample_in = mix(answer, spatial, spatial_u);\n"
 "            ratio = held ? mix(sample_in, held_ratio, frames / (frames + 1.0)) : sample_in;\n"
 "        }\n"
 "#endif\n",
 ""),
],
T: [
("                                 ///< pixel; 0: anywhere\n",
 "",
 "    bool spatial = false;        ///< bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL: 1: the\n"
 "                                 ///< centred window's resolve (window_centred) takes into the history\n"
 "                                 ///< this frame's answer mixed with the mean of it and its 3x3\n"
 "                                 ///< neighbours on the pixel's plane, unless the pixel's last frames were all lit\n"
 "                                 ///< or all dark (point_shadow_ray.comp spatialMean, spatial_u); 0: as\n"
 "                                 ///< before\n"),
("inline constexpr std::uint32_t LampTuneCentred = 1u << 22;    // bbport (r60_lamp-centred-window)\n",
 "",
 "// bbport (r93_lamp-shadow-spatial): bit 26, BB_LAMP_SHADOW_SPATIAL, read only by the CENTRED builds'\n"
 "// resolve. LampTuneWords leaves it 0; vk_point_shadow.cpp Flush sets it (LampTuneSpatialBit).\n"
 "inline constexpr std::uint32_t LampTuneSpatial = 1u << 26;\n"),
("                                  LampTuneWindow | (7u << LampTuneViewShift) | (0x3Fu << 12))) == 0);\n",
 "",
 "// bbport (r93_lamp-shadow-spatial): bit 26 is none of the bits above either\n"
 "static_assert((LampTuneSpatial & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |\n"
 "                                  LampTuneWindow | LampTuneCentred | (7u << LampTuneViewShift) |\n"
 "                                  (0x3Fu << 12))) == 0);\n"
 "/// bbport (r93_lamp-shadow-spatial): word 0's bit 26 for a pass: set only with the centred window,\n"
 "/// whose resolve is the only code that reads it.\n"
 "inline constexpr std::uint32_t LampTuneSpatialBit(const LampShadowTune& tune) {\n"
 "    return tune.spatial && tune.window && tune.window_centred ? LampTuneSpatial : 0u;\n"
 "}\n"),
("        tune.around = std::max(tune.around, LampAroundLeast);\n    }\n",
 "",
 "    tune.spatial = Whole(get, \"BB_LAMP_SHADOW_SPATIAL\", tune.spatial ? 1u : 0u, 1u) != 0; // bbport (r93)\n"),
],
H: [
("    u32 line_blend = 0, line_read = 0, line_cuts = 0, line_beside = 0, line_half = 0;\n",
 "",
 "    // bbport (r93_lamp-shadow-spatial): the frames of line_blend whose pass ran its resolve with word 0\n"
 "    // bit 26 (BB_LAMP_SHADOW_SPATIAL=1 and the centred window); said in the r93 line after the r42 line\n"
 "    u32 line_spatial = 0;\n"),
],
C: [
("                        resolve_pipeline ? \"its own\" : resolve_wanted ? \"the centred one (its own could not be made)\"\n"
 "                                                                      : \"the centred one\");\n"
 "        }\n",
 "",
 "        // bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL=1, said once (on or off and why first:\n"
 "        // the slot runs keep 300 characters of a line)\n"
 "        if (tune.spatial) {\n"
 "            std::printf(\"Ray traced lamps (r93): spatial pre-filter %s (BB_LAMP_SHADOW_SPATIAL=1%s): the centred \"\n"
 "                        \"window's resolve takes into the history this frame's answer mixed with the mean of it and \"\n"
 "                        \"its 3x3 neighbours that have an answer and lie on the pixel's plane (point_shadow_ray.comp \"\n"
 "                        \"spatialMean): all of the mean where no history was found, none where the pixel's last \"\n"
 "                        \"frames were all lit or all dark, else 8 r (1 - r) of it, r the history's ratio; every \"\n"
 "                        \"guard against trails takes the raw answer; nothing with sharp lamps (no history), views \"\n"
 "                        \"2, 3 and 7, or in a half-resolution pass that runs its plain build\\n\",\n"
 "                        centred ? \"on\" : \"off\",\n"
 "                        centred ? \"\"\n"
 "                                : \"; it needs the centred window, BB_LAMP_SHADOW_WINDOW=2, which this run does not \"\n"
 "                                  \"have (not set, or its build could not be made)\");\n"
 "        }\n"),
("            data.insert(data.end(), tune_words.begin(), tune_words.end());\n",
 "",
 "            data[tune_at] |= LampTuneSpatialBit(pass_tune); // bbport (r93_lamp-shadow-spatial): bit 26\n"),
("    if (split) {\n        answers_short = false;\n    }\n",
 "",
 "    line_spatial += split && repair && LampTuneSpatialBit(pass_tune) != 0u ? 1 : 0; // bbport (r93)\n"),
("    std::printf(\"\\n\");\n    line_blend = line_read = line_cuts = line_beside = line_half = 0;\n",
 "",
 "    // bbport (r93_lamp-shadow-spatial): a short line of its own right after the r42 line, at its\n"
 "    // times (the slot runs keep 300 characters of a log line; the r42 line is longer before its lamps)\n"
 "    if (tune.spatial) {\n"
 "        std::printf(\"Ray traced lamps (r93): the spatial pre-filter ran in the resolve on %u of the frames \"\n"
 "                    \"the r42 line above counts as averaged\\n\",\n"
 "                    line_spatial);\n"
 "    }\n"
 "    line_spatial = 0; // bbport (r93_lamp-shadow-spatial)\n"),
],
U: [
("    std::puts(\"lamp shadow tune: ok\");\n",
 r"""    // bbport (r93_lamp-shadow-spatial): BB_LAMP_SHADOW_SPATIAL is off unless set to 1 (2 or more: 1;
    // below 0 or text: off). It changes none of LampTuneWords' words nor the history block's: Flush
    // ORs bit 26 in (LampTuneSpatialBit), and only with the centred window (0 and 1 have no resolve).
    {
        static_assert(LampTuneSpatial == 1u << 26);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(!d.spatial && LampTuneSpatialBit(d) == 0u);
        const LampShadowTune on = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "1"}}});
        assert(on.spatial && LampTuneSpatialBit(on) == (LampWindowDefault == 2 ? LampTuneSpatial : 0u));
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "0"}}}).spatial);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "3"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "-1"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", "yes"}}}).spatial);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", ""}}}).spatial);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SPATIAL", " 1 "}}}).spatial);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const char* window : {"0", "1", "2"}) {
            const std::array<Pair, 2> with{{{"BB_LAMP_SHADOW_WINDOW", window}, {"BB_LAMP_SHADOW_SPATIAL", "1"}}};
            const std::array<Pair, 1> without{{{"BB_LAMP_SHADOW_WINDOW", window}}};
            const LampShadowTune t = Read(with), p = Read(without);
            assert(t.spatial && !p.spatial);
            const auto words = LampTuneWords(t, true, 0.05f, view.data(), 9u);
            assert(words == LampTuneWords(p, true, 0.05f, view.data(), 9u) && (words[0] & LampTuneSpatial) == 0u);
            assert(LampHistoryTail(t) == LampHistoryTail(p));
            assert(LampTuneSpatialBit(t) == (window[0] == '2' ? LampTuneSpatial : 0u) && LampTuneSpatialBit(p) == 0u);
        }
        // As bit 22: never without the window, even with window_centred set.
        LampShadowTune odd = on;
        odd.window = false;
        odd.window_centred = true;
        assert(LampTuneSpatialBit(odd) == 0u);
    }
""",
 ""),
],
# README.md: readme_edit (the row after the BB_LAMP_SHADOW_CLAMP row)
}

ROW = ("| `BB_LAMP_SHADOW_SPATIAL` | `1`: with `BB_LAMP_SHADOW_WINDOW=2` (the default) the lamp pass takes into a "
       "pixel's history this frame's shadow answer mixed with the mean of it and the answers of its 3x3 neighbours "
       "that lie on its surface (within 1 cm plus 0.5% of the distance of the pixel's plane): all of the mean where "
       "the pixel has no history yet, none where its last 15 or so frames were all lit or all dark (a settled hard "
       "edge or contact shadow), else 8 r (1 - r) of it, r the pixel's averaged shadow ratio (all of it for r "
       "between about 0.15 and 0.85: a penumbra). So soft shadow edges settle into smooth bands instead of "
       "grain, also while they move. The guards that stop trails behind moving shadows still take the pixel's own "
       "answer. At half resolution (`graphics_lamp_shadow_half=1`) the pixel of each 2x2 block that the first pass "
       "traces takes its neighbouring blocks' pixels, 2 pixels apart. It does nothing with `BB_LAMP_SHADOW_WINDOW` "
       "0 or 1, with sharp lamps (no history), with `BB_LAMP_SHADOW_VIEW` 2, 3 or 7, and in a half-resolution pass "
       "whose centred build could not be made. `0`: as before | `0` |\n")


def readme_edit(text):
    """The README row goes after the BB_LAMP_SHADOW_CLAMP row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_CLAMP` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_CLAMP row is there %d times, wanted 1" % len(lines))
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


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    s = texts[S]
    for want, n in (("(1u << 26u)", 1), ("bool t_spatial = false;", 1), ("float spatialMean(", 1),
                    ("spatial = spatialMean(own, px, P, n, answer, resolve_apart);", 1),
                    ("const float SPATIAL_PLANE_M = 0.01;", 1), ("const float SPATIAL_PLANE_REL = 0.005;", 1),
                    ("const float SPATIAL_SETTLED = 1e-4;", 1), ("float spatial_u = 1.0;", 1),
                    ("mix(answer, spatial, spatial_u)", 1), ("min(8.0 * held_ratio * (1.0 - held_ratio), 1.0)", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # every r93 line of the shader lies inside #ifdef CENTRED (the other builds keep their SPIR-V)
    depth, centred_at = 0, []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            centred_at.append(st == "#ifdef CENTRED")
        elif st.startswith("#endif"):
            centred_at.pop()
        elif ("r93" in line or "spatial" in line.lower()) and not any(centred_at):
            raise SystemExit("text check: r93 shader line outside #ifdef CENTRED: %r" % line)
    if "(1 << 26)" in texts[T] or texts[T].count("LampTuneSpatial = 1u << 26;") != 1:
        raise SystemExit("text check: LampTuneSpatial is not bit 26")
    row = [l for l in texts[R].split("\n") if l.startswith("| `BB_LAMP_SHADOW_SPATIAL` |")]
    if len(row) != 1 or "1 cm plus 0.5%" not in row[0] or "0.15 and 0.85" not in row[0] or \
            "8 r (1 - r)" not in row[0]:
        raise SystemExit("text check: README row and shader constants disagree")
    # the spatial_u block sits after the 5x5 mean (it reads `spatial`) and before the blend (which reads it)
    a, b, c = s.find("spatial = spatialMean("), s.find("float spatial_u = 1.0;"), s.find("mix(answer, spatial, spatial_u)")
    if not (0 <= a < b < c):
        raise SystemExit("text check: spatialMean, spatial_u and the blend are out of order")
    # the r93 count is a line of its own, after the r42 line's end
    cs = texts[C]
    if cs.find('Ray traced lamps (r93): the spatial pre-filter ran') < cs.find(
            '    std::printf("\\n");\n    line_blend = line_read = line_cuts = line_beside = line_half = 0;\n'):
        raise SystemExit("text check: the r93 count line is not after the r42 line")


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse.
    Inserted texts are found by themselves, not next to their anchor: a later patch may have put its own
    text between them (r92's draft inserts on the same side of two of these anchors: before the test's
    "lamp shadow tune: ok" line and after the bit static_assert in lamp_shadow_tune.h)."""
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
        raise SystemExit("%s is not a source tree root (set R93_ROOT)" % ROOT)
    plan = []
    for path in (S, T, H, C, U, R):
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
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            # no inserted text holds another edit's anchor or text: the result reads as applied
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
            tmp = full + ".r93tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    # each inserted text is taken out where it is (once: state_of found it once), so a later patch's
    # text that came between it and its anchor stays; all files are worked out before any is written
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
        tmp = full + ".r93tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
