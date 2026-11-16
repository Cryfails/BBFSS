# r117e_shelter-proof: FEATURE fix on top of r117_wind-shelter, r117b, r117c and r117d_shelter-thin (all applied and
# built; r117d in b40). Still off with r117's knob BB_WIND_SHELTER (no new knob): every edit is in r117's own files,
# which only exist or run with the knob (see "Off" below).
#
# WHAT b40 SHOWED (r117d-grave1, -lamp1, -none): graveyard 35.3% sheltered (target 15-35), mean 0.343 (target under
# 0.3), camera 0.29, 9.1% above 0.95; lamp-test-spot 51.3% / 0.501 (b35: 51.5% / 0.504, unchanged). Two defects of the
# PROOF: r117d's own line ('N obstacle cells ...') is in no log, and the library job's only line is the early
# '0 depth samples' one.
#
# CAUSE OF THE MISSING LINES (read from the runner, Test-BBFSSSlot.ps1, not guessed): the runner keeps the FIRST AND
# LAST line of each kind (digits folded), puts the lines of the features under test first and cuts that list at
# 30 (Select-Object -First 30), THEN the other kinds (up to 40). Report() prints four wind lines in a row; the
# graveyard run ended 269 frames in, so it had only the 120-pass report, and the runner's 30-line cap (about 20 other
# features' lines come first in the log: halation, heat haze, particles...) kept only the first of the four. The lamp
# run kept four of five (the r117c line last but one, r117d's last: gone). The 600-frame line needs 600 frames after
# the first report: the graveyard run never got there, the library's 120-pass line fell in the loading frames.
#
# FIX 1 (the proof): (a) the first line of Report() (the one every run keeps: it is the 'view' line) now ends with the
# r117d numbers: '; hits N: L% low T% thin K% kept G% tall' (K: hits whose weight stays at 0.5 or more; G: of those
# the ones with a top 4 m or more above the ground: tree-like or tall wall), so one kept line carries every number
# a verdict needs; (b) LineFrames 600 -> 300: after the first line (120 passes) the next comes 300 frames later, so a
# 40 s test run (the jobs now wait 30 s) has two lines, both kept (first and last of the kind); the jobs' labels
# say which numbers to copy. The r117, r117c and r117d lines after the first stay (as extra lines when the cap allows).
#
# FIX 2 (a little less outdoor shelter): two changes, none touching the numbers of walls, tombs, halls and trees that
# the tests assert:
#  1. WS_THIN_UNSEEN 0.5 -> 0.15. In r117d a ray met a thing whose four neighbours across the ray the cache did not
#     know and counted it in full (w = 1 + 4 x 0.5 = 3: smoothstep 1). The cache has many gaps in a graveyard (what
#     the camera never saw: behind trunks, under grass), so single trunks, posts and gravestones next to gaps still
#     counted as walls. Now four unknown neighbours give w = 1.6, a weight of 0.22; a wall whose cache has one
#     known tall neighbour (w >= 2.15 with a second at 0.15) is above 0.5 and with two known ones in full.
#  2. A neighbour counts as wide only when it STANDS: its lowest height is less than WS_LIFT_LO (1.2 m) above the
#     ground. A bare tree's branches over a trunk are known cells with tall tops but they start 3 m or more up: they
#     do not make the trunk a wall (the ray's blocking already says a lifted cell blocks less: ray() uses the same
#     lift). A canopy whose cells reach the ground (the ground under it seen) is unchanged: that is the limit the
#     r117d context names for the next step (a per-cell share of solid samples: not done here, see below).
# NOT done (reasons): cut-out plant cards cannot be told from solid things in the depth buffer (no material is
# known there); they stand under about 1 m, which r117d's height weight (nothing under 1.2 m, half at 1.6 m, from
# 2.0 m in full) already drops, and a tall weed of 1.5-2 m counts as a thin one-cell thing (width weight). Near the
# camera a low thing (under 2.0 m) is dropped by r117c's keep rule inside 4 m. The height thresholds are not raised:
# that would change the 2 m tombs the tests and the owner's rule ('walls and tombs give a soft lee') keep.
# The graveyard's remaining sheltered share may still be the porous canopies (a tree's cells from the ground to
# 8 m count as a 3 m wall): this patch ADDS TWO COUNTERS to tell: 'tall' (G) in the line says how much of what is
# still counted is tall (top 4 m or more above the ground). If G is high and the mean stays above 0.3 the next step is the
# solid-share word (WS_CELL_WORDS 6 -> 7, a per-cell count of samples above 1 m over the cell's bottom, merged with a
# slow follow; a canopy has 20-40%, a wall 60% or more: to be calibrated from a log first).
#
# Off: nothing here runs without r117's knob (the shader is only built into the pass r117 makes, BbWindShelter::
# KnobOnce().on; the new constants and counters are in r117's own header, shader and layout; the log text is in
# r117's Report). BB_WIND off and BB_WIND_SHELTER off are unchanged.
# Cost on: raw pass: two more comparisons and two private counters per obstacle cell met (hits only), one more
# comparison in the width test's neighbour read: far below 0.01 ms. Memory: the counter buffer 80 -> 96 bytes.
# CPU: the log line a little longer, one line every 300 frames instead of 600 (a minute and a half apart at 60 fps).
#
# Files (all r117's): host_shaders/wind_shelter_layout.h, wind_shelter.comp, shim/bbport_wind_shelter.h,
# renderer_vulkan/vk_wind_shelter.cpp, tests/test_wind_shelter.cpp, README.md (the row).
# Use: python -I -X utf8 r117e_shelter-proof.py check | apply | revert
# Root: R117E_ROOT, else <tree>. Line ends kept. Needs r117, r117b, r117c and r117d applied (refuses else).
import math, os, sys

ROOT = os.environ.get("R117E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r117e_backup")
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
LAY = HS + "wind_shelter_layout.h"
COMP = HS + "wind_shelter.comp"
HDR = "engine/gpu/shim/bbport_wind_shelter.h"
VKC = RV + "vk_wind_shelter.cpp"
TST = "engine/tests/test_wind_shelter.cpp"
RM = "README.md"

# ---------------------------------------------------------------------------------------------
LAY_UN_OLD = "#define WS_THIN_UNSEEN 0.5f\n"
LAY_UN_NEW = '''#define WS_THIN_UNSEEN 0.15f
// r117e: a hit whose top is at least WS_TALL_H above the ground is "tall" in the log (a tree or a tall wall); a
// neighbour across the ray counts as wide only if it stands (its lowest height under WS_LIFT_LO above the ground).
#define WS_TALL_H 4.0f
'''
LAY_CW_OLD = "#define WS_COUNTER_WORDS 20u\n"
LAY_CW_NEW = "#define WS_COUNTER_WORDS 24u\n"
LAY_C_ANCHOR = "#define WS_C_THIN_NARROW 18u   // of the rest with a width weight below 0.5\n"
LAY_C_AFTER = '''#define WS_C_THIN_KEPT 19u     // of the hits, those whose weight stays at 0.5 or more (r117e)
#define WS_C_THIN_TALL 20u     // of the kept ones, those with a top WS_TALL_H or more above the ground
'''

COMP_DOC_ANCHOR = "//  SHOW   (the SHOW build only) the field painted over the scene colour (cells.z 0), or alone\n"
COMP_DOC_BEFORE = '''//  r117e  a neighbour across the ray makes a thing wide only if it stands (its bottom under WS_LIFT_LO above the
//         ground: branches over a trunk do not); a cell the cache knows nothing of counts WS_THIN_UNSEEN (0.15).
'''
COMP_STAND_OLD = "                if (nb.z > 0.0 && nb.y - ground >= WS_THIN_NB) {\n"
COMP_STAND_NEW = "                if (nb.z > 0.0 && nb.y - ground >= WS_THIN_NB && nb.x - ground < WS_LIFT_LO) { // r117e: it stands\n"
COMP_DECL_ANCHOR = "uint ws_thin_narrow = 0u;\n"
COMP_DECL_AFTER = '''uint ws_thin_kept = 0u; // r117e: hits whose weight stays at 0.5 or more
uint ws_thin_tall = 0u; // of them, with a top WS_TALL_H or more above the ground
'''
COMP_KEPT_ANCHOR = "                    blocked = max(blocked, hit * t_w);\n"
COMP_KEPT_BEFORE = '''                    if (hit * t_w >= 0.5) { // r117e: a hit that still counts (for the log)
                        ++ws_thin_kept;
                        if (col.y - ground >= WS_TALL_H) {
                            ++ws_thin_tall;
                        }
                    }
'''
COMP_ATOM_ANCHOR = "        atomicAdd(counters.c[WS_C_THIN_NARROW], ws_thin_narrow);\n"
COMP_ATOM_AFTER = '''        atomicAdd(counters.c[WS_C_THIN_KEPT], ws_thin_kept);
        atomicAdd(counters.c[WS_C_THIN_TALL], ws_thin_tall);
'''

HDR_STAND_OLD = "                if (nb.seen && nb.top - ground >= ThinNb) {\n"
HDR_STAND_NEW = "                if (nb.seen && nb.top - ground >= ThinNb && nb.bot - ground < LiftLo) { // r117e: it stands\n"
HDR_CNT_ANCHOR = "    std::uint64_t thin_seen = 0, thin_low = 0, thin_narrow = 0; ///< r117d\n"
HDR_CNT_AFTER = "    std::uint64_t thin_kept = 0, thin_tall = 0; ///< r117e\n"
HDR_CNTB_OLD = "            d(WS_C_THIN_SEEN),      d(WS_C_THIN_LOW),         d(WS_C_THIN_NARROW)};\n"
HDR_CNTB_NEW = ("            d(WS_C_THIN_SEEN),      d(WS_C_THIN_LOW),         d(WS_C_THIN_NARROW),\n"
                "            d(WS_C_THIN_KEPT),      d(WS_C_THIN_TALL)};\n")

VK_LF_OLD = "constexpr u32 LineFrames = 600;\n"
VK_LF_NEW = ("constexpr u32 LineFrames = 300; ///< r117e: was 600 (a 40 s test run never reached the second line)\n")
VK_FMT_OLD = '                     "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f)\\n",\n'
VK_FMT_NEW = ('                     "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f); "\n'
              '                     "hits %llu: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall\\n",\n')
VK_ARGS_OLD = "                     double(BbWindShelter::CoverIndoors(cover_share)), double(cover_share));\n"
VK_ARGS_NEW = '''                     double(BbWindShelter::CoverIndoors(cover_share)), double(cover_share),
                     ull(c.thin_seen), // r117d/r117e numbers on the line every run keeps
                     100.0 * double(c.thin_low) / std::max(1.0, double(c.thin_seen)),
                     100.0 * double(c.thin_narrow) / std::max(1.0, double(c.thin_seen - c.thin_low)),
                     100.0 * double(c.thin_kept) / std::max(1.0, double(c.thin_seen)),
                     100.0 * double(c.thin_tall) / std::max(1.0, double(c.thin_kept)));
'''

TEST_TU_OLD = ('    Expect(Raw(TrunkUnknown, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "a trunk whose neighbours are not known: '
               'as a wall");\n')
TEST_TU_NEW = ('    Expect(Near(Raw(TrunkUnknown, 11, 0, 1.0f, 0.0f, 1.7f), 0.216f, 0.01f),\n'
               '           "a trunk whose neighbours are not known: mostly thin (r117e: 0.22, r117d: as a wall)");\n')
TEST_TW_OLD = "               Near(ThinWeight(TrunkUnknown, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f),\n"
TEST_TW_NEW = "               Near(ThinWeight(TrunkUnknown, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 0.216f, 0.002f),\n"
TEST_FN_ANCHOR = "void TestThin() {\n"
TEST_FN_BEFORE = '''// r117e: branches over a trunk do not make it wide; a neighbour that stands does
Column Overhang(int x, int z) { // a trunk 8 m with branch cells 4-8 m either side across the wind
    return x == 10 && z == 0 ? ColumnOf(0.0f, 8.0f)
           : x == 10 && z >= -2 && z <= 2 ? ColumnOf(4.0f, 8.0f)
                                          : ColumnOf(0.0f, 0.0f);
}
Column Standing(int x, int z) { // the same cells reaching the ground: a canopy, 5 wide
    return x == 10 && z >= -2 && z <= 2 ? ColumnOf(0.0f, 8.0f) : ColumnOf(0.0f, 0.0f);
}

void TestStanding() {
    Expect(Raw(Overhang, 11, 0, 1.0f, 0.0f, 1.7f) == 0.0f && Raw(Overhang, 13, 0, 1.0f, 0.0f, 1.7f) == 0.0f,
           "a trunk with branches over it: thin (r117d: as a wall)");
    Expect(ThinWeight(Overhang, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f) == 0.0f &&
               Near(ThinWeight(Standing, 10.5f, 0.5f, 1.0f, 0.0f, 0.0f), 1.0f, 1e-6f),
           "the width weight: lifted neighbours 0, neighbours that stand 1");
    Expect(Raw(Standing, 11, 0, 1.0f, 0.0f, 1.7f) > 0.99f, "a canopy that reaches the ground: a wall, as before");
}

'''
TEST_MAIN_ANCHOR = "    TestThin();\n"
TEST_MAIN_AFTER = "    TestStanding();\n"
TEST_CNT_ANCHOR = '           "the obstacle counts, word by word");\n'
TEST_CNT_AFTER = '''    // r117e: the kept and tall hits
    before = {};
    now = {};
    now[WS_C_THIN_SEEN] = 900;
    now[WS_C_THIN_KEPT] = 400;
    now[WS_C_THIN_TALL] = 300;
    c = CountsBetween(now.data(), before.data());
    Expect(c.thin_seen == 900 && c.thin_kept == 400 && c.thin_tall == 300, "the kept and tall counts, word by word");
'''

README_OLD = "one cell wide across the wind hardly counts)"
README_NEW = "one cell wide across the wind, or one wide only because of branches over it, hardly counts)"

EDITS = {
    LAY: [("rep", LAY_UN_OLD, LAY_UN_NEW), ("rep", LAY_CW_OLD, LAY_CW_NEW), ("ins", LAY_C_ANCHOR, "", LAY_C_AFTER)],
    COMP: [("ins", COMP_DOC_ANCHOR, COMP_DOC_BEFORE, ""), ("rep", COMP_STAND_OLD, COMP_STAND_NEW),
           ("ins", COMP_DECL_ANCHOR, "", COMP_DECL_AFTER), ("ins", COMP_KEPT_ANCHOR, COMP_KEPT_BEFORE, ""),
           ("ins", COMP_ATOM_ANCHOR, "", COMP_ATOM_AFTER)],
    HDR: [("rep", HDR_STAND_OLD, HDR_STAND_NEW), ("ins", HDR_CNT_ANCHOR, "", HDR_CNT_AFTER),
          ("rep", HDR_CNTB_OLD, HDR_CNTB_NEW)],
    VKC: [("rep", VK_LF_OLD, VK_LF_NEW), ("rep", VK_FMT_OLD, VK_FMT_NEW), ("rep", VK_ARGS_OLD, VK_ARGS_NEW)],
    TST: [("rep", TEST_TU_OLD, TEST_TU_NEW), ("rep", TEST_TW_OLD, TEST_TW_NEW),
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


# ---- the Python copy of the model (r117d and r117e), for the numbers the tests assert ---------------
def _ss(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _q(y):
    return min(max(math.floor((y + 1024.0) * 32.0 + 0.5), 0), 65535) / 32.0 - 1024.0


def _col(bot, top):
    return (_q(bot), _q(top))


def _keep(top_above, dist_cam):
    return max(_ss(2.0, 2.6, top_above), _ss(4.0, 7.0, dist_cam))


def _thick(col, x, z, dx, dz, g, unseen, stand):
    sx, sz = -dz, dx
    mx, mz = math.floor(x) + 0.5, math.floor(z) + 0.5
    w = 1.0
    for j in (-2, -1, 1, 2):
        px, pz, v = mx + sx * j, mz + sz * j, 0.0
        for a in (-1, 0, 1):
            c = col(math.floor(px + dx * a), math.floor(pz + dz * a))
            if c and c[1] - g >= 1.5 and (not stand or c[0] - g < 1.2):
                v = 1.0
            elif a == 0 and not c:
                v = max(v, unseen)
        w += v
    return _ss(1.0, 3.0, w)


def _ray(col, cx, cz, dx, dz, g, cam, new, tally):
    unseen, stand = (0.15, True) if new else (0.5, False)
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
                    hit *= _thick(col, fx + dx * k, fz + dz * k, dx, dz, g, unseen, stand)
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


def _raw(col, cx, cz, dx, dz, cam_y=1.7, cover=0.0, new=True, cam=(1e9, 1e9), tally=None):
    tally = tally if tally is not None else [0, 0, 0]
    own = col(cx, cz)
    g = cam_y - 1.7
    if own:
        g = own[0]
    else:
        lows = [col(cx + i, cz + j)[0] for j in (-1, 0, 1) for i in (-1, 0, 1) if col(cx + i, cz + j)]
        if lows:
            g = min(lows)
    a, c = _rot(-dx, -dz, -14.0), _rot(-dx, -dz, 14.0)
    r = [_ray(col, cx, cz, a[0], a[1], g, cam, new, tally), _ray(col, cx, cz, -dx, -dz, g, cam, new, tally),
         _ray(col, cx, cz, c[0], c[1], g, cam, new, tally)]
    lee = max(min(r[0], r[1]), min(max(r[0], r[1]), r[2]))
    return 1.0 - (1.0 - lee) * (1.0 - cover)


def model_checks():
    flat = lambda x, z: _col(0, 0)
    wall = lambda x, z: _col(0, 3) if x == 10 and -20 <= z <= 20 else _col(0, 0)
    post = lambda x, z: _col(0, 3) if x == 10 and z == 0 else _col(0, 0)
    tomb = lambda x, z: _col(0, 2) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    tree = lambda x, z: _col(0, 8) if 8 <= x <= 12 and -2 <= z <= 2 else _col(0, 0)
    person = lambda x, z: _col(0, 1.9) if 8 <= x <= 9 and -1 <= z <= 0 else _col(0, 0)
    trunk = lambda x, z: _col(0, 8) if x == 10 and z == 0 else _col(0, 0)
    trunk_u = lambda x, z: _col(0, 8) if x == 10 and z == 0 else (None if x == 10 else _col(0, 0))
    overhang = lambda x, z: (_col(0, 8) if x == 10 and z == 0 else
                             _col(4, 8) if x == 10 and -2 <= z <= 2 else _col(0, 0))
    standing = lambda x, z: _col(0, 8) if x == 10 and -2 <= z <= 2 else _col(0, 0)
    pair = lambda x, z: _col(0, 3) if x == 10 and 0 <= z <= 1 else _col(0, 0)
    got = {}
    want = [
        ("flat", _raw(flat, 5, 0, 1, 0), 0.0, 0.0), ("wall 11", _raw(wall, 11, 0, 1, 0), 1.0, 1e-6),
        ("wall 16", _raw(wall, 16, 0, 1, 0), 0.857, 0.01), ("wall 20", _raw(wall, 20, 0, 1, 0), 0.198, 0.01),
        ("tomb 11", _raw(tomb, 11, 0, 1, 0), 1.0, 0.01), ("tomb 13", _raw(tomb, 13, 0, 1, 0), 0.857, 0.01),
        ("tree 13", _raw(tree, 13, 0, 1, 0), 1.0, 0.01), ("tree 21", _raw(tree, 21, 0, 1, 0), 0.30, 0.05),
        ("post 11", _raw(post, 11, 0, 1, 0), 0.0, 0.0), ("trunk 11", _raw(trunk, 11, 0, 1, 0), 0.0, 0.0),
        ("trunk, neighbours unknown 11 (r117d: 1)", _raw(trunk_u, 11, 0, 1, 0), 0.216, 0.01),
        ("trunk, neighbours unknown 13 (the side rays meet unknown cells: median 0)", _raw(trunk_u, 13, 0, 1, 0), 0.0, 0.0),
        ("trunk with branches over it 11 (r117d: 1)", _raw(overhang, 11, 0, 1, 0), 0.0, 0.0),
        ("trunk with branches over it 13", _raw(overhang, 13, 0, 1, 0), 0.0, 0.0),
        ("canopy to the ground 11", _raw(standing, 11, 0, 1, 0), 1.0, 0.01),
        ("two cells wide 11", _raw(pair, 11, 0, 1, 0), 0.5, 0.1),
        ("Hunter, no camera", _raw(person, 11, 0, 1, 0), 0.5, 0.1),
        ("wall, diagonal wind 13 (TestModel)", _raw(wall, 13, 0, math.sqrt(0.5), math.sqrt(0.5)), 1.0, 0.01),
        ("wall, wind 40 deg 12", _raw(wall, 12, 0, math.cos(0.6981), math.sin(0.6981)), 1.0, 0.01),
    ]
    for name, g, expect, tol in want:
        got[name] = g
        if abs(g - expect) > tol:
            raise SystemExit("model check: %s is %.4f, the test asserts %.4f +- %g" % (name, g, expect, tol))
    # the weight the width test gives a lone trunk with 4 unknown neighbours: 1 + 4 x 0.15
    if abs(_ss(1.0, 3.0, 1.6) - 0.216) > 1e-6:
        raise SystemExit("model check: 0.216")
    old = {"trunk, neighbours unknown": _raw(trunk_u, 11, 0, 1, 0, new=False),
           "trunk with branches over it": _raw(overhang, 11, 0, 1, 0, new=False)}
    if not (old["trunk, neighbours unknown"] > 0.99 and old["trunk with branches over it"] > 0.99):
        raise SystemExit("model check: r117d's numbers are not as described: %s" % old)
    return got, old


# synthetic graveyards: share of the seen cells above 0.5 and the mean field, no cover. Scene 'C' is r117d's
# scene B with the cache gaps of a real graveyard made denser (40% of the open cells unknown) and bare trees:
# canopy cells either side of a trunk start 3 m up (branches), only a core of 3x3 reaches the ground.
def _scene(seed, kind):
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


def _synthetic(new, kind, seeds, winds):
    n, shares, means, tally = 64, [], [], [0, 0, 0]
    for seed in seeds:
        col = _scene(seed, kind)
        for w in winds:
            g = [[_raw(col, i - 32, j - 32, w[0], w[1], new=new, cam=(0.5, 0.5), tally=tally) for i in range(n)]
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
    f = lambda a: sum(a) / len(a)
    return f(shares), f(means), tally


def text_checks(texts):
    layout, header, comp, vk, test = texts[LAY], texts[HDR], texts[COMP], texts[VKC], texts[TST]
    for want in ("#define WS_THIN_UNSEEN 0.15f", "#define WS_TALL_H 4.0f", "#define WS_COUNTER_WORDS 24u",
                 "#define WS_C_THIN_KEPT 19u", "#define WS_C_THIN_TALL 20u"):
        if layout.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    if (comp.count("nb.x - ground < WS_LIFT_LO") != 1 or comp.count("ws_thin_kept") != 3 or
            comp.count("ws_thin_tall") != 3):
        raise SystemExit("text check: the shader's r117e code is not there as designed")
    if header.count("nb.bot - ground < LiftLo") != 1 or header.count("thin_kept = 0, thin_tall = 0") != 1:
        raise SystemExit("text check: %s" % HDR)
    if vk.count("hits %llu") != 1 or vk.count("LineFrames = 300") != 1:
        raise SystemExit("text check: vk_wind_shelter.cpp")
    if "r117e_shelter-proof" not in open(os.path.abspath(__file__), encoding="utf-8").read():
        raise SystemExit("text check: self")
    # the first line is under 300 characters (the runner cuts there) with the worst numbers
    sample = ("Wind shelter (r117): %d frames before the upscaler, %d passes; the view: "
              "%.1f%% of %d depth samples sheltered (field above 0.5), %.1f%% indoors "
              "(above 0.95), mean %.3f; at the camera %.2f; overhead cover %.2f (share %.2f); "
              "hits %d: %.0f%% low %.0f%% thin %.0f%% kept %.0f%% tall"
              % (300, 300, 100.0, 9178029, 100.0, 1.0, 1.0, 1.0, 1.0, 123456789, 100.0, 100.0, 100.0, 100.0))
    if len(sample) >= 300:
        raise SystemExit("text check: the first log line is %d characters" % len(sample))
    if test.count("TestStanding()") != 2 or texts[RM].count("branches over it, hardly counts)") != 1:
        raise SystemExit("text check: test main or README")
    return model_checks(), len(sample)


def report(res, full):
    (got, old), n = res
    print("model: all asserted numbers pass; first log line at worst %d characters (limit 299)." % n)
    print("  a lone trunk with unknown neighbours: r117d %.2f -> r117e %.2f; a trunk with branches over it: %.2f -> %.2f"
          % (old["trunk, neighbours unknown"], got["trunk, neighbours unknown 11 (r117d: 1)"],
             old["trunk with branches over it"], got["trunk with branches over it 11 (r117d: 1)"]))
    if full:
        seeds, winds = range(4), ((1, 0), (-0.707, 0.707))
        for kind, label in (("B", "r117d's scene B, 40% gaps"), ("C", "bare trees (branches 3 m up), 60% gaps")):
            for new, name in ((False, "r117d"), (True, "r117e")):
                sm, mm, t = _synthetic(new, kind, seeds, winds)
                print("synthetic %-38s %s: %.1f%% of the seen cells above 0.5, mean %.3f; hits %d, kept %.0f%%, "
                      "tall %.0f%% of kept" % (label, name, 100 * sm, mm, t[0], 100.0 * t[1] / max(1, t[0]),
                                               100.0 * t[2] / max(1, t[1])))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R117E_ROOT)" % ROOT)
    plan = []
    for path in (LAY, COMP, HDR, VKC, TST, RM):
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit("r117_wind-shelter is not applied (%s is missing)" % path)
        raw, eol, cur = load(path)
        if path == LAY and "WS_C_THIN_NARROW" not in cur:
            raise SystemExit("r117d_shelter-thin is not applied (the layout has no WS_C_THIN_NARROW)")
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
            tmp = full + ".r117etmp"
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
        tmp = full + ".r117etmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
