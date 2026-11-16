# r107f_caustics-world-anchored: FEATURE follow-up to r107e_caustics-puddles.py (applies ON TOP of r107,
# r107b, r107c, r107d and r107e; branch when published: visual/glass-water). Context:
# bbfss-ctx-glass-water-caustics.md, section "2026-11-16 r107f".
#
# The owner tested build 72 (BB_CAUSTICS=1, BB_CAUSTICS_LAMPS=4) and wrote: "Caustics seem pretty good
# but really only look right when the liquid is rippling", "It seems caustics move with the camera and
# don't just stay in place according to the light source. Shadows get reflected as well from the
# caustics?", "Water looks invisible", "No caustics under water".
#
# Findings (from the code and the b72 log; no run yet):
#  (1) The pattern itself IS world-anchored (Pattern(X.xz) at the point X where the lamp's mirrored
#      path crosses the plane: it depends on the receiver, the lamp and the plane only; its drift is
#      the wind's world velocity). What follows the camera is WHERE the pattern is drawn: a lamp's
#      crossing X counts as water only when the SCREEN shows water there (caustics.comp Water():
#      off the screen, or hidden behind something nearer, count as "unseen": no light). So the
#      light has a hole wherever the hunter, a pillar or the screen's edge hides the water, and the
#      holes move with the camera. The b72 log: "crossings 825063 dry, 1237335 unseen" against
#      32303 lit at the graveyard; 637589 unseen against 742353 lit in the sewer. On puddles
#      (r107e) a crossing must also be a glossy candidate pixel on the plane, in view.
#      Second cause: ChooseLamps ranks the 4 lamps by reach / (reach + distance to the camera), so
#      the chosen set changes as the camera moves.
#  (2) "Shadows": nothing reads a reflected colour. The dark shapes are those holes (the hunter's
#      body hides the water: a hunter-shaped gap in the net) and the lamps' light being added with no
#      lamp shadow (the pass has no per-lamp visibility). The first is fixed here; the second is
#      not (no ray query in this pass; named in the README).
#  (3) "Water invisible": not caused by r107*: the pass never touches a water pixel (receivers are
#      0.03 m or more above the plane), the glass pairs (BB_RT_GLASS) are the vs c6cdba2b / e30b0480
#      draws, not the water's 9253a878:e3021062, and the sewer's water is as dark in the b4 pictures
#      made before any caustics (slot_p4_sewerwater_level.jpg). The sewer water draws opaque and dark
#      and shows no mirror image of the wall lantern. Job r107f-sw0 shows it at the owner's place
#      with BB_CAUSTICS_LAMPS only; compare with that old picture.
#  (4) "No caustics under water": r107 lights only receivers ABOVE the plane. This adds the light of
#      the lamps on the water's bed (below).
#
# What BB_CAUSTICS_WORLD=<n> (needs BB_CAUSTICS_LAMPS; n above 0, up to 4; 1 is the normal value) does:
#  - A world map of what the water is: 256 x 256 cells of 0.25 m (wrapped: 64 m), one word each, in a
#    new device-local buffer of 256 KB (binding 7). Every up-facing pixel on the plane writes its
#    cell: water (on a puddle plane only a glossy candidate), or dry (up-facing, up to 0.6 m above
#    the plane, unless the cell is water). A lamp's crossing that the screen cannot see (off it or
#    hidden) takes what the map says: water or dry; unknown stays "unseen" as before. A new plane
#    (more than 8 cm away) starts a new generation: older cells read as unknown. Hence the net no
#    longer has holes where the hunter or the screen's edge hides the water.
#  - The lamps are chosen with a hysteresis: a lamp chosen in the last pass counts 1.6 times (found
#    again within 0.15 m), so the set does not change with the camera for near-equal lamps.
#  - Under the water: a water pixel on a mirrored plane (the sewer; its depth is the water's, its
#    G-buffer albedo the bed's) gets the lamps' unshadowed light on a horizontal surface x the bed's
#    albedo x 0.3 x BB_CAUSTICS_WORLD x the pattern at that point (caustic net on the bed seen
#    through the water). A puddle's pixel (glossy candidate on the plane) has its lamp-light share
#    (the modelled lamp light over its own, at most 1) x 0.7 moved by the pattern (at most 3 times).
#  - Puddles ripple like water: the pattern at 0.8 of the speed, full contrast (the owner: caustics
#    only look right when the liquid ripples; r107e's 0.25 and half contrast looked dead).
#  - Log: "Water caustics (r107f, BB_CAUSTICS_WORLD=...)" once, and "Water caustics (r107f): world
#    map ..." with the periodic lines.
#
# Off (BB_CAUSTICS_WORLD unset, 0, negative or unreadable): knobs.world is 0, so no map buffer is made
# (the 8th binding gets the counters buffer, which the shader never reads there), the push flag
# CAUSTICS_FLAG_WORLD is never set, the shader's new code sits behind that flag, ChooseLamps gets a
# null keep list (its result is as before), the data words 13 and 14 are 0 and no log line is added.
#
# Files: r107's own only (host_shaders/caustics.comp, caustics_layout.h; renderer_vulkan/
# caustics_params.h, vk_caustics.h, vk_caustics.cpp; tests/test_caustics.cpp; README.md) plus the
# caustics row of tests/test_effect_pipelines.cpp (an 8th binding). No new file.
#
# Use: python -I -X utf8 r107f_caustics-world-anchored.py check | apply | revert. Root from
# R107F_ROOT, R107E_ROOT, R107D_ROOT, R107C_ROOT, R107B_ROOT or R107_ROOT, else <tree>. Each edit
# is an exact text (old -> new) found exactly once; "applied" = every new text once and its old one
# gone, "clean" = every old text once and no new one; anything else is refused (exit 1, nothing
# written). Line ends are kept (CRLF in the tree). apply keeps the touched files in r107f_backup/ next
# to this script. Revert order: r107f, r107e, r107d, r107c, r107b, r107 (the older scripts' checks
# fail on r107f's text).
# Exit: 0 done, 1 refused, 2 usage.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r107f_backup")
ROOT = (os.environ.get("R107F_ROOT") or os.environ.get("R107E_ROOT") or os.environ.get("R107D_ROOT")
        or os.environ.get("R107C_ROOT") or os.environ.get("R107B_ROOT") or os.environ.get("R107_ROOT")
        or "<tree>")
V = "engine/gpu/shadps4/video_core/"

README_PARA_OLD = "Nothing under the water; the sun and moon not on puddles."
README_PARA_NEW = ("Nothing under the water unless `BB_CAUSTICS_WORLD` is set (then the lamps' light on the water's bed "
                   "and rippling puddles, below); the sun and moon not on puddles.")
README_ROW = ("| `BB_CAUSTICS_WORLD` | Needs `BB_CAUSTICS_LAMPS`. A number above 0 (up to 4; `1` is the normal value) turns on the world-anchored "
              "lamp caustics (0, unset, a negative number or other text is off, as r107e). Why: the net's pattern is a function of the "
              "world point where a lamp's reflected path crosses the water, but it was drawn only where the screen shows water at "
              "that point, so it had holes where the hunter, a pillar or the screen's edge hides the water, and the holes moved with the "
              "camera (the owner: the caustics move with the camera, with shadows in them). Now: (1) a world map of what the water is, "
              "256 x 256 cells of 0.25 m wrapped at 64 m, one word each (the plane's generation x 4 + water or dry), in its own "
              "device-local buffer of 256 KB, bound as the pass's 8th binding (the counters buffer stands in when the knob is off); "
              "every up-facing pixel (normal y 0.9 or more) on the plane writes its cell: water (on a puddle plane only a glossy "
              "candidate), or dry when it lies up to 0.6 m above the plane and the cell is not water; a lamp's crossing that is off the "
              "screen or hidden behind something nearer takes the map's answer (water or dry; unknown stays unseen); a plane more than "
              "8 cm from the last starts a new generation, so old cells read as unknown; (2) a lamp chosen in the last pass counts 1.6 "
              "times in the ranking of the 4 lamps (found again within 0.15 m), so the set does not change with the camera for "
              "near-equal lamps; (3) light under the water: a water pixel on a mirrored plane (the sewer) gets the lamps' unshadowed light "
              "on a horizontal surface times the albedo the G-buffer holds there (the bed's) times 0.3 times this number times the "
              "pattern at that point, faded with distance as the rest; a puddle's glossy pixel on the plane has the share of its light "
              "that comes from the lamps (the modelled lamp light over its own, at most 1) times 0.7 moved by the pattern (at most 3 "
              "times); (4) puddles ripple like water: the pattern at 0.8 of the speed with all its contrast (r107e: 0.25 and half). "
              "Not done: the lamps' own shadows (this pass has no per-lamp visibility, so light also lands where a post or a coffin "
              "would shade the water), the sun's light under the water, caustics on a bed under water the depth does not show. Cost "
              "(estimate, not measured): the pixels within 0.6 m of the plane add 4 depth reads and one 4-byte store, water pixels a loop "
              "over the lamps, 0.02 to 0.06 ms at 1080p; memory 256 KB. Log: `Water caustics (r107f, BB_CAUSTICS_WORLD=...)` once and "
              "`Water caustics (r107f): world map ...` with the periodic lines. | off |")

EDITS = {
    V + 'host_shaders/caustics_layout.h': [
        (r'''#define CAUSTICS_FLAG_PUDDLE_PLANE 128u
''',
         r'''#define CAUSTICS_FLAG_PUDDLE_PLANE 128u
// bbport (r107f_caustics-world-anchored): BB_CAUSTICS_WORLD (with BB_CAUSTICS_LAMPS, a plane or a
// puddle plane): the world map (binding 7) is read and written, the water gets the light of the lamps
// seen through it (a mirrored plane) or their ripple (puddles).
#define CAUSTICS_FLAG_WORLD 256u
'''),
        (r'''// (from 5.12 m below the camera to the camera). Words 33-39 are free.
''',
         r'''// (from 5.12 m below the camera to the camera). Words 33-38 are r107f's (below), 39 is free.
'''),
        (r'''#define CAUSTICS_W_PUDDLE_WET 32
''',
         r'''#define CAUSTICS_W_PUDDLE_WET 32
// bbport (r107f_caustics-world-anchored): 33 water pixels given the light of the lamps seen through
// the water (a mirrored plane), 34 and 35 cells written to the world map as water and as dry, 36 and
// 37 lamp crossings the screen cannot see (off it, hidden) taken from the map as water and as dry, 38
// puddle pixels the ripple moved.
#define CAUSTICS_W_BED 33
#define CAUSTICS_W_MAP_WATER 34
#define CAUSTICS_W_MAP_DRY 35
#define CAUSTICS_W_MAP_RESCUED_WATER 36
#define CAUSTICS_W_MAP_RESCUED_DRY 37
#define CAUSTICS_W_BED_PUDDLE 38
'''),
        (r'''#define CAUSTICS_DATA_LOOK 12
''',
         r'''#define CAUSTICS_DATA_LOOK 12
// bbport (r107f_caustics-world-anchored): the map's generation (uint: a cell counts only when it
// holds this one; 0 without the map) and the bed's strength (float: BB_CAUSTICS_WORLD).
#define CAUSTICS_DATA_WORLD_GEN 13
#define CAUSTICS_DATA_BED 14
'''),
        (r'''#define CAUSTICS_PUDDLE_CONTRAST 0.5
''',
         r'''#define CAUSTICS_PUDDLE_CONTRAST 0.5
// bbport (r107f_caustics-world-anchored): the world map: CAUSTICS_MAP_SIZE x CAUSTICS_MAP_SIZE cells
// of 1 / CAUSTICS_MAP_CELLS_PER_M m in world x, z (wrapped: 64 m), one word each: the plane's
// generation x 4 + the state (CAUSTICS_MAP_*). Written by every up-facing pixel on the plane (water;
// on puddles only a candidate) or up to CAUSTICS_MAP_LEDGE m above it (dry), read where a lamp's
// crossing is off the screen or hidden. The bed: a mirrored plane's water pixel gets the lamps'
// unshadowed light on the horizontal surface x its albedo (the bed's, from the G-buffer) x
// CAUSTICS_BED_T x the pattern there x BB_CAUSTICS_WORLD's number; a puddle's pixel has the share of
// its light that comes from the lamps (at most 1) x CAUSTICS_BED_PUDDLE moved by the pattern (at most
// 3). Puddles ripple like water: the pattern at CAUSTICS_RIPPLE_SPEED of the speed, with
// CAUSTICS_RIPPLE_CONTRAST of its contrast.
#define CAUSTICS_MAP_SIZE 256
#define CAUSTICS_MAP_WORDS 65536
#define CAUSTICS_MAP_CELLS_PER_M 4.0
#define CAUSTICS_MAP_UNKNOWN 0u
#define CAUSTICS_MAP_WATER 1u
#define CAUSTICS_MAP_DRY 2u
#define CAUSTICS_MAP_LEDGE 0.6
#define CAUSTICS_BED_T 0.3
#define CAUSTICS_BED_PUDDLE 0.7
#define CAUSTICS_RIPPLE_SPEED 0.8
#define CAUSTICS_RIPPLE_CONTRAST 1.0
'''),
    ],
    V + 'host_shaders/caustics.comp': [
        (r'''// CAUSTICS_PUDDLE_SPEED as fast and has CAUSTICS_PUDDLE_CONTRAST of its contrast (still water).
#version 450
''',
         r'''// CAUSTICS_PUDDLE_SPEED as fast and has CAUSTICS_PUDDLE_CONTRAST of its contrast (still water).
// bbport (r107f_caustics-world-anchored): BB_CAUSTICS_WORLD (CAUSTICS_FLAG_WORLD): a world map of what
// the water is (binding 7; caustics_layout.h): the up-facing pixels on the plane write their cell, a
// lamp's crossing the screen cannot see (off it, hidden) reads it, so the net has no holes where the
// hunter or the screen's edge hides the water. Water pixels of a mirrored plane get the lamps' light
// on the bed under them, a puddle's pixels the ripple (CAUSTICS_RIPPLE_*).
#version 450
'''),
        (r'''layout(binding = 6) uniform texture2D records_tex; // G-buffer cb3 (.a: the pixel's light set)
''',
         r'''layout(binding = 6) uniform texture2D records_tex; // G-buffer cb3 (.a: the pixel's light set)
// bbport (r107f_caustics-world-anchored): the world map, one word a cell (the generation x 4 + state).
layout(binding = 7, std430) buffer WorldMap {
    uint world_map[];
};
'''),
        (r'''void Shade(ivec2 p) {
''',
         r'''// bbport (r107f_caustics-world-anchored): the world map's cell of the world point (x, z), wrapped.
uint MapIndex(vec2 xz) {
    const ivec2 c = ivec2(floor(xz * CAUSTICS_MAP_CELLS_PER_M)) & (CAUSTICS_MAP_SIZE - 1);
    return uint(c.y * CAUSTICS_MAP_SIZE + c.x);
}

// What the cell holds in this plane's generation (CAUSTICS_MAP_UNKNOWN, _WATER or _DRY).
uint MapState(vec2 xz) {
    const uint v = world_map[MapIndex(xz)];
    return (v >> 2u) == Data(CAUSTICS_DATA_WORLD_GEN) ? (v & 3u) : CAUSTICS_MAP_UNKNOWN;
}

void MapSet(vec2 xz, uint state) {
    world_map[MapIndex(xz)] = (Data(CAUSTICS_DATA_WORLD_GEN) << 2u) | state;
}

void Shade(ivec2 p) {
'''),
        (r'''    vec3 added = vec3(0.0), direct = vec3(0.0); // r107c: direct, the lamps' own light (the model)
''',
         r'''    // bbport (r107f_caustics-world-anchored): the world map and the light seen through the water. An
    // up-facing pixel on the plane (or up to CAUSTICS_MAP_LEDGE above it) writes what it is; a water
    // pixel gets the lamps' unshadowed light on a horizontal surface, as the bed's (a mirrored
    // plane) or as the ripple that moves its own lamp light (a puddle).
    const bool world = (flags & CAUSTICS_FLAG_WORLD) != 0u;
    vec3 bed_add = vec3(0.0); // light seen through a mirrored plane's water, added
    vec3 bed_lit = vec3(0.0); // a puddle pixel's own lamp light (modelled)
    float bed_c = 1.0;        // the ripple's pattern there (1: none)
    if (world && height > -(CAUSTICS_WATER_M + CAUSTICS_WATER_REL * P.z) && height < CAUSTICS_MAP_LEDGE) {
        if (!have_n) {
            n = NormalAt(p, P);
            have_n = true;
        }
        if (DirToWorld(n).y >= CAUSTICS_PUDDLE_UP) {
            const bool on_plane = height <= CAUSTICS_WATER_M + CAUSTICS_WATER_REL * P.z;
            bool wet = on_plane;
            if (on_plane && puddle) {
                wet = (flags & CAUSTICS_FLAG_MATERIAL) != 0u &&
                      texelFetch(material_tex, TexelOf(material_tex, p, vec2(p) + 0.5), 0).r >= CAUSTICS_PUDDLE_GLOSS;
            }
            if (wet) {
                MapSet(Pw.xz, CAUSTICS_MAP_WATER);
                atomicAdd(group_counts[CAUSTICS_W_MAP_WATER], 1u);
                const uint lamps_here = min(Data(CAUSTICS_DATA_COUNT), uint(CAUSTICS_MAX_LAMPS));
                vec3 bed = vec3(0.0);
                for (uint k = 0u; k < lamps_here; ++k) {
                    const uint at = CAUSTICS_DATA_LAMPS + k * CAUSTICS_LAMP_WORDS;
                    const vec3 L = uintBitsToFloat(uvec3(Data(at), Data(at + 1u), Data(at + 2u)));
                    const float reach = uintBitsToFloat(Data(at + 3u));
                    const vec3 colour = uintBitsToFloat(uvec3(Data(at + 4u), Data(at + 5u), Data(at + 6u)));
                    const vec3 d = L - Pw;
                    const float dl = length(d);
                    if (dl < reach && dl > 1e-3) {
                        bed += colour * (LampCurve(dl / reach) * max(d.y / dl, 0.0));
                    }
                }
                const vec3 bed_albedo =
                    (flags & CAUSTICS_FLAG_ALBEDO) != 0u
                        ? texelFetch(albedo_tex, TexelOf(albedo_tex, p, vec2(p) + 0.5), 0).rgb
                        : vec3(0.5);
                const float bed_fade = 1.0 - smoothstep(CAUSTICS_FADE_START, CAUSTICS_FADE_END, P.z);
                if (puddle) {
                    bed_lit = bed * bed_albedo * bed_fade;
                    bed_c = clamp(mix(1.0, Pattern(Pw.xz, CAUSTICS_RIPPLE_SPEED), CAUSTICS_RIPPLE_CONTRAST), 0.0, 3.0);
                } else {
                    bed_add = bed * bed_albedo *
                              (CAUSTICS_BED_T * uintBitsToFloat(Data(CAUSTICS_DATA_BED)) * bed_fade *
                               Pattern(Pw.xz, 1.0));
                }
            } else if (MapState(Pw.xz) != CAUSTICS_MAP_WATER) {
                MapSet(Pw.xz, CAUSTICS_MAP_DRY);
                atomicAdd(group_counts[CAUSTICS_W_MAP_DRY], 1u);
            }
        }
    }
    vec3 added = vec3(0.0), direct = vec3(0.0); // r107c: direct, the lamps' own light (the model)
'''),
        (r'''            int crossing = Water(X, xi, xq);
            if (puddle && crossing <= AT_BELOW) {
''',
         r'''            int crossing = Water(X, xi, xq);
            bool mapped = false; // r107f
            if (world && (crossing == AT_OFF || crossing == AT_HIDDEN)) {
                // r107f: the screen cannot see this crossing: the world map says what it was.
                const uint known = MapState(X.xz);
                if (known != CAUSTICS_MAP_UNKNOWN) {
                    atomicAdd(group_counts[known == CAUSTICS_MAP_WATER ? CAUSTICS_W_MAP_RESCUED_WATER
                                                                         : CAUSTICS_W_MAP_RESCUED_DRY], 1u);
                    crossing = known == CAUSTICS_MAP_WATER ? AT_WATER : AT_DRY;
                    mapped = true;
                }
            }
            if (puddle && crossing <= AT_BELOW && !mapped) {
'''),
        (r'''            const float pattern = puddle ? mix(1.0, Pattern(X.xz, CAUSTICS_PUDDLE_SPEED), CAUSTICS_PUDDLE_CONTRAST)
                                         : Pattern(X.xz, 1.0);
''',
         r'''            // r107f: with the world map puddles ripple like water.
            const float pattern =
                puddle ? (world ? mix(1.0, Pattern(X.xz, CAUSTICS_RIPPLE_SPEED), CAUSTICS_RIPPLE_CONTRAST)
                                : mix(1.0, Pattern(X.xz, CAUSTICS_PUDDLE_SPEED), CAUSTICS_PUDDLE_CONTRAST))
                       : Pattern(X.xz, 1.0);
'''),
        (r'''    if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0) && !measure) {
        return;
    }
''',
         r'''    const bool bed_on = dot(bed_add, LUMA) > 0.0 || bed_c != 1.0; // r107f
    if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0) && !measure && !bed_on) {
        return;
    }
'''),
        (r'''        if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0)) {
            return;
        }
''',
         r'''        if (factor == 1.0 && tint_k <= 0.0 && !(dot(added, LUMA) > 0.0) && !bed_on) {
            return;
        }
'''),
        (r'''        rgb += added;
    }
    if (tint_k > 0.0) {
        rgb = Tinted(rgb, tint, tint_k);
    }
''',
         r'''        rgb += added;
    }
    if (bed_c != 1.0) {
        // r107f: a puddle's own lamp light moved by the ripple (its share of the pixel's light).
        const float own_bed = max(dot(max(rgb, vec3(0.0)), LUMA), 1e-4);
        rgb *= 1.0 + CAUSTICS_BED_PUDDLE * clamp(dot(bed_lit, LUMA) / own_bed, 0.0, 1.0) * (bed_c - 1.0);
        atomicAdd(group_counts[CAUSTICS_W_BED_PUDDLE], 1u);
    }
    if (dot(bed_add, LUMA) > 0.0) {
        rgb += bed_add; // r107f: the lamps' light on the bed under a mirrored plane's water
        atomicAdd(group_counts[CAUSTICS_W_BED], 1u);
    }
    if (tint_k > 0.0) {
        rgb = Tinted(rgb, tint, tint_k);
    }
'''),
    ],
    V + 'renderer_vulkan/caustics_params.h': [
        (r'''inline constexpr std::uint32_t HeightBins = CAUSTICS_HEIGHT_BINS;
''',
         r'''inline constexpr std::uint32_t HeightBins = CAUSTICS_HEIGHT_BINS;
// bbport (r107f_caustics-world-anchored): the world map's words, flag and counters fit; the cells
// wrap by a mask (a power of two). A new plane starts at WorldKeep m from the last; a lamp chosen in
// the last pass is found again within LampKeepRadius m and counts LampKeepBonus times.
static_assert(CAUSTICS_FLAG_WORLD == 256u && CAUSTICS_W_BED > CAUSTICS_W_PUDDLE_WET &&
              CAUSTICS_W_BED_PUDDLE < CAUSTICS_W_HEIGHTS && CAUSTICS_W_MAP_RESCUED_DRY < CAUSTICS_W_BED_PUDDLE);
static_assert(CAUSTICS_DATA_WORLD_GEN > CAUSTICS_DATA_LOOK && CAUSTICS_DATA_BED < CAUSTICS_DATA_LAMPS);
static_assert(CAUSTICS_MAP_WORDS == CAUSTICS_MAP_SIZE * CAUSTICS_MAP_SIZE &&
              (CAUSTICS_MAP_SIZE & (CAUSTICS_MAP_SIZE - 1)) == 0);
inline constexpr std::uint32_t FlagWorld = CAUSTICS_FLAG_WORLD, MapWords = CAUSTICS_MAP_WORDS;
inline constexpr float WorldKeep = 0.08f, LampKeepRadius = 0.15f, LampKeepBonus = 1.6f;
'''),
        (r'''    bool lamps_unreadable = false; ///< BB_CAUSTICS_LAMPS was set to text that is not a number nor "show"
};
''',
         r'''    bool lamps_unreadable = false; ///< BB_CAUSTICS_LAMPS was set to text that is not a number nor "show"
    float world = 0.0f;            ///< BB_CAUSTICS_WORLD (r107f); 0: off
};
'''),
        (r'''    k.lamp_strength = ParseOne(lamps, k.show, k.lamps_unreadable);
    return k;
}
''',
         r'''    k.lamp_strength = ParseOne(lamps, k.show, k.lamps_unreadable);
    return k;
}

/// bbport (r107f_caustics-world-anchored): BB_CAUSTICS_WORLD: a number above 0 (at most MaxStrength);
/// unset, empty, 0, negative or other text is 0 (off). "show" is 1 (it has no test view of its own).
inline float WorldOf(const char* text) {
    bool show = false, unreadable = false;
    return ParseOne(text, show, unreadable);
}
'''),
        (r'''/// that count most first (luminance x (1 - height / reach)^2 x reach / (reach + distance to the
/// camera); ties: the earlier record). `view_to_world`: the pass camera's 3x4 rows.
inline std::uint32_t ChooseLamps(const std::uint32_t* records, std::size_t count,
                                 const std::array<float, 12>& view_to_world, float plane_y,
                                 std::array<Lamp, MaxLamps>& out) {
''',
         r'''/// that count most first (luminance x (1 - height / reach)^2 x reach / (reach + distance to the
/// camera); ties: the earlier record). `view_to_world`: the pass camera's 3x4 rows.
/// bbport (r107f_caustics-world-anchored): `keep` (null: none) the lamps of the last pass (`keep_count`
/// of them): a lamp within LampKeepRadius m of one of them counts LampKeepBonus times.
inline std::uint32_t ChooseLamps(const std::uint32_t* records, std::size_t count,
                                 const std::array<float, 12>& view_to_world, float plane_y,
                                 std::array<Lamp, MaxLamps>& out,
                                 const std::array<Lamp, MaxLamps>* keep = nullptr,
                                 std::uint32_t keep_count = 0) {
'''),
        (r'''        if (!(lamp.importance > 0.0f)) {
            continue;
        }
''',
         r'''        for (std::uint32_t j = 0; keep != nullptr && j < keep_count && j < MaxLamps; ++j) {
            const auto& old = (*keep)[j];
            const float kx = lamp.world[0] - old.world[0], ky = lamp.world[1] - old.world[1],
                        kz = lamp.world[2] - old.world[2];
            if (kx * kx + ky * ky + kz * kz < LampKeepRadius * LampKeepRadius) {
                lamp.importance *= LampKeepBonus; // r107f
                break;
            }
        }
        if (!(lamp.importance > 0.0f)) {
            continue;
        }
'''),
    ],
    V + 'renderer_vulkan/vk_caustics.h': [
        (r'''    } counters;
    bool made = false;
''',
         r'''    } counters;
    // bbport (r107f_caustics-world-anchored): the world map (device local; none without
    // BB_CAUSTICS_WORLD), the plane's generation and height it was written for, whether the first
    // dispatch cleared it, the lamps chosen in the last pass that found any.
    Buffer world_map;
    u32 world_gen = 0;
    float world_plane = 0.0f;
    bool world_cleared = false;
    std::array<::BbCaustics::Lamp, ::BbCaustics::MaxLamps> last_lamps{};
    u32 last_lamp_count = 0;
    bool made = false;
'''),
        (r'''        u64 puddle_ground = 0, puddle_wet = 0; ///< r107e: the guard's last counts
''',
         r'''        u64 puddle_ground = 0, puddle_wet = 0; ///< r107e: the guard's last counts
        u32 world_draws = 0;   ///< r107f: dispatches that used the world map
        u32 world_changes = 0; ///< r107f: new plane generations (the map starts again)
'''),
    ],
    V + 'renderer_vulkan/vk_caustics.cpp': [
        (r'''constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32);
''',
         r'''constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32);
/// bbport (r107f_caustics-world-anchored): the world map (caustics_layout.h): one word a cell.
constexpr vk::DeviceSize WorldBytes = BC::MapWords * sizeof(u32);
'''),
        (r'''        const BC::Knobs read = BC::Parse(value, std::getenv("BB_CAUSTICS_LAMPS"));
''',
         r'''        BC::Knobs read = BC::Parse(value, std::getenv("BB_CAUSTICS_LAMPS"));
        read.world = BC::WorldOf(std::getenv("BB_CAUSTICS_WORLD")); // r107f
'''),
        (r'''SampledImage, SampledImage},
                              sizeof(BC::Push), CAUSTICS_COMP, "Water caustics");
''',
         r'''SampledImage, SampledImage, StorageBuffer},
                              sizeof(BC::Push), CAUSTICS_COMP, "Water caustics");
'''),
        (r'''            std::memset(counters.mapped, 0, BufferBytes);
        }
    }
''',
         r'''            std::memset(counters.mapped, 0, BufferBytes);
        }
    }
    if (made && knobs.world > 0.0f && knobs.lamp_strength > 0.0f) {
        // bbport (r107f_caustics-world-anchored): the world map, device local; the first dispatch
        // that uses it clears it. Without it the knob does nothing (the log says so).
        const VkBufferCreateInfo map_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = WorldBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo map_alloc{};
        map_alloc.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
        VkBuffer map_raw{};
        if (vmaCreateBuffer(instance.GetAllocator(), &map_ci, &map_alloc, &map_raw,
                            &world_map.allocation, nullptr) == VK_SUCCESS) {
            world_map.buffer = map_raw;
        }
    }
'''),
        (r'''    if (!upscaler_on) {
''',
         r'''    if (knobs.world > 0.0f) {
        std::printf("Water caustics (r107f, BB_CAUSTICS_WORLD=%.2f): %s; a world map of what the water is "
                    "(%u x %u cells of %.2f m, %u KB), the lamps kept from pass to pass, the lamps' light "
                    "on the bed under a mirrored plane's water, puddles that ripple\n",
                    double(knobs.world),
                    world_map.buffer ? "on"
                                     : "off - it needs BB_CAUSTICS_LAMPS and the pass made, and the map did not fit",
                    unsigned(CAUSTICS_MAP_SIZE), unsigned(CAUSTICS_MAP_SIZE), 1.0 / CAUSTICS_MAP_CELLS_PER_M,
                    unsigned(WorldBytes / 1024));
    }
    if (!upscaler_on) {
'''),
        (r'''    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}
''',
         r'''    if (world_map.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), world_map.buffer, world_map.allocation); // r107f
    }
    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}
'''),
        (r'''            if (puddle_checked) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen);
                lamp_draw = chosen_count > 0;
''',
         r'''            if (puddle_checked) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
                lamp_draw = chosen_count > 0;
'''),
        (r'''            if (lamp_draw && camera.valid) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen);
            }
''',
         r'''            if (lamp_draw && camera.valid) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
            }
'''),
        (r'''    if (!draw && !lamp_draw && !knobs.show && !puddle) { // r107e: puddles measure every pass
        done();
''',
         r'''    if (knobs.world > 0.0f && chosen_count > 0) {
        last_lamps = chosen; // r107f: the lamps of this pass count more in the next one
        last_lamp_count = chosen_count;
    }
    if (!draw && !lamp_draw && !knobs.show && !puddle) { // r107e: puddles measure every pass
        done();
'''),
        (r'''                 (lamp_draw && albedo_view ? BC::FlagAlbedo : 0u);
    push.slot = dispatches % BC::Slots;
''',
         r'''                 (lamp_draw && albedo_view ? BC::FlagAlbedo : 0u);
    // r107f: the world map is used with the lamps' caustics; a plane more than WorldKeep m from the
    // last one starts a new generation (the old cells read as unknown); the first use clears it.
    const bool world_on = knobs.world > 0.0f && lamp_draw && world_map.buffer;
    bool clear_map = false;
    if (world_on) {
        if (world_gen == 0 || std::fabs(plane_y - world_plane) > BC::WorldKeep) {
            ++world_gen;
            world_plane = plane_y;
            ++stats.world_changes;
        }
        push.flags |= BC::FlagWorld;
        ++stats.world_draws;
        clear_map = !world_cleared;
        world_cleared = true;
    }
    push.slot = dispatches % BC::Slots;
'''),
        (r'''        std::memcpy(&data[CAUSTICS_DATA_LOOK], &look, sizeof(float));
''',
         r'''        std::memcpy(&data[CAUSTICS_DATA_LOOK], &look, sizeof(float));
        // r107f: the world map's generation and the bed's strength (0 and 0 without BB_CAUSTICS_WORLD)
        data[CAUSTICS_DATA_WORLD_GEN] = world_on ? world_gen : 0u;
        const float bed_strength = world_on ? knobs.world : 0.0f;
        std::memcpy(&data[CAUSTICS_DATA_BED], &bed_strength, sizeof(float));
'''),
        (r'''         bound_records,
         counter_buffer = counters.buffer, pass_pipeline = *pipeline,
         pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            cmdbuf.fillBuffer(counter_buffer, push.slot * SlotBytes, SlotBytes, 0);
''',
         r'''         bound_records,
         counter_buffer = counters.buffer,
         world_buffer = world_map.buffer ? world_map.buffer : counters.buffer, clear_map, // r107f
         pass_pipeline = *pipeline,
         pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            if (clear_map) {
                cmdbuf.fillBuffer(world_buffer, 0, WorldBytes, 0); // r107f: the first use
            }
            cmdbuf.fillBuffer(counter_buffer, push.slot * SlotBytes, SlotBytes, 0);
'''),
        (r'''            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, BufferBytes};
''',
         r'''            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, BufferBytes};
            const vk::DescriptorBufferInfo world_info{world_buffer, 0, VK_WHOLE_SIZE}; // r107f
'''),
        (r'''                                    Write(6, SampledImage, &infos[5])};
''',
         r'''                                    Write(6, SampledImage, &infos[5]),
                                    vk::WriteDescriptorSet{.dstBinding = 7,
                                                           .descriptorCount = 1,
                                                           .descriptorType = StorageBuffer,
                                                           .pBufferInfo = &world_info}};
'''),
        (r'''                     double(BC::PuddleMaxWet), stats.puddle_none, stats.puddle_floor);
    stats = {};
''',
         r'''                     double(BC::PuddleMaxWet), stats.puddle_none, stats.puddle_floor);
    if (knobs.world > 0.0f) {
        // r107f: the world map and the light under the water (a dispatch: means over every dispatch read)
        BbReport::Printf("Water caustics (r107f): world map (bed %.2f): %u dispatches with it, %u new plane "
                         "generations (now %u, plane y %.2f); a dispatch: %.0f cells written as water, %.0f "
                         "as dry; lamp crossings the screen cannot see taken from the map: %.0f as water, "
                         "%.0f as dry; light through the water %.0f px (mirrored plane), ripple on %.0f px "
                         "(puddles)\n",
                         double(knobs.world), stats.world_draws, stats.world_changes, world_gen,
                         double(world_plane), px(CAUSTICS_W_MAP_WATER), px(CAUSTICS_W_MAP_DRY),
                         px(CAUSTICS_W_MAP_RESCUED_WATER), px(CAUSTICS_W_MAP_RESCUED_DRY), px(CAUSTICS_W_BED),
                         px(CAUSTICS_W_BED_PUDDLE));
    }
    stats = {};
'''),
    ],
    'engine/tests/test_caustics.cpp': [
        (r'''    // bbport (r107e_caustics-puddles): the puddle plane from the candidates' heights, and the guard.
''',
         r'''    // bbport (r107f_caustics-world-anchored): the world knob, and the lamp choice's hysteresis.
    {
        assert(WorldOf(nullptr) == 0.0f && WorldOf("") == 0.0f && WorldOf("0") == 0.0f && WorldOf("-1") == 0.0f);
        assert(WorldOf("1") == 1.0f && WorldOf("2.5") == 2.5f && WorldOf("9") == MaxStrength);
        assert(WorldOf("yes") == 0.0f && WorldOf("1x") == 0.0f && Parse("1", "1").world == 0.0f);
        assert(FlagWorld == 256u && MapWords == 65536u && CAUSTICS_MAP_SIZE * CAUSTICS_MAP_SIZE == 65536);
        // Five lamps at the same distance from the camera (0, 2, 0), 1 m above it: the fifth is 10%
        // brighter, so it wins on its own; with the first four kept it does not.
        const std::array<float, 12> m{1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1, 0};
        const auto word = [](float f) {
            std::uint32_t u = 0;
            std::memcpy(&u, &f, sizeof(u));
            return u;
        };
        std::uint32_t rec[16 * 5] = {};
        const float spots[5][2] = {{3.0f, 4.0f}, {-3.0f, 4.0f}, {4.0f, 3.0f}, {-4.0f, 3.0f}, {0.0f, 5.0f}};
        for (int i = 0; i < 5; ++i) {
            const float c = i == 4 ? 1.1f : 1.0f;
            const float w[7] = {spots[i][0], 1.0f, spots[i][1], 1.0f / 36.0f, c, c, c};
            for (int j = 0; j < 7; ++j) {
                rec[i * 16 + j] = word(w[j]);
            }
        }
        std::array<Lamp, MaxLamps> first{}, kept{}, plain{};
        assert(ChooseLamps(rec, 4, m, 0.0f, first) == 4);
        assert(ChooseLamps(rec, 5, m, 0.0f, plain) == 4 && Near(plain[0].colour[0], 1.1f, 1e-5f));
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, &first, 4) == 4);
        for (std::uint32_t i = 0; i < 4; ++i) {
            assert(Near(kept[i].colour[0], 1.0f, 1e-5f)); // the kept four, not the brighter newcomer
        }
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, nullptr, 4) == 4 && Near(kept[0].colour[0], 1.1f, 1e-5f));
        // A newcomer clearly brighter (twice) still wins.
        rec[4 * 16 + 4] = rec[4 * 16 + 5] = rec[4 * 16 + 6] = word(2.0f);
        assert(ChooseLamps(rec, 5, m, 0.0f, kept, &first, 4) == 4 && Near(kept[0].colour[0], 2.0f, 1e-5f));
    }
    // bbport (r107e_caustics-puddles): the puddle plane from the candidates' heights, and the guard.
'''),
    ],
    'engine/tests/test_effect_pipelines.cpp': [
        (r'''         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer, eSampledImage,
          eSampledImage},
         128},
''',
         r'''         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer, eSampledImage,
          eSampledImage, eStorageBuffer}, // r107f: the world map
         128},
'''),
    ],
    'README.md': [
        (README_PARA_OLD, README_PARA_NEW),
        ("\n\n### Blood sheen (in development)\n", "\n" + README_ROW + "\n\n### Blood sheen (in development)\n"),
    ],
}


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print("REFUSED %s: missing (are r107 to r107e applied?)" % path)
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
    layout = t[V + "host_shaders/caustics_layout.h"]
    shader = t[V + "host_shaders/caustics.comp"]
    cpp = t[V + "renderer_vulkan/vk_caustics.cpp"]
    params = t[V + "renderer_vulkan/caustics_params.h"]
    readme = t["README.md"]
    for name in ("FLAG_WORLD 256u", "W_BED 33", "W_MAP_WATER 34", "W_MAP_DRY 35", "W_MAP_RESCUED_WATER 36",
                 "W_MAP_RESCUED_DRY 37", "W_BED_PUDDLE 38", "DATA_WORLD_GEN 13", "DATA_BED 14", "MAP_SIZE 256",
                 "MAP_WORDS 65536", "MAP_CELLS_PER_M 4.0", "MAP_UNKNOWN 0u", "MAP_WATER 1u", "MAP_DRY 2u",
                 "MAP_LEDGE 0.6", "BED_T 0.3", "BED_PUDDLE 0.7", "RIPPLE_SPEED 0.8", "RIPPLE_CONTRAST 1.0",
                 "SLOT_WORDS 168", "DATA_WORDS 48", "DATA_LAMPS 16", "W_HEIGHTS 40", "FLAG_PUDDLE_PLANE 128u"):
        if layout.count("#define CAUSTICS_" + name + chr(10)) != 1:
            raise SystemExit("text check: caustics_layout.h lacks %r" % name)
    # the data words 13 and 14 lie before the lamps (16), the new counters before the heights (40)
    for want in ("layout(binding = 7, std430) buffer WorldMap", "uint MapIndex(vec2 xz)", "uint MapState(vec2 xz)",
                 "void MapSet(vec2 xz, uint state)", "const bool world = (flags & CAUSTICS_FLAG_WORLD) != 0u;",
                 "CAUSTICS_W_MAP_RESCUED_WATER", "CAUSTICS_W_BED_PUDDLE", "CAUSTICS_W_BED]", "!mapped",
                 "Pattern(X.xz, CAUSTICS_RIPPLE_SPEED)", "Pattern(Pw.xz, CAUSTICS_RIPPLE_SPEED)",
                 "i += CAUSTICS_GROUP * CAUSTICS_GROUP"):
        if want not in shader:
            raise SystemExit("text check: the shader lacks %r" % want)
    if shader.count("layout(binding = ") != 8:
        raise SystemExit("text check: the shader does not have 8 bindings")
    if shader.count("CAUSTICS_FLAG_WORLD") < 2:
        raise SystemExit("text check: the shader does not test CAUSTICS_FLAG_WORLD")
    # every use of the map sits behind the flag: MapSet and MapState are called only under `world`
    # (Shade's block and the crossing) -- count the calls
    if shader.count("MapSet(Pw.xz") != 2 or shader.count("MapState(") != 3:
        raise SystemExit("text check: the shader's map calls are not the two writes and two reads")
    for want in ("world_map.buffer ? world_map.buffer : counters.buffer", "cmdbuf.fillBuffer(world_buffer, 0, WorldBytes, 0)",
                 ".dstBinding = 7", "StorageBuffer},\n                              sizeof(BC::Push)", "BC::WorldOf(",
                 "knobs.world > 0.0f ? &last_lamps : nullptr", "Water caustics (r107f, BB_CAUSTICS_WORLD=",
                 "Water caustics (r107f): world map", "VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE", "BC::FlagWorld"):
        if want not in cpp:
            raise SystemExit("text check: vk_caustics.cpp lacks %r" % want)
    if cpp.count("knobs.world > 0.0f ? &last_lamps : nullptr") != 2:
        raise SystemExit("text check: both ChooseLamps calls must take the keep list")
    for want in ("inline float WorldOf(const char* text)", "LampKeepBonus = 1.6f", "WorldKeep = 0.08f",
                 "const std::array<Lamp, MaxLamps>* keep = nullptr", "float world = 0.0f;"):
        if want not in params:
            raise SystemExit("text check: caustics_params.h lacks %r" % want)
    sec = readme[readme.find("### Water caustics (in development)"):readme.find("## Sponsors")]
    for want in ("`BB_CAUSTICS_WORLD`", "256 x 256 cells of 0.25 m", "256 KB", "1.6 times", "0.8 of the speed",
                 "Water caustics (r107f)", "Not done: the lamps' own shadows", "Lamps also over puddles",
                 "unless `BB_CAUSTICS_WORLD` is set"):
        if want not in sec:
            raise SystemExit("text check: README section lacks %r" % want)
    if "Nothing under the water; the sun" in sec:
        raise SystemExit("text check: README section still says nothing under the water")
    if cpp.count("plane_y, chosen);") != 0:
        raise SystemExit("text check: a ChooseLamps call without the keep list is left")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        print("%s is not a source tree root (set R107F_ROOT)" % ROOT)
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
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
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
        for path, eds, raw, eol, cur, _ in plan:
            tmp = os.path.join(ROOT, path) + ".r107ftmp"
            open(tmp, "wb").write(out[path])
            written.append((tmp, os.path.join(ROOT, path)))
        for tmp, full in written:
            os.replace(tmp, full)
    except OSError as e:
        for tmp, _ in written:
            if os.path.exists(tmp):
                os.remove(tmp)
        print("REFUSED: write failed (%s); nothing changed" % e)
        sys.exit(1)
    print("%s: %d files, %d edits" % ("applied" if cmd == "apply" else "reverted", len(plan),
                                      sum(len(p[1]) for p in plan)))


main()
