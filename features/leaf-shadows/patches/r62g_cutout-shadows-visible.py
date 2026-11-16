# r62g_cutout-shadows-visible: FEATURE patch (cut-out shadows, lane r62g of 2026-11-16). Off unless
# BB_RT_CARD_ALPHA=2 and BB_RT_CARD_LAMPS=1 are on (the builds of before are untouched: see "Off").
#
# Why (owner, 2026-11-16: "I can't see anything in the cut out shadows, why not use the foliage in the
# same scene instead to test the cut out shadows"): the cards work (r63 line: 24.0-25.5 % of the lamp rays
# that meet a card are stopped by a kept texel, a read keeps 7-9 % of the time, the weeds region is net
# darker in the sharp-lamp pictures) but a lamp is a disc (0.1 m by default) and the shadow of a thin blade
# or a small leaf on a surface behind it is a penumbra wider than the blade: a 1 cm blade 0.5 m from the
# lamp, receiver 0.3 m behind it: at most 17 % of the lamp's disc is blocked (penumbra 12 cm), with a
# 0.02 m disc 78 % (2.4 cm). The solid geometry wants the soft disc (it is the owner's soft look); a leaf
# wants a small one. So (this patch):
#  1. point_shadow_ray.comp, CARDS builds only: where the lamp's disc is larger than CARD_DISC (specialization
#     constant 1, BB_RT_CARD_LAMP_RADIUS, default 0.02 m; 0.5 = the lamp's own disc, as before) a lamp ray
#     is two rays: the solid geometry (mask 0x04, opaque: the very ray the builds without cards cast) to the
#     point of the lamp's disc as before, and, only when that one is free, the cut-out cards (mask 0x08, the
#     candidate loop of cardTraceShadow) to the point of the same disc scaled to CARD_DISC. Blocked when
#     either is. So the solid shadows are the soft ones of before and the cut-out shadows are sharp.
#  2. Test view: with BB_RT_CARD_LAMP_SHARE_VIEW=1 (read at start) BB_LAMP_SHADOW_VIEW=7 paints, per pixel,
#     the share of the rays it cast this frame that only a leaf texel blocked (red to yellow to white) over a
#     dim copy of the shadow ratio (the categories of view 7 are shown without the knob).
#  3. Numbers for the cause (the r63 line stays; one more line "Ray traced lamps (r62g)"): of the layer reads
#     the share at a level above 0, on a texel of alpha 0, on a partly covered texel the rule dropped, kept;
#     the card rays cast, those a card alone blocked, those the solid ray blocked first. Six more counters in
#     the same 16-uint buffer (indices 10-15, rt_card_layers_layout.h).
#
# Off: the knobs off build no CARDS pipeline and call nothing of this patch (CardExtrasFromEnv is called
# only from MakeCardBuild and the once-line, both in the BB_RT_CARD_LAMPS=1 branch). Every new shader line
# is inside #ifdef CARDS (the 12 builds without CARDS compile to the same SPIR-V words: proved by compiling
# all 16 point_shadow_ray builds before and after). With BB_RT_CARD_LAMP_RADIUS=0.5 the CARDS builds trace the
# one ray of r63 (the picture is r63's; the counters are the only difference).
#
# Cost, CARDS builds with a card in the scene and a sharp card disc: one more ray query (cards only, mask
# 0x08) for each lamp ray the solid ray left free; the solid ray is the plain pass's ray (cheaper than the
# combined ray of r63, which entered the candidate loop); estimate 0.05-0.15 ms GPU at 1080p render (4K
# DLSS Performance) at lamp-test-spot, NOT measured (the r63 pass row is 0.14 ms over 0.23 ms plain there).
# A ray that meets no card costs the candidate loop's first Proceed. Memory: none (two specialization
# constants, six counters in the existing 64-byte buffer). No CPU cost per frame.
#
# Files: point_shadow_ray.comp, rt_cards.glsl, rt_card_layers_layout.h, vk_point_shadow.cpp, README.md.
# No CMakeLists change (the includes are listed already), no new file.
#
# Not compiled here (no clang++): the C++ spots a compiler could reject are named in the hand-off; both
# shaders were compiled with glslangValidator -V --target-env vulkan1.2 and checked with spirv-val.
#
# Use: python -I -X utf8 r62g_cutout-shadows-visible.py check | apply | revert
# Root: R62G_CUTOUT_SHADOWS_VISIBLE_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs
# the originals up in r62g_backup next to this script. Every edit replaces an anchor that it keeps (an
# insert) or one line that it swaps (rt_cards.glsl's CardRay constructor, the specialization lines); each
# anchor must be found exactly once. revert takes each inserted text out where it is (found by itself,
# exactly once), so a patch applied later that put its own text next to this one's stays.
import os, sys

ROOT = os.environ.get("R62G_CUTOUT_SHADOWS_VISIBLE_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r62g_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
S = HS + "point_shadow_ray.comp"
G = HS + "rt_cards.glsl"
L = HS + "rt_card_layers_layout.h"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
R = "README.md"

# (old, new): `old` is found once; `new` replaces it (an insert keeps `old` inside `new`).
EDITS = {
S: [
# --- the header block of the CARDS builds: the constants and the globals
("bool ray_card_kept = false;\n",
 r"""bool ray_card_kept = false;
// bbport (r62g_cutout-shadows-visible): the cut-out shadows' own disc. A card is tested on a ray to a
// point of a disc of at most CARD_DISC metres around the lamp (specialization constant 1,
// BB_RT_CARD_LAMP_RADIUS, vk_point_shadow.cpp MakeCardBuild; 0.5 or more: the lamp's own disc, as before
// r62g), the solid geometry on the ray to the point of the lamp's disc as before. card_sharp: this ray()
// is both (set by lampVisibility: the lamp's disc is larger than CARD_DISC); card_target: the card
// ray's target; card_only_sum: the rays of this invocation that only a card blocked (view 7 with
// CARD_VIEW_SHARE, specialization constant 2, BB_RT_CARD_LAMP_SHARE_VIEW=1, paints their share).
layout(constant_id = 1) const float CARD_DISC = 0.02;
layout(constant_id = 2) const uint CARD_VIEW_SHARE = 0u;
vec3 card_target = vec3(0.0);
bool card_sharp = false;
float card_only_sum = 0.0;
"""),
# --- cardNote: the layer reads' counters
("        atomicAdd(card_counts[CARD_LAMP_HOW + hit.how], 1u);\n",
 """        atomicAdd(card_counts[CARD_LAMP_HOW + hit.how], 1u);
        atomicAdd(card_counts[CARD_LAMP_LOD_READS], hit.lod_reads); // bbport (r62g_cutout-shadows-visible)
        atomicAdd(card_counts[CARD_LAMP_ZERO_READS], hit.zero_reads);
        atomicAdd(card_counts[CARD_LAMP_PARTIAL_READS], hit.partial_reads);
"""),
# --- cardCount: one counter's add, on the same pixels and passes as cardNote
("            atomicAdd(card_counts[CARD_LAMP_BLIND], 1u);\n        }\n    }\n}\n",
 r"""            atomicAdd(card_counts[CARD_LAMP_BLIND], 1u);
        }
    }
}

// bbport (r62g_cutout-shadows-visible): one counter's add on the passes and pixels cardNote counts.
void cardCount(uint index, uint n) {
    if ((mode & MODE_CARD_COUNT) != 0u && ((gl_GlobalInvocationID.x | gl_GlobalInvocationID.y) & 7u) == 0u) {
        atomicAdd(card_counts[index], n);
    }
}
"""),
# --- ray(): the two rays
("    const float width0 = length(origin) * cardPixelAngle() * pixels;\n",
 r"""    const float width0 = length(origin) * cardPixelAngle() * pixels;
    if (card_sharp) {
        // bbport (r62g_cutout-shadows-visible): the solid geometry first, on this ray to the point of the
        // lamp's disc, as the builds without cards cast it (mask 0x04, opaque: no card has the bit); then,
        // for a ray that is free, the cut-out cards (mask CARD_LAMP_MASK) on the ray to card_target, a
        // point of a disc of CARD_DISC metres. A leaf's shadow is sharp, the solid shadows stay soft. The
        // ray stops at its first confirmed card, as cardTraceShadow's rays do. cardNote counts every ray
        // once, as in the combined ray; a ray the solid geometry blocked met no card (seen 0).
        rayQueryEXT solid;
        rayQueryInitializeEXT(solid, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT, 0x04u,
                              origin, reach * 0.5, ray_to / ray_len, tmax);
        rayQueryProceedEXT(solid);
        ray_card_kept = false;
        if (rayQueryGetIntersectionTypeEXT(solid, true) != gl_RayQueryCommittedIntersectionNoneEXT) {
            cardNote(CardRay(-1.0, CARD_RAY_OPAQUE, 0u, 0u, 0u, 0u, 0u, 0u));
            cardCount(CARD_LAMP_SOLID_FIRST, 1u);
            ray_went = rayQueryGetIntersectionTEXT(solid, true);
            ray_left = ray_len - ray_went;
            return ray_went / ray_len;
        }
        const vec3 card_to = card_target - origin;
        const float card_len = length(card_to);
        const float card_tmax = card_len - (ray_clear > 0.0 ? ray_clear : t_clear);
        if (!(card_tmax > reach)) {
            cardNote(CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u, 0u, 0u, 0u));
            return -1.0;
        }
        cardCount(CARD_LAMP_SHARP_RAYS, 1u);
        const CardRay card_hit = cardTraceShadow(scene, gl_RayFlagsTerminateOnFirstHitEXT, CARD_LAMP_MASK, origin,
                                                 reach * 0.5, card_to / card_len, card_tmax, t_card_cap, width0,
                                                 -width0 / card_len);
        cardNote(card_hit);
        ray_card_kept = card_hit.how == CARD_RAY_KEPT;
        if (card_hit.t < 0.0) {
            return -1.0;
        }
        card_only_sum += 1.0;
        cardCount(CARD_LAMP_CARD_ONLY, 1u);
        ray_went = card_hit.t;
        ray_left = card_len - ray_went;
        return ray_went / card_len;
    }
"""),
# --- ray(): the combined ray's card-only count (the share view)
("    ray_card_kept = hit.how == CARD_RAY_KEPT;\n",
 """    ray_card_kept = hit.how == CARD_RAY_KEPT;
    // bbport (r62g_cutout-shadows-visible): the share view and the counter (here a kept texel stopped the
    // ray; whether solid geometry lies behind it is not asked)
    card_only_sum += ray_card_kept ? 1.0 : 0.0;
    cardCount(CARD_LAMP_CARD_ONLY, ray_card_kept ? 1u : 0u);
"""),
# --- lampVisibility: the card ray's target
("    return ray(from, reach, target) < 0.0 ? 1.0 : 0.0;\n",
 r"""#ifdef CARDS
    // bbport (r62g_cutout-shadows-visible): where the lamp's disc is larger than CARD_DISC (0.5 or more:
    // never) ray() traces the cards on a ray to the point of the same disc shrunk to CARD_DISC around the
    // lamp's centre (the offset of the ray's own point, lifted off the surface as it is, times
    // CARD_DISC / radius). radius is this call's (the halo's and the flame's included), so the card
    // ray's point lies within CARD_DISC of the centre, whatever shape the disc has.
    card_sharp = radius > CARD_DISC && CARD_DISC < 0.5;
    card_target = L + (target - L) * (card_sharp ? CARD_DISC / radius : 1.0);
#endif
    return ray(from, reach, target) < 0.0 ? 1.0 : 0.0;
"""),
# --- the test view
("        if (t_view == 7u && card_what != 0u) {\n",
 r"""        // bbport (r62g_cutout-shadows-visible): BB_RT_CARD_LAMP_SHARE_VIEW=1: 7 paints, per pixel, the share
        // of the rays it cast this frame that only a leaf texel blocked (the solid geometry did not): black
        // 0, red, yellow, white 1, over a dim copy of the shadow ratio. (A pixel that took its block's
        // answer cast no ray: it shows the ratio alone. Without the knob 7 is the colours below.)
        if (t_view == 7u && CARD_VIEW_SHARE != 0u) {
            const float card_share = clamp(card_only_sum / float(max(rays_cast, 1u)), 0.0, 1.0);
            shown = vec3(0.1 * answer) + vec3(min(card_share * 2.0, 1.0), clamp(card_share * 2.0 - 1.0, 0.0, 1.0),
                                              clamp(card_share * 4.0 - 3.0, 0.0, 1.0));
        } else
        if (t_view == 7u && card_what != 0u) {
"""),
],
G: [
("    uint no_data; // of them, without data (passed)\n",
 """    uint no_data; // of them, without data (passed)
    uint lod_reads;     // bbport (r62g_cutout-shadows-visible): of the tested, read at a level above 0
    uint zero_reads;    // of the tested, texels whose alpha was 0
    uint partial_reads; // of the tested, texels with an alpha above 0 that the rule dropped
"""),
("    CardRay r = CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u);\n",
 "    CardRay r = CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u, 0u, 0u, 0u); // (r62g: three more counts)\n"),
("            ++r.tested;\n",
 """            ++r.tested;
            r.lod_reads += lod > 0.0 ? 1u : 0u; // bbport (r62g_cutout-shadows-visible)
            r.zero_reads += c.alpha <= 0.0 ? 1u : 0u;
            r.partial_reads += c.status != CARD_KEPT && c.alpha > 0.0 ? 1u : 0u;
"""),
],
L: [
("#define CARD_LAMP_BLIND 9\n",
 """#define CARD_LAMP_BLIND 9
// bbport (r62g_cutout-shadows-visible): six more counters of the same 16: of the layer reads, those at a
// level above 0, those on a texel of alpha 0, those on a texel with an alpha above 0 that the card's rule
// dropped (the rest were kept); the rays cast to the card disc (BB_RT_CARD_LAMP_RADIUS), those only a
// card blocked, and the rays the solid ray blocked first (no card ray was cast).
#define CARD_LAMP_LOD_READS 10
#define CARD_LAMP_ZERO_READS 11
#define CARD_LAMP_PARTIAL_READS 12
#define CARD_LAMP_SHARP_RAYS 13
#define CARD_LAMP_CARD_ONLY 14
#define CARD_LAMP_SOLID_FIRST 15
"""),
],
C: [
("static_assert(CARD_LAMP_COUNTERS == 16);\n",
 """static_assert(CARD_LAMP_COUNTERS == 16);
// bbport (r62g_cutout-shadows-visible): the counters it adds (rt_card_layers_layout.h) lie in the 16
static_assert(CARD_LAMP_BLIND < CARD_LAMP_LOD_READS && CARD_LAMP_LOD_READS < CARD_LAMP_ZERO_READS &&
              CARD_LAMP_ZERO_READS < CARD_LAMP_PARTIAL_READS && CARD_LAMP_PARTIAL_READS < CARD_LAMP_SHARP_RAYS &&
              CARD_LAMP_SHARP_RAYS < CARD_LAMP_CARD_ONLY && CARD_LAMP_CARD_ONLY < CARD_LAMP_SOLID_FIRST &&
              CARD_LAMP_SOLID_FIRST < CARD_LAMP_COUNTERS);
"""),
("// bbport (r63_leaf-stage4): a CARDS build: set 0 as EffectPass::Create makes it for the build\n",
 r"""// bbport (r62g_cutout-shadows-visible): the CARDS builds' specialization constants 1 and 2
// (point_shadow_ray.comp CARD_DISC, CARD_VIEW_SHARE), read once from the environment, and only by the code
// that makes a CARDS build (BB_RT_CARD_LAMPS=1). BB_RT_CARD_LAMP_RADIUS: metres, 0 to 0.5, default 0.02 (a
// value that is not a number: the default); 0.5: the cards are tested on the lamp's own disc, as before.
// BB_RT_CARD_LAMP_SHARE_VIEW=1: BB_LAMP_SHADOW_VIEW=7 paints the share of rays a card alone blocked.
struct CardExtras {
    float disc_m;
    bool share_view;
};
CardExtras CardExtrasFromEnv() {
    static const CardExtras extras = [] {
        CardExtras e{0.02f, false};
        if (const char* const text = std::getenv("BB_RT_CARD_LAMP_RADIUS")) {
            char* end = nullptr;
            const float value = std::strtof(text, &end);
            if (end != text && std::isfinite(value)) {
                e.disc_m = std::clamp(value, 0.0f, 0.5f);
            }
        }
        const char* const share = std::getenv("BB_RT_CARD_LAMP_SHARE_VIEW");
        e.share_view = share && share[0] == '1';
        return e;
    }();
    return extras;
}

// bbport (r63_leaf-stage4): a CARDS build: set 0 as EffectPass::Create makes it for the build
"""),
("    const vk::SpecializationMapEntry scale_entry{0, 0, sizeof(float)};\n"
 "    const vk::SpecializationInfo spec{1, &scale_entry, sizeof(float), &texel_scale};\n",
 """    // bbport (r62g_cutout-shadows-visible): constant 0 the texel scale, 1 CARD_DISC (m), 2 CARD_VIEW_SHARE
    const CardExtras extras = CardExtrasFromEnv();
    const std::array<u32, 3> spec_words{std::bit_cast<u32>(texel_scale), std::bit_cast<u32>(extras.disc_m),
                                        extras.share_view ? 1u : 0u};
    const std::array<vk::SpecializationMapEntry, 3> spec_entries{{{0, 0, 4}, {1, 4, 4}, {2, 8, 4}}};
    const vk::SpecializationInfo spec{u32(spec_entries.size()), spec_entries.data(), sizeof(spec_words),
                                      spec_words.data()};
"""),
("                    CardRayCap(card_cap_bits), double(card_texel_scale * float(CARD_RAY_TEXELS_PER_M)));\n",
 r"""                    CardRayCap(card_cap_bits), double(card_texel_scale * float(CARD_RAY_TEXELS_PER_M)));
        {
            const CardExtras extras = CardExtrasFromEnv();
            std::printf("Ray traced lamps (r62g): cut-out shadows visible: a lamp whose disc is larger than %.3f m "
                        "(BB_RT_CARD_LAMP_RADIUS, 0 to 0.5, 0.5 = the lamp's own disc as in r63) casts its cut-outs' "
                        "shadows with a disc of that radius: a second ray, to the cards only, for each lit lamp ray, "
                        "while the solid geometry keeps the lamp's disc; BB_LAMP_SHADOW_VIEW=7 %s\n",
                        double(extras.disc_m),
                        extras.share_view ? "paints the share of rays a leaf texel alone blocked (BB_RT_CARD_LAMP_SHARE_VIEW=1)"
                                          : "shows where the rays met cards (BB_RT_CARD_LAMP_SHARE_VIEW=1: the share a card alone blocked)");
        }
"""),
("                card_rays > 0.0 ? d[CARD_LAMP_NO_DATA] / card_rays : 0.0, now[CARD_LAMP_MOST]);\n",
 r"""                card_rays > 0.0 ? d[CARD_LAMP_NO_DATA] / card_rays : 0.0, now[CARD_LAMP_MOST]);
    {
        // bbport (r62g_cutout-shadows-visible): what the layer reads were and what the card rays did, the
        // numbers first (a slot run keeps 300 characters of a line)
        const CardExtras extras = CardExtrasFromEnv();
        const double reads = d[CARD_LAMP_TESTED];
        const double kept_reads = std::max(reads - d[CARD_LAMP_ZERO_READS] - d[CARD_LAMP_PARTIAL_READS], 0.0);
        std::printf("Ray traced lamps (r62g): %.0f counted rays, %.1f %% blocked by a card alone, %.1f %% by solid "
                    "geometry before a card ray was cast, %.0f card rays cast (%.1f %%); of %.0f layer reads %.1f %% "
                    "at a level above 0, %.1f %% on a texel of alpha 0, %.1f %% on a partly covered texel the rule "
                    "dropped, %.1f %% kept; card disc %.3f m (BB_RT_CARD_LAMP_RADIUS, 0.5 = the lamp's own)\n",
                    d[CARD_LAMP_RAYS], share(d[CARD_LAMP_CARD_ONLY], d[CARD_LAMP_RAYS]),
                    share(d[CARD_LAMP_SOLID_FIRST], d[CARD_LAMP_RAYS]), d[CARD_LAMP_SHARP_RAYS],
                    share(d[CARD_LAMP_SHARP_RAYS], d[CARD_LAMP_RAYS]), reads, share(d[CARD_LAMP_LOD_READS], reads),
                    share(d[CARD_LAMP_ZERO_READS], reads), share(d[CARD_LAMP_PARTIAL_READS], reads),
                    share(kept_reads, reads), double(extras.disc_m));
    }
"""),
],
}

ROW = (
    "| `BB_RT_CARD_LAMP_RADIUS`, `BB_RT_CARD_LAMP_SHARE_VIEW` | Cut-out shadows made readable; only with "
    "`BB_RT_CARD_ALPHA=2` and `BB_RT_CARD_LAMPS=1`. A lamp is a disc (`graphics_lamp_shadow_softness`, "
    "`BB_LAMP_SHADOW_SOFT`), and the shadow of a thin blade or a small leaf on a surface behind it is a "
    "penumbra wider than the blade: a 1 cm blade 0.5 m from a lamp of radius 0.1 m, the surface 0.3 m behind "
    "the blade, blocks at most 17 % of the lamp's disc (penumbra 12 cm), with a disc of radius 0.02 m 78 % "
    "(2.4 cm). `BB_RT_CARD_LAMP_RADIUS` (metres, 0 to 0.5): where a lamp's disc is larger, a lamp ray is two "
    "rays: the solid geometry on the ray to a point of the lamp's disc, as before (its shadows stay as soft "
    "as the setting makes them), and, if that one is free, the cut-out cards on a ray to a point of the same "
    "disc shrunk to this radius. A value that is not a number gives the default; 0.5 gives the lamp's own "
    "disc for the cards, as before. Costs one more ray (cards only) for each lit lamp ray while the scene "
    "holds a card with data (estimate 0.05-0.15 ms at 1080p, not measured). `BB_RT_CARD_LAMP_SHARE_VIEW=1`: "
    "`BB_LAMP_SHADOW_VIEW=7` paints, for each pixel, the share of the rays it cast this frame that only a "
    "leaf texel blocked (black 0, red, yellow, white 1) over a dim copy of the shadow ratio, in place of the "
    "colours of where rays met cards. Both read at start | `0.02`, off |")
ANCHOR_ROW = "| `BB_RT_CARD_ALPHA`, `BB_RT_CARD_LAMPS`, `BB_RT_CARD_SAFE` |"


def readme_edit(text):
    """The README row goes after the BB_RT_CARD_ALPHA row (the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith(ANCHOR_ROW)]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_RT_CARD_ALPHA row is there %d times, wanted 1" % len(lines))
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


# Text checks on the result: the ties a compiler cannot check.
def text_checks(texts):
    s, g, l, c = texts[S], texts[G], texts[L], texts[C]
    for want, n in (("layout(constant_id = 1) const float CARD_DISC = 0.02;", 1),
                    ("layout(constant_id = 2) const uint CARD_VIEW_SHARE = 0u;", 1),
                    ("card_sharp = radius > CARD_DISC && CARD_DISC < 0.5;", 1),
                    ("void cardCount(uint index, uint n) {", 1),
                    ("CardRay(-1.0, CARD_RAY_OPAQUE, 0u, 0u, 0u, 0u, 0u, 0u)", 1),
                    ("CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u, 0u, 0u, 0u)", 1),
                    ("if (t_view == 7u && CARD_VIEW_SHARE != 0u) {", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    if g.count("CardRay(-1.0, CARD_RAY_FREE, 0u, 0u, 0u, 0u, 0u, 0u)") != 1 or g.count("uint lod_reads;") != 1:
        raise SystemExit("text check: rt_cards.glsl: the CardRay struct and its constructor disagree")
    # eight members (t, how, seen, tested, no_data, lod_reads, zero_reads, partial_reads), eight arguments
    start = g.index("struct CardRay {")
    body = g[start:g.index("};", start)]
    n_members = sum(1 for line in body.split("\n")[1:] if line.strip().split("//")[0].strip().endswith(";"))
    if n_members != 8:
        raise SystemExit("text check: CardRay has %d members, the constructors give 8" % n_members)
    # every r62g shader line lies inside #ifdef CARDS (the builds without it keep their SPIR-V)
    stack = []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifdef CARDS")
        elif st.startswith("#endif"):
            stack.pop()
        elif st.startswith("#else"):
            stack[-1] = False
        elif ("r62g" in line or "card_sharp" in line or "card_only_sum" in line or "CARD_DISC" in line or
              "CARD_VIEW_SHARE" in line) and not any(stack):
            raise SystemExit("text check: an r62g shader line is outside #ifdef CARDS: %r" % line)
    for name in ("CARD_LAMP_LOD_READS 10", "CARD_LAMP_ZERO_READS 11", "CARD_LAMP_PARTIAL_READS 12",
                 "CARD_LAMP_SHARP_RAYS 13", "CARD_LAMP_CARD_ONLY 14", "CARD_LAMP_SOLID_FIRST 15"):
        if l.count("#define " + name + "\n") != 1:
            raise SystemExit("text check: %s lacks #define %s" % (L, name))
    if c.count("CardExtras CardExtrasFromEnv()") != 1 or c.count("CardExtrasFromEnv()") != 4:
        raise SystemExit("text check: CardExtrasFromEnv is not used at MakeCardBuild, the once-line and the line")
    if c.index("CardExtras CardExtrasFromEnv()") > c.index("bool MakeCardBuild("):
        raise SystemExit("text check: CardExtrasFromEnv is defined after MakeCardBuild")
    row = [x for x in texts[R].split("\n") if x.startswith("| `BB_RT_CARD_LAMP_RADIUS`")]
    if len(row) != 1 or "17 %" not in row[0] or "78 %" not in row[0]:
        raise SystemExit("text check: README row")
    if not row[0].endswith("| `0.02`, off |"):
        raise SystemExit("text check: README row's default column")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R62G_CUTOUT_SHADOWS_VISIBLE_ROOT)" % ROOT)
    plan = []
    for path in (S, G, L, C, R):
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
            tmp = full + ".r62gtmp"
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
        tmp = full + ".r62gtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
