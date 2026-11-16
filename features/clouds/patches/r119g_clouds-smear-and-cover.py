# r119g_clouds-smear-and-cover: FEATURE fix on top of r119f_clouds-open-sky.fixed.py and r119 to r119e
# (BB_VOLUMETRIC_CLOUDS=1 only; still off by default, still costs nothing when off: nothing here runs without the
# CloudLayer object, which Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# Why (b49, picture _rd_clouds_pair.png, lamp-test-spot w6, left off, right on): a DARK ANGULAR SMEAR sits left of the
# hunter inside the cloud layer (a dark pyramid-like silhouette, hard edged underneath, soft above), and the layer
# covers much of the dramatic painted sky with soft cream blobs, which is the owner's look to choose.
#
# CAUSE of the smear (read from the shader and the picture; NOT yet proven in the game, the job pair below proves it):
#  - It is not a depth or edge fault. The off picture has nothing there, the pyramid is cloud: the march's pixels
#    around it are sky (bright orange glow low over the roofs) and the cloud in front of it is DENSE and UNLIT.
#  - Unlit because the lit light read ONE tap of the density, at the middle of the path toward the light (cloud_layer.comp
#    lit term, p + L x 0.5 lp). With the light low, lp is up to 600 m and the tap lands hundreds of metres to the side:
#    a dense core whose tap hits a neighbouring cloud edge goes from exp(-0) to exp(-12) over a few pixels. The tap
#    projects the cloud's own silhouette along the light into the picture: a hard edged, straight sided, dark shape
#    (the pyramid), with the cream forward glow only where the tap found clear air.
#  - Black, not just dark: with no lit light the shade is all that is left, tone.x (0.5) x mix(0.25, 1, v) of the sky,
#    divided by the contrast 1.25: a quarter of the sky or less at a cloud's base, against a bright horizon.
# FIX (the "smear fix", on by default, BB_VOLUMETRIC_CLOUDS_SMEAR=0 gives the exact r119f look in one game):
#  1. two light taps (LightTaps) at (k + jitter) / 2 of the path, the jitter the march's own per pixel interleaved noise
#     (the upscaler averages the frames): the hard silhouette turns into soft noise, and a core is no longer decided by
#     one tap. With the fix off one tap at 0.5, byte for byte the old arithmetic.
#  2. the shade at a cloud's base is 0.45 of its top's (was 0.25) (ShadeBase),
#  3. a horizon glow floor: where the ray is within 30 degrees of the horizon the accumulated shade is at least
#     HorizonGlow (0.30) x the cloud's opacity: the underside of a cloud low over a bright horizon is lit by that
#     horizon (smoothstep 0.10 to 0.50 of the ray's y).
# COVER and look choice for the owner: BB_VOLUMETRIC_CLOUDS_COVER becomes a live knob (the test tools' live knobs file),
# as BB_VOLUMETRIC_CLOUDS_CONTRAST and _SPEED already are, and a new BB_VOLUMETRIC_CLOUDS_TINT (0 to 1, default 0 = the
# look before) lets the clouds take the colour of the painted sky behind them: at 1 the shade side and the lit side are
# the sky's own tint (no desaturation, no cooling), so a cloud over a dusk glow is dusk coloured. TINT is a live knob.
# The job file makes the same-camera set in ONE game: off, cover 0.3 / 0.5 / 0.7, contrast 1.25 (the default) / 2.0,
# the smear fix off / on, and the tint 0.5 / 1.
#
# Code: the shader's Params block grows from 13 to 14 vec4 (extra: tint, light taps, shade base, horizon glow), the
# CPU Params the same, the buffer is sizeof(Params) so nothing else changes. The member is declared in the MARCH build
# only, so the COMPOSITE build stays byte-identical (proved with glslang).
# COST: the lit step reads the density twice instead of once (+1 noise evaluation of three octaves per lit step):
# estimate +0.1 to 0.2 ms at 1080p internal with half the picture sky (before 0.2-0.4); BB_VOLUMETRIC_CLOUDS_SMEAR=0 takes
# it back; no new memory (the params buffer grows by 16 bytes). Unmeasured.
#
# TOOL or FEATURE: FEATURE. No new file, no shared hook, no CMake change. Edits r119's own files: cloud_layer.comp,
# cloud_layer_params.h, vk_cloud_layer.cpp/.h, tests/test_cloud_layer.cpp, README.md. Apply after r119f; revert BEFORE
# r119f (its check ties to text near these lines).
#
# Use: python -I -X utf8 r119g_clouds-smear-and-cover.py check | apply | revert
# Root: R119G_ROOT, else <tree>. Line ends kept. Backups in r119g_backup next to this script.
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119g_backup")
ROOT = os.environ.get("R119G_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
TMP = ".r119gtmp"

PARAMS = R + "cloud_layer_params.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
SHADER = V + "host_shaders/cloud_layer.comp"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

EDITS = [
    # ---- the shader --------------------------------------------------------------------------------------------
    (SHADER,
     "// shade colour is divided by it and the lit colour multiplied by its square root (darker undersides, brighter rims).\n"
     "#version 450\n",
     "// shade colour is divided by it and the lit colour multiplied by its square root (darker undersides, brighter rims).\n"
     "// bbport (r119g_clouds-smear-and-cover): the dark angular smear (a dense cloud low over a bright horizon, lit by ONE\n"
     "// tap toward the light whose hard silhouette showed) is fixed by Params.extra: two jittered light taps, the shade at a\n"
     "// cloud's base 0.45 of its top's and a horizon glow floor (extra.y, .z, .w; the smear fix off gives the old arithmetic:\n"
     "// one tap at 0.5, base 0.25, no floor); extra.x is the tint (0: the sky's tint desaturated and cooled, 1: the sky's own).\n"
     "#version 450\n"),
    (SHADER,
     "    vec4 tone;             // ambient, light, desaturation of the tint, forward scatter\n};\n",
     "    vec4 tone;             // ambient, light, desaturation of the tint (tint knob applied), forward scatter\n"
     "#ifdef MARCH\n"
     "    vec4 extra;            // r119g: tint (0..1), light taps, shade base (at a cloud's base, of its top's), horizon glow\n"
     "#endif\n"
     "};\n"),
    (SHADER,
     "const float BASE_AMBIENT = 0.25;   // the shade at a cloud's base, of its top's (Params.tone.x)\n",
     "// (r119g: the shade at a cloud's base, of its top's, is Params.extra.z: 0.45, or 0.25 with the smear fix off)\n"),
    (SHADER,
     "        acc_amb += T * a * tone.x * mix(BASE_AMBIENT, 1.0, v);\n",
     "        acc_amb += T * a * tone.x * mix(extra.z, 1.0, v);\n"),
    (SHADER,
     "            float unused;\n"
     "            float dl = density_at(p + light.xyz * (0.5 * lp), lod, unused);\n",
     "            float unused;\n"
     "            // bbport (r119g_clouds-smear-and-cover): extra.y taps along the path toward the light, each at\n"
     "            // (k + jitter) / taps of it (one tap: the middle, as before), averaged: the cloud's own silhouette\n"
     "            // along the light no longer shows as a hard edged dark shape\n"
     "            int taps = max(int(extra.y), 1);\n"
     "            float dsum = 0.0;\n"
     "            for (int k = 0; k < taps; ++k) {\n"
     "                float where_at = taps > 1 ? (float(k) + jitter) / float(taps) : 0.5;\n"
     "                dsum += density_at(p + light.xyz * (where_at * lp), lod, unused);\n"
     "            }\n"
     "            float dl = dsum / float(taps);\n"),
    (SHADER,
     "    vec3 tint = sky_sum / sky_n;\n",
     "    // bbport (r119g): a horizon glow floor: low over the horizon the underside of a cloud is lit by it (extra.w = 0: off)\n"
     "    acc_amb = max(acc_amb, (1.0 - T) * extra.w * (1.0 - smoothstep(0.10, 0.50, dw.y)));\n"
     "    vec3 tint = sky_sum / sky_n;\n"),
    (SHADER,
     "    vec3 shade_col = mix(tint, grey, tone.z) * SHADE_COOL / contrast;\n",
     "    vec3 shade_col = mix(tint, grey, tone.z) * mix(SHADE_COOL, vec3(1.0), extra.x) / contrast; // bbport (r119g): tint\n"),
    # ---- the numbers and the knobs ------------------------------------------------------------------------------
    (PARAMS,
     "static_assert(DefaultContrast >= MinContrast && DefaultContrast <= MaxContrast);\n",
     "static_assert(DefaultContrast >= MinContrast && DefaultContrast <= MaxContrast);\n"
     "// bbport (r119g_clouds-smear-and-cover): the smear fix (cloud_layer.comp's header says what it does) and the tint.\n"
     "// BB_VOLUMETRIC_CLOUDS_SMEAR=0 turns the fix off (the r119f look), BB_VOLUMETRIC_CLOUDS_TINT 0 to 1 takes the sky's\n"
     "// own colour into the clouds; BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR are live knobs with the test tools' file.\n"
     "inline constexpr float DefaultTint = 0.0f;\n"
     "inline constexpr int LightTaps = 2;         ///< density taps toward the light with the fix on (1 with it off)\n"
     "inline constexpr float ShadeBase = 0.45f;   ///< the shade at a cloud's base, of its top's, with the fix on\n"
     "inline constexpr float OldShadeBase = 0.25f; ///< ... with the fix off (r119f)\n"
     "inline constexpr float HorizonGlow = 0.30f; ///< the shade floor x opacity for rays near the horizon, with the fix on\n"
     "inline float ParseCover(const char* text) {\n"
     "    return std::clamp(CloudShadows::Number(text, DefaultCover), 0.0f, 1.0f);\n"
     "}\n"
     "inline float ParseTint(const char* text) {\n"
     "    return std::clamp(CloudShadows::Number(text, DefaultTint), 0.0f, 1.0f);\n"
     "}\n"
     "/// The smear fix is on unless the text starts with 0.\n"
     "inline bool ParseSmear(const char* text) {\n"
     "    return text == nullptr || text[0] != '0';\n"
     "}\n"),
    (PARAMS,
     "    float contrast = DefaultContrast; ///< bbport (r119e): the march's shade divided by it, its lit light times its square root\n",
     "    float contrast = DefaultContrast; ///< bbport (r119e): the march's shade divided by it, its lit light times its square root\n"
     "    float tint = DefaultTint;         ///< bbport (r119g): 0 to 1, how much the clouds take the painted sky's own colour\n"
     "    bool smear = true;                ///< bbport (r119g): the smear fix (two light taps, shade base, horizon glow)\n"),
    (PARAMS,
     "                       const char* speed = nullptr, const char* contrast = nullptr) {\n",
     "                       const char* speed = nullptr, const char* contrast = nullptr,\n"
     "                       const char* tint = nullptr, const char* smear = nullptr) {\n"),
    (PARAMS,
     "    k.contrast = ParseContrast(contrast); // bbport (r119e_clouds-real-sky)\n",
     "    k.contrast = ParseContrast(contrast); // bbport (r119e_clouds-real-sky)\n"
     "    k.tint = ParseTint(tint);             // bbport (r119g_clouds-smear-and-cover)\n"
     "    k.smear = ParseSmear(smear);\n"),
    (PARAMS,
     "/// cloud_layer.comp's Params block: 13 vec4, field for field.\n",
     "/// cloud_layer.comp's Params block: 14 vec4 (r119g: extra), field for field.\n"),
    (PARAMS,
     "    std::array<float, 4> tone{};                 ///< ambient, light, desaturation, forward\n"
     "};\n"
     "static_assert(sizeof(Params) == 13 * 16 && offsetof(Params, off0) == 64 &&\n"
     "                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192,\n"
     "              \"cloud_layer.comp's Params block: 13 vec4\");\n",
     "    std::array<float, 4> tone{};                 ///< ambient, light, desaturation (tint applied), forward\n"
     "    std::array<float, 4> extra{};                ///< bbport (r119g): tint, light taps, shade base, horizon glow\n"
     "};\n"
     "static_assert(sizeof(Params) == 14 * 16 && offsetof(Params, off0) == 64 &&\n"
     "                  offsetof(Params, light) == 112 && offsetof(Params, tone) == 192 &&\n"
     "                  offsetof(Params, extra) == 208,\n"
     "              \"cloud_layer.comp's Params block: 14 vec4\");\n"),
    (PARAMS,
     "    p.tone = {Ambient, LightGain, Desaturate, Forward};\n",
     "    p.tone = {Ambient, LightGain, Desaturate * (1.0f - knobs.tint), Forward}; // bbport (r119g): the tint\n"
     "    p.extra = {knobs.tint, knobs.smear ? float(LightTaps) : 1.0f, knobs.smear ? ShadeBase : OldShadeBase,\n"
     "               knobs.smear ? HorizonGlow : 0.0f};\n"),
    # ---- the engine ---------------------------------------------------------------------------------------------
    (CPP,
     "        std::getenv(\"BB_VOLUMETRIC_CLOUDS_CONTRAST\")); // bbport (r119e_clouds-real-sky)\n",
     "        std::getenv(\"BB_VOLUMETRIC_CLOUDS_CONTRAST\"), // bbport (r119e_clouds-real-sky)\n"
     "        std::getenv(\"BB_VOLUMETRIC_CLOUDS_TINT\"), std::getenv(\"BB_VOLUMETRIC_CLOUDS_SMEAR\")); // bbport (r119g)\n"),
    (CPP,
     "constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? \"live knobs on\" : \"read at the start\";\n",
     "/// bbport (r119g_clouds-smear-and-cover): BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR now (live knobs with the test\n"
     "/// tools' header, asked again at every use), else the start's value.\n"
     "float LiveCover([[maybe_unused]] float at_start) {\n"
     "#if BB_CLOUD_LAYER_LIVE\n"
     "    static BbLiveKnobs::Knob<float> cover{\"BB_VOLUMETRIC_CLOUDS_COVER\", CL::ParseCover};\n"
     "    return cover.Get();\n"
     "#else\n"
     "    return at_start;\n"
     "#endif\n"
     "}\n"
     "\n"
     "float LiveTint([[maybe_unused]] float at_start) {\n"
     "#if BB_CLOUD_LAYER_LIVE\n"
     "    static BbLiveKnobs::Knob<float> tint{\"BB_VOLUMETRIC_CLOUDS_TINT\", CL::ParseTint};\n"
     "    return tint.Get();\n"
     "#else\n"
     "    return at_start;\n"
     "#endif\n"
     "}\n"
     "\n"
     "bool LiveSmear([[maybe_unused]] bool at_start) {\n"
     "#if BB_CLOUD_LAYER_LIVE\n"
     "    static BbLiveKnobs::Knob<bool> smear{\"BB_VOLUMETRIC_CLOUDS_SMEAR\", CL::ParseSmear};\n"
     "    return smear.Get();\n"
     "#else\n"
     "    return at_start;\n"
     "#endif\n"
     "}\n"
     "\n"
     "constexpr const char* LiveText = BB_CLOUD_LAYER_LIVE ? \"live knobs on\" : \"read at the start\";\n"),
    (CPP,
     "                     double(CL::LitScale(knobs.contrast)), LiveText);\n",
     "                     double(CL::LitScale(knobs.contrast)), LiveText);\n"
     "    // bbport (r119g_clouds-smear-and-cover): under 300 characters\n"
     "    BbReport::Printf(\"Volumetric clouds (r119g, BB_VOLUMETRIC_CLOUDS=1): smear fix %s (%d light taps, shade base %.2f, \"\n"
     "                     \"horizon glow %.2f), sky tint %.2f; BB_VOLUMETRIC_CLOUDS_COVER, _TINT and _SMEAR (%s)\\n\",\n"
     "                     knobs.smear ? \"on\" : \"off (BB_VOLUMETRIC_CLOUDS_SMEAR=0)\",\n"
     "                     knobs.smear ? CL::LightTaps : 1, double(knobs.smear ? CL::ShadeBase : CL::OldShadeBase),\n"
     "                     double(knobs.smear ? CL::HorizonGlow : 0.0f), double(knobs.tint), LiveText);\n"),
    (CPP,
     "    live.contrast = LiveContrast(knobs.contrast);\n"
     "    if (told_speed < 0.0f) {\n",
     "    live.contrast = LiveContrast(knobs.contrast);\n"
     "    // bbport (r119g_clouds-smear-and-cover): the cover, the tint and the smear fix, said once per change\n"
     "    live.cover = LiveCover(knobs.cover);\n"
     "    live.tint = LiveTint(knobs.tint);\n"
     "    live.smear = LiveSmear(knobs.smear);\n"
     "    if (told_cover < 0.0f) {\n"
     "        told_cover = live.cover;\n"
     "        told_tint = live.tint;\n"
     "        told_smear = live.smear ? 1 : 0;\n"
     "    } else if (live.cover != told_cover || live.tint != told_tint || (live.smear ? 1 : 0) != told_smear) {\n"
     "        told_cover = live.cover;\n"
     "        told_tint = live.tint;\n"
     "        told_smear = live.smear ? 1 : 0;\n"
     "        std::printf(\"Volumetric clouds (r119g): live knobs: cover %.2f, tint %.2f, smear fix %s\\n\", double(live.cover),\n"
     "                    double(live.tint), live.smear ? \"on\" : \"off\");\n"
     "    }\n"
     "    if (told_speed < 0.0f) {\n"),
    (CPP,
     "                     double(live.contrast));\n"
     "    stats = {};\n",
     "                     double(live.contrast));\n"
     "    BbReport::Printf(\"Volumetric clouds (r119g): cover %.2f, tint %.2f, smear fix %s\\n\", double(live.cover),\n"
     "                     double(live.tint), live.smear ? \"on\" : \"off\"); // bbport (r119g_clouds-smear-and-cover)\n"
     "    stats = {};\n"),
    (HDR,
     "    float told_speed = -1.0f, told_contrast = -1.0f; ///< bbport (r119e): the live speed and contrast said last (below 0: none yet)\n",
     "    float told_speed = -1.0f, told_contrast = -1.0f; ///< bbport (r119e): the live speed and contrast said last (below 0: none yet)\n"
     "    float told_cover = -1.0f, told_tint = -1.0f;     ///< bbport (r119g): the live cover and tint said last (below 0: none yet)\n"
     "    int told_smear = -1;                             ///< bbport (r119g): the live smear fix said last (-1: none yet)\n"),
    # ---- the test -----------------------------------------------------------------------------------------------
    (TEST,
     "        assert(ReportFramesLeast == 30u && ReportFramesMost == 3000u && FramesFirst < FramesPeriod);\n"
     "    }\n",
     "        assert(ReportFramesLeast == 30u && ReportFramesMost == 3000u && FramesFirst < FramesPeriod);\n"
     "    }\n"
     "    // n. (r119g_clouds-smear-and-cover) the cover, the tint and the smear fix: parsing, defaults, the Params slots.\n"
     "    {\n"
     "        assert(ParseCover(nullptr) == DefaultCover && ParseCover(\"0.3\") == 0.3f && ParseCover(\"9\") == 1.0f &&\n"
     "               ParseCover(\"-1\") == 0.0f && ParseCover(\"abc\") == DefaultCover);\n"
     "        assert(ParseTint(nullptr) == DefaultTint && ParseTint(\"0.5\") == 0.5f && ParseTint(\"7\") == 1.0f &&\n"
     "               ParseTint(\"x\") == DefaultTint && DefaultTint == 0.0f);\n"
     "        assert(ParseSmear(nullptr) && ParseSmear(\"\") && ParseSmear(\"1\") && ParseSmear(\"x\") && !ParseSmear(\"0\"));\n"
     "        const Knobs d = MakeKnobs(\"1\", nullptr, nullptr, nullptr, nullptr);\n"
     "        assert(d.tint == 0.0f && d.smear);\n"
     "        const Knobs t = MakeKnobs(\"1\", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,\n"
     "                                  nullptr, \"0.4\", \"0\");\n"
     "        assert(t.tint == 0.4f && !t.smear);\n"
     "        const std::array<float, 12> rows{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};\n"
     "        const std::array<float, 4> proj{1.0f, -1.0f, 1.0f, 0.1f};\n"
     "        const VolumetricFogNoise::Drift drift;\n"
     "        const std::array<float, 3> light = Unit(0.0f, 0.8f, 0.6f);\n"
     "        const std::array<float, 2> slope = CloudShadows::Slope(light);\n"
     "        const Params on = MakeParams(rows, proj, drift, d, light, true, slope, {0.0f, 0.0f});\n"
     "        assert(on.extra[0] == 0.0f && on.extra[1] == float(LightTaps) && on.extra[2] == ShadeBase &&\n"
     "               on.extra[3] == HorizonGlow && on.tone[2] == Desaturate);\n"
     "        const Params off = MakeParams(rows, proj, drift, t, light, true, slope, {0.0f, 0.0f});\n"
     "        assert(off.extra[0] == 0.4f && off.extra[1] == 1.0f && off.extra[2] == OldShadeBase && off.extra[3] == 0.0f);\n"
     "        assert(Near(off.tone[2], double(Desaturate) * 0.6, 1e-6)); // a tint of 0.4 leaves 60% of the desaturation\n"
     "        const Knobs full = MakeKnobs(\"1\", nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr,\n"
     "                                     nullptr, \"1\");\n"
     "        assert(MakeParams(rows, proj, drift, full, light, true, slope, {0.0f, 0.0f}).tone[2] == 0.0f);\n"
     "        assert(LightTaps == 2 && ShadeBase > OldShadeBase && OldShadeBase == 0.25f && HorizonGlow > 0.0f);\n"
     "    }\n"),
    # ---- README ---------------------------------------------------------------------------------------------------
    (README,
     "The shadows keep their own edges | `0.5` |",
     "The shadows keep their own edges. With the test tools' live knobs file it can be changed in a running game | `0.5` |"),
    (README,
     "| `BB_VOLUMETRIC_CLOUDS_DENSITY` |",
     "| `BB_VOLUMETRIC_CLOUDS_TINT` | 0 to 1: how much the clouds take the colour of the painted sky behind them. At `0` the shade side is the sky's tint pulled 55% toward grey and cooled and the lit side 27% toward grey (the look before this knob: grey and cream clouds); at `1` both are the sky's own colour, so over a dusk glow the clouds are dusk coloured and blend with it. A live knob with the test tools' live knobs file | `0` |\n"
     "| `BB_VOLUMETRIC_CLOUDS_SMEAR` | A test aid: `0` turns off the smear fix (the look before it, to compare in one game with the live knobs file). A dense cloud low over a bright horizon came out nearly black with hard edges, because the light was read with ONE density tap (its silhouette along the light showed) and the shade at a cloud's base was a quarter of the top's. With the fix on, the default: 2 jittered density taps toward the light, the shade at the base 0.45 of the top's and a horizon glow floor of 0.30 x opacity for rays near the horizon. Costs one more noise read per lit march step. Any text not starting with 0 is on | on |\n"
     "| `BB_VOLUMETRIC_CLOUDS_DENSITY` |"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the header, the code and the test agree."""
    params, cpp, readme, test, shader = texts[PARAMS], texts[CPP], texts[README], texts[TEST], texts[SHADER]
    for text in ("LightTaps = 2;", "ShadeBase = 0.45f;", "OldShadeBase = 0.25f;", "HorizonGlow = 0.30f;", "DefaultTint = 0.0f;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_SMEAR` |")]
    if len(rows) != 1 or "2 jittered" not in rows[0] or "0.45" not in rows[0] or "0.30" not in rows[0]:
        raise SystemExit("tie check: README SMEAR row against LightTaps, ShadeBase, HorizonGlow")
    rows = [l for l in readme.split("\n") if l.startswith("| `BB_VOLUMETRIC_CLOUDS_TINT` |")]
    if len(rows) != 1 or "55%" not in rows[0] or "27%" not in rows[0] or "| `0` |" not in rows[0]:
        raise SystemExit("tie check: README TINT row against Desaturate 0.55 and DefaultTint")
    if "Desaturate = 0.55f;" not in params:
        raise SystemExit("tie check: the README's 55% / 27% against Desaturate")
    for text in ("0.45 of its top's", "extra.y, .z, .w"):
        if text not in shader:
            raise SystemExit("tie check: the shader header text %r against ShadeBase" % text)
    if "offsetof(Params, extra) == 208" not in params or "vec4 extra;" not in shader:
        raise SystemExit("tie check: extra in the shader and in Params")
    if shader.count("BASE_AMBIENT") != 0:
        raise SystemExit("tie check: BASE_AMBIENT left in the shader")
    for name in ("BB_VOLUMETRIC_CLOUDS_COVER", "BB_VOLUMETRIC_CLOUDS_TINT", "BB_VOLUMETRIC_CLOUDS_SMEAR"):
        if cpp.count('"%s"' % name) < 1:
            raise SystemExit("tie check: %s not read in the engine" % name)
    if "ParseSmear(\"0\")" not in test or "ShadeBase > OldShadeBase" not in test:
        raise SystemExit("tie check: the test")
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119G_ROOT)" % ROOT)
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
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (is r119f applied? "
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
