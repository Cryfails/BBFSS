# r119d_clouds-contrast: FEATURE fix on top of r119c_clouds-gaps.fixed.py, r119b and r119 (BB_VOLUMETRIC_CLOUDS=1
# only; still off by default, still costs nothing when off: nothing here runs without the CloudLayer object, which
# Rasterizer makes only when BB_VOLUMETRIC_CLOUDS starts with 1).
#
# What was wrong (build 40, jobs r119c-lt / r119c-lts / r119c-gb): the coverage now has gaps (show view: magenta
# patches with green gaps; covered 0.70, visible 0.58, mean opacity 0.34) but in the normal picture the layer is a
# dim grey veil over the painted dusk sky: no distinct masses, no lit rims, no visible drift (on0 against on1 at
# the noise floor). The graveyard job never looked at real sky and printed no cloud line.
# Cause (read from the shader and checked with scratch r119d_sim_look.py, a python port of the march with the
# colour accumulation):
#  - COLOUR. The cloud's colour was the mean painted sky behind it, desaturated, times one ambient-plus-light
#    number: a cloud is the sky's own grey, only dimmer. The light term was almost never there: the light's path
#    through the cloud was weighed exp(-1.2 tau) with tau 10 to 16 for a full column, so only the very thin edge
#    was lit, and the lit rim (2.2 x sky at best) sat inside the sky's own brightness range.
#  - EDGES. smoothstep(0.49, 0.65, n) is a ramp over 0.16 of n: a soft grey transition, no edge.
#  - CORES. optical depth 2.8 of a full column, opacity capped at 0.70: even the core let 30% of the painted sky
#    through.
#  - DRIFT. 6 m/s at the layer is 0.2 degrees a second at 1500 m: invisible in two stills 2 s apart.
# Fix (all inside r119's own files; sim figures: sky of luminance 1, sun 22 degrees up, 36 views of the sky):
#  1. EDGES: LayerLow 0.49 / LayerHigh 0.65 -> 0.51 / 0.57 (a band of 0.06 of n: a smoothstep that reads as an
#     edge). Cover 0.5 keeps partial cover: sim 51% of the sky has cloud, 50% is clear gaps (0.52 / 0.52 before);
#     the cover knob still moves both edges by 0.3 x (0.5 - cover).
#  2. CORES: SigmaScale 4 -> 8 (a full column's optical depth 5.6) and OpacityCap 0.70 -> 0.92.
#  3. COLOUR AND LIGHT. The march now keeps the shade (ambient) and the lit light apart: shade colour = the sky's
#     tint desaturated 0.55 and cooled (x 0.88 0.94 1.06), at 0.25 of the ambient at the base up to the full
#     Ambient (0.50) at the top: a dark underside; lit colour = the sky's tint desaturated half as much (a sunset
#     rim stays warm, a moon rim stays pale), LightGain 2.2 -> 3.0 times the light's share times the transmission
#     toward the light, exp(-0.8 tau) + 0.25 exp(-0.2 tau) (a multi-scatter floor so a dense core keeps a faint
#     glow instead of black), times the phase 0.45 + Forward x (0.7 cos^4 + 0.3 cos^32), Forward 2.5 -> 3.0: a
#     bright rim and a forward glow near the light. A sky darker than 0.015 is treated as that grey. Sim: the
#     visible cloud pixels' brightness against the sky behind them (the old look: p5 0.47, p50 1.00, p95 1.87;
#     0.36 of them darker than 0.7 of the sky, 0.08 brighter than 1.4) is now p5 0.28, p50 1.33, p95 4.00 with
#     0.43 darker than 0.7 and 0.49 brighter than 1.4: two clear tones, dark undersides and bright rims, not a veil.
#  4. DRIFT: BB_VOLUMETRIC_CLOUDS_SPEED default 1 -> 6, and the one wind's cloud speed is held between
#     DriftFloor 2.5 and DriftCeil 8 m/s before it (the weather's calm state gives 1.6 m/s, its strong state
#     15 m/s): the layer drifts 15 to 48 m/s at the default, 0.8 to 2.6 degrees a second at 1000 m horizontal
#     distance, 1.6 to 5 degrees (20 to 60 px at 1280x720) in 2 s. The heading is still the wind's.
#  5. LOG: the first 600-frame line comes after 200 frames (a slow place such as the graveyard never reached 600 in a
#     55 s job: no line at all), then every 600; a fourth line (r119d) with the share of the visible cloud that is
#     darker than 0.7 of the sky behind it and the share brighter than 1.4 of it (two new counter words, 14 and 15;
#     proof of contrast in the numbers) and the speed; the knob line and the 600-frame line print the layer's real
#     speed.
# Cost: the march gets one more exp per lit step and one more image-colour multiply (about +3% of the march);
# denser cores end a ray's march sooner (T < 0.03), so a cloudy ray takes about the same steps or fewer: estimate
# 0.2 to 0.4 ms at 1080p internal with half the picture sky as r119c, 0.03 ms with no sky. Not measured; the
# counters add 2 words in the existing 16 (no new memory).
# Look constants are guesses, in cloud_layer_params.h and at the top of the shader.
#
# TOOL or FEATURE: FEATURE (same lane as r119).
# Edits r119's own files: cloud_layer_params.h, cloud_layer.comp, cloud_layer_layout.h, vk_cloud_layer.cpp/.h,
# tests/test_cloud_layer.cpp, README.md. No new file, no shared hook, no CMake change.
# Apply after r119, r119b and r119c; revert BEFORE r119c (their checks tie to text this patch changes).
#
# Use: python -I -X utf8 r119d_clouds-contrast.py check | apply | revert
# Root: R119D_ROOT, else <tree>. Line ends kept. Backups in r119d_backup next to this script.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r119d_backup")
ROOT = os.environ.get("R119D_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TMP = ".r119dtmp"

PARAMS = R + "cloud_layer_params.h"
SHADER = H + "cloud_layer.comp"
LAYOUT = H + "cloud_layer_layout.h"
CPP = R + "vk_cloud_layer.cpp"
HDR = R + "vk_cloud_layer.h"
TEST = "engine/tests/test_cloud_layer.cpp"
README = "README.md"

SHADER_NOTE = '''// bbport (r119d_clouds-contrast): readable clouds. The coverage edge is a narrow smoothstep (Params.cloud_off1.w to
// cloud_off2.w, 0.06 of n apart), the cores dense (opacity up to 0.92), the march keeps the shade (ambient, dark at
// the base) and the lit light (bright rim, forward glow, a multi-scatter floor) apart and colours them differently:
// the shade is the painted sky's tint desaturated and cooled, the lit light the sky's tint nearly as it is, at 3 x its
// brightness at the most near the light. The counters 14 and 15 say how much of the visible cloud ends darker than
// 0.7 or brighter than 1.4 of the sky behind it.
'''

SHADER_CONSTS = '''// bbport (r119d_clouds-contrast): the look (the march's; the composite build leaves them out)
#ifdef MARCH
const vec3 LUMA_W = vec3(0.2126, 0.7152, 0.0722);
const float BASE_AMBIENT = 0.25;   // the shade at a cloud's base, of its top's (Params.tone.x)
const float LIGHT_TAU = 0.8;       // the optical depth toward the light is weighed exp(-LIGHT_TAU tau) ...
const float MULTI_SCATTER = 0.25;  // ... plus this x exp(-0.2 tau): a dense core keeps a faint glow
const float LUM_FLOOR = 0.015;     // a sky darker than this counts as this grey
const vec3 SHADE_COOL = vec3(0.88, 0.94, 1.06); // the shade side is cooler than the sky
#endif
'''

SHADER_LOOP_OLD = '''    float T = 1.0, acc = 0.0;
    uint taken = 0u;
    for (int i = 0; i < steps; ++i) {
        ++taken;
        vec3 p = cam + dw * (t0 + (float(i) + jitter) * dt);
        float v;
        float dens = density_at(p, lod, v);
        if (dens <= 0.0) continue;
        float a = 1.0 - exp(-dens * dt);
        float lam = tone.x * mix(0.3, 1.0, v);
        if (light.w > 0.0 && a > 0.004) {
            float lp = min((top_y - p.y) / max(light.y, 0.15), 2.0 * slab.y);
            float unused;
            float dl = density_at(p + light.xyz * (0.5 * lp), lod, unused);
            lam += tone.y * light.w * exp(-dl * lp * 1.2) * (0.45 + tone.w * forward);
        }
        acc += T * a * lam;
        T *= 1.0 - a;
        if (T < 0.03) break;
    }
    vec3 tint = sky_sum / sky_n;
    tint = mix(tint, vec3(dot(tint, vec3(0.2126, 0.7152, 0.0722))), tone.z);
    float scale = fade * look.y;
    float alpha = (1.0 - T) * scale;
'''

SHADER_LOOP_NEW = '''    float T = 1.0, acc_amb = 0.0, acc_lit = 0.0; // bbport (r119d): the shade and the lit light kept apart
    uint taken = 0u;
    for (int i = 0; i < steps; ++i) {
        ++taken;
        vec3 p = cam + dw * (t0 + (float(i) + jitter) * dt);
        float v;
        float dens = density_at(p, lod, v);
        if (dens <= 0.0) continue;
        float a = 1.0 - exp(-dens * dt);
        acc_amb += T * a * tone.x * mix(BASE_AMBIENT, 1.0, v);
        if (light.w > 0.0 && a > 0.004) {
            float lp = min((top_y - p.y) / max(light.y, 0.15), 2.0 * slab.y);
            float unused;
            float dl = density_at(p + light.xyz * (0.5 * lp), lod, unused);
            float tau = dl * lp * LIGHT_TAU;
            float open_to_light = exp(-tau) + MULTI_SCATTER * exp(-0.2 * tau);
            acc_lit += T * a * tone.y * light.w * open_to_light * (0.45 + tone.w * forward);
        }
        T *= 1.0 - a;
        if (T < 0.03) break;
    }
    vec3 tint = sky_sum / sky_n;
    float sky_lum = dot(tint, LUMA_W);
    if (sky_lum < LUM_FLOOR) {
        tint = vec3(LUM_FLOOR);
        sky_lum = LUM_FLOOR;
    }
    vec3 grey = vec3(sky_lum);
    vec3 shade_col = mix(tint, grey, tone.z) * SHADE_COOL;
    vec3 lit_col = mix(tint, grey, 0.5 * tone.z);
    float scale = fade * look.y;
    float alpha = (1.0 - T) * scale;
    vec3 rgb = (shade_col * acc_amb + lit_col * acc_lit) * scale;
'''

SHADER_RET_OLD = '''    return vec4(tint * (acc * scale), alpha);
'''
SHADER_RET_NEW = '''    if (alpha >= float(CL_VISIBLE_ALPHA)) {
        // bbport (r119d): the picture's brightness over this sky against the sky alone (the mean of the block)
        float ratio = (1.0 - alpha) + dot(rgb, LUMA_W) / sky_lum;
        if (ratio < float(CL_DARK_RATIO)) {
            atomicAdd(group_counts[CL_WORD_DARK], 1u);
        } else if (ratio > float(CL_BRIGHT_RATIO)) {
            atomicAdd(group_counts[CL_WORD_BRIGHT], 1u);
        }
    }
    return vec4(rgb, alpha);
'''

LAYOUT_NEW = '''// bbport (r119d_clouds-contrast): of the visible sky pixels (opacity CL_VISIBLE_ALPHA or more) those whose picture is
// darker than CL_DARK_RATIO or brighter than CL_BRIGHT_RATIO of the sky behind them (the contrast proof)
#define CL_WORD_DARK 14u
#define CL_WORD_BRIGHT 15u
#define CL_DARK_RATIO 0.7
#define CL_BRIGHT_RATIO 1.4
'''

PARAMS_SPEED_OLD = "inline constexpr float DefaultSpeed = 1.0f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed\n"
PARAMS_SPEED_NEW = ("inline constexpr float DefaultSpeed = 6.0f;   ///< BB_VOLUMETRIC_CLOUDS_SPEED: times the one wind's cloud speed "
                    "(r119d: was 1)\n")
PARAMS_FLOOR_OLD = "inline constexpr float MinSpeed = 0.25f, MaxSpeed = 60.0f; ///< BB_VOLUMETRIC_CLOUDS_SPEED's clamp\n"
PARAMS_FLOOR_NEW = PARAMS_FLOOR_OLD + '''// bbport (r119d_clouds-contrast): the one wind's cloud speed is held between these (m/s) before the knob: the
// weather's calm state (1.6 m/s) would drift 0.1 degrees a second, too slow to see; 15 to 48 m/s at the default.
inline constexpr float DriftFloor = 2.5f, DriftCeil = 8.0f;
'''

PARAMS_LAYER_OLD = "inline constexpr float LayerLow = 0.49f, LayerHigh = 0.65f; ///< n's edges at cover 0.5 (clear below, full above)\n"
PARAMS_LAYER_NEW = ("inline constexpr float LayerLow = 0.51f, LayerHigh = 0.57f; ///< n's edges at cover 0.5 (clear below, full above; "
                    "r119d: a band of 0.06, was 0.49 / 0.65)\n")

PARAMS_WIND_OLD = '''inline std::array<float, 3> LayerWind(float heading_deg, float cloud_speed, const Knobs& k) {
    return CloudShadows::DriftVelocity(heading_deg, cloud_speed * k.speed, k.size);
}
'''
PARAMS_WIND_NEW = '''inline std::array<float, 3> LayerWind(float heading_deg, float cloud_speed, const Knobs& k) {
    return CloudShadows::DriftVelocity(heading_deg, LayerSpeed(cloud_speed, k), k.size);
}
'''
PARAMS_WIND_DOC_OLD = '''/// The layer's drift "wind" for VolumetricFogNoise::Drift::Advance:'''
PARAMS_WIND_DOC_NEW = '''/// bbport (r119d_clouds-contrast): the layer's speed (m/s): the one wind's cloud speed held between DriftFloor and
/// DriftCeil, times BB_VOLUMETRIC_CLOUDS_SPEED (a speed that is not a number counts as the floor).
inline float LayerSpeed(float cloud_speed, const Knobs& k) {
    return (cloud_speed > DriftFloor ? std::min(cloud_speed, DriftCeil) : DriftFloor) * k.speed;
}

/// The layer's drift "wind" for VolumetricFogNoise::Drift::Advance:'''

EDITS = [
    # ---- the shader
    (SHADER, "// lit rim and a forward glow toward the light.\n#version 450\n",
     "// lit rim and a forward glow toward the light.\n" + SHADER_NOTE + "#version 450\n"),
    (SHADER, "const float MAX_CHORD = 3000.0; // m: the longest stretch of a ray marched in the slab\n",
     "const float MAX_CHORD = 3000.0; // m: the longest stretch of a ray marched in the slab\n" + SHADER_CONSTS),
    (SHADER, SHADER_LOOP_OLD, SHADER_LOOP_NEW),
    (SHADER, SHADER_RET_OLD, SHADER_RET_NEW),
    # ---- the layout
    (LAYOUT, "#define CL_WORDS 16u\n", LAYOUT_NEW + "#define CL_WORDS 16u\n"),
    # ---- the header of the parameters
    (PARAMS, "// about 2.8 x density; the opacity is then capped (OpacityCap) so that the painted sky shows\n"
             "// through at the default.\n",
     "// about 5.6 x density (r119d; 2.8 before); the opacity is then capped (OpacityCap, 0.92) so that a core is dense\n"
     "// and only the thin edges show the painted sky through.\n"),
    (PARAMS, PARAMS_SPEED_OLD, PARAMS_SPEED_NEW),
    (PARAMS, PARAMS_FLOOR_OLD, PARAMS_FLOOR_NEW),
    (PARAMS, PARAMS_LAYER_OLD, PARAMS_LAYER_NEW),
    (PARAMS, "inline constexpr float SigmaScale = 4.0f;    ///< sigma = SigmaScale / thickness x density (1/m)\n",
     "inline constexpr float SigmaScale = 8.0f;    ///< sigma = SigmaScale / thickness x density (1/m) (r119d: was 4)\n"),
    (PARAMS, "inline constexpr float OpacityCap = 0.70f;   ///< the most opacity a ray's cloud gives\n",
     "inline constexpr float OpacityCap = 0.92f;   ///< the most opacity a ray's cloud gives (r119d: was 0.70)\n"),
    (PARAMS, "inline constexpr float LightGain = 2.2f;     ///< the lit share of a sample x this (x the phase)\n",
     "inline constexpr float LightGain = 3.0f;     ///< the lit share of a sample x this (x the phase) (r119d: was 2.2)\n"),
    (PARAMS, "inline constexpr float Forward = 2.5f;       ///< the forward scatter's gain (phase: 0.45 + this x (0.7 cos^4 + 0.3 cos^32))\n",
     "inline constexpr float Forward = 3.0f;       ///< the forward scatter's gain (phase: 0.45 + this x (0.7 cos^4 + 0.3 cos^32)) "
     "(r119d: was 2.5)\n"),
    (PARAMS, "inline constexpr std::uint32_t FramesPeriod = 600; ///< the periodic log line\n",
     "inline constexpr std::uint32_t FramesPeriod = 600; ///< the periodic log line\n"
     "inline constexpr std::uint32_t FramesFirst = 200;  ///< the first log line of a run (r119d: a slow place never reached 600)\n"),
    (PARAMS, "    double visible = 0.0; ///< sky pixels with an opacity of CL_VISIBLE_ALPHA or more / sky pixels (r119c)\n",
     "    double visible = 0.0; ///< sky pixels with an opacity of CL_VISIBLE_ALPHA or more / sky pixels (r119c)\n"
     "    double dark = 0.0;    ///< of the visible ones: picture darker than CL_DARK_RATIO of the sky behind (r119d)\n"
     "    double bright = 0.0;  ///< of the visible ones: picture brighter than CL_BRIGHT_RATIO of the sky behind (r119d)\n"),
    (PARAMS, "    s.visible = sky > 0.0 ? double(t.words[CL_WORD_VISIBLE]) / sky : 0.0;\n",
     "    s.visible = sky > 0.0 ? double(t.words[CL_WORD_VISIBLE]) / sky : 0.0;\n"
     "    const double vis = double(t.words[CL_WORD_VISIBLE]);\n"
     "    s.dark = vis > 0.0 ? double(t.words[CL_WORD_DARK]) / vis : 0.0; // bbport (r119d_clouds-contrast)\n"
     "    s.bright = vis > 0.0 ? double(t.words[CL_WORD_BRIGHT]) / vis : 0.0;\n"),
    (PARAMS, "static_assert(CL_WORD_VISIBLE == CL_WORD_Z_LAST + 1u && CL_WORD_VISIBLE < CL_WORDS && CL_VISIBLE_ALPHA == 0.25);\n",
     "static_assert(CL_WORD_VISIBLE == CL_WORD_Z_LAST + 1u && CL_WORD_VISIBLE < CL_WORDS && CL_VISIBLE_ALPHA == 0.25);\n"
     "static_assert(CL_WORD_DARK == CL_WORD_VISIBLE + 1u && CL_WORD_BRIGHT == CL_WORD_DARK + 1u &&\n"
     "              CL_WORD_BRIGHT < CL_WORDS && CL_DARK_RATIO == 0.7 && CL_BRIGHT_RATIO == 1.4); // bbport (r119d)\n"),
    (PARAMS, PARAMS_WIND_DOC_OLD, PARAMS_WIND_DOC_NEW),
    (PARAMS, PARAMS_WIND_OLD, PARAMS_WIND_NEW),
    # ---- the engine
    (HDR, "    bool told_no_place = false;\n", "    bool told_no_place = false;\n    bool reported_once = false; ///< bbport (r119d): the first log line comes after FramesFirst frames\n"),
    (CPP, "double(knobs.size), double(clk.Velocity() * knobs.speed),\n",
     "double(knobs.size), double(CL::LayerSpeed(clk.Velocity(), knobs)),\n"),
    (CPP, "    if (stats.frames >= CL::FramesPeriod) {\n        Report();\n    }\n",
     "    if (stats.frames >= (reported_once ? CL::FramesPeriod : CL::FramesFirst)) { // bbport (r119d): a first line early\n"
     "        Report();\n    }\n"),
    (CPP, "void CloudLayer::Report() {\n    const CL::Shares s = CL::SharesOf(totals);\n",
     "void CloudLayer::Report() {\n    reported_once = true;\n    const CL::Shares s = CL::SharesOf(totals);\n"),
    (CPP, "double(ClockState().Velocity(ClockKnobs()) * knobs.speed), double(knobs.size),\n",
     "double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), knobs)), double(knobs.size),\n"),
    (CPP, "                     double(CL::DepthEdges[4]), z[5], z[6], double(knobs.sky_z));\n    stats = {};\n    totals = {};\n}\n",
     "                     double(CL::DepthEdges[4]), z[5], z[6], double(knobs.sky_z));\n"
     "    // bbport (r119d_clouds-contrast): the contrast proof, under 300 characters\n"
     "    BbReport::Printf(\"Volumetric clouds (r119d): of the visible cloud pixels %.3f are darker than %.1f of the sky behind \"\n"
     "                     \"them and %.3f brighter than %.1f of it; edges %.2f-%.2f at cover %.2f, opacity cap %.2f, \"\n"
     "                     \"drift %.1f m/s\\n\",\n"
     "                     s.dark, double(CL_DARK_RATIO), s.bright, double(CL_BRIGHT_RATIO),\n"
     "                     double(CL::CoverEdges(CL::LayerLow, CL::LayerHigh, knobs.cover).low),\n"
     "                     double(CL::CoverEdges(CL::LayerLow, CL::LayerHigh, knobs.cover).high), double(knobs.cover),\n"
     "                     double(CL::OpacityCap),\n"
     "                     double(CL::LayerSpeed(ClockState().Velocity(ClockKnobs()), knobs)));\n"
     "    stats = {};\n    totals = {};\n}\n"),
    # ---- the test
    (TEST, "        // a full column straight up: optical depth about 2.8 x density at the defaults\n",
     "        // a full column straight up: optical depth about 5.6 x density at the defaults (r119d)\n"),
    (TEST, "d.size == 800.0f && d.speed == DefaultSpeed && d.speed == 1.0f);\n",
     "d.size == 800.0f && d.speed == DefaultSpeed && d.speed == 6.0f);\n"),
    (TEST, "        // march's noise gives clear 0.461, in between 0.353, full 0.186 (the shadows' 100 m size: the same\n"
           "        // shares, but a sky ray averages them out)\n",
     "        // march's noise gives (r119d edges 0.51 / 0.57) clear 1848, in between 520, full 1232 of the 3600 (r119c\n"
     "        // edges 0.49 / 0.65: 1659, 1270, 671)\n"),
    (TEST, "        assert(clear > 1260 && clear < 2090 && full > 360 && full < 1080 && partial > 720);\n",
     "        assert(clear > 1500 && clear < 2200 && full > 900 && full < 1550 && partial > 300 && partial < 760);\n"),
    (TEST, "nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, \"2\");\n",
     "nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, \"12\");\n"),
    (TEST, "        assert(Near(LayerWind(0.0f, 6.0f, d)[0], 6.0, 1e-5) && Near(LayerWind(0.0f, 6.0f, fast)[0], 12.0, 1e-5));\n",
     "        assert(Near(LayerWind(0.0f, 6.0f, d)[0], 36.0, 1e-4) && Near(LayerWind(0.0f, 6.0f, fast)[0], 72.0, 1e-4));\n"),
    (TEST, '    std::puts("cloud layer: ok");',
     '''    // k. (r119d_clouds-contrast) a narrow edge band, dense cores, a drift that shows in 2 s, the contrast counters.
    {
        const Knobs d = MakeKnobs("1", nullptr, nullptr, nullptr, nullptr);
        assert(LayerHigh > LayerLow && LayerHigh - LayerLow < 0.07f);
        assert(Near(Smoothstep(LayerLow, LayerHigh, 0.5f * (LayerLow + LayerHigh)), 0.5, 1e-5));
        assert(Smoothstep(LayerLow, LayerHigh, LayerLow) == 0.0f && Smoothstep(LayerLow, LayerHigh, LayerHigh) == 1.0f);
        assert(OpacityCap > 0.9f && SigmaScale >= 8.0f && LightGain > Ambient && Forward >= 3.0f);
        // the speed: the wind's cloud speed held between the floor and the ceiling, times the knob
        assert(LayerSpeed(0.0f, d) == DriftFloor * d.speed && LayerSpeed(1.6f, d) == DriftFloor * d.speed);
        assert(Near(LayerSpeed(6.0f, d), 36.0, 1e-4) && LayerSpeed(15.0f, d) == DriftCeil * d.speed);
        assert(LayerSpeed(std::nanf(""), d) == DriftFloor * d.speed);
        // at the slowest default a cloud 1000 m away moves more than 1.5 degrees in 2 s (about 20 px at 1280x720)
        assert(LayerSpeed(0.0f, d) * 2.0f / 1000.0f * 57.29578f > 1.5f);
        // the counters
        Totals t;
        std::array<std::uint32_t, CL_WORDS> frame{};
        frame[CL_WORD_SKY] = 400;
        frame[CL_WORD_VISIBLE] = 100;
        frame[CL_WORD_DARK] = 30;
        frame[CL_WORD_BRIGHT] = 50;
        t.Add(frame);
        const Shares s = SharesOf(t);
        assert(Near(s.dark, 0.3, 1e-9) && Near(s.bright, 0.5, 1e-9));
        assert(SharesOf(Totals{}).dark == 0.0 && SharesOf(Totals{}).bright == 0.0);
        assert(CL_WORD_DARK == 14u && CL_WORD_BRIGHT == 15u && CL_WORD_BRIGHT < CL_WORDS);
    }
    std::puts("cloud layer: ok");'''),
    # ---- the README
    (README, "turned 55% toward its grey), so they sit in the painting: dark on the underside, with a bright forward-scattered rim toward the light. They are thin and partial at the default (an opacity of at most 0.70), so the painted clouds show through,",
     "turned 55% toward its grey), so they sit in the painting: dark on the underside, with a bright forward-scattered rim toward the light. (r119d: the shade side and the lit side are coloured apart: the shade is the sky's tint turned 55% toward its grey and cooled, at a quarter of the ambient at the base up to its full value at the top; the lit light is the sky's tint turned 27% toward its grey, 3 times its brightness at the most near the light, weighed by how open the way toward the light is, with a faint floor for a dense core: dark undersides and bright rims against the painted sky.) A cloud is dense in its core (an opacity of at most 0.92) with a narrow edge band, so the clouds are separate masses and the painted sky shows through only at the thin edges and between them,"),
    (README, "edges smoothstep(0.49, 0.65, n) at cover 0.5, about half of the sky covered)",
     "edges smoothstep(0.51, 0.57, n) at cover 0.5, a band of 0.06 so an edge reads as an edge, about half of the sky covered)"),
    (README, "which says where a place's sky lies. Cost:",
     "which says where a place's sky lies, and a fourth (`r119d`) with the share of the visible cloud whose picture is darker than 0.7 of the sky behind it and the share brighter than 1.4 of it, the edges, the opacity cap and the speed (the first set of lines comes after 200 frames, then every 600). Cost:"),
    (README, "| `BB_VOLUMETRIC_CLOUDS_COVER` | 0 to 1. At `0.5` the layer's edges are smoothstep(0.49, 0.65, n): about half",
     "| `BB_VOLUMETRIC_CLOUDS_COVER` | 0 to 1. At `0.5` the layer's edges are smoothstep(0.51, 0.57, n): about half"),
    (README, "| `BB_VOLUMETRIC_CLOUDS_SPEED` | 0.25 to 60: times the one wind's cloud speed (`BB_WIND_SPEED` x 4, 6 m/s at the wind's default 1.5 m/s: 0.2 degrees a second at 1500 m, too slow to see in two stills). The heading is the wind's; the shapes morph slowly whatever the speed | `1` |",
     "| `BB_VOLUMETRIC_CLOUDS_SPEED` | 0.25 to 60: times the one wind's cloud speed (`BB_WIND_SPEED` x 4, or the weather's) held between 2.5 and 8 m/s first, so 15 to 48 m/s at the default: 0.8 to 2.6 degrees a second at 1000 m, 20 to 60 pixels in 2 s at 1280x720 (at 1 the layer drifted 1.6 to 15 m/s: too slow to see in two stills). The heading is the wind's; the shapes morph slowly whatever the speed | `6` |"),
    (README, "the density, sigma = 4 / thickness x density per metre (a full column straight up has an optical depth of about 2.8 at 1; the opacity of one ray is capped at 0.70 whatever the density)",
     "the density, sigma = 8 / thickness x density per metre (a full column straight up has an optical depth of about 5.6 at 1; the opacity of one ray is capped at 0.92 whatever the density)"),
]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    """Ties (rule 10): the README, the layout, the header and the shader agree."""
    params, layout, shader, readme = texts[PARAMS], texts[LAYOUT], texts[SHADER], texts[README]
    for text in ("LayerLow = 0.51f, LayerHigh = 0.57f;", "SigmaScale = 8.0f;", "OpacityCap = 0.92f;",
                 "DefaultSpeed = 6.0f;", "DriftFloor = 2.5f, DriftCeil = 8.0f;", "Ambient = 0.50f;",
                 "LightGain = 3.0f;", "Forward = 3.0f;", "Desaturate = 0.55f;"):
        if params.count(text) != 1:
            raise SystemExit("tie check: %s" % text)
    rows = {k: [l for l in readme.split("\n") if l.startswith("| `%s` |" % k)]
            for k in ("BB_VOLUMETRIC_CLOUDS_SPEED", "BB_VOLUMETRIC_CLOUDS_COVER", "BB_VOLUMETRIC_CLOUDS_DENSITY")}
    if any(len(v) != 1 for v in rows.values()):
        raise SystemExit("tie check: one README row each for SPEED, COVER and DENSITY")
    if "| `6` |" not in rows["BB_VOLUMETRIC_CLOUDS_SPEED"][0] or "between 2.5 and 8 m/s" not in rows["BB_VOLUMETRIC_CLOUDS_SPEED"][0]:
        raise SystemExit("tie check: README SPEED row against DefaultSpeed / DriftFloor / DriftCeil")
    if "smoothstep(0.51, 0.57, n)" not in rows["BB_VOLUMETRIC_CLOUDS_COVER"][0] or "0.49" in rows["BB_VOLUMETRIC_CLOUDS_COVER"][0]:
        raise SystemExit("tie check: README's edges 0.51, 0.57")
    if "sigma = 8 / thickness" not in rows["BB_VOLUMETRIC_CLOUDS_DENSITY"][0] or "capped at 0.92" not in rows["BB_VOLUMETRIC_CLOUDS_DENSITY"][0]:
        raise SystemExit("tie check: README DENSITY row against SigmaScale / OpacityCap")
    if "smoothstep(0.51, 0.57, n) at cover 0.5" not in readme or "smoothstep(0.49, 0.65" in readme:
        raise SystemExit("tie check: README's body edges")
    for define in ("#define CL_WORD_DARK 14u\n", "#define CL_WORD_BRIGHT 15u\n", "#define CL_DARK_RATIO 0.7\n",
                   "#define CL_BRIGHT_RATIO 1.4\n", "#define CL_WORDS 16u\n", "#define CL_WORD_VISIBLE 13u\n"):
        if layout.count(define) != 1:
            raise SystemExit("tie check: layout %s" % define.strip())
    for text in ("mix(BASE_AMBIENT, 1.0, v)", "const float BASE_AMBIENT = 0.25;", "CL_WORD_DARK", "CL_WORD_BRIGHT",
                 "return vec4(rgb, alpha);"):
        if shader.count(text) < 1:
            raise SystemExit("tie check: shader %s" % text)
    if "tint * (acc * scale)" in shader:
        raise SystemExit("tie check: the old return is still in the shader")
    if "5.6" not in readme or "r119d" not in readme:
        raise SystemExit("tie check: README's r119d text")
    if not all(ord(c) < 128 for _, _, new in EDITS for c in new):
        raise SystemExit("new text must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R119D_ROOT)" % ROOT)
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
            raise SystemExit("%s: %d of %d edits in place, %d ready to apply (are r119, r119b and r119c applied? "
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
