# r62h_cutout-cards-hit: FEATURE fix on top of r62g (lane r62h of 2026-11-16). Only in the CARDS builds,
# so off unless BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 are on (the builds of before are untouched: see "Off").
#
# Why (owner, 2026-11-16: "I can't see anything in the cut out shadows"). Build 32 (r62g) logs, read again:
#  - "0 card rays cast" is NOT the default lamp. The only logs that carried it are the jobs with a sharp lamp
#    (BB_LAMP_SHADOW_SOFT=0.02: disc = card disc, one combined ray by design). The default (soft, half
#    resolution) lamp jobs of the same run (cg1, cg3, cg4, cutf-stand, cutf-walk: slot logs
#    <slots>/s*/logs/session.log) cast the card ray: 60-84 % of the counted rays, 15-39 % of the
#    rays were stopped by solid geometry first. So no gate stops it; the 'lit' test, the lamp radius
#    (0.10 m), the knob read and the half-resolution path are all fine.
#  - The layer reads of those default-lamp runs: 100.0 % at a level above 0 (a sharp lamp: 91-96 %), 65 % on
#    a texel of alpha 0 (a grass card is mostly clear: plausible, not a wrong UV: the dream house's leaf
#    cards read 0.6 % clear and 98 % kept), 28.6 % on a partly covered texel that the rule dropped, 5.9 %
#    kept. A blade is 1-3 texels of the 256 square layer (a game texture of 512-1024 resampled to 256,
#    then mipped): its alpha peaks near the reference or below, and the footprint level (r63: the
#    camera pixel's footprint at 256 texels a metre, times 2 pixels in the half-resolution first pass)
#    averages it further: the kept texels are a third of the blade texels that the game's own test keeps.
#  - A card ray that is stopped is, mostly, a ray of a blade or leaf pixel itself (the dream house:
#    99.8 % of the rays that met a card were stopped on the first layer read, 1.02 reads a ray; the
#    share view paints the blades pale): a card against its own plant, not a shadow on the wall behind it.
#    The shadow of a blade on the wall exists (the share view of cg1 shows white strips on the wall left of
#    the clumps, in the diff of on and off the same strips), but that wall lies 2-3 m from the torch, which is
#    a weak light there: the picture does not show a shadow on a dark wall. The weeds that stand close to
#    the torch are behind the hunter's arm in these shots.
# What this patch does (CARDS builds only):
#  1. Level: the lamp rays read the layer at level 0 (spec constant 3, BB_RT_CARD_LAMP_LEVEL 0 to 1, default
#     0: the footprint level of r63 times this; 1 = r63/r62g). A lamp ray's shadow is averaged over the
#     frames and the disc's points anyway; the footprint level blurs a thin blade out of the test.
#     (The hint BB_RT_CARD_LAMP_TEXELS high is the wrong way: more texels a metre means a coarser level;
#     16 is the least.)
#  2. Reference: a rule that keeps alpha above a reference (op greater or greater-or-equal, the usual
#     test) keeps, for the lamp rays only, alpha above REF times the reference (spec constant 4,
#     BB_RT_CARD_LAMP_REF 0.1 to 1, default 0.6): the blade that the 256 layer thinned still blocks. 1 = the
#     game's reference. Other ops are untouched. Counted: reads kept only by this ("rescued").
#  3. Start: the card ray (not the solid ray) starts CARD_TMIN further along its way (spec constant 5,
#     BB_RT_CARD_LAMP_TMIN 0 to 0.2 m, default 0.03): a card within 3 cm of the surface is the pixel's own
#     blade or leaf, not a shadow-caster. With it above 0 the two rays are cast for every lit lamp ray with
#     the card disc (also for a sharp lamp, whose single combined ray is r62g's); 0 = r62g.
#  4. Numbers: the card rays' stopping hits by the distance of the hit from the ray's start (under 3 cm,
#     3-10, 10-30, farther), the layer reads of these rays, the reads rescued by the reference, the mean
#     level (rt_card_layers_layout.h, counters 16-22 of now 32; one more log line "Ray traced lamps (r62h)").
# r62g behaviour back: BB_RT_CARD_LAMP_LEVEL=1 BB_RT_CARD_LAMP_REF=1 BB_RT_CARD_LAMP_TMIN=0.
#
# Off: the knobs off build no CARDS pipeline and call nothing of this patch (CardExtrasFromEnv is read only by
# the CARDS builds' code). Every new shader line is inside #ifdef CARDS (point_shadow_ray.comp) or
# #ifdef CARD_TRACE_SHADOW (rt_cards.glsl, defined by the lamp pass alone): the 12 builds without CARDS and
# rt_card_view.comp compile to the same SPIR-V words (proved by compiling before and after).
#
# Cost: no more rays for the default lamp (the r62g two rays); level 0 reads one layer level, not a blend
# of two (a cache miss less); a sharp lamp with TMIN above 0 casts the solid ray and the card ray (one
# more than r62g's combined ray; sharp lamps are not the default). Reads: 3 uint compares and adds a read.
# Memory: the counter buffer 64 -> 128 bytes (two of them: device and readback). No CPU cost per frame.
# NOT measured.
#
# Files: point_shadow_ray.comp, rt_cards.glsl, rt_card_layers_layout.h, vk_point_shadow.cpp, vk_point_shadow.h,
# README.md. No CMakeLists change, no new file.
#
# Not compiled here (no clang++): the C++ spots a compiler could reject are named in the hand-off; the shaders
# were compiled with glslangValidator -V --target-env vulkan1.2 and checked with spirv-val.
#
# Use: python -I -X utf8 r62h_cutout-cards-hit.py check | apply | revert
# Root: R62H_CUTOUT_CARDS_HIT_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the
# originals up in r62h_backup next to this script. Needs r62g applied first (its lines are the anchors). Every
# edit replaces an anchor that it keeps (an insert) or one line that it swaps; each anchor must be found
# exactly once. Revert r62h before r62g (a swapped line of r62g's text is put back by r62h's revert).
import os, sys

ROOT = os.environ.get("R62H_CUTOUT_CARDS_HIT_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62h_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
S = HS + "point_shadow_ray.comp"
G = HS + "rt_cards.glsl"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
H = RV + "vk_point_shadow.h"
R = "README.md"

# (old, new): `old` is found once; `new` replaces it (an insert keeps `old` inside `new`).
EDITS = {
S: [
# --- the header block of the CARDS builds: three more specialization constants
("float card_only_sum = 0.0;\n",
 """float card_only_sum = 0.0;
// bbport (r62h_cutout-cards-hit): specialization constants 3 to 5 (vk_point_shadow.cpp MakeCardBuild):
// CARD_LEVEL_SCALE: times the footprint of a lamp ray's layer read (0: level 0; 1: r63's level);
// CARD_REF_SCALE: times the reference of a greater / greater-or-equal rule, for the lamp rays (1: the
// game's); CARD_TMIN: metres a card ray starts further from the surface than a solid ray (0: r62g's ray).
layout(constant_id = 3) const float CARD_LEVEL_SCALE = 0.0;
layout(constant_id = 4) const float CARD_REF_SCALE = 0.6;
layout(constant_id = 5) const float CARD_TMIN = 0.03;
"""),
# --- the footprint's angle, times the level scale (0: every read at level 0)
("        card_px = angle >= 0.0 && !isinf(angle) ? angle : 0.0;\n",
 """        card_px = angle >= 0.0 && !isinf(angle) ? angle : 0.0;
        card_px *= CARD_LEVEL_SCALE; // bbport (r62h_cutout-cards-hit)
"""),
# --- the card ray: where it starts and the end of its range
("        if (!(card_tmax > reach)) {\n",
 """        // bbport (r62h_cutout-cards-hit): the card ray starts CARD_TMIN along its way at least: a card
        // within that of the surface is the pixel's own blade or leaf
        const float card_tmin = max(reach * 0.5, CARD_TMIN);
        if (!(card_tmax > max(reach, card_tmin))) {
"""),
("                                                 reach * 0.5, card_to / card_len, card_tmax, t_card_cap, width0,\n",
 "                                                 card_tmin, card_to / card_len, card_tmax, t_card_cap, width0,\n"),
# --- the card ray: the reference scale for its reads, its counters
("        cardCount(CARD_LAMP_SHARP_RAYS, 1u);\n",
 """        cardCount(CARD_LAMP_SHARP_RAYS, 1u);
        card_ref_scale = CARD_REF_SCALE; // bbport (r62h_cutout-cards-hit): for this ray's reads only
        card_rescued = 0u;
        card_lod16 = 0u;
"""),
("        cardNote(card_hit);\n",
 """        cardNote(card_hit);
        // bbport (r62h_cutout-cards-hit): the reads of this ray (cardCount counts them on the passes and
        // pixels cardNote counts)
        card_ref_scale = 1.0;
        cardCount(CARD_LAMP_SPLIT_READS, card_hit.tested);
        cardCount(CARD_LAMP_RESCUED, card_rescued);
        cardCount(CARD_LAMP_LOD16, card_lod16);
"""),
("        cardCount(CARD_LAMP_CARD_ONLY, 1u);\n",
 """        cardCount(CARD_LAMP_CARD_ONLY, 1u);
        // bbport (r62h_cutout-cards-hit): the distance of the blocking hit from the ray's start
        cardCount(card_hit.t < 0.03 ? CARD_LAMP_KEPT_D0 : card_hit.t < 0.10 ? CARD_LAMP_KEPT_D1
                  : card_hit.t < 0.30 ? CARD_LAMP_KEPT_D2 : CARD_LAMP_KEPT_D3, 1u);
"""),
# --- the two rays also with a card start (CARD_TMIN) for a lamp whose disc is not larger than the card disc
("    card_target = L + (target - L) * (card_sharp ? CARD_DISC / radius : 1.0);\n",
 """    card_target = L + (target - L) * (card_sharp ? CARD_DISC / radius : 1.0);
    // bbport (r62h_cutout-cards-hit): with CARD_TMIN above 0 the two rays are cast for every lamp (the card
    // ray to the same point where the disc is not larger than CARD_DISC); 0: r62g's single ray there
    card_sharp = card_sharp || (CARD_DISC < 0.5 && CARD_TMIN > 0.0);
"""),
],
G: [
("layout(set = CARD_SET, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;\n",
 """layout(set = CARD_SET, binding = CARD_BINDING_ALPHA) uniform sampler2DArray card_alpha;
#ifdef CARD_TRACE_SHADOW
// bbport (r62h_cutout-cards-hit): card_ref_scale: times the reference of a greater or greater-or-equal
// rule (the lamp pass sets it for one ray's reads; 1: the game's rule); card_rescued: the reads kept only
// because of it; card_lod16: the sum of the levels read, in sixteenths. The lamp pass zeroes the counts
// before the ray and takes them after it.
float card_ref_scale = 1.0;
uint card_rescued = 0u;
uint card_lod16 = 0u;
#endif
"""),
("                   : CARD_DROPPED;\n    return r;\n}\n",
 """                   : CARD_DROPPED;
#ifdef CARD_TRACE_SHADOW
    // bbport (r62h_cutout-cards-hit): the lamp rays keep a texel above card_ref_scale times the reference
    // where the game's rule is "above the reference" (greater, greater or equal): the layer is a
    // resampled copy, thinner than the game's texel at a blade's edge
    if (r.status == CARD_DROPPED && card_ref_scale < 1.0) {
        const uint op = (a.z >> CARD_ROW_OP_SHIFT) & 7u;
        if ((op == CARD_OP_GREATER || op == CARD_OP_GREATER_EQUAL) &&
            cardKeeps(r.alpha, uintBitsToFloat(a.w) * card_ref_scale, op, (a.z & CARD_ROW_NONZERO) != 0u)) {
            r.status = CARD_KEPT;
            ++card_rescued;
        }
    }
#endif
    return r;
}
"""),
("            r.lod_reads += lod > 0.0 ? 1u : 0u; // bbport (r62g_cutout-shadows-visible)\n",
 """            r.lod_reads += lod > 0.0 ? 1u : 0u; // bbport (r62g_cutout-shadows-visible)
            card_lod16 += uint(lod * 16.0 + 0.5); // bbport (r62h_cutout-cards-hit)
"""),
],
L: [
("#define CARD_LAMP_SOLID_FIRST 15\n",
 """#define CARD_LAMP_SOLID_FIRST 15
// bbport (r62h_cutout-cards-hit): seven more, of the card rays of the two-ray form (r62g): the rays that a
// card stopped by the distance of the hit from the ray's start (under 3 cm, under 10, under 30, farther), the
// reads of these rays, those kept only by the reference scale (BB_RT_CARD_LAMP_REF) and the sum of the
// levels read in sixteenths.
#define CARD_LAMP_KEPT_D0 16
#define CARD_LAMP_KEPT_D1 17
#define CARD_LAMP_KEPT_D2 18
#define CARD_LAMP_KEPT_D3 19
#define CARD_LAMP_RESCUED 20
#define CARD_LAMP_LOD16 21
#define CARD_LAMP_SPLIT_READS 22
"""),
("#define CARD_LAMP_COUNTERS 16\n",
 "#define CARD_LAMP_COUNTERS 32 // (r62h: was 16)\n"),
],
C: [
("static_assert(CARD_LAMP_COUNTERS == 16);\n",
 """static_assert(CARD_LAMP_COUNTERS == 32); // bbport (r62h_cutout-cards-hit): was 16 (header.h card_last)
static_assert(CARD_LAMP_SOLID_FIRST < CARD_LAMP_KEPT_D0 && CARD_LAMP_KEPT_D0 + 3 == CARD_LAMP_KEPT_D3 &&
              CARD_LAMP_KEPT_D3 < CARD_LAMP_RESCUED && CARD_LAMP_RESCUED < CARD_LAMP_LOD16 &&
              CARD_LAMP_LOD16 < CARD_LAMP_SPLIT_READS && CARD_LAMP_SPLIT_READS < CARD_LAMP_COUNTERS);
"""),
("    bool share_view;\n};\n",
 """    bool share_view;
    float level_scale; // bbport (r62h_cutout-cards-hit): BB_RT_CARD_LAMP_LEVEL, 0 to 1, default 0
    float ref_scale;   // BB_RT_CARD_LAMP_REF, 0.1 to 1, default 0.6
    float tmin_m;      // BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m, default 0.03
};
"""),
("        CardExtras e{0.02f, false};\n",
 "        CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f}; // (r62h: three more)\n"),
("        e.share_view = share && share[0] == '1';\n",
 """        e.share_view = share && share[0] == '1';
        // bbport (r62h_cutout-cards-hit): three more numbers (clamped; not a number: the default)
        const auto number = [](const char* name, float fallback, float lo, float hi) {
            if (const char* const text = std::getenv(name)) {
                char* end = nullptr;
                const float value = std::strtof(text, &end);
                if (end != text && std::isfinite(value)) {
                    return std::clamp(value, lo, hi);
                }
            }
            return fallback;
        };
        e.level_scale = number("BB_RT_CARD_LAMP_LEVEL", e.level_scale, 0.0f, 1.0f);
        e.ref_scale = number("BB_RT_CARD_LAMP_REF", e.ref_scale, 0.1f, 1.0f);
        e.tmin_m = number("BB_RT_CARD_LAMP_TMIN", e.tmin_m, 0.0f, 0.2f);
"""),
("    const std::array<u32, 3> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),\n"
 "                                        extras.share_view ? 1u : 0u};\n",
 """    // (r62h_cutout-cards-hit: constants 3 CARD_LEVEL_SCALE, 4 CARD_REF_SCALE, 5 CARD_TMIN)
    const std::array<u32, 6> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),
                                        extras.share_view ? 1u : 0u, std::bit_cast<u32>(extras.level_scale),
                                        std::bit_cast<u32>(extras.ref_scale), std::bit_cast<u32>(extras.tmin_m)};
"""),
("    const std::array<vk::SpecializationMapEntry, 3> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}}};\n",
 "    const std::array<vk::SpecializationMapEntry, 6> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}}};\n"),
("                                          : \"shows where the rays met cards (BB_RT_CARD_LAMP_SHARE_VIEW=1: the share a card alone blocked)\");\n"
 "        }\n",
 """                                          : "shows where the rays met cards (BB_RT_CARD_LAMP_SHARE_VIEW=1: the share a card alone blocked)");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62h_cutout-cards-hit)
            std::printf("Ray traced lamps (r62h): cut-out cards hit: the lamp rays read the layer at the footprint's "
                        "level times %.2f (BB_RT_CARD_LAMP_LEVEL, 0 to 1; 1 = r63's level, 0 = level 0), keep a texel "
                        "above %.2f times the game's reference where its rule is 'above the reference' "
                        "(BB_RT_CARD_LAMP_REF, 0.1 to 1; 1 = the game's), and the card ray starts at least %.3f m from "
                        "the surface (BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m; 0 = r62g's single ray for a lamp whose disc is "
                        "not larger than the card disc); r62g's behaviour: LEVEL=1 REF=1 TMIN=0\\n",
                        double(extras.level_scale), double(extras.ref_scale), double(extras.tmin_m));
        }
"""),
("                    share(kept_reads, reads), double(extras.disc_m));\n    }\n",
 """                    share(kept_reads, reads), double(extras.disc_m));
    }
    {
        // bbport (r62h_cutout-cards-hit): the two-ray form's rays by where a card stopped them, and its reads
        // (the numbers first). Near hits (under 3 cm) are the pixel's own blade or leaf, far ones a shadow.
        const CardExtras extras = CardExtrasFromEnv();
        const double stopped = d[CARD_LAMP_KEPT_D0] + d[CARD_LAMP_KEPT_D1] + d[CARD_LAMP_KEPT_D2] +
                               d[CARD_LAMP_KEPT_D3];
        const double split_reads = d[CARD_LAMP_SPLIT_READS];
        std::printf("Ray traced lamps (r62h): of %.0f card rays cast, %.0f stopped by a card: %.1f %% within 3 cm of "
                    "the ray's start, %.1f %% 3-10 cm, %.1f %% 10-30 cm, %.1f %% farther; of %.0f layer reads of "
                    "these rays %.1f %% kept only by the reference scale %.2f, mean level %.2f (level scale %.2f); "
                    "card ray starts %.3f m from the surface at least (BB_RT_CARD_LAMP_TMIN)\\n",
                    d[CARD_LAMP_SHARP_RAYS], stopped, share(d[CARD_LAMP_KEPT_D0], stopped),
                    share(d[CARD_LAMP_KEPT_D1], stopped), share(d[CARD_LAMP_KEPT_D2], stopped),
                    share(d[CARD_LAMP_KEPT_D3], stopped), split_reads, share(d[CARD_LAMP_RESCUED], split_reads),
                    double(extras.ref_scale), split_reads > 0.0 ? d[CARD_LAMP_LOD16] / 16.0 / split_reads : 0.0,
                    double(extras.level_scale), double(extras.tmin_m));
    }
"""),
],
H: [
("    std::array<u32, 16> card_last{};\n",
 "    std::array<u32, 32> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS\n"),
],
}

ROW = (
    "| `BB_RT_CARD_LAMP_LEVEL`, `BB_RT_CARD_LAMP_REF`, `BB_RT_CARD_LAMP_TMIN` | Cut-out shadows that show; only with "
    "`BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1`. The lamp rays' card test is made for a blade of grass that "
    "the layer (a 256 square copy of the game's texture, with mips) has thinned: `BB_RT_CARD_LAMP_LEVEL` (0 to 1) "
    "multiplies the footprint the layer's level is taken from (0: level 0, the default; 1: the level of the "
    "ray's footprint as before; `BB_RT_CARD_LAMP_TEXELS` high gives a coarser level, 16 the finest); "
    "`BB_RT_CARD_LAMP_REF` (0.1 to 1) multiplies the game's reference where its alpha rule keeps a texel above "
    "it (the usual test), for the lamp rays only (1: the game's reference); `BB_RT_CARD_LAMP_TMIN` (metres, 0 to "
    "0.2) starts the card ray that far from the surface at least (a card closer than that is the pixel's own "
    "leaf, not a shadow); above 0 a lamp of any size casts the two rays (the solid one and the card one), "
    "so a sharp lamp costs one ray more than before, and 0 gives r62g's single ray for it. All three read at "
    "start. `LEVEL=1 REF=1 TMIN=0` is r62g. The log's r62h line says how many card rays were stopped within "
    "3 cm of their start (the pixel's own plant), within 10 and 30 cm and farther (a shadow on what lies "
    "behind), how many reads the reference scale kept and the mean level | `0`, `0.6`, `0.03`; off |")
ANCHOR_ROW = "| `BB_RT_CARD_LAMP_RADIUS`, `BB_RT_CARD_LAMP_SHARE_VIEW` |"


def readme_edit(text):
    """The README row goes after the r62g row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_RADIUS row is there %d times, wanted 1 (r62g applied?)" % len(lines))
    return (lines[0] + "\n", lines[0] + "\n" + ROW + "\n")


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


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit, else refuse. A swap (new does not hold old) is applied when old is
    gone and new is there once; an insert (new holds old) when new is there once."""
    done = todo = 0
    for old, new in eds:
        n_old, n_new = cur.count(old), cur.count(new)
        holds = old in new
        if n_old == 1 and n_new == 0:
            todo += 1
        elif (holds and n_old == 1 and n_new == 1) or (not holds and n_old == 0 and n_new == 1):
            done += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted once, none): %r"
                             % (path, n_old, n_new, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def inside_only(text, markers, flags, what):
    """Every line of `text` that holds one of `markers` lies inside an #ifdef of `flags` (a set of names)."""
    stack = []
    for line in text.split("\n"):
        st = line.strip()
        if st.startswith("#ifdef") or st.startswith("#ifndef") or st.startswith("#if "):
            stack.append(st.startswith("#ifdef") and st.split()[1] in flags)
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = False
        elif any(m in line for m in markers) and not any(stack):
            raise SystemExit("text check: %s: a line of r62h is outside its #ifdef: %r" % (what, line))


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    s, g, l, c, h = texts[S], texts[G], texts[L], texts[C], texts[H]
    for want, n in (("layout(constant_id = 3) const float CARD_LEVEL_SCALE = 0.0;", 1),
                    ("layout(constant_id = 4) const float CARD_REF_SCALE = 0.6;", 1),
                    ("layout(constant_id = 5) const float CARD_TMIN = 0.03;", 1),
                    ("card_px *= CARD_LEVEL_SCALE;", 1),
                    ("card_sharp = card_sharp || (CARD_DISC < 0.5 && CARD_TMIN > 0.0);", 1),
                    ("card_tmin, card_to / card_len, card_tmax, t_card_cap, width0,", 1),
                    ("card_ref_scale = CARD_REF_SCALE;", 1), ("card_ref_scale = 1.0;", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    if g.count("float card_ref_scale = 1.0;") != 1 or g.count("++card_rescued;") != 1:
        raise SystemExit("text check: rt_cards.glsl: card_ref_scale / card_rescued")
    inside_only(s, ("r62h", "CARD_LEVEL_SCALE", "CARD_REF_SCALE", "CARD_TMIN", "card_ref_scale", "card_rescued",
                    "card_lod16", "CARD_LAMP_KEPT_D"), {"CARDS"}, S)
    inside_only(g, ("r62h", "card_ref_scale", "card_rescued", "card_lod16"), {"CARD_TRACE_SHADOW"}, G)
    want = ["KEPT_D0 16", "KEPT_D1 17", "KEPT_D2 18", "KEPT_D3 19", "RESCUED 20", "LOD16 21", "SPLIT_READS 22"]
    for name in want:
        if l.count("#define CARD_LAMP_" + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define CARD_LAMP_%s" % (L, name))
    if l.count("#define CARD_LAMP_COUNTERS 32 ") != 1:
        raise SystemExit("text check: CARD_LAMP_COUNTERS is not 32")
    if c.count("static_assert(CARD_LAMP_COUNTERS == 32);") != 1 or "std::array<u32, 32> card_last{};" not in h:
        raise SystemExit("text check: the counter count is not 32 in the cpp and the header")
    # six spec words, six entries, offsets 0 to 20
    if c.count("std::array<u32, 6> spec_words{") != 1 or c.count("std::array<vk::SpecializationMapEntry, 6> spec_entries{{{0, 0, 4}") != 1:
        raise SystemExit("text check: spec words / entries")
    if "{5, 20, 4}" not in c or c.count("std::bit_cast<u32>(extras.tmin_m)};") != 1:
        raise SystemExit("text check: spec constant 5")
    if c.count('"BB_RT_CARD_LAMP_LEVEL"') != 1 or c.count('"BB_RT_CARD_LAMP_REF"') != 1 or c.count('"BB_RT_CARD_LAMP_TMIN"') != 1:
        raise SystemExit("text check: env names")
    if c.count("CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f};") != 1:
        raise SystemExit("text check: CardExtras initializer")
    # r62h's printf formats: a '%' count equals the arguments (a check of the two lines)
    for key in ("Ray traced lamps (r62h): cut-out cards hit:", "Ray traced lamps (r62h): of %.0f card rays cast"):
        if c.count(key) != 1:
            raise SystemExit("text check: log line %r" % key)
    row = [x for x in texts[R].split("\n") if x.startswith("| `BB_RT_CARD_LAMP_LEVEL`")]
    if len(row) != 1 or not row[0].endswith("| `0`, `0.6`, `0.03`; off |"):
        raise SystemExit("text check: README row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62H_CUTOUT_CARDS_HIT_ROOT)" % ROOT)
    plan = []
    for path in (S, G, L, C, H, R):
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
            for old, new in eds:
                cur = cur.replace(old, new)
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
            print("REFUSED: already applied")
            sys.exit(1)
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r62htmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r62htmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
