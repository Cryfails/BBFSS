# r131b_lrt-settings: FEATURE patch (lane LRT, task LRT-T05 foliage for sun and lamps; water and blood).
# Owner words (goals.md): LRT-G043 (foliage for sun and lamps; the owner could use none of it from the menu or the launcher).
# Until now four LRT parts could be reached only by environment variables or had no menu row: the ray traced foliage shadows
# (BB_RT_CARD_ALPHA=2, BB_RT_CARD_LAMPS=1, BB_RT_CARD_SUN=1, read once at the start), the water motion (r130b: key and live read exist,
# no menu or launcher row), the blood sheen strength (r128d: key exists, no menu or launcher row) and the blood sheen colour
# (BB_BLOOD_SHEEN_TINT, a test knob of the live knobs header only). This patch makes them settings and rows.
#
# Keys (lantern.ini):
#  - graphics_rt_foliage_shadows: int 0 off, 1 lamps, 2 lamps and sun (sun and moon); default 0; RESTART (read once, from the start copy
#    BbSettings::startup_rt_foliage_shadows). One key, not two: the sun part cannot run without the lamp part. Out of range is the
#    nearest end, text is 0. The three variables win each for its own part when set and not empty (also "0" and text: off, as before):
#    BB_RT_CARD_ALPHA (the recompiler's level), BB_RT_CARD_LAMPS (RtShadow::CardLampsWanted), BB_RT_CARD_SUN (CardSunWanted).
#    One change: an EMPTY variable now falls to the setting (before it was off).
#  - graphics_water_motion_strength (r130b, 0..4, live) and graphics_blood_sheen (r128d, 0..4, a strength, restart): no engine change,
#    only the menu rows, the launcher rows and the launcher defaults. BB_WATER_MOTION and BB_BLOOD_SHEEN still win.
#  - graphics_blood_sheen_tint: int 0 grey test, 1 red, 2 clear film; default 1; LIVE (read per frame into the push flags). Text or a
#    number outside 0..2 is 1 (a line says so; the grey test view is never reached by accident). BB_BLOOD_SHEEN_TINT, set and not
#    empty, wins; in a build without the live knobs header it is now read once (before it was ignored there).
#
# Off = unchanged: every default is today's behaviour. No variable and no key: no card alpha, no lamp or sun cards, no blood sheen made,
# water motion 0, tint 1. The shaders are untouched (the builds' SPIR-V is byte-identical).
#
# Cost: settings only at default: ~0 ms. Per frame one relaxed load for the tint (the blood sheen's edit and show passes call TintMode,
# which exists only when a BloodSheen is made). Foliage is read three times at the start. Turned on, each key costs what its variable
# costs today (r62e / r63 / r128c; r130b / r130e; r128d); not measured again here. The foliage card ring is 24 MiB plus a 64 MiB pool.
#
# Log lines: "Ray traced foliage shadows (r131b): setting graphics_rt_foliage_shadows=N (off | lamps | lamps and sun); BB_RT_CARD_ALPHA
# <set: it decides | not set>, BB_RT_CARD_LAMPS ..., BB_RT_CARD_SUN ..." once, at the first CardAlphaLevel call; the r63 and r128c
# lines now name their source (the variable or "the setting graphics_rt_foliage_shadows=N"); "Blood sheen (r131b): tint N (grey test |
# red | clear film) from the setting (graphics_blood_sheen_tint) | the environment (BB_BLOOD_SHEEN_TINT)" at the first call and after a
# change of value or source (so only when a BloodSheen is made); CardSunNow's live knob: unset or empty = on (CardSunWanted decided),
# "0" off, "1" on.
#
# Menu and launcher: PictureSection gets the foliage combo (before the REFIT row), the water motion slider (after Water caustics) and a
# Blood sheen section (strength slider with a restart note, colour combo); the footer's restart test gets the two start copies. The
# launcher's Graphics > Lighting gets the four rows (both GraphicsPage.cs), IniFile.cs the four defaults, Choices.cs two lists, the 13
# localization json files and the 8 menu tables the new strings. Non-English texts are the ENGLISH text (decision of the lead,
# 2026-11-16: the owner reads English); the tree has no mark for untranslated text, so none is added: a translator finds the new
# entries as one block after each table's "Water caustics" rows and after the "Water caustics from the sun and moon" json line.
# README: two key rows and two paragraphs (the water motion and blood sheen keys already have their rows).
# The end markers "r131b: end ..." in bbport_overlay.cpp and both GraphicsPage.cs are the anchors a later patch (r131a foliage
# translucency) inserts after.
#
# Files: bbport_settings.h/.cpp, bbport_overlay.cpp, bbport_menu_i18n.cpp, cutout_analysis_pass.cpp, rt_card_uv.h, rt_card_sun.h,
# vk_rt_shadow.cpp, blood_sheen.h, vk_blood_sheen.cpp, test_settings.cpp, test_rt_card_uv.cpp, test_blood_sheen.cpp, launcher
# IniFile.cs, Choices.cs, both GraphicsPage.cs, 13 Localization json, README.md.
#
# Use: python -I -X utf8 r131b_lrt-settings.py check | apply | revert
# Root: R131B_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r131b_backup next to this script.
# Every edit inserts text before or after an anchor found exactly once (the anchor stays whole), or replaces a whole text found exactly
# once; revert takes out what apply inserted (each inserted block found by itself exactly once). Needs r128b, r128c, r128d, r130a and
# r130b applied (their constants and lines are the anchors; apply refuses without them, and refuses a tree with only part of r131b).
import io, json, os, re, sys

ROOT = os.environ.get("R131B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r131b_backup")
H = "engine/gpu/shadps4/video_core/renderer_vulkan/"
SH = "engine/gpu/shim/"
SETTINGS_H = SH + "bbport_settings.h"
SETTINGS_C = SH + "bbport_settings.cpp"
OVERLAY = SH + "bbport_overlay.cpp"
I18N = SH + "bbport_menu_i18n.cpp"
CUTOUT = "engine/gpu/shadps4/shader_recompiler/ir/passes/cutout_analysis_pass.cpp"
CARD_UV = H + "rt_card_uv.h"
CARD_SUN = H + "rt_card_sun.h"
RT_SHADOW = H + "vk_rt_shadow.cpp"
RT_SHADOW_H = H + "vk_rt_shadow.h"
BLOOD_H = H + "blood_sheen.h"
BLOOD_C = H + "vk_blood_sheen.cpp"
T_SETTINGS = "engine/tests/test_settings.cpp"
T_CARD_UV = "engine/tests/test_rt_card_uv.cpp"
T_BLOOD = "engine/tests/test_blood_sheen.cpp"
LW = "launcher/windows/"
GP_B = LW + "BloodborneLauncher/Views/GraphicsPage.cs"
GP_L = LW + "LanternLauncher/Views/GraphicsPage.cs"
INI = LW + "BloodborneLauncher/Core/IniFile.cs"
CHOICES = LW + "BloodborneLauncher/Core/Choices.cs"
LOC = LW + "BloodborneLauncher/Localization/"
README = "README.md"
LOC_CODES = ["de", "es", "fr", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "uk", "zh-CN", "zh-TW"]
TABLE_NAMES = ["kSpanish", "kPortugueseBrazil", "kFrench", "kGerman", "kItalian", "kPolish", "kTurkish", "kChinese"]

END_OVERLAY_FOLIAGE = "    // r131b: end of the foliage shadows row (a later row anchors after this line)\n"
END_OVERLAY_BLOOD = "    // r131b: end of the blood sheen rows (a later row anchors after this line)\n"
END_GP = "            // r131b: end (a later row anchors here)\n"

# ---------------------------------------------------------------- texts (English everywhere, see the header)
EN = {
    "fol_t": "Ray traced foliage shadows",
    "fol_c1": "Lamps",
    "fol_c2": "Lamps and sun",
    "fol_h": "Off by default. Applied when the game restarts. Leaves, weeds and other cut-out plants cast shadows in "
             "their true shape, with light through the gaps. Lamps: in Ray traced lamp shadows. Lamps and sun: also in "
             "Ray traced sun shadows (sun and moon). Costs GPU time and video memory while on.",
    "wm_t": "Water motion",
    "wm_h": "Live, off by default. The water surface moves in slow waves, with rings where the hunter steps. It shows "
            "where the game draws water as a mirror (the sewers). 0 is off, 1 is the intended look, up to 4 is "
            "stronger. Needs the upscaler: with none nothing is drawn.",
    "bs_t": "Blood sheen",
    "bs_h": "Off by default. Applied when the game restarts. Fresh blood on the ground gets a wet shine that catches "
            "lamp, sun and moon light. 0 is off, 1 is the intended look, up to 4 is stronger.",
    "bt_t": "Blood sheen colour",
    "bt_c0": "Grey (test)",
    "bt_c1": "Red",
    "bt_c2": "Clear",
    "bt_h": "Live, Red by default. The colour of the wet shine. Red is the look so far. Clear is a clear liquid film that "
            "keeps the colour of what it reflects (no pink moon glints). Grey is a test view.",
}
# every new string once per menu table ("Off" exists in the tables already; "Red" and "Clear" are not in them)
TABLE_KEYS = ["fol_t", "fol_c1", "fol_c2", "fol_h", "wm_t", "wm_h", "bs_t", "bs_h", "bt_t", "bt_c0", "bt_c1", "bt_c2", "bt_h"]
LOC_KEYS = ["fol_t", "fol_c1", "fol_c2", "wm_t", "bs_t", "bt_t", "bt_c0"]  # not in the json files yet ("Off", "Red", "Clear" are)
H2_PREFIX = '    {"Live, off by default. The same moving net from the light of the sun or moon'
LOC_ANCHOR_KEY = '  "Water caustics from the sun and moon": '


def cpp_lit(text, indent, width=84):
    """text as adjacent C++ string literals, one per line (the join is exactly the text)."""
    words = text.split(" ")
    pieces, cur = [], ""
    for i, w in enumerate(words):
        add = w + (" " if i < len(words) - 1 else "")
        if cur and len(cur) + len(add) > width:
            pieces.append(cur)
            cur = ""
        cur += add
    pieces.append(cur)
    assert "".join(pieces) == text and all('"' not in p and "\\" not in p for p in pieces)
    return "\n".join(" " * indent + '"' + p + '"' for p in pieces)


# ---------------------------------------------------------------- engine blocks
SETTINGS_H_CONST_ANCHOR = ("inline constexpr float WaterMotionStrengthMin = 0.0f, WaterMotionStrengthMax = 4.0f, "
                           "WaterMotionStrengthDefault = 0.0f;\n")
SETTINGS_H_CONST = (
    "// bbport (r131b_lrt-settings): the ray traced foliage shadows (graphics_rt_foliage_shadows: 0 off, 1 the lamps, 2 the lamps and the sun\n"
    "// and moon; restart; a set BB_RT_CARD_ALPHA, BB_RT_CARD_LAMPS or BB_RT_CARD_SUN wins for its own part) and the blood sheen's colour\n"
    "// (graphics_blood_sheen_tint: 0 grey test, 1 red, 2 clear film; live; a set BB_BLOOD_SHEEN_TINT wins). The colour is tied to\n"
    "// BloodSheenRules by a static_assert in vk_blood_sheen.cpp.\n"
    "inline constexpr int RtFoliageOff = 0, RtFoliageLamps = 1, RtFoliageLampsSun = 2, RtFoliageDefault = 0;\n"
    "inline constexpr int BloodSheenTintMin = 0, BloodSheenTintMax = 2, BloodSheenTintDefault = 1;\n")
SETTINGS_H_ATOMIC_ANCHOR = "    std::atomic<float> graphics_blood_sheen{BloodSheenDefault};\n"
SETTINGS_H_ATOMIC = (
    "    std::atomic<int> graphics_rt_foliage_shadows{RtFoliageDefault}; // 0 off, 1 lamps, 2 lamps and sun, bbport (r131b): restart\n"
    "    std::atomic<int> graphics_blood_sheen_tint{BloodSheenTintDefault}; // 0 grey test, 1 red, 2 clear film, bbport (r131b): live\n")
SETTINGS_H_START_ANCHOR = "    int startup_sun_far_shadows = SunFarGame; // bbport (r15_far-shadow-setting): what the hook uses\n"
SETTINGS_H_START = ("    int startup_rt_foliage_shadows = RtFoliageDefault; // bbport (r131b_lrt-settings): what the render code uses\n"
                    "    float startup_blood_sheen = BloodSheenDefault;     // bbport (r131b): for the menu's restart note\n")

SETTINGS_C_PARSE_ANCHOR = (
    '    } else if (key == "graphics_blood_sheen") { // bbport (r128d_lrt-sheen-interior)\n'
    '        v.graphics_blood_sheen = Clamp(std::isfinite(f) ? f : BloodSheenDefault, BloodSheenMin, BloodSheenMax);\n')
SETTINGS_C_PARSE = (
    '    } else if (key == "graphics_rt_foliage_shadows") { // bbport (r131b_lrt-settings)\n'
    '        v.graphics_rt_foliage_shadows = std::clamp(i, RtFoliageOff, RtFoliageLampsSun);\n'
    '    } else if (key == "graphics_blood_sheen_tint") {\n'
    '        if (value != "0" && value != "1" && value != "2") {\n'
    '            std::printf("Settings: unknown graphics_blood_sheen_tint \'%s\' (expected 0, 1 or 2); red\\n", value.c_str());\n'
    '        }\n'
    '        v.graphics_blood_sheen_tint = value == "0" ? 0 : value == "2" ? 2 : 1;\n')
SETTINGS_C_PUT_ANCHOR = '    put("graphics_blood_sheen", fixed(v.graphics_blood_sheen, 2)); // bbport (r128d_lrt-sheen-interior)\n'
SETTINGS_C_PUT = (
    '    put("graphics_rt_foliage_shadows", std::to_string(std::clamp(v.graphics_rt_foliage_shadows.load(), RtFoliageOff, RtFoliageLampsSun))); // bbport (r131b)\n'
    '    put("graphics_blood_sheen_tint", std::to_string(std::clamp(v.graphics_blood_sheen_tint.load(), BloodSheenTintMin, BloodSheenTintMax)));\n')
SETTINGS_C_START_ANCHOR = "    v.startup_sun_far_shadows = v.graphics_sun_far_shadows; // bbport (r15_far-shadow-setting)\n"
SETTINGS_C_START = ("    v.startup_rt_foliage_shadows = v.graphics_rt_foliage_shadows; // bbport (r131b_lrt-settings)\n"
                    "    v.startup_blood_sheen = v.graphics_blood_sheen;\n")

CARD_UV_ANCHOR = ("[[nodiscard]] constexpr bool CardAlphaMisread(const char* text) noexcept {\n"
                  "    return text && !((text[0] == '0' || text[0] == '1' || text[0] == '2') && text[1] == '\\0');\n"
                  "}\n")
CARD_UV_BLOCK = r"""// bbport (r131b_lrt-settings): the setting graphics_rt_foliage_shadows (0 off, 1 lamps, 2 lamps and sun) next to the variables. A variable
// that is set and not empty decides for its own part (also "0" and text: off); else the setting. Pure, so tests/test_rt_card_uv.cpp builds it.
[[nodiscard]] constexpr bool EnvGiven(const char* text) noexcept {
    return text != nullptr && text[0] != '\0';
}
/// BB_RT_CARD_ALPHA or, with none, the setting: 1 or 2 give the layers (2), 0 off.
[[nodiscard]] constexpr std::uint32_t CardAlphaOf(const char* env, int setting) noexcept {
    return EnvGiven(env) ? ReadCardAlpha(env) : setting >= 1 ? CardAlphaLayers : CardAlphaOff;
}
/// BB_RT_CARD_LAMPS (exactly "1" is on) or, with none, the setting 1 or 2.
[[nodiscard]] constexpr bool CardLampsOf(const char* env, int setting) noexcept {
    return EnvGiven(env) ? (env[0] == '1' && env[1] == '\0') : setting >= 1;
}
static_assert(EnvGiven("0") && EnvGiven("x") && !EnvGiven("") && !EnvGiven(nullptr));
static_assert(CardAlphaOf("0", 2) == CardAlphaOff && CardAlphaOf(nullptr, 1) == CardAlphaLayers && CardAlphaOf("", 2) == CardAlphaLayers &&
              CardAlphaOf("x", 2) == CardAlphaOff && CardAlphaOf(nullptr, 0) == CardAlphaOff && CardAlphaOf("1", 0) == CardAlphaUv);
static_assert(!CardLampsOf("0", 2) && CardLampsOf(nullptr, 1) && CardLampsOf("", 2) && !CardLampsOf("", 0) && CardLampsOf("1", 0) &&
              !CardLampsOf("x", 2) && !CardLampsOf(nullptr, 0));
"""

CARD_SUN_ANCHOR = ('static_assert(CardSunText("1") && !CardSunText("0") && !CardSunText("") && !CardSunText("11") && !CardSunText("on") &&\n'
                   '              !CardSunText(nullptr));\n')
CARD_SUN_BLOCK = r"""
/// bbport (r131b_lrt-settings): the sun side from BB_RT_CARD_SUN or, when that is unset or empty, the setting graphics_rt_foliage_shadows
/// (2 = lamps and sun). A variable that is set decides (also "0" and text: off).
constexpr bool CardSunOf(const char* env, int setting) {
    return env != nullptr && env[0] != '\0' ? CardSunText(env) : setting >= 2;
}
/// The live knob's reading (test builds): -1 unset or empty (CardSunWanted decided at the start: the variable or the setting), else 1 for
/// exactly "1" and 0 for the rest.
constexpr int CardSunLive(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : CardSunText(text) ? 1 : 0;
}
static_assert(CardSunOf("1", 0) && !CardSunOf("0", 2) && CardSunOf(nullptr, 2) && CardSunOf("", 2) && !CardSunOf(nullptr, 1) &&
              !CardSunOf("", 0) && !CardSunOf("on", 2));
static_assert(CardSunLive(nullptr) == -1 && CardSunLive("") == -1 && CardSunLive("1") == 1 && CardSunLive("0") == 0 && CardSunLive("on") == 0);
"""

CUTOUT_INC_ANCHOR = '#include "video_core/renderer_vulkan/rt_card_uv.h" // bbport (r54_leaf-stage2): ReadCardAlpha\n'
CUTOUT_INC = '#include "bbport_settings.h" // bbport (r131b_lrt-settings): the foliage setting\n'
CUTOUT_OLD = (
    '        if (Vulkan::CardAlphaMisread(env)) {\n'
    '            std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is not 0, 1 or 2: "\n'
    '                        "off\\n",\n'
    '                        env);\n'
    '        }\n'
    '        return Vulkan::ReadCardAlpha(env);\n')
CUTOUT_NEW = (
    '        // bbport (r131b_lrt-settings): a variable that is set and not empty decides; else the setting graphics_rt_foliage_shadows\n'
    '        // (the start copy: the three readers cannot disagree after a menu change). First call is after BbSettings::Load.\n'
    '        const int setting = BbSettings::Get().startup_rt_foliage_shadows;\n'
    '        if (Vulkan::EnvGiven(env) && Vulkan::CardAlphaMisread(env)) {\n'
    '            std::printf("Ray tracing card UVs (r54): BB_RT_CARD_ALPHA=%.16s is not 0, 1 or 2: "\n'
    '                        "off\\n",\n'
    '                        env);\n'
    '        }\n'
    '        {\n'
    '            const auto given = [](const char* name) {\n'
    '                return Vulkan::EnvGiven(std::getenv(name)) ? "set: it decides" : "not set";\n'
    '            };\n'
    '            std::printf("Ray traced foliage shadows (r131b): setting graphics_rt_foliage_shadows=%d (%s); BB_RT_CARD_ALPHA %s, "\n'
    '                        "BB_RT_CARD_LAMPS %s, BB_RT_CARD_SUN %s\\n",\n'
    '                        setting, setting >= 2 ? "lamps and sun" : setting == 1 ? "lamps" : "off", given("BB_RT_CARD_ALPHA"),\n'
    '                        given("BB_RT_CARD_LAMPS"), given("BB_RT_CARD_SUN"));\n'
    '        }\n'
    '        return Vulkan::CardAlphaOf(env, setting);\n')

LAMPS_OLD = (
    '        const char* const env = std::getenv("BB_RT_CARD_LAMPS");\n'
    '        if (!env) {\n'
    '            return false;\n'
    '        }\n'
    '        const bool one = std::strcmp(env, "1") == 0;\n'
    '        const bool layers = Shader::Optimization::CardAlphaLevel() == 2;\n'
    '        std::printf("Ray traced lamps (r63): BB_RT_CARD_LAMPS=%s: %s\\n", one ? "1" : "(not 1)",\n')
LAMPS_NEW = (
    '        const char* const env = std::getenv("BB_RT_CARD_LAMPS");\n'
    '        // bbport (r131b_lrt-settings): a variable that is set and not empty decides (also "0" and text); else the setting\n'
    '        // graphics_rt_foliage_shadows (the start copy) 1 or 2 turns it on. Neither: off, as with the variable unset.\n'
    '        const int setting = BbSettings::Get().startup_rt_foliage_shadows;\n'
    '        const bool from_env = EnvGiven(env);\n'
    '        if (!from_env && setting < 1) {\n'
    '            return false;\n'
    '        }\n'
    '        const bool one = CardLampsOf(env, setting);\n'
    '        const bool layers = Shader::Optimization::CardAlphaLevel() == 2;\n'
    '        char source[64];\n'
    '        if (from_env) {\n'
    '            std::snprintf(source, sizeof source, "BB_RT_CARD_LAMPS=%s", one ? "1" : "(not 1)");\n'
    '        } else {\n'
    '            std::snprintf(source, sizeof source, "the setting graphics_rt_foliage_shadows=%d", setting);\n'
    '        }\n'
    '        std::printf("Ray traced lamps (r63): %s: %s\\n", source,\n')
SUN_OLD = (
    '        const char* const env = std::getenv("BB_RT_CARD_SUN");\n'
    '        if (env == nullptr || *env == \'\\0\') {\n'
    '            return false;\n'
    '        }\n'
    '        const bool one = CardSunText(env);\n'
    '        const bool cards = one && CardLampsWanted();\n'
    '        const bool glass = RtGlassLightOn();\n'
    '        std::printf("Ray traced sun cut-outs (r128c): BB_RT_CARD_SUN=%s: %s\\n", env,\n')
SUN_NEW = (
    '        const char* const env = std::getenv("BB_RT_CARD_SUN");\n'
    '        // bbport (r131b_lrt-settings): a variable that is set and not empty decides; else the setting 2 (lamps and sun).\n'
    '        const int setting = BbSettings::Get().startup_rt_foliage_shadows;\n'
    '        const bool from_env = EnvGiven(env);\n'
    '        if (!from_env && setting < 2) {\n'
    '            return false;\n'
    '        }\n'
    '        const bool one = CardSunOf(env, setting);\n'
    '        const bool cards = one && CardLampsWanted();\n'
    '        const bool glass = RtGlassLightOn();\n'
    '        char source[96];\n'
    '        if (from_env) {\n'
    '            std::snprintf(source, sizeof source, "BB_RT_CARD_SUN=%.40s", env);\n'
    '        } else {\n'
    '            std::snprintf(source, sizeof source, "the setting graphics_rt_foliage_shadows=%d", setting);\n'
    '        }\n'
    '        std::printf("Ray traced sun cut-outs (r128c): %s: %s\\n", source,\n')
LIVE_OLD = (
    '    static BbLiveKnobs::Knob<bool> live{"BB_RT_CARD_SUN", [](const char* text) -> bool { return CardSunText(text); }};\n'
    '    static bool told_on = true;\n'
    '    const bool on = live.Get();\n')
LIVE_NEW = (
    '    // bbport (r131b_lrt-settings): unset or empty in the knobs file is -1 (CardSunWanted decided: the variable or the setting), so the\n'
    '    // setting\'s sun build runs in a slot build; "0" turns it off live, "1" on.\n'
    '    static BbLiveKnobs::Knob<int> live{"BB_RT_CARD_SUN", [](const char* text) -> int { return CardSunLive(text); }};\n'
    '    static bool told_on = true;\n'
    '    const int live_value = live.Get();\n'
    '    const bool on = live_value < 0 || live_value == 1;\n')

BLOOD_H_ANCHOR = "/// bbport (r130a_sheen-colour): BB_BLOOD_SHEEN_GLOSS and BB_BLOOD_SHEEN_LEVEL's text: a number into 0..1; unset, empty or other\n"
BLOOD_H_BLOCK = r"""/// bbport (r131b_lrt-settings): BB_BLOOD_SHEEN_TINT as the variable half of the setting rule: unset or empty: -1 (the setting decides),
/// else ReadTint (a variable that is set decides, also with text: 1).
inline int ReadTintEnv(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : ReadTint(text);
}
/// The tint in force: the variable's (0..2) when it is set and not empty (env >= 0), else the setting graphics_blood_sheen_tint into 0..2.
constexpr int TintOf(int env, int setting) {
    return env >= 0 ? env : std::clamp(setting, 0, 2);
}
"""
BLOOD_C_ANCHOR = ("static_assert(BbSettings::BloodSheenMax == R::MaxStrength && BbSettings::BloodSheenMin == 0.0f &&\n"
                  "              BbSettings::BloodSheenDefault == 0.0f);\n")
BLOOD_C_BLOCK = ("// bbport (r131b_lrt-settings): the colour setting's numbers are the film's three views (grey test, red, clear), red the default.\n"
                 "static_assert(BbSettings::BloodSheenTintMin == 0 && BbSettings::BloodSheenTintMax == 2 &&\n"
                 "              BbSettings::BloodSheenTintDefault == 1 && R::TintOf(-1, BbSettings::BloodSheenTintDefault) == 1);\n")
TINT_OLD = (
    'int TintMode() {\n'
    '#ifdef BLOOD_SHEEN_LIVE_PAUSE\n'
    '    static BbLiveKnobs::Knob<int> knob{"BB_BLOOD_SHEEN_TINT", R::ReadTint};\n'
    '    static int last = 1;\n'
    '    const int now = knob.Get();\n'
    '    if (now != last) {\n'
    '        last = now;\n'
    '        BbReport::Printf( // r130a\n'
    '            "Blood sheen (r130a): tint %s (BB_BLOOD_SHEEN_TINT %d)\\n",\n'
    '            now == 0 ? "off (untinted grey specular)" : (now == 2 ? "clear film (grey, dimming by redness)" : "r100i red"), now);\n'
    '    }\n'
    '    return now;\n'
    '#else\n'
    '    return 1;\n'
    '#endif\n'
    '}\n')
TINT_NEW = (
    'int TintMode() {\n'
    '    // bbport (r131b_lrt-settings): the variable (set and not empty: it decides) or else the setting graphics_blood_sheen_tint, read at\n'
    '    // every call (a relaxed load). Without the live knobs header the variable is read once (it was ignored there before).\n'
    '#ifdef BLOOD_SHEEN_LIVE_PAUSE\n'
    '    static BbLiveKnobs::Knob<int> knob{"BB_BLOOD_SHEEN_TINT", R::ReadTintEnv};\n'
    '    const int env = knob.Get();\n'
    '#else\n'
    '    static const int env = R::ReadTintEnv(std::getenv("BB_BLOOD_SHEEN_TINT"));\n'
    '#endif\n'
    '    const int now = R::TintOf(env, BbSettings::Get().graphics_blood_sheen_tint.load(std::memory_order_relaxed));\n'
    '#ifdef BLOOD_SHEEN_LIVE_PAUSE\n'
    '    static int last = 1;\n'
    '    if (now != last) {\n'
    '        last = now;\n'
    '        BbReport::Printf( // r130a\n'
    '            "Blood sheen (r130a): tint %s (BB_BLOOD_SHEEN_TINT %d)\\n",\n'
    '            now == 0 ? "off (untinted grey specular)" : (now == 2 ? "clear film (grey, dimming by redness)" : "r100i red"), now);\n'
    '    }\n'
    '#endif\n'
    '    static int told_value = -1, told_from_env = -1; // r131b: the first call and a change of value or source\n'
    '    const int from_env = env >= 0 ? 1 : 0;\n'
    '    if (now != told_value || from_env != told_from_env) {\n'
    '        told_value = now;\n'
    '        told_from_env = from_env;\n'
    '        BbReport::Printf( // r131b\n'
    '            "Blood sheen (r131b): tint %d (%s) from %s\\n", now, now == 0 ? "grey test" : (now == 2 ? "clear film" : "red"),\n'
    '            from_env != 0 ? "the environment (BB_BLOOD_SHEEN_TINT)" : "the setting (graphics_blood_sheen_tint)");\n'
    '    }\n'
    '    return now;\n'
    '}\n')


# ---------------------------------------------------------------- menu (overlay)
def hint(key):
    return "        Hint(BbSettings::MenuText(\n" + cpp_lit(EN[key], 12) + "));\n"


RESTART_NOTE = ('        if (%s != %s) {\n'
                '            ImGui::TextDisabled("%%s", BbSettings::MenuText("Applied when the game restarts.",\n'
                '                                                           "Применяется после перезапуска игры."));\n'
                '        }\n')

OVERLAY_A_ANCHOR = "    // bbport (r37_menu-options): BB_RT_REFIT_EVERY=8 as a setting."
OVERLAY_A = (
    "    // bbport (r131b_lrt-settings): the ray traced foliage shadows (BB_RT_CARD_ALPHA=2, BB_RT_CARD_LAMPS=1 and BB_RT_CARD_SUN=1 as one\n"
    "    // setting): 0 off, 1 the lamps, 2 the lamps and the sun and moon. Read once when the game starts (restart note). Each variable that\n"
    "    // is set and not empty decides for its own part (EnvNote).\n"
    '    if (const char* label = Item("%s")) {\n' % EN["fol_t"] +
    '        const char* names[] = {BbSettings::MenuText("Off"), BbSettings::MenuText("%s"),\n' % EN["fol_c1"] +
    '                               BbSettings::MenuText("%s")};\n' % EN["fol_c2"] +
    "        int mode = std::clamp(s.graphics_rt_foliage_shadows.load(), BbSettings::RtFoliageOff, BbSettings::RtFoliageLampsSun);\n"
    "        const bool changed = ImGui::Combo(label, &mode, names, BbSettings::RtFoliageLampsSun + 1);\n"
    "        Store(s.graphics_rt_foliage_shadows, mode, changed);\n" +
    hint("fol_h") +
    RESTART_NOTE % ("s.graphics_rt_foliage_shadows", "s.startup_rt_foliage_shadows") +
    '        EnvNote("BB_RT_CARD_ALPHA");\n'
    '        EnvNote("BB_RT_CARD_LAMPS");\n'
    '        EnvNote("BB_RT_CARD_SUN");\n'
    "    }\n" + END_OVERLAY_FOLIAGE)

OVERLAY_BC_ANCHOR = '        EnvNote("BB_CAUSTICS");\n    }\n'
OVERLAY_BC = (
    "    // bbport (r131b_lrt-settings): the moving water (r130b), live like the rows above; a set BB_WATER_MOTION wins over the slider\n"
    "    // (EnvNote). 0 is the default: off.\n"
    '    if (const char* label = Item("%s")) {\n' % EN["wm_t"] +
    "        Slider(label, s.graphics_water_motion_strength, BbSettings::WaterMotionStrengthMin,\n"
    '               BbSettings::WaterMotionStrengthMax, "%.2f", ImGuiSliderFlags_AlwaysClamp);\n' +
    hint("wm_h") +
    '        EnvNote("BB_WATER_MOTION");\n'
    "    }\n"
    "    // bbport (r131b_lrt-settings): the blood sheen: its strength (r128d: read once when the game starts, so a restart note; 0 is off,\n"
    "    // the default) and its colour (r130a: live). A set BB_BLOOD_SHEEN or BB_BLOOD_SHEEN_TINT wins over its row (EnvNote).\n"
    '    Section("%s");\n' % EN["bs_t"] +
    '    if (const char* label = Item("%s")) {\n' % EN["bs_t"] +
    '        Slider(label, s.graphics_blood_sheen, BbSettings::BloodSheenMin, BbSettings::BloodSheenMax, "%.2f",\n'
    "               ImGuiSliderFlags_AlwaysClamp);\n" +
    hint("bs_h") +
    RESTART_NOTE % ("s.graphics_blood_sheen", "s.startup_blood_sheen") +
    '        EnvNote("BB_BLOOD_SHEEN");\n'
    "    }\n"
    '    if (const char* label = Item("%s")) {\n' % EN["bt_t"] +
    '        const char* names[] = {BbSettings::MenuText("%s"), BbSettings::MenuText("%s"),\n' % (EN["bt_c0"], EN["bt_c1"]) +
    '                               BbSettings::MenuText("%s")};\n' % EN["bt_c2"] +
    "        int mode = std::clamp(s.graphics_blood_sheen_tint.load(), BbSettings::BloodSheenTintMin, BbSettings::BloodSheenTintMax);\n"
    "        const bool changed = ImGui::Combo(label, &mode, names, BbSettings::BloodSheenTintMax + 1);\n"
    "        Store(s.graphics_blood_sheen_tint, mode, changed);\n" +
    hint("bt_h") +
    '        EnvNote("BB_BLOOD_SHEEN_TINT");\n'
    "    }\n" + END_OVERLAY_BLOOD)

OVERLAY_D_ANCHOR = "        s.graphics_sun_far_shadows != s.startup_sun_far_shadows || // bbport (r15_far-shadow-setting)\n"
OVERLAY_D = ("        s.graphics_rt_foliage_shadows != s.startup_rt_foliage_shadows || // bbport (r131b_lrt-settings)\n"
             "        s.graphics_blood_sheen != s.startup_blood_sheen ||\n")

# ---------------------------------------------------------------- tests
T_SETTINGS_ANCHOR = "    // bbport (r128b_lrt-caustics-water): the water caustics' strengths. Nothing above sets them"
T_SETTINGS_BLOCK = r"""    // bbport (r131b_lrt-settings): graphics_rt_foliage_shadows (0, 1, 2; restart) and graphics_blood_sheen_tint (0, 1, 2; live). Nothing above
    // sets them: the defaults 0 and 1; written back; read (and the start copy); saved after a change; the foliage setting out of range is
    // the nearest end and text is 0; the tint setting out of range or text is 1 (never the grey test view). The water motion's and the
    // blood sheen's keys are tested elsewhere in this file (r130b, r128d).
    static_assert(BbSettings::RtFoliageOff == 0 && BbSettings::RtFoliageLamps == 1 && BbSettings::RtFoliageLampsSun == 2 &&
                  BbSettings::RtFoliageDefault == 0 && BbSettings::BloodSheenTintMin == 0 &&
                  BbSettings::BloodSheenTintMax == 2 && BbSettings::BloodSheenTintDefault == 1);
    assert(s.graphics_rt_foliage_shadows == BbSettings::RtFoliageDefault &&
           s.graphics_blood_sheen_tint == BbSettings::BloodSheenTintDefault);
    BbSettings::Save();
    assert(Read(path).find("graphics_rt_foliage_shadows=0\n") != std::string::npos &&
           Read(path).find("graphics_blood_sheen_tint=1\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_rt_foliage_shadows=2\n"
                                        "graphics_blood_sheen_tint=0\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_foliage_shadows == 2 && s.graphics_blood_sheen_tint == 0);
    assert(s.startup_rt_foliage_shadows == 2); // the start copy is taken at Load
    s.graphics_rt_foliage_shadows = 1;
    s.graphics_blood_sheen_tint = 2;
    BbSettings::Save();
    assert(Read(path).find("graphics_rt_foliage_shadows=1\n") != std::string::npos &&
           Read(path).find("graphics_blood_sheen_tint=2\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_rt_foliage_shadows=9\n"
                                        "graphics_blood_sheen_tint=9\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_foliage_shadows == BbSettings::RtFoliageLampsSun && s.graphics_blood_sheen_tint == 1);
    { std::ofstream file(path); file << "graphics_rt_foliage_shadows=-3\n"
                                        "graphics_blood_sheen_tint=-1\n"; }
    BbSettings::Load();
    assert(s.graphics_rt_foliage_shadows == BbSettings::RtFoliageOff && s.graphics_blood_sheen_tint == 1);
    { std::ofstream file(path); file << "graphics_rt_foliage_shadows=abc\n"
                                        "graphics_blood_sheen_tint=abc\n"; }
    s.graphics_rt_foliage_shadows = 2; // not the default before this Load
    s.graphics_blood_sheen_tint = 2;
    BbSettings::Load();
    assert(s.graphics_rt_foliage_shadows == BbSettings::RtFoliageDefault &&
           s.graphics_blood_sheen_tint == BbSettings::BloodSheenTintDefault);
    BbSettings::Save();
"""
T_CARD_UV_ANCHOR = '    CHECK(CardAlphaMisread("on"));\n'
T_CARD_UV_BLOCK = r"""    // bbport (r131b_lrt-settings): the setting graphics_rt_foliage_shadows next to the variables (a variable set and not empty decides)
    CHECK(EnvGiven("0") && EnvGiven("x") && !EnvGiven("") && !EnvGiven(nullptr));
    CHECK(CardAlphaOf("0", 2) == CardAlphaOff);                                  // the variable "0" with setting 2: off
    CHECK(CardAlphaOf(nullptr, 1) == CardAlphaLayers && CardAlphaOf(nullptr, 2) == CardAlphaLayers); // unset: the setting
    CHECK(CardAlphaOf(nullptr, 0) == CardAlphaOff && CardAlphaOf("", 0) == CardAlphaOff);
    CHECK(CardAlphaOf("", 2) == CardAlphaLayers);                                // an empty variable falls to the setting
    CHECK(CardAlphaOf("x", 2) == CardAlphaOff && CardAlphaOf("3", 2) == CardAlphaOff);
    CHECK(CardAlphaOf("1", 0) == CardAlphaUv && CardAlphaOf("2", 0) == CardAlphaLayers);
    CHECK(CardLampsOf(nullptr, 1) && CardLampsOf(nullptr, 2) && !CardLampsOf(nullptr, 0));
    CHECK(!CardLampsOf("0", 2) && CardLampsOf("1", 0) && CardLampsOf("", 1) && !CardLampsOf("", 0));
    CHECK(!CardLampsOf("x", 2) && !CardLampsOf("11", 2) && !CardLampsOf("true", 1));
"""
T_BLOOD_ANCHOR = '        assert(ReadTint("7") == 1 && ReadTint("x") == 1 && ReadTint(" 2 ") == 2 && ReadTint("20") == 1 && ReadTint("2x") == 1);\n'
T_BLOOD_BLOCK = r"""        // bbport (r131b_lrt-settings): the tint variable (unset or empty: -1, the setting decides) and the setting rule
        assert(ReadTintEnv(nullptr) == -1 && ReadTintEnv("") == -1 && ReadTintEnv("2") == 2 && ReadTintEnv("0") == 0);
        assert(ReadTintEnv("x") == 1 && ReadTintEnv("7") == 1 && ReadTintEnv(" 2 ") == 2);
        assert(TintOf(-1, 2) == 2 && TintOf(0, 2) == 0 && TintOf(-1, 9) == 2 && TintOf(-1, -4) == 0 && TintOf(2, 0) == 2);
        static_assert(TintOf(-1, 1) == 1 && TintOf(0, 1) == 0 && TintOf(1, 2) == 1);
"""

# ---------------------------------------------------------------- launcher, README
INI_ANCHOR = '            ("graphics_water_caustics_sun_strength", "0.00"),\n'
INI_BLOCK = ("            // r131b: the water motion, the blood sheen, the foliage shadows and the blood sheen colour, the engine's defaults\n"
             "            // (BbSettings::WaterMotionStrengthDefault, BloodSheenDefault, RtFoliageDefault, BloodSheenTintDefault).\n"
             '            ("graphics_water_motion_strength", "0.00"),\n'
             '            ("graphics_rt_foliage_shadows", "0"),\n'
             '            ("graphics_blood_sheen", "0.00"),\n'
             '            ("graphics_blood_sheen_tint", "1"),\n')
GP_ANCHOR = '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Water caustics from the sun and moon"), 4, "graphics_water_caustics_sun_strength", 0);\n'
GP_BLOCK = (
    "            // r131b: the water motion (live) and the blood sheen strength (read at the start), the ray traced foliage shadows\n"
    "            // (applied at the start) and the blood sheen colour (live); the in-game menu has the same rows.\n"
    '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Water motion"), 4, "graphics_water_motion_strength", 0);\n'
    '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Blood sheen"), 4, "graphics_blood_sheen", 0);\n'
    '            IniCombo(SymbolRegular.Lightbulb24, L.T("Ray traced foliage shadows"), L.T("Applied when the game starts"), Choices.RtFoliageShadows, "graphics_rt_foliage_shadows");\n'
    '            IniCombo(SymbolRegular.Lightbulb24, L.T("Blood sheen colour"), null, Choices.BloodSheenTint, "graphics_blood_sheen_tint");\n'
    + END_GP)
CHOICES_ANCHOR = "        public static readonly Choice[] FpsModes =\n"
CHOICES_BLOCK = (
    "        /// <summary>graphics_rt_foliage_shadows (r131b): the ray traced foliage shadows, 0 off, 1 the lamps, 2 the lamps and the sun and\n"
    "        /// moon. The engine reads it when the game starts; BB_RT_CARD_ALPHA, BB_RT_CARD_LAMPS and BB_RT_CARD_SUN win when set.</summary>\n"
    "        public static readonly Choice[] RtFoliageShadows =\n"
    "        {\n"
    '            new(L.T("Off"), "0"),\n'
    '            new(L.T("Lamps"), "1"),\n'
    '            new(L.T("Lamps and sun"), "2"),\n'
    "        };\n\n"
    "        /// <summary>graphics_blood_sheen_tint (r131b): the blood sheen's colour, live in the game: 0 the grey test view, 1 red (the\n"
    "        /// default, and what the engine reads for text it does not know), 2 the clear film.</summary>\n"
    "        public static readonly Choice[] BloodSheenTint =\n"
    "        {\n"
    '            new(L.T("Grey (test)"), "0"),\n'
    '            new(L.T("Red"), "1"),\n'
    '            new(L.T("Clear"), "2"),\n'
    "        };\n\n")

README_ROW_FOLIAGE_ANCHOR = "| `BB_RT_CARD_SUN` | FEATURE (r128c)"
README_ROW_FOLIAGE = (
    "| `graphics_rt_foliage_shadows` | `lantern.ini` key (r131b_lrt-settings): the ray traced foliage shadows as one setting, 0 to 2, read once "
    "when the game starts: `0` off (the default); `1` the lamps (as `BB_RT_CARD_ALPHA=2` with `BB_RT_CARD_LAMPS=1`); `2` the lamps and the sun "
    "and moon (also `BB_RT_CARD_SUN=1`). Each of the three variables, when set and not empty, decides for its own part instead of the key (also "
    "with `0` or text: off); the sun part stays off with `BB_RT_GLASS_LIGHT`, as before. A value outside the range is the nearest end, text "
    "that is no number is `0`. Menu: **Insert**, Ray traced foliage shadows (a restart note shows); launcher: Graphics > Lighting. The log has "
    "a `Ray traced foliage shadows (r131b)` line at the start, and the `Ray traced lamps (r63)` and `Ray traced sun cut-outs (r128c)` lines "
    "name the source. Cost: what the variables cost (the card ring is 24 MiB plus a 64 MiB pool at the first card) | `0` |\n")
README_ROW_TINT_ANCHOR = "| `BB_BLOOD_SHEEN_GLOSS` |"
README_ROW_TINT = (
    "| `graphics_blood_sheen_tint` | `lantern.ini` key (r131b_lrt-settings): the blood sheen's colour, live: `0` the grey test view, `1` red (the "
    "look so far), `2` the clear film (as `BB_BLOOD_SHEEN_TINT` describes). `BB_BLOOD_SHEEN_TINT`, when set and not empty, wins over it (a build "
    "without the test tools' live knobs header now reads it once; it was ignored there). A number outside 0 to 2 or text is `1`, and the log says "
    "so. Menu: Blood sheen colour; launcher: Graphics > Lighting. The log has a `Blood sheen (r131b)` line at the first use and after each "
    "change of value or source. Cost: one relaxed load a frame | `1` |\n")
README_PARA_WATER_ANCHOR = "### Water caustics (in development)\n"
README_PARA_WATER = (
    "\nThe moving water (r130b) has a slider too (r131b_lrt-settings): the `lantern.ini` key `graphics_water_motion_strength` (0 to 4, default `0`, "
    "off), in the in-game menu (**Insert**, row Water motion, live) and in the launcher (Graphics > Lighting). `BB_WATER_MOTION`, when set and "
    "not empty, wins over it.\n")
README_PARA_BLOOD_ANCHOR = "### Blood sheen (in development)\n"
README_PARA_BLOOD = (
    "\nThe strength (`graphics_blood_sheen`, 0 to 4, read once when the game starts) and the colour (`graphics_blood_sheen_tint`, 0 grey test, 1 red, "
    "2 clear film, live) are rows in the in-game menu (**Insert**, section Blood sheen; the strength row shows a restart note) and in the launcher "
    "(Graphics > Lighting) (r131b_lrt-settings). `BB_BLOOD_SHEEN` and `BB_BLOOD_SHEEN_TINT`, when set and not empty, win over them.\n")

# ---------------------------------------------------------------- the edit list
EDITS = []  # (path, kind, old, new, block)  kind: after | before | replace


def INS_AFTER(path, anchor, block):
    EDITS.append((path, "after", anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, "before", anchor, block + anchor, block))


def REPLACE(path, old, new):
    EDITS.append((path, "replace", old, new, new))


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        raise SystemExit("REFUSED: %s not found under %s" % (path, ROOT))
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def derived_line(text, start, where):
    """the one whole line (with its newline) that begins with `start` in text, else a refusal naming `where`"""
    hits = [m.group(0) for m in re.finditer(r"^" + re.escape(start) + r".*\n", text, re.M)]
    if len(hits) != 1:
        raise SystemExit("REFUSED: %s: the line %r found %d times (r128b not applied?)" % (where, start[:50], len(hits)))
    return hits[0]


def unique_table_keys():
    seen, out = set(), []
    for k in TABLE_KEYS:
        if EN[k] not in seen:
            seen.add(EN[k])
            out.append(k)
    return out


def build_edits():
    del EDITS[:]
    INS_AFTER(SETTINGS_H, SETTINGS_H_CONST_ANCHOR, SETTINGS_H_CONST)
    INS_AFTER(SETTINGS_H, SETTINGS_H_ATOMIC_ANCHOR, SETTINGS_H_ATOMIC)
    INS_AFTER(SETTINGS_H, SETTINGS_H_START_ANCHOR, SETTINGS_H_START)
    INS_AFTER(SETTINGS_C, SETTINGS_C_PARSE_ANCHOR, SETTINGS_C_PARSE)
    INS_AFTER(SETTINGS_C, SETTINGS_C_PUT_ANCHOR, SETTINGS_C_PUT)
    INS_AFTER(SETTINGS_C, SETTINGS_C_START_ANCHOR, SETTINGS_C_START)
    INS_AFTER(CARD_UV, CARD_UV_ANCHOR, CARD_UV_BLOCK)
    INS_AFTER(CARD_SUN, CARD_SUN_ANCHOR, CARD_SUN_BLOCK)
    INS_AFTER(CUTOUT, CUTOUT_INC_ANCHOR, CUTOUT_INC)
    REPLACE(CUTOUT, CUTOUT_OLD, CUTOUT_NEW)
    REPLACE(RT_SHADOW, LAMPS_OLD, LAMPS_NEW)
    REPLACE(RT_SHADOW, SUN_OLD, SUN_NEW)
    REPLACE(RT_SHADOW, LIVE_OLD, LIVE_NEW)
    INS_BEFORE(BLOOD_H, BLOOD_H_ANCHOR, BLOOD_H_BLOCK)
    INS_AFTER(BLOOD_C, BLOOD_C_ANCHOR, BLOOD_C_BLOCK)
    REPLACE(BLOOD_C, TINT_OLD, TINT_NEW)
    INS_BEFORE(OVERLAY, OVERLAY_A_ANCHOR, OVERLAY_A)
    INS_AFTER(OVERLAY, OVERLAY_BC_ANCHOR, OVERLAY_BC)
    INS_AFTER(OVERLAY, OVERLAY_D_ANCHOR, OVERLAY_D)
    i18n = load(I18N)[2]
    entries = "".join('    {"%s", "%s"},\n' % (EN[k], EN[k]) for k in unique_table_keys())
    for name in TABLE_NAMES:
        # a first comment line makes each table's block its own (the machinery wants every block found once in the file)
        block = "    // r131b_lrt-settings (%s): new strings, English until translated\n" % name + entries
        start = i18n.find("constexpr Entry %s[] = {" % name)
        if start < 0:
            raise SystemExit("REFUSED: %s: table %s not found" % (I18N, name))
        span = i18n[start:i18n.index("\n};", start)] + "\n"
        INS_AFTER(I18N, derived_line(span, H2_PREFIX, name), block)
    INS_AFTER(INI, INI_ANCHOR, INI_BLOCK)
    for gp in (GP_B, GP_L):
        INS_AFTER(gp, GP_ANCHOR, GP_BLOCK)
    INS_BEFORE(CHOICES, CHOICES_ANCHOR, CHOICES_BLOCK)
    for code in LOC_CODES:
        anchor = derived_line(load(LOC + code + ".json")[2], LOC_ANCHOR_KEY, code + ".json")
        INS_AFTER(LOC + code + ".json", anchor, "".join('  "%s": "%s",\n' % (EN[k], EN[k]) for k in LOC_KEYS))
    INS_BEFORE(T_SETTINGS, T_SETTINGS_ANCHOR, T_SETTINGS_BLOCK)
    INS_AFTER(T_CARD_UV, T_CARD_UV_ANCHOR, T_CARD_UV_BLOCK)
    INS_AFTER(T_BLOOD, T_BLOOD_ANCHOR, T_BLOOD_BLOCK)
    INS_BEFORE(README, README_ROW_FOLIAGE_ANCHOR, README_ROW_FOLIAGE)
    INS_BEFORE(README, README_ROW_TINT_ANCHOR, README_ROW_TINT)
    INS_AFTER(README, README_PARA_WATER_ANCHOR, README_PARA_WATER)
    INS_AFTER(README, README_PARA_BLOOD_ANCHOR, README_PARA_BLOOD)


# ---------------------------------------------------------------- machinery
def edits_of(path):
    return [e for e in EDITS if e[0] == path]


def state_of(path, text):
    eds = edits_of(path)
    done = sum(text.count(e[4]) == 1 and (e[1] != "replace" or text.count(e[2]) == 0) for e in eds)
    todo = sum(text.count(e[4]) == 0 and text.count(e[2]) == 1 for e in eds)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    bad = [e[2][:60] for e in eds
           if not ((text.count(e[4]) == 1 and (e[1] != "replace" or text.count(e[2]) == 0))
                   or (text.count(e[4]) == 0 and text.count(e[2]) == 1))]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d would apply; anchor or block not found once: %r"
                     % (path, done, len(eds), todo, bad))


def apply_text(path, text):
    for p, kind, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(block) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:60]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, kind, old, new, block in reversed(EDITS):
        if p != path:
            continue
        if text.count(block) != 1:
            raise SystemExit("REFUSED: %s: block found %d times: %r" % (path, text.count(block), block[:60]))
        text = text.replace(block, old if kind == "replace" else "", 1)
    return text


def table_span(text, name):
    start = text.index("constexpr Entry %s[] = {" % name)
    return text[start:text.index("\n};", start)]


def need(cond, message):
    if not cond:
        raise SystemExit("text check: " + message)


def text_checks(texts):
    # settings: each key once in the struct, the parse and the save; the start copies once
    st_h, st_c = texts[SETTINGS_H], texts[SETTINGS_C]
    for key in ("graphics_rt_foliage_shadows", "graphics_blood_sheen_tint"):
        need(st_h.count(key + "{") == 1 and st_c.count('key == "%s"' % key) == 1 and st_c.count('put("%s"' % key) == 1,
             "settings: %s not once in the struct, the parse and the save" % key)
    need(st_h.count("startup_rt_foliage_shadows = RtFoliageDefault") == 1 and st_h.count("startup_blood_sheen = BloodSheenDefault") == 1
         and st_c.count("v.startup_rt_foliage_shadows = ") == 1 and st_c.count("v.startup_blood_sheen = ") == 1,
         "settings: the start copies not once")
    # engine pieces (what the compiler would see first)
    uv, sun, cut, rt, bh, bc = (texts[p] for p in (CARD_UV, CARD_SUN, CUTOUT, RT_SHADOW, BLOOD_H, BLOOD_C))
    for text, needle, where in ((uv, "constexpr bool EnvGiven(", "rt_card_uv.h"), (uv, "constexpr std::uint32_t CardAlphaOf(", "rt_card_uv.h"),
                                (uv, "constexpr bool CardLampsOf(", "rt_card_uv.h"), (sun, "constexpr bool CardSunOf(", "rt_card_sun.h"),
                                (sun, "constexpr int CardSunLive(", "rt_card_sun.h"), (cut, "Vulkan::CardAlphaOf(env, setting)", "cutout"),
                                (cut, '#include "bbport_settings.h"', "cutout"), (rt, "CardLampsOf(env, setting)", "vk_rt_shadow.cpp"),
                                (rt, "CardSunOf(env, setting)", "vk_rt_shadow.cpp"), (rt, "CardSunLive(text)", "vk_rt_shadow.cpp"),
                                (bh, "inline int ReadTintEnv(", "blood_sheen.h"), (bh, "constexpr int TintOf(", "blood_sheen.h"),
                                (bc, "R::TintOf(env,", "vk_blood_sheen.cpp")):
        need(text.count(needle) == 1, "%s: %r not once" % (where, needle))
    need(bc.count("R::ReadTintEnv") == 2 and bc.count("Blood sheen (r131b): tint") == 1 and bc.count("Blood sheen (r130a): tint") == 2,
         "vk_blood_sheen.cpp: the tint reads or lines")
    need(rt.count("Ray traced lamps (r63): %s: %s") == 1 and rt.count("Ray traced sun cut-outs (r128c): %s: %s") == 1,
         "vk_rt_shadow.cpp: the r63 / r128c lines")
    need(cut.count("Ray traced foliage shadows (r131b)") == 1, "cutout: the r131b line")
    # the overlay: English text once (the title Blood sheen twice: section and row), variables once, markers once
    ov = texts[OVERLAY]
    joined = re.sub(r'"\s*\n\s*"', "", ov)
    for k, want in (("fol_t", 1), ("fol_h", 1), ("wm_t", 1), ("wm_h", 1), ("bs_t", 2), ("bs_h", 1), ("bt_t", 1), ("bt_h", 1),
                    ("bt_c0", 1), ("bt_c1", 1), ("bt_c2", 1), ("fol_c1", 1), ("fol_c2", 1)):
        need(joined.count('"%s"' % EN[k]) == want, "overlay: %r found %d times, want %d" % (EN[k][:40], joined.count('"%s"' % EN[k]), want))
    for env in ("BB_RT_CARD_ALPHA", "BB_RT_CARD_LAMPS", "BB_RT_CARD_SUN", "BB_WATER_MOTION", "BB_BLOOD_SHEEN", "BB_BLOOD_SHEEN_TINT"):
        need(ov.count('EnvNote("%s");' % env) == 1, "overlay: EnvNote(%s) not once" % env)
    need(ov.count(END_OVERLAY_FOLIAGE) == 1 and ov.count(END_OVERLAY_BLOOD) == 1, "overlay: the r131b end markers not once")
    need(ov.count("s.graphics_rt_foliage_shadows != s.startup_rt_foliage_shadows") == 2 and
         ov.count("s.graphics_blood_sheen != s.startup_blood_sheen") == 2, "overlay: restart tests (row note and footer) not twice")
    # the menu tables: each new string once in every table (English text, see the header)
    i18n = texts[I18N]
    for name in TABLE_NAMES:
        span = table_span(i18n, name)
        for k in unique_table_keys():
            need(span.count('{"%s"' % EN[k]) == 1 and span.count('    {"%s", "%s"},\n' % (EN[k], EN[k])) == 1,
                 "%s: %r not found exactly once" % (name, EN[k][:40]))
    for k in unique_table_keys():
        need(i18n.count('{"%s"' % EN[k]) == 8, "%r is not in all 8 tables" % EN[k][:40])
    # launcher
    for path in (GP_B, GP_L):
        t = texts[path]
        for needle in ('L.T("Water motion"), 4, "graphics_water_motion_strength", 0);',
                       'L.T("Blood sheen"), 4, "graphics_blood_sheen", 0);',
                       'Choices.RtFoliageShadows, "graphics_rt_foliage_shadows");',
                       'Choices.BloodSheenTint, "graphics_blood_sheen_tint");'):
            need(t.count(needle) == 1, "%s: row %r not once" % (path, needle))
        need(t.count(END_GP) == 1, "%s: the r131b end marker not once" % path)
    ini = texts[INI]
    for key, val in (("graphics_water_motion_strength", "0.00"), ("graphics_rt_foliage_shadows", "0"),
                     ("graphics_blood_sheen", "0.00"), ("graphics_blood_sheen_tint", "1")):
        need(ini.count('("%s", "%s"),' % (key, val)) == 1, "IniFile.cs default %s" % key)
    ch = texts[CHOICES]
    need(ch.count("Choice[] RtFoliageShadows") == 1 and ch.count("Choice[] BloodSheenTint") == 1, "Choices.cs lists")
    zh = json.loads(texts[LOC + "zh-CN.json"])
    for code in LOC_CODES:
        data = json.loads(texts[LOC + code + ".json"])
        for k in LOC_KEYS:
            need(data.get(EN[k]) == EN[k], "%s.json: %r wrong or missing" % (code, EN[k]))
            need(EN[k] in zh, "zh-CN.json lacks %r (the reference for the code's strings)" % EN[k])
    # the new texts are plain ASCII (the tables and json carry English)
    need(all(ord(c) < 0x80 for k in TABLE_KEYS for c in EN[k]), "a new English text is not ASCII")
    # README
    rd = texts[README]
    for key in ("graphics_rt_foliage_shadows", "graphics_blood_sheen_tint"):
        need(rd.count("| `%s` |" % key) == 1, "README: row %s not once" % key)
    need(rd.count("(r131b_lrt-settings)") >= 4, "README: the four r131b texts")
    # tests
    need(texts[T_SETTINGS].count("graphics_rt_foliage_shadows=2\\n") == 1 and texts[T_CARD_UV].count("CardAlphaOf(") >= 8 and
         texts[T_BLOOD].count("ReadTintEnv(") >= 4, "tests: the r131b blocks")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R131B_ROOT)" % ROOT)
    needs = {SETTINGS_H: ("WaterCausticsStrengthDefault", "r128b_lrt-caustics-water"),
             RT_SHADOW_H: ("CardSunWanted", "r128c_lrt-cutout-props"),
             BLOOD_H: ("ReadTint", "r130a_sheen-colour")}
    for path, (needle, name) in needs.items():
        if needle not in load(path)[2]:
            raise SystemExit("REFUSED: %s is not applied (%s lacks %s): apply it first" % (name, path, needle))
    if "BloodSheenDefault" not in load(SETTINGS_H)[2]:
        raise SystemExit("REFUSED: r128d_lrt-sheen-interior is not applied (bbport_settings.h lacks BloodSheenDefault)")
    if "graphics_water_motion_strength" not in load(SETTINGS_H)[2]:
        raise SystemExit("REFUSED: r130b_water-moves is not applied (bbport_settings.h lacks graphics_water_motion_strength)")
    build_edits()
    paths = []
    for e in EDITS:
        if e[0] not in paths:
            paths.append(e[0])
    plan = []
    for path in paths:
        raw, eol, cur = load(path)
        plan.append((path, raw, eol, cur, state_of(path, cur)))
    states = {p[4] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED: mixed state (a tree with part of r131b): " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[3] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks({p[0]: apply_text(p[0], p[3]) for p in plan})
            print("not applied; would apply (%d files edited, %d edits; every anchor found once; text checks "
                  "on the result pass)" % (len(plan), len(EDITS)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, raw, eol, cur, _ in plan:
            texts[path] = apply_text(path, cur)
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r131btmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r131btmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d edits)" % (len(plan), len(EDITS)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    outs = [(path, revert_text(path, cur).replace("\n", eol).encode("utf-8")) for path, raw, eol, cur, _ in plan]
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    print("reverted (%d files edited back)" % len(outs))


main()
