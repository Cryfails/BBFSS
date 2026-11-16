# r86c_glass-glint-visible. FEATURE fix on top of r86b_glass-visible.fixed.py (which must be applied and
# built; this script edits only files r86b made, plus its README rows). Branch when published:
# visual/glass-water, with r86b. Context: bbfss-ctx-glass-water-caustics.md, section "2026-11-15 r86c".
#
# WHAT WAS WRONG (b23 dream-house log: glass px 8324, lamps 8.0, glint px 0, shadowed 0/0, max add 0.00)
# The pass found the glass (8324 pane pixels, the depth, the camera and the lamps' view space all agree)
# and added nothing, because its lobe was too narrow for the glass that is there:
#  - exponent 256: half the peak at 4.2 degrees of normal, 2 % of it at 10 degrees; a curved bottle
#    (a body of revolution, vertical axis) reflects a lamp only if the lamp lies within about 15 degrees of
#    its horizontal plane (peak per unit lamp colour at 20 degrees up: 0.007, at 30 degrees: 0.00002), and
#    a flat window shows a lamp only at the one point where its mirror image falls; the dream house's
#    lamps sit above the bottles (the shelf lantern 30 to 45 degrees over the lower shelves) or far;
#  - amplitude: Fresnel 0.04 x (n + 8) / 8 times the lamp's colour x falloff^2 x N.L is the lamp's
#    irradiance spread over the lobe, not the lamp's image: a flame's radiance is a thousand times
#    its irradiance / pi, so at the top of the lobe the sum is about the scene's own level (log-mean key
#    0.053) and a lobe that narrow almost never reaches its top.
# The numbers (hand torch at 3.77 m, colour 2.49, reach 8.5 m; r86b: fall 0.31, N.L 0.7, F 0.04, 33): the
# top of the lobe is 2.49 x 0.31 x 0.7 x 0.04 x 33 = 0.71; a lamp 20 degrees off a bottle's horizontal plane
# gives 0.014 (half vector 10 degrees off the normal: 2 % of the top), 30 degrees 0.0001, 40 degrees 0:
# under the 1/255 test that gates the shadow ray. "shadow rays 0" says no pixel of any pane had a lamp
# within about 22 degrees. Read from the numbers and a simulation, NOT proven by a run: the second log
# line (pairs, facing, highest N.H, brightest term) settles it on the next run.
#   Checked and cleared (code reading): lamp positions and the hit points are in one view space (the
# pass's rays and rt_card_view's are the same, and point_shadow_ray.comp traces lamp rays through the
# same TLAS from the same records); lamp radius from word 3 as 1 / sqrt(inverse radius squared), colour
# words 4 to 6, 8 lamps pushed ("lamps 8.0"); the normal from central differences is finite and
# unit; the half vector from a camera at the origin; the 1/255 test is on the brightest term x strength
# (a pixel can only be missed there when every term is tiny: that is the symptom, not a bug); "glint
# px" counts a pixel whose largest added channel is over 0.02, after the lamp colour. The show job's
# "depth-rejected 859771" is the average over the passes of the pixels whose ray meets a pane only
# behind the depth (41 % of the frame: a pane mesh far below and behind the room's floor and walls;
# the picture's blue lower part, its top edge at the horizon): a count a pass, not a frame's sum
# (2 073 600 px at 1080p); only the test view counts it.
#
# WHAT THIS CHANGES
#  1. The lobe: BB_GLASS_GLINT_SHARP defaults to 32 (256 before). At 32 a bottle reflects the torch up to
#     about 45 degrees off its horizontal plane (0.53 at 20 degrees, 0.12 at 40, 0.07 at 45), a sparkle is
#     3 to 4 pixels across.
#  2. A look gain of 8 (GLASS_GLINT_GAIN) on the lamp term: the lamp's image in glass against the irradiance
#     lobe; at the top of the torch's lobe 2.49 x 0.31 x 0.7 x 0.04 x 5 x 8 = 0.86, 16 x the scene key
#     and well over the 0.02 glint level. AddMax 8 still caps a channel; strength 0.25 to 4 scales it.
#  3. The numbers that prove the next run (second log line, per pass): pane points (units), their mean
#     distance, those without a normal, those curved (normals of the pixels before and after the centre
#     differ by more than 2.6 degrees: a bottle, not a flat window: this tells which glass the pair is),
#     lamp x pane pairs inside the lamp's reach and facing it, the lamp-to-pane distance (nearest, mean),
#     the highest N.H, the brightest lamp term before the strength and the 1/255 test, and the lamps as
#     pushed (colour up to, reach from to).
#  4. The cap is asked first and before any other work (a few compares): draws it leaves out no longer
#     pick lamps or read the camera (dark alley: 1942 such draws in 600 frames).
#
# Edits: host_shaders/glass_glint_layout.h (slot 24 words, words 12 to 20, GLASS_GLINT_GAIN),
# host_shaders/glass_glint.comp (counters, Curved, the gain), renderer_vulkan/glass_glint.h (default,
# Gain, Capped, DistMinMetres), vk_glass_glint.h/.cpp (stats, early cap, second line, 6144 bytes),
# tests/test_glass_glint.cpp, README.md (rows). No new file, no hook line anywhere else.
# Off (BB_GLASS_GLINT unset or 0, BB_RT_GLASS off): unchanged from r86b (no GlassGlint is made; every
# hook is a null pointer test); nothing in this script is reached.
#
# Use: python -I -X utf8 r86c_glass-glint-visible.py check | apply | revert. Root from R86C_ROOT, else
# <tree>. Each edit is an exact text (old -> new) found exactly once; "applied" = every new text
# once; "clean" = every old text once, no new text; anything else is refused (exit 1, nothing
# written). Line ends are kept (README CRLF; the glass glint files as r86b wrote them). apply keeps the
# touched files in r86c_backup/ next to this script. Exit: 0 done, 1 refused, 2 usage.
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86c_backup")
ROOT = os.environ.get("R86C_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
RV = V + "renderer_vulkan/"
HS = V + "host_shaders/"
LAYOUT = HS + "glass_glint_layout.h"
SHADER = HS + "glass_glint.comp"
RULES = RV + "glass_glint.h"
PASS_H = RV + "vk_glass_glint.h"
PASS_CPP = RV + "vk_glass_glint.cpp"
TEST = "engine/tests/test_glass_glint.cpp"

EDITS = {
    LAYOUT: [
        (r'''#define GLASS_GLINT_SLOT_WORDS 16u
''', r'''#define GLASS_GLINT_SLOT_WORDS 24u
'''),
        (r'''#define GLASS_GLINT_W_NO_NORMAL 11u
#define GLASS_GLINT_W_COUNT 12u
''', r'''#define GLASS_GLINT_W_NO_NORMAL 11u
// bbport (r86c_glass-glint-visible): the numbers behind the log's second line, a slot's words 12 on.
// Summed, a unit being a pixel or a 2x2 quad: 12 pane points (units) in front of the depth, 13 pane
// point x lamp pairs inside the lamp's reach, 14 of them facing the lamp (N.L above 0), 15 the sum of
// those pairs' distances (cm). The largest (atomicMax): 16 the nearest pair as 0xFFFFFFFF less its
// distance in mm (0: no pair), 17 the brightest lamp term before the strength and the shadow test
// (float bits), 18 the highest N.H of a facing pair (float bits). Summed: 19 pane points whose normal
// from the two units before the centre differs by more than 2.6 degrees from the normal from the two
// after it (curved), 20 the sum of the pane points' distances t (cm, each put into 100 m).
#define GLASS_GLINT_W_UNITS 12u
#define GLASS_GLINT_W_PAIRS 13u
#define GLASS_GLINT_W_FACING 14u
#define GLASS_GLINT_W_DIST_SUM 15u
#define GLASS_GLINT_W_DIST_MIN 16u
#define GLASS_GLINT_W_BEST_MAX 17u
#define GLASS_GLINT_W_NH_MAX 18u
#define GLASS_GLINT_W_CURVED 19u
#define GLASS_GLINT_W_T_SUM 20u
#define GLASS_GLINT_W_COUNT 21u
'''),
        (r'''#define GLASS_GLINT_F0 0.04
''', r'''#define GLASS_GLINT_F0 0.04
// bbport (r86c_glass-glint-visible): the look gain on a lamp's term. The Blinn-Phong lobe spreads the
// lamp's irradiance (the game's units); the lamp's image in glass is its radiance, a thousand times
// that over pi, so the lobe's top is about the scene's own level (log-mean key 0.05) and a glint that
// small does not show. At 32 the torch of the dream house (3.77 m, colour 2.49, reach 8.5 m) gives
// 0.86 at the top of the lobe.
#define GLASS_GLINT_GAIN 8.0
'''),
    ],
    SHADER: [
        # thread-private numbers for the log
        (r'''bool Near(vec4 a, vec4 centre) {
''', r'''// bbport (r86c_glass-glint-visible): this thread's numbers for the log (Glint fills them, main
// flushes them into the slot): pane point x lamp pairs inside the lamp's reach and those facing the
// lamp, the sum (cm) and the nearest (0xFFFFFFFF less mm) of the distances, the highest N.H, the
// brightest lamp term before the strength and the shadow test.
uint d_pairs = 0u, d_facing = 0u, d_dist_sum = 0u, d_dist_min = 0u;
float d_nh = 0.0, d_best = 0.0;

bool Near(vec4 a, vec4 centre) {
'''),
        # the curvature test, before Glint
        (r'''// The glint at pane point `p` with normal `n` from the pass's lamps (x strength).
''', r'''// bbport (r86c_glass-glint-visible): is the pane curved at this point: the normal from the two units
// before the centre and the one from the two after it differ by more than 2.6 degrees (a bottle's
// body does at a pixel, a flat window does not). Only where both neighbours of both axes are on the
// same surface. Log only.
bool Curved(uint c, vec4 centre) {
    const vec4 lx = group_hit[c - 1u], hx = group_hit[c + 1u];
    const vec4 ly = group_hit[c - GRID], hy = group_hit[c + GRID];
    if (!(Near(lx, centre) && Near(hx, centre) && Near(ly, centre) && Near(hy, centre))) {
        return false;
    }
    const vec3 a = cross(centre.xyz - lx.xyz, centre.xyz - ly.xyz);
    const vec3 b = cross(hx.xyz - centre.xyz, hy.xyz - centre.xyz);
    const float la = length(a), lb = length(b);
    return la > 1e-12 && lb > 1e-12 && dot(a, b) < 0.999 * la * lb;
}

// The glint at pane point `p` with normal `n` from the pass's lamps (x strength).
'''),
        # pairs, facing, distances, N.H
        (r'''        const vec3 l = to / d;
        const float nl = dot(n, l);
        if (!(nl > 0.0)) {
            continue;
        }
        const vec3 h = normalize(l + v);
        const float nh = max(dot(n, h), 0.0);
''', r'''        const vec3 l = to / d;
        ++d_pairs; // bbport (r86c_glass-glint-visible): the numbers of the log's second line
        d_dist_sum += uint(d * 100.0);
        d_dist_min = max(d_dist_min, 0xFFFFFFFFu - uint(d * 1000.0));
        const float nl = dot(n, l);
        if (!(nl > 0.0)) {
            continue;
        }
        ++d_facing;
        const vec3 h = normalize(l + v);
        const float nh = max(dot(n, h), 0.0);
        d_nh = max(d_nh, nh);
'''),
        # the gain and the brightest term
        (r'''        const vec3 term = group_lamp[2u * k + 1u].rgb *
                          (fall * fall * nl * fresnel * pc.params.z * pow(nh, pc.params.y));
        sum += term;
        const float m = max(term.r, max(term.g, term.b));
''', r'''        const vec3 term = group_lamp[2u * k + 1u].rgb *
                          (fall * fall * nl * fresnel * pc.params.z * float(GLASS_GLINT_GAIN) *
                           pow(nh, pc.params.y));
        sum += term;
        const float m = max(term.r, max(term.g, term.b));
        d_best = max(d_best, m); // bbport (r86c_glass-glint-visible)
'''),
        # per unit: units, t, curved
        (r'''    uint glass = 0u, rejected = 0u, glints = 0u, shadow_rays = 0u, shadowed = 0u, no_normal = 0u;
''', r'''    uint glass = 0u, rejected = 0u, glints = 0u, shadow_rays = 0u, shadowed = 0u, no_normal = 0u;
    uint units = 0u, curved = 0u, t_sum = 0u; // bbport (r86c_glass-glint-visible)
'''),
        (r'''            vec3 n;
            if (GridNormal(c, hit, n)) {
                add = Glint(hit.xyz, n, lamp_count, shadow_rays, shadowed);
            } else {
                ++no_normal;
            }
''', r'''            vec3 n;
            units = 1u; // bbport (r86c_glass-glint-visible): the log's second line
            t_sum = uint(min(hit.w, 100.0) * 100.0);
            if (GridNormal(c, hit, n)) {
                add = Glint(hit.xyz, n, lamp_count, shadow_rays, shadowed);
                if (Curved(c, hit)) {
                    ++curved;
                }
            } else {
                ++no_normal;
            }
'''),
        # thread -> group
        (r'''    if (max_add > 0.0) {
        atomicMax(group_count[GLASS_GLINT_W_MAX_ADD], floatBitsToUint(max_add));
    }
''', r'''    if (max_add > 0.0) {
        atomicMax(group_count[GLASS_GLINT_W_MAX_ADD], floatBitsToUint(max_add));
    }
    // bbport (r86c_glass-glint-visible): the log's second line
    if (units != 0u) {
        atomicAdd(group_count[GLASS_GLINT_W_UNITS], units);
        atomicAdd(group_count[GLASS_GLINT_W_T_SUM], t_sum);
    }
    if (curved != 0u) {
        atomicAdd(group_count[GLASS_GLINT_W_CURVED], curved);
    }
    if (d_pairs != 0u) {
        atomicAdd(group_count[GLASS_GLINT_W_PAIRS], d_pairs);
        atomicAdd(group_count[GLASS_GLINT_W_DIST_SUM], d_dist_sum);
        atomicMax(group_count[GLASS_GLINT_W_DIST_MIN], d_dist_min);
    }
    if (d_facing != 0u) {
        atomicAdd(group_count[GLASS_GLINT_W_FACING], d_facing);
        atomicMax(group_count[GLASS_GLINT_W_NH_MAX], floatBitsToUint(d_nh));
    }
    if (d_best > 0.0) {
        atomicMax(group_count[GLASS_GLINT_W_BEST_MAX], floatBitsToUint(d_best));
    }
'''),
        # group -> slot
        (r'''        if (group_count[GLASS_GLINT_W_MAX_ADD] != 0u) {
            atomicMax(counters[base + GLASS_GLINT_W_MAX_ADD], group_count[GLASS_GLINT_W_MAX_ADD]);
        }
''', r'''        if (group_count[GLASS_GLINT_W_MAX_ADD] != 0u) {
            atomicMax(counters[base + GLASS_GLINT_W_MAX_ADD], group_count[GLASS_GLINT_W_MAX_ADD]);
        }
        // bbport (r86c_glass-glint-visible): the log's second line (sums, then the largest)
        for (uint w = GLASS_GLINT_W_UNITS; w <= GLASS_GLINT_W_DIST_SUM; ++w) {
            if (group_count[w] != 0u) {
                atomicAdd(counters[base + w], group_count[w]);
            }
        }
        for (uint w = GLASS_GLINT_W_DIST_MIN; w <= GLASS_GLINT_W_NH_MAX; ++w) {
            if (group_count[w] != 0u) {
                atomicMax(counters[base + w], group_count[w]);
            }
        }
        for (uint w = GLASS_GLINT_W_CURVED; w <= GLASS_GLINT_W_T_SUM; ++w) {
            if (group_count[w] != 0u) {
                atomicAdd(counters[base + w], group_count[w]);
            }
        }
'''),
    ],
    RULES: [
        (r'''(default 256; other
''', r'''(default 32, 256 before r86c; other
'''),
        (r'''//    MaxPasses passes ran this frame and none on this depth (else "cap").
''', r'''//    MaxPasses passes ran this frame and none on this depth (else "cap"; r86c asks the cap first,
//    before any other work, so a draw it leaves out costs a few compares).
'''),
        (r'''inline constexpr std::uint32_t SharpDefault = 256, SharpMin = 16, SharpMax = 4096;
''', r'''inline constexpr std::uint32_t SharpDefault = 32, SharpMin = 16, SharpMax = 4096;
'''),
        (r'''inline constexpr float F0 = float(GLASS_GLINT_F0), AddMax = float(GLASS_GLINT_ADD_MAX);
''', r'''inline constexpr float F0 = float(GLASS_GLINT_F0), AddMax = float(GLASS_GLINT_ADD_MAX);
inline constexpr float Gain = float(GLASS_GLINT_GAIN); // bbport (r86c_glass-glint-visible)
'''),
        (r'''static_assert(CounterWords <= SlotWords && GLASS_GLINT_W_MAX_ADD < CounterWords &&
              GLASS_GLINT_W_NO_NORMAL < CounterWords);
''', r'''static_assert(CounterWords <= SlotWords && GLASS_GLINT_W_MAX_ADD < CounterWords &&
              GLASS_GLINT_W_NO_NORMAL < CounterWords);
// bbport (r86c_glass-glint-visible): the shader flushes 12 to 15 with atomicAdd, 16 to 18 with
// atomicMax, 19 and 20 with atomicAdd
static_assert(GLASS_GLINT_W_NO_NORMAL + 1 == GLASS_GLINT_W_UNITS &&
                  GLASS_GLINT_W_DIST_SUM + 1 == GLASS_GLINT_W_DIST_MIN &&
                  GLASS_GLINT_W_NH_MAX + 1 == GLASS_GLINT_W_CURVED &&
                  GLASS_GLINT_W_T_SUM + 1 == GLASS_GLINT_W_COUNT && GLASS_GLINT_W_NH_MAX > GLASS_GLINT_W_BEST_MAX &&
                  GLASS_GLINT_W_BEST_MAX > GLASS_GLINT_W_DIST_MIN);
'''),
        (r'''    return fall * fall * nl * Fresnel(vh) * Normalisation(n) * std::pow(std::max(nh, 0.0f), n);
''', r'''    return fall * fall * nl * Fresnel(vh) * Normalisation(n) * Gain * std::pow(std::max(nh, 0.0f), n);
'''),
        (r'''constexpr std::uint32_t GroupsOf(std::uint32_t units) {
    return (units + Group - 1) / Group;
}
''', r'''constexpr std::uint32_t GroupsOf(std::uint32_t units) {
    return (units + Group - 1) / Group;
}

/// bbport (r86c_glass-glint-visible): the nearest lamp-to-pane distance of a pass in metres from its
/// counter word (0xFFFFFFFF less the distance in mm; 0: no pair, -1).
constexpr float DistMinMetres(std::uint32_t stored) {
    return stored == 0 ? -1.0f : float(0xFFFFFFFFu - stored) * 0.001f;
}
'''),
        (r'''constexpr Skip Decide(const Gate& g) {
    return (!g.panes || !g.this_frame)             ? Skip::NoPane
           : !g.same_camera                        ? Skip::OtherCamera
           : !g.lamps                              ? Skip::NoLamps
           : g.lamps_open                          ? Skip::LampsOpen
           : !g.shape                              ? Skip::Shape
           : (g.passes >= MaxPasses || g.depth_done) ? Skip::Cap
                                                     : Skip::None;
}
''', r'''/// bbport (r86c_glass-glint-visible): the cap, asked first and before any other work: MaxPasses
/// passes ran this frame, or one ran on this depth.
constexpr bool Capped(std::uint32_t passes, bool depth_done) {
    return passes >= MaxPasses || depth_done;
}

constexpr Skip Decide(const Gate& g) {
    return Capped(g.passes, g.depth_done)       ? Skip::Cap
           : (!g.panes || !g.this_frame)        ? Skip::NoPane
           : !g.same_camera                     ? Skip::OtherCamera
           : !g.lamps                           ? Skip::NoLamps
           : g.lamps_open                       ? Skip::LampsOpen
           : !g.shape                           ? Skip::Shape
                                                : Skip::None;
}
'''),
    ],
    PASS_H: [
        (r'''a 5.5 KB host
''', r'''a 6 KB host
'''),
        (r'''        std::array<u64, ::BbGlassGlint::CounterWords> words{};
        float max_add = 0.0f;
''', r'''        std::array<u64, ::BbGlassGlint::CounterWords> words{};
        float max_add = 0.0f;
        // bbport (r86c_glass-glint-visible): the log's second line: the largest over the passes read
        // (the brightest term, the highest N.H, the nearest distance as the shader stores it) and
        // the lamps as pushed
        float best_max = 0.0f, nh_max = 0.0f;
        u32 dist_stored = 0;
        float lamp_colour_max = 0.0f, reach_min = 0.0f, reach_max = 0.0f;
'''),
    ],
    PASS_CPP: [
        (r'''static_assert(BufferBytes == 5632);
''', r'''static_assert(BufferBytes == 6144); // 16 x 24 + 16 x 72 words
'''),
        (r'''    ++stats.glass_draws;
    // The gate, in glass_glint.h's order (Decide names the first reason that holds).
''', r'''    ++stats.glass_draws;
    // bbport (r86c_glass-glint-visible): the cap first, before the camera, the lamps or any image
    // lookup: a draw it leaves out costs a few compares (Decide asks it first too).
    const bool depth_done = std::find(frame_depths.begin(), frame_depths.begin() + frame_passes,
                                      depth_id) != frame_depths.begin() + frame_passes;
    if (BG::Capped(frame_passes, depth_done)) {
        ++stats.cap;
        return;
    }
    // The gate, in glass_glint.h's order (Decide names the first reason that holds).
'''),
        (r'''    gate.depth_done = std::find(frame_depths.begin(), frame_depths.begin() + frame_passes,
                                depth_id) != frame_depths.begin() + frame_passes;
''', r'''    gate.depth_done = depth_done; // false here: a capped draw returned above
'''),
        (r'''    stats.lamps += picked.count;
''', r'''    stats.lamps += picked.count;
    for (u32 k = 0; k < picked.count; ++k) { // bbport (r86c_glass-glint-visible): the lamps as pushed
        const BG::Lamp& lamp = picked.lamps[k];
        stats.lamp_colour_max =
            std::max(stats.lamp_colour_max, std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]}));
        stats.reach_min = stats.reach_min > 0.0f ? std::min(stats.reach_min, lamp.reach) : lamp.reach;
        stats.reach_max = std::max(stats.reach_max, lamp.reach);
    }
'''),
        (r'''            if (i == GLASS_GLINT_W_MAX_ADD) {
                stats.max_add = std::max(stats.max_add, std::bit_cast<float>(done[i]));
            } else {
''', r'''            if (i == GLASS_GLINT_W_MAX_ADD) {
                stats.max_add = std::max(stats.max_add, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_BEST_MAX) { // bbport (r86c_glass-glint-visible)
                stats.best_max = std::max(stats.best_max, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_NH_MAX) {
                stats.nh_max = std::max(stats.nh_max, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_DIST_MIN) {
                stats.dist_stored = std::max(stats.dist_stored, done[i]);
            } else {
'''),
        (r'''        double(stats.max_add), double(stats.lamps) / std::max(1.0, double(stats.passes)));
    stats = {};
''', r'''        double(stats.max_add), double(stats.lamps) / std::max(1.0, double(stats.passes)));
    // bbport (r86c_glass-glint-visible): the second line: what the glass is and how far the lamps are
    const double units = std::max(1.0, double(stats.words[GLASS_GLINT_W_UNITS]));
    const double pairs = std::max(1.0, double(stats.words[GLASS_GLINT_W_PAIRS]));
    char nearest[16] = "-";
    if (const float metres = BG::DistMinMetres(stats.dist_stored); metres >= 0.0f) {
        std::snprintf(nearest, sizeof(nearest), "%.2f", double(metres));
    }
    BbReport::Printf(
        "Ray tracing glass glint (r86c): a pass: pane points %.0f (%.2f m away, %.0f without a "
        "normal, %.0f curved); lamp pairs in reach %.0f, facing %.0f, lamp-to-pane distance min %s m "
        "mean %.2f m, highest N.H %.3f, brightest term %.4f (before the strength and the 1/255 "
        "shadow test); lamps as pushed: colour up to %.2f, reach %.1f to %.1f m\n",
        per(GLASS_GLINT_W_UNITS), double(stats.words[GLASS_GLINT_W_T_SUM]) / units * 0.01,
        per(GLASS_GLINT_W_NO_NORMAL), per(GLASS_GLINT_W_CURVED), per(GLASS_GLINT_W_PAIRS),
        per(GLASS_GLINT_W_FACING), nearest,
        double(stats.words[GLASS_GLINT_W_DIST_SUM]) / pairs * 0.01, double(stats.nh_max),
        double(stats.best_max), double(stats.lamp_colour_max), double(stats.reach_min),
        double(stats.reach_max));
    stats = {};
'''),
    ],
    TEST: [
        (r'''    assert(Parse("1", nullptr).sharp == SharpDefault && SharpDefault == 256);
    assert(Parse("1", "").sharp == 256 && !Parse("1", "").sharp_unreadable);
''', r'''    assert(Parse("1", nullptr).sharp == SharpDefault && SharpDefault == 32);
    assert(Parse("1", "").sharp == 32 && !Parse("1", "").sharp_unreadable);
'''),
        (r'''    assert(Parse("1", "soft").sharp == 256 && Parse("1", "soft").sharp_unreadable);
    assert(Parse("1", "64.5").sharp == 256 && Parse("1", "64.5").sharp_unreadable);
''', r'''    assert(Parse("1", "soft").sharp == 32 && Parse("1", "soft").sharp_unreadable);
    assert(Parse("1", "64.5").sharp == 32 && Parse("1", "64.5").sharp_unreadable);
'''),
        (r'''    assert(Near(Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f), 0.25f * 0.04f * Normalisation(256.0f),
                1e-5f));
''', r'''    assert(Near(Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f),
                0.25f * 0.04f * Normalisation(256.0f) * Gain, 1e-5f));
    // r86c: the look gain, and the lobe. A half vector 10 degrees off the normal keeps 2 % of the
    // top at 256 (r86b's default: the glints never showed) and 61 % at 32 (the default now).
    assert(Gain == 8.0f && GLASS_GLINT_GAIN == 8.0);
    {
        const float off = std::cos(0.17453293f);
        const float r256 = Term(0.5f, 1.0f, 1.0f, off, 1.0f, 256.0f) / Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 256.0f);
        const float r32 = Term(0.5f, 1.0f, 1.0f, off, 1.0f, 32.0f) / Term(0.5f, 1.0f, 1.0f, 1.0f, 1.0f, 32.0f);
        assert(r256 > 0.015f && r256 < 0.03f && r32 > 0.55f && r32 < 0.68f);
        // 20 degrees off the half vector (a lamp 40 degrees off the horizontal of a bottle): nothing
        // at 256 (r86b), a visible glint at 32 for the dream house's torch (3.77 m of 8.5 m, colour
        // 2.49, N.L 0.7): the numbers of the README's r86c table.
        const float far_off = std::cos(0.34906585f);
        const float torch = 2.49f * Term(3.77f, 8.5f, 0.7f, far_off, 0.94f, 256.0f);
        const float torch32 = 2.49f * Term(3.77f, 8.5f, 0.7f, far_off, 0.94f, 32.0f);
        assert(torch < ShadowLevel && torch32 > 4.0f * float(GLASS_GLINT_GLINT_LEVEL)); // 0 and 0.118
        // the top of the torch's lobe at 32: 2.49 x 0.31 x 0.7 x 0.04 x 5 x 8 = 0.86
        const float top = 2.49f * Term(3.77f, 8.5f, 0.7f, 1.0f, 1.0f, 32.0f);
        assert(Near(top, 0.865f, 0.02f));
    }
    // the nearest lamp-to-pane distance as the shader stores it
    assert(DistMinMetres(0) == -1.0f && Near(DistMinMetres(0xFFFFFFFFu - 1234u), 1.234f, 1e-5f));
    assert(Capped(MaxPasses, false) && Capped(0, true) && !Capped(MaxPasses - 1, false));
'''),
        (r'''        g.depth_done = true;
        assert(Decide(g) == Skip::Cap);
        g.shape = false;
        assert(Decide(g) == Skip::Shape);
''', r'''        g.depth_done = true;
        assert(Decide(g) == Skip::Cap);
        g.shape = false; // r86c: the cap is asked first
        assert(Decide(g) == Skip::Cap);
        g.depth_done = false;
        assert(Decide(g) == Skip::Shape);
'''),
    ],
    "README.md": [
        (r'''(in the Hunter's Dream house the bottles and jars on the shelves, pair `e30b0480:8a6c7657`)''',
         r'''(in the Hunter's Dream house pair `e30b0480:8a6c7657`: its leaded windows and perhaps the bottles and jars on the shelves; the r86c log's curved count says which: a bottle's pane points are curved, a window's are not)'''),
        (r'''(no pane, camera: another camera or a menu's preview frame, no lamps, lamps open, shape, cap)''',
         r'''(cap, asked first and before any other work: two passes a frame, one a depth; then no pane, camera: another camera or a menu's preview frame, no lamps, lamps open, shape)'''),
        (r'''(n + 8) / 8 (the game's lamp units: its lamp light has no 1/pi), Schlick from 0.04,''',
         r'''(n + 8) / 8 (the game's lamp units: its lamp light has no 1/pi) times a look gain of 8 (a lamp's image in glass is its radiance, far above the lobe of its irradiance; r86c: without it a glint stayed under the scene's own level), Schlick from 0.04,'''),
        (r'''the largest channel added and the lamps. Cost:''',
         r'''the largest channel added and the lamps; then a second line, `Ray tracing glass glint (r86c)`, for a pass: the pane points (a pixel, or a 2x2 quad in the quad mode) and their mean distance, those without a normal and those curved (the normals from the two units before and the two after differ by more than 2.6 degrees: a bottle, not a flat window), the lamp-to-pane pairs inside the lamp's reach and those facing it, the lamp-to-pane distance (nearest, mean), the highest N.H, the brightest lamp term (look gain included, before the strength and the 1/255 shadow test) and the lamps as pushed (their colour up to, their reach from and to). Cost:'''),
        (r'''and 5632 bytes of counters and lamps''', r'''and 6144 bytes of counters and lamps'''),
        (r'''Unset or empty: 256; other text: 256, said once in the log | 256 |''',
         r'''Unset or empty: 32 (256 before r86c, whose lobe was too narrow: a bottle reflected a lamp only within about 15 degrees of its horizontal plane, at 32 within about 45 for the dream house's torch); other text: 32, said once in the log | 32 |'''),
    ],
}


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print("REFUSED %s: missing (r86b not applied?)" % path)
        sys.exit(1)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        print("REFUSED %s: mixed line ends" % path)
        sys.exit(1)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    done = todo = 0
    for old, new in eds:
        no, nn = cur.count(old), cur.count(new)
        if nn == 1 and no == (1 if old in new else 0):
            done += 1
        elif no == 1 and nn == 0:
            todo += 1
        else:
            print("REFUSED %s: old text found %d times, new text %d times: %r" % (path, no, nn, old[:70]))
            sys.exit(1)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    print("REFUSED %s: %d of %d edits applied" % (path, done, len(eds)))
    sys.exit(1)


def text_checks(t):
    """The ties a compiler cannot check, on the texts as they are once applied."""
    layout, shader, rules = t[LAYOUT], t[SHADER], t[RULES]
    cpp, readme, test = t[PASS_CPP], t["README.md"], t[TEST]
    for want in ("#define GLASS_GLINT_SLOT_WORDS 24u\n", "#define GLASS_GLINT_W_COUNT 21u\n",
                 "#define GLASS_GLINT_GAIN 8.0\n", "#define GLASS_GLINT_DATA_WORDS 72u\n",
                 "#define GLASS_GLINT_SLOTS 16u\n", "#define GLASS_GLINT_W_UNITS 12u\n",
                 "#define GLASS_GLINT_W_DIST_MIN 16u\n", "#define GLASS_GLINT_W_T_SUM 20u\n"):
        if layout.count(want) != 1:
            raise SystemExit("text check: glass_glint_layout.h lacks %r" % want)
    # 16 slots x (24 + 72) words x 4 bytes = 6144, the README's and vk_glass_glint.cpp's
    if 16 * (24 + 72) * 4 != 6144 or "static_assert(BufferBytes == 6144);" not in cpp or "6144 bytes" not in readme \
            or "5632" in cpp or "5632 bytes" in readme:
        raise SystemExit("text check: the counters' size is not 6144 bytes in both")
    for want in ("0.25 to 4", "2 cm + 0.2 %", "(n + 8) / 8 (the game's lamp units", "look gain of 8", "1/255", "| 32 |",
                 "Ray tracing glass glint (r86b)", "Ray tracing glass glint (r86c)", "Lighting: glass glint",
                 "above 0.02", "curved"):
        if want not in readme:
            raise SystemExit("text check: README rows lack %r" % want)
    if "SharpDefault = 32, SharpMin = 16, SharpMax = 4096;" not in rules or "| 256 |" in readme:
        raise SystemExit("text check: the exponent's default is not 32 in glass_glint.h and the README")
    if "* Normalisation(n) * Gain *" not in rules or "float(GLASS_GLINT_GAIN) *" not in shader:
        raise SystemExit("text check: the C++ and the shader terms do not both carry the gain")
    # the counters: the shader flushes what the C++ reads
    for name in ("UNITS", "PAIRS", "FACING", "DIST_SUM", "DIST_MIN", "BEST_MAX", "NH_MAX", "CURVED", "T_SUM"):
        if ("GLASS_GLINT_W_" + name) not in shader or ("GLASS_GLINT_W_" + name) not in cpp:
            raise SystemExit("text check: word %s is not in both the shader and the C++" % name)
    for want in ("atomicMax(group_count[GLASS_GLINT_W_DIST_MIN]", "atomicMax(group_count[GLASS_GLINT_W_BEST_MAX]",
                 "atomicMax(group_count[GLASS_GLINT_W_NH_MAX]", "bool Curved(uint c, vec4 centre)"):
        if want not in shader:
            raise SystemExit("text check: glass_glint.comp lacks %r" % want)
    if shader.index("bool Curved(") > shader.index("vec3 Glint("):
        raise SystemExit("text check: Curved must come before Glint")
    if shader.index("uint d_pairs") > shader.index("bool Near("):
        raise SystemExit("text check: the d_ numbers must be declared before their users")
    if "BG::Capped(frame_passes, depth_done)" not in cpp or "constexpr bool Capped(" not in rules:
        raise SystemExit("text check: the early cap is not in both")
    if cpp.index("BG::Capped(frame_passes, depth_done)") > cpp.index("camera_motion.PassMatrices()"):
        raise SystemExit("text check: the cap must be asked before the camera is read")
    for want in ("Ray tracing glass glint (r86c): a pass: pane points",):
        if want not in cpp:
            raise SystemExit("text check: vk_glass_glint.cpp lacks %r" % want)
    if "SharpDefault == 32" not in test or "DistMinMetres" not in test:
        raise SystemExit("text check: the test does not hold the r86c numbers")
    # the Printf of the second line: 13 conversions, 13 arguments
    a = cpp.index("Ray tracing glass glint (r86c): a pass:")
    b = cpp.index("    stats = {};", a)
    block = cpp[a:b]
    fmt_end = block.index('",\n')
    conversions = block[:fmt_end].count("%") - block[:fmt_end].count("%%") * 2
    args = block[fmt_end + 3:]
    n_args = args.count("per(") + args.count("double(") + args.count("nearest")
    if conversions != 13 or n_args != 13:
        raise SystemExit("text check: the second line has %d conversions and %d arguments (want 13 and 13)"
                         % (conversions, n_args))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        print("%s is not a source tree root (set R86C_ROOT)" % ROOT)
        sys.exit(1)
    plan = []
    for path, eds in EDITS.items():
        raw, eol, cur = load(path)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        print("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
        sys.exit(1)
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                print("REFUSED %s: the result does not read as applied" % path)
                sys.exit(1)
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
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        manifest = []
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
            manifest.append("%s %s" % (hashlib.sha256(raw).hexdigest(), path))
        open(os.path.join(BACKUP, "MANIFEST.txt"), "w", encoding="utf-8", newline="\n").write(
            "r86c_glass-glint-visible: the touched files before apply (sha256, path)\n" + "\n".join(manifest) + "\n")
        out = {p[0]: texts[p[0]].replace("\n", p[3]).encode("utf-8") for p in plan}
    else:
        if state != "applied":
            print("nothing to revert")
            return
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in reversed(eds):
                cur = cur.replace(new, old, 1)
            if state_of(cur, eds, path) != "clean":
                print("REFUSED %s: the revert does not read as clean; nothing written" % path)
                sys.exit(1)
            out[path] = cur.replace("\n", eol).encode("utf-8")
    written = []
    try:
        for path in out:
            full = os.path.join(ROOT, path)
            before = open(full, "rb").read()
            tmp = full + ".r86ctmp"
            open(tmp, "wb").write(out[path])
            os.replace(tmp, full)
            written.append((full, before))
    except OSError as err:
        for full, before in reversed(written):
            open(full, "wb").write(before)
        print("REFUSED: write failed (%s); everything written was put back" % err)
        sys.exit(1)
    print("applied" if cmd == "apply" else "reverted")


main()
