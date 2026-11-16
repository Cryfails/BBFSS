# r117g_shelter-graveyard: FEATURE fix on top of r117_wind-shelter .. r117f_shelter-distance (r117f in b46). Still off with
# r117's knob BB_WIND_SHELTER (no new knob): every edit is in r117's own files, which only exist or run with the knob.
#
# WHAT b46 SHOWED (r117f-grave1, lamp1, none): graveyard 33.7% sheltered, mean 0.348 (target under 0.3), 11.4% indoors
# (field above 0.95; target under 8%), camera 0.01, OVERHEAD COVER 0.00 (share 0.12); 1.93M hits, 13% kept, 62% of the
# kept ones tall (4 m+), 75% far-cut. Red/orange on near-left grass and foreground, a left branch, the far-right tree, a
# tomb edge. lamp-test-spot 33.8% / 0.372 (pass), library 100% (pass).
#
# CAUSE (read from the numbers, not guessed at): the overhead cover is 0.00 at the graveyard, so the 11.4% "indoors"
# (above 0.95) is made by the rays alone: a hit counts 1 only within WS_DIST_NEAR (1 m) of a wide, tall thing. Two kinds
# of cell are in that case: the cells right behind a wall (true lee) and the cells that are PART of a wide tall thing (a
# tree mass, a building, a tomb row): the upwind neighbour of a cell inside such a thing is the same thing, one cell
# away, so the cell reads fully sheltered, and a depth sample is 100 times likelier to be on a trunk, a tomb face or a
# canopy than on the open ground between (vertical surfaces fill the picture). That is also the red branch, tomb edge and
# far-right tree. The cover rule (the task's "raise the overhead rule") is NOT the cause here (cover 0.00) and is NOT
# changed: the library's 100% comes from it and stays.
#
# FIX 1 (a short lee for low things, far_weight): the distance law now depends on the height of the thing. s =
# smoothstep(WS_SHORT_LO 2 m, WS_SHORT_HI 3 m, top above the ground): reach = WS_SHORT_REACH (3.5 m) + (WS_DIST_FAR - 3.5) s
# is where the weight stops falling, floor = WS_DIST_FLOOR s. A thing under 2 m (grass, plants, fences, a person) gives
# a lee of about 3 m and nothing beyond; a tomb (2-2.6 m) 3 m and a little more; a wall or tree from 3 m exactly as in
# r117f (so every r117f number for 3 m and taller things stays, and the lamp hall keeps its result). Cut-out plant cards
# are not told from solid things (the cache holds only the lowest and highest height of a cell).
# FIX 2 (self_weight): a cell that is itself tall (its own top 2-3 m or more above its ground: own_up) gets from a
# hit that does NOT rise above its own top only WS_SELF_KEEP (0.4) of the weight: smoothstep(0, WS_SELF_RISE 2 m,
# hit top - own top) is the share that rises: weight = 1 - k (1 - WS_SELF_KEEP) (1 - rise), k = smoothstep(WS_SELF_H_LO,
# WS_SELF_H_HI, own_up). So the inside and the top of a tree mass, a roof or a wall, where the wind blows freely, read
# about 0.4 (yellow) from the neighbours of its own height, never 1 (red); a wall or a tree that stands 2 m higher than the
# cell still counts in full. A real roof or a hall is 1 by the COVER (what the camera saw overhead: the library 100%);
# without cover a closed hall reads 0.4 (the r117 test 'in a hall: 1' now says 0.4, the cover being the rule). Cost on
# the lamp hall: its inner cells read a little less (it passes its target by 0.03).
# Counters (words 22 and 23 of the 24): hits cut by FIX 2 (counted in full without it) and seen cells that are tall; the
# log gets its own line 'Wind shelter (r117g)' with the first (early) report too, so the runner keeps it.
#
# Python model (the twin of the shader, below) on synthetic scenes: see the output of 'check'.
#
# Off: nothing here runs without r117's knob (the shader is only built into the pass r117 makes, BbWindShelter::
# KnobOnce().on; the constants and counter words are in r117's own header and layout; the log text is in r117's Report).
# BB_WIND off and BB_WIND_SHELTER off are unchanged.
# Cost on: raw pass: per obstacle cell that beats the ray's value two smoothsteps, one mix and a few multiplies more
# (far below 0.01 ms; the raw pass is 64 x 64 cells x 3 rays). Memory: none (counter words 22 and 23 of the 24 allocated).
# CPU: none.
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row).
# Use: python -I -X utf8 r117g_shelter-graveyard.py check | apply | revert
# Root: R117G_ROOT, else <tree>. Line ends kept. Needs r117 .. r117f applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117G_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117g_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAY_K_ANCHOR = "#define WS_ELEV_HI 0.50f\n"
LAY_K_AFTER = '''// r117g (see r117g_shelter-graveyard.py): the lee of a low thing is short: s = smoothstep(WS_SHORT_LO, WS_SHORT_HI, top above
// the ground); the distance weight reaches its floor (WS_DIST_FLOOR s) at WS_SHORT_REACH + (WS_DIST_FAR - WS_SHORT_REACH) s
// m. A cell that is itself tall (own top WS_SELF_H_LO..HI above its ground) takes from a hit that does not rise above its
// own top only WS_SELF_KEEP of the weight (the hit counts in full from WS_SELF_RISE m above the cell's top).
#define WS_SHORT_LO 2.0f
#define WS_SHORT_HI 3.0f
#define WS_SHORT_REACH 3.5f
#define WS_SELF_H_LO 2.0f
#define WS_SELF_H_HI 3.0f
#define WS_SELF_RISE 2.0f
#define WS_SELF_KEEP 0.4f
'''
LAY_C_ANCHOR = "#define WS_C_FAR_CUT 21u       // of the hits that beat the ray's value, those cut under 0.5 by distance/elevation (r117f)\n"
LAY_C_AFTER = '''#define WS_C_SELF_CUT 22u      // of the hits that counted 0.5 or more after distance/elevation, those the cell's own height cut under 0.5 (r117g)
#define WS_C_SELF_CELLS 23u    // seen window cells that are tall (own top WS_SELF_H_HI or more above their ground) (r117g)
'''

COMP_DOC_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_DOC_BEFORE = '''//  r117g  the lee of a low thing is short (far_weight: the distance weight reaches its floor at WS_SHORT_REACH m for a
//         thing under WS_SHORT_LO, at WS_DIST_FAR for one from WS_SHORT_HI), and a cell that is itself tall is sheltered by
//         a hit that does not rise above its own top only by WS_SELF_KEEP (self_weight): the inside and the top of a
//         tree mass, a roof or a wall is not "indoors" (the cover is what makes a real roof 1).
'''
COMP_DECL_ANCHOR = "uint ws_far_cut = 0u; // r117f: of the hits that beat the ray's value, those far_weight cut under 0.5\n"
COMP_DECL_AFTER = "uint ws_self_cut = 0u; // r117g: of the hits that counted 0.5 or more so far, those self_weight cut under 0.5\n"
COMP_FN_OLD = '''    const float wd = 1.0 - (1.0 - WS_DIST_FLOOR) * clamp((dist - WS_DIST_NEAR) / (WS_DIST_FAR - WS_DIST_NEAR), 0.0, 1.0);
    return wd * smoothstep(WS_ELEV_LO, WS_ELEV_HI, (top_above - WS_H_START) / dist);
}
'''
COMP_FN_NEW = '''    // r117g: a low thing (under WS_SHORT_LO) gives a lee WS_SHORT_REACH m long and nothing beyond, a tall one (from
    // WS_SHORT_HI) as in r117f: its floor and its reach by s
    const float s = smoothstep(WS_SHORT_LO, WS_SHORT_HI, top_above);
    const float reach = WS_SHORT_REACH + (WS_DIST_FAR - WS_SHORT_REACH) * s;
    const float wd = 1.0 - (1.0 - WS_DIST_FLOOR * s) * clamp((dist - WS_DIST_NEAR) / (reach - WS_DIST_NEAR), 0.0, 1.0);
    return wd * smoothstep(WS_ELEV_LO, WS_ELEV_HI, (top_above - WS_H_START) / dist);
}

// r117g: how much a hit of `top_above` m (its top over the ground) counts for a cell whose own top is `own_up` m over
// its ground: 1 for a cell that is not tall, and for a hit that rises WS_SELF_RISE m or more above the cell's top; down
// to WS_SELF_KEEP for a hit no higher than a tall cell's own top (the cell is part of the thing: the wind blows over it).
float self_weight(float top_above, float own_up) {
    const float k = smoothstep(WS_SELF_H_LO, WS_SELF_H_HI, own_up);
    const float over = smoothstep(0.0, WS_SELF_RISE, top_above - own_up);
    return 1.0 - k * (1.0 - WS_SELF_KEEP) * (1.0 - over);
}
'''
COMP_RAYSIG_OLD = "float ray(vec2 from, vec2 dir, float ground) {\n"
COMP_RAYSIG_NEW = "float ray(vec2 from, vec2 dir, float ground, float own_up) {\n"
COMP_HIT_OLD = "                    hit *= f_w;\n"
COMP_HIT_AFTER = '''                    // r117g: the cell's own height (a hit no higher than a tall cell's own top shelters it by WS_SELF_KEEP)
                    const float s_w = self_weight(col.y - ground, own_up);
                    if (s_w < 0.5 && hit >= 0.5) {
                        ++ws_self_cut;
                    }
                    hit *= s_w;
'''
COMP_RAYS_OLD = '''    const float r0 = ray(from, rotated(upwind, -WS_RAY_DEG), ground);
    const float r1 = ray(from, upwind, ground);
    const float r2 = ray(from, rotated(upwind, WS_RAY_DEG), ground);
'''
COMP_RAYS_NEW = '''    const float own_up = own.z > 0.0 ? own.y - ground : 0.0; // r117g: how tall the cell itself is
    const float r0 = ray(from, rotated(upwind, -WS_RAY_DEG), ground, own_up);
    const float r1 = ray(from, upwind, ground, own_up);
    const float r2 = ray(from, rotated(upwind, WS_RAY_DEG), ground, own_up);
'''
COMP_SEEN_OLD = '''    if (own.z > 0.0) {
        atomicAdd(counters.c[WS_C_CELLS_SEEN], 1u);
    }
'''
COMP_SEEN_NEW = '''    if (own.z > 0.0) {
        atomicAdd(counters.c[WS_C_CELLS_SEEN], 1u);
        if (own_up >= WS_SELF_H_HI) { // r117g
            atomicAdd(counters.c[WS_C_SELF_CELLS], 1u);
        }
    }
'''
COMP_ATOM_ANCHOR = "        atomicAdd(counters.c[WS_C_FAR_CUT], ws_far_cut);\n"
COMP_ATOM_AFTER = "        atomicAdd(counters.c[WS_C_SELF_CUT], ws_self_cut);\n"

HDR_K_ANCHOR = "                       ElevLo = WS_ELEV_LO, ElevHi = WS_ELEV_HI; // r117f\n"
HDR_K_AFTER = '''inline constexpr float ShortLo = WS_SHORT_LO, ShortHi = WS_SHORT_HI, ShortReach = WS_SHORT_REACH,
                       SelfHLo = WS_SELF_H_LO, SelfHHi = WS_SELF_H_HI, SelfRise = WS_SELF_RISE,
                       SelfKeep = WS_SELF_KEEP; // r117g
static_assert(ShortHi > ShortLo && SelfHHi > SelfHLo && SelfRise > 0.0f && ShortReach > DistNear && ShortReach <= DistFar &&
                  SelfKeep >= 0.0f && SelfKeep <= 1.0f,
              "the short lee's and the own height's edges");
'''
HDR_FN_OLD = '''    const float t = std::clamp((dist - DistNear) / (DistFar - DistNear), 0.0f, 1.0f);
    return (1.0f - (1.0f - DistFloor) * t) *
           BbWind::Smoothstep(ElevLo, ElevHi, (top_above_ground - HStart) / dist);
}
'''
HDR_FN_NEW = '''    // r117g: a low thing (under ShortLo) gives a lee ShortReach m long and nothing beyond, one from ShortHi as in r117f
    const float s = BbWind::Smoothstep(ShortLo, ShortHi, top_above_ground);
    const float reach = ShortReach + (DistFar - ShortReach) * s;
    const float t = std::clamp((dist - DistNear) / (reach - DistNear), 0.0f, 1.0f);
    return (1.0f - (1.0f - DistFloor * s) * t) *
           BbWind::Smoothstep(ElevLo, ElevHi, (top_above_ground - HStart) / dist);
}

/// r117g: how much a hit of `top_above_ground` m counts for a cell whose own top is `own_up` m over its ground
/// (wind_shelter.comp's self_weight): 1 for a cell that is not tall and for a hit rising SelfRise m or more above the
/// cell's top, down to SelfKeep for a hit no higher than a tall cell's own top.
[[nodiscard]] inline float SelfWeight(float top_above_ground, float own_up) {
    const float k = BbWind::Smoothstep(SelfHLo, SelfHHi, own_up);
    const float over = BbWind::Smoothstep(0.0f, SelfRise, top_above_ground - own_up);
    return 1.0f - k * (1.0f - SelfKeep) * (1.0f - over);
}
'''
HDR_SIG_OLD = "                               float ground, float cam_x = 1.0e9f, float cam_z = 1.0e9f) {\n"
HDR_SIG_NEW = "                               float ground, float cam_x = 1.0e9f, float cam_z = 1.0e9f, float own_up = 0.0f) {\n"
HDR_HIT_OLD = "                    hit *= FarWeight(dist, col.top - ground); // r117f: by the distance and the elevation\n"
HDR_HIT_AFTER = "                    hit *= SelfWeight(col.top - ground, own_up); // r117g: by the cell's own height\n"
HDR_RAYS_OLD = '''    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground, cam_x, cam_z);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground, cam_x, cam_z);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground, cam_x, cam_z);
'''
HDR_RAYS_NEW = '''    const float own_up = own.seen ? own.top - ground : 0.0f; // r117g: how tall the cell itself is
    const float r0 = RayBlocked(column, cx, cz, a[0], a[1], ground, cam_x, cam_z, own_up);
    const float r1 = RayBlocked(column, cx, cz, ux, uz, ground, cam_x, cam_z, own_up);
    const float r2 = RayBlocked(column, cx, cz, c[0], c[1], ground, cam_x, cam_z, own_up);
'''
HDR_CNT_ANCHOR = "    std::uint64_t far_cut = 0; ///< r117f\n"
HDR_CNT_AFTER = "    std::uint64_t self_cut = 0, self_cells = 0; ///< r117g\n"
HDR_CNTB_OLD = "            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL),        d(WS_C_FAR_CUT)};\n"
HDR_CNTB_NEW = "            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL),        d(WS_C_FAR_CUT),       d(WS_C_SELF_CUT),\n            d(WS_C_SELF_CELLS)};\n"

VK_ANCHOR = "    // r117f: the first report is the view line alone (the runner keeps 30 lines of the features under test, in the\n"
VK_BEFORE = '''    // r117g: its own line, with the view line (the first report too: the runner keeps the first and the last of a kind)
    BbReport::Printf("Wind shelter (r117g): %.1f%% of the %llu hits cut by the cell's own height, %.1f%% of the seen cells "
                     "are tall (%.0f m+); a low thing's lee %.1f m, keep %.1f\\n",
                     100.0 * double(c.self_cut) / std::max(1.0, double(c.thin_seen)), ull(c.thin_seen),
                     100.0 * double(c.self_cells) / std::max(1.0, double(c.cells_seen)), double(WS_SELF_H_HI),
                     double(WS_SHORT_REACH), double(WS_SELF_KEEP));
'''

TEST_TOMB_OLD = '    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.049f, 0.01f), "3 m behind it: 0.05 (r117e: 0.86; a 2 m tomb is low)");\n'
TEST_TOMB_NEW = '    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.013f, 0.01f), "3 m behind it: 0.02 (r117f: 0.05, r117e: 0.86; a 2 m tomb is low, its lee short)");\n'
TEST_ROOM_OLD = '''    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "in a hall: 1");
    Expect(Near(Raw(Room, 9, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "at its downwind edge: 1");
'''
TEST_ROOM_NEW = '''    // r117g: the cell is tall itself and the walls are no higher: 0.4 (the cover, what the camera saw overhead, makes it 1)
    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f), 0.4f, 1e-5f), "in a hall without cover: 0.4 (r117f: 1)");
    Expect(Near(Raw(Room, 9, 0, 1.0f, 0.0f, 1.7f), 0.4f, 1e-5f), "at its downwind edge: 0.4 (r117f: 1)");
    Expect(Near(Raw(Room, 0, 0, 1.0f, 0.0f, 1.7f, 1.0f), 1.0f, 1e-6f), "in a hall with cover 1: 1");
'''
TEST_PER_OLD = ('    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.367f, 0.05f), "without the camera\'s place the 2 x 2 block '
                'shelters by a third (r117f: 0.37, r117d: half)");\n')
TEST_PER_NEW = ('    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.25f, 0.05f), "without the camera\'s place the 2 x 2 block '
                'shelters by a quarter (r117g: 0.25, r117f: 0.37, r117d: half)");\n')
TEST_PER2_OLD = "    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.367f, 0.05f),\n"
TEST_PER2_NEW = "    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.25f, 0.05f),\n"
TEST_FAR_OLD = "    Expect(Near(FarWeight(6.0f, 3.0f), 0.0317f, 0.002f) && Near(FarWeight(3.0f, 2.0f), 0.0571f, 0.002f),\n"
TEST_FAR_NEW = "    Expect(Near(FarWeight(6.0f, 3.0f), 0.0317f, 0.002f) && Near(FarWeight(3.0f, 2.0f), 0.0148f, 0.002f),\n"

TEST_FN_ANCHOR = "void TestThin() {\n"
TEST_FN_BEFORE = '''// r117g: the lee of a low thing is short; a tall cell is sheltered by a hit no higher than its own top only by 0.4
void TestGraveyard() {
    Expect(FarWeight(1.0f, 2.0f) == 1.0f && Near(FarWeight(2.0f, 2.0f), 0.6f, 0.002f),
           "a 2 m thing: full at 1 m, 0.6 at 2 m (r117f 0.89)");
    Expect(Near(FarWeight(3.0f, 2.5f), 0.621f, 0.003f) && FarWeight(3.5f, 2.0f) < 1e-6f && FarWeight(5.0f, 1.9f) < 1e-6f,
           "a 2.5 m thing at 3 m, none from 3.5 m for a low one");
    Expect(Near(FarWeight(2.0f, 3.0f), 0.886f, 0.002f) && Near(FarWeight(4.0f, 3.0f), 0.657f, 0.002f) &&
               Near(FarWeight(4.0f, 9.0f), 0.657f, 0.002f),
           "a 3 m thing and the taller ones keep r117f's numbers");
    Expect(SelfWeight(8.0f, 0.0f) == 1.0f && SelfWeight(3.0f, 1.5f) == 1.0f && SelfWeight(1.0f, 1.9f) == 1.0f,
           "a cell that is not tall: every hit counts in full");
    Expect(Near(SelfWeight(3.0f, 3.0f), 0.4f, 1e-6f) && Near(SelfWeight(8.0f, 8.0f), 0.4f, 1e-6f) &&
               Near(SelfWeight(2.0f, 8.0f), 0.4f, 1e-6f),
           "a tall cell, a hit no higher: 0.4");
    Expect(Near(SelfWeight(4.0f, 3.0f), 0.7f, 1e-5f) && SelfWeight(5.0f, 3.0f) == 1.0f && SelfWeight(11.0f, 8.0f) == 1.0f,
           "a hit 1 m higher: 0.7; 2 m or more higher: 1");
    Expect(Near(SelfWeight(3.0f, 2.5f), 0.7469f, 1e-4f), "a cell 2.5 m tall is half a tall cell");
    // a tree mass (5 x 5 cells, 8 m): its inside is not sheltered by its own neighbours; behind it, it is
    Expect(Near(Raw(Tree, 10, 0, 1.0f, 0.0f, 1.7f), 0.4f, 0.02f) && Near(Raw(Tree, 11, 0, 1.0f, 0.0f, 1.7f), 0.4f, 0.02f),
           "inside a tree mass: 0.4 (r117f: 1)");
    Expect(Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "right behind it: 1");
    // the log's counter words
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_SELF_CUT] = 33;
    now[WS_C_SELF_CELLS] = 44;
    const auto c = CountsBetween(now.data(), before.data());
    Expect(WS_C_SELF_CELLS < WS_COUNTER_WORDS && c.self_cut == 33 && c.self_cells == 44 && c.far_cut == 0,
           "the own-height counts, word by word");
}

'''
TEST_MAIN_ANCHOR = "    TestFar();\n"
TEST_MAIN_AFTER = "    TestGraveyard();\n"

README_OLD = "so a low wall's lee is a few metres long and a far wall gives a faint one)"
README_NEW = ("so a low wall's lee is a few metres long and a far wall gives a faint one; a thing under 2 m gives a lee of "
              "about 3 m and no more; and a cell that is itself part of a tall thing, the inside and the top of a tree "
              "mass or a wall, is sheltered by things no higher than itself by two fifths at most, indoors being the "
              "business of the overhead cover alone)")

EDITS = {
    LAY: [("ins", LAY_K_ANCHOR, "", LAY_K_AFTER), ("ins", LAY_C_ANCHOR, "", LAY_C_AFTER)],
    COMP: [("ins", COMP_DOC_ANCHOR, COMP_DOC_BEFORE, ""), ("ins", COMP_DECL_ANCHOR, "", COMP_DECL_AFTER),
           ("rep", COMP_FN_OLD, COMP_FN_NEW), ("rep", COMP_RAYSIG_OLD, COMP_RAYSIG_NEW),
           ("ins", COMP_HIT_OLD, "", COMP_HIT_AFTER), ("rep", COMP_RAYS_OLD, COMP_RAYS_NEW),
           ("rep", COMP_SEEN_OLD, COMP_SEEN_NEW), ("ins", COMP_ATOM_ANCHOR, "", COMP_ATOM_AFTER)],
    HDR: [("ins", HDR_K_ANCHOR, "", HDR_K_AFTER), ("rep", HDR_FN_OLD, HDR_FN_NEW), ("rep", HDR_SIG_OLD, HDR_SIG_NEW),
          ("ins", HDR_HIT_OLD, "", HDR_HIT_AFTER), ("rep", HDR_RAYS_OLD, HDR_RAYS_NEW),
          ("ins", HDR_CNT_ANCHOR, "", HDR_CNT_AFTER), ("rep", HDR_CNTB_OLD, HDR_CNTB_NEW)],
    VKC: [("ins", VK_ANCHOR, VK_BEFORE, "")],
    TST: [("rep", TEST_TOMB_OLD, TEST_TOMB_NEW), ("rep", TEST_ROOM_OLD, TEST_ROOM_NEW), ("rep", TEST_FAR_OLD, TEST_FAR_NEW), ("rep", TEST_PER_OLD, TEST_PER_NEW), ("rep", TEST_PER2_OLD, TEST_PER2_NEW),
          ("ins", TEST_FN_ANCHOR, TEST_FN_BEFORE, ""), ("ins", TEST_MAIN_ANCHOR, "", TEST_MAIN_AFTER)],
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


# ---- the Python copy of the model (r117d, r117e, r117f, r117g), for the numbers the tests assert -------------
# mode 0 = r117e (no far weight), 1 = r117f, 2 = r117g
NEAR, FAR, FLOOR, ELO, EHI = 1.0, 8.0, 0.2, 0.30, 0.50
SLO, SHI, SREACH = 2.0, 3.0, 3.5
OLO, OHI, ORISE, OKEEP = 2.0, 3.0, 2.0, 0.4


def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _far(dist, top_above, mode):
    if mode == 0:
        return 1.0
    if mode == 1:
        t = min(max((dist - NEAR) / (FAR - NEAR), 0.0), 1.0)
        return (1.0 - (1.0 - FLOOR) * t) * _ss(ELO, EHI, (top_above - 1.0) / dist)
    s = _ss(SLO, SHI, top_above)
    reach = SREACH + (FAR - SREACH) * s
    t = min(max((dist - NEAR) / (reach - NEAR), 0.0), 1.0)
    return (1.0 - (1.0 - FLOOR * s) * t) * _ss(ELO, EHI, (top_above - 1.0) / dist)


def _self(top_above, own_up, mode):
    if mode < 2:
        return 1.0
    k = _ss(OLO, OHI, own_up)
    over = _ss(0.0, ORISE, top_above - own_up)
    return 1.0 - k * (1.0 - OKEEP) * (1.0 - over)


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
            if c and c[1] - g >= 1.5 and c[0] - g < 1.2:
                v = 1.0
            elif a == 0 and not c:
                v = max(v, 0.15)
        w += v
    return _ss(1.0, 3.0, w)


def _ray(col, cx, cz, dx, dz, g, cam, mode, tally, own_up):
    fx, fz, blocked, k = cx + 0.5, cz + 0.5, 0.0, 1
    while k <= 28 and blocked < 1.0:
        ix, iz = math.floor(fx + dx * k), math.floor(fz + dz * k)
        c = col(ix, iz)
        if c:
            ex, lift = min(max(c[1] - g - 1.0, 0.0), 2.0), c[0] - g
            keep = _keep(c[1] - g, math.hypot((ix + 0.5) - cam[0], (iz + 0.5) - cam[1]))
            hit = _ss(0.12, 0.40, ex / k) * (1.0 - _ss(1.2, 2.4, lift)) * keep
            if hit > blocked:
                tally[0] += 1
                hit *= _ss(1.2, 2.0, c[1] - g)
                if hit > blocked:
                    fw = _far(k, c[1] - g, mode)
                    if fw < 0.5:
                        tally[3] += 1
                    hit *= fw
                    sw = _self(c[1] - g, own_up, mode)
                    if sw < 0.5 and hit >= 0.5:
                        tally[4] += 1
                    hit *= sw
                    if hit > blocked:
                        hit *= _thick(col, fx + dx * k, fz + dz * k, dx, dz, g)
                        if hit >= 0.5:
                            tally[1] += 1
                            if c[1] - g >= 4.0:
                                tally[2] += 1
                blocked = max(blocked, hit)
        k += 1
    return blocked


def _rot(vx, vz, deg):
    a = math.radians(deg)
    return vx * math.cos(a) - vz * math.sin(a), vx * math.sin(a) + vz * math.cos(a)


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, mode=2, cam=(1e9, 1e9), tally=None):
    tally = tally if tally is not None else [0, 0, 0, 0, 0]
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    own_up = own[1] - g if own else 0.0
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g, cam, mode, tally, own_up), _ray(col, cx, cz, -dx, -dz, g, cam, mode, tally, own_up),
         _ray(col, cx, cz, c[0], c[1], g, cam, mode, tally, own_up)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    return 1.0 - (1.0 - lee) * (1.0 - cover)


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    tall = lambda x, z: _col(0, 9) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    post = lambda x, z: _col(0, 3) if x == 10 and z == 0 else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    tree = lambda x, z: _col(0, 8) if 8 <= x <= 12 and -2 <= z <= 2 else _col(0, 0)
    person = lambda x, z: _col(0, 1.9) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    big = lambda x, z: _col(0, 2.6) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    stone = lambda x, z: _col(0, 1.6) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    two = lambda x, z: _col(0, 3) if x == 10 and 0 <= z <= 1 else _col(0, 0)
    trunk = lambda x, z: _col(0, 8) if x == 10 and z == 0 else _col(0, 0)
    trunk_u = lambda x, z: _col(0, 8) if x == 10 and z == 0 else (None if x == 10 else _col(0, 0))
    overhang = lambda x, z: (_col(0, 8) if x == 10 and z == 0 else
                             _col(4, 8) if x == 10 and -2 <= z <= 2 else _col(0, 0))
    standing = lambda x, z: _col(0, 8) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    step = lambda x, z: (_col(0, 3) if x == 10 and -3 <= z <= 3 else (None if x == 11 and z == 0 else _col(0, 0)))
    room = lambda x, z: _col(0, 3) if -10 <= x <= 10 and -10 <= z <= 10 else None
    rs = math.sqrt(0.5)
    cam = (11.5, 0.5)
    got = {}
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 12", _raw(wall, 12, 0, 1, 0), 0.886, 0.01), ("wall 14", _raw(wall, 14, 0, 1, 0), 0.657, 0.01),
        ("wall 16", _raw(wall, 16, 0, 1, 0), 0.027, 0.01), ("wall 20", _raw(wall, 20, 0, 1, 0), 0.0, 0.005),
        ("wall 26", _raw(wall, 26, 0, 1, 0), 0.0, 0.01), ("wall wind -x, cell 7", _raw(wall, 7, 0, -1, 0), 0.771, 0.01),
        ("wall diagonal 13", _raw(wall, 13, 0, rs, rs), 0.657, 0.02),
        ("wall, cover .3, 11", _raw(wall, 11, 0, 1, 0, cover=0.3), 1.0, 1e-6),
        ("wall, cover .5, 14", _raw(wall, 14, 0, 1, 0, cover=0.5), 1.0 - (1.0 - 0.657) * 0.5, 0.01),
        ("tomb 11", _raw(tomb, 11, 0, 1, 0), 1.0, 0.01), ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.013, 0.01),
        ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("tall 11", _raw(tall, 11, 0, 1, 0), 1.0, 0.01), ("tall 16", _raw(tall, 16, 0, 1, 0), 0.367, 0.01),
        ("tall 20", _raw(tall, 20, 0, 1, 0), 0.04, 0.01), ("tall 27", _raw(tall, 27, 0, 1, 0), 0.0, 0.0),
        ("tree 13", _raw(tree, 13, 0, 1, 0), 1.0, 0.01), ("tree 21", _raw(tree, 21, 0, 1, 0), 0.061, 0.02),
        ("tree inside 10", _raw(tree, 10, 0, 1, 0), 0.4, 0.02), ("tree inside 11", _raw(tree, 11, 0, 1, 0), 0.4, 0.02),
        ("post 11", _raw(post, 11, 0, 1, 0), 0.0, 0.0), ("trunk 11", _raw(trunk, 11, 0, 1, 0), 0.0, 0.0),
        ("trunk, neighbours unknown 11", _raw(trunk_u, 11, 0, 1, 0), 0.216, 0.01),
        ("trunk, neighbours unknown 13", _raw(trunk_u, 13, 0, 1, 0), 0.0, 0.0),
        ("trunk with branches over it 11", _raw(overhang, 11, 0, 1, 0), 0.0, 0.0),
        ("canopy to the ground 11", _raw(standing, 11, 0, 1, 0), 1.0, 0.01),
        ("step_up 11", _raw(step, 11, 0, 1, 0), 1.0, 0.01),
        ("room 0", _raw(room, 0, 0, 1, 0), 0.4, 1e-5), ("room 9", _raw(room, 9, 0, 1, 0), 0.4, 1e-5),
        ("room 0, cover 1", _raw(room, 0, 0, 1, 0, cover=1.0), 1.0, 1e-6),
        ("two cells wide 11", _raw(two, 11, 0, 1, 0), 0.5, 0.1), ("fence 1.6 m 11", _raw(stone, 11, 0, 1, 0), 0.5, 0.05),
        ("Hunter, no camera", _raw(person, 11, 0, 1, 0), 0.25, 0.05),
        ("Hunter, camera next to it", _raw(person, 11, 0, 1, 0, cam=cam), 0.0, 0.0),
        ("big tomb, camera next to it", _raw(big, 11, 0, 1, 0, cam=cam), 0.5, 0.1),
        ("Hunter, camera 19 m away", _raw(person, 11, 0, 1, 0, cam=(30.5, 0.5)), 0.25, 0.05),
        ("wall 12, camera next to it", _raw(wall, 12, 0, 1, 0, cam=cam), 0.886, 0.01),
        ("wall 16, camera next to it", _raw(wall, 16, 0, 1, 0, cam=cam), 0.0, 0.05),
    ]
    for name, g, expect, tol in want:
        got[name] = g
        if abs(g - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, g, expect, tol))
    far = {(1, 3): 1.0, (1, 9): 1.0, (4, 8): 0.657, (4, 4): 0.657, (8, 20): 0.2, (30, 30): 0.2, (6, 3): 0.0317,
           (3, 2): 0.0148, (10, 5.66): 0.1846, (1, 2): 1.0, (2, 2): 0.6, (3, 2.5): 0.621, (3.5, 2.0): 0.0,
           (5, 1.9): 0.0, (2, 3): 0.886, (4, 3): 0.657}
    last = 2.0
    for d in range(1, 29):
        w = _far(float(d), 9.0, 2)
        if w > last + 1e-6 or (d <= 16 and w < 0.2 - 1e-6):
            raise SystemExit("model check: TestFar's loop fails at %d m (%.4f)" % (d, w))
        last = w
    if not _far(17.0, 9.0, 2) < 0.2:
        raise SystemExit("model check: TestFar's 17 m check")
    for (d, t), v in far.items():
        if abs(_far(d, t, 2) - v) > 0.003:
            raise SystemExit("model check: far weight (%s, %s) is %.4f, the test asserts %.4f" % (d, t, _far(d, t, 2), v))
    sw = [((8.0, 0.0), 1.0), ((3.0, 1.5), 1.0), ((1.0, 1.9), 1.0), ((3.0, 3.0), 0.4), ((8.0, 8.0), 0.4), ((2.0, 8.0), 0.4),
          ((4.0, 3.0), 0.7), ((5.0, 3.0), 1.0), ((11.0, 8.0), 1.0), ((3.0, 2.5), 0.7469)]
    for (t, o), v in sw:
        if abs(_self(t, o, 2) - v) > 1e-4:
            raise SystemExit("model check: self weight (%s, %s) is %.5f, the test asserts %.5f" % (t, o, _self(t, o, 2), v))
    old = {"wall 16": _raw(wall, 16, 0, 1, 0, mode=0), "wall 20": _raw(wall, 20, 0, 1, 0, mode=0),
           "tree 21": _raw(tree, 21, 0, 1, 0, mode=0)}
    if not (abs(old["wall 16"] - 0.857) < 0.01 and abs(old["wall 20"] - 0.198) < 0.01 and abs(old["tree 21"] - 0.30) < 0.05):
        raise SystemExit("model check: r117e's numbers are not as described: %s" % old)
    f117 = {"tomb 13": _raw(tomb, 13, 0, 1, 0, mode=1), "room 0": _raw(room, 0, 0, 1, 0, mode=1),
            "tree inside 10": _raw(tree, 10, 0, 1, 0, mode=1)}
    return got, old, f117


# synthetic scenes: share of the seen cells above 0.5 / above 0.95 and the mean field, no cover. B and C are r117d/e's
# graveyards (C: bare trees, many cache gaps); D is a hall like the lamp-test-spot: 8 m side and back walls, a colonnade
# of 6 m one-cell columns every 4 m on the other side, open in front, clutter, cache gaps; E the same with a solid wall.
def _scene(seed, kind):
    import random
    rnd = random.Random(seed)
    cells = {}

    def put(x, z, top, bot=0.0):
        k = (x, z)
        cells[k] = (min(cells[k][0], bot), max(cells[k][1], top)) if k in cells else (bot, top)
    if kind in ("D", "E"):
        for x in range(-12, 13):
            put(x, -7, 8.0)
        for z in range(-7, 8):
            put(-12, z, 8.0)
        for x in range(-12, 13, 1 if kind == "E" else 4):
            put(x, 7, 6.0)
        for _ in range(6):
            put(rnd.randint(-10, 10), rnd.randint(-5, 5), rnd.uniform(1.0, 1.8))
        for _ in range(8):
            put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(5, 9))
        gap = 7
    else:
        for _ in range(9):
            tx, tz = rnd.randint(-26, 26), rnd.randint(-26, 26)
            top = rnd.uniform(7, 9)
            for j in range(-2, 3):
                for i in range(-2, 3):
                    core = abs(i) <= 1 and abs(j) <= 1
                    if kind == "C" and not core:
                        put(tx + i, tz + j, top - rnd.uniform(0, 1.5), 3.0)
                    else:
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
        for j in range(2):
            for i in range(2):
                put(3 + i, j - 1, 1.9)
        for _ in range(14):
            put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(5, 9))
        for _ in range(8):
            rx, rz = rnd.randint(-26, 18), rnd.randint(-28, 28)
            horiz = rnd.random() < 0.5
            for i in range(8):
                put(rx + (i if horiz else 0), rz + (0 if horiz else i), 1.5)
        for _ in range(40):
            put(rnd.randint(-28, 28), rnd.randint(-28, 28), rnd.uniform(1.4, 2.2))
        gap = 4 if kind == "C" else 6

    def col(x, z):
        if (x, z) in cells:
            return (_q(cells[(x, z)][0]), _q(cells[(x, z)][1]))
        if (x * 7919 + z * 104729 + seed) % 10 < gap:
            return _col(0, 0)
        return None
    return col


def _synthetic(mode, kind, seeds, winds, area):
    n, shares, ind, means, tally = 64, [], [], [], [0, 0, 0, 0, 0]
    for seed in seeds:
        col = _scene(seed, kind)
        for w in winds:
            g = [[_raw(col, i - 32, j - 32, w[0], w[1], mode=mode, cam=(0.5, 0.5), tally=tally) for i in range(n)]
                 for j in range(n)]
            tot = sh = ih = 0
            sm = 0.0
            for j in range(32 - area[1], 32 + area[1]):
                for i in range(32 - area[0], 32 + area[0]):
                    if col(i - 32, j - 32) is None:
                        continue
                    b = 0.0
                    for dj in (-1, 0, 1):
                        for di in (-1, 0, 1):
                            b += (2 - abs(di)) * (2 - abs(dj)) / 16.0 * g[j + dj][i + di]
                    v = min(b * 1.06, 1.0)
                    tot += 1
                    sh += v > 0.5
                    ih += v > 0.95
                    sm += v
            shares.append(sh / tot)
            ind.append(ih / tot)
            means.append(sm / tot)
    f = lambda a: sum(a) / len(a)
    return f(shares), f(ind), f(means), tally


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_SHORT_LO 2.0f", "#define WS_SHORT_HI 3.0f", "#define WS_SHORT_REACH 3.5f",
                 "#define WS_SELF_H_LO 2.0f", "#define WS_SELF_H_HI 3.0f", "#define WS_SELF_RISE 2.0f",
                 "#define WS_SELF_KEEP 0.4f", "#define WS_C_SELF_CUT 22u", "#define WS_C_SELF_CELLS 23u",
                 "#define WS_COUNTER_WORDS 24u"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    if (comp.count("float self_weight(") != 1 or comp.count("self_weight(col.y - ground, own_up)") != 1 or
            comp.count("ws_self_cut") != 3 or comp.count("float ray(vec2 from, vec2 dir, float ground, float own_up)") != 1 or
            comp.count(", ground, own_up);") != 3 or comp.count("WS_C_SELF_CELLS") != 1):
        raise SystemExit("text check: the shader's r117g code is not there as designed")
    if (header.count("SelfWeight(col.top - ground, own_up)") != 1 or header.count("float SelfWeight(") != 1 or
            header.count("cam_z, own_up);") != 3 or header.count("self_cells = 0") != 1):
        raise SystemExit("text check: %s" % HDR)
    if vk.count("Wind shelter (r117g)") != 1:
        raise SystemExit("text check: vk_wind_shelter.cpp")
    if "r117g_shelter-graveyard" not in open(os.path.abspath(__file__), encoding="utf-8").read():
        raise SystemExit("text check: self")
    if test.count("TestGraveyard()") != 2 or texts[RM].count("two fifths at most") != 1:
        raise SystemExit("text check: test main or README")
    # the r117g line is short; the first (view) line is r117f's and unchanged
    line = ("Wind shelter (r117g): %.1f%% of the %d hits cut by the cell's own height, %.1f%% of the seen cells are tall "
            "(%.0f m+); a low thing's lee %.1f m, keep %.1f" % (100.0, 123456789, 100.0, 3.0, 3.5, 0.4))
    if len(line) >= 300:
        raise SystemExit("text check: the r117g line is %d characters" % len(line))
    return model_checks(), len(line)


def report(res, full):
    (got, old, f117), n = res
    print("model: all asserted numbers pass; the r117g log line at worst %d characters (limit 299)." % n)
    print("  tomb (2 m) 3 m behind: r117f %.3f -> r117g %.3f; a tree mass (5 x 5 cells), inside: r117f %.2f -> r117g %.2f; "
          "a closed hall without cover: r117f %.2f -> r117g %.2f" % (f117["tomb 13"], got["tomb 13"], f117["tree inside 10"],
                                                                     got["tree inside 10"], f117["room 0"], got["room 0"]))
    print("  a 3 m wall, lee at 2 / 4 / 6 m: %.2f / %.2f / %.2f (unchanged from r117f); a 9 m wall at 6 / 10 m: %.2f / %.2f"
          % (got["wall 12"], got["wall 14"], got["wall 16"], got["tall 16"], got["tall 20"]))
    if full:
        seeds, winds = range(2), ((1, 0), (-0.707, 0.707))
        for kind, label, area in (("B", "graveyard scene B (40% gaps)", (24, 24)), ("C", "graveyard C, bare trees", (24, 24)),
                                  ("D", "hall, colonnade side", (12, 7)), ("E", "hall, solid walls", (12, 7))):
            for mode, name in ((1, "r117f"), (2, "r117g")):
                sm, ih, mm, t = _synthetic(mode, kind, seeds, winds, area)
                print("synthetic %-30s %s: %.1f%% of the seen cells above 0.5, %.1f%% above 0.95, mean %.3f; hits %d, "
                      "kept %.0f%%, own-cut %.1f%%" % (label, name, 100 * sm, 100 * ih, mm, t[0], 100.0 * t[1] / max(1, t[0]),
                                                      100.0 * t[4] / max(1, t[0])))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117G_ROOT)" % ROOT)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % path)
        raw, eol, cur = load(path)
        if path == LAY and "WS_C_FAR_CUT" not in cur:
            raise SystemExit("r117f_shelter-distance is not applied (the layout has no WS_C_FAR_CUT)")
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
            tmp = full + ".r117gtmp"
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
        tmp = full + ".r117gtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
