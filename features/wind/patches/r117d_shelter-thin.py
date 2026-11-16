# r117d_shelter-thin: FEATURE fix on top of r117_wind-shelter, r117b_shelter-indoors and r117c_shelter-outdoors
# (all applied and built; r117c in b35). Still off with r117's knob BB_WIND_SHELTER (no new knob): every edit
# is in r117's own files, which only exist or run with the knob (see "Off" below).
#
# WHAT b35 SHOWED (r117c-grave1, -lamp1, -none): indoors is right (library 100% sheltered, mean 0.998).
# The graveyard is better than b30 but still too sheltered: 40.8% of the view above 0.5 (target 5-35), mean
# 0.405 (wanted under 0.3), 15.0% above 0.95 in an open yard, at the camera 0.30, overhead cover 0.00. The
# show view: open ground and the far wall yellow, green only in patches, red on grass and near branches;
# lamp-test-spot 51.5% sheltered, mean 0.504. The reader's suspicion: thin or low things (grave markers,
# fences, trunks, railings) count as full walls.
#
# CAUSE (read from the shader, not measured): the cache keeps only the lowest and highest height of a 1 m
# cell. The ray test (ray() in the shader, RayBlocked in C++) blocks by smoothstep(0.12, 0.40, (top - ground
# - 1 m) / distance) whatever stands in the cell: a one-cell trunk, a post, a 1.3 m gravestone or a 1.6 m
# rail count as much as a wall of the same height. Close behind such a thing all three rays (14 degrees
# apart: 0.5 m at 2 m) meet the one cell, so the median is 1; and a field of them (a graveyard) leaves little
# open ground. (An obstacle's thickness ALONG the ray does not matter to the wind; its width ACROSS the ray
# does: the air goes round a thing one cell wide.)
#
# FIX: two weights on what a ray meets, both 1 for a wall (so the numbers of walls, tombs 2 m and over, trees
# 5 cells wide and halls do not change) and falling for small things:
#  1. HEIGHT: smoothstep(WS_THIN_H_LO 1.2, WS_THIN_H_HI 2.0, top - ground): nothing under 1.2 m counts, 1.6 m
#     half, 2.0 m and over in full. (Grave markers, rails, low fences.) Gravestones (1.2-1.8 m) also have little
#     excess above the 1 m start, so they were weak before; now they are almost nothing.
#  2. WIDTH ACROSS THE RAY: at the cell a ray meets, the four cells next to it across the ray's direction (2 on
#     each side, taken at the same distance along the ray) are looked at: w = 1 + sum over them (1 if the cell
#     is known and its top is at least WS_THIN_NB 1.5 m above the ground, 0.5 if it is not known (the cache
#     has gaps: no news is not a gap in a wall), 0 if it is known and low). The weight is
#     smoothstep(WS_THIN_W_LO 1, WS_THIN_W_HI 3, w): a one-cell thing with known low cells either side: 0 (a
#     trunk, a post, a lamp post: nothing), two cells: 0.5, three or more: 1. The width test runs only when
#     the obstacle would block more than the ray has found so far (hits only: a few cells a ray).
#     (Review fix: each of the 4 counts as tall if the cell or the one a step up or down the ray from it is tall,
#     unknown only by the cell itself: with single samples a wall slanting more than ~30 degrees across the ray
#     read as one cell wide and sheltered nothing, failing TestModel's unchanged diagonal-wind assertion.)
# The share-of-blocked-rays idea (more rays): not done: the median of three already needs two rays blocked, and
# the width weight addresses thinness directly and at its source; five rays would cost two thirds more on the
# raw pass for little. NOT touched: the tree canopy (a wide column from the ground to the canopy counts as a 3 m
# wall: the cache cannot tell a solid wall from a canopy over a trunk; see the context file for the next step if
# the graveyard stays above target).
#
# The model below (this script's check) asserts the new numbers; the synthetic graveyards show what the
# weights do to the share of the view above 0.5 and to the mean field: a model, NOT the game.
#
# LOG: a new line next to r117c's, once every 600 frames: "Wind shelter (r117d): N obstacle cells met by the
# raw pass's rays, X% under 1.6 m tall (height weight below 0.5), Y% of the rest one or two cells wide
# (width weight below 0.5)" (per the 600 frames: it is a count of ray/cell meetings that would have raised
# a ray's value).
#
# Off: nothing here runs without r117's knob (the shader is only built into the pass r117 makes:
# BbWindShelter::KnobOnce().on); the new constants and the function are in r117's own header, shader and layout;
# the log line is in r117's Report. BB_WIND off and BB_WIND_SHELTER off are unchanged.
# Cost on (estimates): raw pass: per obstacle cell a ray meets (and only when it would raise the ray's value)
# one smoothstep and 12 cache reads (global memory, 16 bytes each, hot in cache): at most 4096 cells x 3 rays x
# 28 steps = 344k meetings a frame, in practice a few thousand: far below 0.01 ms. Memory: none (the counter
# buffer grows from 16 to 20 words: 16 bytes). CPU: one more log line a minute.
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row).
# Use: python -I -X utf8 r117d_shelter-thin.py check | apply | revert
# Root: R117D_ROOT, else <tree>. Line ends kept. Needs r117, r117b and r117c applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117d_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAY_ANCHOR = "#define WS_NEAR_CAM_HI 7.0f\n"
LAY_AFTER = '''// r117d (thin and low things counted as walls, see r117d_shelter-thin.py): an obstacle a ray meets counts by
// smoothstep(WS_THIN_H_LO, WS_THIN_H_HI, its top above the ground) times smoothstep(WS_THIN_W_LO, WS_THIN_W_HI, w),
// w = 1 + the cells next to it across the ray (2 on each side): 1 for a known cell with a top at least
// WS_THIN_NB above the ground, WS_THIN_UNSEEN for a cell the cache knows nothing of, 0 for a known low one.
#define WS_THIN_H_LO 1.2f
#define WS_THIN_H_HI 2.0f
#define WS_THIN_W_LO 1.0f
#define WS_THIN_W_HI 3.0f
#define WS_THIN_NB 1.5f
#define WS_THIN_UNSEEN 0.5f
'''
LAY_CW_OLD = "#define WS_COUNTER_WORDS 16u\n"
LAY_CW_NEW = "#define WS_COUNTER_WORDS 20u\n"
LAY_COUNTER_ANCHOR = "#define WS_C_MID 15u           // of them ending on another surface within WS_COVER_DIST (the rest: sky or beyond)\n"
LAY_COUNTER_AFTER = '''#define WS_C_THIN_SEEN 16u     // obstacle cells a raw-pass ray met that would have raised its value (r117d)
#define WS_C_THIN_LOW 17u      // of them with a height weight below 0.5
#define WS_C_THIN_NARROW 18u   // of the rest with a width weight below 0.5
'''

COMP_DOC_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_DOC_BEFORE = '''//  r117d  an obstacle a ray meets counts by its height (nothing under WS_THIN_H_LO above the ground, in full from
//         WS_THIN_H_HI) and by its width across the ray (thick_weight: a one-cell thing counts for nothing).
'''
COMP_FN_ANCHOR = "// One ray from the cell centre `from` (world, m) upwind along `dir`: how far it is blocked, 0-1.\n"
COMP_FN_BEFORE = '''// r117d: the counts the raw pass keeps for the log (private to the invocation; raw_pass adds them to the counters).
uint ws_thin_seen = 0u;
uint ws_thin_low = 0u;
uint ws_thin_narrow = 0u;

// r117d: how wide the thing a ray meets at the world point `at` (xz, m) is across the ray (direction `dir`, unit):
// w = 1 + its 4 neighbours across the ray (offsets -2, -1, 1, 2 cells from the middle of the cell met, each with the
// cells a step up and down the ray: a slanting wall stays wide); a known cell whose top is at least
// WS_THIN_NB above `ground` adds 1, one the cache knows nothing of WS_THIN_UNSEEN, a known low one 0.
float thick_weight(vec2 at, vec2 dir, float ground) {
    const vec2 side = vec2(-dir.y, dir.x) * WS_CELL;
    const vec2 along = dir * WS_CELL;
    const vec2 mid = (floor(at * (1.0 / WS_CELL)) + 0.5) * WS_CELL; // the cell's middle: a slanted ray meets a cell near its edge
    float w = 1.0;
    for (int j = -2; j <= 2; ++j) {
        if (j != 0) {
            // the cell across the ray and the two one step up and down the ray from it (a wall slanting across
            // the ray stays wide): tall if any of the three is; unknown only by the middle one
            const vec2 p = mid + side * float(j);
            float v = 0.0;
            for (int a = -1; a <= 1; ++a) {
                const vec3 nb = column(ivec2(floor((p + along * float(a)) * (1.0 / WS_CELL))));
                if (nb.z > 0.0 && nb.y - ground >= WS_THIN_NB) {
                    v = 1.0;
                } else if (a == 0 && nb.z <= 0.0) {
                    v = max(v, WS_THIN_UNSEEN);
                }
            }
            w += v;
        }
    }
    return smoothstep(WS_THIN_W_LO, WS_THIN_W_HI, w);
}

'''
COMP_RAY_OLD = "            blocked = max(blocked, smoothstep(WS_TAN_LO, WS_TAN_HI, eff / dist) * pass_ * keep);\n"
COMP_RAY_NEW = '''            // r117d: by the height of the thing and by its width across the ray (thin or low things shelter little);
            // the width is looked at only when the thing would raise the ray's value
            float hit = smoothstep(WS_TAN_LO, WS_TAN_HI, eff / dist) * pass_ * keep;
            if (hit > blocked) {
                const float h_w = smoothstep(WS_THIN_H_LO, WS_THIN_H_HI, col.y - ground);
                ++ws_thin_seen;
                hit *= h_w;
                if (h_w < 0.5) {
                    ++ws_thin_low;
                }
                if (hit > blocked) {
                    const float t_w = thick_weight(from + dir * dist, dir, ground);
                    if (t_w < 0.5) {
                        ++ws_thin_narrow;
                    }
                    blocked = max(blocked, hit * t_w);
                }
            }
'''
COMP_RAWEND_ANCHOR = """        atomicAdd(counters.c[WS_C_CELLS_SEEN], 1u);
    }
"""
COMP_RAWEND_AFTER = """    if (ws_thin_seen != 0u) { // r117d
        atomicAdd(counters.c[WS_C_THIN_SEEN], ws_thin_seen);
        atomicAdd(counters.c[WS_C_THIN_LOW], ws_thin_low);
        atomicAdd(counters.c[WS_C_THIN_NARROW], ws_thin_narrow);
    }
"""

HDR_CONST_ANCHOR = "                       NearCamLo = WS_NEAR_CAM_LO, NearCamHi = WS_NEAR_CAM_HI; // r117c\n"
HDR_CONST_AFTER = '''inline constexpr float ThinHLo = WS_THIN_H_LO, ThinHHi = WS_THIN_H_HI, ThinWLo = WS_THIN_W_LO,
                       ThinWHi = WS_THIN_W_HI, ThinNb = WS_THIN_NB, ThinUnseen = WS_THIN_UNSEEN; // r117d
'''
HDR_FN_ANCHOR = "/// A ray from the middle of cell (cx, cz) UPWIND along (dx, dz) (a unit vector): how far it is\n"
HDR_FN_BEFORE = '''/// r117d: how much an obstacle of height `top_above_ground` counts: 0 under ThinHLo, 1 from ThinHHi.
[[nodiscard]] inline float HeightWeight(float top_above_ground) {
    return BbWind::Smoothstep(ThinHLo, ThinHHi, top_above_ground);
}

/// r117d: the weight of an obstacle by its width across a ray: the thing met at the world point (x, z) m by a
/// ray along the unit vector (dx, dz): w = 1 + the cells 1 and 2 to either side of it across the ray, counted from
/// the middle of the cell met (a slanted ray meets a cell near its edge) (a known
/// cell with a top at least ThinNb above `ground` adds 1, an unknown cell ThinUnseen, a known low cell 0),
/// the weight Smoothstep(ThinWLo, ThinWHi, w): one cell wide with known low cells either side 0, two cells 0.5,
/// three or more 1 (wind_shelter.comp's thick_weight, operation for operation).
template <class ColumnFn>
[[nodiscard]] float ThinWeight(ColumnFn&& column, float x, float z, float dx, float dz, float ground) {
    const float sx = -dz * Cell, sz = dx * Cell;
    const float ax = dx * Cell, az = dz * Cell;
    const float mx = (std::floor(x * (1.0f / Cell)) + 0.5f) * Cell, mz = (std::floor(z * (1.0f / Cell)) + 0.5f) * Cell;
    float w = 1.0f;
    for (int j = -2; j <= 2; ++j) {
        if (j != 0) {
            // the cell across the ray and the two one step up and down the ray from it (a slanting wall stays
            // wide): tall if any of the three is; unknown only by the middle one
            const float px = mx + sx * float(j), pz = mz + sz * float(j);
            float v = 0.0f;
            for (int a = -1; a <= 1; ++a) {
                const Column nb = column(int(std::floor((px + ax * float(a)) * (1.0f / Cell))),
                                         int(std::floor((pz + az * float(a)) * (1.0f / Cell))));
                if (nb.seen && nb.top - ground >= ThinNb) {
                    v = 1.0f;
                } else if (a == 0 && !nb.seen) {
                    v = std::max(v, ThinUnseen);
                }
            }
            w += v;
        }
    }
    return BbWind::Smoothstep(ThinWLo, ThinWHi, w);
}

'''
HDR_BLK_OLD = "            blocked = std::max(blocked, BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass * keep);\n"
HDR_BLK_NEW = '''            // r117d: by the height and by the width across the ray, the width only when it matters
            float hit = BbWind::Smoothstep(TanLo, TanHi, excess / dist) * pass * keep;
            if (hit > blocked) {
                hit *= HeightWeight(col.top - ground);
                if (hit > blocked) {
                    hit *= ThinWeight(column, fx + dx * dist, fz + dz * dist, dx, dz, ground);
                    blocked = std::max(blocked, hit);
                }
            }
'''
HDR_CNT_ANCHOR = "    std::uint64_t climb_up = 0, climb_close = 0, climb_down = 0, climb_mid = 0; ///< r117c\n"
HDR_CNT_AFTER = "    std::uint64_t thin_seen = 0, thin_low = 0, thin_narrow = 0; ///< r117d\n"
HDR_CNTB_OLD = "            d(WS_C_MID)};\n"
HDR_CNTB_NEW = ("            d(WS_C_MID),\n"
                "            d(WS_C_THIN_SEEN),      d(WS_C_THIN_LOW),         d(WS_C_THIN_NARROW)};\n")

VK_ANCHOR = "                     100.0 * (up - double(c.climb_close + c.climb_down + c.climb_mid)) / up);\n"
VK_AFTER = '''    // r117d: the obstacle cells the raw pass's rays met that would have raised a ray's value: how many were low
    // (a height weight under 0.5), and of the rest how many were thin (a width weight under 0.5)
    const double met = std::max(1.0, double(c.thin_seen));
    BbReport::Printf("Wind shelter (r117d): %llu obstacle cells met by the rays, %.1f%% low (under 1.6 m), "
                     "%.1f%% of the rest thin (one or two cells wide)\\n",
                     ull(c.thin_seen), 100.0 * double(c.thin_low) / met,
                     100.0 * double(c.thin_narrow) / std::max(1.0, double(c.thin_seen - c.thin_low)));
'''

TEST_POST_OLD = '    Expect(Raw(Post, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind a post: 1");\n'
TEST_POST_NEW = ('    Expect(Raw(Post, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f, "right behind a one-cell post: 0 (r117d: a thin '
                 'thing shelters nothing)");\n')
TEST_P1_OLD = ('    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "without the camera\'s place the block shelters '
               '(r117b)");\n')
TEST_P1_NEW = ('    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.1f), "without the camera\'s place the 2 x 2 '
               'block shelters by half (r117d: two cells wide)");\n')
TEST_P2_OLD = ('    Expect(Raw(BigTomb, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) > 0.99f, "a 2.6 m block next to it still '
               'shelters");\n')
TEST_P2_NEW = ('    Expect(Near(Raw(BigTomb, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.5f, 0.1f), "a 2.6 m block next to it '
               'still shelters by half (r117d)");\n')
TEST_P3_OLD = '    Expect(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f) > 0.99f,\n'
TEST_P3_NEW = '    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.5f, 0.1f),\n'

TEST_FN_ANCHOR = "// r117b: the camera's cover\nvoid TestCover() {\n"
TEST_FN_BEFORE = '''// r117d: thin and low things shelter little, walls and wide things as before
Column Trunk(int x, int z) { // a trunk: one cell, 8 m
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}
Column TrunkUnknown(int x, int z) { // the same trunk, its neighbours across the ray not known
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f) : x == 10 ? Column{} : ColumnOf(0.0f, 0.0f);
}
Column Rail(int x, int z) { // a rail 1.2 m high along z at x = 10, 40 m long
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 1.2f) : ColumnOf(0.0f, 0.0f);
}
Column Stone(int x, int z) { // a fence of 1.6 m
    return x == 10 && z >= -20 && z <= 20 ? ColumnOf(0.0f, 1.6f) : ColumnOf(0.0f, 0.0f);
}
Column TwoCells(int x, int z) { // a thing two cells wide, 3 m
    return x == 10 && z >= 0 && z <= 1 ? ColumnOf(0.0f, 3.0f) : ColumnOf(0.0f, 0.0f);
}

void TestThin() {
    Expect(HeightWeight(1.0f) == 0.0f && HeightWeight(1.2f) == 0.0f && HeightWeight(2.0f) == 1.0f &&
               HeightWeight(3.0f) == 1.0f && Near(HeightWeight(1.6f), 0.5f, 1e-6f),
           "the height weight: 0 under 1.2 m, half at 1.6, 1 from 2.0");
    // a trunk (one cell, all neighbours known low): nothing, close or far
    Expect(Raw(Trunk, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Trunk, 12, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "behind a one-cell trunk: nothing (r117c: 1.0 close behind it)");
    // the same trunk with its neighbours unknown (cache gaps) is not called thin: w = 3, as before
    Expect(Raw(TrunkUnknown, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "a trunk whose neighbours are not known: as a wall");
    // a low rail, 40 m long: its height alone keeps it from counting
    Expect(Raw(Rail, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Rail, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "behind a 1.2 m rail: 0 (r117c: it counted by its 0.2 m of excess)");
    Expect(Near(Raw(Stone, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.05f), "behind a 1.6 m fence: half (the height weight)");
    // a thing two cells wide: half
    Expect(Near(Raw(TwoCells, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.1f), "a thing two cells wide: about half");
    // walls, tombs, trees as before
    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f) && Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f) &&
               Raw(Tomb, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,
           "a wall, a tomb and a tree are not thin");
    // ThinWeight directly: a wide wall's cell is 1; a lone cell with known low neighbours 0; unknown ones 0.5 each
    Expect(Near(ThinWeight(Wall, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f) &&
               ThinWeight(Post, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f) == 0.0f &&
               Near(ThinWeight(Post, 10.5f, 0.5f, 0.0f, 1.0f, 0.0f), 0.0f, 1e-6f) &&
               Near(ThinWeight(TrunkUnknown, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f),
           "the width weight");
}

'''
TEST_MAIN_ANCHOR = "    TestOutdoors();\n"
TEST_MAIN_AFTER = "    TestThin();\n"
TEST_CNT_ANCHOR = '           "the climbing rays\' counts, word by word");\n'
TEST_CNT_AFTER = '''    // r117d: the obstacle cells the rays met
    before = {};
    now = {};
    now[WS_C_THIN_SEEN] = 900;
    now[WS_C_THIN_LOW] = 300;
    now[WS_C_THIN_NARROW] = 200;
    c = CountsBetween(now.data(), before.data());
    Expect(c.thin_seen == 900 && c.thin_low == 300 && c.thin_narrow == 200,
           "the obstacle counts, word by word");
'''

README_OLD = "and a tall tree or building shelters like a 3 m wall)"
README_NEW = ("a tall tree or building shelters like a 3 m wall, and an obstacle under about 1.2 m tall or one cell "
              "wide across the wind hardly counts)")

EDITS = {
    LAY: [("ins", LAY_ANCHOR, "", LAY_AFTER),
          ("rep", LAY_CW_OLD, LAY_CW_NEW),
          ("ins", LAY_COUNTER_ANCHOR, "", LAY_COUNTER_AFTER)],
    COMP: [("ins", COMP_DOC_ANCHOR, COMP_DOC_BEFORE, ""),
           ("ins", COMP_FN_ANCHOR, COMP_FN_BEFORE, ""),
           ("rep", COMP_RAY_OLD, COMP_RAY_NEW),
           ("ins", COMP_RAWEND_ANCHOR, "", COMP_RAWEND_AFTER)],
    HDR: [("ins", HDR_CONST_ANCHOR, "", HDR_CONST_AFTER),
          ("ins", HDR_FN_ANCHOR, HDR_FN_BEFORE, ""),
          ("rep", HDR_BLK_OLD, HDR_BLK_NEW),
          ("ins", HDR_CNT_ANCHOR, "", HDR_CNT_AFTER),
          ("rep", HDR_CNTB_OLD, HDR_CNTB_NEW)],
    VKC: [("ins", VK_ANCHOR, "", VK_AFTER)],
    TST: [("rep", TEST_POST_OLD, TEST_POST_NEW), ("rep", TEST_P1_OLD, TEST_P1_NEW),
          ("rep", TEST_P2_OLD, TEST_P2_NEW), ("rep", TEST_P3_OLD, TEST_P3_NEW),
          ("ins", TEST_FN_ANCHOR, TEST_FN_BEFORE, ""), ("ins", TEST_MAIN_ANCHOR, "", TEST_MAIN_AFTER),
          ("ins", TEST_CNT_ANCHOR, "", TEST_CNT_AFTER)],
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


def _thick(col, x, z, dx, dz, g):
    sx, sz = -dz, dx
    mx, mz = math.floor(x) + 0.5, math.floor(z) + 0.5
    w = 1.0
    for j in (-2, -1, 1, 2):
        px, pz, v = mx + sx * j, mz + sz * j, 0.0
        for a in (-1, 0, 1):
            c = col(math.floor(px + dx * a), math.floor(pz + dz * a))
            if c and c[1] - g >= 1.5:
                v = 1.0
            elif a == 0 and not c:
                v = max(v, 0.5)
        w += v
    return _ss(1.0, 3.0, w)


def _ray(col, cx, cz, dx, dz, g, cam, thin):
    fx, fz, blocked, k = cx + 0.5, cz + 0.5, 0.0, 1
    while k <= 28 and blocked < 1.0:
        ix, iz = math.floor(fx + dx * k), math.floor(fz + dz * k)
        c = col(ix, iz)
        if c:
            ex, lift = min(max(c[1] - g - 1.0, 0.0), 2.0), c[0] - g
            keep = _keep(c[1] - g, math.hypot((ix + 0.5) - cam[0], (iz + 0.5) - cam[1]))
            hit = _ss(0.12, 0.40, ex / k) * (1.0 - _ss(1.2, 2.4, lift)) * keep
            if hit > blocked:
                if thin:
                    hit *= _ss(1.2, 2.0, c[1] - g)
                    if hit > blocked:
                        hit *= _thick(col, fx + dx * k, fz + dz * k, dx, dz, g)
                blocked = max(blocked, hit)
        k += 1
    return blocked


def _rot(vx, vz, deg):
    a = math.radians(deg)
    return vx * math.cos(a) - vz * math.sin(a), vx * math.sin(a) + vz * math.cos(a)


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, thin=True, cam=(1e9, 1e9)):
    """thin False: r117c; True: r117d."""
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g, cam, thin), _ray(col, cx, cz, -dx, -dz, g, cam, thin),
         _ray(col, cx, cz, c[0], c[1], g, cam, thin)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    return 1.0 - (1.0 - lee) * (1.0 - cover)


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    post = lambda x, z: _col(0, 3) if x == 10 and z == 0 else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    tree = lambda x, z: _col(0, 8) if 8 <= x <= 12 and -2 <= z <= 2 else _col(0, 0)
    person = lambda x, z: _col(0, 1.9) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    bigtomb = lambda x, z: _col(0, 2.6) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    trunk = lambda x, z: _col(0, 8) if x == 10 and z == 0 else _col(0, 0)
    trunk_u = lambda x, z: _col(0, 8) if x == 10 and z == 0 else (None if x == 10 else _col(0, 0))
    rail = lambda x, z: _col(0, 1.2) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    stone = lambda x, z: _col(0, 1.6) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    pair = lambda x, z: _col(0, 3) if x == 10 and 0 <= z <= 1 else _col(0, 0)
    cam = (11.5, 0.5)
    got = {}
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 16", _raw(wall, 16, 0, 1, 0), 0.857, 0.01), ("wall 20", _raw(wall, 20, 0, 1, 0), 0.198, 0.01),
        ("tomb 11", _raw(tomb, 11, 0, 1, 0), 1.0, 0.01), ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.857, 0.01),
        ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("tree 13", _raw(tree, 13, 0, 1, 0), 1.0, 0.01), ("tree 21", _raw(tree, 21, 0, 1, 0), 0.30, 0.05),
        ("post 11 (r117c: 1)", _raw(post, 11, 0, 1, 0), 0.0, 0.0), ("post 13", _raw(post, 13, 0, 1, 0), 0.0, 0.0),
        ("trunk 11 (r117c: 1)", _raw(trunk, 11, 0, 1, 0), 0.0, 0.0),
        ("trunk 12", _raw(trunk, 12, 0, 1, 0), 0.0, 0.0),
        ("trunk, neighbours unknown 11", _raw(trunk_u, 11, 0, 1, 0), 1.0, 0.01),
        ("rail 1.2 m 11 (r117c: 0.2)", _raw(rail, 11, 0, 1, 0), 0.0, 0.0), ("rail 13", _raw(rail, 13, 0, 1, 0), 0.0, 0.0),
        ("fence 1.6 m 11", _raw(stone, 11, 0, 1, 0), 0.5, 0.05),
        ("two cells wide 11", _raw(pair, 11, 0, 1, 0), 0.5, 0.1),
        ("Hunter, no camera (r117c: 1)", _raw(person, 11, 0, 1, 0), 0.5, 0.1),
        ("Hunter next to the camera", _raw(person, 11, 0, 1, 0, cam=cam), 0.0, 0.0),
        ("2.6 m block next to the camera", _raw(bigtomb, 11, 0, 1, 0, cam=cam), 0.5, 0.1),
        ("Hunter, camera 19 m away", _raw(person, 11, 0, 1, 0, cam=(30.5, 0.5)), 0.5, 0.1),
        ("3 m wall near the camera 12", _raw(wall, 12, 0, 1, 0, cam=cam), 1.0, 1e-6),
        ("3 m wall near the camera 16", _raw(wall, 16, 0, 1, 0, cam=cam), 0.857, 0.01),
        ("wall, diagonal wind 13 (TestModel)", _raw(wall, 13, 0, math.sqrt(0.5), math.sqrt(0.5)), 1.0, 0.01),
        ("wall, wind 30 deg 12", _raw(wall, 12, 0, math.cos(0.5236), math.sin(0.5236)), 1.0, 0.01),
        ("wall, wind 40 deg 12", _raw(wall, 12, 0, math.cos(0.6981), math.sin(0.6981)), 1.0, 0.01),
        ("post, diagonal wind 11", _raw(post, 11, 1, math.sqrt(0.5), math.sqrt(0.5)), 0.0, 0.0),
    ]
    for name, g, expect, tol in want:
        got[name] = g
        if abs(g - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, g, expect, tol))
    # the same things in r117c (thin False): what changed
    old = {"post 11": _raw(post, 11, 0, 1, 0, thin=False), "trunk 11": _raw(trunk, 11, 0, 1, 0, thin=False),
           "rail 1.2 m 11": _raw(rail, 11, 0, 1, 0, thin=False), "tomb 13": _raw(tomb, 13, 0, 1, 0, thin=False),
           "Hunter, no camera": _raw(person, 11, 0, 1, 0, thin=False)}
    if not (old["post 11"] > 0.99 and old["trunk 11"] > 0.99 and old["rail 1.2 m 11"] > 0.1 and
            abs(old["tomb 13"] - 0.857) < 0.01 and old["Hunter, no camera"] > 0.99):
        raise SystemExit("model check: r117c's numbers are not as described: %s" % old)
    for h, e in ((1.0, 0.0), (1.2, 0.0), (1.6, 0.5), (2.0, 1.0), (3.0, 1.0)):
        if abs(_ss(1.2, 2.0, h) - e) > 1e-6:
            raise SystemExit("model check: height weight(%s) = %s, not %s" % (h, _ss(1.2, 2.0, h), e))
    return got, old


# synthetic graveyards (see the header): share of the seen cells above 0.5 and the mean field, no cover
def _scene(seed, kind):
    """kind 'A': r117c's window (9 canopies 5x5, 60 gravestones, 6 tombs, a wall, the Hunter); 'B': A with the
    thin things of a real graveyard added (14 trunks, 8 rails of 8 cells at 1.5 m, 40 more markers at 1.4-2.2 m)."""
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
    if kind == "B":
        for _ in range(14):
            put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(5, 9))
        for _ in range(8):
            rx, rz = rnd.randint(-26, 18), rnd.randint(-28, 28)
            horiz = rnd.random() < 0.5
            for i in range(8):
                put(rx + (i if horiz else 0), rz + (0 if horiz else i), 1.5)
        for _ in range(40):
            put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(1.4, 2.2))

    def col(x, z):
        if (x, z) in cells:
            return (_q(cells[(x, z)][0]), _q(cells[(x, z)][1]))
        if (x * 7919 + z * 104729 + seed) % 10 < 6:
            return _col(0, 0)
        return None
    return col


def _synthetic(thin, kind, seeds, winds):
    n, shares, means = 64, [], []
    for seed in seeds:
        col = _scene(seed, kind)
        for w in winds:
            g = [[_raw(col, i - 32, j - 32, w[0], w[1], thin=thin, cam=(0.5, 0.5)) for i in range(n)]
                 for j in range(n)]
            tot = sh = 0
            sm = 0.0
            for j in range(8, n - 8):
                for i in range(8, n - 8):
                    if col(i - 32, j - 32) is None:
                        continue
                    b = 0.0
                    for dj in (-1, 0, 1):
                        for di in (-1, 0, 1):
                            b += (2 - abs(di)) * (2 - abs(dj)) / 16.0 * g[j + dj][i + di]
                    v = min(b * 1.06, 1.0)
                    tot += 1
                    sh += v > 0.5
                    sm += v
            shares.append(sh / tot)
            means.append(sm / tot)
    f = lambda a: (sum(a) / len(a), min(a), max(a))
    return f(shares), f(means)


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_THIN_H_LO 1.2f", "#define WS_THIN_H_HI 2.0f", "#define WS_THIN_W_HI 3.0f",
                 "#define WS_THIN_NB 1.5f", "#define WS_THIN_UNSEEN 0.5f", "#define WS_COUNTER_WORDS 20u",
                 "#define WS_C_THIN_SEEN 16u", "#define WS_C_THIN_NARROW 18u"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    if comp.count("thick_weight(") != 2 or comp.count("ws_thin_seen") != 4 or comp.count("smoothstep(WS_THIN_H_LO") != 1:
        raise SystemExit("text check: the shader's r117d code is not there as designed")
    for want in ("inline float HeightWeight(", "float ThinWeight(", "thin_seen = 0", "ThinHLo = WS_THIN_H_LO"):
        if header.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (HDR, want))
    if header.count("ThinWeight(column,") != 1:
        raise SystemExit("text check: RayBlocked's call")
    if vk.count("Wind shelter (r117d)") != 1:
        raise SystemExit("text check: vk_wind_shelter.cpp")
    for line in vk.split("\n"):
        if "Wind shelter (r117d)" in line and len(line) > 130:
            raise SystemExit("text check: log line too long")
    if test.count("TestThin()") != 2:
        raise SystemExit("text check: test main")
    sample = ("Wind shelter (r117d): %d obstacle cells met by the rays, %.1f%% low (under 1.6 m), %.1f%% of the "
              "rest thin (one or two cells wide)" % (100000000, 100.0, 100.0))
    if len(sample) >= 300:
        raise SystemExit("text check: log line %d characters" % len(sample))
    if texts[RM].count("hardly counts)") != 1:
        raise SystemExit("text check: README lacks the new words")
    return model_checks()


def report(res, full):
    got, old = res
    print("model: all asserted numbers pass. r117c gave: a post close behind %.2f, a trunk %.2f, a 1.2 m rail %.2f, "
          "the 2 x 2 Hunter-sized block %.2f (r117d: %.2f, %.2f, %.2f, %.2f)" %
          (old["post 11"], old["trunk 11"], old["rail 1.2 m 11"], old["Hunter, no camera"],
           got["post 11 (r117c: 1)"], got["trunk 11 (r117c: 1)"], got["rail 1.2 m 11 (r117c: 0.2)"],
           got["Hunter, no camera (r117c: 1)"]))
    if full:
        seeds, winds = range(4), ((1, 0), (-0.707, 0.707))
        for kind, label in (("A", "r117c's synthetic graveyard"), ("B", "same plus trunks, rails, markers")):
            for thin, name in ((False, "r117c"), (True, "r117d")):
                (sm, slo, shi), (mm, mlo, mhi) = _synthetic(thin, kind, seeds, winds)
                print("synthetic %-34s %s: %.1f%% of the seen cells above 0.5 (min %.1f%%, max %.1f%%), mean %.3f"
                      % (label, name, 100 * sm, 100 * slo, 100 * shi, mm))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117D_ROOT)" % ROOT)
    for need in (COMP, LAY, HDR, VKC, TST):
        if not os.path.exists(os.path.join(ROOT, need)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % need)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        raw, eol, cur = load(path)
        if path == LAY and "WS_COVER_CLOSE" not in cur:
            raise SystemExit("r117c_shelter-outdoors is not applied (the layout has no WS_COVER_CLOSE)")
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
            print("applied (text checks and the model's numbers pass)")
        else:
            res = text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result and the "
                  "model's numbers pass)" % (len(plan), sum(len(p[1]) for p in plan)))
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
            tmp = full + ".r117dtmp"
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
        tmp = full + ".r117dtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
