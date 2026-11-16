# r128b_lrt-caustics-water: FEATURE patch (lane LRT, task LRT-T05 water and caustics).
# Owner words (goals.md): LRT-G057 "I would just have sun caustics if it can't be cheap as its own
# setting"; LRT-G056 "water ... and reflection caustics"; LRT-G060 (b72, "Caustics seem pretty good").
# Until now the water caustics (r107 .. r107f) could be switched on only by environment variables
# (BB_CAUSTICS for the sun and moon, BB_CAUSTICS_LAMPS for the lamps, read once at the start), so the
# owner could not use them from the menu or the launcher and nothing of it could go on a feature branch
# as a player-facing option. This patch makes the two strengths settings, LIVE, off by default.
#
# What it does:
#  - Two lantern.ini keys, graphics_water_caustics_sun_strength (the sun and moon, BB_CAUSTICS) and
#    graphics_water_caustics_lamps_strength (the lamps, BB_CAUSTICS_LAMPS), 0 to 4 (caustics_params.h
#    MaxStrength), default 0 = off. A value outside the range is the nearest end, text that is no number
#    is 0, a value that is not finite is the default (bbport_settings.cpp, as r109a / r97e).
#  - A variable that is set and not empty still decides for its channel (also "0" and text: off), read
#    once as before (BC::WithSettings: the environment's Knobs where its variable is set, else the
#    setting). BB_CAUSTICS_WORLD and the test view ("show") stay environment only.
#  - Caustics::Wanted() now reads the strengths in force (setting or variable) at each call. The
#    Caustics object is made as before at the rasterizer's start when a strength is above 0, and now
#    ALSO at the first frame a strength goes above 0 (vk_rasterizer_effects.cpp, after the halation
#    block, the place r97e uses for the heat haze: the upscaler's trigger draw, frame end). Each frame
#    Caustics::Refresh() takes the two strengths again, so a slider acts at once; at 0 for both
#    Apply returns at its first line (no counts, no dispatch) and AddLights / OnLightSets are not fed.
#    A strength that goes to 0 keeps the object (its pipeline and 7 KB buffer) until the game ends.
#  - Caustics::StrengthLine(): a log line "Water caustics (r128b): ..." with both strengths and where
#    each came from (setting or environment), at the first frame and after a change (StrengthKnob::Line,
#    at most once every 600 frames); Report() ends with a "Water caustics (r128b)" line with the counters
#    (strength changes, passes skipped with both at 0).
#  - In-game menu (Insert): a section "Water caustics" with two live sliders (lamps, sun and moon),
#    hint, EnvNote for the variable that wins; both launchers' Graphics > Lighting get the same two
#    sliders (StrengthSlider, as r109b / r97e: ShowStrengths re-reads them), IniFile.cs defaults 0.00,
#    13 localization json files (row titles), the eight menu tables (hints and titles; the Chinese text
#    uses only characters of third_party/fonts/LanternMenuSC-glyphs.txt, checked here; the sun and moon
#    have no glyph there, so it says "external light" 外部光; every non-English text needs a native
#    speaker), README rows and paragraph, tests (test_settings.cpp, test_caustics.cpp).
#
# Off (the default, no variable): graphics_water_caustics_* are 0, so Wanted() is false, no Caustics is
# made (no pipeline, no buffer, no pass), and every hook stays one null pointer test, exactly as with
# BB_CAUSTICS unset today (the shader and the pass are untouched: the builds' SPIR-V is byte-identical).
# Per frame without an object: StrengthLine + Wanted = four relaxed atomic loads, a handful of compares.
# Env set as before (BB_CAUSTICS=1 BB_CAUSTICS_LAMPS=4 ...): the knobs equal ReadKnobs() (a channel
# whose variable is set takes nothing from the setting), the log lines of r107 .. r107f are unchanged.
#
# Cost: unchanged pass cost (r107b .. r107f: an estimate of 0.03 to 0.08 ms at 1080p for the puddle
# measure, not measured; the profile row stays "Lighting: water caustics"); one extra effect only when
# the slider first goes above 0: a compute pipeline (EffectPass::Create, a hitch of one frame is
# possible, as with r97e's haze made at its first frame) and a 6912 byte host-visible buffer
# (8 slots x 168 words + 8 data blocks x 48 words). Settings reads: negligible.
#
# Files: caustics_params.h (SettingOf, WithSettings), vk_caustics.h/.cpp (Wanted, Current, StrengthLine,
# Refresh, the idle return, the report line), vk_rasterizer_effects.cpp (the lazy make and Refresh),
# bbport_settings.h/.cpp (two constants, two atomics, parse, save), bbport_overlay.cpp (section),
# bbport_menu_i18n.cpp (8 tables), launcher IniFile.cs, both GraphicsPage.cs, 13 Localization json,
# test_settings.cpp, test_caustics.cpp, README.md.
#
# Use: python -I -X utf8 r128b_lrt-caustics-water.py check | apply | revert
# Root: R128B_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in
# r128b_backup next to this script. Every edit inserts text before or after an anchor found exactly
# once (the anchor stays whole), or replaces a whole text found exactly once; revert takes out what
# apply inserted (each inserted block found by itself exactly once). Needs r109a/r109b and r97e applied
# (their key rows and launcher rows are the anchors; apply refuses without them).
import io, json, os, re, sys

ROOT = os.environ.get("R128B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r128b_backup")
H = "engine/gpu/shadps4/video_core/renderer_vulkan/"
SH = "engine/gpu/shim/"
PARAMS = H + "caustics_params.h"
CH = H + "vk_caustics.h"
CC = H + "vk_caustics.cpp"
EFFECTS = H + "vk_rasterizer_effects.cpp"
SETTINGS_H = SH + "bbport_settings.h"
SETTINGS_C = SH + "bbport_settings.cpp"
OVERLAY = SH + "bbport_overlay.cpp"
I18N = SH + "bbport_menu_i18n.cpp"
GLYPHS = "engine/gpu/third_party/fonts/LanternMenuSC-glyphs.txt"
T_SETTINGS = "engine/tests/test_settings.cpp"
T_CAUSTICS = "engine/tests/test_caustics.cpp"
LW = "launcher/windows/"
GP_B = LW + "BloodborneLauncher/Views/GraphicsPage.cs"
GP_L = LW + "LanternLauncher/Views/GraphicsPage.cs"
INI = LW + "BloodborneLauncher/Core/IniFile.cs"
LOC = LW + "BloodborneLauncher/Localization/"
README = "README.md"

KEY_SUN = "graphics_water_caustics_sun_strength"
KEY_LAMPS = "graphics_water_caustics_lamps_strength"

# ---------------------------------------------------------------- texts
EN = {
    "sec": "Water caustics",
    "t1": "Water caustics from lamps",
    "t2": "Water caustics from the sun and moon",
    "h1": "Live, off by default. The light of up to 4 lamps that a water surface reflects, as a slowly "
          "moving net of bright lines on the walls and undersides beside it and over puddles. It shows "
          "only where the game draws water as a mirror (the sewers) or on very glossy wet ground. 0 is "
          "off, 1 is the lamps' own light, up to 4 adds a stronger look. Needs the upscaler: with none "
          "nothing is drawn.",
    "h2": "Live, off by default. The same moving net from the light of the sun or moon, where that light "
          "reaches the water, so not under a roof. 0 is off, 1 is the intended look, up to 4 is "
          "stronger. Needs the upscaler: with none nothing is drawn.",
}
RU = {
    "sec": "Блики от воды (каустика)",
    "t1": "Блики от воды: свет ламп",
    "t2": "Блики от воды: солнце и луна",
    "h1": "Работает сразу, по умолчанию выкл. Свет до 4 ламп, который отражает поверхность воды, в виде "
          "медленно движущейся сетки ярких линий на ближних стенах и нижних сторонах и над лужами. Виден "
          "только там, где игра рисует воду как зеркало (канализация), или на очень блестящей мокрой "
          "земле. 0 — выкл., 1 — собственный свет ламп, до 4 добавляет более сильный вид. Нужен "
          "апскейлер: без него ничего не рисуется.",
    "h2": "Работает сразу, по умолчанию выкл. Та же движущаяся сетка от света солнца или луны там, где он "
          "достигает воды, поэтому не под крышей. 0 — выкл., 1 — задуманный вид, до 4 сильнее. Нужен "
          "апскейлер: без него ничего не рисуется.",
}
TABLES = [  # (table name, anchor = the "Lamp fog glow size" entry and the line after it, as r109b)
    ("kSpanish", '    {"Lamp fog glow size", "Tamaño del brillo de la niebla de lámparas"},\n'
                 '    {"Applied when the game restarts.", "Se aplica al iniciar el juego"},\n'),
    ("kPortugueseBrazil", '    {"Lamp fog glow size", "Tamaño del brillo de la niebla de lámparas"},\n'
                          '    {"Applied when the game restarts.", "Aplicado ao iniciar o jogo"},\n'),
    ("kFrench", '    {"Lamp fog glow size", "Taille du halo du brouillard des lampes"},\n'
                '    {"Applied when the game restarts.", "Appliqué au lancement du jeu"},\n'),
    ("kGerman", '    {"Lamp fog glow size", "Glühgröße des Lampennebels"},\n'
                '    {"Applied when the game restarts.", "Wird beim Spielstart angewendet"},\n'),
    ("kItalian", '    {"Lamp fog glow size", "Dimensione del bagliore della nebbia delle lampade"},\n'
                 '    {"Applied when the game restarts.", "Si applica all\'avvio del gioco"},\n'),
    ("kPolish", '    {"Lamp fog glow size", "Rozmiar poświaty mgły lamp"},\n'
                '    {"Applied when the game restarts.", "Stosowane przy uruchomieniu gry"},\n'),
    ("kTurkish", '    {"Lamp fog glow size", "Lamba sisi parıltı boyutu"},\n'
                 '    {"Applied when the game restarts.", "Oyun başlarken uygulanır"},\n'),
    ("kChinese", '    {"Lamp fog glow size", "灯光雾光晕大小"},\n'
                 '    {"Applied when the game restarts.", "游戏启动时应用"},\n'),
]
TR = {
    "kSpanish": {
        "sec": "Cáusticas del agua",
        "t1": "Cáusticas del agua por lámparas",
        "t2": "Cáusticas del agua por el sol y la luna",
        "h1": "Al instante, desactivado por defecto. La luz de hasta 4 lámparas que refleja una superficie "
              "de agua, como una red de líneas brillantes que se mueve despacio sobre las paredes y los "
              "bajos cercanos y sobre los charcos. Solo se ve donde el juego dibuja el agua como un espejo "
              "(las alcantarillas) o sobre suelo mojado muy brillante. 0 lo desactiva, 1 es la luz propia "
              "de las lámparas y hasta 4 añade un aspecto más marcado. Necesita el escalador: sin él no "
              "se dibuja nada.",
        "h2": "Al instante, desactivado por defecto. La misma red en movimiento con la luz del sol o de la "
              "luna, donde esa luz llega al agua; por eso no bajo un techo. 0 lo desactiva, 1 es el "
              "aspecto previsto y hasta 4 es más fuerte. Necesita el escalador: sin él no se dibuja nada.",
    },
    "kPortugueseBrazil": {
        "sec": "Cáusticas da água",
        "t1": "Cáusticas da água das lâmpadas",
        "t2": "Cáusticas da água do sol e da lua",
        "h1": "Na hora, desligado por padrão. A luz de até 4 lâmpadas que uma superfície de água reflete, "
              "como uma rede de linhas brilhantes que se move devagar nas paredes e nas partes de baixo "
              "ao lado e sobre poças. Só aparece onde o jogo desenha a água como espelho (os esgotos) ou "
              "em chão molhado muito brilhante. 0 desliga, 1 é a luz própria das lâmpadas e até 4 "
              "acrescenta um visual mais forte. Precisa do upscaler: sem ele nada é desenhado.",
        "h2": "Na hora, desligado por padrão. A mesma rede em movimento com a luz do sol ou da lua, onde "
              "essa luz chega à água; por isso não sob um telhado. 0 desliga, 1 é o visual previsto e "
              "até 4 é mais forte. Precisa do upscaler: sem ele nada é desenhado.",
    },
    "kFrench": {
        "sec": "Caustiques de l'eau",
        "t1": "Caustiques de l'eau des lampes",
        "t2": "Caustiques de l'eau du soleil et de la lune",
        "h1": "Immédiat, désactivé par défaut. La lumière de 4 lampes au plus qu'une surface d'eau "
              "réfléchit, comme un filet de lignes brillantes qui bouge lentement sur les murs et les "
              "dessous voisins et sur les flaques. Elle n'apparaît que là où le jeu dessine l'eau en "
              "miroir (les égouts) ou sur un sol mouillé très brillant. 0 désactive, 1 est la lumière "
              "propre des lampes et jusqu'à 4 ajoute un rendu plus marqué. Nécessite l'upscaler : sans "
              "lui, rien n'est dessiné.",
        "h2": "Immédiat, désactivé par défaut. Le même filet mouvant avec la lumière du soleil ou de la "
              "lune, là où elle atteint l'eau, donc pas sous un toit. 0 désactive, 1 est le rendu prévu "
              "et jusqu'à 4 plus fort. Nécessite l'upscaler : sans lui, rien n'est dessiné.",
    },
    "kGerman": {
        "sec": "Wasserkaustik",
        "t1": "Wasserkaustik durch Lampen",
        "t2": "Wasserkaustik durch Sonne und Mond",
        "h1": "Sofort wirksam, standardmäßig aus. Das Licht von bis zu 4 Lampen, das eine Wasserfläche "
              "zurückwirft, als langsam wanderndes Netz heller Linien auf den Wänden und Unterseiten "
              "daneben und über Pfützen. Zu sehen nur, wo das Spiel Wasser als Spiegel zeichnet (die "
              "Kanalisation) oder auf sehr glänzendem nassem Boden. 0 ist aus, 1 ist das eigene Licht der "
              "Lampen, bis 4 kommt ein stärkerer Look dazu. Braucht den Upscaler: ohne ihn wird nichts "
              "gezeichnet.",
        "h2": "Sofort wirksam, standardmäßig aus. Dasselbe wandernde Netz mit dem Licht von Sonne oder "
              "Mond, wo es das Wasser erreicht, also nicht unter einem Dach. 0 ist aus, 1 ist der "
              "vorgesehene Look, bis 4 stärker. Braucht den Upscaler: ohne ihn wird nichts gezeichnet.",
    },
    "kItalian": {
        "sec": "Caustiche dell'acqua",
        "t1": "Caustiche dell'acqua dalle lampade",
        "t2": "Caustiche dell'acqua da sole e luna",
        "h1": "Subito attivo, disattivato di default. La luce di al massimo 4 lampade che una superficie "
              "d'acqua riflette, come una rete di linee luminose che si muove lentamente sulle pareti e "
              "sulle parti inferiori vicine e sulle pozzanghere. Si vede solo dove il gioco disegna "
              "l'acqua a specchio (le fogne) o su terreno bagnato molto lucido. 0 disattiva, 1 è la luce "
              "propria delle lampade e fino a 4 aggiunge un aspetto più marcato. Richiede l'upscaler: "
              "senza non si disegna nulla.",
        "h2": "Subito attivo, disattivato di default. La stessa rete in movimento con la luce del sole o "
              "della luna, dove raggiunge l'acqua, quindi non sotto un tetto. 0 disattiva, 1 è l'aspetto "
              "previsto e fino a 4 più forte. Richiede l'upscaler: senza non si disegna nulla.",
    },
    "kPolish": {
        "sec": "Kaustyka wody",
        "t1": "Kaustyka wody od lamp",
        "t2": "Kaustyka wody od słońca i księżyca",
        "h1": "Działa od razu, domyślnie wył. Światło do 4 lamp odbijane przez powierzchnię wody, jako "
              "powoli poruszająca się siatka jasnych linii na pobliskich ścianach i spodach oraz nad "
              "kałużami. Widać ją tylko tam, gdzie gra rysuje wodę jak lustro (kanały) lub na bardzo "
              "błyszczącej mokrej ziemi. 0 wyłącza, 1 to własne światło lamp, do 4 dodaje mocniejszy "
              "wygląd. Wymaga upscalera: bez niego nic nie jest rysowane.",
        "h2": "Działa od razu, domyślnie wył. Ta sama poruszająca się siatka ze światła słońca lub "
              "księżyca, tam gdzie dociera ono do wody, więc nie pod dachem. 0 wyłącza, 1 to zamierzony "
              "wygląd, do 4 mocniej. Wymaga upscalera: bez niego nic nie jest rysowane.",
    },
    "kTurkish": {
        "sec": "Su kostikleri",
        "t1": "Lambalardan su kostikleri",
        "t2": "Güneş ve aydan su kostikleri",
        "h1": "Anında, varsayılan olarak kapalı. Bir su yüzeyinin yansıttığı en çok 4 lambanın ışığı; "
              "yakındaki duvarlarda, alt yüzeylerde ve su birikintilerinde yavaşça hareket eden parlak "
              "çizgilerden bir ağ olarak görünür. Yalnızca oyunun suyu ayna gibi çizdiği yerlerde "
              "(kanalizasyon) ya da çok parlak ıslak zeminde görünür. 0 kapatır, 1 lambaların kendi "
              "ışığıdır, 4'e kadar daha belirgin bir görünüm ekler. Upscaler gerekir: yoksa hiçbir şey "
              "çizilmez.",
        "h2": "Anında, varsayılan olarak kapalı. Güneşin veya ayın ışığıyla aynı hareketli ağ; ışık suya "
              "ulaştığı yerde görünür, yani çatı altında değil. 0 kapatır, 1 tasarlanan görünümdür, "
              "4'e kadar daha güçlüdür. Upscaler gerekir: yoksa hiçbir şey çizilmez.",
    },
    "kChinese": {
        "sec": "水面反光",
        "t1": "灯光的水面反光",
        "t2": "外部光的水面反光",
        "h1": "立即生效，默认关闭。水面反射的最多 4 个灯的光，在附近的物体表面和积水处形成慢慢移动的亮色网纹。"
              "只在游戏用镜面方式绘制水的位置（下水道）或非常光滑的积水表面才看得到。0 为关闭，1 为灯光本身"
              "的亮度，最高 4 会加上更强的效果。需要超分辨率算法：没有它时不绘制任何内容。",
        "h2": "立即生效，默认关闭。外部的月光或其他光照到水面时形成的相同的移动亮色网纹，所以有遮挡的位置看不到。"
              "0 为关闭，1 为设计的效果，最高 4 更强。需要超分辨率算法：没有它时不绘制任何内容。",
    },
}
# Launcher row titles (the launcher is not limited to the menu font's glyphs).
LAUNCHER = {
    "es": TR["kSpanish"], "pt-BR": TR["kPortugueseBrazil"], "fr": TR["kFrench"], "de": TR["kGerman"],
    "it": TR["kItalian"], "pl": TR["kPolish"], "tr": TR["kTurkish"],
    "zh-CN": {"t1": "灯光的水面反光", "t2": "太阳和月亮的水面反光"},
    "zh-TW": {"t1": "燈光的水面反光", "t2": "太陽和月亮的水面反光"},
    "ja": {"t1": "ランプによる水の集光模様（コースティクス）", "t2": "太陽と月による水の集光模様（コースティクス）"},
    "ko": {"t1": "램프에 의한 물 반사광(코스틱)", "t2": "태양과 달에 의한 물 반사광(코스틱)"},
    "ru": {"t1": RU["t1"], "t2": RU["t2"]},
    "uk": {"t1": "Відблиски води: світло ламп", "t2": "Відблиски води: сонце і місяць"},
}
LOC_ANCHOR = {
    "de": '  "Lamp fog strength": "Stärke des Lampennebels",\n',
    "es": '  "Lamp fog strength": "Intensidad de la niebla de lámparas",\n',
    "fr": '  "Lamp fog strength": "Intensité du brouillard des lampes",\n',
    "it": '  "Lamp fog strength": "Intensità della nebbia delle lampade",\n',
    "ja": '  "Lamp fog strength": "ランプの霧の強さ",\n',
    "ko": '  "Lamp fog strength": "램프 안개 강도",\n',
    "pl": '  "Lamp fog strength": "Siła mgły lamp",\n',
    "pt-BR": '  "Lamp fog strength": "Intensidade da névoa de lâmpadas",\n',
    "ru": '  "Lamp fog strength": "Сила тумана от ламп",\n',
    "tr": '  "Lamp fog strength": "Lamba sisi gücü",\n',
    "uk": '  "Lamp fog strength": "Сила туману від ламп",\n',
    "zh-CN": '  "Lamp fog strength": "灯光雾强度",\n',
    "zh-TW": '  "Lamp fog strength": "燈光霧強度",\n',
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


def table_block(lang):
    t = TR[lang]
    return "".join('    {"%s", "%s"},\n' % (EN[k], t[k]) for k in ("sec", "t1", "t2", "h1", "h2"))


# ---------------------------------------------------------------- engine blocks
PARAMS_BLOCK = r"""/// bbport (r128b_lrt-caustics-water): a lantern.ini strength (graphics_water_caustics_sun_strength,
/// graphics_water_caustics_lamps_strength) as a knob strength: not finite or not above 0 is 0, above
/// MaxStrength is MaxStrength.
inline float SettingOf(float setting) {
    return std::isfinite(setting) && setting > 0.0f ? std::min(setting, MaxStrength) : 0.0f;
}

/// bbport (r128b_lrt-caustics-water): the knobs the renderer runs with. `env` is what Parse and WorldOf
/// read from the variables once. A channel whose variable is set and not empty (`sun_env`: BB_CAUSTICS,
/// `lamps_env`: BB_CAUSTICS_LAMPS) keeps the environment's strength, also 0 or unreadable text: the
/// variable decides, as BB_HEAT_HAZE does; else the channel's strength is the setting's (SettingOf).
/// The test view (`show`), `unreadable` and the world map stay the environment's.
inline Knobs WithSettings(const Knobs& env, bool sun_env, bool lamps_env, float sun_setting,
                          float lamps_setting) {
    Knobs k = env;
    if (!sun_env) {
        k.strength = SettingOf(sun_setting);
    }
    if (!lamps_env) {
        k.lamp_strength = SettingOf(lamps_setting);
    }
    return k;
}

"""
PARAMS_ANCHOR = "/// The push words of caustics.comp, field for field.\nstruct Push {\n"

CH_DECL = ("    /// bbport (r128b_lrt-caustics-water): Wanted reads the strengths in force at each call (the\n"
           "    /// variable where set and not empty, else the lantern.ini setting), so the rasterizer makes the\n"
           "    /// object at the first frame one is above 0. Refresh takes the two strengths again (once a\n"
           "    /// frame); StrengthLine says them (first frame, after a change, at most once every 600).\n"
           "    static void StrengthLine();\n"
           "    void Refresh();\n")
CH_ANCHOR1 = "    [[nodiscard]] static bool Wanted();\n"
CH_MEMBERS = ("    u32 strength_changes = 0; ///< r128b: Refresh found another strength (setting moved)\n"
              "    u32 idle_passes = 0;      ///< r128b: Apply calls skipped with both strengths 0\n")
CH_ANCHOR2 = "    bool reported = false;\n    bool told_first = false;\n"

CC_INCLUDE_ANCHOR = '#include "bbport_toggles.h"\n'
CC_INCLUDE = '#include "video_core/renderer_vulkan/strength_knob.h" // bbport (r128b_lrt-caustics-water)\n'

CC_HELPER = r"""// bbport (r128b_lrt-caustics-water): the strengths in force. A variable that is set and not empty
// decides for its channel (BB_CAUSTICS the sun and moon, BB_CAUSTICS_LAMPS the lamps; also with 0 or
// text: ReadKnobs read it once), else the lantern.ini setting, read at every call (a relaxed load).
bool EnvSet(const char* name) {
    const char* text = std::getenv(name);
    return text != nullptr && text[0] != '\0';
}

struct InForce {
    BC::Knobs knobs;
    bool sun_env = false, lamps_env = false;
};

InForce Current() {
    static const bool sun_env = EnvSet("BB_CAUSTICS"), lamps_env = EnvSet("BB_CAUSTICS_LAMPS");
    const auto& s = BbSettings::Get();
    return {BC::WithSettings(ReadKnobs(), sun_env, lamps_env,
                             s.graphics_water_caustics_sun_strength.load(std::memory_order_relaxed),
                             s.graphics_water_caustics_lamps_strength.load(std::memory_order_relaxed)),
            sun_env, lamps_env};
}

"""
CC_HELPER_ANCHOR = ("vk::DescriptorImageInfo Info(vk::ImageView view) {\n"
                    "    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};\n}\n")

CC_WANTED_OLD = ("bool Caustics::Wanted() {\n"
                 "    return ReadKnobs().strength > 0.0f || ReadKnobs().lamp_strength > 0.0f;\n}\n")
CC_WANTED_NEW = r"""// bbport (r128b_lrt-caustics-water): the setting's numbers are the header's (one maximum, off by default).
static_assert(BbSettings::WaterCausticsStrengthMax == ::BbCaustics::MaxStrength &&
              BbSettings::WaterCausticsStrengthMin == 0.0f && BbSettings::WaterCausticsStrengthDefault == 0.0f);

bool Caustics::Wanted() {
    const BC::Knobs k = Current().knobs;
    return k.strength > 0.0f || k.lamp_strength > 0.0f;
}

void Caustics::StrengthLine() {
    static StrengthKnob::Line line;
    const InForce now = Current();
    const StrengthKnob::Value sun{now.knobs.strength, now.sun_env};
    const StrengthKnob::Value lamps{now.knobs.lamp_strength, now.lamps_env};
    if (line.Due(LineCalls, sun, lamps)) {
        std::printf("Water caustics (r128b): sun and moon strength %.2f from the %s (%s), lamps strength "
                    "%.2f from the %s (%s)%s\n",
                    double(sun.value), StrengthKnob::SourceName(sun),
                    sun.from_env ? "BB_CAUSTICS" : "graphics_water_caustics_sun_strength",
                    double(lamps.value), StrengthKnob::SourceName(lamps),
                    lamps.from_env ? "BB_CAUSTICS_LAMPS" : "graphics_water_caustics_lamps_strength",
                    sun.value > 0.0f || lamps.value > 0.0f ? "" : "; both 0: nothing is made or drawn");
    }
}

void Caustics::Refresh() {
    const BC::Knobs now = Current().knobs;
    if (now.strength != knobs.strength || now.lamp_strength != knobs.lamp_strength) {
        ++strength_changes;
        knobs.strength = now.strength;
        knobs.lamp_strength = now.lamp_strength;
    }
}
"""

CC_CTOR_OLD = "      knobs{ReadKnobs()} {\n    // The pipeline and the counters are made here, at the start (no compile in play).\n"
CC_CTOR_NEW = ("      knobs{Current().knobs} { // bbport (r128b_lrt-caustics-water): setting or variable\n"
               "    // The pipeline and the counters are made here, at the start or, with the setting, at the\n"
               "    // first frame a strength is above 0 (r128b; as the heat haze, r97e).\n")

CC_IDLE_ANCHOR = "    armed = false;\n    applied_depth = gbuffer_depth;\n"
CC_IDLE_BLOCK = r"""    if (!SunWanted() && !LampsWanted() && !knobs.show) { // bbport (r128b_lrt-caustics-water)
        ++idle_passes; // both strengths went to 0 (the slider): no counts, no dispatch, no line
        return;
    }
"""

CC_REPORT_ANCHOR = "    stats = {};\n}\n\n} // namespace Vulkan\n"
CC_REPORT_BLOCK = r"""    // bbport (r128b_lrt-caustics-water): the strengths now and how often the setting moved them
    BbReport::Printf("Water caustics (r128b): strengths now sun %.2f, lamps %.2f; %u changes of them since the "
                     "start, %u passes skipped with both at 0\n",
                     double(knobs.strength), double(knobs.lamp_strength), strength_changes, idle_passes);
"""

EFFECTS_ANCHOR = ("            halation->Apply(upscaler->SceneColor(), strength);\n"
                  "        }\n"
                  "    }\n")
EFFECTS_BLOCK = r"""    // bbport (r128b_lrt-caustics-water): the water caustics' strengths are settings
    // (graphics_water_caustics_sun_strength, graphics_water_caustics_lamps_strength; BB_CAUSTICS and
    // BB_CAUSTICS_LAMPS win when set), read every frame. The Caustics is made at the start when a strength is
    // above 0 and here, at the first frame one is, when it was not; it is kept. At 0 its passes return at
    // once. Without an object at 0: four relaxed loads and a few compares.
    if (compute_hash == upscaler->TriggerHash()) {
        Caustics::StrengthLine();
        if (!caustics && Caustics::Wanted()) {
            caustics = std::make_unique<Caustics>(instance, scheduler, texture_cache, runtime,
                                                  *scene_targets, *camera_motion, *point_shadow,
                                                  upscaler->Enabled());
        }
        if (caustics) {
            caustics->Refresh();
        }
    }
"""

SETTINGS_H_CONST_ANCHOR = "inline constexpr float LampFlickerSteadyDefault = 1.0f, LampFlickerOnGameDefault = 0.0f;\n"
SETTINGS_H_CONST = ("// bbport (r128b_lrt-caustics-water): the water caustics' strengths (live; 0 = off, the default; a set\n"
                    "// BB_CAUSTICS (sun and moon) or BB_CAUSTICS_LAMPS (lamps) wins). Tied to BbCaustics::MaxStrength by a\n"
                    "// static_assert in vk_caustics.cpp.\n"
                    "inline constexpr float WaterCausticsStrengthMin = 0.0f, WaterCausticsStrengthMax = 4.0f,\n"
                    "                       WaterCausticsStrengthDefault = 0.0f;\n")
SETTINGS_H_ATOMIC_ANCHOR = ("    std::atomic<float> graphics_lamp_flicker_on_game_strength{LampFlickerOnGameDefault}; "
                            "// 0..1, flame lamps the game changes; 0: left alone\n")
SETTINGS_H_ATOMIC = (
    "    std::atomic<float> graphics_water_caustics_sun_strength{WaterCausticsStrengthDefault};   // 0..4, bbport (r128b): sun and moon; 0: off\n"
    "    std::atomic<float> graphics_water_caustics_lamps_strength{WaterCausticsStrengthDefault}; // 0..4, bbport (r128b): lamps; 0: off\n")

SETTINGS_C_PARSE_ANCHOR = (
    '    } else if (key == "graphics_lamp_flicker_on_game_strength") {\n'
    '        v.graphics_lamp_flicker_on_game_strength =\n'
    '            Clamp(std::isfinite(f) ? f : LampFlickerOnGameDefault, LampFlickerStrengthMin, LampFlickerStrengthMax);\n')
SETTINGS_C_PARSE = (
    '    } else if (key == "graphics_water_caustics_sun_strength") { // bbport (r128b_lrt-caustics-water)\n'
    '        v.graphics_water_caustics_sun_strength =\n'
    '            Clamp(std::isfinite(f) ? f : WaterCausticsStrengthDefault, WaterCausticsStrengthMin, WaterCausticsStrengthMax);\n'
    '    } else if (key == "graphics_water_caustics_lamps_strength") {\n'
    '        v.graphics_water_caustics_lamps_strength =\n'
    '            Clamp(std::isfinite(f) ? f : WaterCausticsStrengthDefault, WaterCausticsStrengthMin, WaterCausticsStrengthMax);\n')
SETTINGS_C_PUT_ANCHOR = ('    put("graphics_lamp_flicker_on_game_strength", fixed(v.graphics_lamp_flicker_on_game_strength, 2));\n')
SETTINGS_C_PUT = ('    put("graphics_water_caustics_sun_strength", fixed(v.graphics_water_caustics_sun_strength, 2)); // bbport (r128b)\n'
                  '    put("graphics_water_caustics_lamps_strength", fixed(v.graphics_water_caustics_lamps_strength, 2));\n')


def overlay_row(key, lo, hi, env, t, h):
    return ('    if (const char* label = Item("%s",\n'
            '                                 "%s")) {\n'
            '        Slider(label, s.%s, BbSettings::%s,\n'
            '               BbSettings::%s, "%%.2f", ImGuiSliderFlags_AlwaysClamp);\n'
            '        Hint(BbSettings::MenuText(\n%s,\n%s));\n'
            '        EnvNote("%s");\n'
            '    }\n') % (EN[t], RU[t], key, lo, hi, cpp_lit(EN[h], 12), cpp_lit(RU[h], 12), env)


OVERLAY_ANCHOR = '        EnvNote("BB_HEAT_HAZE");\n    }\n'
OVERLAY_BLOCK = (
    "    // bbport (r128b_lrt-caustics-water): the water caustics' strengths (r107), live: the renderer reads each\n"
    "    // every frame and makes its pass at the first frame above 0. A set BB_CAUSTICS (sun and moon) or\n"
    "    // BB_CAUSTICS_LAMPS (lamps) wins over its slider (EnvNote). 0 is the default: off.\n"
    '    Section("%s",\n            "%s");\n' % (EN["sec"], RU["sec"]) +
    overlay_row("graphics_water_caustics_lamps_strength", "WaterCausticsStrengthMin", "WaterCausticsStrengthMax",
                "BB_CAUSTICS_LAMPS", "t1", "h1") +
    overlay_row("graphics_water_caustics_sun_strength", "WaterCausticsStrengthMin", "WaterCausticsStrengthMax",
                "BB_CAUSTICS", "t2", "h2"))

T_SETTINGS_ANCHOR = ("    // bbport (r109a_strength-settings-engine): the halation's and the lamp flicker's strengths.\n")
T_SETTINGS_BLOCK = r"""    // bbport (r128b_lrt-caustics-water): the water caustics' strengths. Nothing above sets them: the default 0
    // (off); written back; read; saved after a change; a value outside 0..4 is the nearest end; a text that is
    // no number is 0; a value that is not finite is the default.
    static_assert(BbSettings::WaterCausticsStrengthMin == 0.0f && BbSettings::WaterCausticsStrengthMax == 4.0f &&
                  BbSettings::WaterCausticsStrengthDefault == 0.0f);
    assert(s.graphics_water_caustics_sun_strength == BbSettings::WaterCausticsStrengthDefault &&
           s.graphics_water_caustics_lamps_strength == BbSettings::WaterCausticsStrengthDefault);
    BbSettings::Save();
    assert(Read(path).find("graphics_water_caustics_sun_strength=0.00\n") != std::string::npos &&
           Read(path).find("graphics_water_caustics_lamps_strength=0.00\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_water_caustics_sun_strength=1.5\n"
                                        "graphics_water_caustics_lamps_strength=2.25\n"; }
    BbSettings::Load();
    assert(s.graphics_water_caustics_sun_strength == 1.5f && s.graphics_water_caustics_lamps_strength == 2.25f);
    s.graphics_water_caustics_sun_strength = 4.0f;
    s.graphics_water_caustics_lamps_strength = 0.5f;
    BbSettings::Save();
    assert(Read(path).find("graphics_water_caustics_sun_strength=4.00\n") != std::string::npos &&
           Read(path).find("graphics_water_caustics_lamps_strength=0.50\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_water_caustics_sun_strength=9\n"
                                        "graphics_water_caustics_lamps_strength=-1\n"; }
    BbSettings::Load();
    assert(s.graphics_water_caustics_sun_strength == BbSettings::WaterCausticsStrengthMax &&
           s.graphics_water_caustics_lamps_strength == 0.0f);
    { std::ofstream file(path); file << "graphics_water_caustics_sun_strength=abc\n"
                                        "graphics_water_caustics_lamps_strength=2\n"; }
    BbSettings::Load();
    assert(s.graphics_water_caustics_sun_strength == 0.0f && s.graphics_water_caustics_lamps_strength == 2.0f);
    { std::ofstream file(path); file << "graphics_water_caustics_sun_strength=nan\n"
                                        "graphics_water_caustics_lamps_strength=inf\n"; }
    s.graphics_water_caustics_sun_strength = 3.0f; // not the default before this Load
    s.graphics_water_caustics_lamps_strength = 3.0f;
    BbSettings::Load();
    assert(s.graphics_water_caustics_sun_strength == BbSettings::WaterCausticsStrengthDefault &&
           s.graphics_water_caustics_lamps_strength == BbSettings::WaterCausticsStrengthDefault);
    BbSettings::Save();
"""

T_CAUSTICS_ANCHOR = "    // The pattern's mean is 1 (PatternMean), its values from 0 to 1 / PatternMean.\n"
T_CAUSTICS_BLOCK = r"""    // bbport (r128b_lrt-caustics-water): the setting as a strength, and the knobs with it. A variable that is set
    // and not empty decides for its channel (also 0, also text); else the setting (0..MaxStrength, 0 for what is
    // not finite or not above 0); show, unreadable and world stay the environment's.
    assert(SettingOf(0.0f) == 0.0f && SettingOf(-1.0f) == 0.0f && SettingOf(1.5f) == 1.5f);
    assert(SettingOf(9.0f) == MaxStrength && SettingOf(std::nanf("")) == 0.0f && SettingOf(INFINITY) == 0.0f);
    {
        const Knobs none = Parse(nullptr, nullptr);
        const Knobs off = WithSettings(none, false, false, 0.0f, 0.0f);
        assert(off.strength == 0.0f && off.lamp_strength == 0.0f && !off.show);
        const Knobs set = WithSettings(none, false, false, 1.0f, 2.5f);
        assert(set.strength == 1.0f && set.lamp_strength == 2.5f && GainOf(set) == Gain);
        const Knobs envs = WithSettings(Parse("0", "0.5"), true, true, 4.0f, 4.0f); // the variables decide
        assert(envs.strength == 0.0f && envs.lamp_strength == 0.5f);
        const Knobs half = WithSettings(Parse("2", nullptr), true, false, 4.0f, 3.0f); // sun env, lamps setting
        assert(half.strength == 2.0f && half.lamp_strength == 3.0f);
        const Knobs text = WithSettings(Parse("yes", nullptr), true, false, 4.0f, 0.0f);
        assert(text.strength == 0.0f && text.unreadable && text.lamp_strength == 0.0f);
        const Knobs show = WithSettings(Parse(nullptr, "show"), false, true, 2.0f, 4.0f); // show stays, lamps env
        assert(show.show && show.strength == 2.0f && show.lamp_strength == 1.0f);
        assert(WithSettings(none, false, false, 9.0f, 9.0f).strength == MaxStrength);
        assert(WithSettings(Parse("1", "1"), true, true, 4.0f, 4.0f).strength == 1.0f); // as before r128b
    }
"""

README_PARA_ANCHOR = "### Water caustics (in development)\n"
README_PARA = (
    "\nThe two strengths are also settings, live: the `lantern.ini` keys `graphics_water_caustics_sun_strength` (the sun and "
    "moon) and `graphics_water_caustics_lamps_strength` (the lamps), 0 to 4, default `0` (off), with two sliders in the "
    "in-game menu (**Insert**, section Water caustics) and in the launcher (Graphics > Lighting). `BB_CAUSTICS` (sun and "
    "moon) and `BB_CAUSTICS_LAMPS` (lamps), when set and not empty, win over their key (also with `0` or text that is "
    "no number: off), read once when the game starts; the test view (`show`) and `BB_CAUSTICS_WORLD` stay environment "
    "only (and `BB_CAUSTICS_WORLD` needs a lamp strength above 0 at the start). With both strengths at 0 and no "
    "variable nothing is made; the pipeline and its 7 KB buffer are made at the start, or at the first frame a strength "
    "goes above 0 (the upscaler's trigger draw; one frame may take longer), and kept; with both back at 0 the pass "
    "returns at its first line. The log has a `Water caustics (r128b):` line with both strengths and where each came "
    "from (setting or environment) at the first frame, and again after a change (at most once every 600 frames), and "
    "one with the counts (changes, passes skipped with both at 0) after the `Water caustics (r107)` lines. Like the "
    "variables, the sliders act only with the upscaler on and only where the pass finds water (a mirrored water "
    "plane, or puddles for the lamps), not under open sky alone.\n")
README_ROWS_ANCHOR = "| `BB_CAUSTICS` | `1`: on; a number above 0 is the strength, up to 4 (0, unset"
README_ROWS = (
    "| `graphics_water_caustics_sun_strength` | `lantern.ini` key: the strength of the sun and moon caustics, 0 to 4, "
    "read every frame, with the net `BB_CAUSTICS` describes; `BB_CAUSTICS` wins over it when set and not empty. A "
    "value outside the range is the nearest end, one that is not a finite number is `0`, text that is no number is "
    "`0` | `0` |\n"
    "| `graphics_water_caustics_lamps_strength` | `lantern.ini` key: the strength of the lamps' caustics, 0 to 4, "
    "read every frame, with the net `BB_CAUSTICS_LAMPS` describes (up to 1 the lamps' light, above 1 the look); "
    "`BB_CAUSTICS_LAMPS` wins over it when set and not empty. A value outside the range is the nearest end, one that "
    "is not a finite number is `0`, text that is no number is `0` | `0` |\n")

INI_ANCHOR = '            ("graphics_heat_haze_strength", "0.00"),\n'
INI_BLOCK = ("            // r128b: the water caustics' strengths, off by default (BbSettings::WaterCausticsStrengthDefault).\n"
             '            ("graphics_water_caustics_lamps_strength", "0.00"),\n'
             '            ("graphics_water_caustics_sun_strength", "0.00"),\n')
GP_ANCHOR = '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Heat haze"), 2, "graphics_heat_haze_strength", 0);\n'
GP_BLOCK = ("            // r128b: the water caustics, off by default (0); the in-game menu has the same sliders, live.\n"
            '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Water caustics from lamps"), 4, "graphics_water_caustics_lamps_strength", 0);\n'
            '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("Water caustics from the sun and moon"), 4, "graphics_water_caustics_sun_strength", 0);\n')

# ---------------------------------------------------------------- the edit list
EDITS = []  # (path, kind, old, new, block)  kind: after | before | replace


def INS_AFTER(path, anchor, block):
    EDITS.append((path, "after", anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, "before", anchor, block + anchor, block))


def REPLACE(path, old, new):
    EDITS.append((path, "replace", old, new, new))


INS_BEFORE(PARAMS, PARAMS_ANCHOR, PARAMS_BLOCK)
INS_AFTER(CH, CH_ANCHOR1, CH_DECL)
INS_AFTER(CH, CH_ANCHOR2, CH_MEMBERS)
INS_AFTER(CC, CC_INCLUDE_ANCHOR, CC_INCLUDE)
INS_BEFORE(CC, CC_HELPER_ANCHOR, CC_HELPER)
REPLACE(CC, CC_WANTED_OLD, CC_WANTED_NEW)
REPLACE(CC, CC_CTOR_OLD, CC_CTOR_NEW)
# review fix: after applied_depth/applied_frame are set, so an idle pass does not re-arm at every
# blended draw of the same G-buffer pass (OnGBufferDraw compares them); before the counts.
INS_BEFORE(CC, "    ++stats.calls;" + chr(10), CC_IDLE_BLOCK)
INS_BEFORE(CC, CC_REPORT_ANCHOR, CC_REPORT_BLOCK)
INS_AFTER(EFFECTS, EFFECTS_ANCHOR, EFFECTS_BLOCK)
INS_AFTER(SETTINGS_H, SETTINGS_H_CONST_ANCHOR, SETTINGS_H_CONST)
INS_AFTER(SETTINGS_H, SETTINGS_H_ATOMIC_ANCHOR, SETTINGS_H_ATOMIC)
INS_AFTER(SETTINGS_C, SETTINGS_C_PARSE_ANCHOR, SETTINGS_C_PARSE)
INS_AFTER(SETTINGS_C, SETTINGS_C_PUT_ANCHOR, SETTINGS_C_PUT)
INS_AFTER(OVERLAY, OVERLAY_ANCHOR, OVERLAY_BLOCK)
for _table, _anchor in TABLES:
    INS_AFTER(I18N, _anchor, table_block(_table))
INS_AFTER(INI, INI_ANCHOR, INI_BLOCK)
for _gp in (GP_B, GP_L):
    INS_AFTER(_gp, GP_ANCHOR, GP_BLOCK)
for _code, _anchor in LOC_ANCHOR.items():
    _t = LAUNCHER[_code]
    INS_AFTER(LOC + _code + ".json", _anchor, "".join('  "%s": "%s",\n' % (EN[k], _t[k]) for k in ("t1", "t2")))
INS_BEFORE(T_SETTINGS, T_SETTINGS_ANCHOR, T_SETTINGS_BLOCK)
INS_BEFORE(T_CAUSTICS, T_CAUSTICS_ANCHOR, T_CAUSTICS_BLOCK)
INS_AFTER(README, README_PARA_ANCHOR, README_PARA)
INS_BEFORE(README, README_ROWS_ANCHOR, README_ROWS)


# ---------------------------------------------------------------- machinery
def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


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


def text_checks(texts):
    i18n = texts[I18N]
    glyphs = {int(x.strip()[2:], 16) for x in
              open(os.path.join(ROOT, GLYPHS), encoding="utf-8").read().split(",") if x.strip()}
    for name, _ in TABLES:
        span = table_span(i18n, name)
        for k in ("sec", "t1", "t2", "h1", "h2"):
            line = '    {"%s", "%s"},\n' % (EN[k], TR[name][k])
            if span.count(line) != 1 or span.count('{"%s"' % EN[k]) != 1:
                raise SystemExit("text check: %s: %r not found exactly once" % (name, EN[k][:40]))
    zh = "".join(TR["kChinese"].values())
    missing = sorted({c for c in zh if ord(c) > 0x7e and ord(c) not in glyphs})
    if missing:
        raise SystemExit("text check: Chinese menu text has characters the menu font lacks: %s" % "".join(missing))
    joined = re.sub(r'"\s*\n\s*"', "", texts[OVERLAY])
    for k in ("sec", "t1", "t2", "h1", "h2"):
        for text in (EN[k], RU[k]):
            if joined.count('"%s"' % text) != 1:
                raise SystemExit("text check: overlay: %r not found exactly once" % text[:40])
        if i18n.count('{"%s"' % EN[k]) != 8:
            raise SystemExit("text check: %r is not in all 8 tables" % EN[k][:40])
    for env in ("BB_CAUSTICS", "BB_CAUSTICS_LAMPS"):
        if texts[OVERLAY].count('EnvNote("%s");' % env) != 1:
            raise SystemExit("text check: overlay: EnvNote(%s) not once" % env)
    for path in (GP_B, GP_L):
        t = texts[path]
        for key, title in ((KEY_LAMPS, EN["t1"]), (KEY_SUN, EN["t2"])):
            needle = 'StrengthSlider(SymbolRegular.Lightbulb24, L.T("%s"), 4, "%s", 0);' % (title, key)
            if t.count(needle) != 1:
                raise SystemExit("text check: %s: row %r not once" % (path, needle))
    for code in LOC_ANCHOR:
        data = json.loads(texts[LOC + code + ".json"])
        zhdata = json.loads(texts[LOC + "zh-CN.json"])
        for k in ("t1", "t2"):
            if data.get(EN[k]) != LAUNCHER[code][k] or EN[k] not in zhdata:
                raise SystemExit("text check: %s.json: %r wrong or missing" % (code, EN[k]))
    ini = texts[INI]
    for k in (KEY_LAMPS, KEY_SUN):
        if ini.count('("%s", "0.00"),' % k) != 1:
            raise SystemExit("text check: IniFile.cs default %s" % k)
    # the C++ pieces the compiler would check first
    cc = texts[CC]
    for needle in ("bool Caustics::Wanted()", "void Caustics::StrengthLine()", "void Caustics::Refresh()",
                   "InForce Current()", "knobs{Current().knobs}"):
        if cc.count(needle) != 1:
            raise SystemExit("text check: vk_caustics.cpp: %r not once" % needle)
    if "ReadKnobs()" not in cc:
        raise SystemExit("text check: vk_caustics.cpp lost ReadKnobs")
    for key in (KEY_SUN, KEY_LAMPS):
        if texts[SETTINGS_H].count(key + "{") != 1 or texts[SETTINGS_C].count('key == "%s"' % key) != 1 \
                or texts[SETTINGS_C].count('put("%s"' % key) != 1:
            raise SystemExit("text check: settings: %s not once in the struct, the parse and the save" % key)
        if texts[README].count("`%s`" % key) < 2:
            raise SystemExit("text check: README: %s" % key)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R128B_ROOT)" % ROOT)
    needs = {SETTINGS_H: "HalationStrengthDefault", I18N: '"Halation strength"'}
    for path, needle in needs.items():
        if needle not in load(path)[2]:
            raise SystemExit("REFUSED: r109a / r109b are not applied (%s lacks %s): apply them first" % (path, needle))
    if "HeatHazeStrengthDefault" not in load(SETTINGS_H)[2]:
        raise SystemExit("REFUSED: r97e_heat-haze-option is not applied (its rows are anchors)")
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
        raise SystemExit("REFUSED: mixed state: " + ", ".join("%s %s" % (p[0], p[4]) for p in plan))
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
                tmp = full + ".r128btmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r128btmp"
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
