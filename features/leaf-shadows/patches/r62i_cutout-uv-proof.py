# r62i_cutout-uv-proof: FEATURE (a test view of the cut-out lamp shadows, with the feature's other debug knobs; it stays
# with the feature branch, as the share view does) on top of r62h (build 36). Only in the CARDS builds of the lamp pass,
# so off unless BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 are on AND BB_RT_CARD_LAMP_PROOF_VIEW is 1 or 2 (see "Off").
#
# Why. Build 36 (r62h) forced the lamp rays' layer reads to level 0 and the card ray fires for the default lamp
# (78-86 % of the counted rays), yet 80.7 % of the reads land on a texel of alpha 0 and only 1.7-2.5 % of the rays are
# stopped by a card alone; the pictures show nothing blade-shaped. Two readings are open:
#   (A) the chain is right: a lamp ray crosses a card at a random place, and a grass card is mostly clear, so most reads
#       are alpha 0 and a ray is rarely blocked (the shadow of sparse blades is thin and faint);
#   (B) the chain is wrong: the card hit -> record UV -> layer texel link reads the wrong place (a UV set, the
#       barycentric weights, a scale/offset/flip, the wrong texture in the layer, the wrong layer for the instance, the
#       hit's primitive index against the index list the UVs were captured for).
# The lamp rays' reads cannot tell (A) from (B): nothing says where a ray ought to land. The proof view can: a pixel
# whose G-buffer surface IS a card (the game's own alpha test kept it) is a place where the answer is known. A camera
# ray to that pixel meets the card instance near the G-buffer depth; the layer read at the hit's UV (the same
# cardTestLod, instanceCustomIndex, primitive index, barycentrics, pool record, row, layer as a lamp ray's read) must say
# "kept", and painted over the screen it must reproduce the blades as the game draws them.
#
# What this patch does (CARDS builds of point_shadow_ray.comp, view 7 only):
#  1. BB_RT_CARD_LAMP_PROOF_VIEW=1 (specialization constant 6, read once, like BB_RT_CARD_LAMP_SHARE_VIEW): with
#     BB_LAMP_SHADOW_VIEW=7 (which may be set live by the live knobs file: the game is started with the PROOF env) the
#     lamp pass paints, for every pixel it shadows, the proof: a tiny ray from the camera (view space origin) to the
#     pixel's point against ALL instances (as rt_card_view.comp does), the card candidate within the depth tolerance
#     (0.5 % + 2 cm, CARD_VIEW_TOL_*) nearest to the depth is read at layer level 0 with the game's own reference
#     (card_ref_scale 1). Colour: WHITE the layer says kept, BLACK dropped, magenta the card has no data, teal the card's
#     rule is not judged (sun pass rule, dithered, or a rule keeping no alpha), dark blue the pixel's surface is not a
#     card. Value 2 paints the layer's alpha itself (grey, times the vertex factor) instead of white/black.
#     The shown light is multiplied by the surface's colour like every other view (white weeds look green).
#  2. Counters (indices 23-31 of the 32 of r62h; no more memory): screen pixels read, not a card, kept, dropped on alpha
#     0, dropped on a partly covered texel, no data, not judged, kept at level 1 (what a coarser read says), coordinates
#     outside 0-1 (a repeat or a clamp at work). On the counted passes (one in 16) at one pixel in 16. One log line
#     'Ray traced lamps (r62i)' every 600 frames while the knob is on, and a once-line at start.
#  How to read it: kept near 100 % of the judged card pixels and the picture shows the blades = (A), the chain is right
#  and nothing is to fix in it (then the lamp ray's alpha-0 share is the grass' real emptiness and the next lever is
#  more rays or a wider footprint on the wall, not the chain). Kept near the share a random place gives (about the
#  fraction of the card that is blade, 20-30 %), or white where the game draws no blade = (B): the picture's wrong
#  places and the 'coordinates outside 0-1' and level-1 counts say which link: smooth wrong blades = UV/offset/flip
#  (compare BB_RT_CARD_ALPHA_VIEW=3 UV view), uniform black = the layer is empty (a fill before the texture upload or a
#  layer of another texture), patchy = primitive index/pool mismatch. The lamp rays read through the same function, so a
#  fix of the chain reaches them without another change.
#
# Off: nothing of this patch runs without the knob. The new shader lines are inside #ifdef CARDS; the 12 builds without
# CARDS are byte-identical (proved by compiling before and after), the 4 CARDS builds change only by dead code behind
# the specialization constant CARD_PROOF (0: the view block and the proof function fold away when the pipeline is
# specialized; the 7th spec word is 0). CardExtrasFromEnv is read only by the code that makes a CARDS build.
#
# Cost (NOT measured): only while the proof view is on (a test view; view 7 on top): one more short ray query a shadowed
# pixel (camera to its surface, through all instances, up to the surface) and two layer reads, a few atomic adds on 1 pixel
# in 16 of one pass in 16. Off: 0. Memory: none (the counters 23-31 lie in the 32 uints of r62h).
#
# Files: point_shadow_ray.comp, rt_card_layers_layout.h, vk_point_shadow.cpp, README.md. No new file, no CMake change.
# Not compiled here (no clang++): the C++ spots a compiler could reject are named in the hand-off.
#
# Use: python -I -X utf8 r62i_cutout-uv-proof.py check | apply | revert
# Root: R62I_CUTOUT_UV_PROOF_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r62i_backup next to this script. Needs r62h applied first (its lines are the anchors). Revert r62i before r62h.
import os, sys

ROOT = os.environ.get("R62I_CUTOUT_UV_PROOF_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62i_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
S = HS + "point_shadow_ray.comp"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
R = "README.md"

# (old, new): `old` is found once; `new` replaces it (an insert keeps `old` inside `new`; a swap does not).
EDITS = {
S: [
# --- the 7th specialization constant
("layout(constant_id = 5) const float CARD_TMIN = 0.03;\n",
 """layout(constant_id = 5) const float CARD_TMIN = 0.03;
// bbport (r62i_cutout-uv-proof): specialization constant 6 (vk_point_shadow.cpp, BB_RT_CARD_LAMP_PROOF_VIEW): 0 off;
// 1: BB_LAMP_SHADOW_VIEW=7 paints the proof of the card chain (white: the layer keeps the texel a screen card pixel's
// camera ray hits, black dropped); 2: the layer's alpha as grey.
layout(constant_id = 6) const uint CARD_PROOF = 0u;
"""),
# --- the proof function and its counter
("        atomicAdd(card_counts[index], n);\n    }\n}\n",
 """        atomicAdd(card_counts[index], n);
    }
}

// bbport (r62i_cutout-uv-proof): the proof of the chain "card hit -> pool record UV -> layer texel", for the pixels whose
// G-buffer surface is a card. A camera ray (origin 0, the TLAS's view space) to the pixel's point P meets every candidate
// up to just past it (no opaque flag, the others confirmed: rt_card_view.comp's way); the card candidate whose distance is
// nearest the pixel's depth distance, within CARD_VIEW_TOL_*, is the game's own surface there (the game's alpha test kept
// it), and cardTestLod reads it with the instance's slot, the primitive index and the barycentrics, as a lamp ray's
// read does, at level 0 with the game's reference (card_ref_scale is 1 outside a lamp ray's reads). The classes:
const uint PROOF_NO_CARD = 0u;   // the surface is not a card (or none within the tolerance)
const uint PROOF_KEPT = 1u;      // the layer keeps the texel (what must hold on a pixel the game kept)
const uint PROOF_ZERO = 2u;      // dropped on a texel of alpha 0
const uint PROOF_PARTIAL = 3u;   // dropped on a partly covered texel
const uint PROOF_NO_DATA = 4u;   // the card has no data (row not ready, layer gone, primitive past the pool)
const uint PROOF_UNJUDGED = 5u;  // the row's rule is the sun pass's, dithered, or keeps no alpha: not comparable
uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {
    r0 = CardResult(CARD_NO_DATA, 0.0, vec2(0.0), vec2(0.0), 0u);
    kept_l1 = false;
    uv_outside = false;
    const float depth_t = length(P);
    if (!(depth_t > 1e-3)) {
        return PROOF_NO_CARD;
    }
    const float tol = float(CARD_VIEW_TOL_REL) * depth_t + float(CARD_VIEW_TOL_ABS);
    rayQueryEXT query;
    rayQueryInitializeEXT(query, scene, gl_RayFlagsNoOpaqueEXT, 0xffu, vec3(0.0), 0.0, P / depth_t,
                          depth_t + 2.0 * tol);
    float best_diff = 1e30;
    uint best_slot = 0u, best_primitive = 0u;
    vec2 best_bary = vec2(0.0);
    while (rayQueryProceedEXT(query)) {
        if (rayQueryGetIntersectionTypeEXT(query, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {
            continue;
        }
        const uint slot = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false));
        if (slot == 0u) {
            rayQueryConfirmIntersectionEXT(query);
            continue;
        }
        const float diff = abs(rayQueryGetIntersectionTEXT(query, false) - depth_t);
        if (diff < tol && diff < best_diff) {
            best_diff = diff;
            best_slot = slot;
            best_primitive = uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false));
            best_bary = rayQueryGetIntersectionBarycentricsEXT(query, false);
        }
    }
    if (best_slot == 0u) {
        return PROOF_NO_CARD;
    }
    // (review) the nearest solid surface the ray met (a confirmed hit) is the pixel's surface when it lies at least as
    // near the depth as the card: the ground a few cm behind a grass card's clear texel, which the game shows there,
    // must not be read as that card (it would count as "dropped" and bias the proof toward a broken chain)
    if (rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionTriangleEXT &&
        abs(rayQueryGetIntersectionTEXT(query, true) - depth_t) <= best_diff) {
        return PROOF_NO_CARD;
    }
    r0 = cardTestLod(best_slot, best_primitive, best_bary, 0.0);
    if (r0.status == CARD_NO_DATA) {
        return PROOF_NO_DATA;
    }
    uv_outside = any(lessThan(r0.raw, vec2(-0.001))) || any(greaterThan(r0.raw, vec2(1.001)));
    kept_l1 = cardTestLod(best_slot, best_primitive, best_bary, 1.0).status == CARD_KEPT;
    if ((r0.flags & (CARD_ROW_SUN | CARD_ROW_DITHER | CARD_ROW_CLEAR)) != 0u) {
        return PROOF_UNJUDGED;
    }
    return r0.status == CARD_KEPT ? PROOF_KEPT : r0.alpha <= 0.0 ? PROOF_ZERO : PROOF_PARTIAL;
}

// One proof counter's add: on the counted passes (MODE_CARD_COUNT), from one pixel in 16.
void proofCount(uint index) {
    if ((mode & MODE_CARD_COUNT) != 0u && ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 3u) == 0u) {
        atomicAdd(card_counts[index], 1u);
    }
}
"""),
# --- the view: 7 with the proof on
("        if (t_view == 7u && CARD_VIEW_SHARE != 0u) {\n",
 """        // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW=1 or 2: 7 paints the proof of the card chain on every
        // pixel the pass shadows (cardProof): white the layer keeps the texel the game kept, black dropped, magenta no
        // data, teal not judged, dark blue not a card; with 2 the layer's alpha as grey. Counted (CARD_LAMP_PROOF_*).
        if (CARD_PROOF != 0u && t_view == 7u && live) {
            CardResult proof;
            bool proof_l1 = false, proof_outside = false;
            const uint proof_class = cardProof(P, proof, proof_l1, proof_outside);
            proofCount(CARD_LAMP_PROOF_PIXELS);
            proofCount(CARD_LAMP_PROOF_NO_CARD + proof_class);
            if (proof_class != PROOF_NO_CARD && proof_class != PROOF_NO_DATA) {
                if (proof_class != PROOF_UNJUDGED && proof_l1) {
                    proofCount(CARD_LAMP_PROOF_KEPT_L1);
                }
                if (proof_outside) {
                    proofCount(CARD_LAMP_PROOF_UV_OUTSIDE);
                }
            }
            shown = proof_class == PROOF_NO_CARD  ? vec3(0.0, 0.0, 0.1 + 0.1 * answer)
                    : proof_class == PROOF_NO_DATA ? vec3(1.0, 0.0, 1.0)
                    : CARD_PROOF == 2u             ? vec3(proof.alpha)
                    : proof_class == PROOF_KEPT    ? vec3(1.0)
                    : proof_class == PROOF_UNJUDGED ? vec3(0.0, 0.5, 0.5)
                                                    : vec3(0.0);
        } else
        if (t_view == 7u && CARD_VIEW_SHARE != 0u) {
"""),
],
L: [
("#define CARD_LAMP_SPLIT_READS 22\n",
 """#define CARD_LAMP_SPLIT_READS 22
// bbport (r62i_cutout-uv-proof): nine more of the 32, of the proof view (BB_RT_CARD_LAMP_PROOF_VIEW): the screen pixels
// read, then one counter a class of cardProof (not a card, kept, dropped on alpha 0, dropped on a partly covered texel,
// no data, not judged: CARD_LAMP_PROOF_NO_CARD + class), the card pixels the layer's level 1 keeps, and the card pixels
// whose raw coordinates lie outside 0-1.
#define CARD_LAMP_PROOF_PIXELS 23
#define CARD_LAMP_PROOF_NO_CARD 24
#define CARD_LAMP_PROOF_KEPT 25
#define CARD_LAMP_PROOF_ZERO 26
#define CARD_LAMP_PROOF_PARTIAL 27
#define CARD_LAMP_PROOF_NO_DATA 28
#define CARD_LAMP_PROOF_UNJUDGED 29
#define CARD_LAMP_PROOF_KEPT_L1 30
#define CARD_LAMP_PROOF_UV_OUTSIDE 31
"""),
],
C: [
("              CARD_LAMP_LOD16 < CARD_LAMP_SPLIT_READS && CARD_LAMP_SPLIT_READS < CARD_LAMP_COUNTERS);\n",
 """              CARD_LAMP_LOD16 < CARD_LAMP_SPLIT_READS && CARD_LAMP_SPLIT_READS < CARD_LAMP_COUNTERS);
// bbport (r62i_cutout-uv-proof): its nine counters fill the last of the 32
static_assert(CARD_LAMP_SPLIT_READS < CARD_LAMP_PROOF_PIXELS && CARD_LAMP_PROOF_NO_CARD == CARD_LAMP_PROOF_PIXELS + 1 &&
              CARD_LAMP_PROOF_UNJUDGED == CARD_LAMP_PROOF_NO_CARD + 5 &&
              CARD_LAMP_PROOF_UV_OUTSIDE == CARD_LAMP_COUNTERS - 1);
"""),
("    float tmin_m;      // BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m, default 0.03\n};\n",
 """    float tmin_m;      // BB_RT_CARD_LAMP_TMIN, 0 to 0.2 m, default 0.03
    u32 proof_view;    // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW, 0 (off), 1 or 2
};
"""),
("        CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f}; // (r62h: three more)\n",
 "        CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f, 0u}; // (r62h: three more; r62i: the proof view)\n"),
("        e.tmin_m = number(\"BB_RT_CARD_LAMP_TMIN\", e.tmin_m, 0.0f, 0.2f);\n",
 """        e.tmin_m = number("BB_RT_CARD_LAMP_TMIN", e.tmin_m, 0.0f, 0.2f);
        // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW 1 or 2 (anything else: off)
        if (const char* const proof = std::getenv("BB_RT_CARD_LAMP_PROOF_VIEW")) {
            e.proof_view = proof[0] == '1' && proof[1] == '\\0' ? 1u : proof[0] == '2' && proof[1] == '\\0' ? 2u : 0u;
        }
"""),
("    const std::array<u32, 6> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),\n",
 "    const std::array<u32, 7> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),\n"),
("                                        std::bit_cast<u32>(extras.ref_scale), std::bit_cast<u32>(extras.tmin_m)};\n",
 "                                        std::bit_cast<u32>(extras.ref_scale), std::bit_cast<u32>(extras.tmin_m),\n"
 "                                        extras.proof_view}; // (r62i_cutout-uv-proof: constant 6 CARD_PROOF)\n"),
("    const std::array<vk::SpecializationMapEntry, 6> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}}};\n",
 "    const std::array<vk::SpecializationMapEntry, 7> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}}};\n"),
("                        double(extras.level_scale), double(extras.ref_scale), double(extras.tmin_m));\n        }\n",
 """                        double(extras.level_scale), double(extras.ref_scale), double(extras.tmin_m));
        }
        if (const CardExtras extras = CardExtrasFromEnv(); extras.proof_view != 0) { // bbport (r62i_cutout-uv-proof)
            std::printf("Ray traced lamps (r62i): BB_RT_CARD_LAMP_PROOF_VIEW=%u: BB_LAMP_SHADOW_VIEW=7 paints the proof "
                        "of the card chain on every shadowed pixel: a camera ray to a pixel whose surface is a card, "
                        "the layer read at the hit's coordinates (white: kept, as the game kept it, black: dropped, "
                        "magenta: no data, teal: rule not judged, dark blue: not a card%s); the log counts them\\n",
                        extras.proof_view, extras.proof_view == 2 ? "; 2: the layer's alpha as grey in place of white/black" : "");
        }
"""),
("                    double(extras.level_scale), double(extras.tmin_m));\n    }\n",
 """                    double(extras.level_scale), double(extras.tmin_m));
    }
    if (CardExtrasFromEnv().proof_view != 0) {
        // bbport (r62i_cutout-uv-proof): the proof view's numbers (cardProof; view 7 must be on, else all 0): of the
        // screen pixels read, the card pixels by what the layer said at the camera ray's hit. On a pixel the game kept,
        // 'kept' must be near 100 % if the chain is right.
        const double pixels = d[CARD_LAMP_PROOF_PIXELS];
        const double cards = pixels - d[CARD_LAMP_PROOF_NO_CARD];
        const double judged = d[CARD_LAMP_PROOF_KEPT] + d[CARD_LAMP_PROOF_ZERO] + d[CARD_LAMP_PROOF_PARTIAL];
        std::printf("Ray traced lamps (r62i): proof of %.0f screen pixels, %.0f card pixels (%.1f %% of them no data, "
                    "%.1f %% not judged); of %.0f judged card pixels: %.1f %% kept at level 0, %.1f %% dropped on alpha "
                    "0, %.1f %% dropped on a partly covered texel, %.1f %% kept at level 1; %.1f %% of the card pixels "
                    "have coordinates outside 0-1 (BB_RT_CARD_LAMP_PROOF_VIEW, view 7)\\n",
                    pixels, cards, share(d[CARD_LAMP_PROOF_NO_DATA], cards), share(d[CARD_LAMP_PROOF_UNJUDGED], cards),
                    judged, share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_PROOF_ZERO], judged),
                    share(d[CARD_LAMP_PROOF_PARTIAL], judged), share(d[CARD_LAMP_PROOF_KEPT_L1], judged),
                    share(d[CARD_LAMP_PROOF_UV_OUTSIDE], cards));
    }
"""),
],
}

ROW = (
    "| `BB_RT_CARD_LAMP_PROOF_VIEW` | A test view that proves the cut-out card chain (the card a ray hits, its coordinates, the "
    "layer's texel); only with `BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1`, read at start. `1`: with "
    "`BB_LAMP_SHADOW_VIEW=7` (also set live) the lamp pass paints, on every pixel it shadows whose surface is a card (the "
    "game's own alpha test kept it), the layer's answer at the card the camera sees there: white the layer keeps the texel, "
    "black dropped, magenta the card has no data, teal its rule is not comparable (sun pass, dithered), dark blue not a "
    "card. On a weed bed the white must be the blades as the game draws them. `2`: the layer's alpha as grey. The log's "
    "`Ray traced lamps (r62i)` line counts the card pixels read kept or dropped (kept near 100 % when the chain is right) | "
    "unset; off |")
ANCHOR_ROW = "| `BB_RT_CARD_LAMP_LEVEL`, `BB_RT_CARD_LAMP_REF`, `BB_RT_CARD_LAMP_TMIN` |"


def readme_edit(text):
    """The README row goes after the r62h row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_LEVEL row is there %d times, wanted 1 (r62h applied?)" % len(lines))
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
            raise SystemExit("text check: %s: a line of r62i is outside its #ifdef: %r" % (what, line))


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    s, l, c = texts[S], texts[L], texts[C]
    for want, n in (("layout(constant_id = 6) const uint CARD_PROOF = 0u;", 1),
                    ("uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {", 1),
                    ("void proofCount(uint index) {", 1),
                    ("if (CARD_PROOF != 0u && t_view == 7u && live) {", 1),
                    ("proofCount(CARD_LAMP_PROOF_NO_CARD + proof_class);", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    inside_only(s, ("r62i", "CARD_PROOF", "cardProof", "proofCount", "PROOF_NO_CARD", "PROOF_KEPT", "CARD_LAMP_PROOF"),
                {"CARDS"}, S)
    want = ["PIXELS 23", "NO_CARD 24", "KEPT 25", "ZERO 26", "PARTIAL 27", "NO_DATA 28", "UNJUDGED 29",
            "KEPT_L1 30", "UV_OUTSIDE 31"]
    for name in want:
        if l.count("#define CARD_LAMP_PROOF_" + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define CARD_LAMP_PROOF_%s" % (L, name))
    if l.count("#define CARD_LAMP_COUNTERS 32 ") != 1:
        raise SystemExit("text check: CARD_LAMP_COUNTERS is not 32 (r62h applied?)")
    # class ids index the counters: NO_CARD + 0 .. + 5 must be the six counters 24-29 in the order of the PROOF_ constants
    order = ("PROOF_NO_CARD = 0u", "PROOF_KEPT = 1u", "PROOF_ZERO = 2u", "PROOF_PARTIAL = 3u", "PROOF_NO_DATA = 4u",
             "PROOF_UNJUDGED = 5u")
    for o in order:
        if s.count("const uint " + o + ";") != 1:
            raise SystemExit("text check: class constant %s" % o)
    if c.count("std::array<u32, 7> spec_words{") != 1 or c.count("std::array<vk::SpecializationMapEntry, 7> spec_entries{{{0, 0, 4}") != 1:
        raise SystemExit("text check: spec words / entries")
    if "{6, 24, 4}" not in c or c.count("extras.proof_view}; // (r62i_cutout-uv-proof: constant 6 CARD_PROOF)") != 1:
        raise SystemExit("text check: spec constant 6")
    if c.count('"BB_RT_CARD_LAMP_PROOF_VIEW"') != 1:
        raise SystemExit("text check: env name")
    if c.count("CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f, 0u};") != 1:
        raise SystemExit("text check: CardExtras initializer")
    for key in ("Ray traced lamps (r62i): BB_RT_CARD_LAMP_PROOF_VIEW=%u:", "Ray traced lamps (r62i): proof of %.0f screen pixels"):
        if c.count(key) != 1:
            raise SystemExit("text check: log line %r" % key)
    row = [x for x in texts[R].split("\n") if x.startswith("| `BB_RT_CARD_LAMP_PROOF_VIEW`")]
    if len(row) != 1 or not row[0].endswith("| unset; off |"):
        raise SystemExit("text check: README row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62I_CUTOUT_UV_PROOF_ROOT)" % ROOT)
    plan = []
    for path in (S, L, C, R):
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
            tmp = full + ".r62itmp"
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
        tmp = full + ".r62itmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
