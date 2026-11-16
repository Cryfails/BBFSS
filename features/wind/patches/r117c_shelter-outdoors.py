# r117c_shelter-outdoors: FEATURE fix on top of r117_wind-shelter and r117b_shelter-indoors (both applied
# and built, b30). Still off with r117's knob BB_WIND_SHELTER (no new knob): every edit is in r117's own
# files, which only exist or run with the knob (see "Off" below).
#
# WHAT b30 SHOWED (r117b-grave1, -grave1r, -lamp1, -none): indoors is right (library 100% sheltered, mean
# 0.998, at the camera 1.00, cover 1.00) and the lee flips with the wind direction (graveyard at the
# camera 0.98 -> 0.24). Open ground read too sheltered: graveyard 50-55% of the view above 0.5 (wanted
# 5-35), 23% above 0.95 ("indoors") on open ground, at the camera 0.83 / 0.98 standing in the open,
# overhead cover 0.22-0.27 with a covered share of 0.77-0.79, almost no green in the show view.
#
# CAUSES, found by reading the b30 log numbers against the shader and by a model of the passes (the
# numbers below come from this script's "check", which prints them):
#
#  1. THE COVERED SHARE COUNTED FAR WALLS AS ROOFS (the cause of the baseline: nothing in the open read 0).
#     A climbing view ray (above about 19 degrees) counted as covered when it ended on ANY surface within
#     80 m. In a graveyard the top strip of the view shows branches and, behind them, the dark walls of
#     the city 30-80 m away: 77-79% of the rays ended within 80 m, so the share was 0.77-0.79 and
#     smoothstep(0.70, 0.95) made it a cover of 0.19-0.27. That cover is added to every cell within 16 m
#     of the camera that the camera sees (raw = 1 - (1 - leeward)(1 - cover)), so open ground started
#     at 0.2-0.27 (yellow-green in the ramp, which is why nothing was green) and every lee value was
#     raised on top of it. (The lamp spot's share was 0.50: cover 0.00, so it had no baseline, and its
#     red came from causes 2 and 3.) FIX: a ray is covered when it ends within WS_COVER_CLOSE = 35 m of the
#     camera (a ceiling, a wall of a room, the first branches), or beyond that, within 80 m, on a surface
#     that FACES DOWN (the normal, from the depth, turned toward the camera, has y below -0.5: the
#     underside of a vault, a hall's ceiling, a roof, the underside of a canopy). A far wall in the
#     open (a courtyard's, the city's) faces sideways and no longer counts. The mapping becomes
#     smoothstep(0.80, 0.96). A hall's ceiling stays covered at any distance, a room's walls within 35 m
#     stay covered: the model below gives the library, small rooms and halls up to 34 x 24 x 18 m a share of
#     1.00, the graveyard-like open scene 0.57 (cover 0). LIMIT: a hall deeper than 35 m looked at along
#     its length has its far wall beyond 35 m, which is not an underside: those rays are not covered (the
#     r117b rule counted them; an 80 x 20 x 18 m nave still reads 0.95 from its ceiling). The log's new
#     third line shows where the rays end, to move the 35 m if the game's halls or yards need it.
#
#  2. A TREE OR A BUILDING SHELTERED LIKE A SKYSCRAPER. The cache keeps the lowest and highest height
#     seen in a 1 m cell. A tree (trunk to canopy, 7-9 m, the ground under the canopy seen too) is a
#     column 8 m tall: a ray blocks by smoothstep(0.12, 0.40, (top - ground - 1) / distance), so the
#     tree shelters fully within 17 m and still partly out to 28 m (the ray's length); with the canopies
#     5-6 cells wide all three rays meet it (the median does not drop it). A graveyard is full of them
#     (the b30 picture: the trees and the ground around them orange and red; 23% of the view above
#     0.95). FIX: WS_EFF_MAX = 2.0: an obstacle counts at most 2 m above the 1 m start, that is as a 3 m
#     wall: full shelter within 5 m, none beyond 17 m, a soft edge. Everything up to a 3 m wall gives the
#     same numbers as before (the tests' wall and tomb numbers are unchanged); a tall tree or building
#     is like a 3 m wall. (Bare branches ARE a poor wall; this is the simple cap, the porosity of a
#     canopy is not known to the cache: it keeps only the lowest and the highest height.)
#
#  3. THE HUNTER SHELTERED THE CAMERA (the camera's 0.83 / 0.98, and the yellow fan behind him in the
#     picture). The camera of this game stands 2.5-4.5 m behind the Hunter, who is a 1.9 m, 2 x 2 cell
#     column in the cache. His cells are 2-4 m upwind of the camera cell when the wind blows toward the
#     camera: eff 0.9 / 2 m: smoothstep gives 1.0; the three rays (+-14 degrees at 3 m: 0.75 m apart) all
#     meet two cells, the median is 1: the camera reads 0.98 (b30: wind from 225: 0.98; turned by 180
#     degrees the Hunter is downwind and the camera reads 0.24 = only the cover). The model's number for a
#     2 x 2 column 2-3 m upwind of the camera cell: 1.00 (below). The lee of a person is real but a
#     fraction of a metre long; the cache cannot tell a person from a tomb of the same height (it has
#     only the lowest and highest height of a 1 m cell). FIX: an obstacle LOWER than 2.0..2.6 m above its
#     ground that stands within 4..7 m of the camera (xz) counts for nothing there:
#     keep = max(smoothstep(2.0, 2.6, top - ground), smoothstep(4, 7, distance to the camera)); a block of
#     1.9 m 2-4 m from the camera is ignored, the same block 7 m or more away, or a tomb of 2.6 m and over,
#     counts in full (a graveyard's gravestones, tombs, walls, trees and pillars are as before; only the
#     stones within 4 m of the camera lose their short lee, which is continuous as the camera moves).
#
#  4. LAMP SPOT: the "grey sky" of b30's r117b-lamp1 is not the sky: the SHOW view paints the surfaces
#     OUTSIDE the field's window (more than 30 m away, but nearer than 90 m) a flat grey 0.2 and the sky
#     (no depth or beyond 90 m) black. Now outside the window is near black too (0.04) so the test view
#     shows only the field.
#
# THE MODEL (this script's check): a synthetic graveyard window (9 trees with 5x5 canopies 7-9 m, 60
# gravestones 1.2-1.8 m, 6 tombs 2-2.6 m, a 12 cell wall of 3 m, the Hunter 2x2 3 m from the camera, 60% of
# the cells known), 4 seeds x 2 winds in this script's check (8 x 4 in the longer run), share of the seen cells above 0.5 with no cover:
#   r117b (14 deg rays, no cap)   about 39%  (with the baseline cover 0.2-0.27 the b30 game gave 50-55%)
#   r117c (cap 2.0, Hunter rule)  about 25%
#
# LOG (new third line, once every 600 frames next to r117's two): "Wind shelter (r117c): N climbing view
# rays: X% ended within 35 m, Y% on a surface facing down (to 80 m), Z% on another surface within 80 m, W%
# on the sky or beyond": the covered share is X + Y (the numbers to tune the cover with).
#
# Off: nothing here runs without r117's knob: the shader is only built into the pass r117 makes
# (BbWindShelter::KnobOnce().on); the new constants and functions are in r117's own header; the log line is
# in r117's Report. BB_WIND off and BB_WIND_SHELTER off are unchanged.
# Cost on (estimates): the splat pass gains, for the climbing rays beyond 35 m (a few percent of the
# samples: the top strip of the view), two more depth reads and two world points (a normal): about 20
# multiply-adds on 1 in 30 samples; the ray loop gains two smoothsteps and a distance per cell the ray
# meets (the cells with something in them). Together far below 0.01 ms. Memory: none (four counter
# words that existed: the counter buffer has 16). CPU: one more log line a minute.
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row).
# Use: python -I -X utf8 r117c_shelter-outdoors.py check | apply | revert
# Root: R117C_ROOT, else <tree>. Line ends kept. Needs r117_wind-shelter and r117b applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117c_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAY_COVER_OLD = "#define WS_COVER_LO 0.70f\n#define WS_COVER_HI 0.95f\n"
LAY_COVER_NEW = "#define WS_COVER_LO 0.80f\n#define WS_COVER_HI 0.96f\n"
LAY_NOGROUND_ANCHOR = "#define WS_NO_GROUND 1.7f\n"
LAY_NOGROUND_AFTER = '''// r117c (open ground read sheltered, see r117c_shelter-outdoors.py): a climbing view ray is covered when it
// ends within WS_COVER_CLOSE m of the camera, or beyond that within WS_COVER_DIST m on a surface facing
// down (its normal, turned toward the camera, has y below -WS_DOWN_NY; the neighbour pixels used for it
// may differ in depth by at most WS_NORMAL_TOL of the distance). An obstacle counts for at most
// WS_EFF_MAX m above WS_H_START (a tree or a building shelters like a 3 m wall). An obstacle lower than
// WS_NEAR_TOP_LO..HI above its ground that stands within WS_NEAR_CAM_LO..HI m of the camera (the Hunter)
// counts for nothing: keep = max(smoothstep(TOP_LO, TOP_HI, height), smoothstep(CAM_LO, CAM_HI, distance)).
#define WS_COVER_CLOSE 35.0f
#define WS_DOWN_NY 0.5f
#define WS_NORMAL_TOL 0.08f
#define WS_EFF_MAX 2.0f
#define WS_NEAR_TOP_LO 2.0f
#define WS_NEAR_TOP_HI 2.6f
#define WS_NEAR_CAM_LO 4.0f
#define WS_NEAR_CAM_HI 7.0f
'''
LAY_COUNTER_ANCHOR = "#define WS_C_PIXELS_SUM_HI 11u // carry of WS_C_PIXELS_SUM: with it a 64-bit total (r117b)\n"
LAY_COUNTER_AFTER = '''#define WS_C_UP 12u            // climbing view rays (r117c)
#define WS_C_CLOSE 13u         // of them ending within WS_COVER_CLOSE m
#define WS_C_DOWN 14u          // of them ending beyond that on a surface facing down, within WS_COVER_DIST
#define WS_C_MID 15u           // of them ending on another surface within WS_COVER_DIST (the rest: sky or beyond)
'''

COMP_DOC_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_DOC_BEFORE = '''//  r117c  the cover counts a climbing ray that ends within WS_COVER_CLOSE m or, beyond that, on a surface
//         that faces down (a ceiling, a vault, a canopy's underside: faces_down); an obstacle counts at
//         most WS_EFF_MAX above WS_H_START; a low obstacle within WS_NEAR_CAM m of the camera (the
//         Hunter) is not counted (keep in ray()). Four counter words say where the rays ended.
'''
COMP_SHARED_OLD = "shared uint g_pixels, g_sheltered, g_sum, g_indoor, g_up, g_covered;\n"
COMP_SHARED_NEW = '''// r117c: does the surface the depth pixel `px` shows (at `hit`, view depth z) face down? Its normal is
// the cross product of the steps to the pixels 2 to the right and 2 down, turned toward the camera;
// a neighbour that is no surface or a different one (view depth differing by more than WS_NORMAL_TOL)
// gives no normal: not facing down.
bool faces_down(ivec2 px, ivec2 size, vec3 hit, float z) {
    const ivec2 pr = min(px + ivec2(2, 0), size - 1);
    const ivec2 pd = min(px + ivec2(0, 2), size - 1);
    const float dr = texelFetch(depth_tex, pr, 0).r;
    const float dd = texelFetch(depth_tex, pd, 0).r;
    if (!(dr > 0.0 && dr < 1.0 && dd > 0.0 && dd < 1.0)) {
        return false;
    }
    const float zr = view_z(dr);
    const float zd = view_z(dd);
    if (!(zr > 0.0 && zd > 0.0) || abs(zr - z) > WS_NORMAL_TOL * z || abs(zd - z) > WS_NORMAL_TOL * z) {
        return false;
    }
    vec3 n = cross(world_of(vec2(pr) + 0.5, dr) - hit, world_of(vec2(pd) + 0.5, dd) - hit);
    const float len = length(n);
    if (!(len > 1.0e-12)) {
        return false;
    }
    n *= 1.0 / len;
    if (dot(n, vec3(row0.w, row1.w, row2.w) - hit) < 0.0) {
        n = -n;
    }
    return n.y < -WS_DOWN_NY;
}

shared uint g_pixels, g_sheltered, g_sum, g_indoor, g_up, g_covered, g_close, g_down, g_mid;
'''
COMP_INIT_ANCHOR = "        g_covered = 0u;\n"
COMP_INIT_AFTER = "        g_close = 0u;\n        g_down = 0u;\n        g_mid = 0u;\n"
COMP_HIT_OLD = '''            if (depth > 0.0 && depth < 1.0 && view_z(depth) > 0.0) {
                const vec3 hit = world_of(vec2(px) + 0.5, depth);
                if (distance(hit, vec3(row0.w, row1.w, row2.w)) < WS_COVER_DIST) {
                    atomicAdd(g_covered, 1u);
                }
            }
'''
COMP_HIT_NEW = '''            if (depth > 0.0 && depth < 1.0 && view_z(depth) > 0.0) {
                const float zc = view_z(depth);
                const vec3 hit = world_of(vec2(px) + 0.5, depth);
                const float away = distance(hit, vec3(row0.w, row1.w, row2.w));
                if (away < WS_COVER_CLOSE) {
                    atomicAdd(g_close, 1u);
                    atomicAdd(g_covered, 1u);
                } else if (away < WS_COVER_DIST) {
                    // (r117c) beyond that only an underside counts: a ceiling, a vault, a canopy
                    if (faces_down(px, size, hit, zc)) {
                        atomicAdd(g_down, 1u);
                        atomicAdd(g_covered, 1u);
                    } else {
                        atomicAdd(g_mid, 1u);
                    }
                }
            }
'''
COMP_FLUSH_ANCHOR = "            atomicAdd(state.s[GLOBAL_BASE + 1u], g_covered);\n"
COMP_FLUSH_AFTER = '''            atomicAdd(counters.c[WS_C_UP], g_up);
            atomicAdd(counters.c[WS_C_CLOSE], g_close);
            atomicAdd(counters.c[WS_C_DOWN], g_down);
            atomicAdd(counters.c[WS_C_MID], g_mid);
'''
COMP_RAY_OLD = '''            const float eff = max(col.y - ground - WS_H_START, 0.0);
            const float lift = col.x - ground;
            const float pass_ = 1.0 - smoothstep(WS_LIFT_LO, WS_LIFT_HI, lift);
            blocked = max(blocked, smoothstep(WS_TAN_LO, WS_TAN_HI, eff / dist) * pass_);
'''
COMP_RAY_NEW = '''            // r117c: an obstacle counts at most WS_EFF_MAX above the start (a tree is a 3 m wall), and a
            // low one near the camera (the Hunter) not at all
            const float eff = min(max(col.y - ground - WS_H_START, 0.0), WS_EFF_MAX);
            const float lift = col.x - ground;
            const float pass_ = 1.0 - smoothstep(WS_LIFT_LO, WS_LIFT_HI, lift);
            const float keep =
                max(smoothstep(WS_NEAR_TOP_LO, WS_NEAR_TOP_HI, col.y - ground),
                    smoothstep(WS_NEAR_CAM_LO, WS_NEAR_CAM_HI,
                               distance((vec2(c) + 0.5) * WS_CELL, vec2(row0.w, row2.w))));
            blocked = max(blocked, smoothstep(WS_TAN_LO, WS_TAN_HI, eff / dist) * pass_ * keep);
'''
COMP_SHOW_OLD = "        imageStore(scene_img, px, vec4(inside ? ramp(v) * 1.5 : vec3(0.2), scene.a));\n"
COMP_SHOW_NEW = "        imageStore(scene_img, px, vec4(inside ? ramp(v) * 1.5 : vec3(0.04), scene.a));\n"

HDR_CONST_ANCHOR = "inline constexpr std::uint32_t CoverMin = WS_COVER_MIN, GlobalWords = WS_GLOBAL_WORDS;\n"
HDR_CONST_AFTER = '''inline constexpr float CoverClose = WS_COVER_CLOSE, DownNy = WS_DOWN_NY, NormalTol = WS_NORMAL_TOL,
                       EffMax = WS_EFF_MAX, NearTopLo = WS_NEAR_TOP_LO, NearTopHi = WS_NEAR_TOP_HI,
                       NearCamLo = WS_NEAR_CAM_LO, NearCamHi = WS_NEAR_CAM_HI; // r117c
'''
HDR_KEEP_ANCHOR = "/// A ray from the middle of cell (cx, cz) UPWIND along (dx, dz) (a unit vector): how far it is\n"
HDR_KEEP_BEFORE = '''/// r117c: how much an obstacle counts: 0 for a low one (`top_above_ground` under NearTopLo..NearTopHi: the
/// Hunter, a person) that stands within NearCamLo..NearCamHi m of the camera (`dist_cam`, xz), 1 else.
[[nodiscard]] inline float NearKeep(float top_above_ground, float dist_cam) {
    return std::max(BbWind::Smoothstep(NearTopLo, NearTopHi, top_above_ground),
                    BbWind::Smoothstep(NearCamLo, NearCamHi, dist_cam));
}

'''
HDR_SIG_OLD = ("[[nodiscard]] float RayBlocked(ColumnFn&& column, int cx, int cz, float dx, float dz,\n"
               "                               float ground) {\n")
HDR_SIG_NEW = ("[[nodiscard]] float RayBlocked(ColumnFn&& column, int cx, int cz, float dx, float dz,\n"
               "                               float ground, float cam_x = 1.0e9f, float cam_z = 1.0e9f) {\n")
HDR_EXC_OLD = "            const float excess = std::max(col.top - ground - HStart, 0.0f);\n"
HDR_EXC_NEW = ("            // r117c: at most EffMax (a tree is a 3 m wall), and a low obstacle near the camera not at all\n"
               "            const float excess = std::min(std::max(col.top - ground - HStart, 0.0f), EffMax);\n")
HDR_BLK_OLD = "            blocked = std::max(blocked, BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass);\n"
HDR_BLK_NEW = '''            const float keep = NearKeep(col.top - ground, std::hypot((float(ix) + 0.5f) * Cell - cam_x,
                                                                      (float(iz) + 0.5f) * Cell - cam_z));
            blocked = std::max(blocked, BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass * keep);
'''
HDR_RAWSIG_OLD = "                        float cover = 0.0f) {\n"
HDR_RAWSIG_NEW = "                        float cover = 0.0f, float cam_x = 1.0e9f, float cam_z = 1.0e9f) {\n"
HDR_RAYS_OLD = '''    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground);
'''
HDR_RAYS_NEW = '''    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground, cam_x, cam_z);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground, cam_x, cam_z);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground, cam_x, cam_z);
'''
HDR_HIT_ANCHOR = "/// The share of the climbing rays (`up` of them) that ended within CoverDist (`covered`).\n"
HDR_HIT_BEFORE = '''/// r117c: a climbing view ray that ended `dist` m from the camera on a surface whose normal (unit, turned
/// toward the camera) has y `normal_y` is covered: within CoverClose of any surface, or beyond that, within
/// CoverDist, on one that faces down (normal y below -DownNy: a ceiling, a vault, a canopy's underside).
[[nodiscard]] inline bool CoverHit(float dist, float normal_y) {
    return dist < CoverClose || (dist < CoverDist && normal_y < -DownNy);
}

'''
HDR_CNT_OLD = "    std::uint64_t cells_seen = 0, cells_sheltered = 0, cells = 0, cells_sum = 0, merged = 0;\n"
HDR_CNT_ANCHOR = HDR_CNT_OLD
HDR_CNT_AFTER = ("    std::uint64_t climb_up = 0, climb_close = 0, climb_down = 0, climb_mid = 0; ///< r117c\n")
HDR_CNTB_OLD = "            d(WS_C_CELLS),          d(WS_C_CELLS_SUM),        d(WS_C_MERGED)};\n"
HDR_CNTB_NEW = ("            d(WS_C_CELLS),          d(WS_C_CELLS_SUM),        d(WS_C_MERGED),\n"
                "            d(WS_C_UP),             d(WS_C_CLOSE),            d(WS_C_DOWN),\n"
                "            d(WS_C_MID)};\n")

VK_ANCHOR = "                     stats.no_camera, stats.no_scene);\n"
VK_AFTER = '''    // r117c: where the climbing view rays ended (the camera's cover is made from the ones in the first two
    // groups); the rest ended on the sky, a dome or beyond 80 m
    const double up = std::max(1.0, double(c.climb_up));
    BbReport::Printf("Wind shelter (r117c): %llu climbing view rays: %.1f%% ended within %.0f m, %.1f%% on "
                     "a surface facing down (to %.0f m), %.1f%% on another surface within %.0f m, %.1f%% "
                     "on the sky or beyond\\n",
                     ull(c.climb_up), 100.0 * double(c.climb_close) / up, double(WS_COVER_CLOSE),
                     100.0 * double(c.climb_down) / up, double(WS_COVER_DIST),
                     100.0 * double(c.climb_mid) / up, double(WS_COVER_DIST),
                     100.0 * (up - double(c.climb_close + c.climb_down + c.climb_mid)) / up);
'''

TEST_COVER_OLD = '''    Expect(CoverIndoors(0.0f) == 0.0f && CoverIndoors(0.7f) == 0.0f && CoverIndoors(0.95f) == 1.0f &&
               CoverIndoors(1.0f) == 1.0f && CoverIndoors(0.45f) == 0.0f,
           "a share above 0.95 is indoors, below 0.7 is not");
    Expect(CoverIndoors(0.825f) > 0.49f && CoverIndoors(0.825f) < 0.51f, "half way: half");
'''
TEST_COVER_NEW = '''    Expect(CoverIndoors(0.0f) == 0.0f && CoverIndoors(0.8f) == 0.0f && CoverIndoors(0.96f) == 1.0f &&
               CoverIndoors(1.0f) == 1.0f && CoverIndoors(0.45f) == 0.0f && CoverIndoors(0.78f) == 0.0f,
           "a share above 0.96 is indoors, below 0.8 is not (r117c: the graveyard's 0.77-0.79 is open)");
    Expect(CoverIndoors(0.88f) > 0.49f && CoverIndoors(0.88f) < 0.51f, "half way: half");
'''
TEST_FN_ANCHOR = "// r117b: the camera's cover\nvoid TestCover() {\n"
TEST_FN_BEFORE = '''// r117c: open ground reads open, the Hunter does not shelter the camera, indoors is as before
Column Person(int x, int z) { // the Hunter: 2 x 2 cells, 1.9 m, at x 8..9
    return x >= 8 && x <= 9 && z >= -1 && z <= 0 ? ColumnOf(0.0f, 1.9f) : ColumnOf(0.0f, 0.0f);
}
Column BigTomb(int x, int z) { // the same block, 2.6 m high
    return x >= 8 && x <= 9 && z >= -1 && z <= 0 ? ColumnOf(0.0f, 2.6f) : ColumnOf(0.0f, 0.0f);
}
Column TallWall(int x, int z) { // a wall 9 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 9.0f) : ColumnOf(0.0f, 0.0f);
}
Column Tree(int x, int z) { // a trunk with its canopy: 5 x 5 cells, 8 m (the ground under it seen too)
    return x >= 8 && x <= 12 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}

void TestOutdoors() {
    // an obstacle counts at most as a 3 m wall: a 9 m wall gives the 3 m wall's numbers
    Expect(Near(Raw(TallWall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "6 m behind a 9 m wall: as behind a 3 m one");
    Expect(Near(Raw(TallWall, 20, 0, 1.0f, 0.0f, 1.7f), 0.198f, 0.01f), "10 m behind it: 0.2");
    Expect(Raw(TallWall, 27, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(TallWall, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "17 m behind it: 0 (was 28 m before the cap), right behind it: 1");
    Expect(Near(Raw(Tree, 21, 0, 1.0f, 0.0f, 1.7f), 0.30f, 0.05f) && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "a tree: sheltered close behind it, 0.3 at 9 m (r117b: 1.0 there)");
    // the Hunter: a low block 2-3 m upwind of the camera cell is ignored, only near the camera
    const float cx = 11.5f, cz = 0.5f; // the camera in the middle of cell (11, 0)
    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "without the camera's place the block shelters (r117b)");
    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) == 0.0f, "the Hunter next to the camera: ignored");
    Expect(Raw(BigTomb, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) > 0.99f, "a 2.6 m block next to it still shelters");
    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f) > 0.99f,
           "the same low block with the camera 19 m away shelters as before");
    Expect(NearKeep(1.9f, 2.0f) == 0.0f && NearKeep(2.6f, 2.0f) == 1.0f && NearKeep(1.9f, 7.0f) == 1.0f &&
               Near(NearKeep(1.9f, 5.5f), 0.5f, 1e-6f) && Near(NearKeep(2.3f, 2.0f), 0.5f, 1e-6f),
           "the keep weight");
    Expect(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) > 0.99f &&
               Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.857f, 0.01f),
           "a 3 m wall near the camera shelters in full (3 m is not low)");
    // the covered rays
    Expect(CoverHit(10.0f, 0.0f) && CoverHit(34.9f, 0.9f) && !CoverHit(40.0f, 0.0f) && !CoverHit(40.0f, 0.4f) &&
               CoverHit(40.0f, -0.6f) && CoverHit(79.0f, -0.9f) && !CoverHit(80.0f, -0.9f) && !CoverHit(60.0f, 0.9f),
           "a ray is covered within 35 m, or on a surface facing down within 80 m; a far wall is not");
}

'''
TEST_MAIN_OLD = "    TestCover();\n    if (failures != 0) {\n"
TEST_MAIN_NEW = "    TestCover();\n    TestOutdoors();\n    if (failures != 0) {\n"
TEST_CNT_ANCHOR = "    const Counts none{};\n"
TEST_CNT_BEFORE = '''    // r117c: where the climbing rays ended
    before = {};
    now = {};
    now[WS_C_UP] = 1000;
    now[WS_C_CLOSE] = 200;
    now[WS_C_DOWN] = 100;
    now[WS_C_MID] = 450;
    c = CountsBetween(now.data(), before.data());
    Expect(c.climb_up == 1000 && c.climb_close == 200 && c.climb_down == 100 && c.climb_mid == 450,
           "the climbing rays' counts, word by word");
'''

README_A_OLD = "the share that ends on a surface within 80 m, 0.7 to 0.95 and up;"
README_A_NEW = ("the share that ends within 35 m or, within 80 m, on a surface that faces down (a ceiling, a vault, "
                "a canopy's underside), 0.8 to 0.96 and up;")
README_B_OLD = "a post or a person shelters hardly)"
README_B_NEW = ("a post or a person shelters hardly, a low obstacle within a few metres of the camera is ignored, "
                "and a tall tree or building shelters like a 3 m wall)")

EDITS = {
    LAY: [("rep", LAY_COVER_OLD, LAY_COVER_NEW),
          ("ins", LAY_NOGROUND_ANCHOR, "", LAY_NOGROUND_AFTER),
          ("ins", LAY_COUNTER_ANCHOR, "", LAY_COUNTER_AFTER)],
    COMP: [("ins", COMP_DOC_ANCHOR, COMP_DOC_BEFORE, ""),
           ("rep", COMP_SHARED_OLD, COMP_SHARED_NEW),
           ("ins", COMP_INIT_ANCHOR, "", COMP_INIT_AFTER),
           ("rep", COMP_HIT_OLD, COMP_HIT_NEW),
           ("ins", COMP_FLUSH_ANCHOR, "", COMP_FLUSH_AFTER),
           ("rep", COMP_RAY_OLD, COMP_RAY_NEW),
           ("rep", COMP_SHOW_OLD, COMP_SHOW_NEW)],
    HDR: [("ins", HDR_CONST_ANCHOR, "", HDR_CONST_AFTER),
          ("ins", HDR_KEEP_ANCHOR, HDR_KEEP_BEFORE, ""),
          ("rep", HDR_SIG_OLD, HDR_SIG_NEW), ("rep", HDR_EXC_OLD, HDR_EXC_NEW), ("rep", HDR_BLK_OLD, HDR_BLK_NEW),
          ("rep", HDR_RAWSIG_OLD, HDR_RAWSIG_NEW), ("rep", HDR_RAYS_OLD, HDR_RAYS_NEW),
          ("ins", HDR_HIT_ANCHOR, HDR_HIT_BEFORE, ""),
          ("ins", HDR_CNT_ANCHOR, "", HDR_CNT_AFTER), ("rep", HDR_CNTB_OLD, HDR_CNTB_NEW)],
    VKC: [("ins", VK_ANCHOR, "", VK_AFTER)],
    TST: [("rep", TEST_COVER_OLD, TEST_COVER_NEW), ("ins", TEST_FN_ANCHOR, TEST_FN_BEFORE, ""),
          ("rep", TEST_MAIN_OLD, TEST_MAIN_NEW), ("ins", TEST_CNT_ANCHOR, TEST_CNT_BEFORE, "")],
    RM: [("rep", README_A_OLD, README_A_NEW), ("rep", README_B_OLD, README_B_NEW)],
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


# ---- the Python copy of the model: the numbers the tests assert, and the scenes -----------------
def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _keep(top_above, dist_cam):
    return max(_ss(2.0, 2.6, top_above), _ss(4.0, 7.0, dist_cam))


def _ray(col, cx, cz, dx, dz, g, eff_max, cam, deg_rule):
    fx, fz, blocked, k = cx + 0.5, cz + 0.5, 0.0, 1
    while k <= 28 and blocked < 1.0:
        ix, iz = math.floor(fx + dx * k), math.floor(fz + dz * k)
        c = col(ix, iz)
        if c:
            ex, lift = min(max(c[1] - g - 1.0, 0.0), eff_max), c[0] - g
            keep = 1.0
            if deg_rule:
                keep = _keep(c[1] - g, math.hypot((ix + 0.5) - cam[0], (iz + 0.5) - cam[1]))
            blocked = max(blocked, _ss(0.12, 0.40, ex / k) * (1.0 - _ss(1.2, 2.4, lift)) * keep)
        k += 1
    return blocked


def _rot(vx, vz, deg):
    a = math.radians(deg)
    return vx * math.cos(a) - vz * math.sin(a), vx * math.sin(a) + vz * math.cos(a)


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, new=True, cam=(1e9, 1e9)):
    """new False: r117b (no cap, no Hunter rule); True: r117c."""
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    em = 2.0 if new else 1e9
    r = [_ray(col, cx, cz, a[0], a[1], g, em, cam, new), _ray(col, cx, cz, -dx, -dz, g, em, cam, new),
         _ray(col, cx, cz, c[0], c[1], g, em, cam, new)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    return 1.0 - (1.0 - lee) * (1.0 - cover)


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    tall = lambda x, z: _col(0, 9) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    tree = lambda x, z: _col(0, 8) if 8 <= x <= 12 and -2 <= z <= 2 else _col(0, 0)
    person = lambda x, z: _col(0, 1.9) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    bigtomb = lambda x, z: _col(0, 2.6) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    cam = (11.5, 0.5)
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 16", _raw(wall, 16, 0, 1, 0), 0.857, 0.01), ("wall 20", _raw(wall, 20, 0, 1, 0), 0.198, 0.01),
        ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.857, 0.01), ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("9 m wall 16", _raw(tall, 16, 0, 1, 0), 0.857, 0.01), ("9 m wall 20", _raw(tall, 20, 0, 1, 0), 0.198, 0.01),
        ("9 m wall 27", _raw(tall, 27, 0, 1, 0), 0.0, 0.0), ("9 m wall 11", _raw(tall, 11, 0, 1, 0), 1.0, 1e-6),
        ("tree 13 (close behind)", _raw(tree, 13, 0, 1, 0), 1.0, 0.01),
        ("tree 21 (9 m behind)", _raw(tree, 21, 0, 1, 0), 0.30, 0.05),
        ("Hunter, no camera", _raw(person, 11, 0, 1, 0), 1.0, 1e-6),
        ("Hunter next to the camera", _raw(person, 11, 0, 1, 0, cam=cam), 0.0, 0.0),
        ("2.6 m block next to the camera", _raw(bigtomb, 11, 0, 1, 0, cam=cam), 1.0, 0.01),
        ("Hunter, camera 19 m away", _raw(person, 11, 0, 1, 0, cam=(30.5, 0.5)), 1.0, 1e-6),
        ("3 m wall near the camera 12", _raw(wall, 12, 0, 1, 0, cam=cam), 1.0, 1e-6),
        ("3 m wall near the camera 16", _raw(wall, 16, 0, 1, 0, cam=cam), 0.857, 0.01),
    ]
    for name, got, expect, tol in want:
        if abs(got - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, got, expect, tol))
    # what r117b gave for the same things (for the report)
    old = {"tree 21": _raw(tree, 21, 0, 1, 0, new=False), "9 m wall 27": _raw(tall, 27, 0, 1, 0, new=False),
           "Hunter next to the camera": _raw(person, 11, 0, 1, 0, new=False)}
    if not (old["tree 21"] > 0.9 and old["9 m wall 27"] > 0.3 and old["Hunter next to the camera"] > 0.99):
        raise SystemExit("model check: r117b's numbers are not as described: %s" % old)
    # the keep weight
    for (top, d, e) in ((1.9, 2.0, 0.0), (2.6, 2.0, 1.0), (1.9, 7.0, 1.0), (1.9, 5.5, 0.5), (2.3, 2.0, 0.5)):
        if abs(_keep(top, d) - e) > 1e-6:
            raise SystemExit("model check: keep(%s, %s) = %s, not %s" % (top, d, _keep(top, d), e))
    # the cover's mapping
    for share, e in ((0.0, 0.0), (0.77, 0.0), (0.78, 0.0), (0.8, 0.0), (0.88, 0.5), (0.96, 1.0), (1.0, 1.0)):
        if abs(_ss(0.80, 0.96, share) - e) > 1e-6:
            raise SystemExit("model check: cover(%s) = %s, not %s" % (share, _ss(0.80, 0.96, share), e))
    return old


# a synthetic graveyard window (see the header): share of the seen cells above 0.5, no cover
def _scene(seed, hunter):
    import random
    rnd = random.Random(seed)
    cells = {}

    def put(x, z, top, bot=0.0):
        k = (x, z)
        cells[k] = (min(cells[k][0], bot), max(cells[k][1], top)) if k in cells else (bot, top)
    for _ in range(9):
        tx, tz = rnd.randint(-26, 26), rnd.randint(-26, 26)
        top = rnd.uniform(7, 9)
        for j in range(-2, 3):
            for i in range(-2, 3):
                put(tx + i, tz + j, top - rnd.uniform(0, 1.5))
        put(tx, tz, top)
        put(tx + 1, tz, top)
    for _ in range(60):
        put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(1.2, 1.8))
    for _ in range(6):
        tx, tz = rnd.randint(-26, 26), rnd.randint(-26, 26)
        top = rnd.uniform(2.0, 2.6)
        for j in range(2):
            for i in range(3):
                put(tx + i, tz + j, top)
    wx, wz = rnd.randint(-20, 10), rnd.randint(-25, 25)
    for i in range(12):
        put(wx + i, wz, 3.0)
    for j in range(2):  # the Hunter, 3 m from the camera cell (0, 0) toward +x
        for i in range(2):
            put(3 + i, j - 1, 1.9)
    del hunter

    def col(x, z):
        if (x, z) in cells:
            return (_q(cells[(x, z)][0]), _q(cells[(x, z)][1]))
        if (x * 7919 + z * 104729 + seed) % 10 < 6:
            return _col(0, 0)
        return None
    return col


def _synthetic(new, seeds, winds):
    n, vals = 64, []
    for seed in seeds:
        col = _scene(seed, True)
        for w in winds:
            g = [[_raw(col, i - 32, j - 32, w[0], w[1], new=new, cam=(0.5, 0.5)) for i in range(n)] for j in range(n)]
            tot = sh = 0
            for j in range(8, n - 8):
                for i in range(8, n - 8):
                    if col(i - 32, j - 32) is None:
                        continue
                    b = 0.0
                    for dj in (-1, 0, 1):
                        for di in (-1, 0, 1):
                            b += (2 - abs(di)) * (2 - abs(dj)) / 16.0 * g[j + dj][i + di]
                    tot += 1
                    sh += min(b * 1.06, 1.0) > 0.5
            vals.append(sh / tot)
    return sum(vals) / len(vals), min(vals), max(vals)


# the cover of the camera in synthetic scenes: climbing view rays -> (distance, normal y toward the camera)
def _climb(hit, fov_h=90.0, fov_v=59.0, pitch=0.0, w=160, h=90):
    tx, ty = math.tan(math.radians(fov_h / 2)), math.tan(math.radians(fov_v / 2))
    up = [0, 0, 0, 0]  # up, close, down, mid
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
                up[0] += 1
                d, nyv = hit(vx, vy, vz)
                if d < 35.0:
                    up[1] += 1
                elif d < 80.0 and nyv < -0.5:
                    up[2] += 1
    return up


def _box(x0, x1, z0, z1, top):
    def f(dx, dy, dz):
        t = []
        if dx > 0: t.append(((x1 / dx), 0.0))
        if dx < 0: t.append(((x0 / dx), 0.0))
        if dz > 0: t.append(((z1 / dz), 0.0))
        if dz < 0: t.append(((z0 / dz), 0.0))
        if dy > 0: t.append((((top - 1.7) / dy), -1.0))
        return min(t) if t else (math.inf, 0.0)
    return f


def _courtyard(trees, wall_x=40.0, wall_h=14.0):
    """Open ground, spherical canopies (cx, cy, cz, r) and a far wall at x = wall_x (wall_h high)."""
    def f(dx, dy, dz):
        best = (math.inf, 0.0)
        for (cx, cy, cz, r) in trees:
            ox, oy, oz = -cx, 1.7 - cy, -cz
            b = ox * dx + oy * dy + oz * dz
            c = ox * ox + oy * oy + oz * oz - r * r
            disc = b * b - c
            if disc >= 0:
                t = -b - math.sqrt(disc)
                if t > 0 and t < best[0]:
                    hy = 1.7 + t * dy
                    best = (t, (hy - cy) / r)
        if dx > 0:
            t = wall_x / dx
            if 1.7 + t * dy < wall_h and t < best[0]:
                best = (t, 0.0)
        return best
    return f


def scene_checks():
    out = {}
    out["library 20x14x8"] = _climb(_box(-8.0, 12.0, -7.0, 7.0, 8.0))
    out["small room"] = _climb(_box(-6.0, 14.0, -7.0, 7.0, 5.0))
    out["hall 30x20x15"] = _climb(_box(-10.0, 20.0, -10.0, 10.0, 15.0))
    out["hall 34x24x18"] = _climb(_box(-10.0, 24.0, -12.0, 12.0, 18.0))
    out["long nave 80x20x18 (limit)"] = _climb(_box(-10.0, 70.0, -10.0, 10.0, 18.0))
    trees = [(8, 7, -6, 3.0), (14, 8, 5, 3.5), (-6, 7, 10, 3.0)]
    out["graveyard (3 canopies, wall 40 m)"] = _climb(_courtyard(trees, 40.0, 14.0))
    out["courtyard, no trees, walls 28 m"] = _climb(_courtyard([], 28.0, 12.0))
    out["open"] = _climb(_courtyard([], 400.0, 1.0))
    out["looking down"] = _climb(_courtyard([]), pitch=-25.0)
    shares = {k: ((v[1] + v[2]) / v[0] if v[0] else 0.0) for k, v in out.items()}
    for k in ("library 20x14x8", "small room", "hall 30x20x15", "hall 34x24x18"):
        if shares[k] < 0.99:
            raise SystemExit("scene check: %s share %.3f, indoors must reach 1" % (k, shares[k]))
    # (a hall deeper than 35 m looked at along its length is the rule's limit: its far wall is not an
    # underside; reported, not asserted. The 80 m rule of r117b would have counted it.)
    for k in ("graveyard (3 canopies, wall 40 m)", "courtyard, no trees, walls 28 m", "open"):
        if _ss(0.80, 0.96, shares[k]) != 0.0:
            raise SystemExit("scene check: %s: share %.3f maps to a cover" % (k, shares[k]))
    if out["looking down"][0] >= 64:
        raise SystemExit("scene check: a camera pitched down 25 degrees still has %d climbing rays" % out["looking down"][0])
    return out, shares


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_COVER_CLOSE 35.0f", "#define WS_COVER_LO 0.80f", "#define WS_COVER_HI 0.96f",
                 "#define WS_EFF_MAX 2.0f", "#define WS_NEAR_CAM_HI 7.0f", "#define WS_C_UP 12u",
                 "#define WS_C_MID 15u", "#define WS_COVER_DIST 80.0f"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    if "WS_COUNTER_WORDS 16u" not in layout:
        raise SystemExit("text check: the counter words changed")
    if comp.count("faces_down(") != 2 or comp.count("WS_EFF_MAX") < 2 or comp.count("const float keep =") != 1:
        raise SystemExit("text check: the shader's r117c code is not there as designed")
    if comp.count("WS_C_UP") != 1 or comp.count("g_close") != 4 or "vec3(0.04)" not in comp:
        raise SystemExit("text check: the shader's counters")
    for want in ("inline float NearKeep(", "inline bool CoverHit(", "float cam_x = 1.0e9f", "std::hypot(",
                 "climb_up = 0"):
        if header.count(want) < 1:
            raise SystemExit("text check: %s lacks %r" % (HDR, want))
    if header.count("RayBlocked(column, cx, cz,") != 3:
        raise SystemExit("text check: the three rays")
    if vk.count("Wind shelter (r117c)") != 1:
        raise SystemExit("text check: vk_wind_shelter.cpp")
    for line in vk.split("\n"):
        if "Wind shelter (r117c)" in line and len(line) > 130:
            raise SystemExit("text check: log line too long")
    if test.count("TestOutdoors()") != 2:
        raise SystemExit("text check: test main")
    # the log line stays under 300 characters with its widest numbers
    sample = ("Wind shelter (r117c): %d climbing view rays: %.1f%% ended within %.0f m, %.1f%% on a surface "
              "facing down (to %.0f m), %.1f%% on another surface within %.0f m, %.1f%% on the sky or beyond"
              % (1000000, 100.0, 35, 100.0, 80, 100.0, 80, 100.0))
    if len(sample) >= 300:
        raise SystemExit("text check: log line %d characters" % len(sample))
    for need in ("a low obstacle within a few metres of the camera is ignored", "0.8 to 0.96 and up"):
        if texts[RM].count(need) != 1:
            raise SystemExit("text check: README lacks %r" % need)
    old = model_checks()
    scenes = scene_checks()
    return old, scenes


def report(res, full):
    old, (scenes, shares) = res
    print("model: all asserted numbers pass. r117b gave: a tree 9 m behind %.2f, a 9 m wall 17 m behind %.2f, "
          "the Hunter next to the camera %.2f" % (old["tree 21"], old["9 m wall 27"], old["Hunter next to the camera"]))
    for name, v in scenes.items():
        up, close, down = v[0], v[1], v[2]
        sh = shares[name]
        print("scene %-34s climbing rays %5d: within 35 m %4.1f%%, facing down beyond %4.1f%% -> share %.3f -> cover %.2f" %
              (name, up, 100.0 * close / max(up, 1), 100.0 * down / max(up, 1), sh, _ss(0.80, 0.96, sh)))
    if full:
        seeds, winds = range(4), ((1, 0), (-0.707, 0.707))
        for new, name in ((False, "r117b (14 deg rays, no cap, no Hunter rule)"), (True, "r117c (cap 2.0, Hunter rule)")):
            mean, lo, hi = _synthetic(new, seeds, winds)
            print("synthetic graveyard, no cover, %-45s: %.1f%% of the seen cells above 0.5 (min %.1f%%, max %.1f%%)"
                  % (name, 100 * mean, 100 * lo, 100 * hi))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117C_ROOT)" % ROOT)
    for need in (COMP, LAY, HDR, VKC, TST):
        if not os.path.exists(os.path.join(ROOT, need)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % need)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        raw, eol, cur = load(path)
        if "WS_COVER_CLOSE" not in cur and path == LAY and "WS_COVER_TAN" not in cur:
            raise SystemExit("r117b_shelter-indoors is not applied (the layout has no WS_COVER_TAN)")
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
        report(res, True)
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
            tmp = full + ".r117ctmp"
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
        tmp = full + ".r117ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
