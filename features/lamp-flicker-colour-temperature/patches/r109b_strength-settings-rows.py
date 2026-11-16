# r109b_strength-settings-rows: FEATURE patch (the mechanical half of r109; the engine half is
# r109a_strength-settings-engine.py, which must be applied first). Owner, 2026-11-15 22:10, verbatim:
# "The default halation should be strength 1 but should have a slider to adjust the strength. I think
# the same for light flicker as well, default to off on already flickering lamps but then we can turn
# it on with a strength slider".
#
# What it does (rows only: no engine logic, no parse, no halation or flicker code is touched):
#  - Overlay (bbport_overlay.cpp, end of PictureSection, after the Drawn look rows, outside the
#    "game's code" switch): a section "Light glow and flicker" with three live sliders
#    (Halation strength 0..2, Lamp flicker strength 0..1, Flicker strength on already flickering
#    lamps 0..1), each with a "Live." hint and EnvNote for the variable that wins when it is set
#    (BB_HALATION, BB_LAMP_FLICKER, BB_LAMP_FLICKER_ON_GAME), bounds from the BbSettings constants.
#  - bbport_menu_i18n.cpp: the section title, the three row titles and the three hints in all eight
#    tables (Spanish, Portuguese, French, German, Italian, Polish, Turkish, Chinese; the Chinese text
#    uses only characters of third_party/fonts/LanternMenuSC-glyphs.txt, checked here). Every
#    non-English text needs a native speaker's check.
#  - Both launchers (BloodborneLauncher WPF and LanternLauncher Avalonia, Views/GraphicsPage.cs, two
#    separate copies): three sliders after "Lamp fog glow size" (Graphics > Lighting) made by a new
#    StrengthSlider, which keeps the slider and, after Ini.Refresh (RefreshPerformance), shows it
#    again from lantern.ini without writing it back (ShowStrengths, as ShowLampSoftness does). The
#    shown value is what the engine reads (float(atof), then r109a's rule): the number the text
#    begins with ("1.5x" is 1.5), 0 when it begins with none, the default for inf, nan or a number
#    too large for a float, outside the range the nearest end.
#  (.fixed, review 2026-11-15 23:10: the launcher parse mirrors atof's leading number, not
#    double.TryParse of the whole text; the Chinese flicker hint no longer names the hand lantern
#    (提灯), a lamp the game flickers itself, as a steady lamp.)
#  - IniFile.cs Defaults (one copy: LanternLauncher compiles the same file): 1.00, 1.00, 0.00.
#  - Localization/*.json (13 files, one set for both launchers): the three row titles.
#  - Looks (rule 10): the three keys are NOT look knobs (a look sets the picture's knobs; Original
#    look and Game's own picture leave halation and flicker as the player set them). A LooksChecks
#    check says so and pins the IniFile defaults to the engine's literal defaults (rule 11; the engine
#    side is pinned by test_settings.cpp at 1.00, 1.00, 0.00 and by the BbSettings constants).
#  - README.md: one sentence under each of the two section headings (Lamp flicker, Halation) saying
#    where the sliders are. The key rows r109a wrote are not touched, so r109a's own check still reads
#    "applied".
#  build.sh needs no line: settings-test (C++20, -Werror, bbport_menu_i18n.cpp) already compiles
#  the i18n tables and r109a's settings test.
#
# Off by default / cost: no new engine code; the rows add three ImGui slider calls drawn only while
# the menu is open, and three launcher sliders. The settings they write are read by r109a's code.
#
# Use: python -I -X utf8 r109b_strength-settings-rows.py check | apply | revert
# Root: R109B_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in
# r109b_backup next to this script. Each edit inserts a block right after an anchor found exactly
# once (the anchor stays whole); revert removes the block where it is found by itself, exactly once.
# Needs r109a applied (apply refuses without it; check says so and skips the README edits). Revert
# this one before r109a.
import io, json, os, re, sys

ROOT = os.environ.get("R109B_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r109b_backup")
SH = "engine/gpu/shim/"
OVERLAY = SH + "bbport_overlay.cpp"
I18N = SH + "bbport_menu_i18n.cpp"
SETTINGS_H = SH + "bbport_settings.h"
GLYPHS = "engine/gpu/third_party/fonts/LanternMenuSC-glyphs.txt"
LW = "launcher/windows/"
GP_B = LW + "BloodborneLauncher/Views/GraphicsPage.cs"
GP_L = LW + "LanternLauncher/Views/GraphicsPage.cs"
INI = LW + "BloodborneLauncher/Core/IniFile.cs"
LOOKS_CHECKS = LW + "tests/LooksChecks/Program.cs"
LOC = LW + "BloodborneLauncher/Localization/"
README = "README.md"

# ---------------------------------------------------------------- texts
EN = {
    "t1": "Halation strength",
    "t2": "Lamp flicker strength",
    "t3": "Flicker strength on already flickering lamps",
    "sec": "Light glow and flicker",
    "h1": "Live, default 1. A soft red-orange glow around the brightest small lights: lamps, candles, "
          "the torch flame, bright windows and the moon. 0 draws nothing, 2 is twice the default. It is "
          "drawn before the upscaler, so with no upscaler nothing is drawn.",
    "h2": "Live, default 1. How much flame lamps that the game keeps steady (candles, lanterns, torches, "
          "street gas lamps) flicker, and how much their light warms as it dims: at 1 their light moves "
          "by up to 14% either way. 0 is off.",
    "h3": "Live, off by default. The same flicker for flame lamps whose colour or reach the game already "
          "changes itself, added on top of the game's own flicker: at 1 their light also moves by up to "
          "14% either way. 0 leaves them as the game made them.",
}
RU = {
    "t1": "Сила ореола (halation)",
    "t2": "Сила мерцания ламп",
    "t3": "Сила мерцания у ламп, которые уже мерцают",
    "sec": "Свечение света и мерцание",
    "h1": "Работает сразу, по умолчанию 1. Мягкое красно-оранжевое свечение вокруг самых ярких небольших "
          "источников света: ламп, свечей, пламени факела, ярких окон и луны. 0 — ничего не рисуется, "
          "2 — вдвое больше значения по умолчанию. Рисуется до апскейлера, поэтому без апскейлера "
          "ничего не рисуется.",
    "h2": "Работает сразу, по умолчанию 1. Насколько мерцают лампы с живым огнём, которые игра держит "
          "ровными (свечи, фонари, факелы, уличные газовые лампы), и насколько теплеет их свет при "
          "затухании: при 1 их свет меняется не более чем на 14% в обе стороны. 0 — выкл.",
    "h3": "Работает сразу, по умолчанию выкл. То же мерцание для ламп с живым огнём, у которых игра уже "
          "сама меняет цвет или радиус света, поверх собственного мерцания игры: при 1 их свет "
          "дополнительно меняется не более чем на 14% в обе стороны. 0 оставляет их такими, какими их "
          "сделала игра.",
}
# The eight menu tables: (table name, anchor = the "Lamp fog glow size" entry and the line after it).
TABLES = [
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
        "t1": "Intensidad de la halación",
        "t2": "Intensidad del parpadeo de las lámparas",
        "t3": "Intensidad del parpadeo en lámparas que ya parpadean",
        "sec": "Brillo de luces y parpadeo",
        "h1": "Al instante, por defecto 1. Un suave resplandor rojo anaranjado alrededor de las luces "
              "pequeñas más brillantes: lámparas, velas, la llama de la antorcha, ventanas luminosas y la "
              "luna. 0 no dibuja nada, 2 es el doble del valor por defecto. Se dibuja antes del "
              "escalador, así que sin escalador no se dibuja nada.",
        "h2": "Al instante, por defecto 1. Cuánto parpadean las lámparas de llama que el juego mantiene "
              "estables (velas, faroles, antorchas, farolas de gas) y cuánto se calienta su luz al "
              "atenuarse: con 1 su luz varía hasta un 14 % en ambos sentidos. 0 lo desactiva.",
        "h3": "Al instante, desactivado por defecto. El mismo parpadeo para las lámparas de llama cuyo "
              "color o alcance ya cambia el juego por sí mismo, añadido al parpadeo propio del juego: con "
              "1 su luz también varía hasta un 14 % en ambos sentidos. 0 las deja como las hizo el juego.",
    },
    "kPortugueseBrazil": {
        "t1": "Intensidade da halação",
        "t2": "Intensidade da oscilação das lâmpadas",
        "t3": "Intensidade da oscilação em lâmpadas que já oscilam",
        "sec": "Brilho das luzes e oscilação",
        "h1": "Na hora, padrão 1. Um brilho suave vermelho-alaranjado ao redor das luzes pequenas mais "
              "intensas: lâmpadas, velas, a chama da tocha, janelas iluminadas e a lua. 0 não desenha "
              "nada, 2 é o dobro do padrão. É desenhado antes do upscaler, então sem upscaler nada é "
              "desenhado.",
        "h2": "Na hora, padrão 1. Quanto oscilam as lâmpadas de chama que o jogo mantém estáveis (velas, "
              "lampiões, tochas, postes a gás) e quanto a luz delas esquenta ao diminuir: com 1 a luz "
              "varia até 14% para mais ou para menos. 0 desliga.",
        "h3": "Na hora, desligado por padrão. A mesma oscilação para lâmpadas de chama cuja cor ou "
              "alcance o próprio jogo já altera, somada à oscilação do jogo: com 1 a luz delas também "
              "varia até 14% para mais ou para menos. 0 as deixa como o jogo as fez.",
    },
    "kFrench": {
        "t1": "Intensité de l'halation",
        "t2": "Intensité du scintillement des lampes",
        "t3": "Intensité du scintillement des lampes qui scintillent déjà",
        "sec": "Lueur des lumières et scintillement",
        "h1": "Immédiat, 1 par défaut. Une douce lueur rouge-orangé autour des petites lumières les plus "
              "vives : lampes, bougies, flamme de la torche, fenêtres éclairées et lune. 0 ne dessine "
              "rien, 2 vaut le double de la valeur par défaut. Elle est dessinée avant l'upscaler : sans "
              "upscaler, rien n'est dessiné.",
        "h2": "Immédiat, 1 par défaut. Intensité du scintillement des lampes à flamme que le jeu garde "
              "stables (bougies, lanternes, torches, lampadaires à gaz) et du réchauffement de leur "
              "lumière quand elle faiblit : à 1, leur lumière varie jusqu'à 14 % dans un sens ou "
              "l'autre. 0 désactive.",
        "h3": "Immédiat, désactivé par défaut. Le même scintillement pour les lampes à flamme dont le "
              "jeu change déjà lui-même la couleur ou la portée, ajouté au scintillement propre du jeu : "
              "à 1, leur lumière varie aussi jusqu'à 14 % dans un sens ou l'autre. 0 les laisse comme le "
              "jeu les a faites.",
    },
    "kGerman": {
        "t1": "Stärke der Halation",
        "t2": "Stärke des Lampenflackerns",
        "t3": "Flackerstärke bei Lampen, die schon flackern",
        "sec": "Lichtschein und Flackern",
        "h1": "Sofort wirksam, Standard 1. Ein weicher rotorangefarbener Schein um die hellsten kleinen "
              "Lichter: Lampen, Kerzen, die Fackelflamme, helle Fenster und der Mond. 0 zeichnet nichts, "
              "2 ist das Doppelte des Standards. Wird vor dem Upscaler gezeichnet, ohne Upscaler also "
              "nichts.",
        "h2": "Sofort wirksam, Standard 1. Wie stark Flammenlampen flackern, die das Spiel ruhig hält "
              "(Kerzen, Laternen, Fackeln, Gaslaternen), und wie stark ihr Licht beim Dimmen wärmer "
              "wird: bei 1 schwankt ihr Licht um bis zu 14 % nach oben und unten. 0 ist aus.",
        "h3": "Sofort wirksam, standardmäßig aus. Dasselbe Flackern für Flammenlampen, deren Farbe oder "
              "Reichweite das Spiel schon selbst ändert, zusätzlich zum eigenen Flackern des Spiels: bei "
              "1 schwankt ihr Licht zusätzlich um bis zu 14 % nach oben und unten. 0 lässt sie, wie das "
              "Spiel sie gemacht hat.",
    },
    "kItalian": {
        "t1": "Intensità dell'alone (halation)",
        "t2": "Intensità dello sfarfallio delle lampade",
        "t3": "Intensità dello sfarfallio sulle lampade che già sfarfallano",
        "sec": "Bagliore delle luci e sfarfallio",
        "h1": "Subito attivo, 1 di default. Un morbido bagliore rosso-arancio intorno alle piccole luci "
              "più intense: lampade, candele, la fiamma della torcia, finestre luminose e la luna. 0 non "
              "disegna nulla, 2 è il doppio del valore di default. Viene disegnato prima dell'upscaler, "
              "quindi senza upscaler non si disegna nulla.",
        "h2": "Subito attivo, 1 di default. Quanto sfarfallano le lampade a fiamma che il gioco tiene "
              "stabili (candele, lanterne, torce, lampioni a gas) e quanto la loro luce si scalda mentre "
              "si attenua: con 1 la loro luce varia fino al 14% in più o in meno. 0 disattiva.",
        "h3": "Subito attivo, disattivato di default. Lo stesso sfarfallio per le lampade a fiamma di "
              "cui il gioco già cambia da sé il colore o la portata, aggiunto allo sfarfallio proprio del "
              "gioco: con 1 la loro luce varia anche fino al 14% in più o in meno. 0 le lascia come le "
              "ha fatte il gioco.",
    },
    "kPolish": {
        "t1": "Siła halacji",
        "t2": "Siła migotania lamp",
        "t3": "Siła migotania lamp, które już migoczą",
        "sec": "Poświata świateł i migotanie",
        "h1": "Działa od razu, domyślnie 1. Miękka czerwono-pomarańczowa poświata wokół najjaśniejszych "
              "małych świateł: lamp, świec, płomienia pochodni, jasnych okien i księżyca. 0 nie rysuje "
              "nic, 2 to dwukrotność wartości domyślnej. Rysowana przed upscalerem, więc bez upscalera "
              "nic nie jest rysowane.",
        "h2": "Działa od razu, domyślnie 1. Jak mocno migoczą lampy płomieniowe, które gra utrzymuje "
              "stałe (świece, latarnie, pochodnie, lampy gazowe), i jak bardzo ich światło robi się "
              "cieplejsze, gdy słabnie: przy 1 ich światło zmienia się o co najwyżej 14% w obie strony. "
              "0 wyłącza.",
        "h3": "Działa od razu, domyślnie wył. To samo migotanie dla lamp płomieniowych, którym gra sama "
              "już zmienia kolor lub zasięg, dodane do własnego migotania gry: przy 1 ich światło "
              "zmienia się dodatkowo o co najwyżej 14% w obie strony. 0 zostawia je takimi, jak zrobiła "
              "je gra.",
    },
    "kTurkish": {
        "t1": "Halasyon gücü",
        "t2": "Lamba titremesi gücü",
        "t3": "Zaten titreyen lambalarda titreme gücü",
        "sec": "Işık parıltısı ve titreme",
        "h1": "Anında, varsayılan 1. En parlak küçük ışıkların (lambalar, mumlar, meşale alevi, parlak "
              "pencereler ve ay) çevresinde yumuşak, kırmızımsı turuncu bir parıltı. 0 hiçbir şey "
              "çizmez, 2 varsayılanın iki katıdır. Upscaler'dan önce çizilir; upscaler yoksa hiçbir şey "
              "çizilmez.",
        "h2": "Anında, varsayılan 1. Oyunun sabit tuttuğu alevli lambaların (mumlar, fenerler, "
              "meşaleler, gaz sokak lambaları) ne kadar titrediği ve ışıkları sönerken ne kadar "
              "ısındığı: 1'de ışıkları her iki yönde en çok %14 değişir. 0 kapatır.",
        "h3": "Anında, varsayılan olarak kapalı. Rengini veya erişimini oyunun zaten kendisinin "
              "değiştirdiği alevli lambalar için aynı titreme, oyunun kendi titremesinin üzerine "
              "eklenir: 1'de ışıkları ayrıca her iki yönde en çok %14 değişir. 0 onları oyunun yaptığı "
              "gibi bırakır.",
    },
    "kChinese": {
        "t1": "Halation 强度",
        "t2": "灯光闪烁强度",
        "t3": "已闪烁灯光的闪烁强度",
        "sec": "Halation 与灯光闪烁",
        "h1": "立即生效，默认 1。最亮的小光源（灯、火焰、月亮）向外散出的柔和红光。0 为关闭，不绘制任何"
              "内容；2 为默认的 2 倍。在超分辨率算法之前绘制，因此不使用超分辨率算法时不会显示。",
        "h2": "立即生效，默认 1。游戏保持稳定的火焰灯光（如街灯和油灯）闪烁的程度，亮度变暗时光也会变得"
              "更红：为 1 时光的亮度最多上下变化 14%。0 为关闭。",
        "h3": "立即生效，默认关闭。游戏自身已在改变颜色或照射范围的火焰灯光所用的相同闪烁，叠加在游戏本身"
              "的闪烁之上：为 1 时光的亮度还会再最多上下变化 14%。0 保持游戏原本的效果。",
    },
}
# Launcher row titles (the launcher is not limited to the menu font's glyphs).
LAUNCHER = {
    "es": TR["kSpanish"], "pt-BR": TR["kPortugueseBrazil"], "fr": TR["kFrench"], "de": TR["kGerman"],
    "it": TR["kItalian"], "pl": TR["kPolish"], "tr": TR["kTurkish"],
    "zh-CN": {"t1": "光渗（Halation）强度", "t2": "灯光闪烁强度", "t3": "已闪烁灯光的闪烁强度"},
    "zh-TW": {"t1": "光滲（Halation）強度", "t2": "燈光閃爍強度", "t3": "已閃爍燈光的閃爍強度"},
    "ja": {"t1": "ハレーションの強さ", "t2": "ランプのちらつきの強さ", "t3": "すでにちらつくランプのちらつきの強さ"},
    "ko": {"t1": "헐레이션 강도", "t2": "램프 깜빡임 강도", "t3": "이미 깜빡이는 램프의 깜빡임 강도"},
    "ru": {"t1": RU["t1"], "t2": RU["t2"], "t3": RU["t3"]},
    "uk": {"t1": "Сила ореолу (halation)", "t2": "Сила мерехтіння ламп",
           "t3": "Сила мерехтіння ламп, які вже мерехтять"},
}
# The anchor of each json file: the "Lamp fog strength" line (all 13 hold it once).
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
    return "".join('    {"%s", "%s"},\n' % (EN[k], t[k]) for k in ("t1", "t2", "t3", "sec", "h1", "h2", "h3"))


# ---------------------------------------------------------------- the overlay block
def overlay_row(key, lo, hi, env):
    title = {"graphics_halation_strength": "t1", "graphics_lamp_flicker_strength": "t2",
             "graphics_lamp_flicker_on_game_strength": "t3"}[key]
    hint = {"t1": "h1", "t2": "h2", "t3": "h3"}[title]
    return ('    if (const char* label = Item("%s",\n'
            '                                 "%s")) {\n'
            '        Slider(label, s.%s, BbSettings::%s,\n'
            '               BbSettings::%s, "%%.2f", ImGuiSliderFlags_AlwaysClamp);\n'
            '        Hint(BbSettings::MenuText(\n%s,\n%s));\n'
            '        EnvNote("%s");\n'
            '    }\n') % (EN[title], RU[title], key, lo, hi, cpp_lit(EN[hint], 12), cpp_lit(RU[hint], 12), env)


OVERLAY_BLOCK = (
    "    // bbport (r109b_strength-settings-rows): the strength sliders of the halation (r95) and the lamp\n"
    "    // flicker (r96). The renderer reads each every frame, so a slider acts at once; a set environment\n"
    "    // variable wins over its slider (EnvNote). Not under the game's-code switch above: both are the\n"
    "    // renderer's own passes.\n"
    '    Section("%s",\n            "%s");\n' % (EN["sec"], RU["sec"]) +
    overlay_row("graphics_halation_strength", "HalationStrengthMin", "HalationStrengthMax", "BB_HALATION") +
    overlay_row("graphics_lamp_flicker_strength", "LampFlickerStrengthMin", "LampFlickerStrengthMax",
                "BB_LAMP_FLICKER") +
    overlay_row("graphics_lamp_flicker_on_game_strength", "LampFlickerStrengthMin", "LampFlickerStrengthMax",
                "BB_LAMP_FLICKER_ON_GAME"))
OVERLAY_ANCHOR = (
    '            "оставляют больше исходного изображения. При 0 стиль вообще не работает. Применяется "\n'
    '            "сразу."));\n'
    '    }\n')

# ---------------------------------------------------------------- the launcher blocks
FIELDS_ANCHOR = ("        private bool _lampShowing; // ShowLampSoftness is setting the row: nothing is written to "
                 "the ini\n")
FIELDS_BLOCK = (
    "        // r109b: the strength sliders (Graphics > Lighting) the in-game menu moves live; ShowStrengths\n"
    "        // shows them again from lantern.ini and writes nothing back.\n"
    "        private readonly List<System.Action> _showStrengths = new();\n"
    "        private bool _strengthShowing;\n")
METHODS_ANCHOR = ("            SliderRow(icon, title, null, min, max, step, () => ParseDouble(Ini.Get(key, Fmt(fallback)), "
                  "fallback), v => Ini.Set(key, Fmt(v)), into: into);\n")
METHODS_BLOCK = (
    "\n"
    "        /// <summary>A slider for a setting the in-game menu changes live (r109b: the halation and the\n"
    "        /// lamp flicker strengths). It shows what the engine reads (float(atof), then its rule): the\n"
    "        /// number the text begins with (\"1.5x\" is 1.5), 0 when it begins with none, the engine's\n"
    "        /// default (fallback) for inf, nan or a number too large for a float, a value outside the\n"
    "        /// range the nearest end. ShowStrengths sets it again from lantern.ini.</summary>\n"
    "        private void StrengthSlider(SymbolRegular icon, string title, double max, string key, double fallback)\n"
    "        {\n"
    "            double Value()\n"
    "            {\n"
    "                // Ini already trims the value, as atof skips leading blanks.\n"
    '                var number = System.Text.RegularExpressions.Regex.Match(Ini.Get(key, Fmt(fallback)),\n'
    '                    "^([+-]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][+-]?[0-9]+)?|[+-]?(inf|nan))",\n'
    '                    System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant);\n'
    "                if (!number.Success) return 0;\n"
    "                return double.TryParse(number.Value, System.Globalization.NumberStyles.Float,\n"
    "                           System.Globalization.CultureInfo.InvariantCulture, out var read) && float.IsFinite((float)read)\n"
    "                    ? read : fallback;\n"
    "            }\n"
    "            var slider = SliderRow(icon, title, null, 0, max, 0.05, Value, v => { if (!_strengthShowing) Ini.Set(key, Fmt(v)); });\n"
    "            _showStrengths.Add(() => slider.Value = Math.Clamp(Value(), slider.Minimum, slider.Maximum));\n"
    "        }\n"
    "\n"
    "        /// <summary>The strength sliders follow lantern.ini, which the in-game menu changes live. Setting\n"
    "        /// a slider moves it without a write to the ini (the page's own Ws.SaveSoon still runs, as for\n"
    "        /// any move).</summary>\n"
    "        private void ShowStrengths()\n"
    "        {\n"
    "            _strengthShowing = true;\n"
    "            try { foreach (var show in _showStrengths) show(); }\n"
    "            finally { _strengthShowing = false; }\n"
    "        }\n")
ROWS_ANCHOR = ('            IniSlider(SymbolRegular.Lightbulb24, L.T("Lamp fog glow size"), 0.03, 0.2, '
               '"graphics_point_fog_glow_size", step: 0.01, fallback: 0.08);\n')
ROWS_BLOCK = (
    "            // r109b: the halation and the lamp flicker; the in-game menu (Insert) has the same sliders\n"
    "            // and moves them live, so RefreshPerformance shows them again (ShowStrengths).\n"
    '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("%s"), 2, "graphics_halation_strength", 1);\n'
    '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("%s"), 1, "graphics_lamp_flicker_strength", 1);\n'
    '            StrengthSlider(SymbolRegular.Lightbulb24, L.T("%s"), 1, "graphics_lamp_flicker_on_game_strength", 0);\n'
    % (EN["t1"], EN["t2"], EN["t3"]))
REFRESH_ANCHOR = "            ShowLampSoftness();\n"
REFRESH_BLOCK = "            ShowStrengths();\n"

INI_ANCHOR = '            ("graphics_point_fog_glow_size", "0.08"),\n'
INI_BLOCK = (
    "            // Graphics > Lighting: the halation and the lamp flicker strengths, the engine's defaults\n"
    "            // (BbSettings::HalationStrengthDefault, LampFlickerSteadyDefault, LampFlickerOnGameDefault).\n"
    '            ("graphics_halation_strength", "1.00"),\n'
    '            ("graphics_lamp_flicker_strength", "1.00"),\n'
    '            ("graphics_lamp_flicker_on_game_strength", "0.00"),\n')

CHECK_ANCHOR = ('    "A lamp shadow softness choice does not say what it changes in a note the row shows whole");\n')
CHECK_BLOCK = (
    "// The strength sliders (Graphics > Lighting; r109b): lantern.ini settings the engine reads every frame,\n"
    "// starting at its defaults: halation 1, flicker on lamps the game keeps steady 1, flicker on lamps the\n"
    "// game already flickers 0 (BbSettings::HalationStrengthDefault, LampFlickerSteadyDefault,\n"
    "// LampFlickerOnGameDefault; engine/tests/test_settings.cpp pins the same 1.00, 1.00, 0.00). They are in\n"
    "// no look: a look sets the picture's knobs, and these are effects of their own that a look leaves as\n"
    "// the player set them (Original look and Game's own picture do not switch the halation or the flicker).\n"
    'foreach (var (strengthKey, strengthStart) in new[] { ("graphics_halation_strength", "1.00"), '
    '("graphics_lamp_flicker_strength", "1.00"), ("graphics_lamp_flicker_on_game_strength", "0.00") })\n'
    "{\n"
    "    Require(IniFile.Defaults.Count(d => d.Key == strengthKey) == 1 &&\n"
    "            IniFile.Defaults.Single(d => d.Key == strengthKey).Value == strengthStart,\n"
    '        strengthKey + ": not in the settings defaults once, at the engine\'s default");\n'
    '    Require(!knobs.Contains(strengthKey), strengthKey + ": a strength slider is part of a look");\n'
    "}\n")

README_HAL_ANCHOR = "### Halation (in development)\n"
README_HAL_BLOCK = ("\nThe strength has a slider in the in-game menu (**Insert**, section Light glow and flicker, "
                    "changes at once) and in the launcher (Graphics > Lighting).\n")
README_FLK_ANCHOR = "### Lamp flicker (in development)\n"
README_FLK_BLOCK = ("\nBoth strengths have a slider in the in-game menu (**Insert**, section Light glow and "
                    "flicker, changes at once) and in the launcher (Graphics > Lighting).\n")

# ---------------------------------------------------------------- the edit list
EDITS = []  # (path, anchor, new, block)


def INS_AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


INS_AFTER(OVERLAY, OVERLAY_ANCHOR, OVERLAY_BLOCK)
for _table, _anchor in TABLES:
    INS_AFTER(I18N, _anchor, table_block(_table))
for _gp in (GP_B, GP_L):
    INS_AFTER(_gp, FIELDS_ANCHOR, FIELDS_BLOCK)
    INS_AFTER(_gp, ROWS_ANCHOR, ROWS_BLOCK)
    INS_AFTER(_gp, METHODS_ANCHOR, METHODS_BLOCK)
    INS_AFTER(_gp, REFRESH_ANCHOR, REFRESH_BLOCK)
INS_AFTER(INI, INI_ANCHOR, INI_BLOCK)
INS_AFTER(LOOKS_CHECKS, CHECK_ANCHOR, CHECK_BLOCK)
for _code, _anchor in LOC_ANCHOR.items():
    _t = LAUNCHER[_code]
    INS_AFTER(LOC + _code + ".json", _anchor,
              "".join('  "%s": "%s",\n' % (EN[k], _t[k]) for k in ("t1", "t2", "t3")))
INS_AFTER(README, README_HAL_ANCHOR, README_HAL_BLOCK)
INS_AFTER(README, README_FLK_ANCHOR, README_FLK_BLOCK)

NEEDS_R109A = {README}


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
    done = sum(text.count(e[3]) == 1 for e in eds)
    todo = sum(text.count(e[3]) == 0 and text.count(e[1]) == 1 for e in eds)
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    bad = [e[1][:60] for e in eds
           if not (text.count(e[3]) == 1 or (text.count(e[3]) == 0 and text.count(e[1]) == 1))]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d would apply; anchor or block not found "
                     "once: %r" % (path, done, len(eds), todo, bad))


def apply_text(path, text):
    for p, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(block) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:60]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, old, new, block in reversed(EDITS):
        if p != path:
            continue
        if text.count(block) != 1:
            raise SystemExit("REFUSED: %s: block found %d times: %r" % (path, text.count(block), block[:60]))
        text = text.replace(block, "", 1)
    return text


def table_span(text, name):
    start = text.index("constexpr Entry %s[] = {" % name)
    return text[start:text.index("\n};", start)]


def text_checks(texts):
    # --- the translation tables
    i18n = texts[I18N]
    glyphs = {int(x.strip()[2:], 16) for x in
              open(os.path.join(ROOT, GLYPHS), encoding="utf-8").read().split(",") if x.strip()}
    for name, _ in TABLES:
        span = table_span(i18n, name)
        for k in ("t1", "t2", "t3", "sec", "h1", "h2", "h3"):
            line = '    {"%s", "%s"},\n' % (EN[k], TR[name][k])
            if span.count(line) != 1 or span.count('{"%s"' % EN[k]) != 1:
                raise SystemExit("text check: %s: %r not found exactly once" % (name, EN[k][:40]))
    zh = "".join(TR["kChinese"].values())
    missing = sorted({c for c in zh if ord(c) > 0x7e and ord(c) not in glyphs})
    if missing:
        raise SystemExit("text check: Chinese menu text has characters the menu font lacks: %s" % "".join(missing))
    # --- the overlay: the same English and Russian text as the tables' keys
    block = OVERLAY_BLOCK
    joined = re.sub(r'"\s*\n\s*"', "", texts[OVERLAY])
    for k in ("t1", "t2", "t3", "sec", "h1", "h2", "h3"):
        for text in (EN[k], RU[k]):
            if joined.count('"%s"' % text) != 1:
                raise SystemExit("text check: overlay: %r not found exactly once" % text[:40])
    for k in ("t1", "t2", "t3", "sec", "h1", "h2", "h3"):
        if joined.count('"%s"' % EN[k]) != 1 or i18n.count('{"%s"' % EN[k]) != 8:
            raise SystemExit("text check: %r is not in the overlay once and in all 8 tables" % EN[k][:40])
    for env in ("BB_HALATION", "BB_LAMP_FLICKER", "BB_LAMP_FLICKER_ON_GAME"):
        if texts[OVERLAY].count('EnvNote("%s");' % env) != 1:
            raise SystemExit("text check: overlay: EnvNote(%s) not once" % env)
    # --- the launchers
    for path in (GP_B, GP_L):
        t = texts[path]
        for needle in ("StrengthSlider(SymbolRegular.Lightbulb24, L.T(\"%s\")" % EN[k] for k in ("t1", "t2", "t3")):
            if t.count(needle) != 1:
                raise SystemExit("text check: %s: row %r not once" % (path, needle))
        if t.count("ShowStrengths();") != 1 or t.count("private void ShowStrengths()") != 1:
            raise SystemExit("text check: %s: ShowStrengths not wired once" % path)
        if t.count("private void ShowLampSoftness()") != 1 or t.count("ShowLampSoftness();") != 1:
            raise SystemExit("text check: %s: ShowLampSoftness changed" % path)
        # the call stands right after ShowLampSoftness() in RefreshPerformance, after Ini.Refresh() (.fixed:
        # a line another patch puts between it and UpdatePerformance() no longer refuses the apply)
        at = t.find("            ShowLampSoftness();\n            ShowStrengths();\n")
        if at < 0 or t.rfind("            Ini.Refresh();\n", 0, at) < 0:
            raise SystemExit("text check: %s: RefreshPerformance order" % path)
    # --- the launcher translation files: valid json, the three keys, every key in zh-CN
    for code in LOC_ANCHOR:
        data = json.loads(texts[LOC + code + ".json"])
        zhdata = json.loads(texts[LOC + "zh-CN.json"])
        for k in ("t1", "t2", "t3"):
            if data.get(EN[k]) != LAUNCHER[code][k] or EN[k] not in zhdata:
                raise SystemExit("text check: %s.json: %r wrong or missing" % (code, EN[k]))
    # --- the defaults and the check
    ini = texts[INI]
    for k, v in (("graphics_halation_strength", "1.00"), ("graphics_lamp_flicker_strength", "1.00"),
                 ("graphics_lamp_flicker_on_game_strength", "0.00")):
        if ini.count('("%s", "%s"),' % (k, v)) != 1:
            raise SystemExit("text check: IniFile.cs default %s" % k)
        if texts[LOOKS_CHECKS].count('("%s", "%s")' % (k, v)) != 1:
            raise SystemExit("text check: LooksChecks default %s" % k)
    for path in (README,):
        if texts[path].count("Light glow and flicker") != 2:
            raise SystemExit("text check: README rows")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R109B_ROOT)" % ROOT)
    paths = []
    for e in EDITS:
        if e[0] not in paths:
            paths.append(e[0])
    r109a = ("HalationStrengthDefault" in load(SETTINGS_H)[2] and "graphics_halation_strength" in load(README)[2])
    skipped = []
    if not r109a:
        if cmd == "apply":
            raise SystemExit("REFUSED: r109a_strength-settings-engine is not applied (the slider rows need its "
                             "BbSettings constants and key rows): apply it first")
        if cmd == "check":
            skipped = [README, OVERLAY]
            print("note: r109a is not applied in this tree: the README and overlay edits cannot be checked "
                  "(the overlay uses its BbSettings constants)")
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
        elif skipped:
            clean = [p for p in plan if p[0] not in skipped]
            for p in clean:
                apply_text(p[0], p[3])
            print("not applied; the %d files not needing r109a would apply (every anchor found once); "
                  "README and overlay not checked here" % len(clean))
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
                tmp = full + ".r109btmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r109btmp"
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
