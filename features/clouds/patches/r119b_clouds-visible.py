# r119b_clouds-visible: FEATURE fix on top of r119_volumetric-clouds.fixed.py (BB_VOLUMETRIC_CLOUDS=1 only;
# still off by default, still costs nothing when off: nothing here runs without the CloudLayer object, which
# Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# What was wrong (build 30, jobs r119-gbs, r119-lt, r119-di): the layer ran every frame and drew nothing: "sky px
# share 0.277" then "0.000", covered share 0.000, mean opacity 0.000, march steps 0.0; the show view painted no
# green anywhere; lamp-test-spot said sky 0.000 with the sky plainly visible through the arches.
# Cause, read from the numbers of the tree and of earlier builds (no game was run for this patch):
#  - r119 took a pixel for sky only when its depth was exactly 1 (depth >= 1.0), BB_VOLUMETRIC_CLOUDS_SKYZ was 0.
#    But in the level the game's sky dome is a real mesh that writes a depth just SHORT of 1: the dome's vertices
#    at lamp-test-spot lie 1888 to 1961 m from the camera (r104 probe, slot_b7_result.txt: vertex 0
#    (-1692.6, 0, -836.6), vertex 260 (-1209.3, 379.4, -1497.6)), and the projection's far plane is only about
#    2945 m (log: "projection ... z 1.000017 -0.050068": depth = 1.000017 - 0.050068 / view z, so a dome at 1500 to
#    1900 m has depth 0.999984 to 0.999991, never 1.0). Every other effect that reads the same depth says the same:
#    the ray traced sun counts "skipped: sky 766" then 0 in the level (359394 only on the menu's clear), the
#    interior meter reports "sky 0.0%" at the graveyard where it expects sky near 100 percent, wind_shelter.comp
#    says "the sky dome has a depth below 1". Depth 1 is only the clear of the menu and loading frames: that is the
#    sky share 0.277 / 0.582 of the first log line. So no pixel of the level was sky, the march never ran
#    (counter HIT 0 = "march steps 0.0"), the composite returned at its first test and the show view never painted.
#  - The other suspects of the task, checked and cleared on paper: the ray's up axis matches glass_glint.comp's
#    RayDir and wind_shelter.comp's ray_dir (z sign + from proj.w < 0, row transform of the camera pass, y up; the
#    sun's elevation uses the same y); the slab's world height is no problem (camera y -39 m and -107 m, slab 700
#    to 1000 m: a ray with dy > 0.062 reaches it within MAX_T, lamp-test-spot's arches look 15 to 45 degrees up:
#    dy 0.25 to 0.7, t0 1100 to 3200 m); the cover edges (clear 41%, full 25% of the plane, r105b sample) are fine.
# Fix:
#  1. BB_VOLUMETRIC_CLOUDS_SKYZ now defaults to 500 m (DefaultSkyZ): a pixel counts as sky when its depth is 1 OR
#     its view z (as heat_haze.comp / interior_meter.comp compute it) is beyond 500 m. The dome (1500 to 1900 m)
#     and anything beyond half a kilometre qualify; the nearest geometry the game draws with a view ray rising more
#     than 3.5 degrees is nearer than that. 0 gives the old rule (depth 1 only). Far towers beyond 500 m under a
#     rising ray count as sky too and take the thin cloud (a known limit, said in the README row).
#  2. A depth probe so the next run reads the real numbers whatever the dome's radius is at a place whose sky is
#     drawn by another pair (graveyard, dark alley): the first pixel of each march block is counted into 7 bands
#     (depth 1, view z over 1500, 1000, 500, 250, 100 m, the rest) in the counter words 6 to 12 (CL_WORDS 8 -> 16,
#     64 bytes), one texel fetch and one shared atomic a march pixel, logged every 600 frames as
#     "Volumetric clouds (r119b): picture depth shares ...". If the graveyard's sky is nearer than 500 m the line
#     shows it and BB_VOLUMETRIC_CLOUDS_SKYZ=<less> fixes it at once, without a build.
#  3. The cloud's look was a guess that made the cloud nearly the colour of the sky it lay on (cloud = the sky's
#     own mean tint x 0.32 to 0.8 ambient plus the lit part): ambient 0.80 -> 0.65 (darker undersides) and light gain
#     1.0 -> 1.4 (brighter rims toward the moon or sun). A guess too; the constants are in cloud_layer_params.h.
#
# TOOL or FEATURE: FEATURE (same lane as r119).
# Edits r119's own files: cloud_layer_params.h, cloud_layer.comp, cloud_layer_layout.h, vk_cloud_layer.cpp,
# vk_cloud_layer.h (one comment line), tests/test_cloud_layer.cpp, README.md (the block and the SKYZ row).
# Apply after r119 (it needs its text); revert BEFORE r119 (r119's own check, which compares its new files
# byte for byte, fails while r119b is applied: run r119b revert first).
#
# Use: python -I -X utf8 r119b_clouds-visible.py check | apply | revert
# Root: R119B_ROOT, else <tree>. Line ends kept. Backups in r119b_backup next to this script.
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119b_backup")
ROOT = os.environ.get("R119B_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TMP = ".r119btmp"

PARAMS = R + "cloud_layer_params.h"
SHADER = H + "cloud_layer.comp"
LAYOUT = H + "cloud_layer_layout.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

DEPTH_BLOCK = '''
// ---- the depth probe (r119b) -------------------------------------------------------------------

/// The depth probe's bands (cloud_layer_layout.h CL_WORD_Z_SKY..CL_WORD_Z_LAST): the first pixel of each
/// march block is counted by depth 1, then by view z (m) at or over each of DepthEdges, then the rest.
inline constexpr std::size_t DepthBands = CL_WORD_Z_LAST - CL_WORD_Z_SKY + 1;
inline constexpr std::array<float, 5> DepthEdges{CL_Z_EDGE0, CL_Z_EDGE1, CL_Z_EDGE2, CL_Z_EDGE3,
                                                 CL_Z_EDGE4};
static_assert(DepthBands == DepthEdges.size() + 2);

/// Each band's share of the march blocks (the picture's depth: where a place's sky lies).
inline std::array<double, DepthBands> DepthShares(const Totals& t) {
    std::array<double, DepthBands> out{};
    const double total = double(t.words[CL_WORD_TOTAL]);
    for (std::size_t i = 0; i < out.size(); ++i) {
        out[i] = total > 0.0 ? double(t.words[CL_WORD_Z_SKY + i]) / total : 0.0;
    }
    return out;
}

'''

CPP_BLOCK = '''    // bbport (r119b_clouds-visible): the picture's depth (the first pixel of each march block), so a place whose
    // sky is not depth 1 shows its view z here; under 300 characters
    const std::array<double, CL::DepthBands> z = CL::DepthShares(totals);
    BbReport::Printf("Volumetric clouds (r119b): picture depth shares: depth 1 %.3f, then view z from %.0f m "
                     "%.3f, from %.0f %.3f, from %.0f %.3f, from %.0f %.3f, from %.0f %.3f, rest %.3f; "
                     "counted as sky from view z %.0f m (0: depth 1 only)\\n",
                     z[0], double(CL::DepthEdges[0]), z[1], double(CL::DepthEdges[1]), z[2],
                     double(CL::DepthEdges[2]), z[3], double(CL::DepthEdges[3]), z[4],
                     double(CL::DepthEdges[4]), z[5], z[6], double(knobs.sky_z));
'''

SHADER_FN = '''
// bbport (r119b_clouds-visible): the depth probe's counter word of a depth: CL_WORD_Z_SKY for depth 1, then
// the view z bands (CL_Z_EDGE0 to CL_Z_EDGE4), CL_WORD_Z_LAST for the rest (and for no depth).
uint z_word(float depth) {
    if (depth >= 1.0) return CL_WORD_Z_SKY;
    float z = view_z(depth);
    if (!(z > 0.0)) return CL_WORD_Z_LAST;
    if (z >= CL_Z_EDGE0) return CL_WORD_Z_SKY + 1u;
    if (z >= CL_Z_EDGE1) return CL_WORD_Z_SKY + 2u;
    if (z >= CL_Z_EDGE2) return CL_WORD_Z_SKY + 3u;
    if (z >= CL_Z_EDGE3) return CL_WORD_Z_SKY + 4u;
    if (z >= CL_Z_EDGE4) return CL_WORD_Z_SKY + 5u;
    return CL_WORD_Z_LAST;
}
'''

TEST_BLOCK = '''    // i. (r119b) the game's sky dome is drawn a little short of depth 1: the default counts it as sky.
    {
        // the log's projection: Camera motion: projection x 1.4280 y 2.5386 z 1.000017 -0.050068
        const std::array<float, 4> proj{1.4280f, 2.5386f, 1.000017f, -0.050068f};
        const auto depth_of = [&](float z) { return proj[2] + proj[3] / z; };
        assert(DefaultSkyZ == 500.0f && MakeKnobs("1", nullptr, nullptr, nullptr, nullptr).sky_z == 500.0f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "0").sky_z == 0.0f);
        for (const float z : {600.0f, 1500.0f, 1900.0f, 2800.0f}) { // the dome 1500 to 1900 m, the far plane 2945 m
            assert(depth_of(z) < 1.0f);
            assert(IsSky(depth_of(z), proj, DefaultSkyZ));
            assert(!IsSky(depth_of(z), proj, 0.0f)); // r119's rule: depth 1 only, so the dome never counted
        }
        for (const float z : {0.5f, 30.0f, 200.0f, 400.0f}) {
            assert(!IsSky(depth_of(z), proj, DefaultSkyZ));
        }
        assert(IsSky(1.0f, proj, DefaultSkyZ) && IsSky(1.0f, proj, 0.0f));
        // the probe's bands: the edges and the words
        assert(DepthBands == 7 && DepthEdges[0] == 1500.0f && DepthEdges[1] == 1000.0f &&
               DepthEdges[2] == 500.0f && DepthEdges[3] == 250.0f && DepthEdges[4] == 100.0f);
        assert(CL_WORD_Z_SKY > CL_WORD_STEPS && CL_WORD_Z_LAST < CL_WORDS);
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_TOTAL] = 1000;
        frame[CL_WORD_Z_SKY] = 100;
        frame[CL_WORD_Z_SKY + 1] = 300;
        frame[CL_WORD_Z_LAST] = 600;
        t.Add(frame);
        t.Add(frame);
        const std::array<double, DepthBands> shares = DepthShares(t);
        assert(Near(shares[0], 0.1, 1e-9) && Near(shares[1], 0.3, 1e-9) && shares[2] == 0.0 &&
               Near(shares[DepthBands - 1], 0.6, 1e-9));
        assert(DepthShares(Totals{})[0] == 0.0);
    }
'''

README_SKY_OLD = ("only over the pixels where the sky shows (depth 1; `BB_VOLUMETRIC_CLOUDS_SKYZ` can count a far "
                  "view z too)")
README_SKY_NEW = ("only over the pixels where the sky shows (depth 1, or a view z beyond 500 m: the game's sky "
                  "dome is drawn a little short of depth 1; `BB_VOLUMETRIC_CLOUDS_SKYZ` sets that distance)")
README_LOG_OLD = "with a second line of frame counts and the camera's height."
README_LOG_NEW = ("with a second line of frame counts and the camera's height, and a third (`r119b`) with the shares "
                  "of the picture at depth 1 and at a view z over 1500, 1000, 500, 250 and 100 m, which says where "
                  "a place's sky lies.")
README_ROW_OLD = ("| A pixel whose view z is beyond this many metres counts as sky too (0 to 100000; 0: only depth 1 "
                  "is sky). For a place whose sky is drawn with a depth short of 1 | `0` |")
README_ROW_NEW = ("| A pixel whose view z is beyond this many metres counts as sky too (0 to 100000; 0: only depth 1 "
                  "is sky). The game's sky dome is a mesh drawn a little short of depth 1 (about 1500 to 1900 m away "
                  "at lamp-test-spot), so the default counts everything beyond 500 m; a far tower under a rising view "
                  "ray counts as sky too. The log's `r119b` line says what depth the picture has | `500` |")

# (file, old, new): each old found exactly once before, each new exactly once after.
EDITS = [
    (PARAMS, "///< BB_VOLUMETRIC_CLOUDS_SKYZ's clamp\n",
     "///< BB_VOLUMETRIC_CLOUDS_SKYZ's clamp\n"
     "inline constexpr float DefaultSkyZ = 500.0f; ///< m: view z beyond which a pixel is sky (the dome: 1500 m and more)\n"),
    (PARAMS, "    float sky_z = 0.0f; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only",
     "    float sky_z = DefaultSkyZ; ///< view z (m) beyond which a pixel counts as sky too; 0: depth 1 only"),
    (PARAMS, "CloudShadows::Number(sky_z, 0.0f)", "CloudShadows::Number(sky_z, DefaultSkyZ)"),
    (PARAMS, "inline constexpr float Ambient = 0.80f;", "inline constexpr float Ambient = 0.65f;"),
    (PARAMS, "inline constexpr float LightGain = 1.0f;", "inline constexpr float LightGain = 1.4f;"),
    (PARAMS, "static_assert(CL_WORD_STEPS < CL_WORDS && CL_DIV == 2 && CL_WG == 8 && CL_FLAG_SHOW == 1);",
     "static_assert(CL_WORD_STEPS < CL_WORDS && CL_DIV == 2 && CL_WG == 8 && CL_FLAG_SHOW == 1);\n"
     "static_assert(CL_WORD_Z_SKY == CL_WORD_STEPS + 1u && CL_WORD_Z_LAST < CL_WORDS && CL_Z_EDGE0 == 1500.0 &&\n"
     "              CL_Z_EDGE1 == 1000.0 && CL_Z_EDGE2 == 500.0 && CL_Z_EDGE3 == 250.0 && CL_Z_EDGE4 == 100.0);"),
    (PARAMS, "} // namespace CloudLayerParams", DEPTH_BLOCK.lstrip("\n") + "} // namespace CloudLayerParams"),
    (LAYOUT, "#define CL_WORDS 8u\n",
     "// The depth probe (r119b): the first pixel of each march block, sky or not, by its depth: word Z_SKY depth 1,\n"
     "// then the view z (m) at or over EDGE0 .. EDGE4 (one band a word, Z_SKY + 1 .. Z_SKY + 5), Z_LAST the rest.\n"
     "#define CL_WORD_Z_SKY 6u\n"
     "#define CL_WORD_Z_LAST 12u\n"
     "#define CL_Z_EDGE0 1500.0\n"
     "#define CL_Z_EDGE1 1000.0\n"
     "#define CL_Z_EDGE2 500.0\n"
     "#define CL_Z_EDGE3 250.0\n"
     "#define CL_Z_EDGE4 100.0\n"
     "#define CL_WORDS 16u\n"),
    (SHADER, "bool is_sky(float depth) {\n    return depth >= 1.0 || (dist.z > 0.0 && view_z(depth) > dist.z);\n}\n",
     "bool is_sky(float depth) {\n    return depth >= 1.0 || (dist.z > 0.0 && view_z(depth) > dist.z);\n}\n" + SHADER_FN),
    (SHADER, "vec4 march(ivec2 hp) {\n    ivec2 base = hp * CL_DIV;\n",
     "vec4 march(ivec2 hp) {\n    ivec2 base = hp * CL_DIV;\n"
     "    // bbport (r119b_clouds-visible): the depth probe (one fetch, one shared atomic a march pixel)\n"
     "    atomicAdd(group_counts[z_word(texelFetch(depth_tex, base, 0).r)], 1u);\n"),
    (CPP, "    stats = {};\n    totals = {};\n}", CPP_BLOCK + "    stats = {};\n    totals = {};\n}"),
    (HDR, "// depth below 1, is never written; BB_VOLUMETRIC_CLOUDS_SKYZ lets a far view z count as sky too).",
     "// depth below 1 and nearer than BB_VOLUMETRIC_CLOUDS_SKYZ metres (500) is never written: the game's sky\n"
     "// dome is drawn a little short of depth 1)."),
    (TEST, "k.sky_z == 0.0f);", "k.sky_z == DefaultSkyZ);"),
    (TEST, "e.thick == DefaultThick && e.steps == DefaultSteps && e.sky_z == 0.0f);",
     "e.thick == DefaultThick && e.steps == DefaultSteps && e.sky_z == DefaultSkyZ);"),
    (TEST, '    std::puts("cloud layer: ok");', TEST_BLOCK + '    std::puts("cloud layer: ok");'),
    (README, README_SKY_OLD, README_SKY_NEW),
    (README, README_LOG_OLD, README_LOG_NEW),
    (README, README_ROW_OLD, README_ROW_NEW),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def squash(text):
    return re.sub(r"\s+", "", text)


def text_checks(texts):
    """Ties (rule 10): the README, the layout, the shader and the header agree."""
    params, layout, shader = texts[PARAMS], texts[LAYOUT], texts[SHADER]
    readme = texts[README].split("\n")
    row = [l for l in readme if l.startswith("| `BB_VOLUMETRIC_CLOUDS_SKYZ` |")]
    if len(row) != 1 or "| `500` |" not in row[0] or "0 to 100000" not in row[0]:
        raise SystemExit("tie check: README SKYZ row against DefaultSkyZ and MaxSkyZ")
    if params.count("DefaultSkyZ = 500.0f;") != 1 or "view z beyond 500 m" not in texts[README]:
        raise SystemExit("tie check: DefaultSkyZ 500 against the README's 'view z beyond 500 m'")
    if "view z over 1500, 1000, 500, 250 and 100 m" not in texts[README]:
        raise SystemExit("tie check: README's depth bands")
    for edge, value in (("0", "1500.0"), ("1", "1000.0"), ("2", "500.0"), ("3", "250.0"), ("4", "100.0")):
        if layout.count("#define CL_Z_EDGE%s %s\n" % (edge, value)) != 1:
            raise SystemExit("tie check: layout CL_Z_EDGE%s" % edge)
        if shader.count("z >= CL_Z_EDGE%s)" % edge) != 1:
            raise SystemExit("tie check: shader uses CL_Z_EDGE%s once" % edge)
    for define in ("#define CL_WORD_Z_SKY 6u\n", "#define CL_WORD_Z_LAST 12u\n", "#define CL_WORDS 16u\n"):
        if layout.count(define) != 1:
            raise SystemExit("tie check: layout %s" % define.strip())
    if layout.count("#define CL_WORD_STEPS 5u") != 1:
        raise SystemExit("tie check: CL_WORD_STEPS is no longer 5 (the probe starts at 6)")
    for text in ("Ambient = 0.65f;", "LightGain = 1.4f;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119B_ROOT)" % ROOT)
    files = []
    for path, _, _ in EDITS:
        if path not in files:
            files.append(path)
    plan, texts_now = {}, {}
    for path in files:
        raw, eol, cur = load(path)
        mine = [e for e in EDITS if e[0] == path]
        done = sum(cur.count(new) == 1 for _, old, new in mine)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for _, old, new in mine)
        if done == len(mine):
            state = "applied"
        elif todo == len(mine):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (is r119 applied? "
                             "is another patch editing the same text?)" % (path, done, len(mine), todo))
        plan[path] = (raw, eol, cur, state)
        texts_now[path] = cur
    states = {p[3] for p in plan.values()}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (k, v[3]) for k, v in plan.items()))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks(texts_now)
            print("applied (text checks pass)")
        else:
            after = {}
            for path in files:
                cur = plan[path][2]
                for p, old, new in EDITS:
                    if p == path:
                        cur = cur.replace(old, new, 1)
                after[path] = cur
            text_checks(after)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(files), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        outs, after = [], {}
        for path in files:
            raw, eol, cur, _ = plan[path]
            for p, old, new in EDITS:
                if p == path:
                    cur = cur.replace(old, new, 1)
            after[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(after)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                open(full + TMP, "wb").write(data)
                os.replace(full + TMP, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                if os.path.exists(os.path.join(ROOT, path) + TMP):
                    os.remove(os.path.join(ROOT, path) + TMP)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(files), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = []
    for path in files:
        raw, eol, cur, _ = plan[path]
        for p, old, new in reversed(EDITS):
            if p == path:
                if cur.count(new) != 1:
                    raise SystemExit("%s: edit not found exactly once: %r" % (path, new[:70]))
                cur = cur.replace(new, old, 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files edited back)" % len(files))


main()
