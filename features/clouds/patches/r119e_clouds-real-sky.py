# r119e_clouds-real-sky: FEATURE fix on top of r119d_clouds-contrast.fixed.py, r119c, r119b and r119 (BB_VOLUMETRIC_CLOUDS=1
# only; still off by default, still costs nothing when off: nothing here runs without the CloudLayer object, which
# Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# What b43 showed (jobs r119d-lt, -lt2, -gb, -di): the lamp-test-spot numbers are good (visible 0.71, covered 0.78, dark
# 0.34 + bright 0.55 = 0.89) and on against off shows darker masses with brighter rims in the arches, but (a) the sky is
# only about 5-15% of a slot frame at the lamp-test-spot arches, so the look reads "modest"; (b) the two captures were
# 2 s apart and the drift (15 to 48 m/s at the layer) did not read; (c) the graveyard job looked straight up and saw the
# underside of the great bridge (sky px share 0.008, 98.6% of the picture nearer than 500 m): no open sky.
# Places (all pictures of the runner's nine places in the scratch folder were looked at, 2026-11-16): none of them has an
# open sky that fills half a frame at the game's own highest camera pitch. The largest sky shares are the lamp-test-spot
# arches looking up (two arches, painted dusk clouds, the dome pair draws: about 12-15%) and the church-puddles arch
# (about 15%; whether the clouds draw there is read from the r119 line); the graveyard looking up is the bridge. So this
# patch cannot give half a picture of sky from a place; it makes the sky it has READABLE (below) and the job file asks
# for the comparisons that read at 15%: captures 6 s apart, a live speed x4 between two more, a frozen field for
# contrast steps, off and on at the same camera, and crops of the sky regions for the readers (see the job labels).
# Fix (all inside r119's own files; no shader build other than the MARCH colour lines, COMPOSITE byte-identical):
#  1. LIVE SPEED. BB_VOLUMETRIC_CLOUDS_SPEED is read every frame through the test tools' live knobs header (guarded by
#     __has_include like r119's BB_VOLUMETRIC_CLOUDS knob), so a job can run default speed for 6 s, then
#     set:BB_VOLUMETRIC_CLOUDS_SPEED=24 (x4), then 0.25 (frozen: 0.6 m/s) in ONE game. Without the live knobs header
#     or file nothing changes: the value of the start. Each change is said once: "Volumetric clouds (r119e): ...".
#  2. CONTRAST. New BB_VOLUMETRIC_CLOUDS_CONTRAST (0.5 to 3, default 1.25, also a live knob): the march's shade colour
#     (the dark underside) is divided by it and its lit colour (the rim) multiplied by its square root: 1 is the r119d
#     look, 1.25 makes the undersides 20% darker and the rims 12% brighter (the cloud's own opacity cap 0.92 stays).
#     Carried in Params.dist.w (was unused: the block stays 13 vec4). Sim (S/r119e_sim_contrast.py, the r119d march
#     port; sun 22 degrees up, 36 views of the sky): visible-cloud brightness against the sky behind it, p5 / p50 / p95:
#     contrast 1.0 0.28 / 1.33 / 4.00, 1.25 0.25 / 1.38 / 4.38, 1.6 0.23 / 1.46 / 4.85, 2.0 0.21 / 1.53 / 5.33
#     (the dark and bright shares stay 0.43 / 0.50: the pixels were already past the 0.7 and 1.4 marks; it is the size
#     of the gap that grows). Moderate on purpose: the rim already reaches 4 x the sky near the light.
#  3. LOG. The once-line says the contrast and whether the knobs are live; the r119d periodic line also says the contrast;
#     a live change prints one line at once (prefix "Volumetric", which the slot runner keeps).
# Cost: one divide and one sqrt per MARCH pixel (half resolution, sky pixels only): not measurable; estimate unchanged
# 0.2 to 0.4 ms at 1080p internal with half the picture sky, 0.03 ms with none. No new memory. The live reads are two
# atomic loads a frame while the layer is on. Not measured.
# Off guarantee: nothing of this runs without the CloudLayer object (Rasterizer makes it only with
# BB_VOLUMETRIC_CLOUDS=1); the new knob and the live reads live inside it.
#
# TOOL or FEATURE: FEATURE (same lane as r119). The live-knob reads are guarded by __has_include of the test tools'
# header (a feature branch without it reads the values once, at the start).
# Edits r119's own files: cloud_layer_params.h, cloud_layer.comp, vk_cloud_layer.cpp/.h, tests/test_cloud_layer.cpp,
# README.md. No new file, no shared hook, no CMake change. Apply after r119, r119b, r119c and r119d; revert BEFORE
# r119d (their checks tie to text this patch changes).
#
# Use: python -I -X utf8 r119e_clouds-real-sky.py check | apply | revert
# Root: R119E_ROOT, else <tree>. Line ends kept. Backups in r119e_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119e_backup")
ROOT = os.environ.get("R119E_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TMP = ".r119etmp"

PARAMS = R + "cloud_layer_params.h"
SHADER = H + "cloud_layer.comp"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

SHADER_NOTE_OLD = "// 0.7 or brighter than 1.4 of the sky behind it.\n#version 450\n"
SHADER_NOTE_NEW = '''// 0.7 or brighter than 1.4 of the sky behind it.
// bbport (r119e_clouds-real-sky): a contrast (Params.dist.w, BB_VOLUMETRIC_CLOUDS_CONTRAST, 1 = the r119d look): the
// shade colour is divided by it and the lit colour multiplied by its square root (darker undersides, brighter rims).
#version 450
'''

SHADER_COLS_OLD = '''    vec3 shade_col = mix(tint, grey, tone.z) * SHADE_COOL;
    vec3 lit_col = mix(tint, grey, 0.5 * tone.z);
'''
SHADER_COLS_NEW = '''    float contrast = dist.w > 0.0 ? dist.w : 1.0; // bbport (r119e_clouds-real-sky)
    vec3 shade_col = mix(tint, grey, tone.z) * SHADE_COOL / contrast;
    vec3 lit_col = mix(tint, grey, 0.5 * tone.z) * sqrt(contrast);
'''

PARAMS_FLOOR_OLD = "inline constexpr float DriftFloor = 2.5f, DriftCeil = 8.0f;\n"
PARAMS_FLOOR_NEW = PARAMS_FLOOR_OLD + '''// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_CONTRAST pushes the dark undersides and the lit rims apart: the
// march's shade colour is divided by it and its lit colour multiplied by its square root (1: the r119d look).
inline constexpr float DefaultContrast = 1.25f;
inline constexpr float MinContrast = 0.5f, MaxContrast = 3.0f; ///< BB_VOLUMETRIC_CLOUDS_CONTRAST's clamp
static_assert(DefaultContrast >= MinContrast && DefaultContrast <= MaxContrast);
'''

PARAMS_PARSE_OLD = "inline Knobs MakeKnobs(const char* on, const char* cover, const char* density, const char* height,\n"
PARAMS_PARSE_NEW = '''/// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST from their text (the live knobs ask these
/// again every frame): a number is clamped, anything else is the default.
inline float ParseSpeed(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultSpeed), MinSpeed, MaxSpeed);
}
inline float ParseContrast(const char* text) {
    return std::clamp(CloudShadows::Number(text, DefaultContrast), MinContrast, MaxContrast);
}
/// What a contrast does to the march's two colours (cloud_layer.comp): the shade side divided, the lit side times the
/// square root.
inline float ShadeScale(float contrast) {
    return 1.0f / contrast;
}
inline float LitScale(float contrast) {
    return std::sqrt(contrast);
}

''' + PARAMS_PARSE_OLD

EDITS = [
    # ---- the shader (MARCH colours only; COMPOSITE's code is untouched)
    (SHADER, SHADER_NOTE_OLD, SHADER_NOTE_NEW),
    (SHADER, "    vec4 dist;             // distance fade from, to (m); sky view z (m, 0: depth 1 only); unused\n",
     "    vec4 dist;             // distance fade from, to (m); sky view z (m, 0: depth 1 only); contrast (r119e)\n"),
    (SHADER, SHADER_COLS_OLD, SHADER_COLS_NEW),
    # ---- the parameters
    (PARAMS, PARAMS_FLOOR_OLD, PARAMS_FLOOR_NEW),
    (PARAMS, "    float speed = DefaultSpeed; ///< times the one wind's cloud speed (r119c)\n",
     "    float speed = DefaultSpeed; ///< times the one wind's cloud speed (r119c)\n"
     "    float contrast = DefaultContrast; ///< bbport (r119e): the march's shade divided by it, its lit light times its square root\n"),
    (PARAMS, PARAMS_PARSE_OLD, PARAMS_PARSE_NEW),
    (PARAMS, "                       const char* speed = nullptr) {\n    Knobs k;\n",
     "                       const char* speed = nullptr, const char* contrast = nullptr) {\n    Knobs k;\n"),
    (PARAMS, "    k.speed = std::clamp(CloudShadows::Number(speed, DefaultSpeed), MinSpeed, MaxSpeed);\n",
     "    k.speed = ParseSpeed(speed);\n    k.contrast = ParseContrast(contrast); // bbport (r119e_clouds-real-sky)\n"),
    (PARAMS, "    std::array<float, 4> dist{};                 ///< fade from, to (m); sky view z; unused\n",
     "    std::array<float, 4> dist{};                 ///< fade from, to (m); sky view z; contrast (r119e)\n"),
    (PARAMS, "    p.dist = {FadeFrom, FadeTo, knobs.sky_z, 0.0f};\n",
     "    p.dist = {FadeFrom, FadeTo, knobs.sky_z, knobs.contrast};\n"),
    # ---- the engine: header
    (HDR, "    const CloudLayerParams::Knobs knobs;\n",
     "    const CloudLayerParams::Knobs knobs;\n"
     "    CloudLayerParams::Knobs live; ///< bbport (r119e): the knobs with the speed and the contrast as they are now (live knobs)\n"),
    (HDR, "    bool Active();\n",
     "    bool Active();\n"
     "    /// bbport (r119e_clouds-real-sky): the speed and the contrast now (live knobs); says each change once.\n"
     "    void ReadLive();\n"),
    (HDR, "    bool told_on = true; ///< what the live knob said last (the constructor's line says on)\n",
     "    bool told_on = true; ///< what the live knob said last (the constructor's line says on)\n"
     "    float told_speed = -1.0f, told_contrast = -1.0f; ///< bbport (r119e): the live speed and contrast said last (below 0: none yet)\n"),
    # ---- the engine: source
    (CPP, "double Seconds() {\n",
     '''/// bbport (r119e_clouds-real-sky): BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST now: live knobs with the test tools' header
/// (asked again at every use), else the start's value.
float LiveSpeed([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> speed{"BB_VOLUMETRIC_CLOUDS_SPEED", CL::ParseSpeed};
    return speed.Get();
#else
    return at_start;
#endif
}

float LiveContrast([[maybe_unused]] float at_start) {
#if BB_CLOUD_LAYER_LIVE
    static BbLiveKnobs::Knob<float> contrast{"BB_VOLUMETRIC_CLOUDS_CONTRAST", CL::ParseContrast};
    return contrast.Get();
#else
    return at_start;
#endif
}

constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? "live knobs on" : "read at the start";

double Seconds() {
'''),
    # review fix: the start's read passes BB_VOLUMETRIC_CLOUDS_CONTRAST too (else a branch without the live knobs
    # header ignores the variable, and the once-line prints 1.25 whatever it says)
    (CPP, "std::getenv(\"BB_VOLUMETRIC_CLOUDS_SIZE\"), std::getenv(\"BB_VOLUMETRIC_CLOUDS_SPEED\"));\n",
     "std::getenv(\"BB_VOLUMETRIC_CLOUDS_SIZE\"), std::getenv(\"BB_VOLUMETRIC_CLOUDS_SPEED\"),\n"
     "        std::getenv(\"BB_VOLUMETRIC_CLOUDS_CONTRAST\")); // bbport (r119e_clouds-real-sky)\n"),
    (CPP, "scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{Load()},\n      shared{CloudShadow::Active()} {\n",
     "scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{Load()}, live{Load()},\n      shared{CloudShadow::Active()} {\n"),
    (CPP, "                     knobs.show ? \"; SHOW\" : \"\");\n}\n",
     "                     knobs.show ? \"; SHOW\" : \"\");\n"
     "    // bbport (r119e_clouds-real-sky): the contrast and the live knobs, once (under 300 characters)\n"
     "    BbReport::Printf(\"Volumetric clouds (r119e, BB_VOLUMETRIC_CLOUDS=1): contrast %.2f (undersides x%.2f, rims x%.2f), \"\n"
     "                     \"BB_VOLUMETRIC_CLOUDS_SPEED and _CONTRAST (%s)\\n\",\n"
     "                     double(knobs.contrast), double(CL::ShadeScale(knobs.contrast)),\n"
     "                     double(CL::LitScale(knobs.contrast)), LiveText);\n"
     "}\n"),
    (CPP, "void CloudLayer::SetSunLight(const std::array<float, 3>& world, bool valid) {\n",
     '''void CloudLayer::ReadLive() {
    live.speed = LiveSpeed(knobs.speed);
    live.contrast = LiveContrast(knobs.contrast);
    if (told_speed < 0.0f) {
        told_speed = live.speed;
        told_contrast = live.contrast;
        return;
    }
    if (live.speed != told_speed || live.contrast != told_contrast) {
        told_speed = live.speed;
        told_contrast = live.contrast;
        std::printf("Volumetric clouds (r119e): live knobs: speed x%.2f (%.1f m/s), contrast %.2f (undersides x%.2f, "
                    "rims x%.2f)\\n",
                    double(live.speed), double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)),
                    double(live.contrast), double(CL::ShadeScale(live.contrast)),
                    double(CL::LitScale(live.contrast)));
    }
}

void CloudLayer::SetSunLight(const std::array<float, 3>& world, bool valid) {
'''),
    (CPP, "    // bbport (r119c_clouds-gaps): the layer's own offsets move at the one wind's cloud heading and speed (the\n",
     "    ReadLive(); // bbport (r119e_clouds-real-sky): the live speed and contrast of this frame\n"
     "    // bbport (r119c_clouds-gaps): the layer's own offsets move at the one wind's cloud heading and speed (the\n"),
    (CPP, "                        CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), knobs), knobs.size);\n",
     "                        CL::LayerWind(Direction(), ClockState().Velocity(ClockKnobs()), live), live.size);\n"),
    (CPP, "                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), knobs)), double(knobs.size),\n",
     "                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)), double(knobs.size),\n"),
    (CPP, "                     \"drift %.1f m/s\\n\",\n",
     "                     \"drift %.1f m/s, contrast %.2f\\n\",\n"),
    (CPP, "                     double(CL::OpacityCap),\n                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), knobs)));\n",
     "                     double(CL::OpacityCap),\n                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), live)),\n"
     "                     double(live.contrast));\n"),
    (CPP, "    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, layer_drift, knobs, light,\n",
     "    const CL::Params params = CL::MakeParams(camera.inv_view, camera.proj, layer_drift, live, light,\n"),
    # ---- the test
    (TEST, '    std::puts("cloud layer: ok");',
     '''    // l. (r119e_clouds-real-sky) the contrast knob and the live parsers: clamped, defaulted, in the Params block.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(d.contrast == DefaultContrast && DefaultContrast == 1.25f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "1.6").contrast == 1.6f);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "99").contrast == MaxContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "0").contrast == MinContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "abc").contrast == DefaultContrast);
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "nan").contrast == DefaultContrast);
        assert(ParseContrast(nullptr) == DefaultContrast && ParseContrast("2") == 2.0f && ParseContrast("") == DefaultContrast);
        assert(ParseSpeed(nullptr) == DefaultSpeed && ParseSpeed("24") == 24.0f && ParseSpeed("0") == MinSpeed &&
               ParseSpeed("999") == MaxSpeed && ParseSpeed("x") == DefaultSpeed);
        // the live reads give what the start's read gives
        assert(MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "12").speed == ParseSpeed("12"));
        // the two scales: 1 is the r119d look; 1.25 is undersides x0.80 and rims x1.12
        assert(ShadeScale(1.0f) == 1.0f && LitScale(1.0f) == 1.0f);
        assert(Near(ShadeScale(DefaultContrast), 0.8, 1e-6) && Near(LitScale(DefaultContrast), 1.118034, 1e-5));
        assert(ShadeScale(2.0f) < ShadeScale(DefaultContrast) && LitScale(2.0f) > LitScale(DefaultContrast));
        // the Params block carries it in dist.w
        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<float, 4> proj{1.2f, -2.1f, 1.0f, 0.1f};
        VolumetricFogNoise::Drift drift;
        const Params p = MakeParams(rows, proj, drift, d, {0.0f, 1.0f, 0.0f}, true, {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(p.dist[3] == DefaultContrast && p.dist[2] == DefaultSkyZ);
        const Knobs hot = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, "2");
        const Params q = MakeParams(rows, proj, drift, hot, {0.0f, 1.0f, 0.0f}, true, {0.0f, 0.0f}, {0.0f, 0.0f});
        assert(q.dist[3] == 2.0f);
        // the frozen speed (BB_VOLUMETRIC_CLOUDS_SPEED=0.25) is a small fraction of the default's drift
        Knobs slow = d;
        slow.speed = MinSpeed;
        assert(LayerSpeed(6.0f, slow) < LayerSpeed(6.0f, d) / 20.0f && LayerSpeed(6.0f, slow) > 0.0f);
    }
    std::puts("cloud layer: ok");'''),
    # ---- the README
    (README, "the shapes morph slowly whatever the speed | `6` |",
     "the shapes morph slowly whatever the speed; with the test tools' live knobs file it can be changed in a running game | `6` |"),
    (README, "| `BB_VOLUMETRIC_CLOUDS_DENSITY` | 0.05 to 4: the density,",
     "| `BB_VOLUMETRIC_CLOUDS_CONTRAST` | 0.5 to 3: how far the dark undersides and the lit rims are pushed apart: the dark side's colour is divided by it and the lit side's multiplied by its square root (1 is the look before this knob; `1.25` makes the undersides 20% darker and the rims 12% brighter; the clouds' opacity cap stays). With the test tools' live knobs file it can be changed in a running game | `1.25` |\n"
     "| `BB_VOLUMETRIC_CLOUDS_DENSITY` | 0.05 to 4: the density,"),
    (README, "(the first set of lines comes after 200 frames, then every 600). Cost:",
     "(the first set of lines comes after 200 frames, then every 600; the fourth also says the contrast, and the start says it once with whether the speed and contrast are live knobs; a live change of either prints one `Volumetric clouds (r119e)` line at once). Cost:"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the header and the shader agree."""
    params, shader, readme, cpp = texts[PARAMS], texts[SHADER], texts[README], texts[CPP]
    for text in ("DefaultContrast = 1.25f;", "MinContrast = 0.5f, MaxContrast = 3.0f;", "DefaultSpeed = 6.0f;",
                 "p.dist = {FadeFrom, FadeTo, knobs.sky_z, knobs.contrast};", "return 1.0f / contrast;",
                 "return std::sqrt(contrast);"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_CONTRAST` |")]
    if len(rows) != 1:
        raise SystemExit("tie check: one README row for CONTRAST")
    row = rows[0]
    if not row.rstrip().endswith("| `1.25` |") or "0.5 to 3" not in row or "20% darker" not in row or "12% brighter" not in row:
        raise SystemExit("tie check: README CONTRAST row against DefaultContrast / the clamp / the scales")
    # 1 / 1.25 = 0.80 (20% darker), sqrt(1.25) = 1.118 (12% brighter)
    if abs(1.0 / 1.25 - 0.80) > 1e-9 or abs(1.25 ** 0.5 - 1.12) > 0.005:
        raise SystemExit("tie check: the README's 20% and 12%")
    spd = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_SPEED` |")]
    if len(spd) != 1 or "| `6` |" not in spd[0] or "live knobs file" not in spd[0]:
        raise SystemExit("tie check: README SPEED row")
    for text in ("float contrast = dist.w > 0.0 ? dist.w : 1.0;", "* SHADE_COOL / contrast;", "* sqrt(contrast);"):
        if shader.count(text) != 1:
            raise SystemExit("tie check: shader %s" % text)
    if "vec3 lit_col = mix(tint, grey, 0.5 * tone.z);" in shader:
        raise SystemExit("tie check: the old lit colour is still in the shader")
    for text in ('"BB_VOLUMETRIC_CLOUDS_SPEED", CL::ParseSpeed', '"BB_VOLUMETRIC_CLOUDS_CONTRAST", CL::ParseContrast',
                 "layer_drift, live, light,", 'std::getenv("BB_VOLUMETRIC_CLOUDS_CONTRAST")'):
        if cpp.count(text) != 1:
            raise SystemExit("tie check: cpp %s" % text)
    if "knobs)));" in cpp.split("void CloudLayer::Report()")[1] or ", knobs), double(knobs.size)," in cpp:
        raise SystemExit("tie check: the report still reads the start's speed")
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119E_ROOT)" % ROOT)
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
            bad = [old[:60] for _, old, new in mine if not (cur.count(new) == 1 or (cur.count(old) == 1 and cur.count(new) == 0))]
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (are r119 to r119d applied? "
                             "is another patch editing the same text?) first failing anchor: %r"
                             % (path, done, len(mine), todo, bad[:1]))
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
