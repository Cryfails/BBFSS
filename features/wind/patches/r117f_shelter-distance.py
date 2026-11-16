# r117f_shelter-distance: FEATURE fix on top of r117_wind-shelter, r117b, r117c, r117d and r117e_shelter-proof (all
# applied and built; r117e in b43). Still off with r117's knob BB_WIND_SHELTER (no new knob): every edit is in
# r117's own files, which only exist or run with the knob (see "Off" below).
#
# WHAT b43 SHOWED (r117e-lamp1): lamp-test-spot (a colonnade hall open to one side) 51.3% sheltered, mean 0.496
# (target well under 0.5); of 497,304 hits 72% of the kept ones are tall walls and columns, with full weight wherever
# along the 28 m rays they were hit. The graveyard and library jobs printed only the 'first pass' line.
#
# CAUSE OF THE MISSING LINES (read from the runner, Test-BBFSSSlot.ps1): it keeps the first and last line of each
# kind, puts the lines of the features under test first (the pattern matches '(r117...') and cuts THAT list at 30,
# in the order the lines first appear in the log. A line printed late (the view line came at frame 300 or 120 passes,
# after the lines of halation, flicker, camera, wind sway, twigs, fog noise...) falls behind the 30th. The library
# job's only line was a fallback print in the loading frames with 0 depth samples.
#
# FIX 1 (the proof, vk_wind_shelter.cpp):
#  a. the view line comes EARLY: after 60 passes (was 120), or after 240 frames when at least 20 passes were made (was:
#     300 frames whatever happened, which in a loading screen is a line with 0 samples that then used up the 'first'
#     report); a run that never makes 20 passes still gets its diagnostic line after 1200 frames. The report is
#     BRIEF the first time (only the view line: one kind, so one slot of the runner's 30), the other three lines
#     (window, r117c, r117d) come with the second and later reports (every 300 frames, only with 20 passes).
#  b. the view line carries one more number: '... %.0f%% far' (of the hits, the share the distance and elevation
#     weight cut under half). The engine does not see the runner's captures; frame 240 and 60 passes are early
#     enough for the jobs (they wait for 20 s after the capture).
#
# FIX 2 (the model, a short lee for low things, a faint one far away): in ray(), after the height weight a hit
# that still matters is multiplied by far_weight(dist, top above ground) =
#     wd * ge,   wd = 1 - (1 - WS_DIST_FLOOR) * clamp((dist - WS_DIST_NEAR) / (WS_DIST_FAR - WS_DIST_NEAR), 0, 1)
#     ge = smoothstep(WS_ELEV_LO, WS_ELEV_HI, (top - ground - WS_H_START) / dist)     [the REAL height: the cap of
#                                                                                     r117c does not apply]
# WS_DIST_NEAR 1 m, WS_DIST_FAR 8 m, WS_DIST_FLOOR 0.2, WS_ELEV_LO/HI 0.30/0.50 (the tangent of 17 and 27 degrees: the
# thing must rise about 25 degrees above the receiving point (1 m over the ground) to count in full). Why not the
# suggested 1 - d/28 (floor 0.25): the python model (below) puts the lamp-test-spot-like hall only 10% lower with it
# (hits at 20 m barely exist: the r117c tangent term already cuts everything beyond 17 m), because most hits are
# near. This law reaches its floor at 8 m, so a wall 3 m high shelters fully right behind it, 0.89 at 2 m, 0.66 at
# 4 m, 0.03 at 6 m (was 0.86, a short lee: it is that tall), a 9 m wall 0.37 at 6 m, 0.04 at 10 m; a far tall wall or
# a tree still gives a faint lee, never more than 0.2 beyond 8 m. The thick_weight look (the neighbours across the ray)
# is made only when the far-weighted hit still beats the ray's value (a little cheaper). Python model, synthetic
# scenes (sheltered share of the seen cells / mean): r117e -> r117f, see the output of 'check' (graveyard-like scenes
# B and C about -15%, a colonnade-like hall -20..-25%).
# NOT done: a per-cell share of solid samples (the r117e fallback idea) and a cut-out classification.
#
# Off: nothing here runs without r117's knob (the shader is only built into the pass r117 makes, BbWindShelter::
# KnobOnce().on; the new constants and the counter word are in r117's own header and layout; the log text is in
# r117's Report). BB_WIND off and BB_WIND_SHELTER off are unchanged.
# Cost on: raw pass: one smoothstep, one clamp and one multiply per obstacle cell that beats the ray's value (far
# below 0.01 ms; thick_weight, the dearest part, runs for fewer hits than before). Memory: none (counter word 21 of the
# 24 already allocated). CPU: none.
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row).
# Use: python -I -X utf8 r117f_shelter-distance.py check | apply | revert
# Root: R117F_ROOT, else <tree>. Line ends kept. Needs r117, r117b, r117c, r117d and r117e applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117F_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117f_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAY_TALL_ANCHOR = "#define WS_TALL_H 4.0f\n"
LAY_TALL_AFTER = '''// r117f: a hit that beats the ray's value counts by far_weight(dist, top above the ground): 1 up to WS_DIST_NEAR m,
// falling to WS_DIST_FLOOR at WS_DIST_FAR m, times smoothstep(WS_ELEV_LO, WS_ELEV_HI, tangent of the elevation of its
// top above WS_H_START over the ground, seen from the cell; 0.30 / 0.50 = 17 / 27 degrees).
#define WS_DIST_NEAR 1.0f
#define WS_DIST_FAR 8.0f
#define WS_DIST_FLOOR 0.2f
#define WS_ELEV_LO 0.30f
#define WS_ELEV_HI 0.50f
'''
LAY_C_ANCHOR = "#define WS_C_THIN_TALL 20u     // of the kept ones, those with a top WS_TALL_H or more above the ground\n"
LAY_C_AFTER = "#define WS_C_FAR_CUT 21u       // of the hits that beat the ray's value, those cut under 0.5 by distance/elevation (r117f)\n"

COMP_DOC_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_DOC_BEFORE = '''//  r117f  a hit that beats the ray's value counts less with its distance (full to WS_DIST_NEAR m, WS_DIST_FLOOR from
//         WS_DIST_FAR m) and only when its top rises about 25 degrees (WS_ELEV_LO..HI) above the cell, by its real
//         height: far_weight(). A low wall or a tomb gives a short lee, a far tall wall a faint one.
'''
COMP_DECL_ANCHOR = "uint ws_thin_tall = 0u; // of them, with a top WS_TALL_H or more above the ground\n"
COMP_DECL_AFTER = "uint ws_far_cut = 0u; // r117f: of the hits that beat the ray's value, those far_weight cut under 0.5\n"
COMP_FN_ANCHOR = "// One ray from the cell centre `from` (world, m) upwind along `dir`: how far it is blocked, 0-1.\n"
COMP_FN_BEFORE = '''// r117f: how much an obstacle of `top_above` m (its top over the ground) counts at `dist` m along a ray: its weight
// by distance (1 up to WS_DIST_NEAR, WS_DIST_FLOOR from WS_DIST_FAR, linear between) times how far its top rises above
// the receiving point (WS_H_START over the ground): smoothstep(WS_ELEV_LO, WS_ELEV_HI, tangent), the real height.
float far_weight(float dist, float top_above) {
    const float wd = 1.0 - (1.0 - WS_DIST_FLOOR) * clamp((dist - WS_DIST_NEAR) / (WS_DIST_FAR - WS_DIST_NEAR), 0.0, 1.0);
    return wd * smoothstep(WS_ELEV_LO, WS_ELEV_HI, (top_above - WS_H_START) / dist);
}

'''
COMP_TW_OLD = "                    const float t_w = thick_weight(from + dir * dist, dir, ground);\n"
COMP_TW_NEW = '''                    // r117f: by the distance and the elevation; the width only when the hit still beats the ray
                    const float f_w = far_weight(dist, col.y - ground);
                    if (f_w < 0.5) {
                        ++ws_far_cut;
                    }
                    hit *= f_w;
                    const float t_w = hit > blocked ? thick_weight(from + dir * dist, dir, ground) : 1.0;
'''
COMP_KEPT_OLD = "                    if (hit * t_w >= 0.5) { // r117e: a hit that still counts (for the log)\n"
COMP_KEPT_NEW = "                    if (hit * t_w >= 0.5 && hit > blocked) { // r117e: a hit that still counts (for the log)\n"
COMP_ATOM_ANCHOR = "        atomicAdd(counters.c[WS_C_THIN_TALL], ws_thin_tall);\n"
COMP_ATOM_AFTER = "        atomicAdd(counters.c[WS_C_FAR_CUT], ws_far_cut);\n"

HDR_K_ANCHOR = "                       ThinWHi = WS_THIN_W_HI, ThinNb = WS_THIN_NB, ThinUnseen = WS_THIN_UNSEEN; // r117d\n"
HDR_K_AFTER = '''inline constexpr float DistNear = WS_DIST_NEAR, DistFar = WS_DIST_FAR, DistFloor = WS_DIST_FLOOR,
                       ElevLo = WS_ELEV_LO, ElevHi = WS_ELEV_HI; // r117f
static_assert(DistFar > DistNear && ElevHi > ElevLo && ElevLo > 0.0f && DistFloor > 0.0f && DistFloor <= 1.0f,
              "the far weight's edges");
'''
HDR_FN_ANCHOR = "/// r117d: the weight of an obstacle by its width across a ray: the thing met at the world point (x, z) m by a\n"
HDR_FN_BEFORE = '''/// r117f: how much an obstacle counts at `dist` m along a ray (wind_shelter.comp's far_weight): its weight by distance
/// (1 up to DistNear, DistFloor from DistFar, linear between) times Smoothstep(ElevLo, ElevHi, the tangent of the
/// elevation of its top, `top_above_ground` less HStart, over `dist`): its real height, no cap.
[[nodiscard]] inline float FarWeight(float dist, float top_above_ground) {
    const float t = std::clamp((dist - DistNear) / (DistFar - DistNear), 0.0f, 1.0f);
    return (1.0f - (1.0f - DistFloor) * t) *
           BbWind::Smoothstep(ElevLo, ElevHi, (top_above_ground - HStart) / dist);
}

'''
HDR_TW_OLD = ("                    hit *= ThinWeight(column, fx + dx * dist, fz + dz * dist, dx, dz, ground);\n"
              "                    blocked = std::max(blocked, hit);\n")
HDR_TW_NEW = '''                    hit *= FarWeight(dist, col.top - ground); // r117f: by the distance and the elevation
                    if (hit > blocked) {
                        hit *= ThinWeight(column, fx + dx * dist, fz + dz * dist, dx, dz, ground);
                    }
                    blocked = std::max(blocked, hit);
'''
HDR_CNT_ANCHOR = "    std::uint64_t thin_kept = 0, thin_tall = 0; ///< r117e\n"
HDR_CNT_AFTER = "    std::uint64_t far_cut = 0; ///< r117f\n"
HDR_CNTB_OLD = "            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL)};\n"
HDR_CNTB_NEW = "            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL),        d(WS_C_FAR_CUT)};\n"

VK_FL_OLD = "constexpr u32 FirstLineFrames = 120; ///< the first line comes sooner, for short test runs\n"
VK_FL_NEW = '''constexpr u32 FirstLineFrames = 60; ///< the first line comes sooner, for short test runs (r117f: was 120 passes)
constexpr u32 FirstLineSure = 240;  ///< r117f: or after this many frames, once ReportMinPasses passes were made
constexpr u32 ReportMinPasses = 20; ///< r117f: no report from loading frames (a line with 0 samples is not a view)
'''
VK_DONE_OLD = "        if (stats.frames >= LineFrames || (!reported && stats.passes >= FirstLineFrames)) {\n"
VK_DONE_NEW = '''        // r117f: a report needs ReportMinPasses passes (else only after 4 x LineFrames frames: the diagnostic of an
        // effect that never runs); the first comes after FirstLineFrames passes or FirstLineSure frames
        if (stats.frames >= 4 * LineFrames ||
            (stats.passes >= ReportMinPasses &&
             (stats.frames >= (reported ? LineFrames : FirstLineSure) ||
              (!reported && stats.passes >= FirstLineFrames)))) {
'''
VK_FMT_OLD = '                     "hits %llu: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall\\n",\n'
VK_FMT_NEW = '                     "hits %llu: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall %.0f%% far\\n",\n'
VK_ARGS_OLD = "                     100.0 * double(c.thin_tall) / std::max(1.0, double(c.thin_kept)));\n"
VK_ARGS_NEW = '''                     100.0 * double(c.thin_tall) / std::max(1.0, double(c.thin_kept)),
                     100.0 * double(c.far_cut) / std::max(1.0, double(c.thin_seen))); // r117f: of all hits (at most 100%)
'''
VK_BRIEF_ANCHOR = '    BbReport::Printf("Wind shelter (r117): the window: %.0f of %llu cells with depth data a frame "\n'
VK_BRIEF_BEFORE = '''    // r117f: the first report is the view line alone (the runner keeps 30 lines of the features under test, in the
    // order they first appear: the view line must be early and one kind); the others come with the second report
    static bool view_told = false;
    if (!std::exchange(view_told, true)) {
        stats = {};
        return;
    }
'''

TEST_W_OLD = '''    for (int x : {11, 12, 14}) {
        Expect(Near(Raw(Wall, x, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "close behind a wall: 1");
    }
    Expect(Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "6 m behind a 3 m wall: 0.86");
    Expect(Near(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f), 0.198f, 0.01f), "10 m behind it: 0.2");
'''
TEST_W_NEW = '''    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f), "close behind a wall: 1");
    // r117f: a hit counts less with its distance and only above an elevation of about 25 degrees
    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f), 0.886f, 0.01f) && Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f), 0.657f, 0.01f),
           "2 m and 4 m behind a 3 m wall: 0.89 and 0.66 (r117e: 1)");
    Expect(Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.027f, 0.01f), "6 m behind a 3 m wall: 0.03 (r117e: 0.86)");
    Expect(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f) < 0.005f, "10 m behind it: 0 (r117e: 0.2)");
'''
TEST_NX_OLD = '''    Expect(Raw(Wall, 7, 0, -1.0f, 0.0f, 1.7f) > 0.99f, "wind toward -x: the cell at 7 is behind it");
    const float r = std::sqrt(0.5f);
    Expect(Raw(Wall, 13, 0, r, r, 1.7f) > 0.99f, "a diagonal wind: behind the wall too");
'''
TEST_NX_NEW = '''    Expect(Near(Raw(Wall, 7, 0, -1.0f, 0.0f, 1.7f), 0.771f, 0.01f), "wind toward -x: the cell at 7 is behind it (3 m: 0.77)");
    const float r = std::sqrt(0.5f);
    Expect(Near(Raw(Wall, 13, 0, r, r, 1.7f), 0.657f, 0.02f), "a diagonal wind: behind the wall too (4 m along the ray: 0.66)");
'''
TEST_TOMB_OLD = '    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "3 m behind it: 0.86");\n'
TEST_TOMB_NEW = '    Expect(Near(Raw(Tomb, 13, 0, 1.0f, 0.0f, 1.7f), 0.049f, 0.01f), "3 m behind it: 0.05 (r117e: 0.86; a 2 m tomb is low)");\n'
TEST_CV1_OLD = '    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.3f), 1.0f, 1e-6f), "behind a wall with cover: still 1");\n'
TEST_CV1_NEW = '    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f, 0.3f), 1.0f, 1e-6f), "behind a wall with cover: still 1");\n'
TEST_CV2_OLD = "    Expect(Near(Raw(Wall, 20, 0, 1.0f, 0.0f, 1.7f, 0.5f), 1.0f - (1.0f - 0.198f) * 0.5f, 0.01f),\n"
TEST_CV2_NEW = "    Expect(Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f, 0.5f), 1.0f - (1.0f - 0.657f) * 0.5f, 0.01f),\n"

TEST_OUT_OLD = '''    // an obstacle counts at most as a 3 m wall: a 9 m wall gives the 3 m wall's numbers
    Expect(Near(Raw(TallWall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f), "6 m behind a 9 m wall: as behind a 3 m one");
    Expect(Near(Raw(TallWall, 20, 0, 1.0f, 0.0f, 1.7f), 0.198f, 0.01f), "10 m behind it: 0.2");
'''
TEST_OUT_NEW = '''    // an obstacle counts at most as a 3 m wall in the tangent (r117c), by its real height in the elevation (r117f)
    Expect(Near(Raw(TallWall, 16, 0, 1.0f, 0.0f, 1.7f), 0.367f, 0.01f), "6 m behind a 9 m wall: 0.37 (r117e: as behind a 3 m one, 0.86)");
    Expect(Near(Raw(TallWall, 20, 0, 1.0f, 0.0f, 1.7f), 0.04f, 0.01f), "10 m behind it: 0.04 (r117e: 0.2)");
'''
TEST_TREE_OLD = "    Expect(Near(Raw(Tree, 21, 0, 1.0f, 0.0f, 1.7f), 0.30f, 0.05f) && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,\n"
TEST_TREE_NEW = "    Expect(Near(Raw(Tree, 21, 0, 1.0f, 0.0f, 1.7f), 0.061f, 0.02f) && Raw(Tree, 13, 0, 1.0f, 0.0f, 1.7f) > 0.99f,\n"
TEST_TREE_MSG_OLD = '           "a tree: sheltered close behind it, 0.3 at 9 m (r117b: 1.0 there)");\n'
TEST_TREE_MSG_NEW = '           "a tree: sheltered close behind it, 0.06 at 9 m (r117e: 0.3, r117b: 1.0)");\n'
TEST_PER_OLD = ('    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.5f, 0.1f), "without the camera\'s place the 2 x 2 block '
                'shelters by half (r117d: two cells wide)");\n')
TEST_PER_NEW = ('    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f), 0.367f, 0.05f), "without the camera\'s place the 2 x 2 block '
                'shelters by a third (r117f: 0.37, r117d: half)");\n')
TEST_PER2_OLD = "    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.5f, 0.1f),\n"
TEST_PER2_NEW = "    Expect(Near(Raw(Person, 11, 0, 1.0f, 0.0f, 1.7f, 0.0f, 30.5f, 0.5f), 0.367f, 0.05f),\n"
TEST_WC_OLD = '''    Expect(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) > 0.99f &&
               Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.857f, 0.01f),
'''
TEST_WC_NEW = '''    Expect(Near(Raw(Wall, 12, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz), 0.886f, 0.01f) &&
               Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f, 0.0f, cx, cz) < 0.05f,
'''
TEST_TH_OLD = "    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f) && Near(Raw(Wall, 16, 0, 1.0f, 0.0f, 1.7f), 0.857f, 0.01f) &&\n"
TEST_TH_NEW = "    Expect(Near(Raw(Wall, 11, 0, 1.0f, 0.0f, 1.7f), 1.0f, 1e-6f) && Near(Raw(Wall, 14, 0, 1.0f, 0.0f, 1.7f), 0.657f, 0.01f) &&\n"

TEST_FN_ANCHOR = "void TestThin() {\n"
TEST_FN_BEFORE = '''// r117f: a hit counts less with its distance and only above an elevation of about 25 degrees
void TestFar() {
    Expect(FarWeight(1.0f, 3.0f) == 1.0f && FarWeight(1.0f, 9.0f) == 1.0f, "a wall one cell away counts in full");
    Expect(Near(FarWeight(4.0f, 8.0f), 0.657f, 0.002f) && Near(FarWeight(4.0f, 4.0f), 0.657f, 0.002f),
           "4 m away: 0.66 by distance, the elevation is above 27 degrees");
    Expect(Near(FarWeight(8.0f, 20.0f), 0.2f, 1e-6f) && Near(FarWeight(30.0f, 30.0f), 0.2f, 1e-6f), "from 8 m: the floor, 0.2");
    Expect(Near(FarWeight(6.0f, 3.0f), 0.0317f, 0.002f) && Near(FarWeight(3.0f, 2.0f), 0.0571f, 0.002f),
           "a low thing is cut by the elevation: a 3 m wall at 6 m, a 2 m tomb at 3 m");
    Expect(Near(FarWeight(10.0f, 5.66f), 0.1846f, 0.003f), "the elevation of 25 degrees counts 0.92 of the distance weight");
    float last = 2.0f;
    bool falling = true;
    for (float d = 1.0f; d <= 28.0f; d += 1.0f) {
        const float w = FarWeight(d, 9.0f);
        // the floor holds while the top rises 27 degrees or more (to 16 m for a 9 m wall); beyond, the elevation cuts it
        falling = falling && w <= last + 1e-6f && (d > 16.0f || w >= 0.2f - 1e-6f);
        last = w;
    }
    Expect(falling && FarWeight(17.0f, 9.0f) < 0.2f, "for a tall wall the weight never rises with the distance, keeps the floor to 16 m");
    // the log's counter word
    std::array<std::uint32_t, WS_COUNTER_WORDS> before{}, now{};
    now[WS_C_FAR_CUT] = 120;
    const auto c = CountsBetween(now.data(), before.data());
    Expect(WS_C_FAR_CUT < WS_COUNTER_WORDS && c.far_cut == 120, "the far-cut count, word by word");
}

'''
TEST_MAIN_ANCHOR = "    TestStanding();\n"
TEST_MAIN_AFTER = "    TestFar();\n"

README_OLD = "branches over it, hardly counts)"
README_NEW = ("branches over it, hardly counts; and a wall or tree counts less the further upwind it is, a fifth from 8 m, "
              "and not unless its top rises 17-27 degrees above the cell, so a low wall's lee is a few metres long and a "
              "far wall gives a faint one)")
README_B_OLD = "a wall 3 m high shelters fully within 5 m behind it and not at all beyond 17 m"
README_B_NEW = "a wall 3 m high shelters fully right behind it, by two thirds at 4 m and hardly at all from 6 m"

EDITS = {
    LAY: [("ins", LAY_TALL_ANCHOR, "", LAY_TALL_AFTER), ("ins", LAY_C_ANCHOR, "", LAY_C_AFTER)],
    COMP: [("ins", COMP_DOC_ANCHOR, COMP_DOC_BEFORE, ""), ("ins", COMP_DECL_ANCHOR, "", COMP_DECL_AFTER),
           ("ins", COMP_FN_ANCHOR, COMP_FN_BEFORE, ""), ("rep", COMP_TW_OLD, COMP_TW_NEW),
           ("rep", COMP_KEPT_OLD, COMP_KEPT_NEW), ("ins", COMP_ATOM_ANCHOR, "", COMP_ATOM_AFTER)],
    HDR: [("ins", HDR_K_ANCHOR, "", HDR_K_AFTER), ("ins", HDR_FN_ANCHOR, HDR_FN_BEFORE, ""),
          ("rep", HDR_TW_OLD, HDR_TW_NEW), ("ins", HDR_CNT_ANCHOR, "", HDR_CNT_AFTER),
          ("rep", HDR_CNTB_OLD, HDR_CNTB_NEW)],
    VKC: [("rep", VK_FL_OLD, VK_FL_NEW), ("rep", VK_DONE_OLD, VK_DONE_NEW), ("rep", VK_FMT_OLD, VK_FMT_NEW),
          ("rep", VK_ARGS_OLD, VK_ARGS_NEW), ("ins", VK_BRIEF_ANCHOR, VK_BRIEF_BEFORE, "")],
    TST: [("rep", TEST_W_OLD, TEST_W_NEW), ("rep", TEST_NX_OLD, TEST_NX_NEW), ("rep", TEST_TOMB_OLD, TEST_TOMB_NEW),
          ("rep", TEST_CV1_OLD, TEST_CV1_NEW), ("rep", TEST_CV2_OLD, TEST_CV2_NEW), ("rep", TEST_OUT_OLD, TEST_OUT_NEW),
          ("rep", TEST_TREE_OLD, TEST_TREE_NEW), ("rep", TEST_TREE_MSG_OLD, TEST_TREE_MSG_NEW),
          ("rep", TEST_PER_OLD, TEST_PER_NEW), ("rep", TEST_PER2_OLD, TEST_PER2_NEW), ("rep", TEST_WC_OLD, TEST_WC_NEW),
          ("rep", TEST_TH_OLD, TEST_TH_NEW), ("ins", TEST_FN_ANCHOR, TEST_FN_BEFORE, ""),
          ("ins", TEST_MAIN_ANCHOR, "", TEST_MAIN_AFTER)],
    RM: [("rep", README_OLD, README_NEW), ("rep", README_B_OLD, README_B_NEW)],
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


# ---- the Python copy of the model (r117d, r117e, r117f), for the numbers the tests assert -------------
NEAR, FAR, FLOOR, ELO, EHI = 1.0, 8.0, 0.2, 0.30, 0.50


def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _far(dist, top_above, on):
    if not on:
        return 1.0
    t = min(max((dist - NEAR) / (FAR - NEAR), 0.0), 1.0)
    return (1.0 - (1.0 - FLOOR) * t) * _ss(ELO, EHI, (top_above - 1.0) / dist)


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


def _ray(col, cx, cz, dx, dz, g, cam, on, tally):
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
                    fw = _far(k, c[1] - g, on)
                    if fw < 0.5:
                        tally[3] += 1
                    hit *= fw
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


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, on=True, cam=(1e9, 1e9), tally=None):
    tally = tally if tally is not None else [0, 0, 0, 0]
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g, cam, on, tally), _ray(col, cx, cz, -dx, -dz, g, cam, on, tally),
         _ray(col, cx, cz, c[0], c[1], g, cam, on, tally)]
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
        ("tomb 11", _raw(tomb, 11, 0, 1, 0), 1.0, 0.01), ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.049, 0.01),
        ("tomb 18", _raw(tomb, 18, 0, 1, 0), 0.0, 0.01),
        ("tall 11", _raw(tall, 11, 0, 1, 0), 1.0, 0.01), ("tall 16", _raw(tall, 16, 0, 1, 0), 0.367, 0.01),
        ("tall 20", _raw(tall, 20, 0, 1, 0), 0.04, 0.01), ("tall 27", _raw(tall, 27, 0, 1, 0), 0.0, 0.0),
        ("tree 13", _raw(tree, 13, 0, 1, 0), 1.0, 0.01), ("tree 21", _raw(tree, 21, 0, 1, 0), 0.061, 0.02),
        ("post 11", _raw(post, 11, 0, 1, 0), 0.0, 0.0), ("trunk 11", _raw(trunk, 11, 0, 1, 0), 0.0, 0.0),
        ("trunk, neighbours unknown 11", _raw(trunk_u, 11, 0, 1, 0), 0.216, 0.01),
        ("trunk, neighbours unknown 13", _raw(trunk_u, 13, 0, 1, 0), 0.0, 0.0),
        ("trunk with branches over it 11", _raw(overhang, 11, 0, 1, 0), 0.0, 0.0),
        ("canopy to the ground 11", _raw(standing, 11, 0, 1, 0), 1.0, 0.01),
        ("step_up 11", _raw(step, 11, 0, 1, 0), 1.0, 0.01),
        ("room 0", _raw(room, 0, 0, 1, 0), 1.0, 1e-6), ("room 9", _raw(room, 9, 0, 1, 0), 1.0, 1e-6),
        ("two cells wide 11", _raw(two, 11, 0, 1, 0), 0.5, 0.1), ("fence 1.6 m 11", _raw(stone, 11, 0, 1, 0), 0.5, 0.05),
        ("Hunter, no camera", _raw(person, 11, 0, 1, 0), 0.367, 0.05),
        ("Hunter, camera next to it", _raw(person, 11, 0, 1, 0, cam=cam), 0.0, 0.0),
        ("big tomb, camera next to it", _raw(big, 11, 0, 1, 0, cam=cam), 0.5, 0.1),
        ("Hunter, camera 19 m away", _raw(person, 11, 0, 1, 0, cam=(30.5, 0.5)), 0.367, 0.05),
        ("wall 12, camera next to it", _raw(wall, 12, 0, 1, 0, cam=cam), 0.886, 0.01),
        ("wall 16, camera next to it", _raw(wall, 16, 0, 1, 0, cam=cam), 0.0, 0.05),
    ]
    for name, g, expect, tol in want:
        got[name] = g
        if abs(g - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, g, expect, tol))
    far = {(1, 3): 1.0, (1, 9): 1.0, (4, 8): 0.657, (4, 4): 0.657, (8, 20): 0.2, (30, 30): 0.2, (6, 3): 0.0317,
           (3, 2): 0.0571, (10, 5.66): 0.1846}
    last = 2.0
    for d in range(1, 29):
        w = _far(float(d), 9.0, True)
        if w > last + 1e-6 or (d <= 16 and w < 0.2 - 1e-6):
            raise SystemExit("model check: TestFar's loop fails at %d m (%.4f)" % (d, w))
        last = w
    if not _far(17.0, 9.0, True) < 0.2:
        raise SystemExit("model check: TestFar's 17 m check")
    for (d, t), v in far.items():
        if abs(_far(d, t, True) - v) > 0.003:
            raise SystemExit("model check: far weight (%s, %s) is %.4f, the test asserts %.4f" % (d, t, _far(d, t, True), v))
    old = {"wall 16": _raw(wall, 16, 0, 1, 0, on=False), "wall 20": _raw(wall, 20, 0, 1, 0, on=False),
           "tree 21": _raw(tree, 21, 0, 1, 0, on=False)}
    if not (abs(old["wall 16"] - 0.857) < 0.01 and abs(old["wall 20"] - 0.198) < 0.01 and abs(old["tree 21"] - 0.30) < 0.05):
        raise SystemExit("model check: r117e's numbers are not as described: %s" % old)
    return got, old


# synthetic scenes: share of the seen cells above 0.5 and the mean field, no cover. B and C are r117d/e's graveyards
# (C: bare trees, many cache gaps); D is a hall like the lamp-test-spot: 8 m side and back walls, a colonnade of
# 6 m one-cell columns every 4 m on the other side, open in front, clutter, cache gaps; E the same with a solid wall.
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


def _synthetic(on, kind, seeds, winds, area):
    n, shares, means, tally = 64, [], [], [0, 0, 0, 0]
    for seed in seeds:
        col = _scene(seed, kind)
        for w in winds:
            g = [[_raw(col, i - 32, j - 32, w[0], w[1], on=on, cam=(0.5, 0.5), tally=tally) for i in range(n)]
                 for j in range(n)]
            tot = sh = 0
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
                    sm += v
            shares.append(sh / tot)
            means.append(sm / tot)
    f = lambda a: sum(a) / len(a)
    return f(shares), f(means), tally


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_DIST_NEAR 1.0f", "#define WS_DIST_FAR 8.0f", "#define WS_DIST_FLOOR 0.2f",
                 "#define WS_ELEV_LO 0.30f", "#define WS_ELEV_HI 0.50f", "#define WS_C_FAR_CUT 21u",
                 "#define WS_COUNTER_WORDS 24u"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    if (comp.count("float far_weight(") != 1 or comp.count("far_weight(dist, col.y - ground)") != 1 or
            comp.count("ws_far_cut") != 3 or comp.count("hit > blocked ? thick_weight(") != 1):
        raise SystemExit("text check: the shader's r117f code is not there as designed")
    if (header.count("FarWeight(dist, col.top - ground)") != 1 or header.count("float FarWeight(") != 1 or
            header.count("far_cut = 0") != 1):
        raise SystemExit("text check: %s" % HDR)
    if vk.count("tall %.0f%% far") != 1 or vk.count("FirstLineSure = 240") != 1 or vk.count("view_told") != 2:
        raise SystemExit("text check: vk_wind_shelter.cpp")
    if "r117f_shelter-distance" not in open(os.path.abspath(__file__), encoding="utf-8").read():
        raise SystemExit("text check: self")
    if test.count("TestFar()") != 2 or texts[RM].count("a fifth from 8 m") != 1:
        raise SystemExit("text check: test main or README")
    # the first log line is under 300 characters (the runner cuts there) with the worst numbers
    sample = ("Wind shelter (r117): %d frames before the upscaler, %d passes; the view: "
              "%.1f%% of %d depth samples sheltered (field above 0.5), %.1f%% indoors "
              "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f); "
              "hits %d: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall %.0f%% far"
              % (300, 300, 100.0, 9178029, 100.0, 1.0, 1.0, 1.0, 1.0, 123456789, 100.0, 100.0, 100.0, 100.0, 100.0))
    if len(sample) >= 300:
        raise SystemExit("text check: the first log line is %d characters" % len(sample))
    return model_checks(), len(sample)


def report(res, full):
    (got, old), n = res
    print("model: all asserted numbers pass; first log line at worst %d characters (limit 299)." % n)
    print("  a 3 m wall, lee at 2 / 4 / 6 / 10 m: r117e 1.00 / 1.00 / %.2f / %.2f -> r117f %.2f / %.2f / %.2f / %.2f"
          % (old["wall 16"], old["wall 20"], got["wall 12"], got["wall 14"], got["wall 16"], got["wall 20"]))
    print("  a 9 m wall at 6 / 10 m: %.2f / %.2f (r117e 0.86 / 0.20); a tree at 9 m: %.2f (r117e %.2f)"
          % (got["tall 16"], got["tall 20"], got["tree 21"], old["tree 21"]))
    if full:
        seeds, winds = range(2), ((1, 0), (-0.707, 0.707))
        for kind, label, area in (("B", "graveyard scene B (40% gaps)", (24, 24)), ("C", "graveyard C, bare trees", (24, 24)),
                                  ("D", "hall, colonnade side", (12, 7)), ("E", "hall, solid walls", (12, 7))):
            for on, name in ((False, "r117e"), (True, "r117f")):
                sm, mm, t = _synthetic(on, kind, seeds, winds, area)
                print("synthetic %-30s %s: %.1f%% of the seen cells above 0.5, mean %.3f; hits %d, kept %.0f%%, "
                      "far-cut %.0f%% of those" % (label, name, 100 * sm, mm, t[0], 100.0 * t[1] / max(1, t[0]),
                                                  100.0 * t[3] / max(1, t[0])))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117F_ROOT)" % ROOT)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % path)
        raw, eol, cur = load(path)
        if path == LAY and "WS_C_THIN_TALL" not in cur:
            raise SystemExit("r117e_shelter-proof is not applied (the layout has no WS_C_THIN_TALL)")
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
            tmp = full + ".r117ftmp"
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
        tmp = full + ".r117ftmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
