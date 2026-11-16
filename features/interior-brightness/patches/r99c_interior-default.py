# r99c_interior-default: FEATURE patch (lamp work, "dim interiors"), on top of r99_interior-exposure and
# r99b_interior-brightness (both applied; apply them first, revert this one before them). Owner,
# 2026-11-16, after seeing the Hunter's house, the sewer, the library and the church at off, +0.75
# and +1 (the library and the church also at +1.5 and +2.5), verbatim: "Use +0.75", then: "Also for the
# exposure default to 0.75 but allow a slider to change".
#
# What it does:
#  1. The interior brightness lift is ON by default, with the largest lift 0.75 stops (it was off
#     unless BB_INTERIOR_EXPOSURE=1, the largest lift 1.5). r99b's defaults target 0.05, strength 0.5
#     become r99's 0.02 and 1 (the task: "keep target 0.02 and strength 1"): a view metered at 0.02
#     or above gets nothing, so the dream house (0.018-0.025) gets no lift worth seeing (at most
#     +0.15 EV at 0.018), the graveyard and other open places none (open samples), the library
#     without the Remaster mod (metered about 0.014) about +0.5 stops (log2(0.02/0.014)), with the mod
#     (0.0011-0.0055) the full +0.75.
#  2. A setting, lantern.ini key graphics_interior_brightness: the largest lift in stops, 0..3, default
#     0.75, 0 = off (bbport_settings.h/.cpp: constants, a std::atomic<float>, Load with a clamp and the
#     default for a value that is not finite, Save with two decimals). A missing key is the default (the
#     member's initializer); nothing writes the player's lantern.ini but the game's own settings save.
#     Slider in the in-game menu (bbport_overlay.cpp, a section Interior brightness before the Light
#     glow and flicker section: 0..3 in steps of 0.25, "%.2f EV", help text "lifts only dark interiors;
#     outdoors and bright rooms stay as they are", EnvNote for both variables), the title and the help
#     in all eight translation tables (non-English texts need a native speaker's check; the Chinese
#     uses only characters of LanternMenuSC-glyphs.txt, checked here). The shipped default is in
#     IniFile.cs Defaults (launcher, one line) and pinned by LooksChecks (not a look knob); there is NO
#     launcher slider (the in-game menu only, like r109's rows in the menu), no Localization file.
#  3. The environment wins and keeps working for tests: BB_INTERIOR_EXPOSURE set and not empty: 0 off,
#     1 on (at the setting's lift, at 0.75 when the setting is 0), 2 SHOW (all numbers exaggerated,
#     3 stops, unless set), any other text off; unset or empty: the setting decides (on when its lift
#     is above 0). BB_INTERIOR_EXPOSURE_MAX_EV (a number) is the largest lift in place of the slider
#     (0 there: off, unless BB_INTERIOR_EXPOSURE forces it on); an unreadable one is as unset.
#     _TARGET, _STRENGTH, _OPEN_M: unchanged, environment only.
#  4. Read LIVE: Vulkan::InteriorExposure::Meter resolves the setting and the environment
#     (BbInteriorExposure::Resolve, pure, unit tested) at EVERY call, one relaxed atomic load plus a
#     few compares; the environment is parsed once. A slider move acts on the next frame. 0 -> the
#     pass is no longer recorded and the applied lift goes back to none at once (Rest(): factor exactly
#     1, readings forgotten, open share back to its start), one log line; 0 -> above 0 again: on again,
#     one log line, the pipeline is made at the first frame with the lift above 0 and kept.
#  Log: once "Interior exposure (r99c, on by <BB_INTERIOR_EXPOSURE|graphics_interior_brightness>
#  ...): ... at most +0.75 EV (from <where>)" (replaces r99b's once-line), "Interior exposure (r99c):
#  the largest lift is now X EV (from ...)" after a change (checked at the 2 s line), "... off ..." and
#  "... on again ...", plus r99b's periodic line with its counters (metered, read, held, busy, no
#  camera), unchanged.
#
# Cost: now ON by default, so the cost reaches every player on an upscaler path (DLSS, FSR, XeSS, TAA)
# with the GT7 or ACES curve: r99b's one dispatch of one 256-thread group, estimate 0.01-0.03 ms at
# 1080p internal (NOT MEASURED), a 128-byte host buffer and one compute pipeline. Setting 0 and no
# variable: Meter returns after the resolve (an atomic load and a few compares), nothing recorded, the
# factor exactly 1.0f. Memory: unchanged.
#
# Files: engine/gpu/shim/bbport_interior_exposure.h (defaults, Env, ParseEnv, Resolve, MaxSource,
# Environment replaces Knobs), renderer_vulkan/vk_interior_exposure.cpp/.h (resolve per call, Rest,
# log lines, static_asserts tying the settings constants), bbport_settings.h/.cpp, bbport_overlay.cpp,
# bbport_menu_i18n.cpp, engine/tests/test_interior_exposure.cpp (the old numbers pinned to r99b's
# explicit values, new section h) and test_settings.cpp, launcher IniFile.cs and LooksChecks, README.md
# (the Interior exposure section replaced). No CMake or build.sh change (both tests already built).
#
# Use: python -I -X utf8 r99c_interior-default.py check | apply | revert
# Root: R99C_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in
# r99c_backup next to this script. Each edit replaces an old text found exactly once with a new one;
# revert puts each old text back where its new text is found exactly once. Needs r99b applied (apply
# refuses without it; the r99b state is the old text of the first edits).
import json, os, re, sys

ROOT = os.environ.get("R99C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r99c_backup")
SH = "engine/gpu/shim/"
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HDR = SH + "bbport_interior_exposure.h"
SET_H = SH + "bbport_settings.h"
SET_C = SH + "bbport_settings.cpp"
OVERLAY = SH + "bbport_overlay.cpp"
I18N = SH + "bbport_menu_i18n.cpp"
VK_H = RV + "vk_interior_exposure.h"
VK_C = RV + "vk_interior_exposure.cpp"
T_IE = "engine/tests/test_interior_exposure.cpp"
T_SET = "engine/tests/test_settings.cpp"
INI = "launcher/windows/BloodborneLauncher/Core/IniFile.cs"
LOOKS = "launcher/windows/tests/LooksChecks/Program.cs"
GLYPHS = "engine/gpu/third_party/fonts/LanternMenuSC-glyphs.txt"
README = "README.md"

# ------------------------------------------------------------------ menu texts
EN_TITLE = "Interior brightness"
EN_HINT = ("Live, default 0.75. Lifts only dark interiors; outdoors and bright rooms stay as they are. "
           "The value is the largest lift, in stops of exposure; 0 is off. Works with the GT7 and ACES "
           "tone maps, not the game's own curve.")
RU_TITLE = "Яркость интерьеров"
RU_HINT = ("Работает сразу, по умолчанию 0.75. Поднимает яркость только в тёмных помещениях; на улице "
           "и в светлых комнатах всё остаётся как есть. Значение — наибольший подъём в ступенях "
           "экспозиции; 0 — выкл. Работает с тон-мапами GT7 и ACES, но не с собственной кривой игры.")
TR = {
    "kSpanish": (
        "Brillo de interiores",
        "Efecto inmediato, 0.75 por defecto. Solo aclara los interiores oscuros; el exterior y las "
        "salas luminosas no cambian. El valor es el aumento máximo, en pasos de exposición; 0 lo "
        "desactiva. Funciona con los mapas de tonos GT7 y ACES, no con la curva propia del juego."),
    "kPortugueseBrazil": (
        "Brilho de interiores",
        "Aplica na hora, padrão 0.75. Clareia apenas interiores escuros; áreas externas e salas "
        "claras ficam como estão. O valor é o aumento máximo, em passos de exposição; 0 desliga. "
        "Funciona com os mapas de tons GT7 e ACES, não com a curva própria do jogo."),
    "kFrench": (
        "Luminosité des intérieurs",
        "Effet immédiat, 0.75 par défaut. N'éclaircit que les intérieurs sombres ; l'extérieur et "
        "les pièces claires ne changent pas. La valeur est l'augmentation maximale, en valeurs "
        "d'exposition ; 0 désactive. Fonctionne avec les courbes de tons GT7 et ACES, pas avec la "
        "courbe propre du jeu."),
    "kGerman": (
        "Helligkeit von Innenräumen",
        "Wirkt sofort, Standard 0.75. Hellt nur dunkle Innenräume auf; draußen und in hellen "
        "Räumen bleibt alles, wie es ist. Der Wert ist die größte Aufhellung in Blendenstufen; 0 "
        "schaltet aus. Funktioniert mit den Tonemappings GT7 und ACES, nicht mit der eigenen Kurve "
        "des Spiels."),
    "kItalian": (
        "Luminosità degli interni",
        "Immediato, predefinito 0.75. Schiarisce solo gli interni bui; all'aperto e nelle stanze "
        "luminose tutto resta com'è. Il valore è l'aumento massimo, in stop di esposizione; 0 "
        "disattiva. Funziona con le curve tonali GT7 e ACES, non con la curva propria del gioco."),
    "kPolish": (
        "Jasność wnętrz",
        "Działa od razu, domyślnie 0.75. Rozjaśnia tylko ciemne wnętrza; na zewnątrz i w jasnych "
        "pomieszczeniach nic się nie zmienia. Wartość to największe rozjaśnienie w stopniach "
        "ekspozycji; 0 wyłącza. Działa z mapowaniem tonów GT7 i ACES, nie z własną krzywą gry."),
    "kTurkish": (
        "İç mekân parlaklığı",
        "Anında uygulanır, varsayılan 0.75. Yalnızca karanlık iç mekânları aydınlatır; dış mekân "
        "ve aydınlık odalar olduğu gibi kalır. Değer, pozlama stopu cinsinden en büyük "
        "aydınlatmadır; 0 kapatır. GT7 ve ACES ton eşlemesiyle çalışır, oyunun kendi eğrisiyle "
        "çalışmaz."),
    "kChinese": (
        "内部亮度",
        "立即生效，默认 0.75。只提亮较暗的内部空间；外部和明亮的房间保持不变。该值为最大提亮量，"
        "单位为曝光档；0 为关闭。适用于 GT7 和 ACES 色调映射，不适用于游戏原有的色调映射。"),
}
# The eight menu tables: the anchor is the same "Lamp fog glow size" entry and the line after it that
# r109b's rows use; the new entries go right after it.
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
    t, h = TR[lang]
    return '    {"%s", "%s"},\n    {"%s", "%s"},\n' % (EN_TITLE, t, EN_HINT, h)


OVERLAY_ANCHOR = (
    '            "оставляют больше исходного изображения. При 0 стиль вообще не работает. Применяется "\n'
    '            "сразу."));\n'
    '    }\n')
OVERLAY_BLOCK = (
    "    // bbport (r99c_interior-default): the interior brightness, the largest lift of the dark-interior\n"
    "    // exposure lift (r99b): live (the renderer reads it every frame), 0 is off, steps of 0.25. A set\n"
    "    // BB_INTERIOR_EXPOSURE or BB_INTERIOR_EXPOSURE_MAX_EV wins over the slider (EnvNote).\n"
    '    Section("%s",\n            "%s");\n' % (EN_TITLE, RU_TITLE) +
    '    if (const char* label = Item("%s",\n                                 "%s")) {\n' % (EN_TITLE, RU_TITLE) +
    "        float stops = s.graphics_interior_brightness;\n"
    "        const bool moved = ImGui::SliderFloat(label, &stops, BbSettings::InteriorBrightnessMin,\n"
    "                                              BbSettings::InteriorBrightnessMax, \"%.2f EV\",\n"
    "                                              ImGuiSliderFlags_AlwaysClamp);\n"
    "        Store(s.graphics_interior_brightness, std::round(stops * 4.0f) * 0.25f, moved);\n"
    "        Hint(BbSettings::MenuText(\n" + cpp_lit(EN_HINT, 12) + ",\n" + cpp_lit(RU_HINT, 12) + "));\n"
    '        EnvNote("BB_INTERIOR_EXPOSURE");\n'
    '        EnvNote("BB_INTERIOR_EXPOSURE_MAX_EV");\n'
    "    }\n")

# ------------------------------------------------------------------ texts of the edits
HDR_KNOBS_OLD = r'''// Knobs (environment, read once by Knobs()): BB_INTERIOR_EXPOSURE 1 on, 2 SHOW (the Show* values
// for every number not set), anything else off; BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _MAX_EV,
// _OPEN_M (0: only depth 1 counts as open, r99's rule). A missing, unreadable or non-finite number
// takes the default, then the range. r99's exact behaviour: TARGET=0.02 STRENGTH=1 OPEN_M=0 (the
// open share is then eased too).
'''
HDR_KNOBS_NEW = r'''// Knobs (r99c_interior-default): ON by default, the largest lift 0.75 stops. The setting
// graphics_interior_brightness (BbSettings, 0..3 stops, default 0.75, 0 = off) is the largest lift;
// the meter reads it at every call, so a slider acts at once. The environment is read once
// (Environment()) and wins over the setting: BB_INTERIOR_EXPOSURE set and not empty: 0 off, 1 on
// (at the setting's lift, DefaultMaxEv when the setting is 0), 2 SHOW (the Show* values for every
// number not set), any other text off; unset or empty: the setting decides. BB_INTERIOR_EXPOSURE_MAX_EV
// (a number; an unreadable one is as unset) is the largest lift in place of the setting.
// BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _OPEN_M (0: only depth 1 counts as open, r99's rule) have
// no setting. A missing, unreadable or non-finite number takes the default, then the range. Resolve()
// puts the two together. r99's exact behaviour: OPEN_M=0 MAX_EV=1.5 (the open share is then eased too).
'''
HDR_MEAS_OLD = r'''// Measured 2026-11-15 (hero light off, log-average before the tone curve; no measured view had any
// sample at depth 1): the library 0.014 (looking up 0.011; 0.0055 with the BB PC Remaster mod),
// church-candles 0.040 (0.012 with the mod), the dream house 0.052 (0.030 with the mod, hero light
// kept), the dark alley 0.025 (0.0097 with the mod). The defaults close half the gap in stops to
// 0.05: the library rises about +0.9 EV (+1.5 EV, the cap, with the mod), church-candles with the
// mod about +1.0 EV, the dream house with the mod about +0.37 EV, the dream house without it 0, so
// rooms stay in the same order of brightness. Outdoors relies on the open share: how many samples
// open views have is what the r99b log line measures (not known when this was written).
'''
HDR_MEAS_NEW = r'''// Measured 2026-11-15 (hero light off, log-average before the tone curve; no measured view had any
// sample at depth 1): the library 0.014 (looking up 0.011; 0.0011-0.0055 with the BB PC Remaster
// mod), church-candles 0.040 (0.0053-0.012 with the mod), the dream house 0.018-0.052 (0.030 with
// the mod, hero light kept), the dark alley 0.025 (0.0097 with the mod). The defaults (target 0.02,
// strength 1, at most 0.75 stops: the owner's pick, 2026-11-16) lift the library +0.5 EV without the
// mod (log2(0.02 / 0.014)) and the full +0.75 with it, church-candles with the mod +0.7 to +0.75 EV,
// the dream house at most +0.15 EV (at 0.018; 0 from 0.02 up), church-candles without the mod
// nothing. Open places rely on the open share (the graveyard at night showed 100 % open samples and
// no lift).
'''
HDR_CONST_OLD = r'''inline constexpr float DefaultTarget = 0.05f;  ///< log-average luminance aimed at
inline constexpr float DefaultStrength = 0.5f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 1.5f;    ///< the largest lift, stops
'''
HDR_CONST_NEW = r'''inline constexpr float DefaultTarget = 0.02f;  ///< log-average luminance aimed at
inline constexpr float DefaultStrength = 1.0f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 0.75f;   ///< the largest lift, stops (= BbSettings::InteriorBrightnessDefault)
'''
HDR_KNOBS_FN_OLD = r'''/// The knobs, read from the environment at the first call.
inline const Config& Knobs() {
    static const Config config = Parse(
        std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
        std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"),
        std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"));
    return config;
}
'''
HDR_KNOBS_FN_NEW = r'''/// A number that Number() reads from `text`: not null, not empty, all of it a finite number.
inline bool Readable(const char* text) {
    if (!text || !*text) {
        return false;
    }
    char* end = nullptr;
    const float read = std::strtof(text, &end);
    return end != text && *end == '\0' && std::isfinite(read);
}

/// What the environment says (read once, Environment()); the setting is Resolve()'s other half.
struct Env {
    Config config;           ///< Parse of the variables (mode Off unless BB_INTERIOR_EXPOSURE is 1 or 2)
    bool mode_set = false;   ///< BB_INTERIOR_EXPOSURE is set and not empty: it decides on, off or SHOW
    bool max_ev_set = false; ///< BB_INTERIOR_EXPOSURE_MAX_EV is a number: the largest lift
};

inline Env ParseEnv(const char* mode, const char* target, const char* strength, const char* max_ev,
                    const char* open_m) {
    Env e;
    e.config = Parse(mode, target, strength, max_ev, open_m);
    e.mode_set = mode != nullptr && mode[0] != '\0';
    e.max_ev_set = Readable(max_ev);
    return e;
}

/// The knobs of one frame: the environment's where it says something, else `setting`
/// (graphics_interior_brightness, stops; not finite: DefaultMaxEv; clamped to 0..MaxEvLimit), whose
/// 0 is off. SHOW keeps its own values (the variable's number for the largest lift when set).
/// BB_INTERIOR_EXPOSURE=1 with a setting of 0 and no number is on at DefaultMaxEv. Without the mode
/// variable a largest lift of 0 (the setting, or the number) is off, so nothing is made.
inline Config Resolve(const Env& env, float setting) {
    Config c = env.config;
    if (c.mode == Show) {
        return c;
    }
    const float stops = std::isfinite(setting) ? std::clamp(setting, 0.0f, MaxEvLimit) : DefaultMaxEv;
    float max_ev = env.max_ev_set ? c.max_ev : stops;
    if (env.mode_set) {
        if (c.mode != Off && !env.max_ev_set && !(max_ev > 0.0f)) {
            max_ev = DefaultMaxEv;
        }
    } else {
        c.mode = max_ev > 0.0f ? On : Off;
    }
    c.max_ev = max_ev;
    return c;
}

/// Where Resolve()'s largest lift comes from, for the log.
inline const char* MaxSource(const Env& env, float setting) {
    if (env.max_ev_set) {
        return "BB_INTERIOR_EXPOSURE_MAX_EV";
    }
    if (env.config.mode == Show) {
        return "the SHOW value";
    }
    return std::isfinite(setting) && setting > 0.0f ? "graphics_interior_brightness" : "the default";
}

/// The environment, read at the first call.
inline const Env& Environment() {
    static const Env env =
        ParseEnv(std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
                 std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"),
                 std::getenv("BB_INTERIOR_EXPOSURE_OPEN_M"));
    return env;
}
'''
HDR_SCALE_OLD = r'''/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 unless the knob is on: only
/// Vulkan::InteriorExposure::Meter writes it.
'''
HDR_SCALE_NEW = r'''/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 until the meter has applied a
/// lift, and again once it is switched off (the setting at 0, no variable): only
/// Vulkan::InteriorExposure::Meter writes it.
'''

VKH_OLD = r'''/// BB_INTERIOR_EXPOSURE not 1 or 2 it returns at once: nothing is made, read, recorded or printed.
'''
VKH_NEW = r'''/// the setting graphics_interior_brightness at 0 and BB_INTERIOR_EXPOSURE not 1 or 2 (the setting
/// and the environment are resolved at every call) it returns at once: nothing is recorded or read;
/// a lift it had applied goes back to none, once (BbInteriorExposure::Resolve, r99c).
'''

VKC_ASSERT_OLD = r'''constexpr u32 SlotCount = 4;
constexpr float SampleCount = float(Policy::GridX * Policy::GridY);
'''
VKC_ASSERT_NEW = r'''constexpr u32 SlotCount = 4;
constexpr float SampleCount = float(Policy::GridX * Policy::GridY);

// bbport (r99c_interior-default): graphics_interior_brightness is the largest lift.
static_assert(BbSettings::InteriorBrightnessDefault == Policy::DefaultMaxEv &&
              BbSettings::InteriorBrightnessMax == Policy::MaxEvLimit &&
              BbSettings::InteriorBrightnessMin == 0.0f);
'''
VKC_STATE_OLD = r'''    u32 metered = 0, read = 0, held = 0, busy = 0, no_camera = 0; ///< since the last line
};
'''
VKC_STATE_NEW = r'''    u32 metered = 0, read = 0, held = 0, busy = 0, no_camera = 0; ///< since the last line
    bool active = false;   ///< the meter ran at the last call (the setting or a variable said on)
    bool was_off = false;  ///< it was switched off after it had run: the next on says so
    float said_max = 0.0f; ///< the largest lift the log last named
};

/// The meter's state once it exists (null before the first call with the meter on).
State* g_state = nullptr;

/// The meter is switched off (the setting went to 0): no lift at once, the factor exactly 1, the
/// readings forgotten (the pipeline and the buffer stay). Does nothing when it was not running.
void Rest(State& s) {
    if (!s.active) {
        return;
    }
    s.active = false;
    s.was_off = true;
    s.applied_ev = 0.0f;
    s.open_eased = Policy::OpenStart;
    s.last = Policy::Lift{};
    s.last_reading = Policy::Reading{};
    s.last_open_m = 0.0f;
    s.have_read = false;
    s.pending.fill(false);
    s.metered = s.read = s.held = s.busy = s.no_camera = 0;
    Policy::applied_scale.store(1.0f, std::memory_order_relaxed);
    std::printf("Interior exposure (r99c): off (graphics_interior_brightness is 0): no lift, the "
                "exposure is the game's own\n");
}
'''
VKC_SAYON_SIG_OLD = r'''void SayOn(const Policy::Config& knobs, bool ready) {
'''
VKC_SAYON_SIG_NEW = r'''void SayOn(const Policy::Config& knobs, bool ready, const char* on_by, const char* max_from) {
'''
VKC_SAYON_1_OLD = r'''    std::printf("Interior exposure (r99b, BB_INTERIOR_EXPOSURE=%d%s): meter of %ux%u samples of "
'''
VKC_SAYON_1_NEW = r'''    std::printf("Interior exposure (r99c, on by %s%s): meter of %ux%u samples of "
'''
VKC_SAYON_2_OLD = r'''                "target %.3f, strength %.2f, at most %+.2f EV; open samples: %s; no lift with %.0f%% "
'''
VKC_SAYON_2_NEW = r'''                "target %.3f, strength %.2f, at most %+.2f EV (from %s); open samples: %s; no lift with %.0f%% "
'''
VKC_SAYON_3_OLD = r'''                knobs.mode, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev, open,
'''
VKC_SAYON_3_NEW = r'''                on_by, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev, max_from, open,
'''
VKC_HEAD_OLD = r'''    const Policy::Config& knobs = Policy::Knobs();
    if (knobs.mode == Policy::Off || !color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    if (!s.tried) {
'''
VKC_HEAD_NEW = r'''    // bbport (r99c_interior-default): the setting (live) and the environment (read once) at every call.
    const Policy::Env& env = Policy::Environment();
    const float setting =
        BbSettings::Get().graphics_interior_brightness.load(std::memory_order_relaxed);
    const Policy::Config knobs = Policy::Resolve(env, setting);
    if (knobs.mode == Policy::Off) {
        if (g_state) {
            Rest(*g_state);
        }
        return;
    }
    if (!color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    g_state = &s;
    if (!s.tried) {
'''
VKC_SAYCALL_OLD = r'''        SayOn(knobs, s.ready);
'''
VKC_SAYCALL_NEW = r'''        SayOn(knobs, s.ready, env.mode_set ? "BB_INTERIOR_EXPOSURE" : "graphics_interior_brightness",
              Policy::MaxSource(env, setting));
        s.said_max = knobs.max_ev;
'''
VKC_READY_OLD = r'''    if (!s.ready) {
        return;
    }
    const auto now = Clock::now();
'''
VKC_READY_NEW = r'''    if (!s.ready) {
        return;
    }
    if (!s.active) {
        s.active = true;
        if (s.was_off) {
            s.was_off = false;
            std::printf("Interior exposure (r99c): on again, at most %+.2f EV (from %s)\n", knobs.max_ev,
                        Policy::MaxSource(env, setting));
            s.said_max = knobs.max_ev;
        }
    }
    const auto now = Clock::now();
'''
VKC_LINE_OLD = r'''    if (since >= (knobs.mode == Policy::Show ? 1.0f : 2.0f)) {
        s.last_line = now;
'''
VKC_LINE_NEW = r'''    if (since >= (knobs.mode == Policy::Show ? 1.0f : 2.0f)) {
        s.last_line = now;
        if (std::fabs(knobs.max_ev - s.said_max) > 1e-4f) {
            std::printf("Interior exposure (r99c): the largest lift is now %+.2f EV (from %s)\n",
                        knobs.max_ev, Policy::MaxSource(env, setting));
            s.said_max = knobs.max_ev;
        }
'''

SETH_ANCHOR = '''inline constexpr float LocalLightCoreMin = 0.0f, LocalLightCoreMax = 0.35f, LocalLightCoreDefault = 0.05f;
'''
SETH_CONST = '''// bbport (r99c_interior-default): the interior brightness, the largest lift in stops of the dark-interior
// exposure lift (live; 0 = off; a set BB_INTERIOR_EXPOSURE or BB_INTERIOR_EXPOSURE_MAX_EV wins). Tied to
// BbInteriorExposure by static_asserts in vk_interior_exposure.cpp.
inline constexpr float InteriorBrightnessMin = 0.0f, InteriorBrightnessMax = 3.0f, InteriorBrightnessDefault = 0.75f;
'''
SETH_MEMBER_ANCHOR = '''    std::atomic<bool> engine_previous_paths{false}; // bbport (r39_master-debug): PreviousPathsMask, live
'''
SETH_MEMBER = '''    // bbport (r99c_interior-default): live, the renderer reads it at every frame; a set BB_INTERIOR_EXPOSURE
    // or BB_INTERIOR_EXPOSURE_MAX_EV wins over it.
    std::atomic<float> graphics_interior_brightness{InteriorBrightnessDefault}; // 0..3 stops; 0: off
'''
SETC_LOAD_ANCHOR = '''    } else if (key == "engine_previous_paths") { // bbport (r39_master-debug)
'''
SETC_LOAD = '''    } else if (key == "graphics_interior_brightness") { // bbport (r99c_interior-default)
        v.graphics_interior_brightness =
            Clamp(std::isfinite(f) ? f : InteriorBrightnessDefault, InteriorBrightnessMin, InteriorBrightnessMax);
'''
SETC_SAVE_ANCHOR = '''    put("engine_previous_paths", flag(v.engine_previous_paths)); // bbport (r39_master-debug)
'''
SETC_SAVE = '''    put("graphics_interior_brightness", fixed(v.graphics_interior_brightness, 2)); // bbport (r99c)
'''

T_SET_ANCHOR = '''    // bbport (r39_master-debug): engine_previous_paths and the debug_* keys. Nothing above sets
'''
T_SET_BLOCK = r'''    // bbport (r99c_interior-default): graphics_interior_brightness. Nothing above sets it: the default
    // 0.75 (on); written back; read; saved after a change; a value outside 0..3 is the nearest end; a
    // text that is no number is 0 (off); a value that is not finite is the default.
    static_assert(BbSettings::InteriorBrightnessMin == 0.0f && BbSettings::InteriorBrightnessMax == 3.0f &&
                  BbSettings::InteriorBrightnessDefault == 0.75f);
    assert(s.graphics_interior_brightness == BbSettings::InteriorBrightnessDefault);
    BbSettings::Save();
    assert(Read(path).find("graphics_interior_brightness=0.75\n") != std::string::npos);
    { std::ofstream file(path); file << "graphics_interior_brightness=1.25\n"; }
    BbSettings::Load();
    assert(s.graphics_interior_brightness == 1.25f);
    s.graphics_interior_brightness = 0.0f;
    BbSettings::Save();
    assert(Read(path).find("graphics_interior_brightness=0.00\n") != std::string::npos);
    s.graphics_interior_brightness = 2.0f;
    BbSettings::Load();
    assert(s.graphics_interior_brightness == 0.0f);
    { std::ofstream file(path); file << "graphics_interior_brightness=9\n"; }
    BbSettings::Load();
    assert(s.graphics_interior_brightness == BbSettings::InteriorBrightnessMax);
    { std::ofstream file(path); file << "graphics_interior_brightness=-2\n"; }
    BbSettings::Load();
    assert(s.graphics_interior_brightness == 0.0f);
    { std::ofstream file(path); file << "graphics_interior_brightness=abc\n"; }
    s.graphics_interior_brightness = 1.0f;
    BbSettings::Load();
    assert(s.graphics_interior_brightness == 0.0f);
    { std::ofstream file(path); file << "graphics_interior_brightness=nan\n"; }
    s.graphics_interior_brightness = 1.0f; // not the default before this Load
    BbSettings::Load();
    assert(s.graphics_interior_brightness == BbSettings::InteriorBrightnessDefault);
    BbSettings::Save();
'''

T_IE_ON_OLD = r'''    const Config on = Parse("1", nullptr, nullptr, nullptr);
    const Config show = Parse("2", nullptr, nullptr, nullptr);
'''
T_IE_ON_NEW = r'''    // r99b's numbers (target 0.05, strength 0.5, at most 1.5 EV) as explicit values: the scenes below
    // were derived with them; r99c's defaults are tested in section h.
    const Config on = Parse("1", "0.05", "0.5", "1.5");
    const Config show = Parse("2", nullptr, nullptr, nullptr);
'''
T_IE_REPL = [
    ('        const Lift at = Want(on, Scene(DefaultTarget, all, 0));\n',
     '        const Lift at = Want(on, Scene(on.target, all, 0));\n'),
    ('        assert(mod.valid && mod.wanted_ev == DefaultMaxEv);\n',
     '        assert(mod.valid && mod.wanted_ev == on.max_ev);\n'),
    ('        assert(applied < 0.9f * DefaultMaxEv);\n', '        assert(applied < 0.9f * on.max_ev);\n'),
    ('        assert(applied > 0.9f * DefaultMaxEv);\n', '        assert(applied > 0.9f * on.max_ev);\n'),
]
T_IE_ANCHOR = '''    std::puts("interior-exposure-test: all checks passed");
'''
T_IE_BLOCK = r'''    // h. r99c: the defaults (on, target 0.02, strength 1, at most 0.75 EV), the setting
    //    graphics_interior_brightness (0..3 stops, 0 = off) and the environment, resolved per frame.
    {
        static_assert(DefaultTarget == 0.02f && DefaultStrength == 1.0f && DefaultMaxEv == 0.75f);
        const Env none = ParseEnv(nullptr, nullptr, nullptr, nullptr, nullptr);
        assert(!none.mode_set && !none.max_ev_set && none.config.mode == Off);
        // No variable: the setting decides, 0.75 is on at 0.75, 0 is off, 2 is on at 2.
        const Config d = Resolve(none, DefaultMaxEv);
        assert(d.mode == On && d.max_ev == DefaultMaxEv && d.target == DefaultTarget &&
               d.strength == DefaultStrength && d.open_m == DefaultOpenMeters);
        assert(Resolve(none, 0.0f).mode == Off && Resolve(none, -1.0f).mode == Off);
        assert(Resolve(none, 2.0f).mode == On && Resolve(none, 2.0f).max_ev == 2.0f);
        assert(Resolve(none, 9.0f).max_ev == MaxEvLimit && Resolve(none, 0.25f).max_ev == 0.25f);
        assert(Resolve(none, std::nanf("")).mode == On && Resolve(none, std::nanf("")).max_ev == DefaultMaxEv);
        assert(Resolve(none, INFINITY).max_ev == DefaultMaxEv);
        // The variables win. An empty one is as unset.
        const Env empty = ParseEnv("", "", "", "", "");
        assert(!empty.mode_set && !empty.max_ev_set && Resolve(empty, 0.75f).mode == On &&
               Resolve(empty, 0.0f).mode == Off);
        const Env off = ParseEnv("0", nullptr, nullptr, nullptr, nullptr);
        assert(off.mode_set && Resolve(off, 0.75f).mode == Off);
        const Env junk = ParseEnv("x", nullptr, nullptr, nullptr, nullptr);
        assert(junk.mode_set && Resolve(junk, 0.75f).mode == Off);
        const Env force = ParseEnv("1", nullptr, nullptr, nullptr, nullptr);
        assert(Resolve(force, 0.0f).mode == On && Resolve(force, 0.0f).max_ev == DefaultMaxEv);
        assert(Resolve(force, 2.0f).mode == On && Resolve(force, 2.0f).max_ev == 2.0f);
        const Env sho = ParseEnv("2", nullptr, nullptr, nullptr, nullptr);
        const Config c_show = Resolve(sho, 0.75f);
        assert(c_show.mode == Show && c_show.max_ev == ShowMaxEv && c_show.target == ShowTarget &&
               Resolve(sho, 0.0f).mode == Show);
        const Env cap = ParseEnv(nullptr, nullptr, nullptr, "1.5", nullptr);
        assert(cap.max_ev_set && !cap.mode_set);
        assert(Resolve(cap, 0.75f).mode == On && Resolve(cap, 0.75f).max_ev == 1.5f);
        assert(Resolve(cap, 0.0f).mode == On && Resolve(cap, 0.0f).max_ev == 1.5f);
        const Env cap0 = ParseEnv(nullptr, nullptr, nullptr, "0", nullptr);
        assert(cap0.max_ev_set && Resolve(cap0, 0.75f).mode == Off);
        const Env cap_on = ParseEnv("1", nullptr, nullptr, "0", nullptr);
        assert(Resolve(cap_on, 0.75f).mode == On && Resolve(cap_on, 0.75f).max_ev == 0.0f);
        const Env cap_show = ParseEnv("2", nullptr, nullptr, "1", nullptr);
        assert(Resolve(cap_show, 0.0f).mode == Show && Resolve(cap_show, 0.0f).max_ev == 1.0f);
        const Env cap_high = ParseEnv(nullptr, nullptr, nullptr, "7", nullptr);
        assert(Resolve(cap_high, 0.5f).max_ev == MaxEvLimit);
        const Env cap_bad = ParseEnv(nullptr, nullptr, nullptr, "1.5x", nullptr); // unreadable: unset
        assert(!cap_bad.max_ev_set && Resolve(cap_bad, 0.5f).max_ev == 0.5f);
        const Env cap_nan = ParseEnv(nullptr, nullptr, nullptr, "nan", nullptr);
        assert(!cap_nan.max_ev_set && Resolve(cap_nan, 0.0f).mode == Off);
        const Env other = ParseEnv(nullptr, "0.05", "0.5", nullptr, "40");
        assert(Resolve(other, 0.75f).target == 0.05f && Resolve(other, 0.75f).strength == 0.5f &&
               Resolve(other, 0.75f).open_m == 40.0f && Resolve(other, 0.75f).max_ev == 0.75f);
        assert(Readable("1") && Readable("-0.5") && !Readable("") && !Readable(nullptr) &&
               !Readable("1x") && !Readable("nan") && !Readable("inf"));
        // Where the largest lift comes from.
        assert(std::strcmp(MaxSource(none, 0.75f), "graphics_interior_brightness") == 0);
        assert(std::strcmp(MaxSource(none, 0.0f), "the default") == 0);
        assert(std::strcmp(MaxSource(cap, 0.75f), "BB_INTERIOR_EXPOSURE_MAX_EV") == 0);
        assert(std::strcmp(MaxSource(sho, 0.75f), "the SHOW value") == 0);
        // The measured scenes at the defaults: the library without the mod +0.5, with it the full
        // 0.75, church-candles with the mod just under it, the dream house and church-candles
        // without the mod nothing worth seeing, open places nothing.
        const float lib = Want(d, Scene(0.014f, all, 0)).wanted_ev;
        assert(lib > 0.50f && lib < 0.53f && Near(lib, std::log2(0.02f / 0.014f), 1e-4f));
        assert(Want(d, Scene(0.01425f, all, 0)).wanted_ev > 0.48f && Want(d, Scene(0.01425f, all, 0)).wanted_ev < 0.50f);
        assert(Want(d, Scene(0.01098f, all, 0)).wanted_ev == DefaultMaxEv); // library, looking up
        assert(Want(d, Scene(0.0055f, all, 0)).wanted_ev == DefaultMaxEv);
        assert(Want(d, Scene(0.0011f, all, 0)).wanted_ev == DefaultMaxEv);
        const float church_mod = Want(d, Scene(0.01234f, all, 0)).wanted_ev;
        assert(church_mod > 0.69f && church_mod < 0.71f);
        assert(Want(d, Scene(0.0053f, all, 0)).wanted_ev == DefaultMaxEv);
        assert(Want(d, Scene(0.04016f, all, 0)).wanted_ev == 0.0f);
        assert(Want(d, Scene(0.018f, all, 0)).wanted_ev > 0.14f && Want(d, Scene(0.018f, all, 0)).wanted_ev < 0.16f);
        assert(Want(d, Scene(0.02f, all, 0)).wanted_ev < 1e-4f && Want(d, Scene(0.025f, all, 0)).wanted_ev == 0.0f);
        assert(Want(d, Scene(0.02982f, all, 0)).wanted_ev == 0.0f && Want(d, Scene(0.05192f, all, 0)).wanted_ev == 0.0f);
        assert(Want(d, Scene(0.02509f, all, 0)).wanted_ev == 0.0f); // the dark alley without the mod
        assert(Want(d, Scene(0.0097f, all, 0)).wanted_ev == DefaultMaxEv); // with the mod: a closed view lifts
        assert(Want(d, Scene(0.0097f, all, 0, 0.2f * all)).wanted_ev == 0.0f); // 20 % open: nothing
        assert(Want(d, Scene(0.01f, 0, all)).wanted_ev == 0.0f); // the graveyard at night: all sky
        // The setting scales the lift's cap only: at 0.25 the library asks 0.25, at 3 its full gap.
        assert(Want(Resolve(none, 0.25f), Scene(0.0011f, all, 0)).wanted_ev == 0.25f);
        assert(Near(Want(Resolve(none, 3.0f), Scene(0.0055f, all, 0)).wanted_ev, std::log2(0.02f / 0.0055f), 1e-4f));
    }
'''

# ------------------------------------------------------------------ README
OLD_README = r'''### Interior exposure (in development)

Part of the lamp work: a brighten-only exposure lift, so rooms lit only by lamps (tested with `graphics_disable_player_light=1`) read dim but legible instead of black, while views with 15% or more samples at depth 1 or at the open distance (80 m) or farther get none. Measured with the hero light off (2026-11-15; log-average before the tone curve, no measured view had any sample at depth 1): the library 0.014 (0.0055 with the BB PC Remaster mod) gets about +0.9 EV (+1.5 EV, the cap, with the mod), church-candles 0.040 (0.012 with the mod) about +0.16 EV (+1.0 EV), the Hunter's Dream house 0.052 nothing (0.030 with the mod: about +0.37 EV), so rooms keep their order of brightness. Outdoors depends on the open share alone: a dark street with fewer open samples is lifted like a room (the dark alley, 0.025, would get about +0.5 EV; 0.0097 with the mod, about +1.2 EV); how many open samples real streets show is not measured yet, the log line measures it. Off unless `BB_INTERIOR_EXPOSURE` is `1` or `2`. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing; no ini key yet. `BB_INTERIOR_EXPOSURE_TARGET=0.02 BB_INTERIOR_EXPOSURE_STRENGTH=1 BB_INTERIOR_EXPOSURE_OPEN_M=0` gives the first version's rule (r99), with the open share eased.

| Variable | What it does | Default |
|---|---|---|
| `BB_INTERIOR_EXPOSURE` | `1` turns it on, `2` is the test setting with the exaggerated values in brackets below. At each frame the upscaler takes as an HDR scene (DLSS, FSR, XeSS or TAA before the game's post, as with `upscale_before_post=1`), one group of 256 threads takes 64x36 samples of the scene colour and depth: samples at depth 1 (sky) are counted apart, the others give the log-average L of their Rec.709 luminance before the tone curve (each clamped to 0.0001..64, values pushed to the meter) and are counted by view depth (from the camera's projection) at a quarter, half, one and two times the open distance. A reading the GPU has finished is read back (a 128-byte host buffer, 4 frames in a ring). The open share (samples at depth 1 or at the open distance or farther, of all samples) is eased in real time: 0.15 s time constant while it grows, 1.5 s while it shrinks, starting at 1; a reading metered without a usable camera (no open distance) leaves it as it is. The lift in stops is min(max, strength x log2(target / L)), never below 0, times 1 - smoothstep(0.03, 0.15, eased open share): no lift at or above the target, none while 15% or more of the eased view is open, so a dark view with few open samples starts to be lifted about 1.5 to 3 s after it comes (from 40% or 100% open) and is near the full lift about 3 s later, and a view with 15% or more open samples stops the lift within about a second. A reading with L below 0.0004 (a black or fading frame) keeps the lift as it is. The applied lift eases toward that in real time (1 s time constant while it grows, 0.4 s while it shrinks) and, as the factor 2^lift, multiplies the exposure of the GT7 or ACES tone map (`graphics_tonemapper`, times `graphics_gt7_exposure`); with the game's own curve or the HDR curve extension it changes nothing. With it on, the log has a line once and then every 2 s (1 s with `2`): `Interior exposure (r99b): applied ... EV (x...), wanted ... EV, metered L; open ...%, eased ...%, indoor ... (depth 1 ...%; at least 20/40/80/160 m: .../.../.../...%); GT7/ACES exposure a -> b`; no such line means no frame went through that upscaler path. Cost: one dispatch of one group, 2304 samples, an estimate of 0.01 to 0.03 ms at 1080p internal, not measured; read it on the `Lighting: interior exposure meter` row of `BB_GPU_PROFILE=1`. Off, nothing is made or dispatched and the factor is exactly 1 | off |
| `BB_INTERIOR_EXPOSURE_TARGET` | The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off: the library about 0.014, the dark alley about 0.025, church-candles about 0.040, the Hunter's Dream house about 0.052) | `0.05` (`0.15`) |
| `BB_INTERIOR_EXPOSURE_STRENGTH` | The share of the gap in stops the lift closes, 0 to 1 | `0.5` (`1`) |
| `BB_INTERIOR_EXPOSURE_MAX_EV` | The largest lift in stops, 0 to 3 | `1.5` (`3`) |
| `BB_INTERIOR_EXPOSURE_OPEN_M` | The open distance in metres of view depth, 0 to 1000; 0 counts only depth 1 as open | `80` (`80`) |

'''
NEW_README = r'''### Interior exposure (in development)

Part of the lamp work: a brighten-only exposure lift, so rooms lit only by lamps (tested with `graphics_disable_player_light=1`) read dim but legible instead of black. **On by default, with the largest lift 0.75 stops** (the owner's pick, 2026-11-16, after seeing the Hunter's Dream house, the sewer, the library and the church at off, +0.75 and +1). The largest lift is the setting `graphics_interior_brightness` (0 to 3 stops, default `0.75`, `0` = off). It has a slider in the in-game menu (**Insert**, section Interior brightness, steps of 0.25) and is read every frame, so a change acts at once. At `0`, with no `BB_INTERIOR_EXPOSURE` set, nothing is made, recorded or printed and the factor is exactly 1: the same cost as the feature off. It lifts only dark views (target 0.02, strength 1: a view metered at 0.02 or above gets nothing) and none that show 15% or more samples at depth 1 or at the open distance (80 m) or farther. Measured with the hero light off (2026-11-15; log-average before the tone curve; no measured view had any sample at depth 1), and what the defaults do with it: **without the BB PC Remaster mod the library meters about 0.014 and gets about +0.5 stops (log2(0.02 / 0.014)), so it is brightened a little even without the mod**; with the mod (0.0011 to 0.0055) it gets the full +0.75. Church-candles (0.040) gets nothing without the mod, with the mod (0.0053 to 0.012) +0.7 to +0.75. The Hunter's Dream house meters 0.018 to 0.025 (0.030 with the mod) and gets no lift worth seeing (at most +0.15 EV at the dark end of that range, 0 from 0.02 up). The graveyard and other open places get none (open samples; the graveyard at night showed 100% sky). A dark street whose view shows few open samples is lifted like a room (the dark alley, 0.025 without the mod, is above the target: nothing; with the mod, 0.0097: up to +0.75); how many open samples real streets show is not fully measured, the log line measures it. It acts through the GT7 or ACES tone map (`graphics_tonemapper`, times `graphics_gt7_exposure`); with the game's own curve or the HDR curve extension it changes nothing, and it needs a frame that goes through an upscaler path (DLSS, FSR, XeSS or TAA before the game's post). The environment variables are read once when the game starts, are for testing, and win over the setting: `BB_INTERIOR_EXPOSURE=0` forces it off, `1` on, `2` the SHOW test setting, and `BB_INTERIOR_EXPOSURE_MAX_EV` is the largest lift in place of the slider. A missing or unreadable number takes the default, then the range is applied. `BB_INTERIOR_EXPOSURE_OPEN_M=0 BB_INTERIOR_EXPOSURE_MAX_EV=1.5` gives the first version's rule (r99), with the open share eased.

| Variable | What it does | Default |
|---|---|---|
| `graphics_interior_brightness` | `lantern.ini` key and menu slider: the largest lift in stops, 0 to 3, read every frame; `0` is off (nothing is made). The menu's help text: lifts only dark interiors; outdoors and bright rooms stay as they are. `BB_INTERIOR_EXPOSURE_MAX_EV` wins over it when it is a number, and `BB_INTERIOR_EXPOSURE` when it is set and not empty. A value outside 0 to 3 is the nearest end, one that is not a finite number is `0.75`, text that is no number is 0 | `0.75` |
| `BB_INTERIOR_EXPOSURE` | Set and not empty, it decides: `0` off, `1` on (at the setting's lift, or at 0.75 when the setting is 0), `2` is the test setting with the exaggerated values in brackets below, any other text off; unset or empty: the setting decides. At each frame the upscaler takes as an HDR scene (DLSS, FSR, XeSS or TAA before the game's post, as with `upscale_before_post=1`), one group of 256 threads takes 64x36 samples of the scene colour and depth: samples at depth 1 (sky) are counted apart, the others give the log-average L of their Rec.709 luminance before the tone curve (each clamped to 0.0001..64, values pushed to the meter) and are counted by view depth (from the camera's projection) at a quarter, half, one and two times the open distance. A reading the GPU has finished is read back (a 128-byte host buffer, 4 frames in a ring). The open share (samples at depth 1 or at the open distance or farther, of all samples) is eased in real time: 0.15 s time constant while it grows, 1.5 s while it shrinks, starting at 1; a reading metered without a usable camera (no open distance) leaves it as it is. The lift in stops is min(max, strength x log2(target / L)), never below 0, times 1 - smoothstep(0.03, 0.15, eased open share): no lift at or above the target, none while 15% or more of the eased view is open, so a dark view with few open samples starts to be lifted about 1.5 to 3 s after it comes (from 40% or 100% open) and is near the full lift about 3 s later, and a view with 15% or more open samples stops the lift within about a second. A reading with L below 0.0004 (a black or fading frame) keeps the lift as it is. The applied lift eases toward that in real time (1 s time constant while it grows, 0.4 s while it shrinks) and, as the factor 2^lift, multiplies the exposure of the GT7 or ACES tone map. With it on, the log has a line once, `Interior exposure (r99c, on by ...)`, with the largest lift and where it came from (the setting, the environment or the default), then every 2 s (1 s with `2`) `Interior exposure (r99b): applied ... EV (x...), wanted ... EV, metered L; open ...%, eased ...%, indoor ... (depth 1 ...%; at least 20/40/80/160 m: .../.../.../...%); GT7/ACES exposure a -> b`; no such line means no frame went through that upscaler path. After a change of the largest lift it says `Interior exposure (r99c): the largest lift is now ... EV (from ...)` (checked at the 2 s line), when the setting goes to 0 `Interior exposure (r99c): off ...` (the lift goes back to none at once and the factor to exactly 1) and when it comes back `... on again ...`. Cost: one dispatch of one group, 2304 samples, an estimate of 0.01 to 0.03 ms at 1080p internal, not measured; read it on the `Lighting: interior exposure meter` row of `BB_GPU_PROFILE=1`. Off (setting 0 and no variable), nothing is made or dispatched and the factor is exactly 1 | the setting (on) |
| `BB_INTERIOR_EXPOSURE_TARGET` | The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off: the library about 0.014, the dark alley about 0.025, church-candles about 0.040, the Hunter's Dream house about 0.018 to 0.052) | `0.02` (`0.15`) |
| `BB_INTERIOR_EXPOSURE_STRENGTH` | The share of the gap in stops the lift closes, 0 to 1 | `1` (`1`) |
| `BB_INTERIOR_EXPOSURE_MAX_EV` | The largest lift in stops, 0 to 3, in place of the setting when it is a number (an unreadable one is as unset); with `2` and no number, 3 | the setting, `0.75` (`3`) |
| `BB_INTERIOR_EXPOSURE_OPEN_M` | The open distance in metres of view depth, 0 to 1000; 0 counts only depth 1 as open | `80` (`80`) |

'''

INI_ANCHOR = '            ("graphics_point_fog_glow_size", "0.08"),\n'
INI_BLOCK = (
    "            // Graphics > Lighting: the interior brightness, the engine's default\n"
    "            // (BbSettings::InteriorBrightnessDefault); the in-game menu has its slider.\n"
    '            ("graphics_interior_brightness", "0.75"),\n')
LOOKS_ANCHOR = ('var performanceShared = SharedSettings.Parse(SharedSettings.ToCode(SharedSettings.Take('
                'performanceIni, new LauncherSettings())));\n')
LOOKS_BLOCK = (
    "// The interior brightness (r99c): a lantern.ini setting the engine reads every frame, default 0.75 stops\n"
    "// (BbSettings::InteriorBrightnessDefault; engine/tests/test_settings.cpp pins the same). It is in no\n"
    "// look: a look sets the picture's knobs, and this is an effect of its own that a look leaves as the\n"
    "// player set it.\n"
    'Require(IniFile.Defaults.Count(d => d.Key == "graphics_interior_brightness") == 1 &&\n'
    '        IniFile.Defaults.Single(d => d.Key == "graphics_interior_brightness").Value == "0.75",\n'
    '    "graphics_interior_brightness: not in the settings defaults once, at the engine\'s default");\n'
    'Require(!knobs.Contains("graphics_interior_brightness"), '
    '"graphics_interior_brightness: the interior brightness is part of a look");\n')

# ------------------------------------------------------------------ the edit list
EDITS = []  # (path, old, new, block): block is None for a replacement, else the inserted text


def REPL(path, old, new):
    EDITS.append((path, old, new, None))


def INS_AFTER(path, anchor, block):
    EDITS.append((path, anchor, anchor + block, block))


def INS_BEFORE(path, anchor, block):
    EDITS.append((path, anchor, block + anchor, block))


REPL(HDR, HDR_KNOBS_OLD, HDR_KNOBS_NEW)
REPL(HDR, HDR_MEAS_OLD, HDR_MEAS_NEW)
REPL(HDR, HDR_CONST_OLD, HDR_CONST_NEW)
REPL(HDR, HDR_KNOBS_FN_OLD, HDR_KNOBS_FN_NEW)
REPL(HDR, HDR_SCALE_OLD, HDR_SCALE_NEW)
REPL(VK_H, VKH_OLD, VKH_NEW)
REPL(VK_C, VKC_ASSERT_OLD, VKC_ASSERT_NEW)
REPL(VK_C, VKC_STATE_OLD, VKC_STATE_NEW)
REPL(VK_C, VKC_SAYON_SIG_OLD, VKC_SAYON_SIG_NEW)
REPL(VK_C, VKC_SAYON_1_OLD, VKC_SAYON_1_NEW)
REPL(VK_C, VKC_SAYON_2_OLD, VKC_SAYON_2_NEW)
REPL(VK_C, VKC_SAYON_3_OLD, VKC_SAYON_3_NEW)
REPL(VK_C, VKC_HEAD_OLD, VKC_HEAD_NEW)
REPL(VK_C, VKC_SAYCALL_OLD, VKC_SAYCALL_NEW)
REPL(VK_C, VKC_READY_OLD, VKC_READY_NEW)
REPL(VK_C, VKC_LINE_OLD, VKC_LINE_NEW)
INS_AFTER(SET_H, SETH_ANCHOR, SETH_CONST)
INS_BEFORE(SET_H, SETH_MEMBER_ANCHOR, SETH_MEMBER)
INS_BEFORE(SET_C, SETC_LOAD_ANCHOR, SETC_LOAD)
INS_BEFORE(SET_C, SETC_SAVE_ANCHOR, SETC_SAVE)
INS_AFTER(OVERLAY, OVERLAY_ANCHOR, OVERLAY_BLOCK)
for _table, _anchor in TABLES:
    INS_AFTER(I18N, _anchor, table_block(_table))
REPL(T_IE, T_IE_ON_OLD, T_IE_ON_NEW)
for _old, _new in T_IE_REPL:
    REPL(T_IE, _old, _new)
INS_BEFORE(T_IE, T_IE_ANCHOR, T_IE_BLOCK)
INS_BEFORE(T_SET, T_SET_ANCHOR, T_SET_BLOCK)
INS_AFTER(INI, INI_ANCHOR, INI_BLOCK)
INS_BEFORE(LOOKS, LOOKS_ANCHOR, LOOKS_BLOCK)
REPL(README, OLD_README, NEW_README)


# ------------------------------------------------------------------ machinery
def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_of(path):
    return [e for e in EDITS if e[0] == path]


def edit_state(text, e):
    """applied / clean / broken for one edit. A replacement is applied when its new text is found once
    and its old one not (unless the new text holds the old one); an insertion when its block is found
    once (whatever stands between it and the anchor), clean when the block is absent and the anchor
    found once."""
    path, old, new, block = e
    if block is not None:
        if text.count(block) == 1:
            return "applied"
        return "clean" if text.count(block) == 0 and text.count(old) == 1 else "broken"
    if text.count(new) == 1 and text.count(old) == (1 if old in new else 0):
        return "applied"
    return "clean" if text.count(new) == 0 and text.count(old) == 1 else "broken"


def state_of(path, text):
    states = [edit_state(text, e) for e in edits_of(path)]
    if all(s == "applied" for s in states):
        return "applied"
    if all(s == "clean" for s in states):
        return "clean"
    bad = [e[1][:60] for e, s in zip(edits_of(path), states) if s == "broken"]
    raise SystemExit("REFUSED: %s: %d of %d edits applied, %d clean; old or new text not found as expected "
                     "(is r99b applied? is the file changed by someone else?): %r"
                     % (path, states.count("applied"), len(states), states.count("clean"), bad))


def apply_text(path, text):
    for p, old, new, block in EDITS:
        if p != path:
            continue
        if text.count(old) != 1 or text.count(block if block is not None else new) != 0:
            raise SystemExit("REFUSED: %s: anchor found %d times: %r" % (path, text.count(old), old[:60]))
        text = text.replace(old, new, 1)
    return text


def revert_text(path, text):
    for p, old, new, block in reversed(EDITS):
        if p != path:
            continue
        what = block if block is not None else new
        if text.count(what) != 1:
            raise SystemExit("REFUSED: %s: new text found %d times: %r" % (path, text.count(what), what[:60]))
        text = text.replace(what, "" if block is not None else old, 1)
    return text


def table_span(text, name):
    start = text.index("constexpr Entry %s[] = {" % name)
    return text[start:text.index("\n};", start)]


def printf_args(call):
    """(specifier count, argument count) of one printf call's text between its parentheses: the
    adjacent literals first, then the arguments split at top-level commas (outside strings)."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(call):
        ch = call[i]
        if ch == '"':
            j = i + 1
            while call[j] != '"':
                j += 2 if call[j] == "\\" else 1
            cur += call[i:j + 1]
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', parts[0])).replace("%%", "")
    return len(re.findall(r"%[-+ #0-9.]*[a-zA-Z]", fmt)), len(parts) - 1


def text_checks(texts):
    # --- the header and the README agree
    header, readme = texts[HDR], texts[README]
    for const, row, value in (("DefaultTarget = 0.02f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.02` (`0.15`)"),
                              ("ShowTarget = 0.15f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.02` (`0.15`)"),
                              ("DefaultStrength = 1.0f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`1` (`1`)"),
                              ("ShowStrength = 1.0f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`1` (`1`)"),
                              ("DefaultMaxEv = 0.75f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "`0.75` (`3`)"),
                              ("DefaultMaxEv = 0.75f", "| `graphics_interior_brightness`", "`0.75`"),
                              ("ShowMaxEv = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "(`3`)"),
                              ("MaxEvLimit = 3.0f", "| `graphics_interior_brightness`", "0 to 3"),
                              ("MaxEvLimit = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "0 to 3"),
                              ("DefaultOpenMeters = 80.0f", "| `BB_INTERIOR_EXPOSURE_OPEN_M`", "`80` (`80`)")):
        lines = [l for l in readme.split("\n") if l.startswith(row)]
        if header.count(const) != 1 or len(lines) != 1 or value not in lines[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    if readme.count("### Interior exposure (in development)\n") != 1 or "Knobs()" in header:
        raise SystemExit("README or header check")
    if not all(ord(c) < 128 for c in NEW_README):
        raise SystemExit("README section must be ASCII")
    for t in ("log2(0.02 / 0.014)", "about +0.5 stops", "without the BB PC Remaster mod",
              "lifts only dark interiors; outdoors and bright rooms stay as they are"):
        if t not in readme:
            raise SystemExit("README check: %r missing" % t)
    # --- the settings: header constants, member, load, save, test, launcher default agree
    sh = texts[SET_H]
    if sh.count("InteriorBrightnessMin = 0.0f, InteriorBrightnessMax = 3.0f, InteriorBrightnessDefault = 0.75f;") != 1:
        raise SystemExit("settings check: constants")
    if texts[SET_C].count('"graphics_interior_brightness"') != 2:
        raise SystemExit("settings check: Load and Save (one each)")
    if texts[INI].count('("graphics_interior_brightness", "0.75"),') != 1 or \
            texts[LOOKS].count('"graphics_interior_brightness"') != 3:
        raise SystemExit("launcher check")
    # --- the C++ pieces: the printf counts of the lines this patch writes or changes
    cpp = texts[VK_C]
    for start in ('std::printf("Interior exposure (r99c, on by', 'std::printf("Interior exposure (r99c): off',
                  'std::printf("Interior exposure (r99c): on again', 'std::printf("Interior exposure (r99c): the largest'):
        at = cpp.find(start)
        if at < 0 or cpp.count(start) != 1:
            raise SystemExit("C++ check: %r not once" % start)
        # a call ends at the first ");" that closes it: count parentheses from the "(" after printf
        depth, i = 0, cpp.find("(", at)
        j = i
        while True:
            c = cpp[j]
            if c == '"':
                j += 1
                while cpp[j] != '"':
                    j += 2 if cpp[j] == "\\" else 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        specs, args = printf_args(cpp[i + 1:j])
        if specs != args:
            raise SystemExit("C++ check: printf %r has %d specifiers and %d arguments" % (start, specs, args))
    for t in ("Policy::Resolve(env, setting)", "g_state = &s;", "Rest(*g_state);", "s.pending.fill(false);",
              "Policy::applied_scale.store(1.0f, std::memory_order_relaxed);",
              "BbSettings::InteriorBrightnessDefault == Policy::DefaultMaxEv"):
        if cpp.count(t) != 1:
            raise SystemExit("C++ check: %r not once" % t)
    if "Policy::Knobs()" in cpp:
        raise SystemExit("C++ check: Knobs() is gone")
    # --- the translation tables and the overlay
    i18n = texts[I18N]
    glyphs = {int(x.strip()[2:], 16) for x in
              open(os.path.join(ROOT, GLYPHS), encoding="utf-8").read().split(",") if x.strip()}
    for name, _ in TABLES:
        span = table_span(i18n, name)
        for en, tr in ((EN_TITLE, TR[name][0]), (EN_HINT, TR[name][1])):
            line = '    {"%s", "%s"},\n' % (en, tr)
            if span.count(line) != 1 or span.count('{"%s"' % en) != 1:
                raise SystemExit("text check: %s: %r not found exactly once" % (name, en[:40]))
    zh = "".join(TR["kChinese"])
    missing = sorted({c for c in zh if ord(c) > 0x7e and ord(c) not in glyphs})
    if missing:
        raise SystemExit("text check: Chinese menu text has characters the menu font lacks: %s" % "".join(missing))
    joined = re.sub(r"\s+", " ", re.sub(r'"\s+"', "", texts[OVERLAY]))
    for text in (EN_HINT, RU_HINT):
        if joined.count('"%s"' % text) != 1:
            raise SystemExit("text check: overlay: %r not found once" % text[:40])
    if joined.count('Item("%s", "%s")' % (EN_TITLE, RU_TITLE)) != 1 or \
            joined.count('Section("%s", "%s")' % (EN_TITLE, RU_TITLE)) != 1:
        raise SystemExit("text check: overlay: the section and the row")
    if i18n.count('{"%s"' % EN_TITLE) != 8 or i18n.count('{"%s"' % EN_HINT) != 8:
        raise SystemExit("text check: not in all 8 tables")
    for env in ("BB_INTERIOR_EXPOSURE", "BB_INTERIOR_EXPOSURE_MAX_EV"):
        if texts[OVERLAY].count('EnvNote("%s");' % env) != 1:
            raise SystemExit("text check: overlay: EnvNote(%s) not once" % env)
    if "lifts only dark interiors; outdoors and bright rooms stay as they are" not in EN_HINT.lower():
        raise SystemExit("text check: the help text lost the owner's plain words")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R99C_ROOT)" % ROOT)
    paths = []
    for e in EDITS:
        if e[0] not in paths:
            paths.append(e[0])
    if "OpenRiseSeconds" not in load(HDR)[2] and "r99c_interior-default" not in load(HDR)[2]:
        raise SystemExit("REFUSED: r99b_interior-brightness is not applied in this tree (the interior exposure "
                         "header is r99's): apply r99b first (python -I -X utf8 r99b_interior-brightness.fixed.py "
                         "apply), then this script")
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
            print("not applied; would apply (%d files edited, %d edits; every old text found once; text "
                  "checks on the result pass)" % (len(plan), len(EDITS)))
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
                tmp = full + ".r99ctmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r99ctmp"
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
