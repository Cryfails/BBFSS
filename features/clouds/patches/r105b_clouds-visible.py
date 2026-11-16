# r105b_clouds-visible: FEATURE patch on top of r105_cloud-shadows (order items "Foliage sway and
# clouds" and "Fog and wind go by cloud direction"). Off by default as r105 is (BB_CLOUD_SHADOWS
# unset or 0 and no BB_CLOUD_SHADOWS_SHOW=1: no CloudShadow is made, nothing below runs).
#
# Why: r105's default look (strength 1: a full cloud kept 55% of the sun or moon light, patches
# 160 m, edges 0.48-0.64) was not visible in stills (lead 21:37: graveyard-blood on vs off within
# the noise floor); only the SHOW look showed. With 160 m patches most 60 m views hold one even
# value (CPU sample, scratch r105b_noise_sim.py: only 21% of 60 m stretches of ground hold an edge
# of 0.30 of the light or more). And the drift had its own speed (6 m/s) and, without BB_WIND=1,
# its own direction ("auto", across the light), so fog, plants and cloud shadows did not share one
# wind.
#
# What changes (only r105's own new files and r105's README section; no shared hook line, no
# shader):
#  1. The default look (cloud_shadow_params.h): a full cloud keeps 40% (FullDepth 0.45 -> 0.60),
#     patches 100 m (DefaultScale 160 -> 100), edges 0.47-0.59 (were 0.48-0.64). Same noise sample:
#     41% of the ground clear, 25% under a full cloud, mean light kept 0.75 (was 0.84); 50% of 60 m
#     stretches hold an edge of 0.30 or more (was 21%); a fixed point changes by 0.15 or more within
#     10 s in 45% of cases (was 29%). SHOW is unchanged (keeps 15%, 70 m, edges 0.42-0.54).
#  2. One wind: the clouds travel at SpeedRatio (4) times the wind's mean speed (BB_WIND_SPEED,
#     else 1.5 m/s: 6 m/s, as r105), SHOW ShowSpeedRatio (10: 15 m/s, as r105); read by the wind's
#     own rule (r94's Number = r82's lambda, then BbWind::Sanitize) whether BB_WIND is on or not.
#     The direction: with BB_WIND=1 always the wind's at that frame (wander included) - BB_CLOUDS_DIR
#     is ignored then, so the sun fog's drift, the plants' sway and the cloud shadows go one way;
#     without it BB_CLOUDS_DIR's number, or "auto" (across the light, r105's rule), or by default
#     the direction the wind would blow (BB_WIND_DIR, else 225, with BbWind::WanderDeg on the
#     clouds' clock). Gusts do not move the clouds.
#  3. The once-line names the speed's source and the direction rule in force.
#  4. tests/test_cloud_shadows.cpp: the new rules (d, i, j, l).
#  5. README.md (r105's "Cloud shadows (in development)" section): the numbers and the direction row.
#
# Files: engine/gpu/shadps4/video_core/renderer_vulkan/cloud_shadow_params.h, vk_cloud_shadow.cpp,
# engine/tests/test_cloud_shadows.cpp, README.md. Not touched: vk_cloud_shadow.h, cloud_shadow.comp
# (its SPIR-V is unchanged), every shared hook (the frame end already passes the wind's on and
# direction to CloudShadow::OnFrameEnd).
#
# Cost: as r105 (the passes and their early outs are unchanged; the share of lit pixels written
# rises from about 58% to 59% because "clear" falls from 42% to 41%). Off: zero, as r105 (no
# CloudShadow; the hooks are null pointer tests). Memory: none.
#
# Order: apply after r105_cloud-shadows.fixed.py; revert r105b BEFORE r105 (r105's revert and check
# refuse while r105b's text is in its files: "exists and is not this patch's file").
#
# Review fixes (r105b_clouds-visible.fixed.py, 2026-11-15): (1) rule 10: StartDirection (225, "the
# wind's default") is now tied to BbWind::DefaultDirection by a static_assert, as the header can
# see bbport_wind.h; (2) rule 7: tests/test_cloud_shadows.cpp's comment b still said "160 m" (now
# 100 m). 27 edits.
#
# Use: python -I -X utf8 r105b_clouds-visible.fixed.py check | apply | revert. Root from
# R105B_CLOUDS_VISIBLE_ROOT (or R105B_ROOT), else <tree>. Files keep their line ends. apply
# keeps the edited files' originals in r105b_backup/ next to this script. Each edit is an exact
# text replacement whose old text must be found exactly once (and its new text not at all) to
# apply, and the reverse to revert.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r105b_backup")
ROOT = os.environ.get("R105B_CLOUDS_VISIBLE_ROOT") or os.environ.get("R105B_ROOT") or "<tree>"
R = "engine/gpu/shadps4/video_core/renderer_vulkan/"
PARAMS = R + "cloud_shadow_params.h"
CPP = R + "vk_cloud_shadow.cpp"
TEST = "engine/tests/test_cloud_shadows.cpp"
README = "README.md"
WIND = "engine/gpu/shim/bbport_wind.h"

EDITS = [
    # ---- cloud_shadow_params.h ----
    (PARAMS,
     "// spread (sd) of 0.13 (CPU probe of 60000 points, scratch r105_noise_sim.py); with the default\n"
     "// edges 44% of the ground is clear, 15% under a full cloud, 41% in between, and the mean light\n"
     "// kept at strength 1 is 0.85 of the sun term (with BB_CLOUD_SHADOWS_SHOW: 28% clear, 39% full,\n"
     "// mean 0.52).\n",
     "// spread (sd) of 0.13 (CPU probe of 60000 points, scratch r105_noise_sim.py); with the default\n"
     "// edges (r105b) 41% of the ground is clear, 25% under a full cloud, 34% in between, and the\n"
     "// mean light kept at strength 1 is 0.75 of the sun term (with BB_CLOUD_SHADOWS_SHOW: 28% clear,\n"
     "// 39% full, mean 0.53). r105b chose the size and edges by what a viewer sees (scratch\n"
     "// r105b_noise_sim.py, 1500 random 60 m stretches of ground): half of them hold an edge of 0.30\n"
     "// of the light or more (r105's 160 m, 0.48-0.64 and 0.45: a fifth, so its stills showed an\n"
     "// even dimming or none).\n"),
    (PARAMS,
     "// The drift: Drift (r94's, shared) is advanced with a \"wind\" of Speed m/s toward the clouds'\n"
     "// direction across xz and, in its third axis, a morph rate that moves the largest octave one\n"
     "// lattice cell every MorphSeconds (the finer ones 1.3 and 1.7 times as fast, divided by their\n"
     "// ratio, as Drift moves them), so the shapes change slowly while they pass.\n"
     "// The direction (deg, 0 = +x, 90 = +z, the way the clouds move, as the wind's): BB_CLOUDS_DIR\n"
     "// when it is a number; else, with BB_WIND=1, the wind's own direction at that frame (its wander\n"
     "// included); else \"auto\": across the light, atan2(L.z, L.x) + 90 deg (the clouds cross the moon\n"
     "// or sun sideways in the view toward it), eased toward that with an 8 s time constant along the\n"
     "// shorter arc. Which side \"+90\" is on screen is not checked (the handedness of the game's world).\n",
     "// The drift (r105b: one wind for the sun fog, the plants and the clouds): Drift (r94's, shared)\n"
     "// is advanced with a \"wind\" of SpeedRatio times the wind's mean speed (BB_WIND_SPEED, else\n"
     "// BbWind::DefaultSpeed, read by the rule of Rasterizer::WindOnFrameEnd: Number, then\n"
     "// BbWind::Sanitize, whether BB_WIND is on or not) toward the clouds' direction across xz and, in\n"
     "// its third axis, a morph rate that moves the largest octave one lattice cell every MorphSeconds\n"
     "// (the finer ones 1.3 and 1.7 times as fast, divided by their ratio, as Drift moves them), so\n"
     "// the shapes change slowly while they pass. The wind's gusts do not move the clouds.\n"
     "// The direction (deg, 0 = +x, 90 = +z, the way the clouds move, as the wind's): with BB_WIND=1\n"
     "// the wind's own direction at that frame (its wander included), whatever BB_CLOUDS_DIR says, so\n"
     "// the sun fog's drift, the plants' sway and the cloud shadows go one way; else BB_CLOUDS_DIR\n"
     "// when it is a number; else, when it is \"auto\", across the light, atan2(L.z, L.x) + 90 deg\n"
     "// (the clouds cross the moon or sun sideways in the view toward it), eased toward that with an\n"
     "// 8 s time constant along the shorter arc (which side \"+90\" is on screen is not checked: the\n"
     "// handedness of the game's world); else (missing or other text) the direction the wind would\n"
     "// blow: BB_WIND_DIR, else BbWind::DefaultDirection, with BbWind::WanderDeg's wander on the\n"
     "// clouds' own clock.\n"),
    (PARAMS,
     "#include <cstdint>\n"
     "#include <limits>\n"
     "\n"
     "#include \"volumetric_fog_noise.h\"\n"
     "\n"
     "namespace CloudShadows {\n",
     "#include <cstdint>\n"
     "#include <cstring> // bbport (r105b_clouds-visible): strcmp\n"
     "#include <limits>\n"
     "\n"
     "#include \"volumetric_fog_noise.h\"\n"
     "// bbport (r105b_clouds-visible): the shared wind's defaults, sanitizer and wander (a path\n"
     "// relative to this file, so the pure test still builds with -I. only)\n"
     "#include \"../../../shim/bbport_wind.h\"\n"
     "\n"
     "namespace CloudShadows {\n"),
    (PARAMS,
     "inline constexpr float FullDepth = 0.45f;      ///< share of the sun term a full cloud takes at strength 1\n"
     "inline constexpr float ShowDepth = 0.85f;      ///< BB_CLOUD_SHADOWS_SHOW=1: that share\n"
     "inline constexpr float DefaultScale = 160.0f;  ///< m: BB_CLOUD_SHADOWS_SCALE, the largest cells\n"
     "inline constexpr float ShowScale = 70.0f;      ///< m: the size with BB_CLOUD_SHADOWS_SHOW=1\n"
     "inline constexpr float MinScale = 40.0f, MaxScale = 600.0f; ///< BB_CLOUD_SHADOWS_SCALE's clamp\n"
     "inline constexpr float Low = 0.48f, High = 0.64f;         ///< n's edges (clear below, full above)\n"
     "inline constexpr float ShowLow = 0.42f, ShowHigh = 0.54f; ///< with BB_CLOUD_SHADOWS_SHOW=1\n"
     "inline constexpr float Speed = 6.0f;           ///< m/s: how fast the largest patches travel\n"
     "inline constexpr float ShowSpeed = 15.0f;      ///< m/s with BB_CLOUD_SHADOWS_SHOW=1\n",
     "// bbport (r105b_clouds-visible): FullDepth, DefaultScale, Low and High are r105b's (r105: 0.45,\n"
     "// 160 m, 0.48 and 0.64); the speeds are multiples of the wind's.\n"
     "inline constexpr float FullDepth = 0.60f;      ///< share of the sun term a full cloud takes at strength 1\n"
     "inline constexpr float ShowDepth = 0.85f;      ///< BB_CLOUD_SHADOWS_SHOW=1: that share\n"
     "inline constexpr float DefaultScale = 100.0f;  ///< m: BB_CLOUD_SHADOWS_SCALE, the largest cells\n"
     "inline constexpr float ShowScale = 70.0f;      ///< m: the size with BB_CLOUD_SHADOWS_SHOW=1\n"
     "inline constexpr float MinScale = 40.0f, MaxScale = 600.0f; ///< BB_CLOUD_SHADOWS_SCALE's clamp\n"
     "inline constexpr float Low = 0.47f, High = 0.59f;         ///< n's edges (clear below, full above)\n"
     "inline constexpr float ShowLow = 0.42f, ShowHigh = 0.54f; ///< with BB_CLOUD_SHADOWS_SHOW=1\n"
     "/// The largest patches travel at this many times the wind's mean speed (6 m/s at\n"
     "/// BbWind::DefaultSpeed, 1.5 m/s: clouds aloft move faster than the wind at the ground).\n"
     "inline constexpr float SpeedRatio = 4.0f;\n"
     "inline constexpr float ShowSpeedRatio = 10.0f; ///< with BB_CLOUD_SHADOWS_SHOW=1 (15 m/s at 1.5)\n"),
    (PARAMS,
     "/// BB_CLOUDS_DIR: true and the degrees wrapped into [0, 360) when it starts with a finite number;\n"
     "/// false (\"auto\") when missing, empty, \"auto\" or other text.\n"
     "inline bool ParseDirection(const char* text, float* deg) {\n"
     "    const float nan = std::numeric_limits<float>::quiet_NaN();\n"
     "    const float v = Number(text, nan);\n"
     "    if (!std::isfinite(v)) {\n"
     "        return false;\n"
     "    }\n"
     "    *deg = Wrap360(v);\n"
     "    return true;\n"
     "}\n"
     "\n"
     "struct Knobs {\n"
     "    float strength = 0.0f; ///< 0: off\n"
     "    float scale = DefaultScale;\n"
     "    bool show = false;\n"
     "    bool dir_set = false;  ///< BB_CLOUDS_DIR named a direction\n"
     "    float dir_deg = 0.0f;\n",
     "// bbport (r105b_clouds-visible): auto's start is the wind's default, tied (rule 10)\n"
     "static_assert(StartDirection == BbWind::DefaultDirection, \"the wind's default\");\n"
     "\n"
     "/// Where the clouds' direction comes from (r105b): the wind (BB_WIND=1, whatever BB_CLOUDS_DIR\n"
     "/// says), BB_CLOUDS_DIR's number, auto (BB_CLOUDS_DIR=auto), or the direction the wind would\n"
     "/// blow while BB_WIND is off (WindKnob).\n"
     "enum class Source : std::uint32_t { Env, Wind, Auto, WindKnob };\n"
     "\n"
     "inline const char* SourceName(Source s) {\n"
     "    return s == Source::Env    ? \"BB_CLOUDS_DIR\"\n"
     "           : s == Source::Wind ? \"the wind\"\n"
     "           : s == Source::Auto ? \"auto\"\n"
     "                               : \"the wind's direction, BB_WIND off\";\n"
     "}\n"
     "\n"
     "/// BB_CLOUDS_DIR: Env and the degrees wrapped into [0, 360) when it starts with a finite number;\n"
     "/// Auto when it is exactly \"auto\"; else (missing, empty or other text) WindKnob (r105b; r105\n"
     "/// took auto for all of these).\n"
     "inline Source ParseDirection(const char* text, float* deg) {\n"
     "    const float nan = std::numeric_limits<float>::quiet_NaN();\n"
     "    const float v = Number(text, nan);\n"
     "    if (std::isfinite(v)) {\n"
     "        *deg = Wrap360(v);\n"
     "        return Source::Env;\n"
     "    }\n"
     "    return text != nullptr && std::strcmp(text, \"auto\") == 0 ? Source::Auto : Source::WindKnob;\n"
     "}\n"
     "\n"
     "struct Knobs {\n"
     "    float strength = 0.0f; ///< 0: off\n"
     "    float scale = DefaultScale;\n"
     "    bool show = false;\n"
     "    Source dir = Source::WindKnob; ///< BB_CLOUDS_DIR: Env, Auto or WindKnob\n"
     "    float dir_deg = 0.0f;\n"
     "    /// r105b: the wind's base direction (deg) and mean speed (m/s) as Rasterizer::WindOnFrameEnd\n"
     "    /// reads them (BB_WIND_DIR, BB_WIND_SPEED), whether BB_WIND is on or not\n"
     "    float wind_deg = BbWind::DefaultDirection;\n"
     "    float wind_speed = BbWind::DefaultSpeed;\n"),
    (PARAMS,
     "    float Velocity() const {\n"
     "        return show ? ShowSpeed : Speed;\n"
     "    }\n",
     "    /// m/s: SpeedRatio (ShowSpeedRatio with SHOW) times the wind's mean speed (r105b)\n"
     "    float Velocity() const {\n"
     "        return wind_speed * (show ? ShowSpeedRatio : SpeedRatio);\n"
     "    }\n"),
    (PARAMS,
     "/// the shadows on at MaxStrength with the show look (ShowDepth, the show edges, ShowSpeed and,\n"
     "/// unless BB_CLOUD_SHADOWS_SCALE says otherwise, ShowScale), whatever BB_CLOUD_SHADOWS says.\n"
     "inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show, const char* dir) {\n"
     "    Knobs knobs;\n"
     "    knobs.show = show != nullptr && show[0] == '1';\n"
     "    knobs.strength = knobs.show ? MaxStrength : ParseStrength(strength);\n"
     "    knobs.scale = ParseScale(scale, knobs.show ? ShowScale : DefaultScale);\n"
     "    knobs.dir_set = ParseDirection(dir, &knobs.dir_deg);\n"
     "    return knobs;\n"
     "}\n",
     "/// the shadows on at MaxStrength with the show look (ShowDepth, the show edges, ShowSpeedRatio\n"
     "/// and, unless BB_CLOUD_SHADOWS_SCALE says otherwise, ShowScale), whatever BB_CLOUD_SHADOWS says.\n"
     "/// r105b: wind_dir and wind_speed are BB_WIND_DIR's and BB_WIND_SPEED's text, read as\n"
     "/// Rasterizer::WindOnFrameEnd reads them (Number with the wind's defaults, then BbWind::Sanitize:\n"
     "/// the direction wrapped into [0, 360), the speed clamped to 0-BbWind::MaxSpeed).\n"
     "inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show, const char* dir,\n"
     "                       const char* wind_dir = nullptr, const char* wind_speed = nullptr) {\n"
     "    Knobs knobs;\n"
     "    knobs.show = show != nullptr && show[0] == '1';\n"
     "    knobs.strength = knobs.show ? MaxStrength : ParseStrength(strength);\n"
     "    knobs.scale = ParseScale(scale, knobs.show ? ShowScale : DefaultScale);\n"
     "    knobs.dir = ParseDirection(dir, &knobs.dir_deg);\n"
     "    BbWind::Params wind{};\n"
     "    wind.on = true;\n"
     "    wind.direction_deg = Number(wind_dir, BbWind::DefaultDirection);\n"
     "    wind.speed = Number(wind_speed, BbWind::DefaultSpeed);\n"
     "    wind = BbWind::Sanitize(wind);\n"
     "    knobs.wind_deg = wind.direction_deg;\n"
     "    knobs.wind_speed = wind.speed;\n"
     "    return knobs;\n"
     "}\n"),
    (PARAMS,
     "enum class Source : std::uint32_t { Env, Wind, Auto };\n"
     "\n"
     "inline const char* SourceName(Source s) {\n"
     "    return s == Source::Env ? \"BB_CLOUDS_DIR\" : s == Source::Wind ? \"the wind\" : \"auto\";\n"
     "}\n"
     "\n"
     "/// The clouds' state",
     "// bbport (r105b_clouds-visible): Source and SourceName are above ParseDirection now.\n"
     "/// The clouds' state"),
    (PARAMS,
     "    /// One step of `seconds` (not finite: 0; clamped to 0-MaxStep). The direction: BB_CLOUDS_DIR,\n"
     "    /// else the wind's (wind_on), else auto from `light` (light_valid), eased (the first light\n"
     "    /// sets it at once); without a light auto keeps its last value. Then the drift moves.\n"
     "    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,\n"
     "                 const std::array<float, 3>& light, double seconds) {\n"
     "        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;\n"
     "        time += dt;\n"
     "        float target = 0.0f;\n"
     "        if (knobs.dir_set) {\n"
     "            source = Source::Env;\n"
     "            direction = knobs.dir_deg;\n"
     "        } else if (wind_on) {\n"
     "            source = Source::Wind;\n"
     "            direction = Wrap360(wind_deg);\n"
     "        } else {\n"
     "            source = Source::Auto;\n"
     "            if (light_valid && AutoDeg(light, &target)) {\n"
     "                direction = auto_known ? EaseDeg(direction, target, dt, EaseSeconds) : target;\n"
     "                auto_known = true;\n"
     "            }\n"
     "        }\n",
     "    /// One step of `seconds` (not finite: 0; clamped to 0-MaxStep). The direction (r105b): the\n"
     "    /// wind's (wind_on: BB_WIND=1; wind_deg its direction this frame), else BB_CLOUDS_DIR's\n"
     "    /// number, else with BB_CLOUDS_DIR=auto auto from `light` (light_valid), eased (the first\n"
     "    /// light sets it at once; without a light auto keeps its last value), else the wind's base\n"
     "    /// direction with BbWind::WanderDeg's wander at this state's time. Then the drift moves.\n"
     "    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,\n"
     "                 const std::array<float, 3>& light, double seconds) {\n"
     "        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;\n"
     "        time += dt;\n"
     "        float target = 0.0f;\n"
     "        if (wind_on) {\n"
     "            source = Source::Wind;\n"
     "            direction = Wrap360(wind_deg);\n"
     "        } else if (knobs.dir == Source::Env) {\n"
     "            source = Source::Env;\n"
     "            direction = knobs.dir_deg;\n"
     "        } else if (knobs.dir == Source::Auto) {\n"
     "            source = Source::Auto;\n"
     "            if (light_valid && AutoDeg(light, &target)) {\n"
     "                direction = auto_known ? EaseDeg(direction, target, dt, EaseSeconds) : target;\n"
     "                auto_known = true;\n"
     "            }\n"
     "        } else {\n"
     "            source = Source::WindKnob;\n"
     "            direction = Wrap360(BbWind::WanderDeg(time, knobs.wind_deg));\n"
     "        }\n"),
    # ---- vk_cloud_shadow.cpp ----
    (CPP,
     "                      std::getenv(\"BB_CLOUD_SHADOWS_SHOW\"), std::getenv(\"BB_CLOUDS_DIR\"));\n",
     "                      std::getenv(\"BB_CLOUD_SHADOWS_SHOW\"), std::getenv(\"BB_CLOUDS_DIR\"),\n"
     "                      std::getenv(\"BB_WIND_DIR\"), std::getenv(\"BB_WIND_SPEED\")); // r105b\n"),
    (CPP,
     "    BbReport::Printf(\"Cloud shadows (r105, BB_CLOUD_SHADOWS=%.2f%s): a full cloud keeps %.0f%% of \"\n"
     "                     \"the sun or moon light, clear below n %.2f, full above %.2f, size %.0f m, \"\n"
     "                     \"%.1f m/s toward %s; acts on the ray traced sun's (or VSM's) shadow \"\n"
     "                     \"target and the sun \"\n"
     "                     \"fog's ray traced gate only\\n\",\n"
     "                     double(knobs.strength), knobs.show ? \", SHOW\" : \"\",\n"
     "                     100.0 * (1.0 - double(knobs.Depth())), double(knobs.LowEdge()),\n"
     "                     double(knobs.HighEdge()), double(knobs.scale), double(knobs.Velocity()),\n"
     "                     knobs.dir_set ? \"BB_CLOUDS_DIR\" : \"the wind (BB_WIND=1) or auto\");\n",
     "    // bbport (r105b_clouds-visible): the speed is a multiple of the wind's; the direction is the\n"
     "    // wind's with BB_WIND=1 (read here as Rasterizer::WindOnFrameEnd reads it: starts with 1)\n"
     "    const char* wind_env = std::getenv(\"BB_WIND\");\n"
     "    const bool wind_on = wind_env != nullptr && wind_env[0] == '1';\n"
     "    BbReport::Printf(\"Cloud shadows (r105, BB_CLOUD_SHADOWS=%.2f%s): a full cloud keeps %.0f%% of \"\n"
     "                     \"the sun or moon light, clear below n %.2f, full above %.2f, size %.0f m, \"\n"
     "                     \"%.1f m/s (%.0fx the wind's %.2f m/s) toward %s; needs the ray traced sun \"\n"
     "                     \"or the VSM\\n\", // under 300 characters (the slot runs keep that much)\n"
     "                     double(knobs.strength), knobs.show ? \", SHOW\" : \"\",\n"
     "                     100.0 * (1.0 - double(knobs.Depth())), double(knobs.LowEdge()),\n"
     "                     double(knobs.HighEdge()), double(knobs.scale), double(knobs.Velocity()),\n"
     "                     double(knobs.show ? CS::ShowSpeedRatio : CS::SpeedRatio),\n"
     "                     double(knobs.wind_speed),\n"
     "                     wind_on ? \"the wind (BB_WIND=1; BB_CLOUDS_DIR ignored)\"\n"
     "                     : knobs.dir == CS::Source::Env  ? \"BB_CLOUDS_DIR\"\n"
     "                     : knobs.dir == CS::Source::Auto ? \"auto (across the light)\"\n"
     "                                                     : \"the wind's BB_WIND_DIR (wind off)\");\n"),
    # ---- tests/test_cloud_shadows.cpp ----
    (TEST,
     "//  b. BB_CLOUD_SHADOWS_SCALE: missing or not a number: 160 m (70 m with SHOW); clamped to 40-600.\n",
     "//  b. BB_CLOUD_SHADOWS_SCALE: missing or not a number: 100 m (r105b; 70 m with SHOW); clamped to\n"
     "//     40-600.\n"),
    (TEST,
     "//  d. BB_CLOUDS_DIR: a number (wrapped into [0, 360)) or auto (missing, empty, \"auto\", text).\n",
     "//  d. BB_CLOUDS_DIR: a number (wrapped into [0, 360)), \"auto\", or the wind's direction (missing,\n"
     "//     empty, other text) (r105b).\n"),
    (TEST,
     "//  i. The direction's source: BB_CLOUDS_DIR, then the wind, then auto; auto snaps to the first light,\n"
     "//     then eases, and keeps its value without a light.\n",
     "//  i. The direction's source (r105b): the wind (BB_WIND=1), then BB_CLOUDS_DIR's number, then auto,\n"
     "//     then the wind's BB_WIND_DIR with its wander; auto snaps to the first light, then eases, and\n"
     "//     keeps its value without a light.\n"),
    (TEST,
     "//  k. The push words: the Params block's order and the knobs in their slots.\n"
     "#include <array>\n",
     "//  k. The push words: the Params block's order and the knobs in their slots.\n"
     "//  l. The wind's knobs (r105b): BB_WIND_DIR and BB_WIND_SPEED read as the wind reads them; the\n"
     "//     clouds' speed is SpeedRatio (ShowSpeedRatio) times the wind's.\n"
     "#include <array>\n"),
    (TEST,
     "    assert(plain.LowEdge() == Low && plain.HighEdge() == High && plain.Velocity() == Speed);\n",
     "    assert(plain.LowEdge() == Low && plain.HighEdge() == High &&\n"
     "           Near(plain.Velocity(), SpeedRatio * BbWind::DefaultSpeed, 1e-6));\n"),
    (TEST,
     "           show.HighEdge() == ShowHigh && show.Velocity() == ShowSpeed);\n",
     "           show.HighEdge() == ShowHigh &&\n"
     "           Near(show.Velocity(), ShowSpeedRatio * BbWind::DefaultSpeed, 1e-6));\n"),
    (TEST,
     "    for (const char* autos : {static_cast<const char*>(nullptr), \"\", \"auto\", \"left\"}) {\n"
     "        assert(!MakeKnobs(\"1\", nullptr, nullptr, autos).dir_set);\n"
     "    }\n"
     "    assert(MakeKnobs(\"1\", nullptr, nullptr, \"90\").dir_set &&\n",
     "    for (const char* windy : {static_cast<const char*>(nullptr), \"\", \"left\", \"Auto\"}) {\n"
     "        assert(MakeKnobs(\"1\", nullptr, nullptr, windy).dir == Source::WindKnob);\n"
     "    }\n"
     "    assert(MakeKnobs(\"1\", nullptr, nullptr, \"auto\").dir == Source::Auto);\n"
     "    assert(MakeKnobs(\"1\", nullptr, nullptr, \"90\").dir == Source::Env &&\n"),
    (TEST,
     "        State s;\n"
     "        s.Advance(env, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);\n"
     "        assert(s.From() == Source::Env && s.Direction() == 30.0f);\n"
     "        State w;\n"
     "        w.Advance(plain, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);\n"
     "        assert(w.From() == Source::Wind && w.Direction() == 200.0f);\n"
     "        State a;\n"
     "        a.Advance(plain, false, 200.0f, false, {}, 0.05);\n"
     "        assert(a.From() == Source::Auto && a.Direction() == StartDirection);\n"
     "        a.Advance(plain, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.05); // first light: at once\n"
     "        assert(Near(a.Direction(), 90.0, 1e-4));\n"
     "        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 0.1); // eased toward 180\n"
     "        assert(a.Direction() > 90.0f && a.Direction() < 95.0f);\n"
     "        const float held = a.Direction();\n"
     "        a.Advance(plain, false, 0.0f, false, {}, 0.1); // no light: kept\n"
     "        assert(a.Direction() == held);\n"
     "        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, NAN); // no time: kept\n"
     "        assert(a.Direction() == held && Near(a.Time(), 0.3, 1e-9));\n"
     "        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 50.0); // clamped to MaxStep\n",
     "        State s; // r105b: with BB_WIND=1 the wind decides, whatever BB_CLOUDS_DIR says\n"
     "        s.Advance(env, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);\n"
     "        assert(s.From() == Source::Wind && s.Direction() == 200.0f);\n"
     "        State en;\n"
     "        en.Advance(env, false, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);\n"
     "        assert(en.From() == Source::Env && en.Direction() == 30.0f);\n"
     "        State w;\n"
     "        w.Advance(plain, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);\n"
     "        assert(w.From() == Source::Wind && w.Direction() == 200.0f);\n"
     "        // the wind off: the wind's base direction with its wander, at the state's own time\n"
     "        const Knobs blows = MakeKnobs(\"1\", nullptr, nullptr, nullptr, \"100\", nullptr);\n"
     "        State b;\n"
     "        for (int i = 0; i < 1200; ++i) { // 120 s\n"
     "            b.Advance(blows, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.1);\n"
     "            assert(b.From() == Source::WindKnob);\n"
     "            assert(Near(b.Direction(), BbWind::WanderDeg(b.Time(), 100.0f), 1e-3));\n"
     "            assert(DegGap(b.Direction(), 100.0) <= double(BbWind::Wander) + 1e-3);\n"
     "        }\n"
     "        const Knobs autok = MakeKnobs(\"1\", nullptr, nullptr, \"auto\");\n"
     "        State a;\n"
     "        a.Advance(autok, false, 200.0f, false, {}, 0.05);\n"
     "        assert(a.From() == Source::Auto && a.Direction() == StartDirection);\n"
     "        a.Advance(autok, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.05); // first light: at once\n"
     "        assert(Near(a.Direction(), 90.0, 1e-4));\n"
     "        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 0.1); // eased toward 180\n"
     "        assert(a.Direction() > 90.0f && a.Direction() < 95.0f);\n"
     "        const float held = a.Direction();\n"
     "        a.Advance(autok, false, 0.0f, false, {}, 0.1); // no light: kept\n"
     "        assert(a.Direction() == held);\n"
     "        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, NAN); // no time: kept\n"
     "        assert(a.Direction() == held && Near(a.Time(), 0.3, 1e-9));\n"
     "        a.Advance(autok, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 50.0); // clamped to MaxStep\n"),
    (TEST,
     "        const auto v = DriftVelocity(60.0f, Speed, 200.0f);\n"
     "        assert(Near(std::hypot(v[0], v[2]), Speed, 1e-4) && ",
     "        const auto v = DriftVelocity(60.0f, k.Velocity(), 200.0f); // r105b: the wind's x 4\n"
     "        assert(Near(k.Velocity(), SpeedRatio * BbWind::DefaultSpeed, 1e-6));\n"
     "        assert(Near(std::hypot(v[0], v[2]), k.Velocity(), 1e-4) && "),
    (TEST,
     "    std::puts(\"cloud shadows: ok\");\n"
     "    return 0;\n",
     "    // l. (r105b)\n"
     "    {\n"
     "        const Knobs a = MakeKnobs(\"1\", nullptr, nullptr, nullptr, \"90\", \"3\");\n"
     "        assert(a.wind_deg == 90.0f && a.wind_speed == 3.0f);\n"
     "        assert(Near(a.Velocity(), 3.0 * SpeedRatio, 1e-6));\n"
     "        const Knobs b = MakeKnobs(\"1\", nullptr, nullptr, nullptr, \"-30\", \"9\");\n"
     "        assert(Near(b.wind_deg, 330.0, 1e-4) && b.wind_speed == BbWind::MaxSpeed);\n"
     "        const Knobs c = MakeKnobs(\"1\", nullptr, nullptr, nullptr, \"east\", \"\");\n"
     "        assert(c.wind_deg == BbWind::DefaultDirection && c.wind_speed == BbWind::DefaultSpeed);\n"
     "        const Knobs d = MakeKnobs(\"1\", nullptr, nullptr, nullptr, \"nan\", \"-2\");\n"
     "        assert(d.wind_deg == BbWind::DefaultDirection && d.wind_speed == 0.0f);\n"
     "        assert(d.Velocity() == 0.0f);\n"
     "        const Knobs sh = MakeKnobs(nullptr, nullptr, \"1\", nullptr, nullptr, \"2\");\n"
     "        assert(Near(sh.Velocity(), 2.0 * ShowSpeedRatio, 1e-6));\n"
     "        // the wind's default speed gives r105's speeds (6 m/s, SHOW 15 m/s)\n"
     "        assert(Near(SpeedRatio * BbWind::DefaultSpeed, 6.0, 1e-6) &&\n"
     "               Near(ShowSpeedRatio * BbWind::DefaultSpeed, 15.0, 1e-6));\n"
     "    }\n"
     "    std::puts(\"cloud shadows: ok\"); // r105b: a to l\n"
     "    return 0;\n"),
    # ---- README.md (r105's section) ----
    (README,
     "on the ground and in the sun fog, as clouds passing over would, drifting across the place and slowly changing shape.",
     "on the ground and in the sun fog, as clouds passing over would, drifting with the wind (one direction for the sun fog's drift, the plants' sway and these shadows) and slowly changing shape."),
    (README,
     "multiplied by 1 - 0.45 s smoothstep(0.48, 0.64, n),",
     "multiplied by 1 - 0.6 s smoothstep(0.47, 0.59, n),"),
    (README,
     "At strength 1 about 44% of the ground is in the clear, 15% under a full cloud (0.55 of the light kept) and the rest in the soft edges; the mean light kept is 0.85 (from a sample of the noise, not measured in the game). The patches travel at 6 m/s and change shape over about 2 minutes.",
     "At strength 1 about 41% of the ground is in the clear, 25% under a full cloud (0.40 of the light kept) and the rest in the soft edges; the mean light kept is 0.75, and half of all 60 m stretches of ground hold an edge of 0.30 of the light or more (from a sample of the noise, not measured in the game). The patches travel at 4 times the wind's mean speed (6 m/s at the wind's default 1.5 m/s; `BB_WIND_SPEED`, read also without `BB_WIND=1`; gusts do not move them) and change shape over about 2 minutes."),
    (README,
     "| Size of the largest patches in metres, 40 to 600 | `160` (`70` with SHOW) |",
     "| Size of the largest patches in metres, 40 to 600 | `100` (`70` with SHOW) |"),
    (README,
     "patches 70 m across travelling at 15 m/s | off |",
     "patches 70 m across travelling at 10 times the wind's mean speed (15 m/s at 1.5 m/s) | off |"),
    (README,
     "| `BB_CLOUDS_DIR` | The direction the clouds move, in degrees (0 toward +x, 90 toward +z, as `BB_WIND_DIR`). Missing, `auto` or other text: with `BB_WIND=1` the wind's direction, else across the light (the light's direction across the ground plus 90 degrees, eased over about 8 s as the light turns) | `auto` |",
     "| `BB_CLOUDS_DIR` | Test only, and read only while `BB_WIND` is not 1: with `BB_WIND=1` the clouds always move the way the wind blows at that moment (`BB_WIND_DIR`, its slow wander included), so the sun fog, the plants and the cloud shadows go one way. Without it: a number is the direction the clouds move, in degrees (0 toward +x, 90 toward +z, as `BB_WIND_DIR`); `auto` is across the light (the light's direction across the ground plus 90 degrees, eased over about 8 s as the light turns); missing or other text is the direction the wind would blow (`BB_WIND_DIR`, else 225, with the same wander of up to 15 degrees) | the wind's |"),
]

# README numbers tied to the constants they state (rule 10), checked on the result: (file, the
# constant's text, README row prefix, the README text).
TIES = [(PARAMS, "FullDepth = 0.60f", "| `BB_CLOUD_SHADOWS` |", "1 - 0.6 s smoothstep"),
        (PARAMS, "FullDepth = 0.60f", "| `BB_CLOUD_SHADOWS` |", "(0.40 of the light kept)"),
        (PARAMS, "Low = 0.47f, High = 0.59f", "| `BB_CLOUD_SHADOWS` |", "smoothstep(0.47, 0.59, n)"),
        (PARAMS, "SpeedRatio = 4.0f", "| `BB_CLOUD_SHADOWS` |", "travel at 4 times the wind's mean speed"),
        (PARAMS, "DefaultScale = 100.0f", "| `BB_CLOUD_SHADOWS_SCALE` |", "| `100` (`70` with SHOW) |"),
        (PARAMS, "ShowSpeedRatio = 10.0f", "| `BB_CLOUD_SHADOWS_SHOW` |", "10 times the wind's mean speed"),
        (WIND, "DefaultSpeed = 1.5f", "| `BB_CLOUD_SHADOWS` |", "default 1.5 m/s"),
        (WIND, "DefaultSpeed = 1.5f", "| `BB_CLOUD_SHADOWS_SHOW` |", "(15 m/s at 1.5 m/s)"),
        (WIND, "DefaultDirection = 225.0f", "| `BB_CLOUDS_DIR` |", "else 225,"),
        (WIND, "Wander = 15.0f", "| `BB_CLOUDS_DIR` |", "up to 15 degrees"),
        (PARAMS, "EaseSeconds = 8.0", "| `BB_CLOUDS_DIR` |", "about 8 s"),
        (PARAMS, "AutoTurn = 90.0f", "| `BB_CLOUDS_DIR` |", "plus 90 degrees")]

TMP = ".r105btmp"


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def self_checks():
    for path, old, new in EDITS:
        if old in new or new in old:
            raise SystemExit("script fault: an edit's old and new text contain each other (%s)" % path)
        if not all(ord(c) < 128 for c in old + new) or "\r" in old + new:
            raise SystemExit("script fault: edit text must be ASCII with LF (%s)" % path)


def ties(texts):
    for path, const, row, value in TIES:
        src = texts[path] if path in texts else load(path)[2]
        line = [l for l in texts[README].split("\n") if l.startswith(row)]
        if src.count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %s %r against README row %r (%r)" % (path, const, row, value))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (see the header for the root variable)" % ROOT)
    self_checks()
    files = []
    for path, _, _ in EDITS:
        if path not in files:
            files.append(path)
    loaded = {p: load(p) for p in files}
    states = []
    for path, old, new in EDITS:
        cur = loaded[path][2]
        if cur.count(old) == 1 and cur.count(new) == 0:
            states.append("clean")
        elif cur.count(new) == 1 and cur.count(old) == 0:
            states.append("applied")
        else:
            raise SystemExit("%s: neither the old text nor this patch's text is found exactly once: %r"
                             % (path, old[:70]))
    if len(set(states)) != 1:
        raise SystemExit("mixed state: %d of %d edits applied" % (states.count("applied"), len(states)))
    state = states[0]

    def forward():
        texts = {p: loaded[p][2] for p in files}
        for path, old, new in EDITS:
            if texts[path].count(old) != 1:
                raise SystemExit("%s: old text not found exactly once: %r" % (path, old[:70]))
            texts[path] = texts[path].replace(old, new, 1)
        return texts

    def backward():
        texts = {p: loaded[p][2] for p in files}
        for path, old, new in reversed(EDITS):
            if texts[path].count(new) != 1:
                raise SystemExit("%s: this patch's text not found exactly once: %r" % (path, new[:70]))
            texts[path] = texts[path].replace(new, old, 1)
        return texts

    if cmd == "check":
        if state == "applied":
            ties({p: loaded[p][2] for p in files})
            backward()
            print("applied (ties pass; revert would restore %d edits in %d files)" % (len(EDITS), len(files)))
        else:
            texts = forward()
            ties(texts)
            print("not applied; would apply (%d edits in %d files; ties on the result pass)"
                  % (len(EDITS), len(files)))
        return
    if cmd == "apply" and state == "applied":
        print("already applied")
        return
    if cmd == "revert" and state == "clean":
        print("nothing to revert")
        return
    texts = forward() if cmd == "apply" else backward()
    if cmd == "apply":
        ties(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for p in files:
            open(os.path.join(BACKUP, p.replace("/", "__")), "wb").write(loaded[p][0])
    outs = [(p, texts[p].replace("\n", loaded[p][1]).encode("utf-8"), loaded[p][0]) for p in files]
    written = []
    try:
        for p, data, raw in outs:
            full = os.path.join(ROOT, p)
            open(full + TMP, "wb").write(data)
            os.replace(full + TMP, full)
            written.append((p, raw))
    except Exception:
        for p, _, _ in outs:
            if os.path.exists(os.path.join(ROOT, p) + TMP):
                os.remove(os.path.join(ROOT, p) + TMP)
        for p, raw in written:
            open(os.path.join(ROOT, p), "wb").write(raw)
        raise
    print("%s (%d edits in %d files)" % ("applied" if cmd == "apply" else "reverted", len(EDITS), len(files)))


main()
