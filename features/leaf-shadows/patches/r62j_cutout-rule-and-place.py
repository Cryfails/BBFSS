# r62j_cutout-rule-and-place: FEATURE (the cut-out lamp shadows' alpha rule, with a two-sided proof) on top of r62i (build 39).
# Only in the CARDS builds of the lamp pass (BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1); with the knobs off nothing of it exists.
#
# Why. Build 39's proof (r62i) of the card chain, at the weeds of lamp-test-spot: 1680 card pixels the game itself KEPT, the layer
# keeps 61.8 % at level 0, 8.1 % are on a texel of alpha 0, 30.1 % on a partly covered texel the rule dropped, 11.2 % have raw
# coordinates outside 0-1. At the dream house (broad leaves) the same chain reads 99.1 % kept: the chain is right, the layer is
# the problem. The layer is a 256 square box mean of the game's texture: a thin blade covers a part of a layer texel, so its alpha
# lies between 0 and the reference (0.196 for the weeds) where the game, sampling its own bigger texture, kept the pixel.
#
# What this patch does (CARDS builds only):
#  1. THE RULE. The lamp rays read a layer texel with the 2x2 MAXIMUM of the bilinear footprint (textureGather, one fetch like the
#     bilinear one; level 0 only) instead of the bilinear value: a blade that touches a texel keeps the texel, as the game's own
#     finer texture keeps the pixel. BB_RT_CARD_LAMP_GATHER=0 turns it off (r62h's read), default 1. The reference scale
#     BB_RT_CARD_LAMP_REF default goes 0.6 -> 0.5 (a texel above half the reference is a blade; a guess, the proof's bins say what
#     scale reaches what share). cardTestLod gets two globals for it (card_dilate, card_wrap_clamped), set per lamp ray.
#  2. UVs OUTSIDE 0-1. cardRepeatAxis already wraps or mirrors them as the row's mode (the sampler's clamp mode) says; the proof
#     now says whether that is right: of the card pixels with raw coordinates outside 0-1, the share the row's mode keeps, and
#     the share a forced wrap would keep (BB_RT_CARD_LAMP_WRAP=1 makes the lamp rays wrap an axis whose mode is a plain clamp;
#     default 0, the row's mode).
#  3. A TWO-SIDED PROOF (r62i could only fail one way: a rule that keeps everything reads 100 %). Counters 32-42 of the (now) 48:
#     the judged card pixels the LAMP rule keeps; the pixels the game's rule drops on a partly covered texel by texel alpha over
#     the reference (under 0.25, 0.25-0.5, 0.5-1: a scale s keeps all bins above s); the outside-0-1 pixels (judged, kept by the
#     row's mode, kept by a forced wrap); and the reads at the cards IN FRONT of the pixel's surface on the camera ray (up to 6 a
#     pixel; the game dropped those texels, else they would be the surface): how many, on alpha 0, kept by the game's rule (must be
#     ~0: a chain fault if not), kept by the lamp rule (the false shadow rate of the rule). Line 'Ray traced lamps (r62j)'.
#
# Off: nothing runs without BB_RT_CARD_ALPHA=2 + BB_RT_CARD_LAMPS=1 (the CARDS pipelines are not made). The new shader lines are
# inside #ifdef CARDS / CARD_TRACE_SHADOW (rt_cards.glsl's additions are macros that expand to the old text without
# CARD_TRACE_SHADOW: rt_card_view.comp and the 12 builds without CARDS stay byte-identical, proved by compiling before and after).
# The counter buffer grows 128 -> 192 bytes (CARDS builds only). Cost: a gather fetch for a bilinear one (same unit, 4 texels
# read); the proof's extra reads only while BB_RT_CARD_LAMP_PROOF_VIEW and view 7 are on, on 1 pixel in 16 of 1 pass in 16.
#
# Files: rt_cards.glsl, point_shadow_ray.comp, rt_card_layers_layout.h, vk_point_shadow.cpp, vk_point_shadow.h, README.md.
# No new file, no CMake change. Revert r62j before r62i. Not compiled here (no clang++); the C++ spots are named in the hand-off.
#
# Use: python -I -X utf8 r62j_cutout-rule-and-place.py check | apply | revert
# Root: R62J_CUTOUT_RULE_AND_PLACE_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r62j_backup.
import os, sys

ROOT = os.environ.get("R62J_CUTOUT_RULE_AND_PLACE_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62j_backup")
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
("uint card_lod16 = 0u;\n#endif\n",
 """uint card_lod16 = 0u;
// bbport (r62j_cutout-rule-and-place): card_dilate: a read at level 0 takes the maximum of the bilinear footprint's four
// texels where the row's rule is "above the reference" (greater, greater or equal; a thin blade that touches a texel keeps
// it: the layer is a box mean of a bigger texture; the "below" rules keep the bilinear value); card_wrap_clamped: an axis
// whose mode is a plain clamp wraps instead. Both are set by the lamp pass for one ray's reads (cardReadLampRule and the lamp
// ray) and reset after; the macros below are the old text where CARD_TRACE_SHADOW is not defined.
bool card_dilate = false;
bool card_wrap_clamped = false;
float cardTexel(vec2 uv, uint layer, float lod, uint op) {
    if (card_dilate && lod <= 0.0 && (op == CARD_OP_GREATER || op == CARD_OP_GREATER_EQUAL)) {
        const vec4 g = textureGather(card_alpha, vec3(uv, float(layer)), 0);
        return max(max(g.x, g.y), max(g.z, g.w));
    }
    return textureLod(card_alpha, vec3(uv, float(layer)), lod).r;
}
uint cardModeAdjust(uint mode, uint extra) {
    return card_wrap_clamped && mode == CARD_UV_MODE_CLAMP && extra == 0u ? uint(CARD_UV_MODE_WRAP) : mode;
}
#define CARD_TEXEL(uv, layer, lod, op) cardTexel(uv, layer, lod, op)
#define CARD_MODE(m, e) cardModeAdjust(m, e)
#else
#define CARD_TEXEL(uv, layer, lod, op) textureLod(card_alpha, vec3(uv, float(layer)), lod).r
#define CARD_MODE(m, e) (m)
#endif
"""),
("""    r.uv = vec2(cardRepeatAxis(uv.x, (a.z >> CARD_ROW_MODE_U_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u, border),
                cardRepeatAxis(uv.y, (a.z >> CARD_ROW_MODE_V_SHIFT) & 3u,
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
""",
 """    r.uv = vec2(cardRepeatAxis(uv.x, CARD_MODE((a.z >> CARD_ROW_MODE_U_SHIFT) & 3u, (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u),
                               (a.z >> CARD_ROW_EXTRA_U_SHIFT) & 3u, border),
                cardRepeatAxis(uv.y, CARD_MODE((a.z >> CARD_ROW_MODE_V_SHIFT) & 3u, (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u),
                               (a.z >> CARD_ROW_EXTRA_V_SHIFT) & 3u, border));
"""),
("    r.alpha = textureLod(card_alpha, vec3(r.uv, float(layer)), lod).r * factor;\n",
 "    r.alpha = CARD_TEXEL(r.uv, layer, lod, (a.z >> CARD_ROW_OP_SHIFT) & 7u) * factor; // bbport (r62j_cutout-rule-and-place)\n"),
],
S: [
("layout(constant_id = 6) const uint CARD_PROOF = 0u;\n",
 """layout(constant_id = 6) const uint CARD_PROOF = 0u;
// bbport (r62j_cutout-rule-and-place): specialization constants 7 and 8 (vk_point_shadow.cpp): CARD_GATHER 1: the lamp rays
// read a layer texel as the maximum of the bilinear footprint's four (card_dilate); CARD_WRAP_CLAMPED 1: an axis whose
// sampler mode is a plain clamp wraps in the lamp rays' reads (card_wrap_clamped).
layout(constant_id = 7) const uint CARD_GATHER = 1u;
layout(constant_id = 8) const uint CARD_WRAP_CLAMPED = 0u;
"""),
("        card_ref_scale = CARD_REF_SCALE; // bbport (r62h_cutout-cards-hit): for this ray's reads only\n",
 """        card_ref_scale = CARD_REF_SCALE; // bbport (r62h_cutout-cards-hit): for this ray's reads only
        card_dilate = CARD_GATHER != 0u; // bbport (r62j_cutout-rule-and-place)
        card_wrap_clamped = CARD_WRAP_CLAMPED != 0u;
"""),
("        card_ref_scale = 1.0;\n        cardCount(CARD_LAMP_SPLIT_READS, card_hit.tested);\n",
 """        card_ref_scale = 1.0;
        card_dilate = false; // bbport (r62j_cutout-rule-and-place)
        card_wrap_clamped = false;
        cardCount(CARD_LAMP_SPLIT_READS, card_hit.tested);
"""),
("    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x04u | CARD_LAMP_MASK,\n",
 """    // bbport (r62j_cutout-rule-and-place): the combined ray reads with the lamp rule too
    card_ref_scale = CARD_REF_SCALE;
    card_dilate = CARD_GATHER != 0u;
    card_wrap_clamped = CARD_WRAP_CLAMPED != 0u;
    const CardRay hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, 0x04u | CARD_LAMP_MASK,
"""),
("    cardNote(hit);\n    ray_card_kept = hit.how == CARD_RAY_KEPT;\n",
 """    card_ref_scale = 1.0; // bbport (r62j_cutout-rule-and-place)
    card_dilate = false;
    card_wrap_clamped = false;
    cardNote(hit);
    ray_card_kept = hit.how == CARD_RAY_KEPT;
"""),
# --- the proof: helpers before cardProof
("uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {\n",
 """// bbport (r62j_cutout-rule-and-place): the proof's sampled pixels (1 in 16 of the counted passes, as proofCount), a read with
// the LAMP rule (reference scale, 2x2 maximum, wrap of clamped axes: what a lamp ray's read does at level 0), and a read at a
// card in front of the pixel's surface (the game dropped its texel there: the lamp rule must drop it too).
bool proofSampled() {
    return (mode & MODE_CARD_COUNT) != 0u && ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 3u) == 0u;
}
CardResult cardReadLampRule(uint slot, uint primitive, vec2 bary) {
    card_ref_scale = CARD_REF_SCALE;
    card_dilate = CARD_GATHER != 0u;
    card_wrap_clamped = CARD_WRAP_CLAMPED != 0u;
    const CardResult lamp = cardTestLod(slot, primitive, bary, 0.0);
    card_ref_scale = 1.0;
    card_dilate = false;
    card_wrap_clamped = false;
    return lamp;
}
void proofFront(uint slot, uint primitive, vec2 bary) {
    const CardResult game = cardTestLod(slot, primitive, bary, 0.0);
    if (game.status == CARD_NO_DATA || (game.flags & (CARD_ROW_SUN | CARD_ROW_DITHER | CARD_ROW_CLEAR)) != 0u) {
        return;
    }
    const CardResult lamp = cardReadLampRule(slot, primitive, bary);
    atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_READS], 1u);
    if (game.alpha <= 0.0) {
        atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_ZERO], 1u);
    }
    if (game.status == CARD_KEPT) {
        atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_GAME_KEPT], 1u);
    }
    if (lamp.status == CARD_KEPT) {
        atomicAdd(card_counts[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], 1u);
    }
}
uint cardProof(vec3 P, out CardResult r0, out bool kept_l1, out bool uv_outside) {
"""),
("    float best_diff = 1e30;\n",
 "    float best_diff = 1e30;\n    uint front_left = proofSampled() ? 6u : 0u; // bbport (r62j_cutout-rule-and-place)\n"),
("        const float diff = abs(rayQueryGetIntersectionTEXT(query, false) - depth_t);\n",
 """        if (front_left > 0u && rayQueryGetIntersectionTEXT(query, false) < depth_t - tol) {
            --front_left; // bbport (r62j_cutout-rule-and-place): a card in front of the surface
            proofFront(slot, uint(rayQueryGetIntersectionPrimitiveIndexEXT(query, false)),
                       rayQueryGetIntersectionBarycentricsEXT(query, false));
        }
        const float diff = abs(rayQueryGetIntersectionTEXT(query, false) - depth_t);
"""),
("    return r0.status == CARD_KEPT ? PROOF_KEPT : r0.alpha <= 0.0 ? PROOF_ZERO : PROOF_PARTIAL;\n",
 """    if (proofSampled()) { // bbport (r62j_cutout-rule-and-place): the lamp rule, the bins, the outside-0-1 pixels
        if (cardReadLampRule(best_slot, best_primitive, best_bary).status == CARD_KEPT) {
            atomicAdd(card_counts[CARD_LAMP_PROOF_LAMP_KEPT], 1u);
        }
        if (r0.status != CARD_KEPT && r0.alpha > 0.0) {
            const float ratio = r0.alpha / max(uintBitsToFloat(card_rows[best_slot * 2u].w), 1e-6);
            atomicAdd(card_counts[ratio < 0.25 ? CARD_LAMP_PROOF_BIN1 : ratio < 0.5 ? CARD_LAMP_PROOF_BIN2
                                                                                    : CARD_LAMP_PROOF_BIN3], 1u);
        }
        if (uv_outside) {
            atomicAdd(card_counts[CARD_LAMP_PROOF_OUT_JUDGED], 1u);
            if (r0.status == CARD_KEPT) {
                atomicAdd(card_counts[CARD_LAMP_PROOF_OUT_KEPT], 1u);
            }
            card_wrap_clamped = true;
            const CardResult wrapped = cardTestLod(best_slot, best_primitive, best_bary, 0.0);
            card_wrap_clamped = false;
            if (wrapped.status == CARD_KEPT) {
                atomicAdd(card_counts[CARD_LAMP_PROOF_OUT_WRAP_KEPT], 1u);
            }
        }
    }
    return r0.status == CARD_KEPT ? PROOF_KEPT : r0.alpha <= 0.0 ? PROOF_ZERO : PROOF_PARTIAL;
"""),
],
L: [
("#define CARD_LAMP_PROOF_UV_OUTSIDE 31\n#define CARD_LAMP_COUNTERS 32 // (r62h: was 16)\n",
 """#define CARD_LAMP_PROOF_UV_OUTSIDE 31
// bbport (r62j_cutout-rule-and-place): eleven more of the proof view, then spare: the judged card pixels the LAMP rule keeps;
// the pixels the game's rule dropped on a partly covered texel, by texel alpha over the reference (under 0.25, 0.25-0.5,
// 0.5-1); the judged pixels with coordinates outside 0-1, those the row's mode keeps, those a forced wrap would keep; the
// reads at cards in front of the surface (the game dropped them): all, on alpha 0, kept by the game's rule, kept by the lamp rule.
#define CARD_LAMP_PROOF_LAMP_KEPT 32
#define CARD_LAMP_PROOF_BIN1 33
#define CARD_LAMP_PROOF_BIN2 34
#define CARD_LAMP_PROOF_BIN3 35
#define CARD_LAMP_PROOF_OUT_JUDGED 36
#define CARD_LAMP_PROOF_OUT_KEPT 37
#define CARD_LAMP_PROOF_OUT_WRAP_KEPT 38
#define CARD_LAMP_PROOF_FRONT_READS 39
#define CARD_LAMP_PROOF_FRONT_ZERO 40
#define CARD_LAMP_PROOF_FRONT_GAME_KEPT 41
#define CARD_LAMP_PROOF_FRONT_LAMP_KEPT 42
#define CARD_LAMP_COUNTERS 48 // (r62h: was 16; r62j: was 32)
"""),
],
C: [
("static_assert(CARD_LAMP_COUNTERS == 32); // bbport (r62h_cutout-cards-hit): was 16 (header.h card_last)\n",
 "static_assert(CARD_LAMP_COUNTERS == 48); // bbport (r62h_cutout-cards-hit): was 16; r62j: was 32 (header.h card_last)\n"),
("              CARD_LAMP_PROOF_UV_OUTSIDE == CARD_LAMP_COUNTERS - 1);\n",
 """              CARD_LAMP_PROOF_UV_OUTSIDE == CARD_LAMP_PROOF_UNJUDGED + 2);
// bbport (r62j_cutout-rule-and-place): its eleven counters follow, then spare ones
static_assert(CARD_LAMP_PROOF_LAMP_KEPT == CARD_LAMP_PROOF_UV_OUTSIDE + 1 &&
              CARD_LAMP_PROOF_FRONT_LAMP_KEPT == CARD_LAMP_PROOF_LAMP_KEPT + 10 &&
              CARD_LAMP_PROOF_FRONT_LAMP_KEPT < CARD_LAMP_COUNTERS);
"""),
("    u32 proof_view;    // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW, 0 (off), 1 or 2\n};\n",
 """    u32 proof_view;    // bbport (r62i_cutout-uv-proof): BB_RT_CARD_LAMP_PROOF_VIEW, 0 (off), 1 or 2
    u32 gather;        // bbport (r62j_cutout-rule-and-place): BB_RT_CARD_LAMP_GATHER, 0 or 1, default 1
    u32 wrap_clamped;  // BB_RT_CARD_LAMP_WRAP, 0 or 1, default 0
};
"""),
("        CardExtras e{0.02f, false, 0.0f, 0.6f, 0.03f, 0u}; // (r62h: three more; r62i: the proof view)\n",
 "        CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u}; // (r62h: three more; r62i: the proof view; r62j: REF 0.5, gather, wrap)\n"),
("            e.proof_view = proof[0] == '1' && proof[1] == '\\0' ? 1u : proof[0] == '2' && proof[1] == '\\0' ? 2u : 0u;\n        }\n",
 """            e.proof_view = proof[0] == '1' && proof[1] == '\\0' ? 1u : proof[0] == '2' && proof[1] == '\\0' ? 2u : 0u;
        }
        // bbport (r62j_cutout-rule-and-place): exactly "0" or "1"; anything else keeps the default
        const auto flag = [](const char* name, u32 fallback) -> u32 {
            const char* const text = std::getenv(name);
            return text && text[0] == '0' && text[1] == '\\0' ? 0u : text && text[0] == '1' && text[1] == '\\0' ? 1u : fallback;
        };
        e.gather = flag("BB_RT_CARD_LAMP_GATHER", e.gather);
        e.wrap_clamped = flag("BB_RT_CARD_LAMP_WRAP", e.wrap_clamped);
"""),
("    const std::array<u32, 7> spec_words{",
 "    const std::array<u32, 9> spec_words{"),
("                                        extras.proof_view}; // (r62i_cutout-uv-proof: constant 6 CARD_PROOF)\n",
 "                                        extras.proof_view, extras.gather,\n"
 "                                        extras.wrap_clamped}; // (r62i: constant 6 CARD_PROOF; r62j_cutout-rule-and-place: 7 CARD_GATHER, 8 CARD_WRAP_CLAMPED)\n"),
("    const std::array<vk::SpecializationMapEntry, 7> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}}};\n",
 "    const std::array<vk::SpecializationMapEntry, 9> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}, {3, 12, 4}, {4, 16, 4}, {5, 20, 4}, {6, 24, 4}, {7, 28, 4}, {8, 32, 4}}};\n"),
("                        extras.proof_view, extras.proof_view == 2 ? \"; 2: the layer's alpha as grey in place of white/black\" : \"\");\n        }\n",
 """                        extras.proof_view, extras.proof_view == 2 ? "; 2: the layer's alpha as grey in place of white/black" : "");
        }
        {
            const CardExtras extras = CardExtrasFromEnv(); // bbport (r62j_cutout-rule-and-place)
            std::printf("Ray traced lamps (r62j): cut-out rule: the lamp rays read a layer texel as the %s "
                        "(BB_RT_CARD_LAMP_GATHER, default 1), keep it above %.2f times the game's reference "
                        "(BB_RT_CARD_LAMP_REF, default 0.5), and %s the axes whose sampler mode is a plain clamp "
                        "(BB_RT_CARD_LAMP_WRAP, default 0: the row's mode); the proof view's line counts what each rule keeps\\n",
                        extras.gather != 0 ? "maximum of the bilinear footprint's four texels" : "bilinear value",
                        double(extras.ref_scale), extras.wrap_clamped != 0 ? "wrap" : "leave as the row says");
        }
"""),
("                    share(d[CARD_LAMP_PROOF_UV_OUTSIDE], cards));\n    }\n",
 """                    share(d[CARD_LAMP_PROOF_UV_OUTSIDE], cards));
        // bbport (r62j_cutout-rule-and-place): the two-sided proof of the rule (shares of the judged card pixels, then of the
        // outside-0-1 pixels, then of the reads at cards in front of the surface, which the game dropped)
        const double out_judged = d[CARD_LAMP_PROOF_OUT_JUDGED];
        const double front = d[CARD_LAMP_PROOF_FRONT_READS];
        const CardExtras rule = CardExtrasFromEnv();
        std::printf("Ray traced lamps (r62j): of %.0f judged card pixels the lamp rule (reference x%.2f, 2x2 maximum %u, "
                    "wrap %u) keeps %.1f %% (the game's rule %.1f %%); of them the game dropped on a partly covered texel "
                    "by texel alpha over the reference: %.1f %% under 0.25, %.1f %% 0.25-0.5, %.1f %% 0.5-1; of %.0f pixels "
                    "with coordinates outside 0-1 the row's mode keeps %.1f %%, a wrap would keep %.1f %%; of %.0f reads at a "
                    "card in front of the surface (the game dropped them): %.1f %% on alpha 0, the game's rule keeps %.1f %% "
                    "(a chain fault if not 0), the lamp rule keeps %.1f %% (false shadow)\\n",
                    judged, double(rule.ref_scale), rule.gather, rule.wrap_clamped, share(d[CARD_LAMP_PROOF_LAMP_KEPT], judged),
                    share(d[CARD_LAMP_PROOF_KEPT], judged), share(d[CARD_LAMP_PROOF_BIN1], judged),
                    share(d[CARD_LAMP_PROOF_BIN2], judged), share(d[CARD_LAMP_PROOF_BIN3], judged), out_judged,
                    share(d[CARD_LAMP_PROOF_OUT_KEPT], out_judged), share(d[CARD_LAMP_PROOF_OUT_WRAP_KEPT], out_judged), front,
                    share(d[CARD_LAMP_PROOF_FRONT_ZERO], front), share(d[CARD_LAMP_PROOF_FRONT_GAME_KEPT], front),
                    share(d[CARD_LAMP_PROOF_FRONT_LAMP_KEPT], front));
    }
"""),
],
H: [
("    std::array<u32, 32> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS\n",
 "    std::array<u32, 48> card_last{}; // bbport (r62h_cutout-cards-hit): CARD_LAMP_COUNTERS (r62j: was 32)\n"),
],
}

ROW = (
    "| `BB_RT_CARD_LAMP_GATHER`, `BB_RT_CARD_LAMP_WRAP` | The cut-out rule of the lamp rays (r62j); only with `BB_RT_CARD_ALPHA=2` and "
    "`BB_RT_CARD_LAMPS=1`, read at start, exactly `0` or `1`. The layer is a 256 square box mean of the game's texture, so a thin "
    "blade (grass, a bar, a hook) covers part of a layer texel and the texel's alpha stays under the game's reference where the "
    "game, sampling its own bigger texture, kept the pixel (at the weeds of the test spot the layer kept only 62 % of the pixels "
    "the game kept). `BB_RT_CARD_LAMP_GATHER=1` (default) makes a lamp ray read the maximum of the bilinear footprint's four "
    "texels (one gather fetch in place of the bilinear one; level 0 only), so a blade that touches a texel keeps it; `0` is the "
    "bilinear read of r62h. `BB_RT_CARD_LAMP_WRAP=1` wraps an axis whose sampler mode is a plain clamp (default `0`: the row's mode, "
    "which already wraps or mirrors as the game's sampler does). The proof view's `Ray traced lamps (r62j)` line says what each "
    "rule keeps of the pixels the game kept, of the pixels outside 0-1, and of the cards in front of a surface (which the game "
    "dropped: the rule's false shadows) | `1`, `0`; off |")
ANCHOR_ROW = "| `BB_RT_CARD_LAMP_PROOF_VIEW` |"
OLD_TAIL = "| `0`, `0.6`, `0.03`; off |\n"
NEW_TAIL = "| `0`, `0.5` (r62j; was `0.6`), `0.03`; off |\n"


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_LAMP_PROOF_VIEW row is there %d times, wanted 1 (r62i applied?)" % len(lines))
    return [(OLD_TAIL, NEW_TAIL), (lines[0] + "\n", lines[0] + "\n" + ROW + "\n")]


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
            raise SystemExit("text check: %s: a line of r62j is outside its #ifdef: %r" % (what, line))


def text_checks(texts):
    g, s, l, c, h, r = (texts[p] for p in FILES)
    for want, n in (("layout(constant_id = 7) const uint CARD_GATHER = 1u;", 1),
                    ("layout(constant_id = 8) const uint CARD_WRAP_CLAMPED = 0u;", 1),
                    ("CardResult cardReadLampRule(uint slot, uint primitive, vec2 bary) {", 1),
                    ("void proofFront(uint slot, uint primitive, vec2 bary) {", 1),
                    ("bool proofSampled() {", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # every lamp-ray set of the three globals is undone: sets (CARD_GATHER != 0u) vs resets (= false)
    if s.count("card_dilate = CARD_GATHER != 0u;") != 3 or s.count("card_dilate = false;") != 3:
        raise SystemExit("text check: the lamp rule's globals are not set and reset in pairs (3 and 3)")
    inside_only(s, ("r62j", "CARD_GATHER", "CARD_WRAP_CLAMPED", "card_dilate", "card_wrap_clamped", "proofSampled",
                    "proofFront", "cardReadLampRule", "CARD_LAMP_PROOF_FRONT", "CARD_LAMP_PROOF_BIN"), {"CARDS"}, S)
    if g.count("#define CARD_TEXEL(uv, layer, lod, op) textureLod(card_alpha, vec3(uv, float(layer)), lod).r") != 1 or \
       g.count("#define CARD_MODE(m, e) (m)") != 1:
        raise SystemExit("text check: rt_cards.glsl's old-text macros")
    names = ["LAMP_KEPT 32", "BIN1 33", "BIN2 34", "BIN3 35", "OUT_JUDGED 36", "OUT_KEPT 37", "OUT_WRAP_KEPT 38",
             "FRONT_READS 39", "FRONT_ZERO 40", "FRONT_GAME_KEPT 41", "FRONT_LAMP_KEPT 42"]
    for name in names:
        if l.count("#define CARD_LAMP_PROOF_" + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define CARD_LAMP_PROOF_%s" % (L, name))
    if l.count("#define CARD_LAMP_COUNTERS 48 ") != 1:
        raise SystemExit("text check: CARD_LAMP_COUNTERS is not 48")
    if c.count("std::array<u32, 9> spec_words{") != 1 or c.count("std::array<vk::SpecializationMapEntry, 9> spec_entries{") != 1 \
       or "{8, 32, 4}" not in c:
        raise SystemExit("text check: spec words / entries")
    if c.count("CardExtras e{0.02f, false, 0.0f, 0.5f, 0.03f, 0u, 1u, 0u};") != 1:
        raise SystemExit("text check: CardExtras initializer")
    for key in ('"BB_RT_CARD_LAMP_GATHER"', '"BB_RT_CARD_LAMP_WRAP"', "Ray traced lamps (r62j): cut-out rule:",
                "Ray traced lamps (r62j): of %.0f judged card pixels"):
        if c.count(key) != 1:
            raise SystemExit("text check: %r" % key)
    if h.count("std::array<u32, 48> card_last{}") != 1:
        raise SystemExit("text check: card_last")
    if len([x for x in r.split("\n") if x.startswith("| `BB_RT_CARD_LAMP_GATHER`")]) != 1:
        raise SystemExit("text check: README row")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62J_CUTOUT_RULE_AND_PLACE_ROOT)" % ROOT)
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
            tmp = full + ".r62jtmp"
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
        tmp = full + ".r62jtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
