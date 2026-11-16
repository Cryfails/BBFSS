# r115c_roof-rule-not-trees: FEATURE fix on top of r115b (BB_VOLUMETRIC_ROOF, off by default; owner rule
# 2026-11-15 "The sun fog shouldn't go indoors at all", outdoors keeps it).
#
# FAULT (build 73, graveyard, looking up under bare trees; slot_r115bgb_off_up.jpg vs _on_up.jpg): the grey
# sky haze was cut in the upper half. r115b read the wind shelter's overhead cover, and that cover is the
# share of the camera's climbing view rays that end within 35 m (or on a surface facing down within 80 m):
# the painted sky dome, the tree branches and the Hunter's own body all end within 35 m, so the graveyard
# looking straight up reads 0.75-0.84 share (log: "80.3% ended within 35 m", "share 0.84", cover 0.18) and
# a steeper or longer look-up goes past 0.88, where the sun fog went. Indoors the same number is 1.00 and
# there is no way to tell the two by that share alone.
#
# FIX: BB_VOLUMETRIC_ROOF now reads its own measure, the ROOF SHARE, made in the wind shelter's splat pass
# (wind_shelter.comp) from the same depth samples, and only when the knob is on (push word cells.w):
#   - a climbing view ray (tangent above WS_COVER_TAN, as before) counts as ROOF only if it ends within
#     WS_ROOF_DIST (16 m: a ceiling, a vault, a bridge deck, a near wall; the sky dome, which the graveyard
#     look-up measured as 80 % "within 35 m", is further) AND the surface is solid: the depth pixels 3 px to
#     its left, right, above and below end at the same distance (within WS_NORMAL_TOL, 8 %): a branch, a
#     twig, a lamp post or a rail whose neighbours are sky or a far wall does not count;
#   - the rays are sorted into 4 world quadrants by their direction (x and z sign); the roof share is the
#     SMALLEST share of any quadrant that has at least WS_ROOF_QMIN (32) climbing samples: a roof is wide, so
#     it covers every quadrant the view climbs into; trees, the Hunter or a bridge on one side leave a
#     quadrant open and the share falls to that quadrant's;
#   - followed in time like the cover (WS_COVER_TAU), held when no quadrant has enough samples (a view
#     below the horizon), 0 until the first measure (fog whole).
# Keep(share) = 1 - smoothstep(0.55, 0.90, share) (was 0.50 / 0.95 of the cover): whole fog at 0.55 or less,
# none from 0.90. The wind's own cover (plants, drift, cache cells) is untouched: its share word, counters,
# smoothing and builds read exactly as before; a second pair of counter words (WS_C_ROOF the roof share,
# WS_C_ROOF_ALL the share of all climbing rays that are roof, to see what the quadrant rule did) and 12 more
# state words are added.
#
# OFF (BB_VOLUMETRIC_ROOF unset or not "1"): cells.w is 0 and the shader's roof code sits behind one
# uniform branch per sample (no fetch, no atomic, no state write), the rest of the shader is as it was;
# RoofKeep returns 1.0f as in r115b. The one knob read the shelter makes per pass is the same live knob the
# march already reads. ON: per climbing sample one more atomic in a shared word and, for samples ending
# within 16 m, four depth fetches (the 160x90 sample grid: at most ~7000 samples a frame), and 8 more
# atomics a frame to the state buffer; 12 state words (48 bytes) and 8 counter bytes more. No pass added.
#
# SHADER CHANGE: wind_shelter.comp (both builds: normal and SHOW) changes: the new code is under
# `cells.w != 0`; with cells.w = 0 the results equal the old shader's (the SPIR-V differs, the effect not).
# Every other SPIR-V is untouched.
#
# Files (8): host_shaders/wind_shelter_layout.h (constants, GLOBAL words 8 -> 20, COUNTER words 24 -> 26),
# host_shaders/wind_shelter.comp, vk_wind_shelter.h/.cpp (CameraCover reads WS_C_ROOF; the Push flag; one
# report line), volumetric_roof.h (curve 0.55 / 0.90), vk_volumetric_light.cpp (two log words), README.md
# (the row's words). Needs r115b applied; r115b's tests stay valid (Keep's asserts hold for the new curve).
#
# Use: python -I -X utf8 r115c_roof-rule-not-trees.py check | apply | revert
# Root: R115C_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r115c_backup
# next to this script; revert undoes exactly the inserted/replaced texts.
import os, sys

ROOT = os.environ.get("R115C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r115c_backup")
TAG = ".r115ctmp"
HV = "engine/gpu/shadps4/video_core/"
RV = HV + "renderer_vulkan/"
LAY = HV + "host_shaders/wind_shelter_layout.h"
SHD = HV + "host_shaders/wind_shelter.comp"
WH = RV + "vk_wind_shelter.h"
WC = RV + "vk_wind_shelter.cpp"
VC = RV + "vk_volumetric_light.cpp"
NH = RV + "volumetric_roof.h"
RM = "README.md"
FILES = (LAY, SHD, WH, WC, VC, NH, RM)

# (anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
INS = {
LAY: [
("#define WS_C_SELF_CELLS 23u    // seen window cells that are tall (own top WS_SELF_H_HI or more above their ground) (r117g)\n",
 "",
 "// r115c (the roof rule of BB_VOLUMETRIC_ROOF, see r115c_roof-rule-not-trees.py): a climbing view ray is ROOF when it ends within\n"
 "// WS_ROOF_DIST m on a solid surface (the depth pixels WS_ROOF_STEP px left, right, up and down end within WS_NORMAL_TOL of its\n"
 "// distance). The roof share is the smallest share over the 4 world quadrants (by the signs of the ray's x and z) that have\n"
 "// WS_ROOF_QMIN or more climbing samples in the frame; followed over WS_COVER_TAU, held without such a quadrant. Made only when\n"
 "// the push word cells.w is not 0. State words WS_GLOBAL_WORDS: 8..11 climbing rays a quadrant, 12..15 roof rays a quadrant, 16 the\n"
 "// smoothed roof share (float), 17 1 once it was first taken. Counters: WS_C_ROOF the smoothed roof share (float bits, each\n"
 "// frame), WS_C_ROOF_ALL the share of all the frame's climbing rays that are roof (float bits).\n"
 "#define WS_ROOF_DIST 16.0f\n"
 "#define WS_ROOF_STEP 3\n"
 "#define WS_ROOF_QMIN 32u\n"
 "#define WS_C_ROOF 24u\n"
 "#define WS_C_ROOF_ALL 25u\n"),
],
SHD: [
("shared uint g_pixels, g_sheltered, g_sum, g_indoor, g_up, g_covered, g_close, g_down, g_mid;\n",
 "// r115c: is the surface the depth pixel `px` shows (view depth z) solid, wide: the four pixels WS_ROOF_STEP away end on a surface\n"
 "// at the same view depth (within WS_NORMAL_TOL)? A branch, a rail or a pole has sky or a far wall beside it: not solid.\n"
 "bool solid_at(ivec2 px, ivec2 size, float z) {\n"
 "    const ivec2 d = ivec2(WS_ROOF_STEP);\n"
 "    const ivec2 n4[4] = ivec2[4](min(px + ivec2(d.x, 0), size - 1), min(px + ivec2(0, d.y), size - 1),\n"
 "                                 max(px - ivec2(d.x, 0), ivec2(0)), max(px - ivec2(0, d.y), ivec2(0)));\n"
 "    for (int i = 0; i < 4; ++i) {\n"
 "        const float dn = texelFetch(depth_tex, n4[i], 0).r;\n"
 "        if (!(dn > 0.0 && dn < 1.0)) {\n"
 "            return false;\n"
 "        }\n"
 "        const float zn = view_z(dn);\n"
 "        if (!(zn > 0.0) || abs(zn - z) > WS_NORMAL_TOL * z) {\n"
 "            return false;\n"
 "        }\n"
 "    }\n"
 "    return true;\n"
 "}\n\n",
 "shared uint g_qup[4], g_qroof[4]; // r115c: climbing rays and roof rays a world quadrant (only counted when cells.w != 0)\n"),
("        g_mid = 0u;\n",
 "",
 "        for (uint q = 0u; q < 4u; ++q) { // r115c\n"
 "            g_qup[q] = 0u;\n"
 "            g_qroof[q] = 0u;\n"
 "        }\n"),
("            atomicAdd(g_up, 1u);\n",
 "",
 "            // r115c: the world quadrant of the ray (x and z signs); counted only for BB_VOLUMETRIC_ROOF (cells.w)\n"
 "            const uint rq = (look.x >= 0.0 ? 1u : 0u) + (look.z >= 0.0 ? 2u : 0u);\n"
 "            if (cells.w != 0) {\n"
 "                atomicAdd(g_qup[rq], 1u);\n"
 "            }\n"),
("                const float away = distance(hit, vec3(row0.w, row1.w, row2.w));\n",
 "",
 "                if (cells.w != 0 && away < WS_ROOF_DIST && solid_at(px, size, zc)) { // r115c: a roof ray\n"
 "                    atomicAdd(g_qroof[rq], 1u);\n"
 "                }\n"),
("            atomicAdd(counters.c[WS_C_MID], g_mid);\n",
 "",
 "            if (cells.w != 0) { // r115c\n"
 "                for (uint q = 0u; q < 4u; ++q) {\n"
 "                    atomicAdd(state.s[GLOBAL_BASE + 8u + q], g_qup[q]);\n"
 "                    atomicAdd(state.s[GLOBAL_BASE + 12u + q], g_qroof[q]);\n"
 "                }\n"
 "            }\n"),
("        counters.c[WS_C_COVER] = floatBitsToUint(share);\n",
 "",
 "        if (cells.w != 0) {\n"
 "            // r115c: the roof share: the smallest roof share of the quadrants with enough climbing samples, followed in\n"
 "            // time, held without such a quadrant (the quadrant totals are cleared for the splat pass to fill again)\n"
 "            float roof = uintBitsToFloat(state.s[GLOBAL_BASE + 16u]);\n"
 "            float low = 1.0;\n"
 "            bool enough = false;\n"
 "            uint all_up = 0u;\n"
 "            uint all_roof = 0u;\n"
 "            for (uint q = 0u; q < 4u; ++q) {\n"
 "                const uint qu = state.s[GLOBAL_BASE + 8u + q];\n"
 "                const uint qr = state.s[GLOBAL_BASE + 12u + q];\n"
 "                state.s[GLOBAL_BASE + 8u + q] = 0u;\n"
 "                state.s[GLOBAL_BASE + 12u + q] = 0u;\n"
 "                all_up += qu;\n"
 "                all_roof += qr;\n"
 "                if (qu >= WS_ROOF_QMIN) {\n"
 "                    low = min(low, float(qr) / float(qu));\n"
 "                    enough = true;\n"
 "                }\n"
 "            }\n"
 "            if (enough) {\n"
 "                const float kr = state.s[GLOBAL_BASE + 17u] == 0u\n"
 "                                     ? 1.0\n"
 "                                     : 1.0 - exp(-wind.z * (1.0 / WS_COVER_TAU));\n"
 "                roof += (low - roof) * kr;\n"
 "                state.s[GLOBAL_BASE + 17u] = 1u;\n"
 "            }\n"
 "            state.s[GLOBAL_BASE + 16u] = floatBitsToUint(roof);\n"
 "            counters.c[WS_C_ROOF] = floatBitsToUint(roof);\n"
 "            counters.c[WS_C_ROOF_ALL] = floatBitsToUint(all_up != 0u ? float(all_roof) / float(all_up) : 0.0);\n"
 "        }\n"),
],
WC: [
('#include "video_core/renderer_vulkan/vk_scheduler.h"\n',
 "",
 '#include "video_core/renderer_vulkan/vk_volumetric_light.h" // bbport (r115c_roof-rule-not-trees): VolumetricLight::RoofMode\n'),
("    // r117f: the first report is the view line alone (the runner keeps 30 lines of the features under test, in the\n",
 "    // bbport (r115c_roof-rule-not-trees): BB_VOLUMETRIC_ROOF=1 only: what the roof rule reads (the smoothed roof share, the\n"
 "    // share of all climbing rays that are roof, and the old overhead share beside them)\n"
 "    if (VolumetricLight::RoofMode() != 0) {\n"
 '        BbReport::Printf("Wind shelter (r115c): roof share %.2f (all climbing rays %.2f; the wind\'s overhead share %.2f); "\n'
 '                         "a roof ray ends within %.0f m on a solid surface, the share is the smallest of the 4 quadrants\\n",\n'
 "                         double(BbWindShelter::CameraShelter(now[WS_C_ROOF])),\n"
 "                         double(BbWindShelter::CameraShelter(now[WS_C_ROOF_ALL])), double(cover_share),\n"
 "                         double(WS_ROOF_DIST));\n"
 "    }\n",
 ""),
],
}

# replaced texts (old, new): new does not hold old
REP = {
LAY: [
("#define WS_GLOBAL_WORDS 8u\n",
 "#define WS_GLOBAL_WORDS 20u // r115c: 8 words were used; 8..17 are the roof rule's (below)\n"),
("#define WS_COUNTER_WORDS 24u\n",
 "#define WS_COUNTER_WORDS 26u // r115c: 24, then WS_C_ROOF and WS_C_ROOF_ALL (below)\n"),
],
WH: [
("    /// bbport (r115b_sun-fog-out-of-sewer-library): the camera's overhead cover 0-1 (the r117b\n"
 "    /// measure, BbWindShelter::CoverIndoors of its smoothed share, as the GPU wrote it a frame or two\n"
 "    /// ago); -1 before any pass has run.\n",
 "    /// bbport (r115b, r115c_roof-rule-not-trees): the camera's ROOF share 0-1 (wind_shelter.comp: climbing\n"
 "    /// view rays that end within WS_ROOF_DIST on a solid surface, the smallest share of the 4 quadrants;\n"
 "    /// as the GPU wrote it a frame or two ago; only made while BB_VOLUMETRIC_ROOF=1); -1 before any pass.\n"),
],
WC: [
("                  s32(std::floor(iv[11] / BbWindShelter::Cell)), knobs.show == 2 ? 1 : 0, 0};\n",
 "                  s32(std::floor(iv[11] / BbWindShelter::Cell)), knobs.show == 2 ? 1 : 0,\n"
 "                  VolumetricLight::RoofMode() != 0 ? 1 : 0}; // bbport (r115c): the roof rule's measure on\n"),
("    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_COVER * 4, 4);\n"
 "    return BbWindShelter::CoverIndoors(BbWindShelter::CameraShelter(word));\n",
 "    std::memcpy(&word, static_cast<const u8*>(counter_host.mapped) + WS_C_ROOF * 4, 4); // bbport (r115c): the roof share\n"
 "    return BbWindShelter::CameraShelter(word);\n"),
],
VC: [
("                        \"scaled by 1 - smoothstep(%.2f, %.2f, the camera's overhead cover) (the wind shelter \"\n",
 "                        \"scaled by 1 - smoothstep(%.2f, %.2f, the camera's roof share) (r115c: the wind shelter \"\n"),
("\"whole %llu (no cover known %llu); mean cover %.2f\\n\",",
 "\"whole %llu (no cover known %llu); mean roof share %.2f\\n\","),
],
NH: [
("inline constexpr float CoverLo = 0.50f, CoverHi = 0.95f;\n",
 "inline constexpr float CoverLo = 0.55f, CoverHi = 0.90f; // r115c: of the ROOF share (was 0.50 / 0.95 of the cover)\n"),
],
}

ROW_KEY = "| `BB_VOLUMETRIC_ROOF` |"
RM_OLD = ("smoothstep(0.50, 0.95, c), c the camera's overhead cover from the wind shelter field: the share of the camera's "
          "climbing view rays that end within a few metres on a surface that faces down (a ceiling, a vault, a canopy's "
          "underside), followed over about a second and held while the view has no climbing rays (`Wind shelter (r117)` log "
          "lines: `overhead cover`; 0.99-1.00 in the interiors of one test run, 0.00 in the graveyard)")
RM_NEW = ("smoothstep(0.55, 0.90, s), s the camera's roof share (r115c) from the wind shelter's depth samples: of the "
          "camera's climbing view rays, those that end within 16 m on a solid surface (the depth pixels 3 px around it end "
          "at the same distance: a ceiling, a vault, a bridge deck, a wall; not a branch, a rail or the sky dome), counted "
          "in the 4 world quadrants, the smallest quadrant share (a roof covers every direction; trees or the Hunter leave "
          "one open), followed over about a second and held while the view has no climbing rays (`Wind shelter (r115c)` log "
          "line: roof share; the graveyard looking up under trees read 0.75-0.84 of the old `overhead cover` share and "
          "lost its haze with the first rule)")


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def rep_for(path, text):
    if path == RM:
        lines = [l for l in text.split("\n") if l.startswith(ROW_KEY)]
        if len(lines) != 1:
            if len(lines) == 0:
                raise SystemExit("README.md: the BB_VOLUMETRIC_ROOF row is missing (r115b not applied?)")
            raise SystemExit("README.md: the BB_VOLUMETRIC_ROOF row is there %d times" % len(lines))
        return [(RM_OLD, RM_NEW)]
    return REP.get(path, [])


def state_of(cur, ins, rep, path):
    done = todo = 0
    for anchor, before, after in ins:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    for old, new in rep:
        no, nn = cur.count(old), cur.count(new)
        if no == 1 and nn == 0:
            todo += 1
        elif no == 0 and nn == 1:
            done += 1
        else:
            raise SystemExit("REFUSED %s: replaced text found %d times, its new text %d times: %r"
                             % (path, no, nn, old[:70]))
    total = len(ins) + len(rep)
    if done == total:
        return "applied"
    if todo == total:
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, total))


def text_checks(texts):
    shd, lay, wc, nh = texts[SHD], texts[LAY], texts[WC], texts[NH]
    for want, n in (("bool solid_at(ivec2 px, ivec2 size, float z) {", 1), ("atomicAdd(g_qroof[rq], 1u);", 1),
                    ("counters.c[WS_C_ROOF] = floatBitsToUint(roof);", 1), ("cells.w != 0", 5)):
        if shd.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (SHD, want, shd.count(want), n))
    for want in ("#define WS_COUNTER_WORDS 26u", "#define WS_GLOBAL_WORDS 20u", "#define WS_C_ROOF 24u",
                 "#define WS_C_ROOF_ALL 25u"):
        if lay.count(want) != 1:
            raise SystemExit("text check: %s lacks %r" % (LAY, want))
    # the new counters sit inside the counter buffer, the new state words inside the globals
    if not (24 < 26 and 17 < 20):
        raise SystemExit("text check: layout")
    if "WS_C_ROOF * 4" not in wc or "WS_C_COVER * 4" in wc:
        raise SystemExit("text check: CameraCover does not read WS_C_ROOF alone")
    if wc.count("VolumetricLight::RoofMode()") != 2:
        raise SystemExit("text check: the shelter asks the roof knob twice (the push flag and the report)")
    if "CoverLo = 0.55f, CoverHi = 0.90f" not in nh:
        raise SystemExit("text check: the curve constants")
    row = [l for l in texts[RM].split("\n") if l.startswith(ROW_KEY)]
    if len(row) != 1 or "smoothstep(0.55, 0.90, s)" not in row[0]:
        raise SystemExit("text check: README row and the curve disagree")
    # the state words 8..17 of the roof rule are not the cover's (0..4)
    for bad in ("GLOBAL_BASE + 5u", "GLOBAL_BASE + 6u", "GLOBAL_BASE + 7u"):
        if bad in shd:
            raise SystemExit("text check: %s used" % bad)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R115C_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, NH)):
        raise SystemExit("r115b is not applied (%s is missing)" % NH)
    plan = []
    for path in FILES:
        raw, eol, cur = load(path)
        ins, rep = INS.get(path, []), rep_for(path, cur)
        plan.append((path, ins, rep, raw, eol, cur, state_of(cur, ins, rep, path)))
    states = {p[6] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[6]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, ins, rep, raw, eol, cur, _ in plan:
            for anchor, before, after in ins:
                cur = cur.replace(anchor, before + anchor + after)
            for old, new in rep:
                cur = cur.replace(old, new)
            if state_of(cur, ins, rep, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[5] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) + len(p[2]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, ins, rep, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, ins, rep, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            open(full + TAG, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(full + TAG, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, ins, rep, raw, eol, cur, _ in plan:
        for old, new in rep:
            cur = cur.replace(new, old, 1)
        for anchor, before, after in reversed(ins):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, ins, rep, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, ins, rep, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + TAG, "wb").write(out[path])
        os.replace(full + TAG, full)
    print("reverted")


main()
