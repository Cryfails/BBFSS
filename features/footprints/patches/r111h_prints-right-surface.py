# r111h_prints-right-surface: FEATURE fix on top of r111 to r111g (b46: the graveyard prints read as small BRIGHT red
# splatter clusters, not dark boot soles; one print was stamped on the hunter's hat (scene z 2.68 against the print's
# view z 8.65); the church's wet prints could not be seen; the dream house "do-nothing" diff of 5.9 was not confirmed
# as zero because its log lines were not read). Still off unless BB_FOOTPRINTS is set and still costs nothing when
# off (every edit is inside Footprints, which is not made without the knob, or inside the post stamp's shader, which
# only that object dispatches). Branch: visual/footprints.
#
# WHAT CHANGES
#  (1) Right surface (footprints_flat.comp, footprints_layout.h). The post stamp (a) leaves out a pixel that is much
#      nearer the camera than the print it would take weight from: its view z under POST_NEAR_FRAC (0.9) of the
#      print's own view z AND more than POST_NEAR_M (0.3 m) nearer (a character or a plant in front of the print;
#      the absolute part keeps the near end of a sole at a 1.5 m close-up, which is 0.14 m nearer, from being
#      cut); (b) reads the ground facing from points POST_NORMAL_PX (3) pixels away, not 1 (cobbles' depth noise
#      made the facing speckle, which is part of why a print read as a splatter), and gives no facing at all where a
#      neighbour's view z differs from the pixel's by more than POST_NEIGHBOUR_M + POST_NEIGHBOUR_REL x z (0.15 m +
#      5%: a silhouette, so the edge of a character, a hat or a plant never reads as ground).
#      Honest note: the old height band (within 0.16 m of the print's height) already left out a point far above or
#      beside the print; (a) and (b) are the explicit nearer-than-the-print rule the owner asked for and cover a
#      pixel whose depth is a neighbour's. The b46 hat blob is not explained by the logs; the close-up and the
#      same-framing gbc job (below) are the proof.
#  (2) Blood prints: a DEEP dark red, not a bright one (POST_BLOOD_LUM 0.25, was 0.70: the stamp is the tint, whose
#      luminance is 1, times 0.25 of the lit pixel's luminance, so its red channel is about 0.97 of the stone's and
#      green and blue 0.05: dark maroon, where 0.70 made the red channel 2.7 times the stone's, bright red). The
#      sole is already a boot (heel block, waist, ball: 0.28 x 0.11 m, heel behind along the walk; r111d). The first
#      print of a trail is the strongest and the trail fades from it: BloodFullPrints 1 (was 4), BloodKeep 0.8 (was
#      0.75): strengths 1, 0.80, 0.64, 0.51, 0.41, 0.33, 0.26 ... dry after 13 prints (the same count as before).
#  (3) Wet prints on stone: the post stamp darkens the lit pixel 55% (POST_WET_DARKEN 0.55, was 0.40; the G-buffer
#      change stays the albedo multiply only: no gloss, no specular) with a soft edge: the wet sole's edge ramps over
#      the outer 45% of its radius (POST_WET_EDGE 0.55; blood keeps EDGE 0.82, about 1 cm).
#  (4) Log: "Footprints (r111h): totals at frame N: P prints placed (...), L live, Q post passes with prints, S px
#      stamped in R read-backs (most M), G G-buffer passes" at construction (zeros), at frame 240 and every 600
#      frames: a do-nothing place logs 0 prints, 0 passes and 0 px explicitly. And a once-line with the look.
#      (Jobs: gbc now runs gb1's exact action sequence, so its framing is gb1's; both add a close-up capture about
#      1.5 m from the trail at the graveyard.)
#
# How the code guarantees nothing runs when the feature is off: BB_FOOTPRINTS unset -> Footprints is not made, its
# hook is one null pointer test, and nothing here is reached (LogTotals is called only from its constructor and
# OnFrameEnd; the shader edits run only inside the post stamp's dispatch). Cost: the stamp pass gets two more
# depth reads per pixel (the neighbours are the same two reads, farther), and one view-z per print whose sole
# contains the pixel (a 9-multiply product, only for pixels with weight); no new buffer, no new pass. Memory: one
# u64 counter.
#
# Files edited (the text r111g left; each old text found exactly once): footprints_layout.h, footprints_flat.comp,
# footprints.h, vk_footprints.h, vk_footprints.cpp, engine/tests/test_footprints.cpp, README.md.
# r111g's own `check` refuses after this patch (its text checks want the old look numbers: blood lum above 0.3,
# wet darken below 0.6 is still true, the lum is not): use r111h's check instead; revert r111h before r111g.
#
# Order: needs r111g applied (refused otherwise).
# Use: python -I -X utf8 r111h_prints-right-surface.py check | apply | revert
# Root: R111H_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111h_backup next to this script; revert puts each old text back (each new text found by itself, exactly once).
import os, re, sys

ROOT = os.environ.get("R111H_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111h_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
LAYOUT = HS + "footprints_layout.h"
FLAT = HS + "footprints_flat.comp"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [LAYOUT, FLAT, RULES, VKH, VKC, TEST, README]

# (old, new): `old` found exactly once and `new` not at all (clean), or `new` exactly once (applied).
EDITS = {
    LAYOUT: [
        (r'''#define FOOTPRINTS_POST_WET_DARKEN 0.40
''',
         r'''// (r111h) A wet or mud print darkens the lit pixel 55% (was 40%) with a soft edge (the sole's outer 45% of its
// radius, POST_WET_EDGE; blood keeps EDGE).
#define FOOTPRINTS_POST_WET_DARKEN 0.55
#define FOOTPRINTS_POST_WET_EDGE 0.55
'''),
        (r'''#define FOOTPRINTS_POST_BLOOD_LUM 0.70
''',
         r'''// (r111h) A DEEP dark red, 0.25 of the lit pixel's luminance (was 0.70, which put the red channel at 2.7 times
// the stone's: bright red): the red channel is about 0.97 of the stone's, green and blue 0.05.
#define FOOTPRINTS_POST_BLOOD_LUM 0.25
// (r111h) The right surface: a pixel whose view z is under NEAR_FRAC of its print's view z and more than NEAR_M
// nearer is not on the print (a character or a plant in front of it); the facing is read from points NORMAL_PX
// pixels away and not across a depth jump of more than NEIGHBOUR_M + NEIGHBOUR_REL x z.
#define FOOTPRINTS_POST_NEAR_FRAC 0.9
#define FOOTPRINTS_POST_NEAR_M 0.3
#define FOOTPRINTS_POST_NORMAL_PX 3
#define FOOTPRINTS_POST_NEIGHBOUR_M 0.15
#define FOOTPRINTS_POST_NEIGHBOUR_REL 0.05
'''),
    ],
    FLAT: [
        (r'''// The world point of a neighbour pixel; false for the sky.
bool Neighbour(ivec2 q, out vec3 w) {
    const float z = ViewZ(texelFetch(depth_tex, q, 0).x);
    w = World(q, z);
    return z > 0.0;
}
''',
         r'''// The world point of a neighbour pixel; false for the sky. (r111h) Also false across a depth jump (its view z
// differs from the centre pixel's `z0` by more than POST_NEIGHBOUR_M + POST_NEIGHBOUR_REL x z0: a silhouette), so
// the edge of a character, a hat or a plant never reads as ground from two points on different surfaces.
bool Neighbour(ivec2 q, float z0, out vec3 w) {
    const float z = ViewZ(texelFetch(depth_tex, q, 0).x);
    w = World(q, z);
    return z > 0.0 && abs(z - z0) < FOOTPRINTS_POST_NEIGHBOUR_M + FOOTPRINTS_POST_NEIGHBOUR_REL * z0;
}
'''),
        (r'''float Ellipse(vec2 d, vec2 r) {
    return 1.0 - smoothstep(FOOTPRINTS_EDGE, 1.0, length(d / r));
}
float Sole(float u, float v) {
    const float fore = Ellipse(vec2(u - FOOTPRINTS_FORE_U, v), vec2(FOOTPRINTS_FORE_RU, FOOTPRINTS_FORE_RV));
    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV));
    const float waist = Ellipse(vec2(u - FOOTPRINTS_WAIST_U, v), vec2(FOOTPRINTS_WAIST_RU, FOOTPRINTS_WAIST_RV));
    return max(max(fore, heel), waist);
}
''',
         r'''// (r111h) `edge`: where the soft edge starts, as a share of the radius (EDGE for blood, POST_WET_EDGE for wet).
float Ellipse(vec2 d, vec2 r, float edge) {
    return 1.0 - smoothstep(edge, 1.0, length(d / r));
}
float Sole(float u, float v, float edge) {
    const float fore = Ellipse(vec2(u - FOOTPRINTS_FORE_U, v), vec2(FOOTPRINTS_FORE_RU, FOOTPRINTS_FORE_RV), edge);
    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV), edge);
    const float waist = Ellipse(vec2(u - FOOTPRINTS_WAIST_U, v), vec2(FOOTPRINTS_WAIST_RU, FOOTPRINTS_WAIST_RV), edge);
    return max(max(fore, heel), waist);
}
'''),
        (r'''        const float s = Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE) * pr.a.w;
        const uint kind = min(uint(pr.b.w + 0.5), FOOTPRINTS_KINDS - 1u);
        weight[kind] = max(weight[kind], s);
''',
         r'''        const uint kind = min(uint(pr.b.w + 0.5), FOOTPRINTS_KINDS - 1u);
        const float s = Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE,
                             kind == FOOTPRINTS_KIND_BLOOD ? FOOTPRINTS_EDGE : FOOTPRINTS_POST_WET_EDGE) * pr.a.w;
        if (s <= 0.0) {
            continue;
        }
        // (r111h) a pixel much nearer the camera than the print (a character or a plant in front of it) is not
        // on the print: its view z is under POST_NEAR_FRAC of the print's and more than POST_NEAR_M nearer
        const float pz = ViewOf(pr.a.xyz).z;
        if (z < FOOTPRINTS_POST_NEAR_FRAC * pz && pz - z > FOOTPRINTS_POST_NEAR_M) {
            continue;
        }
        weight[kind] = max(weight[kind], s);
'''),
        (r'''    const ivec2 qx = ivec2(p.x < last.x ? p.x + 1 : p.x - 1, p.y);
    const ivec2 qy = ivec2(p.x, p.y < last.y ? p.y + 1 : p.y - 1);
''',
         r'''    // (r111h) POST_NORMAL_PX pixels away, not 1: the cobbles' depth noise made a 1 pixel facing speckle
    const int nb = FOOTPRINTS_POST_NORMAL_PX;
    const ivec2 qx = ivec2(p.x + nb <= last.x ? p.x + nb : max(p.x - nb, 0), p.y);
    const ivec2 qy = ivec2(p.x, p.y + nb <= last.y ? p.y + nb : max(p.y - nb, 0));
'''),
        (r'''    if (Neighbour(qx, wx) && Neighbour(qy, wy)) {
''',
         r'''    if (Neighbour(qx, z, wx) && Neighbour(qy, z, wy)) {
'''),
    ],
    RULES: [
        (r'''// (r111d: BloodFullPrints is 4 and BloodKeep 0.75: 4 full prints, then 0.75, 0.56 ... dry after 13, the
''',
         r'''// (r111h: BloodFullPrints is 1 and BloodKeep 0.8: the first print of a trail is the strongest and it fades from
// there, 1, 0.8, 0.64, 0.51 ... dry after 13 as before.)
// (r111d: BloodFullPrints is 4 and BloodKeep 0.75: 4 full prints, then 0.75, 0.56 ... dry after 13, the
'''),
        (r'''inline constexpr std::uint32_t BloodFullPrints = 4; ///< a blood coat: this many full prints (r111d: 4, was 3)
inline constexpr float BloodKeep = 0.75f;           ///< then each step keeps this much (r111d: 0.75, was 0.7)
''',
         r'''inline constexpr std::uint32_t BloodFullPrints = 1; ///< a blood coat: this many full prints (r111h: 1, was 4)
inline constexpr float BloodKeep = 0.8f;            ///< then each step keeps this much (r111h: 0.8, was 0.75)
'''),
    ],
    VKH: [
        (r'''        int box_w = 0, box_h = 0;                      ///< the largest print box on a screen, px
''',
         r'''        int box_w = 0, box_h = 0;                      ///< the largest print box on a screen, px
        u64 stamp_px_sum = 0; ///< (r111h) the post stamp's pixels, summed over the read-backs
'''),
        (r'''    void LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const; // (r111g)
''',
         r'''    void LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const; // (r111g)
    void LogTotals() const; // (r111h)
'''),
    ],
    VKC: [
        (r'''        LogStamp(0, 0, 0, std::array<float, 3>{}); // (r111g)
    }
''',
         r'''        LogStamp(0, 0, 0, std::array<float, 3>{}); // (r111g)
        LogTotals();                               // (r111h) a zero copy
    }
    BbReport::Printf("Footprints (r111h): blood prints dark red at %.2f of the lit luminance, strongest first (%u full, "
                     "keep %.2f); wet darkens %.0f%% with edge %.2f; a pixel nearer than %.0f%% of its print's view z "
                     "is skipped; facing read over %d px\n",
                     double(FOOTPRINTS_POST_BLOOD_LUM), R::BloodFullPrints, double(R::BloodKeep),
                     double(FOOTPRINTS_POST_WET_DARKEN) * 100.0, double(FOOTPRINTS_POST_WET_EDGE),
                     double(FOOTPRINTS_POST_NEAR_FRAC) * 100.0, int(FOOTPRINTS_POST_NORMAL_PX));
'''),
        (r'''void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
''',
         r'''/// (r111h) Totals, numbers first: at construction (zeros), at frame 240 and every LineFrames frames, so a place
/// where nothing is placed says 0 prints, 0 passes, 0 px explicitly.
void Footprints::LogTotals() const {
    BbReport::Printf("Footprints (r111h): totals at frame %u: %u prints placed (%u blood, %u wet, %u mud), %u live, %u "
                     "post passes, %llu px stamped in %u read-backs (most %u), %u G-buffer passes\n",
                     stats.frames, stats.by_kind[0] + stats.by_kind[1] + stats.by_kind[2], stats.by_kind[2],
                     stats.by_kind[0], stats.by_kind[1], placed_count, flat.passes,
                     static_cast<unsigned long long>(stats.stamp_px_sum), flat.read_back, flat.post_max,
                     stats.passes);
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
'''),
        (r'''        stats.print_px_max = std::max(stats.print_px_max, px);
        if (px != 0u && !flat_probe.told_stamp) {
''',
         r'''        stats.print_px_max = std::max(stats.print_px_max, px);
        stats.stamp_px_sum += px; // (r111h)
        if (px != 0u && !flat_probe.told_stamp) {
'''),
        (r'''    ++stats.frames;
    stats.planes += plane ? 1 : 0;
''',
         r'''    ++stats.frames;
    stats.planes += plane ? 1 : 0;
    if (stats.frames == 240 || stats.frames % LineFrames == 0) {
        LogTotals(); // (r111h)
    }
'''),
    ],
    TEST: [
        (r'''        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 4u);
''',
         r'''        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 1u);
'''),
        (r'''        // The feet leave the blood (nothing under them: the coat is kept): 4 full prints, then 0.75
        // of the amount a step, dry after 13 prints in all (r111d; r111b had 3 full, then 0.7, 10 prints).
''',
         r'''        // The feet leave the blood (nothing under them: the coat is kept): (r111h) the first print full, then 0.8
        // of the amount a step, dry after 13 prints in all (r111d: 4 full, then 0.75, also 13).
'''),
        (r'''        assert(strength[0] == 1.0f && strength[1] == 1.0f && strength[2] == 1.0f && strength[3] == 1.0f);
        assert(Near(strength[4], 0.75) && Near(strength[5], 0.5625) && Near(strength[12], 0.0751, 1e-3));
        // (r111d) the walk of a short trail: 4 full prints, and 9 more fading over a long walk
        assert(CoatPrints(Kind::Blood) - BloodFullPrints == 9u && CoatPrints(Kind::Wet) - WetFullPrints == 9u);
''',
         r'''        assert(strength[0] == 1.0f && Near(strength[1], 0.8) && Near(strength[2], 0.64) && Near(strength[6], 0.2621, 1e-3) &&
               Near(strength[12], 0.0687, 1e-3));
        // (r111h) the first print is the strongest and each one is weaker than the one before: 1 full print and 12
        // more fading over a long walk (a wet coat: 3 full and 9)
        assert(CoatPrints(Kind::Blood) - BloodFullPrints == 12u && CoatPrints(Kind::Wet) - WetFullPrints == 9u);
'''),
        (r'''        // Blood and wet coats as a table (r111d): blood 4 full then 0.75; wet 3 full then 0.75.
        assert(RuleOf(Kind::Blood).full == 4u && Near(RuleOf(Kind::Blood).keep, 0.75));
''',
         r'''        // Blood and wet coats as a table (r111h): blood 1 full then 0.8; wet 3 full then 0.75.
        assert(RuleOf(Kind::Blood).full == 1u && Near(RuleOf(Kind::Blood).keep, 0.8));
'''),
        (r'''        assert(FOOTPRINTS_POST_BLOOD_LUM < 1.0 && FOOTPRINTS_POST_BLOOD_LUM > 0.3);
''',
         r'''        assert(FOOTPRINTS_POST_BLOOD_LUM < 0.5 && FOOTPRINTS_POST_BLOOD_LUM > 0.1); // (r111h) deep, not bright
'''),
        (r'''        assert(FOOTPRINTS_POST_WET_DARKEN > 0.25 && FOOTPRINTS_POST_WET_DARKEN < 0.6);
''',
         r'''        assert(FOOTPRINTS_POST_WET_DARKEN > 0.45 && FOOTPRINTS_POST_WET_DARKEN < 0.6); // (r111h) 55%
'''),
        (r'''            assert(s <= last && kind == Kind::Blood);
''',
         r'''            assert(s < last && kind == Kind::Blood); // (r111h) strictly weaker with each print
'''),
        (r'''    // Pack.
    {
        float out[PrintFloats];
''',
         r'''    // (r111h) The look in numbers: the stamp's red channel at a full blood print stays under the stone's own
    // (a dark red, never a bright one), the surface rules' numbers, the wet soft edge wider than the blood one.
    {
        const double tr = FOOTPRINTS_POST_BLOOD_TINT_R, tg = FOOTPRINTS_POST_BLOOD_TINT_G;
        const double red_over_stone = tr * FOOTPRINTS_POST_BLOOD_LUM, green_over_stone = tg * FOOTPRINTS_POST_BLOOD_LUM;
        assert(red_over_stone > 0.7 && red_over_stone < 1.1 && green_over_stone < 0.1);
        assert(FOOTPRINTS_POST_WET_EDGE < FOOTPRINTS_EDGE && FOOTPRINTS_POST_WET_EDGE > 0.3);
        assert(FOOTPRINTS_POST_NEAR_FRAC > 0.8 && FOOTPRINTS_POST_NEAR_FRAC < 0.95);
        // the near end of a sole at a 1.5 m close-up (0.14 m nearer than its centre, 0.093) is kept; a hunter 2.7 m
        // from the camera in front of a print 8.65 m away is left out
        const auto left_out = [](double z, double pz) {
            return z < FOOTPRINTS_POST_NEAR_FRAC * pz && pz - z > FOOTPRINTS_POST_NEAR_M;
        };
        assert(!left_out(1.5 - 0.14, 1.5) && left_out(2.68, 8.65) && !left_out(8.65, 8.65) && !left_out(2.5, 2.6));
        assert(FOOTPRINTS_POST_NORMAL_PX >= 2 && FOOTPRINTS_POST_NEIGHBOUR_M > 0.05 && FOOTPRINTS_POST_NEIGHBOUR_REL < 0.2);
    }
    // Pack.
    {
        float out[PrintFloats];
'''),
    ],
    README: [
        (r'''a deeper, more saturated red at 0.7 of that luminance, cover 95%,''',
         r'''a deeper, more saturated red at 0.25 of that luminance (r111h, was 0.7: a dark maroon mark whose red is about the stone's own, no longer a bright red), cover 95%,'''),
        (r'''a wet or mud print darkens the lit pixel a further 40% (r111g, was 25%); times''',
         r'''a wet or mud print darkens the lit pixel a further 55% with a soft edge (r111h; 40% in r111g, 25% before); (r111h) a pixel more than 0.3 m nearer the camera than 90% of its print's view depth (a character or a plant in front of the print) and one whose neighbours lie across a depth jump (a silhouette) are left out, and the facing is read from points 3 pixels away; times'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; is r111g applied, and is this patch's own earlier version reverted?): %r" %
                             (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def split_args(text):
    """The top-level comma separated arguments of a call's text after its format string."""
    out, depth, cur, quote = [], 0, "", False
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == "\\":
                cur += text[i + 1]
                i += 1
            elif ch == '"':
                quote = False
        elif ch == '"':
            quote = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    if cur.strip():
        out.append(cur.strip())
    return out


def define(lay, name):
    m = re.search(r"#define %s ([0-9.]+)\n" % name, lay)
    if not m:
        raise SystemExit("text check: layout lacks %s" % name)
    return float(m.group(1))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    cpp = texts[VKC]
    n_new = 0
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)(.*?)\);\n', cpp, re.S):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        if not fmt.startswith("Footprints (r111h)"):
            continue
        n_new += 1
        convs = re.findall(r"%(?!%)[-+ 0-9.]*(?:ll)?[udfs]", fmt.replace("%%", ""))
        args = split_args(m.group(2).lstrip().lstrip(",")) if m.group(2).strip() else []
        if len(convs) != len(args):
            raise SystemExit("text check: %d conversions, %d arguments: %r" % (len(convs), len(args), fmt[:70]))
        if "%s" in fmt:
            raise SystemExit("text check: a %%s in an r111h line (kinds fold on digits only): %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 10, wide)
        wide = wide.replace("%%", "%")
        print("  r111h log line (wide %d, %d conversions): %s..." % (len(wide), len(convs), fmt[:50]))
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    if n_new != 2:
        raise SystemExit("text check: %d r111h log lines (2 expected)" % n_new)
    if cpp.count("LogTotals()") < 3:
        raise SystemExit("text check: LogTotals calls missing")
    lay = texts[LAYOUT]
    lum = define(lay, "FOOTPRINTS_POST_BLOOD_LUM")
    tr = define(lay, "FOOTPRINTS_POST_BLOOD_TINT_R")
    if not (0.1 < lum < 0.5) or not (0.7 < tr * lum < 1.1):
        raise SystemExit("text check: the blood lum %.2f gives a red of %.2f times the stone's" % (lum, tr * lum))
    print("  blood red channel %.3f of the stone's, green %.3f" % (tr * lum, define(lay, "FOOTPRINTS_POST_BLOOD_TINT_G") * lum))
    wd = define(lay, "FOOTPRINTS_POST_WET_DARKEN")
    if not (0.45 < wd < 0.6):
        raise SystemExit("text check: the post wet darken %.2f is out of range" % wd)
    if not (0.3 < define(lay, "FOOTPRINTS_POST_WET_EDGE") < define(lay, "FOOTPRINTS_EDGE")):
        raise SystemExit("text check: the wet edge must be softer than the blood edge")
    for name in ("FOOTPRINTS_POST_NEAR_FRAC", "FOOTPRINTS_POST_NEAR_M", "FOOTPRINTS_POST_NORMAL_PX",
                 "FOOTPRINTS_POST_NEIGHBOUR_M", "FOOTPRINTS_POST_NEIGHBOUR_REL"):
        define(lay, name)
    # the shader uses every new define and the new signatures
    flat = texts[FLAT]
    for needle in ("FOOTPRINTS_POST_NEAR_FRAC", "FOOTPRINTS_POST_NEAR_M", "FOOTPRINTS_POST_NORMAL_PX",
                   "FOOTPRINTS_POST_NEIGHBOUR_M", "FOOTPRINTS_POST_NEIGHBOUR_REL", "FOOTPRINTS_POST_WET_EDGE",
                   "bool Neighbour(ivec2 q, float z0, out vec3 w)", "Neighbour(qx, z, wx) && Neighbour(qy, z, wy)",
                   "float Sole(float u, float v, float edge)"):
        if needle not in flat:
            raise SystemExit("text check: footprints_flat.comp lacks %r" % needle)
    if "Neighbour(qx, wx)" in flat or "Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE) " in flat:
        raise SystemExit("text check: an old call is left in footprints_flat.comp")
    # the coat: the trail's count is still 13 and no print is stronger than the one before (model of TakeStep)
    h = texts[RULES]
    full = int(re.search(r"BloodFullPrints = (\d+);", h).group(1))
    keep = float(re.search(r"BloodKeep = ([0-9.]+)f;", h).group(1))
    amount, f, strengths = 1.0, full, []
    while amount >= 0.06 and len(strengths) < 64:
        strengths.append(amount)
        if f > 1:
            f -= 1
        else:
            amount *= keep
    print("  blood trail: %d prints, strengths %s" % (len(strengths), " ".join("%.2f" % s for s in strengths[:8])))
    if full != 1 or len(strengths) != 13 or any(b >= a for a, b in zip(strengths, strengths[1:])):
        raise SystemExit("text check: the blood trail is not 13 strictly fading prints from a full first one")
    if "u64 stamp_px_sum" not in texts[VKH] or "void LogTotals() const;" not in texts[VKH]:
        raise SystemExit("text check: vk_footprints.h lacks the totals")
    if "stats.stamp_px_sum += px;" not in cpp:
        raise SystemExit("text check: the stamped px sum is not counted")
    for needle in ("c.full == 1u", "RuleOf(Kind::Blood).full == 1u", "CoatPrints(Kind::Blood) - BloodFullPrints == 12u"):
        if needle not in texts[TEST]:
            raise SystemExit("text check: the unit test lacks %r" % needle)
    for needle in ("a further 55% with a soft edge (r111h", "at 0.25 of that luminance (r111h"):
        if texts[README].count(needle) != 1:
            raise SystemExit("text check: README lacks %r once" % needle)
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111h_prints-right-surface.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111H_ROOT)" % ROOT)
    if "(r111g) the blood weight is rounded" not in load(FLAT)[2]:
        raise SystemExit("REFUSED: r111g is not applied (%s lacks its rounded blood weight)" % FLAT)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (%d files edited; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)" %
                  (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111htmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111htmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
