# r48_lamp-softness: a choice of how soft the ray traced lamp shadows are, sharp | soft | softer,
# as lantern.ini's graphics_lamp_shadow_softness (default soft = the 0.1 m lamp of r42), live,
# with a row in the in-game menu next to "Half-resolution lamp shadows" and one in both Windows
# launchers (Graphics > Lighting, under "Lamp shadow resolution"). The user's words: "options
# for soft, softer, and sharp". check|apply|revert (revert restores byte for byte). On top of
# r1..r47c as <tree> has them on 2026-11-14 evening (r44_half-area-lamp, r45_drawn-look
# and r47c_review-fixes applied). The tree: the one the environment variable R48_ROOT names;
# without it the current directory when that is the root of a source tree, else <tree>/.
# Nothing is changed in place: every new text is written beside its target and moved over it,
# and a failure puts back what was already moved. Files keep their line ends (CRLF or LF, as
# each file has them).
#
# WHY. The lamp of the ray traced lamp pass is a disc of radius 0.1 m (r42; BB_LAMP_SHADOW_SOFT,
# 0..0.5, read once at start); there was no setting for it, and 0 (a point) was a debug value.
#
# WHAT.
#  1. lantern.ini graphics_lamp_shadow_softness = sharp | soft | softer (bbport_settings.h
#     LampSoftness, parsed by name like graphics_sun_far_shadows; an unknown value is soft and
#     the log says so; saved by name, an out-of-range value in memory as the nearest name).
#     BB_LAMP_SHADOW_SOFT, when it gives a number, still wins (ReadLampShadowTune now records
#     that: LampShadowTune::radius_set; text that is not a number leaves the setting in charge,
#     as it left the default before).
#  2. Radii (lamp_shadow_tune.h LampSoftnessRadii): sharp 0 (a point), soft 0.1 m (unchanged),
#     softer 0.2 m. Why 0.2 m:
#      - The noise left in a penumbra does not grow with the disc. A pixel's ray goes to the point
#        samplePoint names in the unit square laid over the disc's area (point_shadow_ray.comp
#        lampVisibility: radius * sqrt(xi.x), angle 2 pi xi.y), and the R2 walk covers that
#        square evenly over any run of frames: the 9 frames of history (BB_LAMP_SHADOW_HISTORY
#        0.9, LampHistoryFrames) stand for a wide disc as well as for a narrow one. One ray a lamp
#        a frame at every radius, so no more rays than the history averages already.
#      - What grows with the radius: the share of the screen in penumbra (twice as wide), where
#        the 5x5 answers around a pixel bind its history least (a moving shadow's wake there is
#        held by the reject alone), and the share of its pixels the half-resolution pass's second
#        half must trace (r44: 17% on the lab's still scene at 0.1 m, point lamps 2%).
#      - A ray to the disc is blind within clearance_m (0.35 m) of its target, and every target
#        lies within the radius of the lamp's centre (the lift towards the surface's plane only
#        shortens that), so below 0.35 m the lamp's centre, where its own model sits (a torch's
#        head, a lantern's cage), stays blind to every ray to its disc. 0.2 m keeps 0.15 m of that;
#        0.25 m would keep 0.1 m, the variable's top 0.5 m none.
#      - Thin casters next to the lamp (a torch's stick, the carrier's arm) cover a smaller part
#        of a wider disc: their shadows get fainter with softer (the hint says so).
#     So 0.2 m: clearly softer (every penumbra twice as wide), the same rays and history.
#  3. Live. The tune is read once (the constructor); PointShadow::Flush now sets tune.radius_m
#     from the setting at every pass (LampSoftnessRadius), before anything of the pass's tuning
#     is worked out from it (LampPassRadius, `beside`, LampHistoryFrames, the state line), and
#     Ready does so before its start line. A history written at another radius is not read: the
#     pass keeps the radius of the pass that wrote the history (history_radius_m) and reads the
#     history only at the same radius, the way a camera cut already drops it (no HistoryRead,
#     the identity reprojection: the pass starts again from this frame's rays and averages anew;
#     one frame of bare rays, then 2, ... as after a cut). Switching to sharp needs nothing more:
#     a point lamp keeps no history (LampHistoryFrames 0, HistoryWrite clear), so the frame after
#     it finds no fresh history either. A log line at each change of the radius: "Ray traced
#     lamps (r48): lamp radius R m (graphics_lamp_shadow_softness=NAME | BB_LAMP_SHADOW_SOFT)...".
#  4. Sharp as a real option. What radius 0 does (read in the code):
#      - Full resolution: t_radius 0, the ray goes to the lamp's centre, the same ray every frame
#        (xi unused); LampHistoryFrames 0, so HistoryBlend is not set, the pass neither reads nor
#        writes a history (flags 0 without LANTERN_RT_LAMP_REUSE), the 5x5 answers and their
#        barrier are not run, TrackLamps runs on the log line's frames only. No stale history: a
#        history is read only when the frame before wrote one (history_fresh) of the same kind
#        and radius.
#      - Half resolution: LampPassRadius gives 0 (no averaging), the HALF build zeroes t_radius
#        without HistoryBlend; the first pass traces pixel (2x,2y) of each block, the second
#        shares the block's answer where the 3x3 blocks agree within 1/64 (point-lamp answers are
#        0 or 1, so they agree almost everywhere off an edge) and traces the rest: r32's pass.
#      - One more source of change from frame to frame, found here: with the picked lamps (the
#        default `steps` 1) a pixel that three or more lamps reach traces its strongest lamp and
#        ONE of the others, picked by weight from a seed that moves with the frame where the
#        camera jitters (DLSS/TAA). The area lamp's history averages the picks; a point lamp has
#        no history, so that light would flicker in the weaker lamps' shadows. So a point lamp
#        (sharp, or BB_LAMP_SHADOW_SOFT=0) now traces every lamp that reaches a pixel
#        (LampPassSteps: steps 0, the shader's `exact` path, the very path LANTERN_RT_LAMPS_EXACT=1
#        takes; r41's lab checked it against mode 0). With experiment 35184372088832 set (the
#        pass of before r41) the pick stays.
#     Cost of sharp against soft, by the code: rays the same where one or two lamps reach a
#     pixel; where three or more do, one ray per lamp in place of two (the exact path); no
#     history read (four texels of history_prev), no history write, no 5x5 bound, one barrier
#     fewer, no TrackLamps on most frames; at half resolution far fewer second-pass pixels (2%
#     against 17% in r44's lab). The history images stay allocated (made when the pass first
#     runs). Not measured in the game.
#  5. Menu: a combo "Lamp shadow softness" (Sharp, Soft, Softer) right after "Half-resolution
#     lamp shadows", disabled while "Ray traced lamp shadows" is off, a hint in English and
#     Russian (bbport_overlay.cpp), the row's name, the three choices and the hint in the eight
#     tables of bbport_menu_i18n.cpp (looked up by the English text; the Chinese text uses only
#     characters of third_party/fonts/LanternMenuSC-glyphs.txt, checked here; "清晰" (clear)
#     stands for Sharp because 利 is not in the font). EnvNote("BB_LAMP_SHADOW_SOFT") under it.
#     engine_previous_paths does not touch it (bit 45 is not in PreviousPathsBits), so no note.
#  6. Launcher (not built): a choice row in Graphics > Lighting under "Lamp shadow resolution"
#     in both GraphicsPage.cs files (BloodborneLauncher, LanternLauncher), Choices.
#     LampShadowSoftness (sharp, soft, softer; notes under Sharp and Softer, at most 110
#     characters in every language, checked here), IniFile.Defaults ("soft"), checks in
#     tests/LooksChecks and tests/LocalizationChecks, 7 strings in each of the 13
#     Localization/*.json files (in front of the entry r38 and r40 put theirs in front of).
#     Not in Graphics > Performance: that group's first line says its first four rows switch
#     live and its rows give up picture for speed; this one is a look (and live). The key goes
#     into shared settings by the graphics_ prefix, as its neighbours do. Not wired, as the
#     comparable lamp-half key is not: Hardware.Recommend, TestedSettings, Looks.Knobs.
#     An unknown value in lantern.ini shows as the first choice (Sharp) in the launcher
#     (Choices.IndexOf), while the engine reads it as soft and writes soft back at its next save.
#  7. Tests: tests/test_lamp_shadow_tune.cpp (LampSoftnessRadius, radius_set, the variable
#     winning, LampPassSteps, what the pass averages at each value), tests/test_settings.cpp (the
#     key's default, names, save, unknown values).
# NOT CHANGED: point_shadow_ray.comp (the shader), the README table (it lists only keys without
# a launcher row) and tools/bbfss-default.ini (it lists neither graphics_lamp_shadow_half nor
# graphics_rt_point_shadows).
# NOT MEASURED: anything in the game (the picture at each value, the cost of the exact path where
# many lamps meet, the half-resolution share at 0.2 m).
# ORDER: r48 goes on last and comes off first: it changes text that r41, r42 and r44 put into
# vk_point_shadow.cpp (their reverts do not find it while r48 stands).
# VERIFIED (2026-11-14): check against <tree>; apply / check ("already applied") / revert on
# a copy of the 28 affected files (byte for byte back after revert); the unit tests
# lamp-shadow-tune-test and settings-test built from the patched files with the targets' flags
# (-UNDEBUG -Wall -Wextra -Werror, gnu++23, MSYS2 CLANG64) and passed; vk_point_shadow.cpp and
# bbport_overlay.cpp compiled with the engine's flags and include paths (-fsyntax-only: no
# object, no link). The spare build tree meant for the full build was gone (deleted from outside
# this round), so the engine was not built or linked and the launcher not built.

import json
import os
import re
import sys

ROOT = os.environ.get("R48_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
S = G + "shim/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"
LAUNCH = ROOT + "launcher/windows/"
W = LAUNCH + "BloodborneLauncher/"
GLYPHS = G + "third_party/fonts/LanternMenuSC-glyphs.txt"

TMP = ".r48tmp"  # a new text waits under this name beside its target (main)
NEW_FILES = {}


def lit(text, indent, width=100):
    """text as adjacent C++ string literals, one a line, each line at most `width` characters."""
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        cand = w if not cur else cur + " " + w
        if cur and len(indent) + len(cand) + 3 > width:
            lines.append(cur + " ")
            cur = w
        else:
            cur = cand
    lines.append(cur)
    assert "".join(lines) == text and not any('"' in l or "\\" in l for l in lines)
    return "\n".join(indent + '"' + l + '"' for l in lines)


# ---- the in-game menu's texts (English and Russian in bbport_overlay.cpp, the rest in
# bbport_menu_i18n.cpp, looked up by the English text) ----
MENU = {
 "en": ("Lamp shadow softness", "Sharp", "Soft", "Softer",
        "Live, Soft by default. Needs Ray traced lamp shadows. How soft the edges of lamp and torch shadows are. "
        "Sharp: hard edges. Each lamp is a point, every lamp that reaches a spot is traced every frame and nothing "
        "is averaged over frames: no noise and no smear behind a moving shadow, but more rays where three or more "
        "lamps light the same spot. Soft: edges that widen with the distance from what casts the shadow, averaged "
        "over about ten frames. Softer: edges twice as wide, for the same rays (with Half-resolution lamp shadows a "
        "little more work); thin things close to a lamp, such as a torch's stick, cast fainter shadows. Right after "
        "switching to Soft or Softer the edges are grainy for a few frames."),
 "ru": ("Мягкость теней ламп", "Резкие", "Мягкие", "Мягче",
        "Работает сразу, по умолчанию «Мягкие». Нужны трассированные тени ламп. Насколько мягкие края у теней ламп и "
        "факелов. Резкие: жёсткие края. Каждая лампа — точка, каждый кадр трассируется каждая лампа, которая достаёт "
        "до места, и ничего не усредняется по кадрам: нет ни шума, ни шлейфа за движущейся тенью, но больше лучей "
        "там, где одно место освещают три лампы и больше. Мягкие: края, которые расширяются с расстоянием от того, "
        "что отбрасывает тень, усреднённые примерно по десяти кадрам. Мягче: края вдвое шире, при том же числе лучей "
        "(с «Тени ламп в половинном разрешении» немного больше работы); тонкие предметы рядом с лампой, например "
        "древко факела, отбрасывают более бледные тени. Сразу после переключения на «Мягкие» или «Мягче» края "
        "несколько кадров зернистые."),
 "es": ("Suavidad de las sombras de lámparas", "Nítidas", "Suaves", "Más suaves",
        "Al instante, «Suaves» por defecto. Requiere «Ray traced lamp shadows». Lo suaves que son los bordes de las "
        "sombras de lámparas y antorchas. Nítidas: bordes duros. Cada lámpara es un punto, cada fotograma se traza "
        "cada lámpara que llega a un lugar y no se promedia nada entre fotogramas: sin ruido y sin estela tras una "
        "sombra que se mueve, pero con más rayos donde tres o más lámparas iluminan el mismo lugar. Suaves: bordes "
        "que se ensanchan con la distancia a lo que proyecta la sombra, promediados durante unos diez fotogramas. "
        "Más suaves: bordes el doble de anchos, con los mismos rayos (con «Sombras de lámparas a media resolución», "
        "algo más de trabajo); las cosas finas cerca de una lámpara, como el palo de una antorcha, proyectan sombras "
        "más tenues. Justo después de cambiar a «Suaves» o «Más suaves», los bordes se ven granulados durante unos "
        "fotogramas."),
 "pt": ("Suavidade das sombras de lâmpadas", "Nítidas", "Suaves", "Mais suaves",
        "Na hora, “Suaves” por padrão. Requer “Ray traced lamp shadows”. O quanto são suaves as bordas das sombras "
        "de lâmpadas e tochas. Nítidas: bordas duras. Cada lâmpada é um ponto, a cada quadro é traçada cada lâmpada "
        "que alcança um lugar e nada é calculado em média entre quadros: sem ruído e sem rastro atrás de uma sombra "
        "em movimento, mas com mais raios onde três ou mais lâmpadas iluminam o mesmo lugar. Suaves: bordas que se "
        "alargam com a distância do que projeta a sombra, em média de cerca de dez quadros. Mais suaves: bordas "
        "duas vezes mais largas, com os mesmos raios (com “Sombras de lâmpadas em meia resolução”, um pouco mais de "
        "trabalho); coisas finas perto de uma lâmpada, como o cabo de uma tocha, projetam sombras mais fracas. Logo "
        "após mudar para “Suaves” ou “Mais suaves”, as bordas ficam granuladas por alguns quadros."),
 "fr": ("Douceur des ombres des lampes", "Nettes", "Douces", "Plus douces",
        "Immédiat, « Douces » par défaut. Nécessite « Ray traced lamp shadows ». La douceur des bords des ombres "
        "des lampes et des torches. Nettes : bords durs. Chaque lampe est un point, chaque lampe qui atteint un "
        "endroit est tracée à chaque image et rien n'est moyenné entre les images : ni bruit ni traînée derrière "
        "une ombre qui bouge, mais davantage de rayons là où trois lampes ou plus éclairent le même endroit. "
        "Douces : des bords qui s'élargissent avec la distance à ce qui projette l'ombre, moyennés sur une dizaine "
        "d'images. Plus douces : des bords deux fois plus larges, pour les mêmes rayons (avec « Ombres des lampes en "
        "demi-résolution », un peu plus de travail) ; les objets fins proches d'une lampe, comme le manche d'une "
        "torche, projettent des ombres plus pâles. Juste après le passage à « Douces » ou « Plus douces », les bords "
        "sont granuleux pendant quelques images."),
 "de": ("Weichheit der Lampenschatten", "Scharf", "Weich", "Weicher",
        "Sofort wirksam, standardmäßig „Weich“. Benötigt „Ray traced lamp shadows“. Wie weich die Ränder der "
        "Schatten von Lampen und Fackeln sind. Scharf: harte Ränder. Jede Lampe ist ein Punkt, jede Lampe, die eine "
        "Stelle erreicht, wird in jedem Bild verfolgt und nichts wird über Bilder gemittelt: kein Rauschen und keine "
        "Schliere hinter einem bewegten Schatten, aber mehr Strahlen, wo drei oder mehr Lampen dieselbe Stelle "
        "beleuchten. Weich: Ränder, die mit dem Abstand zum Schattenwerfer breiter werden, über etwa zehn Bilder "
        "gemittelt. Weicher: doppelt so breite Ränder bei gleich vielen Strahlen (mit „Lampenschatten in halber "
        "Auflösung“ etwas mehr Arbeit); dünne Dinge nahe einer Lampe, etwa der Stiel einer Fackel, werfen blassere "
        "Schatten. Direkt nach dem Wechsel auf „Weich“ oder „Weicher“ sind die Ränder ein paar Bilder lang körnig."),
 "it": ("Morbidezza delle ombre delle lampade", "Nette", "Morbide", "Più morbide",
        "Subito attivo, «Morbide» di default. Richiede «Ray traced lamp shadows». Quanto sono morbidi i bordi delle "
        "ombre di lampade e torce. Nette: bordi duri. Ogni lampada è un punto, ogni lampada che raggiunge un punto "
        "viene tracciata a ogni fotogramma e nulla viene mediato tra i fotogrammi: niente rumore e nessuna scia "
        "dietro un'ombra in movimento, ma più raggi dove tre o più lampade illuminano lo stesso punto. Morbide: "
        "bordi che si allargano con la distanza da ciò che proietta l'ombra, mediati su circa dieci fotogrammi. Più "
        "morbide: bordi larghi il doppio, con gli stessi raggi (con «Ombre delle lampade a metà risoluzione» un po' "
        "più di lavoro); le cose sottili vicino a una lampada, come il manico di una torcia, proiettano ombre più "
        "tenui. Subito dopo il passaggio a «Morbide» o «Più morbide» i bordi restano granulosi per qualche "
        "fotogramma."),
 "pl": ("Miękkość cieni lamp", "Ostre", "Miękkie", "Miększe",
        "Działa od razu, domyślnie „Miękkie”. Wymaga „Ray traced lamp shadows”. Jak miękkie są krawędzie cieni lamp "
        "i pochodni. Ostre: twarde krawędzie. Każda lampa jest punktem, w każdej klatce śledzona jest każda lampa, "
        "która sięga danego miejsca, i nic nie jest uśredniane między klatkami: bez szumu i bez smugi za ruchomym "
        "cieniem, ale więcej promieni tam, gdzie trzy lub więcej lamp oświetla to samo miejsce. Miękkie: krawędzie, "
        "które poszerzają się wraz z odległością od tego, co rzuca cień, uśredniane z około dziesięciu klatek. "
        "Miększe: krawędzie dwa razy szersze przy tej samej liczbie promieni (z „Cienie lamp w połowie "
        "rozdzielczości” nieco więcej pracy); cienkie przedmioty blisko lampy, np. drzewce pochodni, rzucają bledsze "
        "cienie. Tuż po przełączeniu na „Miękkie” lub „Miększe” krawędzie przez kilka klatek są ziarniste."),
 "tr": ("Lamba gölgesi yumuşaklığı", "Keskin", "Yumuşak", "Daha yumuşak",
        "Anında, varsayılan “Yumuşak”. “Ray traced lamp shadows” gerekir. Lamba ve meşale gölgelerinin "
        "kenarlarının ne kadar yumuşak olduğu. Keskin: sert kenarlar. Her lamba bir noktadır, bir yere ulaşan her "
        "lamba her karede izlenir ve kareler arasında hiçbir şeyin ortalaması alınmaz: gürültü yok, hareket eden "
        "bir gölgenin ardında iz yok; ancak üç veya daha fazla lambanın aynı yeri aydınlattığı yerlerde daha çok "
        "ışın. Yumuşak: gölgeyi düşüren şeyden uzaklaştıkça genişleyen kenarlar, yaklaşık on karenin ortalaması. "
        "Daha yumuşak: iki kat geniş kenarlar, aynı sayıda ışınla (“Yarım çözünürlükte lamba gölgeleri” ile biraz "
        "daha fazla iş); bir lambaya yakın ince şeyler, örneğin bir meşalenin sapı, daha soluk gölgeler düşürür. "
        "“Yumuşak” veya “Daha yumuşak” seçeneğine geçtikten hemen sonra kenarlar birkaç kare boyunca grenli "
        "görünür."),
 "zh": ("灯光阴影柔和度", "清晰", "柔和", "更柔和",
        "即时生效，默认 “柔和”。需要开启 “Ray traced lamp shadows”。设置灯光阴影边界的柔和程度。清晰：边界清晰；每个灯光视为一个点，"
        "每帧计算到达该处的每个灯光，不在帧之间取平均：没有闪烁，移动的阴影后面也没有拖影，但 3 个或更多灯光照亮同一处时 RT 计算更多。"
        "柔和：边界的柔和范围随与产生阴影的物体的距离而增大，约在 10 帧之间取平均。更柔和：柔和范围为 “柔和” 的 2 倍，RT 计算相同"
        "（开启 “半分辨率 RT 灯光阴影” 时略多）；灯光附近的细小物体产生的阴影更弱。切换到 “柔和” 或 “更柔和” 后的数帧内，边界会有些闪烁。"),
}
TABLE_LANGS = ["es", "pt", "fr", "de", "it", "pl", "tr", "zh"]
# The end of each table's entry for the hint of "Half-resolution lamp shadows" (r44), which the
# new entries follow.
TABLE_TAIL = {
 "es": 'bjeto más fino que unos 2 píxeles puede perder su sombra."},',
 "pt": 'to mais fino que cerca de 2 pixels pode ficar sem sombra."},',
 "fr": "objet plus fin qu'environ 2 pixels peut perdre son ombre.\"},",
 "de": 't dünner als etwa 2 Pixel kann seinen Schatten verlieren."},',
 "it": 'to più sottile di circa 2 pixel può perdere la sua ombra."},',
 "pl": 'eń. Obiekt cieńszy niż około 2 piksele może stracić cień."},',
 "tr": 'klaşık 2 pikselden ince bir nesne gölgesini kaybedebilir."},',
 "zh": '比约 2 像素更细的物体可能丢掉阴影。"},',
}
FAR_REFIT = '    {"Far animated objects in ray tracing: update every 8th frame",'


def table_entries(lang):
    en, tr = MENU["en"], MENU[lang]
    out = []
    for k in range(5):
        assert '"' not in tr[k] and "\\" not in tr[k]
        if lang == "zh" or k in (1, 2, 3):
            out.append('    {"%s", "%s"},\n' % (en[k], tr[k]))
        else:
            out.append('    {"%s",\n     "%s"},\n' % (en[k], tr[k]))
    return "".join(out)


EN_HINT, RU_HINT = MENU["en"][4], MENU["ru"][4]
OVERLAY_ROW = r"""        if (!PreviousPathsNote()) { // bbport (r39_master-debug)
            EnvNote("BB_LAMP_SHADOW_HALF");
        }
    }
    // bbport (r48_lamp-softness): how soft the ray traced lamp shadows are, as the lamp's radius
    // (renderer_vulkan/lamp_shadow_tune.h LampSoftnessRadius: sharp a point, soft 0.1 m, softer
    // 0.2 m). Live: vk_point_shadow.cpp takes it at every pass and does not read a history made
    // at another radius. BB_LAMP_SHADOW_SOFT, when set to a number, decides instead.
    if (const char* label = Item("Lamp shadow softness", "Мягкость теней ламп")) {
        const char* names[] = {BbSettings::MenuText("Sharp", "Резкие"), BbSettings::MenuText("Soft", "Мягкие"),
                               BbSettings::MenuText("Softer", "Мягче")};
        int mode = std::clamp(s.graphics_lamp_shadow_softness.load(), 0, BbSettings::LampSoftnessCount - 1);
        ImGui::BeginDisabled(!s.graphics_rt_point_shadows);
        const bool changed = ImGui::Combo(label, &mode, names, BbSettings::LampSoftnessCount);
        ImGui::EndDisabled();
        Store(s.graphics_lamp_shadow_softness, mode, changed);
        Hint(BbSettings::MenuText(
@EN@,
@RU@));
        EnvNote("BB_LAMP_SHADOW_SOFT");
    }
""".replace("@EN@", lit(EN_HINT, " " * 12)).replace("@RU@", lit(RU_HINT, " " * 12))

# ---- the launcher's texts (L.T keys = the English text; 13 language files) ----
LAUNCHER_EN = {
 "title": "Lamp shadow softness",
 "hint": "How soft the edges of ray traced lamp and torch shadows are. Sharp: hard edges, nothing averaged over "
         "frames. Soft: soft edges, averaged over about ten frames. Softer: twice as wide; thin things near a lamp "
         "cast fainter shadows. Needs Ray traced lamp shadows, which is in the in-game menu. A change here applies "
         "at the next game start; the in-game menu switches it at once.",
 "sharp": "Sharp",
 "sharp_note": "Hard edges, no noise; more rays where three or more lamps light one spot",
 "soft": "Soft (default)",
 "softer": "Softer",
 "softer_note": "Edges twice as wide; a torch's stick and other thin things near a lamp cast fainter shadows",
}
NB = "\u00a0"  # fr.json's no-break space (before a colon or semicolon, inside « »)
LAUNCHER_TR = {
 "de": ["Weichheit der Lampenschatten",
        "Wie weich die Ränder der Raytracing-Schatten von Lampen und Fackeln sind. Scharf: harte Ränder, nichts wird "
        "über Bilder gemittelt. Weich: weiche Ränder, über etwa zehn Bilder gemittelt. Weicher: doppelt so breit; "
        "dünne Dinge nahe einer Lampe werfen blassere Schatten. Benötigt „Ray traced lamp shadows“ aus dem "
        "Spielmenü. Eine Änderung hier gilt ab dem nächsten Spielstart; das Spielmenü schaltet sie sofort um.",
        "Scharf", "Harte Ränder, kein Rauschen; mehr Strahlen, wo drei oder mehr Lampen eine Stelle beleuchten",
        "Weich (Standard)", "Weicher",
        "Doppelt so breite Ränder; dünne Dinge nahe einer Lampe, etwa ein Fackelstiel, werfen blassere Schatten"],
 "es": ["Suavidad de las sombras de lámparas",
        "Lo suaves que son los bordes de las sombras trazadas de lámparas y antorchas. Nítidas: bordes duros, nada "
        "se promedia entre fotogramas. Suaves: bordes suaves, promediados durante unos diez fotogramas. Más suaves: "
        "el doble de anchos; las cosas finas cerca de una lámpara proyectan sombras más tenues. Requiere «Ray traced "
        "lamp shadows», que está en el menú del juego. Un cambio aquí se aplica la próxima vez que se inicia el "
        "juego; el menú del juego lo cambia al instante.",
        "Nítidas", "Bordes duros, sin ruido; más rayos donde tres o más lámparas iluminan un mismo punto",
        "Suaves (por defecto)", "Más suaves",
        "Bordes el doble de anchos; el palo de una antorcha y otras cosas finas proyectan sombras más tenues"],
 "fr": ["Douceur des ombres des lampes",
        "La douceur des bords des ombres tracées des lampes et des torches. Nettes" + NB + ": bords durs, rien n'est "
        "moyenné entre les images. Douces" + NB + ": bords doux, moyennés sur une dizaine d'images. Plus douces" + NB +
        ": deux fois plus larges" + NB + "; les objets fins proches d'une lampe projettent des ombres plus pâles. "
        "Nécessite «" + NB + "Ray traced lamp shadows" + NB + "», qui se trouve dans le menu en jeu. Un changement ici "
        "s'applique au prochain lancement du jeu" + NB + "; le menu en jeu le change tout de suite.",
        "Nettes", "Bords durs, sans bruit" + NB + "; plus de rayons là où trois lampes ou plus éclairent un même endroit",
        "Douces (par défaut)", "Plus douces",
        "Bords deux fois plus larges" + NB + "; le manche d'une torche et les objets fins projettent des ombres plus pâles"],
 "it": ["Morbidezza delle ombre delle lampade",
        "Quanto sono morbidi i bordi delle ombre tracciate di lampade e torce. Nette: bordi duri, nulla viene mediato "
        "tra i fotogrammi. Morbide: bordi morbidi, mediati su circa dieci fotogrammi. Più morbide: larghe il doppio; "
        "le cose sottili vicino a una lampada proiettano ombre più tenui. Richiede «Ray traced lamp shadows», che si "
        "trova nel menu in gioco. Una modifica qui vale dal prossimo avvio del gioco; il menu in gioco la cambia "
        "subito.",
        "Nette", "Bordi duri, niente rumore; più raggi dove tre o più lampade illuminano lo stesso punto",
        "Morbide (predefinito)", "Più morbide",
        "Bordi larghi il doppio; il manico di una torcia e altre cose sottili proiettano ombre più tenui"],
 "ja": ["ランプの影の柔らかさ",
        "レイトレーシングによるランプと松明の影の縁の柔らかさです。シャープ: 縁がくっきりし、フレーム間の平均化はありません。ソフト: 縁が柔らかく、"
        "約 10 フレームで平均化されます。よりソフト: 縁の幅が 2 倍になり、ランプの近くの細い物体の影は薄くなります。ゲーム内メニューの"
        "「Ray traced lamp shadows」が必要です。ここでの変更は次回のゲーム起動時に適用されます。ゲーム内メニューではすぐに切り替わります。",
        "シャープ", "縁がくっきりし、ノイズはありません。3 つ以上のランプが同じ場所を照らすとレイが増えます",
        "ソフト (既定)", "よりソフト",
        "縁の幅が 2 倍になります。松明の柄などランプの近くの細い物体の影は薄くなります"],
 "ko": ["램프 그림자 부드러움",
        "레이 트레이싱 램프와 횃불 그림자 가장자리가 얼마나 부드러운지 정합니다. 선명: 가장자리가 또렷하고 프레임 간 평균을 내지 않습니다. "
        "부드러움: 가장자리가 부드럽고 약 10프레임에 걸쳐 평균을 냅니다. 더 부드러움: 폭이 두 배이며 램프 가까이의 가는 물체는 그림자가 "
        "옅어집니다. 게임 내 메뉴의 'Ray traced lamp shadows'가 필요합니다. 여기서 바꾸면 다음 게임 시작 때 적용되며, 게임 내 메뉴에서는 "
        "바로 바뀝니다.",
        "선명", "가장자리가 또렷하고 노이즈가 없습니다. 램프 세 개 이상이 한곳을 비추면 광선이 늘어납니다",
        "부드러움 (기본값)", "더 부드러움",
        "가장자리 폭이 두 배입니다. 횃불 자루 등 램프 가까이의 가는 물체는 그림자가 옅어집니다"],
 "pl": ["Miękkość cieni lamp",
        "Jak miękkie są krawędzie śledzonych cieni lamp i pochodni. Ostre: twarde krawędzie, nic nie jest uśredniane "
        "między klatkami. Miękkie: miękkie krawędzie, uśredniane z około dziesięciu klatek. Miększe: dwa razy "
        "szersze; cienkie przedmioty blisko lampy rzucają bledsze cienie. Wymaga „Ray traced lamp shadows” z menu w "
        "grze. Zmiana tutaj działa od następnego uruchomienia gry; menu w grze przełącza ją od razu.",
        "Ostre", "Twarde krawędzie, bez szumu; więcej promieni tam, gdzie trzy lub więcej lamp oświetla jedno miejsce",
        "Miękkie (domyślnie)", "Miększe",
        "Krawędzie dwa razy szersze; drzewce pochodni i inne cienkie przedmioty rzucają bledsze cienie"],
 "pt-BR": ["Suavidade das sombras de lâmpadas",
        "O quanto são suaves as bordas das sombras traçadas de lâmpadas e tochas. Nítidas: bordas duras, nada é "
        "calculado em média entre quadros. Suaves: bordas suaves, em média de cerca de dez quadros. Mais suaves: duas "
        "vezes mais largas; coisas finas perto de uma lâmpada projetam sombras mais fracas. Requer “Ray traced lamp "
        "shadows”, que fica no menu do jogo. Uma mudança aqui vale a partir do próximo início do jogo; o menu do jogo "
        "a troca na hora.",
        "Nítidas", "Bordas duras, sem ruído; mais raios onde três ou mais lâmpadas iluminam o mesmo ponto",
        "Suaves (padrão)", "Mais suaves",
        "Bordas duas vezes mais largas; o cabo de uma tocha e outras coisas finas projetam sombras mais fracas"],
 "ru": ["Мягкость теней ламп",
        "Насколько мягкие края у трассированных теней ламп и факелов. Резкие: жёсткие края, ничего не усредняется по "
        "кадрам. Мягкие: мягкие края, усреднённые примерно по десяти кадрам. Мягче: вдвое шире; тонкие предметы рядом "
        "с лампой отбрасывают более бледные тени. Нужны «Трассированные тени ламп» из внутриигрового меню. Изменение "
        "здесь применяется при следующем запуске игры; внутриигровое меню переключает его сразу.",
        "Резкие", "Жёсткие края, без шума; больше лучей там, где одно место освещают три лампы и больше",
        "Мягкие (по умолчанию)", "Мягче",
        "Края вдвое шире; древко факела и другие тонкие предметы рядом с лампой дают более бледные тени"],
 "tr": ["Lamba gölgesi yumuşaklığı",
        "Işın izlemeli lamba ve meşale gölgelerinin kenarlarının ne kadar yumuşak olduğu. Keskin: sert kenarlar, "
        "kareler arasında ortalama alınmaz. Yumuşak: yumuşak kenarlar, yaklaşık on karenin ortalaması. Daha yumuşak: "
        "iki kat geniş; bir lambaya yakın ince şeyler daha soluk gölge düşürür. Oyun içi menüdeki \"Ray traced lamp "
        "shadows\" gerekir. Buradaki bir değişiklik oyunun bir sonraki açılışında uygulanır; oyun içi menü onu hemen "
        "değiştirir.",
        "Keskin", "Sert kenarlar, gürültü yok; üç veya daha fazla lambanın aydınlattığı yerlerde daha çok ışın",
        "Yumuşak (varsayılan)", "Daha yumuşak",
        "Kenarlar iki kat geniş; meşale sapı ve lambaya yakın ince şeyler daha soluk gölge düşürür"],
 "uk": ["М'якість тіней ламп",
        "Наскільки м'які краї трасованих тіней ламп і смолоскипів. Різкі: чіткі краї, нічого не усереднюється між "
        "кадрами. М'які: м'які краї, усереднені приблизно за десять кадрів. М'якші: удвічі ширші; тонкі предмети біля "
        "лампи відкидають блідіші тіні. Потрібно «Ray traced lamp shadows» із внутрішньоігрового меню. Зміна тут "
        "застосовується під час наступного запуску гри; внутрішньоігрове меню перемикає її одразу.",
        "Різкі", "Чіткі краї, без шуму; більше променів там, де одне місце освітлюють три лампи чи більше",
        "М'які (типово)", "М'якші",
        "Краї вдвічі ширші; держак смолоскипа й інші тонкі предмети біля лампи дають блідіші тіні"],
 "zh-CN": ["灯光阴影柔和度",
        "光线追踪灯光与火把阴影边缘的柔和程度。锐利：边缘清晰，不在帧之间取平均。柔和：边缘柔和，约在 10 帧之间取平均。更柔和：边缘宽一倍；"
        "灯光附近的细小物体投下的阴影更淡。需要开启游戏内菜单中的“Ray traced lamp shadows”。在此处更改将在下次启动游戏时生效；游戏内菜单可立即切换。",
        "锐利", "边缘清晰，无噪点；三个或更多灯光照亮同一处时光线更多",
        "柔和（默认）", "更柔和",
        "边缘宽一倍；火把的柄等灯光附近的细小物体投下的阴影更淡"],
 "zh-TW": ["燈光陰影柔和度",
        "光線追蹤燈光與火把陰影邊緣的柔和程度。銳利：邊緣清晰，不在影格之間取平均。柔和：邊緣柔和，約在 10 個影格之間取平均。更柔和：邊緣寬一倍；"
        "燈光附近的細小物件投下的陰影更淡。需要開啟遊戲內選單中的「Ray traced lamp shadows」。在此處變更將於下次啟動遊戲時生效；遊戲內選單可立即切換。",
        "銳利", "邊緣清晰，無雜訊；三個以上燈光照亮同一處時光線更多",
        "柔和（預設）", "更柔和",
        "邊緣寬一倍；火把的柄等燈光附近的細小物件投下的陰影更淡"],
}
LAUNCHER_KEYS = ["title", "hint", "sharp", "sharp_note", "soft", "softer", "softer_note"]
LANGS = ["de", "es", "fr", "it", "ja", "ko", "pl", "pt-BR", "ru", "tr", "uk", "zh-CN", "zh-TW"]
JSON_ANCHOR = '  "The saved settings are damaged.": "'


def json_entries(lang):
    return "".join("  %s: %s,\n" % (json.dumps(LAUNCHER_EN[k], ensure_ascii=False),
                                    json.dumps(LAUNCHER_TR[lang][i], ensure_ascii=False))
                   for i, k in enumerate(LAUNCHER_KEYS))


def cs(text):
    """L.T("...") of a launcher string, as the C# source has it."""
    assert '"' not in text and "\\" not in text
    return 'L.T("%s")' % text


GRAPHICS_EDITS = [
 (r"""            IniCombo(SymbolRegular.Lightbulb24, L.T("Lamp shadow resolution"), L.T("Applied when the game starts"), Choices.LocalShadowResolution, "graphics_local_shadow_resolution");
""", r"""            IniCombo(SymbolRegular.Lightbulb24, L.T("Lamp shadow resolution"), L.T("Applied when the game starts"), Choices.LocalShadowResolution, "graphics_local_shadow_resolution");
            // How soft the ray traced lamp shadows are (the engine's lamp radius: sharp a point,
            // soft 0.1 m, softer 0.2 m). The in-game menu has the same row and switches it at once.
            IniCombo(SymbolRegular.Lightbulb24, @title@,
                @hint@,
                Choices.LampShadowSoftness, "graphics_lamp_shadow_softness");
""".replace("@title@", cs(LAUNCHER_EN["title"])).replace("@hint@", cs(LAUNCHER_EN["hint"]))),
]

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    R + "lamp_shadow_tune.h": [
        (r"""    float radius_m = 0.1f;       ///< BB_LAMP_SHADOW_SOFT, 0..0.5: the lamp's radius; 0: a point
""",
         r"""    float radius_m = 0.1f;       ///< BB_LAMP_SHADOW_SOFT, 0..0.5: the lamp's radius; 0: a point
    bool radius_set = false;     ///< bbport (r48_lamp-softness): BB_LAMP_SHADOW_SOFT gave radius_m
                                 ///< (a number): it wins over graphics_lamp_shadow_softness
                                 ///< (LampSoftnessRadius)
"""),
        (r"""    tune.radius_m = Number(get, "BB_LAMP_SHADOW_SOFT", tune.radius_m, 0.0f, 0.5f);
""",
         r"""    // bbport (r48_lamp-softness): read with no fallback (a NaN when the variable is not set or
    // is not a number), so that the pass knows whether it gave the radius.
    const float soft = Number(get, "BB_LAMP_SHADOW_SOFT", std::nanf(""), 0.0f, 0.5f);
    tune.radius_set = !std::isnan(soft);
    tune.radius_m = tune.radius_set ? soft : tune.radius_m;
"""),
        (r"""    return averages && !takes_history ? 0.0f : tune.radius_m;
}

""",
         r"""    return averages && !takes_history ? 0.0f : tune.radius_m;
}

/// bbport (r48_lamp-softness): the lamp's radius, m, for graphics_lamp_shadow_softness
/// (bbport_settings.h LampSoftness: 0 sharp, 1 soft, 2 softer; another value: soft, the
/// default). BB_LAMP_SHADOW_SOFT, when it gave a number (radius_set), wins. PointShadow::Flush
/// takes it at every pass, so the menu switches it live.
///  - Sharp, 0: a point lamp. Its ray goes to the lamp's centre, the same ray every frame, and
///    nothing is averaged (LampHistoryFrames 0: the pass neither reads nor writes a history);
///    the pass traces every lamp that reaches a pixel (LampPassSteps).
///  - Soft, 0.1 m: the area lamp of r42, one ray a lamp a frame to a point of its disc, averaged
///    in the history (BB_LAMP_SHADOW_HISTORY 0.9: up to 9 frames before this one).
///  - Softer, 0.2 m: the same with a disc twice as wide, so every penumbra is twice as wide. The
///    rays are as many and the history as long: the points a pixel's rays go to walk the disc
///    in its own measure (samplePoint, the unit square laid over the disc's area), so 9 frames
///    cover a wide disc as evenly as a narrow one and the noise left in a penumbra pixel does
///    not grow with the radius. What grows is the share of the screen in penumbra, where the
///    history does the averaging and the answers around a pixel bind it least, and the share of
///    its pixels the half-resolution pass's second half traces. Every target of a ray lies within
///    the radius of the lamp's centre, and a ray is blind within clearance_m (0.35 m) of its
///    target: 0.2 m keeps the lamp's centre, where its own model sits, 0.15 m inside that.
inline constexpr std::array<float, 3> LampSoftnessRadii{0.0f, 0.1f, 0.2f};
inline float LampSoftnessRadius(const LampShadowTune& tune, int softness) {
    if (tune.radius_set) {
        return tune.radius_m;
    }
    return softness >= 0 && softness < int(LampSoftnessRadii.size()) ? LampSoftnessRadii[std::size_t(softness)]
                                                                       : LampSoftnessRadii[1];
}

/// bbport (r48_lamp-softness): the shader's `steps` for a ray traced lamp pass (its push block):
/// 0 traces every lamp that reaches a pixel; else (`pick`: 1, or 0 with LANTERN_RT_LAMPS_EXACT=1)
/// the strongest lamp and one of the others, picked by weight anew each frame where the camera
/// jitters, which the area lamp's history averages. A point lamp (sharp, or
/// BB_LAMP_SHADOW_SOFT=0) has no history to average the pick in, and the light of a pixel that
/// three or more lamps reach would change from frame to frame in the weaker lamps' shadows: with
/// the repair (not experiment 35184372088832, the pass of before r41) it traces every lamp. No
/// noise, and more rays only where three or more lamps reach a pixel.
inline std::uint32_t LampPassSteps(const LampShadowTune& tune, bool repair, std::uint32_t pick) {
    return repair && !(tune.radius_m > 0.0f) ? 0u : pick;
}

"""),
    ],
    R + "vk_point_shadow.h": [
        (r"""    bool history_blend = false, history_blended = false;
""",
         r"""    bool history_blend = false, history_blended = false;
    // bbport (r48_lamp-softness): the lamp's radius of the pass that wrote the history (-1: none
    // yet; a history written at another radius is not read), and the radius the log last told.
    float history_radius_m = -1.0f, told_radius_m = -1.0f;
"""),
    ],
    R + "vk_point_shadow.cpp": [
        (r"""constexpr u64 HalfPointsBit = 2305843009213693952ull;
""",
         r"""constexpr u64 HalfPointsBit = 2305843009213693952ull;
// bbport (r48_lamp-softness): a lamp radius for each graphics_lamp_shadow_softness value
static_assert(LampSoftnessRadii.size() == std::size_t(BbSettings::LampSoftnessCount));
"""),
        (r"""    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
""",
         r"""    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
        // bbport (r48_lamp-softness): the radius graphics_lamp_shadow_softness gives now (Flush
        // takes it again at every pass)
        tune.radius_m = LampSoftnessRadius(
            tune, BbSettings::Get().graphics_lamp_shadow_softness.load(std::memory_order_relaxed));
"""),
        (r"""                    "35184372088832 set, BB_LAMP_SHADOW_SOFT=0, BB_LAMP_SHADOW_HISTORY=0, not the "
""",
         r"""                    "35184372088832 set, graphics_lamp_shadow_softness=sharp or "
                    "BB_LAMP_SHADOW_SOFT=0, BB_LAMP_SHADOW_HISTORY=0, not the "
"""),
        (r"""    const bool history_pass = use_rays && !history_written && history_ours;
    const bool half_points = use_half && BbToggle::Experiment(HalfPointsBit);
""",
         r"""    // bbport (r48_lamp-softness): the lamp's radius as graphics_lamp_shadow_softness has it now
    // (BB_LAMP_SHADOW_SOFT, when it gave a number, wins: LampSoftnessRadius), taken at every pass
    // before anything below is worked out from it, so the menu switches it live. A history
    // written at another radius is not read (history_radius_m, below): it would blend two
    // softnesses.
    const int softness = BbSettings::Get().graphics_lamp_shadow_softness.load(std::memory_order_relaxed);
    tune.radius_m = LampSoftnessRadius(tune, softness);
    if (use_rays && tune.radius_m != told_radius_m) {
        told_radius_m = tune.radius_m;
        std::printf("Ray traced lamps (r48): lamp radius %.2f m (%s%s)%s\n", tune.radius_m,
                    tune.radius_set ? "BB_LAMP_SHADOW_SOFT" : "graphics_lamp_shadow_softness=",
                    tune.radius_set ? ""
                                    : BbSettings::LampSoftnessNames[std::clamp(
                                          softness, 0, BbSettings::LampSoftnessCount - 1)],
                    tune.radius_m > 0.0f
                        ? "; the history starts again at this radius"
                        : ": point lamps without a history, every lamp that reaches a pixel traced");
    }
    const bool history_pass = use_rays && !history_written && history_ours;
    const bool half_points = use_half && BbToggle::Experiment(HalfPointsBit);
"""),
        (r"""        if (kept && history_fresh && history_blended == blend && last_valid && camera.valid &&
            ok) {
""",
         r"""        // bbport (r48_lamp-softness): nor is one written at another lamp radius (the softness
        // changed): as across a camera cut, the pass starts again from this frame's rays.
        if (kept && history_fresh && history_blended == blend &&
            history_radius_m == pass_tune.radius_m && last_valid && camera.valid && ok) {
"""),
        (r"""                "point lamps without a history (BB_LAMP_SHADOW_SOFT=0)",
""",
         r"""                "point lamps without a history, every lamp that reaches a pixel traced "
                "(graphics_lamp_shadow_softness=sharp or BB_LAMP_SHADOW_SOFT=0)",
"""),
        (r"""        history_written = kept;
        history_blend = blend;
""",
         r"""        history_written = kept;
        history_blend = blend;
        history_radius_m = pass_tune.radius_m; // bbport (r48_lamp-softness)
"""),
        (r"""        .steps = use_rays ? lamp_pick : steps,
""",
         r"""        // bbport (r48_lamp-softness): a point lamp traces every lamp (LampPassSteps)
        .steps = use_rays ? LampPassSteps(tune, repair, lamp_pick) : steps,
"""),
    ],
    S + "bbport_settings.h": [
        (r"""inline constexpr const char* MotionStoreNames[] = {"auto", "large", "small"};
static_assert(sizeof(MotionStoreNames) / sizeof(MotionStoreNames[0]) == MotionStoreCount);
""",
         r"""inline constexpr const char* MotionStoreNames[] = {"auto", "large", "small"};
static_assert(sizeof(MotionStoreNames) / sizeof(MotionStoreNames[0]) == MotionStoreCount);

// bbport (r48_lamp-softness): how soft the ray traced lamp shadows are, as the lamp's radius
// (renderer_vulkan/lamp_shadow_tune.h LampSoftnessRadii): sharp a point (every lamp traced, no
// history), soft 0.1 m (the default, the lamp of r42), softer 0.2 m. Live (vk_point_shadow.cpp
// takes it at every pass); BB_LAMP_SHADOW_SOFT, when set to a number, wins.
enum LampSoftness : int { LampSoftnessSharp = 0, LampSoftnessSoft = 1, LampSoftnessSofter = 2, LampSoftnessCount };
inline constexpr const char* LampSoftnessNames[] = {"sharp", "soft", "softer"};
static_assert(sizeof(LampSoftnessNames) / sizeof(LampSoftnessNames[0]) == LampSoftnessCount);
"""),
        (r"""    std::atomic<bool> graphics_lamp_shadow_half{false};          // BB_LAMP_SHADOW_HALF
""",
         r"""    std::atomic<bool> graphics_lamp_shadow_half{false};          // BB_LAMP_SHADOW_HALF
    std::atomic<int> graphics_lamp_shadow_softness{LampSoftnessSoft}; // bbport (r48_lamp-softness), live; BB_LAMP_SHADOW_SOFT
"""),
    ],
    S + "bbport_settings.cpp": [
        (r"""    } else if (key == "graphics_lamp_shadow_half") { // bbport (r37_menu-options)
        v.graphics_lamp_shadow_half = ZeroOrOne(key, value, false);
""",
         r"""    } else if (key == "graphics_lamp_shadow_half") { // bbport (r37_menu-options)
        v.graphics_lamp_shadow_half = ZeroOrOne(key, value, false);
    } else if (key == "graphics_lamp_shadow_softness") { // bbport (r48_lamp-softness)
        int mode = -1;
        for (int m = 0; m < LampSoftnessCount; ++m) {
            if (value == LampSoftnessNames[m]) mode = m;
        }
        if (mode < 0) {
            std::printf("Settings: unknown graphics_lamp_shadow_softness '%s' (expected sharp, soft or "
                        "softer); soft\n", value.c_str());
        }
        v.graphics_lamp_shadow_softness = mode < 0 ? LampSoftnessSoft : mode;
"""),
        (r"""    put("graphics_lamp_shadow_half",flag(v.graphics_lamp_shadow_half)); // bbport (r37_menu-options)
""",
         r"""    put("graphics_lamp_shadow_half",flag(v.graphics_lamp_shadow_half)); // bbport (r37_menu-options)
    put("graphics_lamp_shadow_softness",
        LampSoftnessNames[std::clamp(v.graphics_lamp_shadow_softness.load(),0,LampSoftnessCount-1)]); // r48
"""),
    ],
    S + "bbport_overlay.cpp": [
        (r"""        if (!PreviousPathsNote()) { // bbport (r39_master-debug)
            EnvNote("BB_LAMP_SHADOW_HALF");
        }
    }
""", OVERLAY_ROW),
    ],
    S + "bbport_menu_i18n.cpp": [
        (TABLE_TAIL[lang] + "\n" + FAR_REFIT, TABLE_TAIL[lang] + "\n" + table_entries(lang) + FAR_REFIT)
        for lang in TABLE_LANGS
    ],
    TESTS + "test_lamp_shadow_tune.cpp": [
        (r"""// bbport (r44_half-area-lamp): which pass of a frame has the area lamp (LampPassRadius).
""",
         r"""// bbport (r44_half-area-lamp): which pass of a frame has the area lamp (LampPassRadius).
// bbport (r48_lamp-softness): graphics_lamp_shadow_softness as the lamp's radius
// (LampSoftnessRadius, BB_LAMP_SHADOW_SOFT winning) and a point lamp's steps (LampPassSteps).
"""),
        (r"""        for (int k = 0; k < 8; ++k) {
            assert(LampPassRadius(point, (k & 1) != 0, (k & 2) != 0, (k & 4) != 0) == 0.0f);
        }
    }
""",
         r"""        for (int k = 0; k < 8; ++k) {
            assert(LampPassRadius(point, (k & 1) != 0, (k & 2) != 0, (k & 4) != 0) == 0.0f);
        }
    }
    // bbport (r48_lamp-softness): graphics_lamp_shadow_softness (0 sharp, 1 soft, 2 softer) as the
    // lamp's radius; BB_LAMP_SHADOW_SOFT, when it gives a number, wins; a point lamp traces every
    // lamp (steps 0), an area lamp keeps the pick.
    {
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(!d.radius_set);
        static_assert(LampSoftnessRadii.size() == 3);
        assert(LampSoftnessRadius(d, 0) == 0.0f && LampSoftnessRadius(d, 1) == 0.1f &&
               LampSoftnessRadius(d, 2) == 0.2f);
        assert(LampSoftnessRadius(d, 1) == d.radius_m); // soft: the radius of before (r42)
        assert(LampSoftnessRadius(d, -1) == 0.1f && LampSoftnessRadius(d, 3) == 0.1f); // unknown: soft
        // Softer is wider than soft, and the lamp's centre stays inside the blind sphere at the
        // end of every ray to its disc (a target lies at most the radius from the centre).
        assert(LampSoftnessRadii[2] > LampSoftnessRadii[1] && LampSoftnessRadii[2] < d.clearance_m);
        for (int k = 0; k < 3; ++k) {
            LampShadowTune pass = d;
            pass.radius_m = LampSoftnessRadius(d, k);
            // Sharp keeps no history; soft and softer average the same 9 frames.
            const float frames = LampHistoryFrames(pass);
            assert(k == 0 ? frames == 0.0f : std::abs(frames - 9.0f) < 1e-4f);
            // The pass that takes the history, at full and at half resolution: the setting's
            // radius; a pass beside it: the point lamp, as before.
            assert(LampPassRadius(pass, true, false, false) == pass.radius_m);
            assert(LampPassRadius(pass, true, true, false) == pass.radius_m);
            assert(LampPassRadius(pass, false, false, false) == 0.0f);
            assert(LampPassRadius(pass, true, true, true) == 0.0f); // experiment 2305843009213693952
            // Sharp traces every lamp; with the pick (1) soft and softer keep it, and so does the
            // pass of before r41 (no repair); LANTERN_RT_LAMPS_EXACT=1 (0) traces every lamp.
            assert(LampPassSteps(pass, true, 1u) == (k == 0 ? 0u : 1u));
            assert(LampPassSteps(pass, false, 1u) == 1u);
            assert(LampPassSteps(pass, true, 0u) == 0u && LampPassSteps(pass, false, 0u) == 0u);
        }
        // The variable, when it gives a number, wins over every value of the setting (0 too).
        for (const char* value : {"0", "0.35", "0.05 "}) {
            const LampShadowTune t = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", value}}});
            assert(t.radius_set);
            for (int k = -1; k < 4; ++k) {
                assert(LampSoftnessRadius(t, k) == t.radius_m);
            }
        }
        const LampShadowTune point = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", "0"}}});
        assert(point.radius_m == 0.0f && LampSoftnessRadius(point, 2) == 0.0f && LampPassSteps(point, true, 1u) == 0u);
        const LampShadowTune high = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", "5"}}});
        assert(high.radius_set && LampSoftnessRadius(high, 0) == 0.5f); // clamped, and it still wins
        // Not set, empty or not a number: the setting decides.
        for (const char* value : {"", "0.2m", "soft", "nan"}) {
            const LampShadowTune t = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_SOFT", value}}});
            assert(!t.radius_set && t.radius_m == d.radius_m);
            assert(LampSoftnessRadius(t, 0) == 0.0f && LampSoftnessRadius(t, 2) == 0.2f);
        }
    }
"""),
    ],
    TESTS + "test_settings.cpp": [
        (r"""    assert(s.object_motion_store == BbSettings::MotionStoreAuto &&
           s.startup_object_motion_store == BbSettings::MotionStoreAuto);
    // bbport (r45_drawn-look): the drawn look's keys.""",
         r"""    assert(s.object_motion_store == BbSettings::MotionStoreAuto &&
           s.startup_object_motion_store == BbSettings::MotionStoreAuto);
    // bbport (r48_lamp-softness): graphics_lamp_shadow_softness takes names (sharp, soft, softer).
    // Nothing above sets it: soft; written back; read; saved after a change; an unknown name, a
    // number or another case is soft; a value out of range in memory is saved as the nearest.
    assert(s.graphics_lamp_shadow_softness == BbSettings::LampSoftnessSoft);
    BbSettings::Save();
    assert(Read(path).find("graphics_lamp_shadow_softness=soft\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_lamp_shadow_softness=sharp\n"; }
    BbSettings::Load();
    assert(s.graphics_lamp_shadow_softness == BbSettings::LampSoftnessSharp);
    s.graphics_lamp_shadow_softness = BbSettings::LampSoftnessSofter;
    BbSettings::Save();
    assert(Read(path).find("graphics_lamp_shadow_softness=softer\n") != std::string::npos);
    s.graphics_lamp_shadow_softness = BbSettings::LampSoftnessSharp;
    BbSettings::Load();
    assert(s.graphics_lamp_shadow_softness == BbSettings::LampSoftnessSofter);
    for (const char* bad : {"hard", "2", "Sharp"}) {
        { std::ofstream file(path); file << "graphics_lamp_shadow_softness=" << bad << "\n"; }
        s.graphics_lamp_shadow_softness = BbSettings::LampSoftnessSharp;
        BbSettings::Load();
        assert(s.graphics_lamp_shadow_softness == BbSettings::LampSoftnessSoft);
    }
    s.graphics_lamp_shadow_softness = 7;
    BbSettings::Save();
    assert(Read(path).find("graphics_lamp_shadow_softness=softer\n") != std::string::npos);
    s.graphics_lamp_shadow_softness = BbSettings::LampSoftnessSoft;
    BbSettings::Save();
    // bbport (r45_drawn-look): the drawn look's keys."""),
    ],
    W + "Core/IniFile.cs": [
        (r"""            ("graphics_rt_point_shadows", "0"),
""",
         r"""            ("graphics_rt_point_shadows", "0"),
            // Graphics > Lighting: how soft the ray traced lamp shadows are, the engine's default.
            ("graphics_lamp_shadow_softness", "soft"),
"""),
    ],
    W + "Core/Choices.cs": [
        (r"""            new(L.T("Every 8th frame"), "rare", L.T("About +10% FPS at one heavy spot with ray tracing off, +11% with it on")),
        };
""",
         r"""            new(L.T("Every 8th frame"), "rare", L.T("About +10% FPS at one heavy spot with ray tracing off, +11% with it on")),
        };

        /// <summary>graphics_lamp_shadow_softness: how soft the ray traced lamp shadows are (the
        /// lamp's radius: sharp a point, soft 0.1 m, softer 0.2 m; the in-game menu switches it
        /// live). Soft is the engine's default and what it reads for a value it does not know.</summary>
        public static readonly Choice[] LampShadowSoftness =
        {
            new(@sharp@, "sharp", @sharp_note@),
            new(@soft@, "soft"),
            new(@softer@, "softer", @softer_note@),
        };
""".replace("@sharp@", cs(LAUNCHER_EN["sharp"])).replace("@sharp_note@", cs(LAUNCHER_EN["sharp_note"]))
           .replace("@softer_note@", cs(LAUNCHER_EN["softer_note"])).replace("@softer@", cs(LAUNCHER_EN["softer"]))
           .replace("@soft@", cs(LAUNCHER_EN["soft"]))),
    ],
    W + "Views/GraphicsPage.cs": GRAPHICS_EDITS,
    LAUNCH + "LanternLauncher/Views/GraphicsPage.cs": GRAPHICS_EDITS,
    LAUNCH + "tests/LocalizationChecks/Program.cs": [
        (r"""    Require(Choices.SunFarShadows.Select(c => c.Value).SequenceEqual(new[] { "game", "alternate", "rare" }), "Far sun shadows choices changed");
""",
         r"""    Require(Choices.SunFarShadows.Select(c => c.Value).SequenceEqual(new[] { "game", "alternate", "rare" }), "Far sun shadows choices changed");
    Require(Choices.LampShadowSoftness.Select(c => c.Value).SequenceEqual(new[] { "sharp", "soft", "softer" }), "Lamp shadow softness choices changed");
"""),
    ],
    LAUNCH + "tests/LooksChecks/Program.cs": [
        (r"""Require(Choices.SunFarShadows[0].Note == null && Choices.SunFarShadows.Skip(1).All(c => c.Note is { Length: > 0 and <= 110 }),
    "A far sun shadow choice does not say what it gains in a note the row shows whole");
""",
         r"""Require(Choices.SunFarShadows[0].Note == null && Choices.SunFarShadows.Skip(1).All(c => c.Note is { Length: > 0 and <= 110 }),
    "A far sun shadow choice does not say what it gains in a note the row shows whole");
// Lamp shadow softness (Graphics > Lighting): starts at the engine's default, soft, and is in no look.
Require(Choices.LampShadowSoftness.Select(c => c.Value).SequenceEqual(new[] { "sharp", "soft", "softer" }), "The lamp shadow softness values changed");
Require(IniFile.Defaults.Count(d => d.Key == "graphics_lamp_shadow_softness") == 1 &&
        IniFile.Defaults.Single(d => d.Key == "graphics_lamp_shadow_softness").Value == "soft",
    "graphics_lamp_shadow_softness: not in the settings defaults once, at soft");
Require(!knobs.Contains("graphics_lamp_shadow_softness"), "Lamp shadow softness is part of a look");
Require(Choices.LampShadowSoftness[1].Note == null && Choices.LampShadowSoftness.Where((c, i) => i != 1).All(c => c.Note is { Length: > 0 and <= 110 }),
    "A lamp shadow softness choice does not say what it changes in a note the row shows whole");
"""),
    ],
}
for _lang in LANGS:
    EDITS[W + "Localization/%s.json" % _lang] = [(JSON_ANCHOR, json_entries(_lang) + JSON_ANCHOR)]


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text."""
    ok = True
    tune = texts[R + "lamp_shadow_tune.h"]
    cpp = texts[R + "vk_point_shadow.cpp"]
    if tune.count("inline constexpr std::array<float, 3> LampSoftnessRadii{0.0f, 0.1f, 0.2f};") != 1 or \
            tune.count("inline std::uint32_t LampPassSteps(") != 1 or tune.count("tune.radius_set = !std::isnan(soft);") != 1:
        print("lamp_shadow_tune.h should hold the radii (0, 0.1, 0.2), LampPassSteps and radius_set once")
        ok = False
    # The radius is taken at every pass and at Ready; the history is read only at the radius it
    # was written at; a point lamp traces every lamp; the pick is not pushed bare any more.
    if cpp.count("tune.radius_m = LampSoftnessRadius(") != 2 or \
            cpp.count("history_radius_m == pass_tune.radius_m") != 1 or \
            cpp.count("history_radius_m = pass_tune.radius_m;") != 1 or \
            cpp.count(".steps = use_rays ? LampPassSteps(tune, repair, lamp_pick) : steps,") != 1 or \
            ".steps = use_rays ? lamp_pick : steps," in cpp:
        print("vk_point_shadow.cpp: the radius, the history's radius or the steps are not as the patch made them")
        ok = False
    # The radius must be set before the pass's tuning is worked out from it.
    at_radius = cpp.find("    tune.radius_m = LampSoftnessRadius(tune, softness);")
    if at_radius < 0 or not (at_radius < cpp.find("const bool beside = ") < cpp.find("pass_tune.radius_m = LampPassRadius(")):
        print("vk_point_shadow.cpp: the radius is not set before the pass's tuning")
        ok = False
    settings_h, settings_cpp = texts[S + "bbport_settings.h"], texts[S + "bbport_settings.cpp"]
    if settings_h.count('LampSoftnessNames[] = {"sharp", "soft", "softer"};') != 1 or \
            settings_h.count("graphics_lamp_shadow_softness{LampSoftnessSoft}") != 1 or \
            settings_cpp.count('key == "graphics_lamp_shadow_softness"') != 1 or \
            settings_cpp.count('put("graphics_lamp_shadow_softness",') != 1:
        print("the setting is not declared, parsed and saved once")
        ok = False
    # The menu row's texts, and their translations by the same English text.
    overlay, i18n = texts[S + "bbport_overlay.cpp"], texts[S + "bbport_menu_i18n.cpp"]
    nl = "\r\n" if "\r\n" in overlay else "\n"
    if overlay.count(fix(lit(EN_HINT, " " * 12), nl)) != 1 or overlay.count(fix(lit(RU_HINT, " " * 12), nl)) != 1 or \
            overlay.count('Item("Lamp shadow softness"') != 1:
        print("the menu row or its hint is not in bbport_overlay.cpp once")
        ok = False
    for k, en in enumerate(MENU["en"]):
        if i18n.count('    {"%s",' % en) != 8:
            print("bbport_menu_i18n.cpp: %r is not in the eight tables" % en[:40])
            ok = False
    glyphs = set()
    if os.path.isfile(GLYPHS):
        glyphs = {int(x.strip()[2:], 16) for x in open(GLYPHS, encoding="utf-8").read().split(",") if x.strip()}
    else:
        print("cannot check the menu's Chinese text: %s is missing" % GLYPHS)
        ok = False
    missing = sorted({c for t in MENU["zh"] for c in t if ord(c) > 0x7e and ord(c) not in glyphs})
    if glyphs and missing:
        print("the menu's Chinese text uses characters the menu font does not have: %s" % "".join(missing))
        ok = False
    # The launcher: the page rows, the choices, and the 7 strings in every language file; a note
    # the row shows whole (at most 110 characters) in every language.
    pages = [p for p in texts if p.endswith("/Views/GraphicsPage.cs")]
    catalogs = [p for p in texts if p.endswith(".json")]
    if len(pages) != 2 or len(catalogs) != 13 or \
            any(texts[p].count('"graphics_lamp_shadow_softness");') != 1 or texts[p].count(cs(LAUNCHER_EN["hint"])) != 1
                for p in pages):
        print("the launcher's row is not in both GraphicsPage.cs files once")
        ok = False
    for p in catalogs:
        try:
            parsed = json.loads(texts[p])
        except ValueError as e:
            print("%s does not parse: %s" % (p, e))
            ok = False
            continue
        for k in LAUNCHER_KEYS:
            if texts[p].count("  %s: " % json.dumps(LAUNCHER_EN[k], ensure_ascii=False)) != 1 or not parsed.get(LAUNCHER_EN[k]):
                print("%s: %r is not there once" % (p, LAUNCHER_EN[k][:40]))
                ok = False
    for lang in LANGS + ["en"]:
        notes = [LAUNCHER_EN[k] for k in ("sharp_note", "softer_note")] if lang == "en" else \
                [LAUNCHER_TR[lang][LAUNCHER_KEYS.index(k)] for k in ("sharp_note", "softer_note")]
        if any(len(n) > 110 for n in notes):
            print("%s: a choice's note is longer than 110 characters" % lang)
            ok = False
    if texts[W + "Core/Choices.cs"].count("public static readonly Choice[] LampShadowSoftness") != 1 or \
            texts[W + "Core/IniFile.cs"].count('("graphics_lamp_shadow_softness", "soft"),') != 1:
        print("Choices.LampShadowSoftness or the ini default is not there once")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
        if not os.path.isfile(path):
            if not quiet:
                print("no such file: %s" % path)
            return None
        t = open(path, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in t else "\n"
        for old, new in (pairs if mode != "revert" else reversed(pairs)):
            a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
            n = t.count(a)
            if n != 1:
                if not quiet:
                    print("anchor found %d times (want 1) in %s: %a" % (n, path, a[:90]))
                return None
            t = t.replace(a, b)
        out[path] = t
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r48_lamp-softness.py check|apply|revert   (the tree: R48_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
            return 1
        return 1
    if mode == "check":
        print("anchors OK (applies cleanly)")
        return 0
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target (one rename a file). If a step fails, what was already moved
    # is put back from the texts read at the start, so the tree is never left half patched.
    before = {path: open(path, "rb").read() for path in out}
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(path, "wb") as f:
                f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
