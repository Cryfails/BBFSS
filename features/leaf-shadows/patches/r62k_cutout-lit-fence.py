# r62k_cutout-lit-fence: FEATURE (a lit-patch finder and window lines for the cut-out lamp shadows, a lit view, and the false-shadow
# measure with a nearest-texel rule) on top of r62j (build 42). Only in the CARDS builds of the lamp pass (BB_RT_CARD_ALPHA=2 and
# BB_RT_CARD_LAMPS=1); with the knobs off nothing of it exists (no CARDS pipeline, CardLampsLine returns at once: card_set_layout).
#
# Why (build 42): (1) the proof lines printed 0 pixels: they came every 600 frames, the v7 capture came after the last one and the
# job ended 8 s later; the runner keeps a line's first 300 characters and a limited number of kinds, and r62j's line is longer.
# (2) The alley's v7 ray colour view shows red where leaf texels stop lamp rays (a band 450 px wide on the pavement by the lamp) but
# the lit picture is dark there: no picture shows a cut-out's shadow on a BRIGHTLY LIT surface. (3) Dream house, do-nothing: of 59 reads
# at a card in front of the surface (the game dropped them) the lamp rule keeps 52.5 %: a possible false shadow.
#
# What this patch does (CARDS builds only):
#  1. WINDOW LINES at every change of the live knobs file (a test job's set:/unset: actions, so one line per capture) and once at 240
#     frames, so a line exists before the first picture and the job's end cannot lose it: 'Foliage lamp shadows (r62k) lit <w>: ...'
#     (the numbers first, under 300 characters, the "Foliage" prefix the runner's evidence list keeps ahead of the rest) and, with the
#     proof view on, 'Foliage lamp shadows (r62k) proof <w>: ...'. <w> is early, then a, b, c ... (letters: the runner folds digits, so
#     lines that differ only in a number would be one kind, of which it keeps the first and last).
#  2. THE LIT PATCH FINDER. For every pixel whose lamp rays were cast (on the passes and pixels the r63 counters use: one in 16 passes,
#     one pixel in 64) the strongest lamp's record is looked at: the pixel is LIT when that lamp is within BB_RT_CARD_LIT_DIST metres of
#     the surface (default 4) and its light is at least BB_RT_CARD_LIT_SHARE (default 0.5) of the pixel's light (lamp light over lamp
#     light plus the light without lamps, the larger colour channel); CARD-SHADOWED when a kept leaf texel stopped the ray to that lamp.
#     Counters: pixels seen, card-shadowed, lit, lit and card-shadowed; for the last the sums that give the patch's centre (view space:
#     x right, y up, z ahead, metres), its bearing, the pixel centre, the lamp's distance and share, and how much the pixel's shadow
#     ratio is under 1. A job that looks around reads the bearing off the lines and aims the next one.
#  3. THE LIT VIEW: BB_RT_CARD_LAMP_PROOF_VIEW=3 with BB_LAMP_SHADOW_VIEW=7 paints, per pixel the pass shadows: red lit and card-shadowed,
#     orange card-shadowed but not lit, green lit and free, else a dim copy of the shadow ratio. (3 makes no camera-ray proof.)
#  4. THE FALSE-SHADOW MEASURE AND FIX. The proof view's counters now count, for the judged card pixels and for the reads at cards in
#     front of the surface, what each of THREE layer rules keeps at the reference scale: 0 the bilinear value (r62h), 1 the maximum of
#     the footprint's four texels (r62j, the default), 2 the NEAREST texel (new: BB_RT_CARD_LAMP_GATHER=2; no dilation: a ray keeps the
#     texel it lies in). The front reads are taken on every pixel of a counted pass (r62j: one in 16: 59 reads in a run). The maximum
#     of four grows a leaf's shadow by up to a layer texel (about 2-8 mm on a card of 0.5-2 m); the nearest texel does not. One run says
#     the three kept shares of the pixels the game kept and the three false-shadow shares: pick the rule from them (the default stays 1
#     until a run says; changing it is the number 1u in CardExtras and in the shader's CARD_GATHER default).
#
# Files: rt_cards.glsl, point_shadow_ray.comp, rt_card_layers_layout.h, vk_point_shadow.cpp, vk_point_shadow.h, README.md.
# No new file, no CMake change. Counters 48 -> 64 (CARDS builds: 192 -> 256 bytes, two buffers). Revert r62k before r62j.
# Cost: lit counting is a few ALU ops and one more read of the lamp record on a counted pass's pixels in one in 64 (the call returns at
# once elsewhere unless the lit view is on); the lit view and the proof's extra reads only while view 7 and the proof knob are on.
# Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62k_cutout-lit-fence.py check | apply | revert
# Root: R62K_CUTOUT_LIT_FENCE_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62k_backup.
import os, sys

ROOT = os.environ.get("R62K_CUTOUT_LIT_FENCE_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62k_backup")
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
(r"""bool card_wrap_clamped = false;
float cardTexel(vec2 uv, uint layer, float lod, uint op) {
""",
 r"""bool card_wrap_clamped = false;
// bbport (r62k_cutout-lit-fence): card_nearest (with card_dilate): the read takes the one texel of the footprint nearest the
// coordinates in place of the maximum of the four (no dilation: BB_RT_CARD_LAMP_GATHER=2)
bool card_nearest = false;
float cardTexel(vec2 uv, uint layer, float lod, uint op) {
"""),
(r"""        const vec4 g = textureGather(card_alpha, vec3(uv, float(layer)), 0);
        return max(max(g.x, g.y), max(g.z, g.w));
""",
 r"""        const vec4 g = textureGather(card_alpha, vec3(uv, float(layer)), 0);
        if (card_nearest) { // bbport (r62k_cutout-lit-fence): the gather's texels are (i0,j1) (i1,j1) (i1,j0) (i0,j0)
            const vec2 f = fract(uv * vec2(textureSize(card_alpha, 0).xy) - 0.5);
            return f.y >= 0.5 ? (f.x >= 0.5 ? g.y : g.x) : (f.x >= 0.5 ? g.z : g.w);
        }
        return max(max(g.x, g.y), max(g.z, g.w));
"""),
],
S: [
(r"""layout(constant_id = 8) const uint CARD_WRAP_CLAMPED = 0u;
""",
 r"""layout(constant_id = 8) const uint CARD_WRAP_CLAMPED = 0u;
// bbport (r62k_cutout-lit-fence): specialization constants 9 and 10 (vk_point_shadow.cpp): a pixel is LIT (cardLit) when its strongest
// lamp is within CARD_LIT_DIST metres and gives at least CARD_LIT_SHARE of its light (BB_RT_CARD_LIT_SHARE, BB_RT_CARD_LIT_DIST).
// CARD_GATHER 2: the lamp rays read the nearest texel (card_nearest), no dilation. CARD_PROOF 3: the lit view.
layout(constant_id = 9) const float CARD_LIT_SHARE = 0.5;
layout(constant_id = 10) const float CARD_LIT_DIST = 4.0;
"""),
(r"""void proofFront(uint slot, uint primitive, vec2 bary) {
""",
 r"""// bbport (r62k_cutout-lit-fence): whether a layer read keeps the texel by one fixed rule, all at the reference scale CARD_REF_SCALE and the
// configured wrap: 0 the bilinear value (r62h), 1 the maximum of the footprint's four texels (r62j), 2 the nearest texel. The globals
// are left as the lamp rays' code expects them (card_nearest as CARD_GATHER says; main sets it first). countRules adds one counter
// of three (first_counter + rule) for each rule that keeps.
bool cardKeptByRule(uint slot, uint primitive, vec2 bary, uint rule) {
    card_ref_scale = CARD_REF_SCALE;
    card_dilate = rule != 0u;
    card_nearest = rule == 2u;
    card_wrap_clamped = CARD_WRAP_CLAMPED != 0u;
    const bool kept = cardTestLod(slot, primitive, bary, 0.0).status == CARD_KEPT;
    card_ref_scale = 1.0;
    card_dilate = false;
    card_nearest = CARD_GATHER == 2u;
    card_wrap_clamped = false;
    return kept;
}
void countRules(uint slot, uint primitive, vec2 bary, uint first_counter) {
    for (uint rule = 0u; rule < 3u; ++rule) {
        if (cardKeptByRule(slot, primitive, bary, rule)) {
            atomicAdd(card_counts[first_counter + rule], 1u);
        }
    }
}
void proofFront(uint slot, uint primitive, vec2 bary) {
"""),
(r"""    if (lamp.status == CARD_KEPT) {
        atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], 1u);
    }
}
""",
 r"""    if (lamp.status == CARD_KEPT) {
        atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], 1u);
    }
    countRules(slot, primitive, bary, CARD_LAMP_FRONT_BILIN); // bbport (r62k_cutout-lit-fence): the three rules' false shadows
}
"""),
(r"""        if (cardReadLampRule(best_slot, best_primitive, best_bary).status == CARD_KEPT) {
            atomicAdd(card_counts[CARD_LAMP_PROOF_LAMP_KEPT], 1u);
        }
""",
 r"""        if (cardReadLampRule(best_slot, best_primitive, best_bary).status == CARD_KEPT) {
            atomicAdd(card_counts[CARD_LAMP_PROOF_LAMP_KEPT], 1u);
        }
        countRules(best_slot, best_primitive, best_bary, CARD_LAMP_JUDGED_BILIN); // bbport (r62k_cutout-lit-fence)
"""),
("    uint front_left = proofSampled() ? 6u : 0u; // bbport (r62j_cutout-rule-and-place)\n",
 "    uint front_left = (mode & MODE_CARD_COUNT) != 0u ? 6u : 0u; // bbport (r62k_cutout-lit-fence): every pixel of a counted pass (r62j: 1 in 16)\n"),
(r"""// One proof counter's add: on the counted passes (MODE_CARD_COUNT), from one pixel in 16.
void proofCount(uint index) {
""",
 r"""// bbport (r62k_cutout-lit-fence): where a cut-out's lamp shadow falls on a brightly lit surface. For a pixel whose lamp rays were cast this
// frame: LIT = its strongest lamp (the record top_at) is within CARD_LIT_DIST metres of the surface and the lamp's light (lamp_light, the
// pixel's lamp light before the shadow) is at least CARD_LIT_SHARE of the pixel's light (lamp over lamp plus base_light, the larger
// channel); BLOCKED = a kept leaf texel stopped the ray to that lamp (top_card). Returns 0 neither, 1 lit, 2 blocked, 3 both. The counts
// (on the passes and pixels cardCount counts): the pixels, blocked, lit, both; for both, the sums the host divides by their number: the
// view-space position in cm (x and y plus 3200: 32 m either side), the pixel, the lamp's distance in cm, its share in %, and how much of
// the lamp light the pixel's shadow ratio takes, in %. Without the lit view (CARD_PROOF 3) a pixel cardCount does not count is skipped.
uint cardLit(vec3 P, vec3 lamp_light, vec3 base_light, uint top_at, bool top_card, float ratio, ivec2 px) {
    const bool counted = (mode & MODE_CARD_COUNT) != 0u && ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 7u) == 0u;
    if (top_at == 0u || !(counted || CARD_PROOF == 3u)) {
        return 0u;
    }
    const vec3 lamp_at = vec3(word(top_at), word(top_at + 1u), word(top_at + 2u));
    const float dist = length(lamp_at - P);
    const float lamp = max(max(lamp_light.r, lamp_light.g), lamp_light.b);
    const float base = max(max(base_light.r, base_light.g), base_light.b);
    const float share = lamp / max(lamp + base, 1e-12);
    const bool lit = dist <= CARD_LIT_DIST && share >= CARD_LIT_SHARE;
    cardCount(CARD_LAMP_LIT_PIXELS, 1u);
    if (top_card) {
        cardCount(CARD_LAMP_LIT_BLOCKED, 1u);
    }
    if (lit) {
        cardCount(CARD_LAMP_LIT_BRIGHT, 1u);
    }
    if (lit && top_card) {
        cardCount(CARD_LAMP_LIT_BOTH, 1u);
        cardCount(CARD_LAMP_LIT_SUM_X, uint(clamp(P.x * 100.0 + 3200.0, 0.0, 6400.0)));
        cardCount(CARD_LAMP_LIT_SUM_Y, uint(clamp(P.y * 100.0 + 3200.0, 0.0, 6400.0)));
        cardCount(CARD_LAMP_LIT_SUM_Z, uint(clamp(P.z * 100.0, 0.0, 20000.0)));
        cardCount(CARD_LAMP_LIT_SUM_PX, uint(max(px.x, 0)));
        cardCount(CARD_LAMP_LIT_SUM_PY, uint(max(px.y, 0)));
        cardCount(CARD_LAMP_LIT_SUM_DIST, uint(min(dist, 15.0) * 100.0));
        cardCount(CARD_LAMP_LIT_SUM_SHARE, uint(share * 100.0));
        cardCount(CARD_LAMP_LIT_SUM_DEPTH, uint((1.0 - clamp(ratio, 0.0, 1.0)) * 100.0 + 0.5));
    }
    return (lit ? 1u : 0u) | (top_card ? 2u : 0u);
}

// One proof counter's add: on the counted passes (MODE_CARD_COUNT), from one pixel in 16.
void proofCount(uint index) {
"""),
("    bool top_card = false;\n",
 "    bool top_card = false;\n    uint lit_class = 0u; // bbport (r62k_cutout-lit-fence): cardLit's class of this pixel (the lit view, CARD_PROOF 3)\n"),
("        ratio = clamp(vsum / wsum, 0.0, 1.0);\n",
 r"""        ratio = clamp(vsum / wsum, 0.0, 1.0);
#ifdef CARDS
        // bbport (r62k_cutout-lit-fence): a pixel that took its block's answer cast no ray and is not counted
#ifdef HALF
        if (half_why != HALF_TAKEN)
#endif
        lit_class = cardLit(P, d0 + d1, s0 + s1, top_at, top_card, ratio, px);
#endif
"""),
("    const bool apart = (mode & MODE_APART) != 0u;\n",
 "#ifdef CARDS\n    card_nearest = CARD_GATHER == 2u; // bbport (r62k_cutout-lit-fence): the lamp rays' texel rule (rt_cards.glsl cardTexel)\n#endif\n"
 "    const bool apart = (mode & MODE_APART) != 0u;\n"),
(r"""        if (CARD_PROOF != 0u && t_view == 7u && live) {
            CardResult proof;
""",
 r"""        // bbport (r62k_cutout-lit-fence): BB_RT_CARD_LAMP_PROOF_VIEW=3: 7 paints the lit view on every pixel the pass shadows (no camera-ray
        // proof): red a pixel lit by its strongest lamp (within CARD_LIT_DIST, at least CARD_LIT_SHARE of its light) whose ray a leaf texel
        // stopped, orange one a leaf texel stopped that is not lit, green one that is lit and free, else a dim copy of the shadow ratio. (A
        // pixel that took the history in place of rays shows the dim copy.)
        if (CARD_PROOF == 3u && t_view == 7u && live) {
            shown = lit_class == 3u ? vec3(1.0, 0.0, 0.0)
                    : lit_class == 2u ? vec3(1.0, 0.5, 0.0)
                    : lit_class == 1u ? vec3(0.0, 0.7, 0.0)
                                      : vec3(0.1 * answer);
        } else
        if (CARD_PROOF != 0u && t_view == 7u && live) {
            CardResult proof;
"""),
],
L: [
("#define CARD_LAMP_COUNTERS 48 // (r62h: was 16; r62j: was 32)\n",
 r"""// bbport (r62k_cutout-lit-fence): the three layer rules' kept counts (rule 0 bilinear, 1 maximum of four, 2 nearest; three each, in
// that order): at cards in front of the surface (the game dropped them: false shadows), then on the judged card pixels (of which the
// game kept most); then the lit patch finder (cardLit): pixels seen, card-shadowed, lit, both, and the sums for both (x, y, z, pixel
// x, pixel y, lamp distance, lamp share, shadow depth), then spare ones
#define CARD_LAMP_FRONT_BILIN 43
#define CARD_LAMP_FRONT_MAX 44
#define CARD_LAMP_FRONT_NEAR 45
#define CARD_LAMP_JUDGED_BILIN 46
#define CARD_LAMP_JUDGED_MAX 47
#define CARD_LAMP_JUDGED_NEAR 48
#define CARD_LAMP_LIT_PIXELS 49
#define CARD_LAMP_LIT_BLOCKED 50
#define CARD_LAMP_LIT_BRIGHT 51
#define CARD_LAMP_LIT_BOTH 52
#define CARD_LAMP_LIT_SUM_X 53
#define CARD_LAMP_LIT_SUM_Y 54
#define CARD_LAMP_LIT_SUM_Z 55
#define CARD_LAMP_LIT_SUM_PX 56
#define CARD_LAMP_LIT_SUM_PY 57
#define CARD_LAMP_LIT_SUM_DIST 58
#define CARD_LAMP_LIT_SUM_SHARE 59
#define CARD_LAMP_LIT_SUM_DEPTH 60
#define CARD_LAMP_COUNTERS 64 // (r62h: was 16; r62j: was 32 then 48; r62k: was 48)
"""),
],
C: [
# review fix: r62j's start line would call GATHER=2 "the maximum of four"
("                        extras.gather != 0 ? \"maximum of the bilinear footprint's four texels\" : \"bilinear value\",\n",
 "                        extras.gather == 2 ? \"nearest texel of the footprint (r62k)\"\n"
 "                        : extras.gather != 0 ? \"maximum of the bilinear footprint's four texels\" : \"bilinear value\",\n"),
("static_assert(CARD_LAMP_COUNTERS == 48); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32 (header.h card_last)\n",
 "static_assert(CARD_LAMP_COUNTERS == 64); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32, then 48; r62k: was 48 (header.h card_last)\n"),
(r"""              CARD_LAMP_PROOF_FRONT_LAMP_KEPT < CARD_LAMP_COUNTERS);
""",
 r"""              CARD_LAMP_PROOF_FRONT_LAMP_KEPT < CARD_LAMP_COUNTERS);
// bbport (r62k_cutout-lit-fence): its eighteen counters follow, then spare ones
static_assert(CARD_LAMP_FRONT_BILIN == CARD_LAMP_PROOF_FRONT_LAMP_KEPT + 1 && CARD_LAMP_FRONT_NEAR == CARD_LAMP_FRONT_BILIN + 2 &&
              CARD_LAMP_JUDGED_BILIN == CARD_LAMP_FRONT_NEAR + 1 && CARD_LAMP_JUDGED_NEAR == CARD_LAMP_JUDGED_BILIN + 2 &&
              CARD_LAMP_LIT_PIXELS == CARD_LAMP_JUDGED_NEAR + 1 && CARD_LAMP_LIT_SUM_DEPTH == CARD_LAMP_LIT_PIXELS + 11 &&
              CARD_LAMP_LIT_SUM_DEPTH < CARD_LAMP_COUNTERS);
"""),
(r"""    u32 wrap_clamped;  // BB_RT_CARD_LAMP_WRAP, 0 or 1, default 0
};
""",
 r"""    u32 wrap_clamped;  // BB_RT_CARD_LAMP_WRAP, 0 or 1, default 0
    float lit_share;   // bbport (r62k_cutout-lit-fence): BB_RT_CARD_LIT_SHARE, 0.05 to 1, default 0.5
    float lit_dist_m;  // BB_RT_CARD_LIT_DIST, 0.5 to 15 m, default 4
};
"""),
("        CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u}; // (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap)\n",
 "        CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f}; // (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap; r62k: lit share, lit distance)\n"),
(r"""            e.proof_view = proof[0] == '1' && proof[1] == '\0' ? 1u : proof[0] == '2' && proof[1] == '\0' ? 2u : 0u;
""",
 r"""            e.proof_view = proof[0] >= '1' && proof[0] <= '3' && proof[1] == '\0' ? u32(proof[0] - '0') : 0u; // (r62k_cutout-lit-fence: 3, the lit view)
"""),
(r"""        e.wrap_clamped = flag("BB_RT_CARD_LAMP_WRAP", e.wrap_clamped);
""",
 r"""        e.wrap_clamped = flag("BB_RT_CARD_LAMP_WRAP", e.wrap_clamped);
        // bbport (r62k_cutout-lit-fence): BB_RT_CARD_LAMP_GATHER=2: the nearest texel of the footprint (no dilation); the lit patch's
        // two numbers (clamped; not a number: the default)
        if (const char* const gather_text = std::getenv("BB_RT_CARD_LAMP_GATHER");
            gather_text && gather_text[0] == '2' && gather_text[1] == '\0') {
            e.gather = 2u;
        }
        e.lit_share = number("BB_RT_CARD_LIT_SHARE", e.lit_share, 0.05f, 1.0f);
        e.lit_dist_m = number("BB_RT_CARD_LIT_DIST", e.lit_dist_m, 0.5f, 15.0f);
"""),
("    const std::array<u32, 9> spec_words{",
 "    const std::array<u32, 11> spec_words{"),
("                                        extras.wrap_clamped}; // (r62i: constant 6 CARD_PROOF; r62j_cutout-rule-and-place: 7 CARD_GATHER, 8 CARD_WRAP_CLAMPED)\n",
 "                                        extras.wrap_clamped, std::bit_cast<u32>(extras.lit_share),\n"
 "                                        std::bit_cast<u32>(extras.lit_dist_m)}; // (r62i: constant 6 CARD_PROOF; r62j_cutout-rule-and-place: 7 CARD_GATHER, 8 CARD_WRAP_CLAMPED; r62k_cutout-lit-fence: 9 CARD_LIT_SHARE, 10 CARD_LIT_DIST)\n"),
("    const std::array<vk::SpecializationMapEntry, 9> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}, {7, 28, 4}, {8, 32, 4}}};\n",
 "    const std::array<vk::SpecializationMapEntry, 11> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}, {7, 28, 4}, {8, 32, 4}, {9, 36, 4}, {10, 40, 4}}};\n"),
(r"""                        double(extras.ref_scale), extras.wrap_clamped != 0 ? "wrap" : "leave as the row says");
        }
""",
 r"""                        double(extras.ref_scale), extras.wrap_clamped != 0 ? "wrap" : "leave as the row says");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62k_cutout-lit-fence)
            std::printf("Foliage lamp shadows (r62k): lit patch finder: a pixel is lit when its strongest lamp is within %.1f m "
                        "(BB_RT_CARD_LIT_DIST) and gives at least %.0f %% of its light (BB_RT_CARD_LIT_SHARE); a window line "
                        "('Foliage lamp shadows (r62k) lit <w>') follows every change of the live knobs file and one after 240 "
                        "frames: pixels lit and under a cut-out's shadow, their centre and bearing; the layer rule is %s "
                        "(BB_RT_CARD_LAMP_GATHER: 0 bilinear, 1 maximum of four, 2 nearest texel); the proof view's window line "
                        "('proof <w>') counts what all three keep; BB_RT_CARD_LAMP_PROOF_VIEW=3 with BB_LAMP_SHADOW_VIEW=7 paints "
                        "the lit view (red lit and under a cut-out's shadow, orange shadow only, green lit)%s\n",
                        double(extras.lit_dist_m), double(extras.lit_share) * 100.0,
                        extras.gather == 2 ? "the nearest texel" : extras.gather == 1 ? "the maximum of four texels" : "bilinear",
                        extras.proof_view == 3 ? " (on)" : "");
        }
"""),
(r"""// bbport (r63_leaf-stage4): every LampLineFrames frames with BB_RT_CARD_LAMPS=1: what the passes
""",
 r"""// bbport (r62k_cutout-lit-fence): the window lines of the lit patch (point_shadow_ray.comp cardLit) and, with the proof view on, of what
// each layer rule keeps. The numbers come first (a slot run keeps 300 characters of a line) under the "Foliage" prefix its evidence list
// keeps ahead of the rest. A window ends at each change of the live knobs file (BbLiveKnobs::Generation: a test job's set: and unset:
// actions, so the line of the n-th window says what the game did before the n-th change: the capture taken in that state) and once at 240
// frames, so a short job still prints before its first picture. The counters are those the card passes copied (read as CardLampsLine
// reads them, without waiting for the GPU). Called every frame while the card passes' set layout exists (BB_RT_CARD_LAMPS=1): with the
// knob off nothing runs.
static void CardLitWindowLine(VideoCore::Buffer* readback) {
    static std::array<u32, CARD_LAMP_COUNTERS> last{};
    static u32 frames = 0;
    static u32 windows = 0;
    static u32 seen_generation = BbLiveKnobs::Generation();
    static bool early_done = false;
    ++frames;
    const u32 generation = BbLiveKnobs::Generation();
    const bool changed = generation != seen_generation && frames >= 20;
    const bool early = !early_done && frames >= 240;
    if (!changed && !early) {
        return;
    }
    seen_generation = generation;
    early_done = true;
    const char letter[2] = {char('a' + (windows % 26)), '\0'};
    const char* const tag = early && !changed ? "early" : letter;
    windows += early && !changed ? 0 : 1;
    std::array<u32, CARD_LAMP_COUNTERS> now{};
    if (readback && readback->mapped_data.size() >= sizeof(now)) {
        readback->Invalidate(0, sizeof(now));
        std::memcpy(now.data(), readback->mapped_data.data(), sizeof(now));
    }
    std::array<double, CARD_LAMP_COUNTERS> d{};
    for (u32 i = 0; i < CARD_LAMP_COUNTERS; ++i) {
        d[i] = double(u32(now[i] - last[i]));
    }
    last = now;
    const u32 was_frames = std::exchange(frames, 0u);
    const auto share = [](double part, double whole) { return whole > 0.0 ? 100.0 * part / whole : 0.0; };
    const double both = d[CARD_LAMP_LIT_BOTH];
    const auto mean = [&](u32 index) { return both > 0.0 ? d[index] / both : 0.0; };
    const double x = both > 0.0 ? mean(CARD_LAMP_LIT_SUM_X) / 100.0 - 32.0 : 0.0;
    const double y = both > 0.0 ? mean(CARD_LAMP_LIT_SUM_Y) / 100.0 - 32.0 : 0.0;
    const double z = mean(CARD_LAMP_LIT_SUM_Z) / 100.0;
    std::printf("Foliage lamp shadows (r62k) lit %s: %.0f px lit and under a cut-out shadow of %.0f blocked, %.0f lit, %.0f seen "
                "(%u frames); dark %.0f %%, lamp %.0f %% of light at %.1f m; centre %.1f %.1f %.1f m (right up ahead) %.0f deg, "
                "screen %.0f %.0f\n",
                tag, both, d[CARD_LAMP_LIT_BLOCKED], d[CARD_LAMP_LIT_BRIGHT], d[CARD_LAMP_LIT_PIXELS], was_frames,
                mean(CARD_LAMP_LIT_SUM_DEPTH), mean(CARD_LAMP_LIT_SUM_SHARE), mean(CARD_LAMP_LIT_SUM_DIST) / 100.0, x, y, z,
                std::atan2(x, z) * 57.29578, mean(CARD_LAMP_LIT_SUM_PX), mean(CARD_LAMP_LIT_SUM_PY));
    if (d[CARD_LAMP_PROOF_PIXELS] > 0.0) {
        const double judged = d[CARD_LAMP_PROOF_KEPT] + d[CARD_LAMP_PROOF_ZERO] + d[CARD_LAMP_PROOF_PARTIAL];
        const double front = d[CARD_LAMP_PROOF_FRONT_READS];
        std::printf("Foliage lamp shadows (r62k) proof %s: of %.0f judged card px the game keeps %.1f %%, bilinear %.1f %%, max4 "
                    "%.1f %%, nearest %.1f %%; of %.0f reads at a card in front (game dropped) bilinear keeps %.1f %%, max4 "
                    "%.1f %%, nearest %.1f %% (false shadow)\n",
                    tag, judged, share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_JUDGED_BILIN], judged),
                    share(d[CARD_LAMP_JUDGED_MAX], judged), share(d[CARD_LAMP_JUDGED_NEAR], judged), front,
                    share(d[CARD_LAMP_FRONT_BILIN], front), share(d[CARD_LAMP_FRONT_MAX], front),
                    share(d[CARD_LAMP_FRONT_NEAR], front));
    }
}

// bbport (r63_leaf-stage4): every LampLineFrames frames with BB_RT_CARD_LAMPS=1: what the passes
"""),
(r"""void PointShadow::CardLampsLine() {
    if (!card_set_layout || ++card_frames < LampLineFrames) {
""",
 r"""void PointShadow::CardLampsLine() {
    if (card_set_layout) {
        CardLitWindowLine(card_readback.get()); // bbport (r62k_cutout-lit-fence)
    }
    if (!card_set_layout || ++card_frames < LampLineFrames) {
"""),
],
H: [
("    std::array<u32, 48> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32)\n",
 "    std::array<u32, 64> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32, then 48; r62k: was 48)\n"),
],
}

ROW = (
    "| `BB_RT_CARD_LIT_SHARE`, `BB_RT_CARD_LIT_DIST` | The lit patch finder of the cut-out lamp shadows (r62k); only with `BB_RT_CARD_ALPHA=2` "
    "and `BB_RT_CARD_LAMPS=1`, read at start, numbers. A pixel whose lamp rays are cast is *lit* when its strongest lamp is within "
    "`BB_RT_CARD_LIT_DIST` metres (0.5 to 15) and gives at least `BB_RT_CARD_LIT_SHARE` (0.05 to 1) of its light, and *under a cut-out "
    "shadow* when a leaf texel stopped the ray to that lamp. The log says, in a `Foliage lamp shadows (r62k) lit <w>` line at every "
    "change of the live knobs file and one at 240 frames, how many pixels are both, their centre (view space, metres) and bearing, how "
    "dark they are; `BB_RT_CARD_LAMP_PROOF_VIEW=3` with `BB_LAMP_SHADOW_VIEW=7` paints them (red lit and under a cut-out shadow, orange "
    "shadow only, green lit). `BB_RT_CARD_LAMP_GATHER=2` reads the nearest layer texel (no dilation; 1 is the maximum of four, 0 the "
    "bilinear value); the proof view's `proof <w>` line says what the three rules keep of the pixels the game kept and of the reads at "
    "cards in front of a surface (false shadows) | `0.5`, `4`; off |")
ANCHOR_ROW = "| `BB_RT_CARD_LAMP_GATHER`, `BB_RT_CARD_LAMP_WRAP` |"


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_GATHER row is there %d times, wanted 1 (r62j applied?)" % len(lines))
    return [(lines[0] + "\n", lines[0] + "\n" + ROW + "\n")]


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
            raise SystemExit("text check: %s: a line of r62k is outside its #ifdef: %r" % (what, line))


def text_checks(texts):
    g, s, l, c, h, r = (texts[p] for p in FILES)
    for want, n in (("layout(constant_id = 9) const float CARD_LIT_SHARE = 0.5;", 1),
                    ("layout(constant_id = 10) const float CARD_LIT_DIST = 4.0;", 1),
                    ("uint cardLit(vec3 P, vec3 lamp_light, vec3 base_light, uint top_at, bool top_card, float ratio, ivec2 px) {", 1),
                    ("bool cardKeptByRule(uint slot, uint primitive, vec2 bary, uint rule) {", 1),
                    ("void countRules(uint slot, uint primitive, vec2 bary, uint first_counter) {", 1),
                    ("card_nearest = CARD_GATHER == 2u;", 2),
                    ("lit_class = cardLit(P, d0 + d1, s0 + s1, top_at, top_card, ratio, px);", 1),
                    ("if (CARD_PROOF == 3u && t_view == 7u && live) {", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # every set of card_nearest by cardKeptByRule is restored (the rule sets true for rule 2 only, restores the configured one)
    if s.count("card_nearest = rule == 2u;") != 1:
        raise SystemExit("text check: card_nearest set in cardKeptByRule")
    inside_only(s, ("r62k", "CARD_LIT_", "cardLit", "cardKeptByRule", "countRules", "lit_class", "card_nearest",
                    "CARD_LAMP_LIT_", "CARD_LAMP_FRONT_BILIN", "CARD_LAMP_JUDGED_BILIN"), {"CARDS"}, S)
    if g.count("bool card_nearest = false;") != 1 or g.count("if (card_nearest) {") != 1:
        raise SystemExit("text check: rt_cards.glsl card_nearest")
    if g.count("#define CARD_TEXEL(uv, layer, lod, op) textureLod(card_alpha, vec3(uv, float(layer)), lod).r") != 1:
        raise SystemExit("text check: rt_cards.glsl's old-text macro")
    for name in ("FRONT_BILIN 43", "FRONT_MAX 44", "FRONT_NEAR 45", "JUDGED_BILIN 46", "JUDGED_MAX 47", "JUDGED_NEAR 48",
                 "LIT_PIXELS 49", "LIT_BLOCKED 50", "LIT_BRIGHT 51", "LIT_BOTH 52", "LIT_SUM_X 53", "LIT_SUM_Y 54", "LIT_SUM_Z 55",
                 "LIT_SUM_PX 56", "LIT_SUM_PY 57", "LIT_SUM_DIST 58", "LIT_SUM_SHARE 59", "LIT_SUM_DEPTH 60"):
        if l.count("#define CARD_LAMP_" + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define CARD_LAMP_%s" % (L, name))
    if l.count("#define CARD_LAMP_COUNTERS 64 ") != 1:
        raise SystemExit("text check: CARD_LAMP_COUNTERS is not 64")
    if c.count("std::array<u32, 11> spec_words{") != 1 or c.count("std::array<vk::SpecializationMapEntry, 11> spec_entries{") != 1 \
       or "{10, 40, 4}" not in c:
        raise SystemExit("text check: spec words / entries")
    if c.count("CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u, 0.5f, 4.0f};") != 1:
        raise SystemExit("text check: CardExtras initializer")
    for key in ('"BB_RT_CARD_LIT_SHARE"', '"BB_RT_CARD_LIT_DIST"', "Foliage lamp shadows (r62k): lit patch finder:",
                "Foliage lamp shadows (r62k) lit %s:", "Foliage lamp shadows (r62k) proof %s:",
                "static void CardLitWindowLine(VideoCore::Buffer* readback) {", "CardLitWindowLine(card_readback.get());"):
        if c.count(key) != 1:
            raise SystemExit("text check: %r" % key)
    if h.count("std::array<u32, 64> card_last{}") != 1:
        raise SystemExit("text check: card_last")
    if len([x for x in r.split("\n") if x.startswith("| `BB_RT_CARD_LIT_SHARE`")]) != 1:
        raise SystemExit("text check: README row")
    # every printed line of r62k stays under the runner's 300 characters with plausible numbers (format widths)
    lit = ("Foliage lamp shadows (r62k) lit early: 99999 px lit and under a cut-out shadow of 99999 blocked, 99999 lit, 99999 seen "
           "(9999 frames); dark 100 %, lamp 100 % of light at 15.0 m; centre -32.0 -32.0 199.9 m (right up ahead) -180 deg, "
           "screen 1920 1080")
    if len(lit) > 300:
        raise SystemExit("text check: the lit line is %d characters" % len(lit))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62K_CUTOUT_LIT_FENCE_ROOT)" % ROOT)
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
            tmp = full + ".r62ktmp"
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
        tmp = full + ".r62ktmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
