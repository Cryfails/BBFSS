# r97e_heat-haze-option: FEATURE patch on top of r97, r97b, r97c, r97d (apply AFTER them, revert BEFORE
# them) and r109a / r109b (it follows their pattern and anchors on their lines; revert it first).
# Owner, 2026-11-16 06:40, verbatim: "Heat haze strength 1 is find as a default, but the option should
# default to off and we should be able to configure the strength."
#
# What it does: the heat haze becomes a setting exactly as the halation did (r109a / r109b):
#  - lantern.ini key graphics_heat_haze_strength, 0..2, DEFAULT 0 = OFF (BbSettings::HeatHazeStrength
#    Min/Max/Default, a live std::atomic<float>, parsed with the isfinite fallback = the default, saved
#    with 2 decimals). Above 0 the shimmer strength is that value: 1 is today's strength 1 (the owner finds
#    it fine), 2 is twice (the same code path as BB_HEAT_HAZE=2 today).
#  - BB_HEAT_HAZE stays and WINS when it is set and not empty (read once; "0", a negative number or text
#    that is not a number is then 0 = off, as before). Unset or empty: the key decides.
#  - The strength is read every frame (HeatHaze::Strength(), as Halation::Strength()). The HeatHaze object
#    (pipeline, atlas image, counter buffers) is made at the rasterizer's start when the strength is above
#    0 then (as before), else at the FIRST frame at the upscaler's trigger with a strength above 0
#    (Rasterizer::EffectsBeforeUpscaler), and kept. A slider moved from 0 to above 0 therefore compiles
#    the compute pipeline then (one hitch, as the halation).
#  - Zero cost at 0: with no object nothing exists (the two relaxed atomic loads at the trigger are the
#    whole cost: StrengthLine and Wanted). With an object kept and the strength back at 0: the hook's
#    condition (HeatHaze::Wanted) is false, so Apply does not run (no pass, no dispatch, no barrier, no
#    wind lookup), and the lamp collector stops (HeatHaze::Gather(false): AddLights returns at once).
#    Frames, stats and logs of the pass stay silent.
#  - Menu: the in-game menu (Insert) gets a slider "Heat haze" 0..2 in the section "Light glow and
#    flicker", after the halation and the flicker rows (live; "%.2f"; EnvNote BB_HEAT_HAZE), label and
#    hint in the Russian overlay text and in all eight i18n tables (Spanish, Portuguese, French, German,
#    Italian, Polish, Turkish, Chinese; Chinese only with glyphs of LanternMenuSC-glyphs.txt, checked
#    here; every non-English text needs a native speaker's check). Both launchers (Graphics > Lighting,
#    after the flicker rows) get a StrengthSlider row (the r109b helper: shows what the engine reads and
#    follows the ini after Ini.Refresh), IniFile.cs Defaults "0.00", the 13 Localization json files the
#    row title, and LooksChecks pins the default (rule 11) and says the key is in no look (rule 10).
#  - Test view variables: BB_HEAT_HAZE_SHOW and BB_HEAT_HAZE_PROOF no longer need BB_HEAT_HAZE itself to be
#    above 0 when they are read (they were parsed together with it); they act only while the strength is
#    above 0 (the pass does not run at 0), whether it comes from the key or from the variable.
#  - Log: once per feature state "Heat haze (r97e): strength S from the setting|environment (key or
#    variable)[; 0: off, nothing is drawn]" at the first frame that reaches the upscaler's trigger, again
#    after a change at most once every 600 frames (StrengthKnob::Line, as "Halation (r109a)"). The once-line
#    of the object now reads "Heat haze (r97, strength S): ..." (was "BB_HEAT_HAZE=S"); the counters of
#    r97 / r97b / r97d are unchanged.
#  - README: the section intro, a key row, the BB_HEAT_HAZE row's first sentences.
#  - Tests: test_heat_haze.cpp (default 0, Pick: key decides, variable wins, clamps, non-finite),
#    test_settings.cpp (default, written back, read, clamped, text 0, not finite = default).
#
# Default picture: unchanged against any earlier build, because heat haze was off by env (BB_HEAT_HAZE
# unset) and is now off by key (default 0); with no object and no pass the frame is the same.
# Files: bbport_settings.h/.cpp, bbport_overlay.cpp, bbport_menu_i18n.cpp (shim); heat_haze.h,
# vk_heat_haze.h/.cpp, vk_rasterizer_effects.cpp (renderer); tests/test_heat_haze.cpp,
# tests/test_settings.cpp; launcher (2 GraphicsPage.cs, IniFile.cs, 13 json, LooksChecks); README.md.
# No shader, no CMake, no build.sh, no vk_rasterizer.cpp / .h line is touched (the start-time creation
# keeps asking HeatHaze::Wanted(), which now reads the strength).
# NOT compiled, not run (no clang++, no .NET 8 here): see the report.
#
# Use: python -I -X utf8 r97e_heat-haze-option.py check | apply | revert
# Root: R97E_ROOT, else <tree>. Line ends kept. apply backs the originals up in r97e_backup next to
# this script. Each insert is a block placed next to an anchor found exactly once (the anchor stays
# whole); each replacement swaps a text found exactly once; revert reverses each where it finds it.
import os, re, sys

ROOT = os.environ.get("R97E_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r97e_backup")
SH = "engine/gpu/shim/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
SETTINGS_H = SH + "bbport_settings.h"
SETTINGS_C = SH + "bbport_settings.cpp"
OVERLAY = SH + "bbport_overlay.cpp"
I18N = SH + "bbport_menu_i18n.cpp"
HH_H = RV + "heat_haze.h"
VK_H = RV + "vk_heat_haze.h"
VK_C = RV + "vk_heat_haze.cpp"
EFFECTS = RV + "vk_rasterizer_effects.cpp"
T_HAZE = "engine/tests/test_heat_haze.cpp"
T_SET = "engine/tests/test_settings.cpp"
GLYPHS = "engine/gpu/third_party/fonts/LanternMenuSC-glyphs.txt"
LW = "launcher/windows/"
GP_B = LW + "BloodborneLauncher/Views/GraphicsPage.cs"
GP_L = LW + "LanternLauncher/Views/GraphicsPage.cs"
INI = LW + "BloodborneLauncher/Core/IniFile.cs"
LOOKS_CHECKS = LW + "tests/LooksChecks/Program.cs"
LOC = LW + "BloodborneLauncher/Localization/"
README = "README.md"

EN = {
    "t": "Heat haze",
    "h": "Live, off by default. A shimmer of rising warm air above flames: the torch, candles, lanterns "
         "and the flames of lamps and bonfires. 0 is off and draws nothing, 1 is the look as designed, 2 is "
         "twice as strong. It is drawn before the upscaler, so with no upscaler nothing is drawn.",
}
RU = {
    "t": "Марево над огнём (heat haze)",
    "h": "Работает сразу, по умолчанию выкл. Дрожание тёплого воздуха, поднимающегося над огнём: факел, "
         "свечи, фонари, пламя ламп и костров. 0 — выкл., ничего не рисуется, 1 — задуманный вид, 2 — "
         "вдвое сильнее. Рисуется до апскейлера, поэтому без апскейлера ничего не рисуется.",
}
# The eight menu tables: (table name, anchor = the "Flicker strength on already flickering lamps" row).
TABLES = [
    ("kSpanish", '    {"Flicker strength on already flickering lamps", "Intensidad del parpadeo en lámparas que ya parpadean"},\n'),
    ("kPortugueseBrazil", '    {"Flicker strength on already flickering lamps", "Intensidade da oscilação em lâmpadas que já oscilam"},\n'),
    ("kFrench", '    {"Flicker strength on already flickering lamps", "Intensité du scintillement des lampes qui scintillent déjà"},\n'),
    ("kGerman", '    {"Flicker strength on already flickering lamps", "Flackerstärke bei Lampen, die schon flackern"},\n'),
    ("kItalian", '    {"Flicker strength on already flickering lamps", "Intensità dello sfarfallio sulle lampade che già sfarfallano"},\n'),
    ("kPolish", '    {"Flicker strength on already flickering lamps", "Siła migotania lamp, które już migoczą"},\n'),
    ("kTurkish", '    {"Flicker strength on already flickering lamps", "Zaten titreyen lambalarda titreme gücü"},\n'),
    ("kChinese", '    {"Flicker strength on already flickering lamps", "已闪烁灯光的闪烁强度"},\n'),
]
TR = {
    "kSpanish": {
        "t": "Distorsión por calor",
        "h": "Al instante, desactivado por defecto. Un temblor del aire caliente que sube sobre las llamas: "
             "la antorcha, las velas, los faroles y las llamas de lámparas y hogueras. 0 lo desactiva y no "
             "dibuja nada, 1 es el aspecto previsto, 2 es el doble de intenso. Se dibuja antes del "
             "escalador, así que sin escalador no se dibuja nada.",
    },
    "kPortugueseBrazil": {
        "t": "Distorção de calor",
        "h": "Na hora, desativado por padrão. Uma ondulação do ar quente que sobe acima das chamas: a "
             "tocha, as velas, as lanternas e as chamas de lampiões e fogueiras. 0 desativa e não desenha "
             "nada, 1 é o visual planejado, 2 é o dobro da intensidade. É desenhado antes do upscaler, "
             "então sem upscaler nada é desenhado.",
    },
    "kFrench": {
        "t": "Brume de chaleur",
        "h": "Immédiat, désactivé par défaut. Un tremblement de l'air chaud qui monte au-dessus des "
             "flammes : la torche, les bougies, les lanternes et les flammes des lampes et des feux de "
             "joie. 0 désactive et ne dessine rien, 1 est le rendu prévu, 2 est deux fois plus fort. Elle "
             "est dessinée avant l'upscaler : sans upscaler, rien n'est dessiné.",
    },
    "kGerman": {
        "t": "Hitzeflimmern",
        "h": "Sofort wirksam, standardmäßig aus. Ein Flimmern der warmen Luft, die über Flammen aufsteigt: "
             "Fackel, Kerzen, Laternen sowie die Flammen von Lampen und Feuerstellen. 0 ist aus und "
             "zeichnet nichts, 1 ist der vorgesehene Look, 2 doppelt so stark. Wird vor dem Upscaler "
             "gezeichnet, ohne Upscaler also nichts.",
    },
    "kItalian": {
        "t": "Distorsione da calore",
        "h": "Subito attivo, disattivato di default. Un tremolio dell'aria calda che sale sopra le "
             "fiamme: la torcia, le candele, le lanterne e le fiamme di lampade e falò. 0 disattiva e non "
             "disegna nulla, 1 è l'aspetto previsto, 2 è il doppio. Viene disegnato prima dell'upscaler, "
             "quindi senza upscaler non si disegna nulla.",
    },
    "kPolish": {
        "t": "Falowanie gorącego powietrza",
        "h": "Działa od razu, domyślnie wyłączone. Drżenie ciepłego powietrza unoszącego się nad "
             "płomieniami: pochodni, świec, latarni oraz płomieni lamp i ognisk. 0 wyłącza i nic nie "
             "rysuje, 1 to zamierzony wygląd, 2 to dwa razy mocniej. Rysowane przed upscalerem, więc bez "
             "upscalera nic nie jest rysowane.",
    },
    "kTurkish": {
        "t": "Isı dalgalanması",
        "h": "Anında, varsayılan olarak kapalı. Alevlerin üstünde yükselen sıcak havanın titreşimi: "
             "meşale, mumlar, fenerler ile lambaların ve ateşlerin alevleri. 0 kapalıdır ve hiçbir şey "
             "çizmez, 1 tasarlanan görünümdür, 2 iki kat güçlüdür. Upscaler'dan önce çizilir; upscaler "
             "yoksa hiçbir şey çizilmez.",
    },
    "kChinese": {
        "t": "Heat haze 强度",
        "h": "立即生效，默认关闭。火焰和灯火上方的画面会抖动。0 为关闭，不绘制任何内容；1 为设计效果；"
             "2 为 2 倍。在超分辨率算法之前绘制，因此不使用超分辨率算法时不会显示。",
    },
}
# Launcher row titles (the launcher is not limited to the menu font's glyphs).
LAUNCHER = {
    "es": TR["kSpanish"]["t"], "pt-BR": TR["kPortugueseBrazil"]["t"], "fr": TR["kFrench"]["t"],
    "de": TR["kGerman"]["t"], "it": TR["kItalian"]["t"], "pl": TR["kPolish"]["t"], "tr": TR["kTurkish"]["t"],
    "zh-CN": "热浪扭曲", "zh-TW": "熱浪扭曲", "ja": "陽炎", "ko": "열 아지랑이",
    "ru": "Марево над огнём", "uk": "Марево над вогнем",
}
# The anchor of each json file: the "Flicker strength on already flickering lamps" line (all 13, once).
LOC_ANCHOR = {
    "de": '  "Flicker strength on already flickering lamps": "Flackerstärke bei Lampen, die schon flackern",\n',
    "es": '  "Flicker strength on already flickering lamps": "Intensidad del parpadeo en lámparas que ya parpadean",\n',
    "fr": '  "Flicker strength on already flickering lamps": "Intensité du scintillement des lampes qui scintillent déjà",\n',
    "it": '  "Flicker strength on already flickering lamps": "Intensità dello sfarfallio sulle lampade che già sfarfallano",\n',
    "ja": '  "Flicker strength on already flickering lamps": "すでにちらつくランプのちらつきの強さ",\n',
    "ko": '  "Flicker strength on already flickering lamps": "이미 깜빡이는 램프의 깜빡임 강도",\n',
    "pl": '  "Flicker strength on already flickering lamps": "Siła migotania lamp, które już migoczą",\n',
    "pt-BR": '  "Flicker strength on already flickering lamps": "Intensidade da oscilação em lâmpadas que já oscilam",\n',
    "ru": '  "Flicker strength on already flickering lamps": "Сила мерцания у ламп, которые уже мерцают",\n',
    "tr": '  "Flicker strength on already flickering lamps": "Zaten titreyen lambalarda titreme gücü",\n',
    "uk": '  "Flicker strength on already flickering lamps": "Сила мерехтіння ламп, які вже мерехтять",\n',
    "zh-CN": '  "Flicker strength on already flickering lamps": "已闪烁灯光的闪烁强度",\n',
    "zh-TW": '  "Flicker strength on already flickering lamps": "已閃爍燈光的閃爍強度",\n',
}


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


# ---------------------------------------------------------------- the edit list
# (path, old, new, block): block is the inserted text for an insert (old stays whole inside new), None
# for a replacement (old is swapped for new).
EDITS = []


def AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


def BEFORE(path, anchor, block):
    EDITS.append((path, anchor, block + anchor, block))


def REPLACE(path, old, new):
    EDITS.append((path, old, new, None))


# ---- settings (shim)
AFTER(SETTINGS_H,
      "inline constexpr float LampFlickerSteadyDefault = 1.0f, LampFlickerOnGameDefault = 0.0f;\n",
      "// bbport (r97e_heat-haze-option): the heat haze's strength (live; 0 = off, the default; a set\n"
      "// BB_HEAT_HAZE wins). Tied to BbHeatHaze by static_asserts in vk_heat_haze.cpp.\n"
      "inline constexpr float HeatHazeStrengthMin = 0.0f, HeatHazeStrengthMax = 2.0f, HeatHazeStrengthDefault = 0.0f;\n")
AFTER(SETTINGS_H,
      "    std::atomic<float> graphics_lamp_flicker_on_game_strength{LampFlickerOnGameDefault}; "
      "// 0..1, flame lamps the game changes; 0: left alone\n",
      "    // bbport (r97e_heat-haze-option): live; 0..2, 0 (the default): off, nothing is made or drawn\n"
      "    std::atomic<float> graphics_heat_haze_strength{HeatHazeStrengthDefault};\n")
AFTER(SETTINGS_C,
      '    } else if (key == "graphics_lamp_flicker_on_game_strength") {\n'
      "        v.graphics_lamp_flicker_on_game_strength =\n"
      "            Clamp(std::isfinite(f) ? f : LampFlickerOnGameDefault, LampFlickerStrengthMin, LampFlickerStrengthMax);\n",
      '    } else if (key == "graphics_heat_haze_strength") { // bbport (r97e_heat-haze-option)\n'
      "        v.graphics_heat_haze_strength =\n"
      "            Clamp(std::isfinite(f) ? f : HeatHazeStrengthDefault, HeatHazeStrengthMin, HeatHazeStrengthMax);\n")
AFTER(SETTINGS_C,
      '    put("graphics_lamp_flicker_on_game_strength", fixed(v.graphics_lamp_flicker_on_game_strength, 2));\n',
      '    put("graphics_heat_haze_strength", fixed(v.graphics_heat_haze_strength, 2)); // bbport (r97e)\n')

# ---- the overlay row
OVERLAY_ANCHOR = '        EnvNote("BB_LAMP_FLICKER_ON_GAME");\n    }\n'
OVERLAY_BLOCK = (
    "    // bbport (r97e_heat-haze-option): the heat haze's strength (r97), live like the rows above; a set\n"
    "    // BB_HEAT_HAZE wins over the slider (EnvNote). 0 is the default: off.\n"
    '    if (const char* label = Item("%s",\n'
    '                                 "%s")) {\n'
    "        Slider(label, s.graphics_heat_haze_strength, BbSettings::HeatHazeStrengthMin,\n"
    '               BbSettings::HeatHazeStrengthMax, "%%.2f", ImGuiSliderFlags_AlwaysClamp);\n'
    "        Hint(BbSettings::MenuText(\n%s,\n%s));\n"
    '        EnvNote("BB_HEAT_HAZE");\n'
    "    }\n") % (EN["t"], RU["t"], cpp_lit(EN["h"], 12), cpp_lit(RU["h"], 12))
AFTER(OVERLAY, OVERLAY_ANCHOR, OVERLAY_BLOCK)
for _table, _anchor in TABLES:
    AFTER(I18N, _anchor, '    {"%s", "%s"},\n    {"%s", "%s"},\n' % (EN["t"], TR[_table]["t"], EN["h"], TR[_table]["h"]))

# ---- the pure header and the pass
AFTER(HH_H,
      "inline constexpr float MaxStrength = 2.0f;      ///< BB_HEAT_HAZE is clamped to 0..2\n",
      "/// (r97e) graphics_heat_haze_strength's default: 0, off (tied to BbSettings::HeatHazeStrengthDefault\n"
      "/// by a static_assert in vk_heat_haze.cpp).\n"
      "inline constexpr float DefaultStrength = 0.0f;\n")
AFTER(VK_H, '#include "video_core/renderer_vulkan/heat_haze.h"\n',
      '#include "video_core/renderer_vulkan/strength_knob.h" // bbport (r97e_heat-haze-option)\n')
REPLACE(VK_H,
        "    /// BB_HEAT_HAZE gives a strength above 0 (read once; the first call says the knobs' state).\n"
        "    [[nodiscard]] static bool Wanted();\n",
        "    /// The strength is above 0 (r97e: Strength(), this frame's; the first call says the knobs' state).\n"
        "    [[nodiscard]] static bool Wanted();\n"
        "    /// (r97e) The strength of the frame, read every frame: BB_HEAT_HAZE when it is set and not empty\n"
        "    /// (read once), else the setting graphics_heat_haze_strength (default 0: off).\n"
        "    [[nodiscard]] static StrengthKnob::Value Strength();\n"
        "    /// (r97e) The strength's line, once a frame at the upscaler's trigger: printed at the first\n"
        "    /// call, then after a change, at most once every 600 calls.\n"
        "    static void StrengthLine();\n"
        "    /// (r97e) At the trigger each frame: whether the lamps of this frame are gathered (the\n"
        "    /// strength is above 0); at 0 AddLights returns at once.\n"
        "    void Gather(bool on) {\n"
        "        gathering = on;\n"
        "    }\n")
REPLACE(VK_H,
        "    void AddLights(const u32* records, u32 count) {\n"
        "        collector.Add(records, count);\n"
        "    }\n",
        "    void AddLights(const u32* records, u32 count) {\n"
        "        if (gathering) { // bbport (r97e_heat-haze-option)\n"
        "            collector.Add(records, count);\n"
        "        }\n"
        "    }\n")
AFTER(VK_H, "    ::BbHeatHaze::Knobs knobs;\n",
      "    bool gathering = true; ///< (r97e) Gather(): false while the strength is 0\n")
AFTER(VK_C, '#include "bbport_toggles.h"\n', '#include "bbport_settings.h" // bbport (r97e_heat-haze-option)\n')
# ReadKnobs: the test views are parsed whatever the strength says (the strength is the caller's, per frame).
AFTER(VK_C,
      '        BbHeatHaze::Knobs read = BbHeatHaze::Parse(haze, std::getenv("BB_HEAT_HAZE_SHOW"));\n',
      "        // bbport (r97e_heat-haze-option): BB_HEAT_HAZE_SHOW is read as if the strength were above 0; the\n"
      "        // strength is HeatHaze::Strength()'s (setting or variable), per frame, and nothing runs at 0.\n"
      "        {\n"
      '            const BbHeatHaze::Knobs view = BbHeatHaze::Parse("1", std::getenv("BB_HEAT_HAZE_SHOW"));\n'
      "            read.show = view.show;\n"
      "            read.outline = view.outline;\n"
      "        }\n")
REPLACE(VK_C,
        "        read.proof = read.strength > 0.0f && proof != nullptr && proof[0] == '1' && proof[1] == 0;\n",
        "        read.proof = proof != nullptr && proof[0] == '1' && proof[1] == 0; // r97e: the strength is per frame\n")
REPLACE(VK_C,
        "bool HeatHaze::Wanted() {\n"
        "    return ReadKnobs().strength > 0.0f;\n"
        "}\n",
        "// bbport (r97e_heat-haze-option): the setting's numbers are the header's (one default: off).\n"
        "static_assert(BbSettings::HeatHazeStrengthDefault == BbHeatHaze::DefaultStrength &&\n"
        "              BbSettings::HeatHazeStrengthMax == BbHeatHaze::MaxStrength &&\n"
        "              BbSettings::HeatHazeStrengthMin == 0.0f);\n"
        "\n"
        "bool HeatHaze::Wanted() {\n"
        "    return Strength().value > 0.0f;\n"
        "}\n"
        "\n"
        "StrengthKnob::Value HeatHaze::Strength() {\n"
        "    // BB_HEAT_HAZE, when set and not empty, decides (its value comes from ReadKnobs: a number clamped\n"
        "    // to 0..2, text that is not a number 0); else the setting, read every frame.\n"
        "    static const StrengthKnob::Env env = [] {\n"
        "        StrengthKnob::Env read;\n"
        '        const char* text = std::getenv("BB_HEAT_HAZE");\n'
        "        read.set = text != nullptr && text[0] != '\\0';\n"
        "        read.value = read.set ? ReadKnobs().strength : 0.0f;\n"
        "        return read;\n"
        "    }();\n"
        "    return StrengthKnob::Pick(\n"
        "        env, BbSettings::Get().graphics_heat_haze_strength.load(std::memory_order_relaxed),\n"
        "        BbHeatHaze::MaxStrength, BbHeatHaze::DefaultStrength);\n"
        "}\n"
        "\n"
        "void HeatHaze::StrengthLine() {\n"
        "    static StrengthKnob::Line line;\n"
        "    const StrengthKnob::Value s = Strength();\n"
        "    if (line.Due(LineFrames, s)) {\n"
        '        BbReport::Printf("Heat haze (r97e): strength %.2f from the %s (%s)%s\\n", double(s.value),\n'
        "                         StrengthKnob::SourceName(s),\n"
        '                         s.from_env ? "BB_HEAT_HAZE" : "graphics_heat_haze_strength",\n'
        '                         s.value > 0.0f ? "" : "; 0: off, nothing is drawn");\n'
        "    }\n"
        "}\n")
REPLACE(VK_C,
        '    std::printf("Heat haze (r97, BB_HEAT_HAZE=%.2f): %s; a shimmer in a column above each flame "\n',
        '    std::printf("Heat haze (r97, strength %.2f): %s; a shimmer in a column above each flame "\n')
REPLACE(VK_C,
        '                double(knobs.strength), made ? "on" : "off - the pass could not be made",\n',
        '                double(Strength().value), made ? "on" : "off - the pass could not be made",\n')
REPLACE(VK_C,
        "        BbHeatHaze::Choose(lamps, view, knobs.strength, knobs.show, wind, atlas, counts);\n",
        "        BbHeatHaze::Choose(lamps, view, Strength().value, knobs.show, wind, atlas, counts); // r97e\n")

# ---- the hook
BEFORE(EFFECTS,
       "    // bbport (r97_heat-haze): BB_HEAT_HAZE only: the shimmer above flames, after the fog\n",
       "    // bbport (r97e_heat-haze-option): the haze's strength is a setting (HeatHaze::Strength: the key\n"
       "    // graphics_heat_haze_strength, or BB_HEAT_HAZE when set), read every frame. The HeatHaze is made at\n"
       "    // the first frame above 0 when it was not made at the start, and kept; at 0 the lamps are not\n"
       "    // gathered and the pass below does not run. Without an object at 0: two relaxed loads.\n"
       "    if (compute_hash == upscaler->TriggerHash()) {\n"
       "        HeatHaze::StrengthLine();\n"
       "        const bool haze_on = HeatHaze::Wanted();\n"
       "        if (!heat_haze && haze_on) {\n"
       "            heat_haze = std::make_unique<HeatHaze>(instance, scheduler, texture_cache, runtime,\n"
       "                                                   *scene_targets, *camera_motion);\n"
       "        }\n"
       "        if (heat_haze) {\n"
       "            heat_haze->Gather(haze_on);\n"
       "        }\n"
       "    }\n")
REPLACE(EFFECTS,
        "    if (heat_haze && compute_hash == upscaler->TriggerHash()) {\n",
        "    if (heat_haze && compute_hash == upscaler->TriggerHash() && HeatHaze::Wanted()) { // r97e\n")

# ---- tests
AFTER(T_HAZE,
      "        assert(Parse(nullptr, nullptr).strength == 0.0f && !Parse(nullptr, nullptr).unreadable);\n",
      "        // bbport (r97e_heat-haze-option): off by default; the key decides unless the variable is set\n"
      "        // (set and not empty: it wins, also with 0 and with text that is no number); a key outside\n"
      "        // 0..2 is the nearest end; a key that is not finite is the default.\n"
      "        static_assert(DefaultStrength == 0.0f);\n"
      "        const auto pick = [](const char* variable, float key) {\n"
      "            return StrengthKnob::Pick(StrengthKnob::ReadEnv(variable, MaxStrength), key, MaxStrength,\n"
      "                                      DefaultStrength);\n"
      "        };\n"
      "        assert(pick(nullptr, DefaultStrength).value == 0.0f && !pick(nullptr, DefaultStrength).from_env);\n"
      "        assert(pick(nullptr, 1.0f).value == 1.0f && pick(\"\", 1.0f).value == 1.0f && !pick(\"\", 1.0f).from_env);\n"
      "        assert(pick(nullptr, 2.0f).value == 2.0f && pick(nullptr, 9.0f).value == MaxStrength);\n"
      "        assert(pick(nullptr, -1.0f).value == 0.0f && pick(nullptr, std::nanf(\"\")).value == DefaultStrength);\n"
      "        assert(pick(\"0.5\", 1.0f).value == 0.5f && pick(\"0.5\", 1.0f).from_env);\n"
      "        assert(pick(\"0\", 1.0f).value == 0.0f && pick(\"0\", 1.0f).from_env);\n"
      "        assert(pick(\"abc\", 1.0f).value == 0.0f && pick(\"abc\", 1.0f).from_env);\n"
      "        assert(pick(\"5\", 0.0f).value == MaxStrength);\n")
AFTER(T_HAZE, '#include "gpu/shadps4/video_core/renderer_vulkan/heat_haze.h"\n',
      '#include "gpu/shadps4/video_core/renderer_vulkan/strength_knob.h" // bbport (r97e_heat-haze-option)\n')
BEFORE(T_SET,
       "    // bbport (r99c_interior-default): graphics_interior_brightness. Nothing above sets it: the default\n",
       "    // bbport (r97e_heat-haze-option): graphics_heat_haze_strength. Nothing above sets it: the default 0\n"
       "    // (off); written back; read; saved after a change; a value outside 0..2 is the nearest end; a text\n"
       "    // that is no number is 0; a value that is not finite is the default.\n"
       "    static_assert(BbSettings::HeatHazeStrengthMin == 0.0f && BbSettings::HeatHazeStrengthMax == 2.0f &&\n"
       "                  BbSettings::HeatHazeStrengthDefault == 0.0f);\n"
       "    assert(s.graphics_heat_haze_strength == BbSettings::HeatHazeStrengthDefault);\n"
       "    BbSettings::Save();\n"
       '    assert(Read(path).find("graphics_heat_haze_strength=0.00\\n") != std::string::npos);\n'
       '    { std::ofstream file(path); file << "graphics_heat_haze_strength=1.25\\n"; }\n'
       "    BbSettings::Load();\n"
       "    assert(s.graphics_heat_haze_strength == 1.25f);\n"
       "    s.graphics_heat_haze_strength = 2.0f;\n"
       "    BbSettings::Save();\n"
       '    assert(Read(path).find("graphics_heat_haze_strength=2.00\\n") != std::string::npos);\n'
       '    { std::ofstream file(path); file << "graphics_heat_haze_strength=9\\n"; }\n'
       "    BbSettings::Load();\n"
       "    assert(s.graphics_heat_haze_strength == BbSettings::HeatHazeStrengthMax);\n"
       '    { std::ofstream file(path); file << "graphics_heat_haze_strength=-1\\n"; }\n'
       "    BbSettings::Load();\n"
       "    assert(s.graphics_heat_haze_strength == 0.0f);\n"
       '    { std::ofstream file(path); file << "graphics_heat_haze_strength=abc\\n"; }\n'
       "    s.graphics_heat_haze_strength = 1.0f;\n"
       "    BbSettings::Load();\n"
       "    assert(s.graphics_heat_haze_strength == 0.0f);\n"
       '    { std::ofstream file(path); file << "graphics_heat_haze_strength=nan\\n"; }\n'
       "    s.graphics_heat_haze_strength = 1.0f; // not the default before this Load\n"
       "    BbSettings::Load();\n"
       "    assert(s.graphics_heat_haze_strength == BbSettings::HeatHazeStrengthDefault);\n"
       "    BbSettings::Save();\n")

# ---- launchers
ROW_ANCHOR = ('            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Flicker strength on already flickering lamps"), '
              '1, "graphics_lamp_flicker_on_game_strength", 0);\n')
ROW_BLOCK = ("            // r97e: the heat haze, off by default (0); the in-game menu has the same slider, live.\n"
             '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Heat haze"), 2, "graphics_heat_haze_strength", 0);\n')
for _gp in (GP_B, GP_L):
    AFTER(_gp, ROW_ANCHOR, ROW_BLOCK)
AFTER(INI, '            ("graphics_lamp_flicker_on_game_strength", "0.00"),\n',
      "            // r97e: the heat haze's strength, off by default (BbSettings::HeatHazeStrengthDefault).\n"
      '            ("graphics_heat_haze_strength", "0.00"),\n')
REPLACE(LOOKS_CHECKS,
        '("graphics_lamp_flicker_on_game_strength", "0.00") })\n',
        '("graphics_lamp_flicker_on_game_strength", "0.00"), ("graphics_heat_haze_strength", "0.00") })\n')
for _code, _anchor in LOC_ANCHOR.items():
    AFTER(LOC + _code + ".json", _anchor, '  "%s": "%s",\n' % (EN["t"], LAUNCHER[_code]))

# ---- README
REPLACE(README,
        "Off unless `BB_HEAT_HAZE` is set. These environment variables are read once when the game starts; "
        "they are for testing, no ini key yet.",
        "Off by default. The strength is the `lantern.ini` key `graphics_heat_haze_strength`, 0 to 2, read every "
        "frame, with a slider in the in-game menu (**Insert**, section Light glow and flicker, changes at once) "
        "and in the launcher (Graphics > Lighting); 0, the default, is off, 1 is the look as designed. "
        "`BB_HEAT_HAZE`, when it is set and not empty, wins over the key (read once, at the first frame). At "
        "strength 0 nothing is drawn: the lamps are no longer gathered and the pass does not run; the pass's "
        "pipeline and images are made at the first frame with a strength above 0 and kept until the game ends, "
        "also when the strength goes back to 0. The session log has a `Heat haze (r97e):` line with the strength "
        "and where it came from (setting or environment) at the first frame that reaches the place before the "
        "upscaler, and again after a change, at most once every 600 frames. The other variables are read once "
        "when the game starts; they are for testing.")
REPLACE(README,
        "| `BB_HEAT_HAZE` | Strength of the haze, a number from 0 to 2 (above 2 counts as 2; 0, unset or text "
        "that is not a number is off); `1` is the look as designed.",
        "| `graphics_heat_haze_strength` | `lantern.ini` key (r97e): the strength of the haze, 0 to 2, read every "
        "frame, with the haze `BB_HEAT_HAZE` describes; `BB_HEAT_HAZE` wins over it when set and not empty. A "
        "value outside the range is the nearest end, one that is not a finite number is `0`, text that is no "
        "number is `0` | `0` (off) |\n"
        "| `BB_HEAT_HAZE` | Strength of the haze, a number from 0 to 2 (above 2 counts as 2; 0 or text that is not "
        "a number is off); `1` is the look as designed. Set and not empty it wins over "
        "`graphics_heat_haze_strength`; unset or empty the key decides.")


# ---------------------------------------------------------------- machinery
def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_of(path):
    return [e for e in EDITS if e[0] == path]


def is_done(e, text):
    """An insert is done when its block is found once; a replacement when its new text is."""
    return text.count(e[3] if e[3] is not None else e[2]) == 1


def is_todo(e, text):
    return text.count(e[1]) == 1 and text.count(e[3] if e[3] is not None else e[2]) == 0


def state_of(path, text):
    eds = edits_of(path)
    done = sum(is_done(e, text) for e in eds)
    todo = sum(is_todo(e, text) for e in eds)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    bad = [e[1][:70] for e in eds if not (is_done(e, text) or is_todo(e, text))]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d would apply; anchor or block not found "
                     "once: %r" % (path, done, len(eds), todo, bad))


def apply_text(path, text):
    for p, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(block if block is not None else new) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:70]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, old, new, block in reversed(EDITS):
        if p != path:
            continue
        gone = block if block is not None else new
        if text.count(gone) != 1:
            raise SystemExit("REFUSED: %s: block found %d times: %r" % (path, text.count(gone), gone[:70]))
        text = text.replace(gone, "" if block is not None else old, 1)
    return text


def table_span(text, name):
    start = text.index("constexpr Entry %s[] = {" % name)
    return text[start:text.index("\n};", start)]


def text_checks(texts):
    i18n = texts[I18N]
    glyphs = {int(x.strip()[2:], 16) for x in
              open(os.path.join(ROOT, GLYPHS), encoding="utf-8").read().split(",") if x.strip()}
    for name, _ in TABLES:
        span = table_span(i18n, name)
        for k in ("t", "h"):
            line = '    {"%s", "%s"},\n' % (EN[k], TR[name][k])
            if span.count(line) != 1 or span.count('{"%s"' % EN[k]) != 1:
                raise SystemExit("text check: %s: %r not found exactly once" % (name, EN[k][:40]))
    zh = TR["kChinese"]["t"] + TR["kChinese"]["h"]
    missing = sorted({c for c in zh if ord(c) > 0x7e and ord(c) not in glyphs})
    if missing:
        raise SystemExit("text check: Chinese menu text has characters the menu font lacks: %s" % "".join(missing))
    joined = re.sub(r'"\s*\n\s*"', "", texts[OVERLAY])
    for k in ("t", "h"):
        for text in (EN[k], RU[k]):
            if joined.count('"%s"' % text) != 1:
                raise SystemExit("text check: overlay: %r not found exactly once" % text[:40])
    for k in ("t", "h"):
        if i18n.count('{"%s"' % EN[k]) != 8:
            raise SystemExit("text check: %r is not a key of all 8 tables" % EN[k][:40])
    if texts[SETTINGS_H].count("HeatHazeStrengthDefault") != 2:
        raise SystemExit("text check: bbport_settings.h: HeatHazeStrengthDefault expected 2 times")
    for p in (GP_B, GP_L):
        if texts[p].count('"graphics_heat_haze_strength", 0);') != 1:
            raise SystemExit("text check: %s: the heat haze row is not there once" % p)
    for code in LOC_ANCHOR:
        t = texts[LOC + code + ".json"]
        if t.count('"%s": "%s",' % (EN["t"], LAUNCHER[code])) != 1 or t.count('"%s":' % EN["t"]) != 1:
            raise SystemExit("text check: %s.json: the row title is not there once" % code)
    if texts[README].count("graphics_heat_haze_strength") < 3:
        raise SystemExit("text check: README: the key is not named in the intro and the table")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode not in ("check", "apply", "revert"):
        raise SystemExit("usage: r97e_heat-haze-option.py check | apply | revert")
    paths = sorted({e[0] for e in EDITS})
    raws, texts, states, eols = {}, {}, {}, {}
    for p in paths:
        raws[p], eols[p], texts[p] = load(p)
        states[p] = state_of(p, texts[p])
    kinds = set(states.values())
    if len(kinds) > 1:
        raise SystemExit("REFUSED: mixed state: " + ", ".join("%s=%s" % (p, s) for p, s in states.items()))
    state = kinds.pop()
    if mode == "check":
        if state == "applied":
            text_checks(texts)
            print("applied (%d files, %d edits; text checks pass)" % (len(paths), len(EDITS)))
        else:
            sim = {p: apply_text(p, texts[p]) for p in paths}
            text_checks(sim)
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(paths), len(EDITS)))
        return
    if mode == "apply":
        if state == "applied":
            print("already applied")
            return
        new = {p: apply_text(p, texts[p]) for p in paths}
        text_checks(new)
        os.makedirs(BACKUP, exist_ok=True)
        for p in paths:
            open(os.path.join(BACKUP, p.replace("/", "__")), "wb").write(raws[p])
        for p in paths:
            open(os.path.join(ROOT, p), "wb").write(new[p].replace("\n", eols[p]).encode("utf-8"))
        print("applied: %d files, %d edits" % (len(paths), len(EDITS)))
        return
    if state == "clean":
        print("nothing to revert")
        return
    new = {p: revert_text(p, texts[p]) for p in paths}
    for p in paths:
        open(os.path.join(ROOT, p), "wb").write(new[p].replace("\n", eols[p]).encode("utf-8"))
    print("reverted: %d files" % len(paths))


main()
