# r62l_cutout-steady-proof: FEATURE part (BB_RT_CARD_LAMP_STRICT: the strict zone against false cut-out shadows) and TOOL part
# (BB_RT_CARD_LAMP_SPLIT: a same-frame checkerboard A/B; the lit patch's classification counters) for the cut-out lamp shadows,
# on top of r62k (build 44). Only in the CARDS builds of the lamp pass (BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1); with the knobs
# off nothing of it exists (no CARDS pipeline, CardLampsLine returns at once: card_set_layout). The TOOL edits are marked TOOL in their
# comments (the split in point_shadow_ray.comp ray() and main, cardLit's classification, the window line, CardExtras split fields);
# the FEATURE edits are marked FEATURE (rt_cards.glsl cardTraceShadow strict zone, spec constant 11).
#
# Why (build 44): (1) the off/on pictures of the weeds differ by the torch's flame and flicker (full-frame off-vs-on equal to on-vs-on2):
# two pictures of two moments cannot show a cut-out shadow of a few percent. (2) 56.7 % of 5533 reads at a card in front of the surface
# (dream house), 12.5 % max4 / 6.3 % bilinear of 3.9 M (weeds) were kept by the lamp rule where the game's rule drops: a possible false
# shadow, but those reads are the CAMERA ray's cards and count the game-KEPT ones too. (3) 2274 lit-and-shadowed pixels at the dream house,
# the do-nothing place, with no way to tell a real leaf shadow from a false one.
#
# What this patch does (CARDS builds only):
#  1. TOOL: BB_RT_CARD_LAMP_SPLIT=<N> (16 to 1024, pixels at the render size; default 0 = off) with BB_RT_CARD_LAMP_SPLIT_PHASE=0|1: the
#     lamp rays of the pixels in the "off" tiles of an N-pixel checkerboard leave the cut-out cards out (the plain 0x04 ray of the builds
#     without cards: no card is traced, no card counter is added), the pixels of the other tiles trace them. ONE frame, ONE lamp state
#     (position, intensity, flicker, flame), so the two kinds of tile differ ONLY by the cut-outs' shadow: the picture itself is the
#     steady A/B. Phase 0: tile (tx, ty) is off when (tx + ty) is even, 1: when it is odd. The rest of the pass (history, windows, filters)
#     is as before: a still camera and a still lamp show clean tiles; walking smears the history across tile borders.
#     Analysis: r62l_splitdiff.ps1 (pwsh; a picture, N, phase, a rectangle: the mean luma of the on side minus the off side of every
#     tile border strip, and a ratio; apply it to the OFF picture of the same job as the null).
#  2. FEATURE: BB_RT_CARD_LAMP_STRICT=<m> (0 to 2, default 0 = off, as r62k): a kept read at a card hit within <m> metres of the ray's
#     start is taken again with the GAME's own rule (reference scale 1, no max-of-four, no nearest): the lamp rule's thicker texel
#     (the reference x0.5, the maximum of four) only holds from farther away, where a thin blade's disc penumbra needs it. A card cannot
#     grow a shadow on the surface it lies next to by the thickening. The count of reads this overruled is a counter.
#  3. TOOL: the lit patch's classification: of the pixels both lit and under a cut-out shadow: the share that lie ON a card surface (a
#     camera ray finds a card at the pixel's depth: a leaf shadowed by other leaves) and the rest (wall or ground: the picture wanted),
#     the share whose blocker lies within 10 cm of the surface (a card shadowing its own neighbourhood: suspect), the mean blocker
#     distance. Also the proof's front reads now count the rules' keeps only among the reads the game DROPPED (the earlier shares divided
#     by all front reads, including those the game kept itself) and the line says how many front reads the game kept.
#  Log: once-line 'Foliage lamp shadows (r62l): ...' when the CARDS builds are made; window lines 'Foliage lamp shadows (r62l) steady <w>'
#  (the same windows as r62k's lit line: at every change of the live knobs file and once after 240 frames); counters 64 -> 72.
#
# Files: rt_cards.glsl, point_shadow_ray.comp, rt_card_layers_layout.h, vk_point_shadow.cpp, vk_point_shadow.h, README.md.
# No new file, no CMake change. Revert r62l before r62k.
# Cost: off 0 (no CARDS pipeline). On: the strict zone is one compare per card read (0 extra reads with STRICT 0); with STRICT > 0 one
# more layer read per kept read within the zone (rare). The split is one integer test a pixel and, in off tiles, SAVES the card ray.
# The classification: one camera ray per lit-and-shadowed pixel of one pixel in 64 of one pass in 16 (a few hundred rays a pass: far
# under 0.01 ms). Memory: counters 256 -> 288 bytes, two buffers.
# Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62l_cutout-steady-proof.py check | apply | revert
# Root: R62L_CUTOUT_STEADY_PROOF_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62l_backup.
import os, sys

ROOT = os.environ.get("R62L_CUTOUT_STEADY_PROOF_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62l_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
G = HS + "rt_cards.glsl"
S = HS + "point_shadow_ray.comp"
L = HS + "rt_card_layers_layout.h"
C = RV + "vk_point_shadow.cpp"
H = RV + "vk_point_shadow.h"
R = "README.md"
FILES = (G, S, L, C, H, R)

EDITS = {
G: [
(r"""bool card_nearest = false;
""",
 r"""bool card_nearest = false;
// bbport (r62l_cutout-steady-proof) FEATURE: card_strict_t: a kept read at a hit nearer than this many metres along the ray is taken
// again with the game's own rule (reference scale 1, no dilation, no nearest texel), and dropped if that drops it (0: off);
// card_strict_drops: the reads that did (the lamp pass adds them to a counter and zeroes it).
float card_strict_t = 0.0;
uint card_strict_drops = 0u;
"""),
(r"""            const CardResult c =
                cardTestLod(uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false)),
                            uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false)),
                            rayQueryGetIntersectionBarycentricsEXT(query, false), lod);
""",
 r"""            const uint hit_slot = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(query, false));
            const uint hit_primitive = uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false));
            const vec2 hit_bary = rayQueryGetIntersectionBarycentricsEXT(query, false);
            const uint rescued_before = card_rescued;
            CardResult c = cardTestLod(hit_slot, hit_primitive, hit_bary, lod);
            // bbport (r62l_cutout-steady-proof) FEATURE: near the surface the game's own rule decides (card_strict_t 0: never taken)
            if (c.status == CARD_KEPT && t < card_strict_t) {
                const float scale_was = card_ref_scale;
                const bool dilate_was = card_dilate;
                const bool nearest_was = card_nearest;
                card_ref_scale = 1.0;
                card_dilate = false;
                card_nearest = false;
                const CardResult game = cardTestLod(hit_slot, hit_primitive, hit_bary, lod);
                card_ref_scale = scale_was;
                card_dilate = dilate_was;
                card_nearest = nearest_was;
                if (game.status != CARD_KEPT) {
                    c = game;
                    card_rescued = rescued_before;
                    ++card_strict_drops;
                }
            }
"""),
],
S: [
(r"""layout(constant_id = 10) const float CARD_LIT_DIST = 4.0;
""",
 r"""layout(constant_id = 10) const float CARD_LIT_DIST = 4.0;
// bbport (r62l_cutout-steady-proof): specialization constants 11 to 13 (vk_point_shadow.cpp): CARD_STRICT (FEATURE): metres of a lamp ray's
// start within which a kept card read is taken again with the game's own rule (BB_RT_CARD_LAMP_STRICT, 0 off); CARD_SPLIT (TOOL): the
// tile size in pixels of the checkerboard whose "off" tiles leave the cut-out cards out of the lamp rays (BB_RT_CARD_LAMP_SPLIT, 0 off),
// CARD_SPLIT_PHASE which parity is off (BB_RT_CARD_LAMP_SPLIT_PHASE). card_split_off: this invocation's pixel is in an off tile.
layout(constant_id = 11) const float CARD_STRICT = 0.0;
layout(constant_id = 12) const uint CARD_SPLIT = 0u;
layout(constant_id = 13) const uint CARD_SPLIT_PHASE = 0u;
bool card_split_off = false;
"""),
("    uint front_left = (mode & MODE_CARD_COUNT) != 0u ? 6u : 0u; // bbport (r62k_cutout-lit-fence): every pixel of a counted pass (r62j: 1 in 16)\n",
 "    uint front_left = (mode & MODE_CARD_COUNT) != 0u && !proof_quiet ? 6u : 0u; // bbport (r62k_cutout-lit-fence): every pixel of a counted pass (r62j: 1 in 16); r62l: not a quiet call\n"),
("    if (proofSampled()) { // bbport (r62j_cutout-rule-and-place): the lamp rule, the bins, the outside-0-1 pixels\n",
 "    if (proofSampled() && !proof_quiet) { // bbport (r62j_cutout-rule-and-place): the lamp rule, the bins, the outside-0-1 pixels\n"),
("uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {\n",
 r"""// bbport (r62l_cutout-steady-proof) TOOL: proof_quiet: cardProof adds to no counter (cardLit asks it only which kind of surface a pixel is)
bool proof_quiet = false;
uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {
"""),
("    countRules(slot, primitive, bary, CARD_LAMP_FRONT_BILIN); // bbport (r62k_cutout-lit-fence): the three rules' false shadows\n",
 "    if (game.status != CARD_KEPT) { // bbport (r62l_cutout-steady-proof) TOOL: only the reads the game dropped can be false shadows\n"
 "        countRules(slot, primitive, bary, CARD_LAMP_FRONT_BILIN); // bbport (r62k_cutout-lit-fence): the three rules' false shadows\n"
 "    }\n"),
("uint cardLit(vec3 P, vec3 lamp_light, vec3 base_light, uint top_at, bool top_card, float ratio, ivec2 px) {\n",
 "uint cardLit(vec3 P, vec3 lamp_light, vec3 base_light, uint top_at, bool top_card, float ratio, ivec2 px, float went) {\n"),
("    if (top_at == 0u || !(counted || CARD_PROOF == 3u)) {\n",
 "    if (top_at == 0u || card_split_off || !(counted || CARD_PROOF == 3u)) { // bbport (r62l_cutout-steady-proof) TOOL: a pixel of an off tile traced no card\n"),
("        cardCount(CARD_LAMP_LIT_SUM_DEPTH, uint((1.0 - clamp(ratio, 0.0, 1.0)) * 100.0 + 0.5));\n",
 r"""        cardCount(CARD_LAMP_LIT_SUM_DEPTH, uint((1.0 - clamp(ratio, 0.0, 1.0)) * 100.0 + 0.5));
        // bbport (r62l_cutout-steady-proof) TOOL: how far from the surface the blocking texel lies (a blocker within 10 cm is the surface's
        // own neighbourhood: suspect), and whether the pixel is itself a card (a leaf lit and shadowed by other leaves) or a wall or ground
        // (what the picture is wanted for): one camera ray, on the counted pixels only, adding to no proof counter
        if (counted) {
            cardCount(CARD_LAMP_LIT_SUM_WENT, uint(clamp(went, 0.0, 3.0) * 100.0));
            if (went < 0.10) {
                cardCount(CARD_LAMP_LIT_NEAR, 1u);
            }
            proof_quiet = true;
            CardResult surface;
            bool surface_l1, surface_outside;
            const uint surface_class = cardProof(P, surface, surface_l1, surface_outside);
            proof_quiet = false;
            if (surface_class != PROOF_NO_CARD) {
                cardCount(CARD_LAMP_LIT_ON_CARD, 1u);
            }
        }
"""),
("#ifdef CARDS\n    // bbport (r63_leaf-stage4): 0x04 and the cut-out cards with data (CARD_LAMP_MASK, built\n",
 r"""#ifdef CARDS
    // bbport (r62l_cutout-steady-proof) TOOL: a pixel of an "off" tile of the checkerboard (BB_RT_CARD_LAMP_SPLIT) casts the plain ray of
    // the builds without cards (mask 0x04, opaque: no card is traced, none counted): the same frame's lamp state as its on neighbours
    if (card_split_off) {
        rayQueryEXT plain;
        rayQueryInitializeEXT(plain, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x04u, origin, reach * 0.5,
                              ray_to / ray_len, tmax);
        rayQueryProceedEXT(plain);
        ray_card_kept = false;
        if (rayQueryGetIntersectionTypeEXT(plain, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
            return -1.0;
        }
        ray_went = rayQueryGetIntersectionTEXT(plain, true);
        ray_left = ray_len - ray_went;
        return ray_went / ray_len;
    }
    // bbport (r63_leaf-stage4): 0x04 and the cut-out cards with data (CARD_LAMP_MASK, built
"""),
("        cardCount(CARD_LAMP_LOD16, card_lod16);\n",
 "        cardCount(CARD_LAMP_LOD16, card_lod16);\n"
 "        cardCount(CARD_LAMP_STRICT_DROPS, card_strict_drops); // bbport (r62l_cutout-steady-proof) FEATURE\n"
 "        card_strict_drops = 0u;\n"),
("    cardNote(hit);\n    ray_card_kept = hit.how == CARD_RAY_KEPT;\n",
 "    cardNote(hit);\n"
 "    cardCount(CARD_LAMP_STRICT_DROPS, card_strict_drops); // bbport (r62l_cutout-steady-proof) FEATURE\n"
 "    card_strict_drops = 0u;\n"
 "    ray_card_kept = hit.how == CARD_RAY_KEPT;\n"),
("        lit_class = cardLit(P, d0 + d1, s0 + s1, top_at, top_card, ratio, px);\n",
 "        lit_class = cardLit(P, d0 + d1, s0 + s1, top_at, top_card, ratio, px, top_went);\n"),
("    card_nearest = CARD_GATHER == 2u; // bbport (r62k_cutout-lit-fence): the lamp rays' texel rule (rt_cards.glsl cardTexel)\n",
 "    card_nearest = CARD_GATHER == 2u; // bbport (r62k_cutout-lit-fence): the lamp rays' texel rule (rt_cards.glsl cardTexel)\n"
 "    card_strict_t = CARD_STRICT; // bbport (r62l_cutout-steady-proof) FEATURE\n"
 "    // bbport (r62l_cutout-steady-proof) TOOL: the checkerboard's off tiles (px is the pixel at the render size, also in the half build's first pass)\n"
 "    card_split_off = CARD_SPLIT != 0u && (((px.x / max(int(CARD_SPLIT), 1)) + (px.y / max(int(CARD_SPLIT), 1))) & 1) == int(CARD_SPLIT_PHASE);\n"),
],
L: [
("#define CARD_LAMP_COUNTERS 64 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48)\n",
 r"""// bbport (r62l_cutout-steady-proof): the lit patch's blocker within 10 cm of the surface, the sum of the blockers' distances (cm, at most
// 300 each), the kept reads the strict zone overruled, and the lit-and-shadowed pixels that lie on a card surface; then spare ones
#define CARD_LAMP_LIT_NEAR 61
#define CARD_LAMP_LIT_SUM_WENT 62
#define CARD_LAMP_STRICT_DROPS 63
#define CARD_LAMP_LIT_ON_CARD 64
#define CARD_LAMP_COUNTERS 72 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48 then 64; r62l: was 64)
"""),
],
C: [
("static_assert(CARD_LAMP_COUNTERS == 64); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32, then 48; r62k: was 48 (header.h card_last)\n",
 "static_assert(CARD_LAMP_COUNTERS == 72); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32, then 48; r62k: was 48, then 64; r62l: was 64 (header.h card_last)\n"),
("              CARD_LAMP_LIT_SUM_DEPTH < CARD_LAMP_COUNTERS);\n",
 r"""              CARD_LAMP_LIT_SUM_DEPTH < CARD_LAMP_COUNTERS);
// bbport (r62l_cutout-steady-proof): its four counters follow, then spare ones
static_assert(CARD_LAMP_LIT_NEAR == CARD_LAMP_LIT_SUM_DEPTH + 1 && CARD_LAMP_LIT_ON_CARD == CARD_LAMP_LIT_NEAR + 3 &&
              CARD_LAMP_LIT_ON_CARD < CARD_LAMP_COUNTERS);
"""),
("    float lit_dist_m;  // BB_RT_CARD_LIT_DIST, 0.5 to 15 m, default 4\n};\n",
 r"""    float lit_dist_m;  // BB_RT_CARD_LIT_DIST, 0.5 to 15 m, default 4
    float strict_m;    // bbport (r62l_cutout-steady-proof) FEATURE: BB_RT_CARD_LAMP_STRICT, 0 to 2 m, default 0 (off)
    u32 split;         // TOOL: BB_RT_CARD_LAMP_SPLIT, tile size in pixels (16 to 1024), 0 = off
    u32 split_phase;   // TOOL: BB_RT_CARD_LAMP_SPLIT_PHASE, 0 or 1
};
"""),
("CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f}; // (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap; r62k: lit share, lit distance)\n",
 "CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f, 0.0f, 0u, 0u}; // (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap; r62k: lit share, lit distance; r62l: strict zone, split, split phase)\n"),
("        e.lit_dist_m = number(\"BB_RT_CARD_LIT_DIST\", e.lit_dist_m, 0.5f, 15.0f);\n",
 r"""        e.lit_dist_m = number("BB_RT_CARD_LIT_DIST", e.lit_dist_m, 0.5f, 15.0f);
        // bbport (r62l_cutout-steady-proof): the strict zone in metres (FEATURE), the checkerboard's tile size in pixels (TOOL: a whole
        // number from 16; not a number or smaller: off) and its phase (exactly 0 or 1)
        e.strict_m = number("BB_RT_CARD_LAMP_STRICT", e.strict_m, 0.0f, 2.0f);
        if (const char* const split_text = std::getenv("BB_RT_CARD_LAMP_SPLIT")) {
            char* end = nullptr;
            const long value = std::strtol(split_text, &end, 10);
            e.split = end != split_text && *end == '\0' && value >= 16 ? u32(std::min(value, 1024l)) : 0u;
        }
        e.split_phase = flag("BB_RT_CARD_LAMP_SPLIT_PHASE", e.split_phase);
"""),
("    const std::array<u32, 11> spec_words{",
 "    const std::array<u32, 14> spec_words{"),
("std::bit_cast<u32>(extras.lit_dist_m)}; // (r62i:",
 "std::bit_cast<u32>(extras.lit_dist_m), std::bit_cast<u32>(extras.strict_m),\n"
 "                                        extras.split, extras.split_phase}; // (r62l_cutout-steady-proof: 11 CARD_STRICT, 12 CARD_SPLIT, 13 CARD_SPLIT_PHASE) (r62i:"),
("    const std::array<vk::SpecializationMapEntry, 11> spec_entries{",
 "    const std::array<vk::SpecializationMapEntry, 14> spec_entries{"),
("{9, 36, 4}, {10, 40, 4}}};\n",
 "{9, 36, 4}, {10, 40, 4}, {11, 44, 4}, {12, 48, 4}, {13, 52, 4}}};\n"),
(r"""                        extras.proof_view == 3 ? " (on)" : "");
        }
""",
 r"""                        extras.proof_view == 3 ? " (on)" : "");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62l_cutout-steady-proof)
            std::printf("Foliage lamp shadows (r62l): steady proof: BB_RT_CARD_LAMP_STRICT=%.2f m (%s: a kept read within that of the "
                        "ray's start is taken again with the game's own rule); BB_RT_CARD_LAMP_SPLIT=%u px phase %u (%s: the pixels "
                        "of the off tiles of a checkerboard trace no cut-out card, in the same frame as their neighbours: one picture "
                        "is the steady A/B); a window line 'Foliage lamp shadows (r62l) steady <w>' follows r62k's lit line: pixels "
                        "lit and under a cut-out shadow, how many lie on a card surface, how many have the blocker within 10 cm\n",
                        double(extras.strict_m), extras.strict_m > 0.0f ? "on" : "off", extras.split, extras.split_phase,
                        extras.split != 0 ? "on" : "off");
        }
"""),
("        const double front = d[CARD_LAMP_PROOF_FRONT_READS];\n        std::printf(\"Foliage lamp shadows (r62k) proof %s:",
 "        const double front = d[CARD_LAMP_PROOF_FRONT_READS];\n"
 "        const double dropped = std::max(front - d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], 0.0); // bbport (r62l_cutout-steady-proof): the reads the game dropped\n"
 "        std::printf(\"Foliage lamp shadows (r62k) proof %s:"),
("share(d[CARD_LAMP_JUDGED_NEAR], judged), front,\n"
 "                    share(d[CARD_LAMP_FRONT_BILIN], front), share(d[CARD_LAMP_FRONT_MAX], front),\n"
 "                    share(d[CARD_LAMP_FRONT_NEAR], front));\n",
 "share(d[CARD_LAMP_JUDGED_NEAR], judged), dropped,\n"
 "                    share(d[CARD_LAMP_FRONT_BILIN], dropped), share(d[CARD_LAMP_FRONT_MAX], dropped),\n"
 "                    share(d[CARD_LAMP_FRONT_NEAR], dropped));\n"),
("    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {\n        const double judged = d[CARD_LAMP_PROOF_KEPT]",
 r"""    // bbport (r62l_cutout-steady-proof): what kind of surface the lit and shadowed pixels are, how far their blockers lie, how many
    // reads the strict zone overruled, and how many front reads the game kept itself (not false shadows: the card is drawn there)
    std::printf("Foliage lamp shadows (r62l) steady %s: %.0f px lit+shadowed, on a card %.0f %%, blocker within 10 cm %.0f %%, mean "
                "blocker %.2f m; strict drops %.0f (zone %.2f m); front reads %.0f, game-kept %.1f %%; split %u px\n",
                tag, both, share(d[CARD_LAMP_LIT_ON_CARD], both), share(d[CARD_LAMP_LIT_NEAR], both),
                both > 0.0 ? d[CARD_LAMP_LIT_SUM_WENT] / both / 100.0 : 0.0, d[CARD_LAMP_STRICT_DROPS],
                double(CardExtrasFromEnv().strict_m), d[CARD_LAMP_PROOF_FRONT_READS],
                share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], d[CARD_LAMP_PROOF_FRONT_READS]), CardExtrasFromEnv().split);
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {
        const double judged = d[CARD_LAMP_PROOF_KEPT]"""),
],
H: [
("    std::array<u32, 64> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32, then 48; r62k: was 48)\n",
 "    std::array<u32, 72> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32, then 48; r62k: was 48, then 64; r62l: was 64)\n"),
],
}

ROWS = (
    "| `BB_RT_CARD_LAMP_STRICT` | FEATURE, only with `BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1`, read at start, a number of metres (0 to 2). "
    "A cut-out card a lamp ray's thicker rule (the reference x0.5, the maximum of four texels) keeps within this distance of the ray's "
    "start is read again with the game's own rule and dropped if that drops it, so a leaf cannot grow a shadow on the surface it lies "
    "next to. The `Foliage lamp shadows (r62l) steady` window line counts the reads this overruled (`strict drops`) | `0` (off) |",
    "| `BB_RT_CARD_LAMP_SPLIT`, `BB_RT_CARD_LAMP_SPLIT_PHASE` | TOOL (test aid), same conditions. A tile size in pixels at the render size "
    "(a whole number from 16, at most 1024): the pixels in the \"off\" tiles of a checkerboard leave the cut-out cards out of their lamp "
    "rays, the others trace them, all in one frame with one lamp state (flame, flicker, position), so a single picture is the steady "
    "A/B of the cut-out shadows. The phase (0 or 1): at phase 0 tile (x, y) is off when x + y is even, at phase 1 when it is odd. "
    "A still camera shows clean tiles. The `steady` line also says how many lit and shadowed pixels lie "
    "on a card and how many have the blocker within 10 cm | `0` (off), `0` |",
)
ANCHOR_ROW = "| `BB_RT_CARD_LIT_SHARE`, `BB_RT_CARD_LIT_DIST` |"


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LIT_SHARE row is there %d times, wanted 1 (r62k applied?)" % len(lines))
    return [(lines[0] + "\n", lines[0] + "\n" + "\n".join(ROWS) + "\n")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def state_of(cur, eds, path):
    """'applied' or 'clean' for every edit, else refuse. A swap (new does not hold old) is applied when old is gone and
    new is there once; an insert (new holds old) when new is there once."""
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
    """Every line holding one of `markers` lies inside an #ifdef of `flags` (a set of names)."""
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
            raise SystemExit("text check: %s: a line of r62l is outside its #ifdef: %r" % (what, line))


def text_checks(texts):
    g, s, l, c, h, r = (texts[p] for p in FILES)
    for want, n in (("layout(constant_id = 11) const float CARD_STRICT = 0.0;", 1),
                    ("layout(constant_id = 12) const uint CARD_SPLIT = 0u;", 1),
                    ("layout(constant_id = 13) const uint CARD_SPLIT_PHASE = 0u;", 1),
                    ("bool card_split_off = false;", 1),
                    ("bool proof_quiet = false;", 1),
                    ("card_split_off = CARD_SPLIT != 0u", 1),
                    ("card_strict_t = CARD_STRICT;", 1),
                    ("if (card_split_off) {", 1),
                    ("cardCount(CARD_LAMP_STRICT_DROPS, card_strict_drops);", 2),
                    ("cardLit(P, d0 + d1, s0 + s1, top_at, top_card, ratio, px, top_went);", 1),
                    ("uint cardLit(vec3 P, vec3 lamp_light, vec3 base_light, uint top_at, bool top_card, float ratio, ivec2 px, float went) {", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    inside_only(s, ("r62l", "CARD_SPLIT", "CARD_STRICT", "card_split_off", "card_strict_", "proof_quiet", "CARD_LAMP_LIT_NEAR",
                    "CARD_LAMP_LIT_ON_CARD", "CARD_LAMP_LIT_SUM_WENT", "CARD_LAMP_STRICT_DROPS"), {"CARDS"}, S)
    if g.count("float card_strict_t = 0.0;") != 1 or g.count("uint card_strict_drops = 0u;") != 1 \
       or g.count("if (c.status == CARD_KEPT && t < card_strict_t) {") != 1:
        raise SystemExit("text check: rt_cards.glsl strict zone")
    # the strict zone sits inside the CARD_TRACE_SHADOW block (the CPU twin and the view shaders do not have it)
    inside_only(g, ("card_strict_t", "card_strict_drops", "hit_slot", "rescued_before"), {"CARD_TRACE_SHADOW"}, G)
    for name in ("LIT_NEAR 61", "LIT_SUM_WENT 62", "STRICT_DROPS 63", "LIT_ON_CARD 64"):
        if l.count("#define CARD_LAMP_" + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define CARD_LAMP_%s" % (L, name))
    if l.count("#define CARD_LAMP_COUNTERS 72 ") != 1:
        raise SystemExit("text check: CARD_LAMP_COUNTERS is not 72")
    if c.count("std::array<u32, 14> spec_words{") != 1 or c.count("std::array<vk::SpecializationMapEntry, 14> spec_entries{") != 1 \
       or "{13, 52, 4}" not in c:
        raise SystemExit("text check: spec words / entries")
    if c.count("CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f, 0.0f, 0u, 0u};") != 1:
        raise SystemExit("text check: CardExtras initializer")
    for key in ('"BB_RT_CARD_LAMP_STRICT"', '"BB_RT_CARD_LAMP_SPLIT"', '"BB_RT_CARD_LAMP_SPLIT_PHASE"',
                "Foliage lamp shadows (r62l): steady proof:", "Foliage lamp shadows (r62l) steady %s:"):
        if c.count(key) != 1:
            raise SystemExit("text check: %r" % key)
    if h.count("std::array<u32, 72> card_last{}") != 1:
        raise SystemExit("text check: card_last")
    if len([x for x in r.split("\n") if x.startswith("| `BB_RT_CARD_LAMP_STRICT`")]) != 1 or \
       len([x for x in r.split("\n") if x.startswith("| `BB_RT_CARD_LAMP_SPLIT`")]) != 1:
        raise SystemExit("text check: README rows")
    # the steady line stays under the runner's 300 characters with plausible numbers
    line = ("Foliage lamp shadows (r62l) steady early: 99999 px lit+shadowed, on a card 100 %, blocker within 10 cm 100 %, mean "
            "blocker 3.00 m; strict drops 99999999 (zone 2.00 m); front reads 99999999, game-kept 100.0 %; split 1024 px")
    if len(line) > 300:
        raise SystemExit("text check: the steady line is %d characters" % len(line))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62L_CUTOUT_STEADY_PROOF_ROOT)" % ROOT)
    for path in FILES:  # apply writes nothing when a folder is missing
        if not os.path.isfile(os.path.join(ROOT, path)):
            raise SystemExit("%s is missing" % path)
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
            tmp = full + ".r62ltmp"
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
        tmp = full + ".r62ltmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
