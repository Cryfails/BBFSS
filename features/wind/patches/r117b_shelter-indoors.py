# r117b_shelter-indoors: FEATURE fix on top of r117_wind-shelter (applied and built, b28). Still off
# with r117's knob BB_WIND_SHELTER (no new knob); BB_WIND off and BB_WIND_SHELTER off are unchanged:
# every edit is in r117's own files, which only exist or run with the knob (see "Off" below).
#
# WHAT b28 SHOWED (jobs r117-grave1, r117-grave0, r117-lamp1, r117-none) AND THE CAUSES, with numbers:
#
#  1. THE LOG'S "mean" WAS WRONG (the log only; the picture and the field were not affected).
#     WS_C_PIXELS_SUM is a 32-bit sum of the field in thousandths over every sampled depth pixel of
#     600 frames. grave1: 8,565,458 samples; the sum passes 2^32 = 4,294,967,296 as soon as the mean
#     is above 4294967296 / (8565458 * 1000) = 0.5014 (library 8,640,000 samples: 0.497; lamp1
#     7,979,616: 0.538). With 63.4% of the samples above 0.5 the true mean is about 0.59, so the
#     counter wrapped once, and the log printed (sum - 2^32) / ... = 0.086 (library 0.113 + 0.497 =
#     0.61, lamp1 0.082 + 0.538 = 0.62: all three agree with their "sheltered" shares). The shares
#     (63.4%, 65.7%, 65.5%) were right, the mean was the overflow. FIX: a 64-bit sum (a carry word).
#
#  2. THE "ROOF" RULE WAS WHAT PAINTED EVERYTHING YELLOW AND RED, AND IT CANNOT SEE INDOORS.
#     raw = 1 - (1 - leeward)(1 - 0.5 roof), roof = smoothstep(2.0, 3.2, own top - own bottom). The
#     cache keeps the lowest and highest height SEEN in a 1 m cell. (a) Outdoors every cell with a
#     tall thing in it has top - bottom above 3.2: a tree (trunk to canopy, 7-8 m), a wall, a
#     pillar, a lamp post, a tower: roof 1, raw 0.5, times the gain 1.06 = 0.53 = yellow, orange
#     with a little leeward, over every tree and building and the ground around them, whatever the
#     wind does (the b28 pictures: lamp1 "mostly yellow", grave1 trees and near ground orange/red,
#     no shape behind the pillars; the shares "63% sheltered" are mostly these 0.53 cells). (b)
#     Indoors the same rule fails the other way: a cell gets a roof only when the camera saw its
#     floor AND its ceiling in the same cell, which a camera at 1.7 m looking along a room does only
#     in the far part (the far wall is red in the library picture); the near cells show floor only
#     (top - bottom about 1 m: roof 0), the ceiling above them was never seen. And the walls that
#     would shelter the room are seen only where the camera looked (the cache holds no cell behind
#     the camera), the three upwind rays meet them only for the upwind directions the view
#     covered, so most indoor cells got 0 leeward + 0 roof = the green and yellow floor and table.
#     At the camera: its own cell is the one cell nothing is seen of (the floor under the lens),
#     ground = camera - 1.7 m, top = none: field 0.00 (b28 log: "at the camera 0.00" in the library).
#     The window had 134 of 4096 cells with depth data in the library (3.3%): only what the view
#     showed; the other 96.7% of a "hall" were cells nothing was known of.
#  3. THE LEE OF WALLS AND TOMBS: with the roof gone every cell that is not behind a wall reads 0
#     (open) and the lee reads what the three rays say (3 m wall: 1 within 5 m, 0.86 at 6 m, 0.2 at
#     10 m; unchanged numbers, tests/test_wind_shelter.cpp still asserts them). The lee is only
#     visible in the show view where the camera sees the cells downwind of the wall: a camera on
#     the windward side sees the wall's face and the shelter is hidden behind it (a depth buffer
#     cannot show what it does not see), so the pair jobs run the same view with the wind turned
#     by 180 degrees: the red must move from behind the walls to in front of them.
#  4. "120 frames, 0 passes": the first log line is after 120 FRAMES OF THE HOOK, and the hook runs
#     during the loading screen and the title, where the pass is skipped for want of a camera or
#     the wind ("skipped 120 without the region or wind"). Not a fault of the field; it made the
#     first line empty. FIX: the first line comes after 120 PASSES (or after 600 frames).
#
# THE FIX: indoors is measured where it can be, at the camera, by what the CLIMBING view rays hit:
#   - per frame, of the depth pixels sampled (every 4th), the ones whose view ray climbs more than
#     WS_COVER_TAN = 0.35 (about 19 degrees above the horizontal: the top sixth of a level view):
#     `up` of them; `covered` = those that end on a surface within WS_COVER_DIST = 80 m of the
#     camera (a ceiling, the inside of a hall, a roof, the vault of a gate). The sky dome (drawn
#     far away, b28's lamp1 sky showed as grey) and distant things count as open. Fewer than 64
#     climbing samples (the camera looks down): no news, the old value stands.
#   - the share covered / up, followed in time (0.4 s; the first measure is taken whole), is mapped
#     smoothstep(0.70, 0.95) to the camera's COVER 0-1: 1 in a room or a hall (every climbing ray
#     ends on a wall or the ceiling), 0 in the open (sky above), a part under a dense canopy.
#   - the cover is REMEMBERED per cache cell (cell word 5): a cell seen this frame within 16 m of
#     the camera moves toward the camera's cover by 25% a frame (so what the camera saw while it was
#     indoors stays covered when it looks away, and goes back to open when it is seen again from the
#     open), the cells within 2.5 m of the camera take it outright.
#   - raw = 1 - (1 - leeward)(1 - cover), cover = the biggest of the cell and its 8 neighbours (a
#     cell seen from the room's floor but never with 2 samples does not leave a hole). The 3x3 blur,
#     the gain, the edge fade and the time filter are as before, so indoors is exactly 1.
#   - the roof rule is gone (RoofLo/Hi/Gain replaced by the cover's numbers): a tall thing gives its
#     own cell nothing; only leeward and cover shelter.
#   - the camera's own sample (the fog drift, the particles, the heat haze read it: counter word
#     WS_C_CAMERA) is max(field at the camera, cover x strength): it follows the cover at once.
#   - the view (BB_WIND_SHELTER_SHOW=2) paints the sky black (surfaces beyond 90 m and no depth).
# Works without ray tracing (everything is the scene depth); the plants read the same field.
#
# LOG: the first r117 line gains "; overhead cover X" (the camera's cover, smoothed, 0-1: about 1
# indoors, 0 in the open); the mean is the real mean; the first line comes after 120 passes.
#
# Off: nothing here runs without r117's knob: the shader is only built into the pass r117 makes
# (BbWindShelter::KnobOnce().on); the state buffer grows by 32 bytes inside that pass; with the knob
# off the rasterizer makes no WindShelter and the sway shaders are as before. BB_WIND off: r117's
# own guard (the knob needs it).
# Cost on (estimates): the splat pass adds per sampled pixel (14,400 at a 640x360 scene, 130k at 1080p)
# one view-ray matrix product (9 multiply-adds) and a compare, about 1% of the pass's own work; the
# upward ones (about a quarter) add one world point and one atomic in the workgroup; the merge reads
# and writes one more word of its 16k cells; the raw pass reads 9 more words a cell (4k cells); the
# final pass's thread (0,0) does the share. Together well below 0.01 ms. Memory: +32 bytes of device
# memory. CPU: nothing new (one counter word more in the log line).
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row's roof sentence).
# Use: python -I -X utf8 r117b_shelter-indoors.py check | apply | revert
# Root: R117B_ROOT, else <tree>. Line ends kept. Needs r117_wind-shelter applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117b_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAYOUT_ROOF_OLD = '''#define WS_ROOF_LO 2.0f
#define WS_ROOF_HI 3.2f
#define WS_ROOF_GAIN 0.5f
'''
LAYOUT_ROOF_NEW = '''// r117b: the overhead cover (no roof rule: a tall thing gives its own cell nothing). The camera's
// view rays that climb (tangent of the elevation above WS_COVER_TAN) and end on a surface within
// WS_COVER_DIST m are covered; their share, followed in time (WS_COVER_TAU s) and mapped by
// smoothstep(WS_COVER_LO, WS_COVER_HI), is the camera's cover; cells seen within WS_COVER_RADIUS
// cells of the camera move toward it by WS_COVER_RATE a frame, the cells within WS_COVER_NEAR
// cells take it outright; fewer than WS_COVER_MIN climbing samples a frame: no news.
#define WS_COVER_TAN 0.35f
#define WS_COVER_DIST 80.0f
#define WS_COVER_MIN 64u
#define WS_COVER_LO 0.70f
#define WS_COVER_HI 0.95f
#define WS_COVER_TAU 0.4f
#define WS_COVER_RADIUS 16.0f
#define WS_COVER_RATE 0.25f
#define WS_COVER_NEAR 2.5f
'''
LAYOUT_GLOBAL_ANCHOR = "#define WS_FRESH_WORDS 3u\n"
LAYOUT_GLOBAL_AFTER = '''// r117b: after the cache's cells and fresh words the state buffer has WS_GLOBAL_WORDS words: 0 the
// frame's count of climbing view rays, 1 of them covered (the splat pass adds, the final pass
// clears), 2 the camera's smoothed covered share (float), 3 the cover it maps to (float), 4 1 once
// the share was first taken. The cache's cell word 5 is the cell's cover (float).
#define WS_GLOBAL_WORDS 8u
'''
LAYOUT_COUNTER_ANCHOR = "#define WS_C_CELLS 9u          // window cells written (final pass)\n"
LAYOUT_COUNTER_AFTER = '''#define WS_C_COVER 10u         // the camera's smoothed covered share (float bits, overwritten each frame)
#define WS_C_PIXELS_SUM_HI 11u // carry of WS_C_PIXELS_SUM: with it a 64-bit total (r117b)
'''

COMP_DOC_OLD = '''//         round; a wall can). Overhead: a cell whose own top is WS_ROOF_LO..HI above its ground has
//         a roof; raw = 1 - (1 - leeward) (1 - WS_ROOF_GAIN roof): indoors the walls and the roof
//         together give 1, an open pavilion about a half.
'''
COMP_DOC_NEW = '''//         round; a wall can). Overhead (r117b): the cell's COVER (below), the biggest of the cell
//         and its 8 neighbours; raw = 1 - (1 - leeward) (1 - cover): indoors the cover is 1, so the
//         field is 1 whatever the rays met. A tall thing (a tree, a wall, a lamp post) gives its own
//         cell no roof (r117's roof rule painted every one of them half sheltered).
'''
COMP_COVER_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_COVER_BEFORE = '''//  COVER  (r117b) indoors is measured at the camera: of the sampled depth pixels, the ones whose
//         view ray climbs (tangent above WS_COVER_TAN) and that end on a surface within WS_COVER_DIST
//         m are covered; the sky dome and the far distance are open. The share covered, followed in
//         time and mapped by smoothstep(WS_COVER_LO, WS_COVER_HI), is the camera's cover (the final
//         pass makes it, the next frame uses it). The merge pass moves every cache cell that was
//         seen within WS_COVER_RADIUS of the camera toward it (the cache remembers what the camera
//         saw while it was indoors) and gives the cells next to the camera it outright.
'''
COMP_DIR_OLD = "shared uint g_pixels, g_sheltered, g_sum, g_indoor;\n"
COMP_DIR_NEW = '''// r117b: the world direction (not normalised) of the view ray through a pixel centre.
vec3 ray_dir(vec2 pix) {
    const vec2 ndc = ((pix - size_jitter.zw) / size_jitter.xy - 0.5) * 2.0;
    const vec3 v = vec3(ndc.x / proj.x, ndc.y / proj.y, 1.0);
    return vec3(dot(row0.xyz, v), dot(row1.xyz, v), dot(row2.xyz, v));
}

shared uint g_pixels, g_sheltered, g_sum, g_indoor, g_up, g_covered;
'''
COMP_FRESH_ANCHOR = '''uint fresh_at(uint slot) {
    return WS_M * WS_M * WS_CELL_WORDS + slot * WS_FRESH_WORDS;
}
'''
COMP_FRESH_AFTER = '''
// r117b: the state buffer's globals (wind_shelter_layout.h says which word is which).
const uint GLOBAL_BASE = WS_M * WS_M * (WS_CELL_WORDS + WS_FRESH_WORDS);
'''
COMP_INIT_ANCHOR = "        g_indoor = 0u;\n"
COMP_INIT_AFTER = "        g_up = 0u;\n        g_covered = 0u;\n"
COMP_LOOK_ANCHOR = '''        if (depth > 0.0 && depth < 1.0) {
            const float z = view_z(depth);
'''
COMP_LOOK_BEFORE = '''        const vec3 look = ray_dir(vec2(px) + 0.5);
        if (look.y > WS_COVER_TAN * length(look.xz)) {
            // r117b: a climbing view ray: does it end on something near (a ceiling, a roof) or go on
            // to the sky dome (a depth below 1, far away) or the distance?
            atomicAdd(g_up, 1u);
            if (depth > 0.0 && depth < 1.0 && view_z(depth) > 0.0) {
                const vec3 hit = world_of(vec2(px) + 0.5, depth);
                if (distance(hit, vec3(row0.w, row1.w, row2.w)) < WS_COVER_DIST) {
                    atomicAdd(g_covered, 1u);
                }
            }
        }
'''
COMP_FLUSH_OLD = '''    if (gl_LocalInvocationIndex == 0u) {
        if (g_pixels != 0u) {
'''
COMP_FLUSH_NEW = '''    if (gl_LocalInvocationIndex == 0u) {
        if (g_up != 0u) {
            atomicAdd(state.s[GLOBAL_BASE], g_up);
            atomicAdd(state.s[GLOBAL_BASE + 1u], g_covered);
        }
        if (g_pixels != 0u) {
'''
COMP_SUM_OLD = "            atomicAdd(counters.c[WS_C_PIXELS_SUM], g_sum);\n"
COMP_SUM_NEW = '''            // a 64-bit total (r117b: 600 frames of 8.6M samples in thousandths pass 2^32)
            const uint sum_before = atomicAdd(counters.c[WS_C_PIXELS_SUM], g_sum);
            if (sum_before + g_sum < sum_before) {
                atomicAdd(counters.c[WS_C_PIXELS_SUM_HI], 1u);
            }
'''
COMP_CAMERA_OLD = '''        counters.c[WS_C_CAMERA] =
            floatBitsToUint(wind_shelter_at(region, vec3(row0.w, row1.w, row2.w)));
'''
COMP_CAMERA_NEW = '''        // (r117b: and the camera's own cover, whichever is bigger)
        counters.c[WS_C_CAMERA] = floatBitsToUint(
            max(wind_shelter_at(region, vec3(row0.w, row1.w, row2.w)),
                uintBitsToFloat(state.s[GLOBAL_BASE + 3u]) * wind.w));
'''
COMP_REKEY_ANCHOR = "        state.s[cw + 4u] = want;\n"
COMP_REKEY_AFTER = "        state.s[cw + 5u] = 0u;\n"
COMP_MERGE_ANCHOR = '''        atomicAdd(counters.c[WS_C_MERGED], 1u);
    }
'''
COMP_MERGE_AFTER = '''    // r117b: the cover memory (cell word 5): what the camera saw overhead while it looked here
    const float c_in = uintBitsToFloat(state.s[GLOBAL_BASE + 3u]);
    const float away = distance((vec2(world) + 0.5) * WS_CELL, vec2(row0.w, row2.w));
    float cover = uintBitsToFloat(state.s[cw + 5u]);
    if (away < WS_COVER_NEAR * WS_CELL) {
        cover = c_in;
    } else if (n >= WS_MIN_SAMPLES && away < WS_COVER_RADIUS * WS_CELL) {
        cover += (c_in - cover) * WS_COVER_RATE;
    }
    state.s[cw + 5u] = floatBitsToUint(cover);
'''
COMP_ROOF_OLD = '''    const float roof = own.z > 0.0 ? smoothstep(WS_ROOF_LO, WS_ROOF_HI, own.y - ground) : 0.0;
    const float raw = 1.0 - (1.0 - leeward) * (1.0 - WS_ROOF_GAIN * roof);
'''
COMP_ROOF_NEW = '''    // r117b: the cover of the cell, or of a neighbour (a cell seen from the floor but never with two
    // samples leaves no hole), in place of the roof rule
    float cover = 0.0;
    for (int j = -1; j <= 1; ++j) {
        for (int i = -1; i <= 1; ++i) {
            cover = max(cover, uintBitsToFloat(cache_at(slot_of(c + ivec2(i, j)), 5u)));
        }
    }
    const float raw = 1.0 - (1.0 - leeward) * (1.0 - cover);
'''
COMP_FINAL_ANCHOR = "        region.w[at] = floatBitsToUint(1.0);\n"
COMP_FINAL_AFTER = '''        // r117b: this frame's climbing view rays -> the camera's cover (the next frame's merge and
        // camera sample use it); the frame's totals are cleared for the splat pass to fill again
        const uint up = state.s[GLOBAL_BASE];
        const uint covered = state.s[GLOBAL_BASE + 1u];
        float share = uintBitsToFloat(state.s[GLOBAL_BASE + 2u]);
        if (up >= WS_COVER_MIN) {
            const float k = state.s[GLOBAL_BASE + 4u] == 0u
                                ? 1.0
                                : 1.0 - exp(-wind.z * (1.0 / WS_COVER_TAU));
            share += (float(covered) / float(up) - share) * k;
            state.s[GLOBAL_BASE + 4u] = 1u;
        }
        state.s[GLOBAL_BASE] = 0u;
        state.s[GLOBAL_BASE + 1u] = 0u;
        state.s[GLOBAL_BASE + 2u] = floatBitsToUint(share);
        state.s[GLOBAL_BASE + 3u] = floatBitsToUint(smoothstep(WS_COVER_LO, WS_COVER_HI, share));
        counters.c[WS_C_COVER] = floatBitsToUint(share);
'''
COMP_SHOW_OLD = "    if (!(depth > 0.0 && depth < 1.0)) {\n"
COMP_SHOW_NEW = '''    // (r117b: the sky dome has a depth below 1: surfaces beyond 90 m count as no surface, black alone)
    if (!(depth > 0.0 && depth < 1.0) || !(view_z(depth) > 0.0 && view_z(depth) < 90.0)) {
'''

HDR_CONST_OLD = "inline constexpr float RoofLo = WS_ROOF_LO, RoofHi = WS_ROOF_HI, RoofGain = WS_ROOF_GAIN;\n"
HDR_CONST_NEW = '''inline constexpr float CoverTan = WS_COVER_TAN, CoverDist = WS_COVER_DIST, CoverLo = WS_COVER_LO,
                       CoverHi = WS_COVER_HI, CoverTau = WS_COVER_TAU, CoverRadius = WS_COVER_RADIUS,
                       CoverRate = WS_COVER_RATE, CoverNear = WS_COVER_NEAR;
inline constexpr std::uint32_t CoverMin = WS_COVER_MIN, GlobalWords = WS_GLOBAL_WORDS;
'''
HDR_ASSERT_OLD = "static_assert(TanHi > TanLo && LiftHi > LiftLo && RoofHi > RoofLo);"
HDR_ASSERT_NEW = ("static_assert(TanHi > TanLo && LiftHi > LiftLo && CoverHi > CoverLo && CoverRate > 0.0f &&\n"
                  "              CoverRate <= 1.0f && CoverRadius > CoverNear);")
HDR_RAW_OLD = '''/// upwind rays (-RayDeg, 0, +RayDeg) is the leeward value, the roof above the cell adds to it:
/// 1 - (1 - leeward) (1 - RoofGain roof). `cam_y`: the camera's height, which gives the ground of a
/// cell nothing is known about (cam_y - NoGround).
template <class ColumnFn>
[[nodiscard]] float Raw(ColumnFn&& column, int cx, int cz, float dir_x, float dir_z, float cam_y) {
'''
HDR_RAW_NEW = '''/// upwind rays (-RayDeg, 0, +RayDeg) is the leeward value, the cover (0-1, r117b: what the camera saw
/// overhead; the biggest of the cell and its 8 neighbours; a cell's own height gives no roof) adds
/// to it: 1 - (1 - leeward) (1 - cover). `cam_y`: the camera's height, which gives the ground of a
/// cell nothing is known about (cam_y - NoGround).
template <class ColumnFn>
[[nodiscard]] float Raw(ColumnFn&& column, int cx, int cz, float dir_x, float dir_z, float cam_y,
                        float cover = 0.0f) {
'''
HDR_TAIL_OLD = '''    const float roof = own.seen ? BbWind::Smoothstep(RoofLo, RoofHi, own.top - ground) : 0.0f;
    return 1.0f - (1.0f - leeward) * (1.0f - RoofGain * roof);
'''
HDR_TAIL_NEW = "    return 1.0f - (1.0f - leeward) * (1.0f - cover);\n"
HDR_COVER_ANCHOR = "/// wind_shelter.comp's push constants (128 bytes"
HDR_COVER_BEFORE = '''// ---- the cover (r117b: indoors, measured at the camera) -------------------------------------

/// A view ray (any length, world) climbs steeply enough to count: its elevation's tangent is above
/// CoverTan.
[[nodiscard]] inline bool CoverRayUp(float dx, float dy, float dz) {
    return dy > CoverTan * std::sqrt(dx * dx + dz * dz);
}

/// The share of the climbing rays (`up` of them) that ended within CoverDist (`covered`).
[[nodiscard]] inline float CoverShare(std::uint32_t up, std::uint32_t covered) {
    return up != 0 ? float(covered) / float(up) : 0.0f;
}

/// The camera's smoothed covered share after a frame: fewer than CoverMin climbing rays: the old
/// value stands; the first measure (`first`) is taken whole; else a time constant of CoverTau.
[[nodiscard]] inline float CoverFollow(float prev, std::uint32_t up, std::uint32_t covered, float dt,
                                       bool first) {
    if (up < CoverMin) {
        return prev;
    }
    const float k = first ? 1.0f : 1.0f - std::exp(-dt * (1.0f / CoverTau));
    return prev + (CoverShare(up, covered) - prev) * k;
}

/// The cover the cells take from the smoothed share.
[[nodiscard]] inline float CoverIndoors(float share) {
    return BbWind::Smoothstep(CoverLo, CoverHi, share);
}

/// One cache cell's cover after a frame: `away` m from the camera, `samples` depth samples of the
/// cell in this frame; the cells next to the camera take `indoors` outright, a cell seen within
/// CoverRadius moves toward it by CoverRate, any other keeps what it had.
[[nodiscard]] inline float CoverCell(float cover, float indoors, float away, std::uint32_t samples) {
    if (away < CoverNear * Cell) {
        return indoors;
    }
    if (samples >= MinSamples && away < CoverRadius * Cell) {
        return cover + (indoors - cover) * CoverRate;
    }
    return cover;
}

'''
HDR_D_OLD = "    const auto d = [&](std::uint32_t w) { return std::uint64_t(std::uint32_t(now[w] - before[w])); };\n"
HDR_D_NEW = '''    const auto d64 = [&](std::uint32_t lo, std::uint32_t hi) { // a total in two words (r117b)
        return ((std::uint64_t(now[hi]) << 32) | now[lo]) -
               ((std::uint64_t(before[hi]) << 32) | before[lo]);
    };
'''
HDR_SUM_OLD = "            d(WS_C_PIXELS_SUM),     d(WS_C_CELLS_SEEN),       d(WS_C_CELLS_SHELTERED),\n"
HDR_SUM_NEW = "            d64(WS_C_PIXELS_SUM, WS_C_PIXELS_SUM_HI), d(WS_C_CELLS_SEEN), d(WS_C_CELLS_SHELTERED),\n"

VK_SIZE_OLD = "                      vk::DeviceSize(WS_M) * WS_M * (WS_CELL_WORDS + WS_FRESH_WORDS) * 4, false,\n"
VK_SIZE_NEW = ("                      (vk::DeviceSize(WS_M) * WS_M * (WS_CELL_WORDS + WS_FRESH_WORDS) + WS_GLOBAL_WORDS) *\n"
               "                          4,\n                      false,\n")
VK_DONE_OLD = "        if (stats.frames >= (reported ? LineFrames : FirstLineFrames)) {\n"
VK_DONE_NEW = ("        // the first line after FirstLineFrames passes (the hook also runs through the loading screen,\n"
               "        // where nothing is drawn), or after LineFrames frames whatever happened\n"
               "        if (stats.frames >= LineFrames || (!reported && stats.passes >= FirstLineFrames)) {\n")
VK_FMT_OLD = '                     "(above 0.95), mean %.3f; at the camera %.2f\\n",\n'
VK_FMT_NEW = '                     "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f)\\n",\n'
VK_ARG_OLD = "                     BbWindShelter::ViewMean(c), double(1.0f - CameraOpen()));\n"
VK_ARG_NEW = ("                     BbWindShelter::ViewMean(c), double(1.0f - CameraOpen()),\n"
              "                     double(BbWindShelter::CoverIndoors(cover_share)), double(cover_share));\n")
# review fix: WS_C_COVER holds the smoothed SHARE (0.64 under the graveyard's canopies is right and maps
# to cover 0); the log prints the mapped cover the job labels expect, and the share beside it
VK_SHARE_ANCHOR = "    const double cells = std::max(1.0, double(c.cells));\n"
VK_SHARE_AFTER = ("    // r117b: the camera's smoothed covered share (WS_C_COVER) and the cover it maps to\n"
                  "    const float cover_share = BbWindShelter::CameraShelter(now[WS_C_COVER]);\n")

TEST_PAV_OLD = '''    // a roofed cell with open sides: only the roof's half
    const float pavilion = Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f);
    Expect(pavilion > 0.4f && pavilion < 0.5f, "an open pavilion: about 0.46");
'''
TEST_PAV_NEW = '''    // r117b: a tall cell gives its own cell no roof; only the cover (what the camera saw overhead) does
    Expect(Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "a tall cell alone in the open: 0");
    Expect(Raw(Pavilion, 0, 0, 1.0f, 0.0f, 1.7f, 1.0f) == 1.0f, "cover 1: 1");
    Expect(Near(Raw(Flat, 5, 0, 1.0f, 0.0f, 1.7f, 0.5f), 0.5f, 1e-6f), "open ground, cover 0.5: 0.5");
    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.3f), 1.0f, 1e-6f), "behind a wall with cover: still 1");
    Expect(Near(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f, 0.5f), 1.0f - (1.0f - 0.198f) * 0.5f, 0.01f),
           "the lee and the cover combine as 1 - (1 - lee)(1 - cover)");
    Expect(Raw(Tomb, 18, 0, 1.0f, 0.0f, 1.7f) < 0.01f && Raw(Wall, 5, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "open ground by a tomb or in front of a wall: still open");
'''
TEST_NS_ANCHOR = "} // namespace\n\nint main() {\n"
TEST_NS_BEFORE = '''// r117b: the camera's cover
void TestCover() {
    Expect(CoverRayUp(0.0f, 1.0f, 1.0f) && !CoverRayUp(1.0f, 0.1f, 0.0f) && !CoverRayUp(3.0f, 1.0f, 4.0f) &&
               CoverRayUp(3.0f, 2.0f, 4.0f) && CoverRayUp(0.0f, 1.0f, 0.0f) && !CoverRayUp(0.0f, -1.0f, 1.0f),
           "a ray climbs when its elevation's tangent is above 0.35");
    Expect(CoverShare(0, 0) == 0.0f && Near(CoverShare(200, 150), 0.75f, 1e-6f), "the covered share");
    Expect(CoverFollow(0.3f, 10, 10, 0.1f, false) == 0.3f && CoverFollow(0.3f, 63, 63, 0.1f, true) == 0.3f,
           "fewer than 64 climbing rays: no news");
    Expect(CoverFollow(0.0f, 100, 100, 0.0f, true) == 1.0f, "the first measure is taken whole");
    Expect(Near(CoverFollow(0.0f, 100, 100, CoverTau, false), 0.632f, 0.001f), "a time constant of 0.4 s");
    Expect(CoverFollow(0.5f, 100, 50, 0.0f, false) == 0.5f, "no time passed: no step");
    Expect(CoverIndoors(0.0f) == 0.0f && CoverIndoors(0.7f) == 0.0f && CoverIndoors(0.95f) == 1.0f &&
               CoverIndoors(1.0f) == 1.0f && CoverIndoors(0.45f) == 0.0f,
           "a share above 0.95 is indoors, below 0.7 is not");
    Expect(CoverIndoors(0.825f) > 0.49f && CoverIndoors(0.825f) < 0.51f, "half way: half");
    Expect(CoverCell(0.2f, 1.0f, 1.0f, 0) == 1.0f && CoverCell(0.9f, 0.0f, 2.0f, 0) == 0.0f,
           "the cells next to the camera take the cover outright, seen or not");
    Expect(CoverCell(0.0f, 1.0f, 10.0f, 0) == 0.0f && CoverCell(0.0f, 1.0f, 10.0f, 1) == 0.0f,
           "a cell not seen (fewer than 2 samples) keeps what it had");
    Expect(Near(CoverCell(0.0f, 1.0f, 10.0f, 5), 0.25f, 1e-6f), "a cell seen moves 25% toward it");
    Expect(CoverCell(0.0f, 1.0f, 17.0f, 50) == 0.0f && CoverCell(1.0f, 0.0f, 17.0f, 50) == 1.0f,
           "a cell seen beyond 16 m keeps what it had (it may be seen through a door)");
    float cell = 0.0f;
    for (int i = 0; i < 12; ++i) { // 12 frames seen from indoors
        cell = CoverCell(cell, 1.0f, 8.0f, 9);
    }
    Expect(cell > 0.96f, "a dozen frames seen indoors: covered");
    for (int i = 0; i < 12; ++i) { // seen again from the open
        cell = CoverCell(cell, 0.0f, 8.0f, 9);
    }
    Expect(cell < 0.04f, "and as many seen from the open: open again");
}

'''
TEST_MAIN_OLD = "    TestCounts();\n    if (failures != 0) {\n"
TEST_MAIN_NEW = "    TestCounts();\n    TestCover();\n    if (failures != 0) {\n"
TEST_HI_ANCHOR = "    const Counts none{};\n"
TEST_HI_BEFORE = '''    // r117b: the sum is a 64-bit total, the high word carries (it wrapped at 2^32 in the b28 log)
    before = {};
    now = {};
    before[WS_C_PIXELS_SUM] = 0xfffffff0u;
    now[WS_C_PIXELS_SUM] = 5;
    now[WS_C_PIXELS_SUM_HI] = 1;
    now[WS_C_PIXELS] = 10;
    c = CountsBetween(now.data(), before.data());
    Expect(c.sum == 21 && c.pixels == 10, "a carry word makes the sum 64 bits");
    before = {};
    now = {};
    now[WS_C_PIXELS] = 8565458;
    now[WS_C_PIXELS_SUM] = 0x2d2ea940u; // 5,053,000,000 - 2^32: alone it reads 0.088
    now[WS_C_PIXELS_SUM_HI] = 1;
    c = CountsBetween(now.data(), before.data());
    Expect(Near(float(ViewMean(c)), 0.59f, 0.01f), "the b28 graveyard's mean: about 0.59, not 0.086");
'''

README_OLD = ("a roof overhead adds (a hall gives 1, an open pavilion about a half), the result is blurred")
README_NEW = ("indoors is measured at the camera (of the view rays that climb above about 19 degrees, the share "
              "that ends on a surface within 80 m, 0.7 to 0.95 and up; a hall or a room gives 1, the open sky "
              "0; the cells seen within 16 m take it and keep it; a tree or a wall gives no roof of its own), "
              "the result is blurred")

EDITS = {
    LAY: [("rep", LAYOUT_ROOF_OLD, LAYOUT_ROOF_NEW),
          ("ins", LAYOUT_GLOBAL_ANCHOR, "", LAYOUT_GLOBAL_AFTER),
          ("ins", LAYOUT_COUNTER_ANCHOR, "", LAYOUT_COUNTER_AFTER)],
    COMP: [("rep", COMP_DOC_OLD, COMP_DOC_NEW),
           ("ins", COMP_COVER_ANCHOR, COMP_COVER_BEFORE, ""),
           ("rep", COMP_DIR_OLD, COMP_DIR_NEW),
           ("ins", COMP_FRESH_ANCHOR, "", COMP_FRESH_AFTER),
           ("ins", COMP_INIT_ANCHOR, "", COMP_INIT_AFTER),
           ("ins", COMP_LOOK_ANCHOR, COMP_LOOK_BEFORE, ""),
           ("rep", COMP_FLUSH_OLD, COMP_FLUSH_NEW),
           ("rep", COMP_SUM_OLD, COMP_SUM_NEW),
           ("rep", COMP_CAMERA_OLD, COMP_CAMERA_NEW),
           ("ins", COMP_REKEY_ANCHOR, "", COMP_REKEY_AFTER),
           ("ins", COMP_MERGE_ANCHOR, "", COMP_MERGE_AFTER),
           ("rep", COMP_ROOF_OLD, COMP_ROOF_NEW),
           ("ins", COMP_FINAL_ANCHOR, "", COMP_FINAL_AFTER),
           ("rep", COMP_SHOW_OLD, COMP_SHOW_NEW)],
    HDR: [("rep", HDR_CONST_OLD, HDR_CONST_NEW), ("rep", HDR_ASSERT_OLD, HDR_ASSERT_NEW),
          ("rep", HDR_RAW_OLD, HDR_RAW_NEW), ("rep", HDR_TAIL_OLD, HDR_TAIL_NEW),
          ("ins", HDR_COVER_ANCHOR, HDR_COVER_BEFORE, ""),
          ("ins", HDR_D_OLD, "", HDR_D_NEW),
          ("rep", HDR_SUM_OLD, HDR_SUM_NEW)],
    VKC: [("rep", VK_SIZE_OLD, VK_SIZE_NEW), ("rep", VK_DONE_OLD, VK_DONE_NEW),
          ("rep", VK_FMT_OLD, VK_FMT_NEW), ("rep", VK_ARG_OLD, VK_ARG_NEW),
          ("ins", VK_SHARE_ANCHOR, "", VK_SHARE_AFTER)],
    TST: [("rep", TEST_PAV_OLD, TEST_PAV_NEW), ("ins", TEST_NS_ANCHOR, TEST_NS_BEFORE, ""),
          ("rep", TEST_MAIN_OLD, TEST_MAIN_NEW), ("ins", TEST_HI_ANCHOR, TEST_HI_BEFORE, "")],
    RM: [("rep", README_OLD, README_NEW)],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (every edit's text there once), 'clean' (none), else refuse."""
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:70]))
        else:
            _, old, new = e
            if old in new:
                raise SystemExit("patch bug: a replacement holds its own old text: %r" % old[:50])
            no, nn = cur.count(old), cur.count(new)
            if no == 0 and nn == 1:
                done += 1
            elif no == 1 and nn == 0:
                todo += 1
            else:
                raise SystemExit("REFUSED %s: old text %d times, new text %d times (wanted 1 and 0, or 0 and 1): %r"
                                 % (path, no, nn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


# ---- the Python copy of the model: the numbers the test asserts, and the scenes -----------------
def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _ray(col, cx, cz, dx, dz, g):
    fx, fz, blocked, k = cx + 0.5, cz + 0.5, 0.0, 1
    while k <= 28 and blocked < 1.0:
        c = col(math.floor(fx + dx * k), math.floor(fz + dz * k))
        if c:
            ex, lift = max(c[1] - g - 1.0, 0.0), c[0] - g
            blocked = max(blocked, _ss(0.12, 0.40, ex / k) * (1.0 - _ss(1.2, 2.4, lift)))
        k += 1
    return blocked


def _rot(vx, vz, deg):
    a = math.radians(deg)
    return vx * math.cos(a) - vz * math.sin(a), vx * math.sin(a) + vz * math.cos(a)


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, roof_rule=False):
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g), _ray(col, cx, cz, -dx, -dz, g), _ray(col, cx, cz, c[0], c[1], g)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    if roof_rule:  # r117's rule, kept here only to show what it did
        roof = _ss(2.0, 3.2, own[1] - g) if own else 0.0
        return 1.0 - (1.0 - lee) * (1.0 - 0.5 * roof)
    return 1.0 - (1.0 - lee) * (1.0 - cover)


def _climb_share(hit_dist, fov_h=90.0, fov_v=59.0, pitch=0.0, w=160, h=90):
    """Share of the climbing view rays (tan > 0.35) that end within 80 m, for a camera at (0, 1.7, 0)
    looking along +x. hit_dist(dx, dy, dz) -> the distance to the first surface along the unit
    direction (inf: none, the sky)."""
    tx, ty = math.tan(math.radians(fov_h / 2)), math.tan(math.radians(fov_v / 2))
    up = cov = 0
    for j in range(h):
        for i in range(w):
            nx = ((i + 0.5) / w - 0.5) * 2.0
            ny = (0.5 - (j + 0.5) / h) * 2.0
            vx, vy, vz = 1.0, ny * ty, nx * tx
            cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
            vx, vy = vx * cp - vy * sp, vx * sp + vy * cp
            n = math.sqrt(vx * vx + vy * vy + vz * vz)
            vx, vy, vz = vx / n, vy / n, vz / n
            if vy > 0.35 * math.sqrt(vx * vx + vz * vz):
                up += 1
                if hit_dist(vx, vy, vz) < 80.0:
                    cov += 1
    return up, cov


def _box_hit(x0, x1, z0, z1, top):
    """Inside a box room (ground 0, ceiling `top`), camera at (0, 1.7, 0): distance to a wall or the ceiling."""
    def f(dx, dy, dz):
        t = []
        if dx > 0: t.append((x1 - 0.0) / dx)
        if dx < 0: t.append((x0 - 0.0) / dx)
        if dz > 0: t.append((z1 - 0.0) / dz)
        if dz < 0: t.append((z0 - 0.0) / dz)
        if dy > 0: t.append((top - 1.7) / dy)
        return min(t) if t else math.inf
    return f


def _open_hit(trees, tower_x=55.0):
    """Open ground: spherical canopies (cx, cy, cz, r), a tower wall at x = tower_x (12 m), sky else."""
    def f(dx, dy, dz):
        best = math.inf
        for (cx, cy, cz, r) in trees:
            ox, oy, oz = -cx, 1.7 - cy, -cz
            b = ox * dx + oy * dy + oz * dz
            c = ox * ox + oy * oy + oz * oz - r * r
            disc = b * b - c
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if t > 0:
                    best = min(best, t)
        if dx > 0:
            t = tower_x / dx
            if 1.7 + t * dy < 24.0:
                best = min(best, t)
        return best
    return f


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    post = lambda x, z: _col(0, 3) if (x, z) == (10, 0) else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    deck = lambda x, z: _col(5, 6) if x == 10 else _col(0, 0)
    room = lambda x, z: _col(0, 3) if -10 <= x <= 10 and -10 <= z <= 10 else None
    pavilion = lambda x, z: _col(0, 3) if (x, z) == (0, 0) else _col(0, 0)
    tree = lambda x, z: _col(0, 8) if (x, z) == (10, 0) else _col(0, 0)  # a trunk with its canopy
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 14", _raw(wall, 14, 0, 1, 0), 1.0, 1e-6), ("wall 16", _raw(wall, 16, 0, 1, 0), 0.857, 0.01),
        ("wall 20", _raw(wall, 20, 0, 1, 0), 0.198, 0.01), ("wall 26", _raw(wall, 26, 0, 1, 0), 0.0, 0.01),
        ("wall 30", _raw(wall, 30, 0, 1, 0), 0.0, 0.0), ("wall front", _raw(wall, 5, 0, 1, 0), 0.0, 0.0),
        ("wall along", _raw(wall, 12, 0, 0, 1), 0.0, 0.0), ("wall toward -x", _raw(wall, 7, 0, -1, 0), 1.0, 0.01),
        ("post 11", _raw(post, 11, 0, 1, 0), 1.0, 0.01), ("post 13", _raw(post, 13, 0, 1, 0), 0.0, 0.0),
        ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.857, 0.01), ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("deck", _raw(deck, 14, 0, 1, 0), 0.0, 0.0), ("room", _raw(room, 0, 0, 1, 0), 1.0, 1e-6),
        ("pavilion (no roof rule)", _raw(pavilion, 0, 0, 1, 0), 0.0, 0.0),
        ("pavilion, cover 1", _raw(pavilion, 0, 0, 1, 0, cover=1.0), 1.0, 0.0),
        ("open, cover 0.5", _raw(flat, 5, 0, 1, 0, cover=0.5), 0.5, 1e-6),
        ("wall 20, cover 0.5", _raw(wall, 20, 0, 1, 0, cover=0.5), 0.599, 0.01),
        ("a tree's own cell (r117: roof 0.5)", _raw(tree, 10, 0, 1, 0), 0.0, 0.0),
    ]
    for name, got, expect, tol in want:
        if abs(got - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, got, expect, tol))
    # what r117's roof rule gave: the tree cell 0.53, a 3 m wall's own cell 0.49, after the gain
    old_tree = min(_raw(tree, 10, 0, 1, 0, roof_rule=True) * 1.06, 1.0)
    old_wall = min(_raw(wall, 10, 0, 1, 0, roof_rule=True) * 1.06, 1.0)
    if not (0.52 < old_tree < 0.54 and 0.48 < old_wall < 0.54):
        raise SystemExit("model check: r117's roof rule gave %.3f / %.3f, expected about 0.5" % (old_tree, old_wall))
    k = 1.0 - math.exp(-1.0 / 0.5)
    if not 0.86 < k < 0.87:
        raise SystemExit("model check: a second's follow is %.4f" % k)
    return old_tree


def scene_checks():
    """The cover of the camera in three scenes, from synthetic view rays (the test jobs check the game)."""
    out = {}
    up, cov = _climb_share(_box_hit(-6.0, 14.0, -7.0, 7.0, 5.0))
    out["library"] = (up, cov, cov / up)
    up, cov = _climb_share(_box_hit(-30.0, 40.0, -20.0, 20.0, 22.0))
    out["hall 22 m"] = (up, cov, cov / up)
    trees = [(8, 7, -6, 3.0), (14, 8, 5, 3.5), (-6, 7, 10, 3.0)]
    up, cov = _climb_share(_open_hit(trees))
    out["graveyard"] = (up, cov, cov / up)
    up, cov = _climb_share(_open_hit([(14, 8, 5, 2.0)]))
    out["sparse trees"] = (up, cov, cov / up)
    up, cov = _climb_share(_open_hit([]))
    out["open"] = (up, cov, cov / up)
    up, cov = _climb_share(_open_hit([]), pitch=-25.0)
    out["looking down"] = (up, cov, 0.0)
    if not (out["library"][2] > 0.99 and out["hall 22 m"][2] > 0.95 and out["graveyard"][2] < 0.7 and
            out["sparse trees"][2] < 0.4 and out["open"][2] < 0.2):
        raise SystemExit("scene check: the cover shares are %s" % out)
    if _ss(0.70, 0.95, out["library"][2]) != 1.0 or _ss(0.70, 0.95, out["graveyard"][2]) != 0.0:
        raise SystemExit("scene check: library should map to 1 and the graveyard to 0: %s" % out)
    if out["looking down"][0] >= 64:
        raise SystemExit("scene check: a camera pitched down 25 degrees still has %d climbing rays" % out["looking down"][0])
    return out


def overflow_check():
    rows = []
    for name, pixels, shown in (("grave1", 8565458, 0.086), ("library", 8640000, 0.113), ("lamp1", 7979616, 0.082)):
        limit = 2 ** 32 / (pixels * 1000.0)
        true_mean = shown + limit
        rows.append((name, pixels, limit, shown, true_mean))
        if not (0.4 < limit < 0.6 and 0.5 < true_mean < 0.7):
            raise SystemExit("overflow check: %s: %s" % (name, rows[-1]))
    return rows


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_COVER_TAN 0.35f", "#define WS_COVER_DIST 80.0f", "#define WS_COVER_MIN 64u",
                 "#define WS_COVER_LO 0.70f", "#define WS_COVER_HI 0.95f", "#define WS_GLOBAL_WORDS 8u",
                 "#define WS_C_COVER 10u", "#define WS_C_PIXELS_SUM_HI 11u"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    for gone in ("WS_ROOF_", "RoofLo", "RoofGain"):
        for name, t in ((LAY, layout), (HDR, header), (COMP, comp), (TST, test)):
            if gone in t:
                raise SystemExit("text check: %s still holds %r" % (name, gone))
    if comp.count("GLOBAL_BASE") < 9 or comp.count("ray_dir(") != 2 or comp.count("WS_C_COVER") != 1:
        raise SystemExit("text check: the shader's cover code is not there as designed")
    if comp.count("cache_at(slot_of(c + ivec2(i, j)), 5u)") != 1 or "state.s[cw + 5u] = 0u;" not in comp:
        raise SystemExit("text check: the cover word 5 is not read and cleared")
    if "WS_COUNTER_WORDS 16u" not in layout:
        raise SystemExit("text check: the counter words changed")
    for line in vk.split("\n"):
        if "overhead cover" in line and len(line) > 120:
            raise SystemExit("text check: log line too long")
    if (vk.count("WS_GLOBAL_WORDS") != 1 or vk.count("stats.passes >= FirstLineFrames") != 1 or
            vk.count("cover_share") != 3):
        raise SystemExit("text check: vk_wind_shelter.cpp edits")
    # the C++ cover functions use the same names as the layout's numbers
    for want in ("CoverTan = WS_COVER_TAN", "CoverNear = WS_COVER_NEAR", "d64(WS_C_PIXELS_SUM, WS_C_PIXELS_SUM_HI)",
                 "float cover = 0.0f) {", "(1.0f - cover)"):
        if header.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (HDR, want))
    if texts[RM].count("a tree or a wall gives no roof of its own") != 1:
        raise SystemExit("text check: README")
    old_tree = model_checks()
    scenes = scene_checks()
    rows = overflow_check()
    return old_tree, scenes, rows


def report(res):
    old_tree, scenes, rows = res
    print("model: all asserted numbers pass; r117's roof rule gave a tree's / wall's own cell %.3f (the yellow)" % old_tree)
    for name, (up, cov, share) in scenes.items():
        print("scene %-13s climbing rays %5d, covered %5d, share %.3f -> cover %.2f" %
              (name, up, cov, share, _ss(0.70, 0.95, share)))
    for name, pixels, limit, shown, true_mean in rows:
        print("log mean %-8s %9d samples: 32-bit sum wraps above a mean of %.4f; logged %.3f -> true %.3f" %
              (name, pixels, limit, shown, true_mean))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117B_ROOT)" % ROOT)
    for need in (COMP, LAY, HDR, VKC, TST):
        if not os.path.exists(os.path.join(ROOT, need)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % need)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        raw, eol, cur = load(path)
        eds = EDITS[path]
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for e in eds:
                if e[0] == "ins":
                    cur = cur.replace(e[1], e[2] + e[1] + e[3])
                else:
                    cur = cur.replace(e[1], e[2])
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            res = text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks, the model's numbers and the scenes pass)")
        else:
            res = text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result, the "
                  "model's numbers and the scenes pass)" % (len(plan), sum(len(p[1]) for p in plan)))
        report(res)
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
            tmp = full + ".r117btmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for e in reversed(eds):
            if e[0] == "ins":
                for part in (e[3], e[2]):
                    if part:
                        cur = cur.replace(part, "", 1)
            else:
                cur = cur.replace(e[2], e[1], 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r117btmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
