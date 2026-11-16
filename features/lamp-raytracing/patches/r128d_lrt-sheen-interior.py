# r128d_lrt-sheen-interior: FEATURE patch (lane LRT, task LRT-T07 wet blood sheen). Goals: LRT-G065 (wet sheen from
# blood), LRT-G066/G067 (blood on the ground, graveyard test place), LRT-G014 (the owner wants to try each change by
# hand), LRT-G003/G004 (optimization stays a priority: the cost is said, the default stays off).
#
# What is wrong today: BB_BLOOD_SHEEN=1 alone picks NOTHING ("NOTHING can be picked: name a draw or use the albedo
# rule", the log says so). The sheen that was tested at the graveyard needs two more environment variables
# (BB_BLOOD_SHEEN_DRAW=c829ee58:dbb222eb and BB_BLOOD_SHEEN_RULE=albedo, found by the r100c/r100d probes), and there
# is no lantern.ini key. So the owner cannot switch the wet pool on by hand, and the "default" run shows nothing.
#
# What it does (OFF by default, nothing changes with the knob off):
#  - New lantern.ini key graphics_blood_sheen (bbport_settings.h/.cpp): 0..4, default 0 = off, read ONCE when the game
#    starts (the sheen's knobs are read once; no live change, no menu row in this patch). 0.01..0.25 count as 0.25 (as
#    BB_BLOOD_SHEEN's numbers do); above 4 is 4; text that is no number is 0; not finite is the default (0).
#  - BB_BLOOD_SHEEN set and not empty wins over the key (0 or text there is off, whatever the key says); unset or
#    empty, the key gives the strength (BloodSheenRules::ReadUsable, pure, unit tested).
#  - When NEITHER BB_BLOOD_SHEEN_DRAW NOR BB_BLOOD_SHEEN_RULE is set (not even empty), the pool's own G-buffer draw
#    c829ee58:dbb222eb and the albedo rule are used: the combination every graveyard test since b52 ran with. Either
#    variable set (even empty): exactly as before (so every existing job and probe reads the same).
#  - Log: once "Blood sheen (r128d): strength S from the setting graphics_blood_sheen | the environment ...; neither
#    ... is set: the pool's own draw ... are used | the draws and the rule are the ones the environment names", and
#    every 600 frames "Blood sheen (r128d): N of M frames had keyed draws; strength from ..., ...".
#
# Off costs nothing: with the key at 0 and BB_BLOOD_SHEEN unset, Knobs.strength is 0, BloodSheen::Wanted() is false,
# no BloodSheen object, pipeline, image or pass is made (as before); the one new cost is one relaxed atomic load of the
# setting the first time Wanted() runs.
# On, the cost is the existing sheen's, now reached with one switch. Estimate (not measured): 0.07 ms at 1080p
# internal for each keyed draw of a G-buffer pass (two passes over the scene around it), the graveyard has about 36
# a frame and the pass marks 32 (r100d log: 8064 draws in 224 frames, 896 over the cap): about 2 ms at 1080p, about
# 4x at 2160p, plus about 0.15 ms for the wet-ground and dimming passes; memory 16.6 MB at 1080p internal. THAT IS
# TOO MUCH TO BE A DEFAULT: the key stays 0 until the slot job's BB_GPU_PROFILE row "Lighting: blood sheen" says what
# it costs at 4K; if it is high the next step is a cheaper pick (the index count of the decal's own mesh in the key,
# or the albedo rule without a keyed draw: wet-ground pass only, about 0.15 ms).
#
# Files: renderer_vulkan/blood_sheen.h (Knobs fields, ReadUsable, IniStrength, Load), vk_blood_sheen.cpp (include,
# Wanted hands the setting over before the first Load, once line, 600-frame line, static_assert tie), bbport_settings.h
# /.cpp (constants, member, Load branch, Save line), tests test_blood_sheen.cpp and test_settings.cpp (both already in
# build.sh --test and CMake), README.md (the key's row, the three BB_BLOOD_SHEEN rows, the section text).
#
# Use: python -I -X utf8 r128d_lrt-sheen-interior.py check | apply | revert
# Root: R128D_ROOT, else <tree>. Line ends kept (CRLF). apply backs the originals up in r128d_backup next to
# this script. Each edit refuses unless its anchor / old text is found exactly once; revert puts each old text back.
import os, sys

ROOT = os.environ.get("R128D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r128d_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
SH = "engine/gpu/shim/"
BH = RV + "blood_sheen.h"
BC = RV + "vk_blood_sheen.cpp"
SS = SH + "bbport_settings.h"
SC = SH + "bbport_settings.cpp"
TB = "engine/tests/test_blood_sheen.cpp"
TS = "engine/tests/test_settings.cpp"
R = "README.md"

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new.
EDITS = {
SS: [
("ins", "inline constexpr float InteriorBrightnessMin = 0.0f, InteriorBrightnessMax = 3.0f, InteriorBrightnessDefault = 0.75f;\n",
 "",
 "// bbport (r128d_lrt-sheen-interior): the blood sheen's strength (lantern.ini key graphics_blood_sheen; 0 = off, the\n"
 "// default; read once at the game's start; a set and not empty BB_BLOOD_SHEEN wins). Tied to BloodSheenRules by\n"
 "// static_asserts in vk_blood_sheen.cpp.\n"
 "inline constexpr float BloodSheenMin = 0.0f, BloodSheenMax = 4.0f, BloodSheenDefault = 0.0f;\n"),
("ins", "    std::atomic<float> graphics_interior_brightness{InteriorBrightnessDefault}; // 0..3 stops; 0: off\n",
 "",
 "    // bbport (r128d_lrt-sheen-interior): read once, when BloodSheen::Wanted first runs; 0..4, 0 (the default): off\n"
 "    std::atomic<float> graphics_blood_sheen{BloodSheenDefault};\n"),
],
SC: [
("ins", "            Clamp(std::isfinite(f) ? f : InteriorBrightnessDefault, InteriorBrightnessMin, InteriorBrightnessMax);\n",
 "",
 "    } else if (key == \"graphics_blood_sheen\") { // bbport (r128d_lrt-sheen-interior)\n"
 "        v.graphics_blood_sheen = Clamp(std::isfinite(f) ? f : BloodSheenDefault, BloodSheenMin, BloodSheenMax);\n"),
("ins", "    put(\"graphics_interior_brightness\", fixed(v.graphics_interior_brightness, 2)); // bbport (r99c)\n",
 "",
 "    put(\"graphics_blood_sheen\", fixed(v.graphics_blood_sheen, 2)); // bbport (r128d_lrt-sheen-interior)\n"),
],
BH: [
("rep", "//                         ';', ',' or spaces. No default: unset, only the albedo rule can pick\n",
 "//                         ';', ',' or spaces. bbport (r128d_lrt-sheen-interior): when neither this nor\n"
 "//                         BB_BLOOD_SHEEN_RULE is set (not even empty) the default is \"c829ee58:dbb222eb\", the\n"
 "//                         graveyard pool's own ground draw (with the albedo rule); one of the two set: no default\n"),
("ins", "//                         and the test view\n",
 "",
 "//                         bbport (r128d_lrt-sheen-interior): unset or empty, the lantern.ini key graphics_blood_sheen\n"
 "//                         (0..4, 0: off, read once at the start) gives the strength; set and not empty this wins\n"
 "//                         (0 or text there is off, whatever the key says)\n"),
("ins", "    float darken = DefaultDarken; ///< BB_BLOOD_SHEEN_DARKEN, 0..1 (0: no dimming pass)\n",
 "",
 "    bool from_ini = false;     ///< bbport (r128d): the strength came from graphics_blood_sheen\n"
 "    bool default_pick = false; ///< bbport (r128d): the pool's own draw and the albedo rule are the defaults taken\n"),
("ins", "/// BB_BLOOD_SHEEN_DARKEN's text: a number into 0..1; unset, empty or other text: the default.\n",
 "// bbport (r128d_lrt-sheen-interior): the draw and the rule the pool was tested with (r100c/r100d probes, every\n"
 "// graveyard job since b52), taken when neither BB_BLOOD_SHEEN_DRAW nor BB_BLOOD_SHEEN_RULE is set.\n"
 "inline constexpr const char* DefaultDrawText = \"c829ee58:dbb222eb\";\n"
 "inline constexpr const char* DefaultRuleText = \"albedo\";\n"
 "\n"
 "/// bbport (r128d): the strength lantern.ini's graphics_blood_sheen gives (0: none), handed over once by the engine\n"
 "/// (BloodSheen::Wanted) before the first Load.\n"
 "inline float& IniStrength() {\n"
 "    static float strength = 0.0f;\n"
 "    return strength;\n"
 "}\n"
 "\n"
 "/// bbport (r128d): Read, plus the ini strength and the defaults. `sheen` set and not empty decides alone (0 or other\n"
 "/// text: off); else `ini` (finite and above 0, put into MinStrength..MaxStrength) gives the strength. `draw` and\n"
 "/// `rule` both nullptr (unset): the pool's draw and the albedo rule; one of them set, even empty: as Read.\n"
 "inline Knobs ReadUsable(const char* sheen, const char* draw, const char* rule, float ini) {\n"
 "    const bool env = sheen != nullptr && sheen[0] != '\\0';\n"
 "    const bool from_ini = !env && std::isfinite(ini) && ini > 0.0f;\n"
 "    const bool defaults = draw == nullptr && rule == nullptr;\n"
 "    Knobs k = Read(env ? sheen : nullptr, defaults ? DefaultDrawText : draw, defaults ? DefaultRuleText : rule);\n"
 "    if (from_ini) {\n"
 "        k.strength = std::clamp(ini, MinStrength, MaxStrength);\n"
 "    }\n"
 "    k.from_ini = from_ini;\n"
 "    k.default_pick = defaults && k.strength > 0.0f;\n"
 "    return k;\n"
 "}\n"
 "\n",
 ""),
("rep",
 "        Knobs k = Read(std::getenv(\"BB_BLOOD_SHEEN\"), std::getenv(\"BB_BLOOD_SHEEN_DRAW\"),\n"
 "                       std::getenv(\"BB_BLOOD_SHEEN_RULE\"));\n",
 "        Knobs k = ReadUsable(std::getenv(\"BB_BLOOD_SHEEN\"), std::getenv(\"BB_BLOOD_SHEEN_DRAW\"),\n"
 "                             std::getenv(\"BB_BLOOD_SHEEN_RULE\"), IniStrength()); // bbport (r128d)\n"),
],
BC: [
("ins", "#include \"bbport_toggles.h\"\n",
 "",
 "#include \"bbport_settings.h\" // bbport (r128d_lrt-sheen-interior)\n"),
("ins", "namespace R = BloodSheenRules;\n",
 "",
 "// bbport (r128d_lrt-sheen-interior): the setting's range is the sheen's strength range, its default is off.\n"
 "static_assert(BbSettings::BloodSheenMax == R::MaxStrength && BbSettings::BloodSheenMin == 0.0f &&\n"
 "              BbSettings::BloodSheenDefault == 0.0f);\n"),
("rep",
 "bool BloodSheen::Wanted() {\n    return R::Load().strength > 0.0f;\n}\n",
 "bool BloodSheen::Wanted() {\n"
 "    // bbport (r128d_lrt-sheen-interior): the setting graphics_blood_sheen is handed to the knobs once, before their\n"
 "    // first read (this is the first caller: the rasterizer's constructor; BbSettings::Load ran in bbgpu_init).\n"
 "    static const bool handed = [] {\n"
 "        R::IniStrength() = BbSettings::Get().graphics_blood_sheen.load(std::memory_order_relaxed);\n"
 "        return true;\n"
 "    }();\n"
 "    (void)handed;\n"
 "    return R::Load().strength > 0.0f;\n"
 "}\n"),
("ins",
 "                     \"(default %.2f, BB_BLOOD_SHEEN_PEAK, 0 = none)\\n\",\n"
 "                     double(R::FillSpec), double(R::PeakDefault));\n",
 "",
 "    // bbport (r128d_lrt-sheen-interior): where the strength and the picked draws come from, once.\n"
 "    BbReport::Printf(\"Blood sheen (r128d): strength %.2f from %s; %s\\n\", double(k.strength),\n"
 "                     k.from_ini ? \"the setting graphics_blood_sheen\" : \"the environment (BB_BLOOD_SHEEN)\",\n"
 "                     k.default_pick ? \"neither BB_BLOOD_SHEEN_DRAW nor BB_BLOOD_SHEEN_RULE is set: the pool's own \"\n"
 "                                      \"draw c829ee58:dbb222eb and the albedo rule are used\"\n"
 "                                    : \"the draws and the rule are the ones the environment names\");\n"),
("ins",
 "    BbReport::Printf(\"Blood sheen (r100k): %u of %u shows with the luminance ceiling %.2f (0: none)\\n\",\n"
 "                     stats.peak_shows, stats.shows, double(PeakCap()));\n",
 "",
 "    {   // bbport (r128d_lrt-sheen-interior): the counter that says the default pick draws\n"
 "        const auto& knobs = R::Load();\n"
 "        BbReport::Printf(\"Blood sheen (r128d): %u of %u frames had keyed draws; strength from %s, %s\\n\",\n"
 "                         stats.keyed_frames, stats.frames,\n"
 "                         knobs.from_ini ? \"the setting graphics_blood_sheen\" : \"BB_BLOOD_SHEEN\",\n"
 "                         knobs.default_pick ? \"default draw and rule\" : \"draw and rule from the environment\");\n"
 "    }\n"),
],
TB: [
("ins", "    std::puts(\"blood sheen: ok\");\n",
 "    // bbport (r128d_lrt-sheen-interior): ReadUsable, the ini strength and the default pick.\n"
 "    {\n"
 "        // neither draw nor rule set: the pool's draw and the albedo rule\n"
 "        const Knobs d = ReadUsable(\"1\", nullptr, nullptr, 0.0f);\n"
 "        assert(d.strength == 1.0f && d.key_count == 1 && d.keys[0].vs == 0xc829ee58ull &&\n"
 "               d.keys[0].ps == 0xdbb222ebull && d.keys[0].indices == 0 && d.keys_bad == 0);\n"
 "        assert(d.rule == Rule::Albedo && !d.rule_bad && d.default_pick && !d.from_ini && CanPick(d));\n"
 "        assert(Flags(d, 0) == (FlagKeyed | FlagRuleAlbedo));\n"
 "        // one of them set, even empty: exactly Read\n"
 "        const Knobs e = ReadUsable(\"1\", \"\", nullptr, 0.0f);\n"
 "        assert(e.key_count == 0 && e.rule == Rule::Draw && !e.default_pick && !CanPick(e));\n"
 "        const Knobs r = ReadUsable(\"1\", nullptr, \"draw\", 0.0f);\n"
 "        assert(r.key_count == 0 && r.rule == Rule::Draw && !r.default_pick);\n"
 "        const Knobs a = ReadUsable(\"1\", nullptr, \"albedo\", 0.0f);\n"
 "        assert(a.key_count == 0 && a.rule == Rule::Albedo && !a.default_pick);\n"
 "        const Knobs p = ReadUsable(\"1\", \"1:2\", nullptr, 0.0f);\n"
 "        assert(p.key_count == 1 && p.keys[0].vs == 1 && p.rule == Rule::Draw && !p.default_pick);\n"
 "        assert(ReadUsable(\"1\", \"\", \"\", 0.0f).key_count == 0 && !ReadUsable(\"1\", \"\", \"\", 0.0f).default_pick);\n"
 "        // the sheen's own text, the test view and off\n"
 "        assert(ReadUsable(\"show\", nullptr, nullptr, 0.0f).show && ReadUsable(\"show\", nullptr, nullptr, 0.0f).default_pick);\n"
 "        assert(ReadUsable(\"2.5\", nullptr, nullptr, 0.0f).strength == 2.5f);\n"
 "        for (const char* off : {static_cast<const char*>(nullptr), \"\", \"0\", \"-1\", \"yes\", \"nan\"}) {\n"
 "            const Knobs k = ReadUsable(off, nullptr, nullptr, 0.0f);\n"
 "            assert(k.strength == 0.0f && !k.default_pick && !k.from_ini); // nothing to pick for\n"
 "        }\n"
 "        // the ini strength: only when BB_BLOOD_SHEEN is unset or empty\n"
 "        const Knobs i = ReadUsable(nullptr, nullptr, nullptr, 2.0f);\n"
 "        assert(i.strength == 2.0f && i.from_ini && i.default_pick && i.key_count == 1 && !i.show);\n"
 "        assert(ReadUsable(\"\", nullptr, nullptr, 2.0f).from_ini && ReadUsable(\"\", nullptr, nullptr, 2.0f).strength == 2.0f);\n"
 "        assert(ReadUsable(nullptr, nullptr, nullptr, 0.1f).strength == MinStrength);\n"
 "        assert(ReadUsable(nullptr, nullptr, nullptr, 9.0f).strength == MaxStrength);\n"
 "        for (const float no : {0.0f, -1.0f, std::nanf(\"\"), INFINITY}) {\n"
 "            const Knobs k = ReadUsable(nullptr, nullptr, nullptr, no);\n"
 "            assert(k.strength == 0.0f && !k.from_ini && !k.default_pick);\n"
 "        }\n"
 "        // set and not empty: the environment wins, 0 and text turn it off whatever the key says\n"
 "        assert(ReadUsable(\"3\", nullptr, nullptr, 2.0f).strength == 3.0f && !ReadUsable(\"3\", nullptr, nullptr, 2.0f).from_ini);\n"
 "        assert(ReadUsable(\"0\", nullptr, nullptr, 2.0f).strength == 0.0f && !ReadUsable(\"0\", nullptr, nullptr, 2.0f).default_pick);\n"
 "        assert(ReadUsable(\"off\", nullptr, nullptr, 2.0f).strength == 0.0f);\n"
 "        assert(ReadUsable(\"show\", nullptr, nullptr, 2.0f).show && !ReadUsable(\"show\", nullptr, nullptr, 2.0f).from_ini);\n"
 "        // ini with a named draw: the draw is kept, no default taken\n"
 "        const Knobs n = ReadUsable(nullptr, \"1:2\", nullptr, 1.0f);\n"
 "        assert(n.from_ini && !n.default_pick && n.key_count == 1 && n.rule == Rule::Draw);\n"
 "        // Read itself is unchanged: nothing named, nothing picked\n"
 "        assert(!CanPick(Read(\"1\", nullptr, nullptr)));\n"
 "        assert(IniStrength() == 0.0f);\n"
 "    }\n"
 "\n",
 ""),
],
TS: [
("ins", "    s.graphics_interior_brightness = 1.0f; // not the default before this Load\n"
        "    BbSettings::Load();\n"
        "    assert(s.graphics_interior_brightness == BbSettings::InteriorBrightnessDefault);\n"
        "    BbSettings::Save();\n",
 "",
 "    // bbport (r128d_lrt-sheen-interior): graphics_blood_sheen. Nothing above sets it: the default 0 (off); written\n"
 "    // back; read; saved after a change; a value outside 0..4 is the nearest end; a text that is no number is 0;\n"
 "    // a value that is not finite is the default.\n"
 "    static_assert(BbSettings::BloodSheenMin == 0.0f && BbSettings::BloodSheenMax == 4.0f &&\n"
 "                  BbSettings::BloodSheenDefault == 0.0f);\n"
 "    assert(s.graphics_blood_sheen == BbSettings::BloodSheenDefault);\n"
 "    BbSettings::Save();\n"
 "    assert(Read(path).find(\"graphics_blood_sheen=0.00\\n\") != std::string::npos);\n"
 "    { std::ofstream file(path); file << \"graphics_blood_sheen=1.50\\n\"; }\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == 1.5f);\n"
 "    s.graphics_blood_sheen = 0.0f;\n"
 "    BbSettings::Save();\n"
 "    assert(Read(path).find(\"graphics_blood_sheen=0.00\\n\") != std::string::npos);\n"
 "    s.graphics_blood_sheen = 2.0f;\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == 0.0f);\n"
 "    { std::ofstream file(path); file << \"graphics_blood_sheen=9\\n\"; }\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == BbSettings::BloodSheenMax);\n"
 "    { std::ofstream file(path); file << \"graphics_blood_sheen=-2\\n\"; }\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == 0.0f);\n"
 "    { std::ofstream file(path); file << \"graphics_blood_sheen=abc\\n\"; }\n"
 "    s.graphics_blood_sheen = 1.0f;\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == 0.0f);\n"
 "    { std::ofstream file(path); file << \"graphics_blood_sheen=nan\\n\"; }\n"
 "    s.graphics_blood_sheen = 1.0f; // not the default before this Load\n"
 "    BbSettings::Load();\n"
 "    assert(s.graphics_blood_sheen == BbSettings::BloodSheenDefault);\n"
 "    BbSettings::Save();\n"),
],
}

ROW_KEY = ("| `graphics_blood_sheen` | `lantern.ini` key (r128d_lrt-sheen-interior): the strength of the blood sheen, 0 to 4, "
           "read once when the game starts (no live change; a menu row and its translations are not in this patch); `0` is "
           "off, the default, and nothing of it is made; a number from 0.01 to 0.25 counts as 0.25; above 4 counts as 4; "
           "text that is no number is 0. `BB_BLOOD_SHEEN` wins over it when it is set and not empty (`0` or other text "
           "there turns the sheen off, whatever the key says). With the sheen on and neither `BB_BLOOD_SHEEN_DRAW` nor "
           "`BB_BLOOD_SHEEN_RULE` set, the pool's own draw `c829ee58:dbb222eb` and the albedo rule are used (the combination "
           "every graveyard test ran with). Cost, an estimate (not measured): as for `BB_BLOOD_SHEEN`; the graveyard has "
           "about 36 keyed draws a frame (32 are marked), about 2 ms at 1080p internal and about four times that at 2160p, "
           "so the key stays off until the `Lighting: blood sheen` row of `BB_GPU_PROFILE=1` says what it costs. The log "
           "says once `Blood sheen (r128d): strength S from ...` and every 600 frames how many frames had keyed draws | `0` |")

README_REPS = [
 ("Nothing is picked unless one of the two is set (no draw is named by default).",
  "Nothing is picked unless one of the two is set, except that when NEITHER variable is set (not even empty) the pool's own "
  "draw `c829ee58:dbb222eb` and the albedo rule are used (r128d_lrt-sheen-interior); with one of them set, even empty, "
  "no draw is named by default."),
 ("(a planar reflection). These environment variables are read once when the game starts; they are for testing, no ini key yet.",
  "(a planar reflection). These environment variables are read once when the game starts; they are for testing; the `lantern.ini` key "
  "`graphics_blood_sheen` (r128d_lrt-sheen-interior) gives the strength when `BB_BLOOD_SHEEN` is unset or empty (read "
  "once too; no menu row yet)."),
 ("(as bright as the pixel, at least 0.1). Unset, empty, `0`, a negative number or other text: off, and nothing of it is made. Cost:",
  "(as bright as the pixel, at least 0.1). Unset or empty: the `lantern.ini` key `graphics_blood_sheen` decides (r128d; its "
  "default 0 is off, and nothing of it is made); `0`, a negative number or other text: off, and nothing of it is made (this "
  "wins over the key). Cost:"),
 ("give the pair and index count of a decal | none |",
  "give the pair and index count of a decal | `c829ee58:dbb222eb` when neither this nor `BB_BLOOD_SHEEN_RULE` is set "
  "(r128d), else none |"),
 ("Use `show` to see what else the rule would make wet | `draw` |",
  "Use `show` to see what else the rule would make wet | `albedo` when neither this nor `BB_BLOOD_SHEEN_DRAW` is set "
  "(r128d), else `draw` |"),
]


def readme_edits(text):
    lines = [l for l in text.split("\n") if l.startswith("| `BB_BLOOD_SHEEN_PAUSE` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_BLOOD_SHEEN_PAUSE row is there %d times, wanted 1" % len(lines))
    return [("rep", o, n) for o, n in README_REPS] + [("ins", lines[0] + "\n", "", ROW_KEY + "\n")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def texts_check(texts):
    b, c, s = texts[BH], texts[BC], texts[SS]
    for want, n in (("inline Knobs ReadUsable(", 1), ("ReadUsable(std::getenv(\"BB_BLOOD_SHEEN\")", 1),
                    ("DefaultDrawText = \"c829ee58:dbb222eb\"", 1), ("DefaultRuleText = \"albedo\"", 1),
                    ("inline float& IniStrength()", 1), ("bool from_ini = false;", 1), ("bool default_pick = false;", 1)):
        if b.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (BH, want, b.count(want), n))
    # ReadUsable sits after Read (it calls it) and before Load (which calls it)
    if not (0 <= b.find("inline Knobs Read(const char* sheen") < b.find("inline Knobs ReadUsable(") <
            b.find("inline const Knobs& Load()")):
        raise SystemExit("text check: Read, ReadUsable and Load are out of order in blood_sheen.h")
    # the Read function itself is untouched: still no default (its unit tests keep their meaning)
    if b.count("Knobs k = ReadStrength(sheen);\n    ReadKeys(k, draw);\n    ReadRule(k, rule);\n") != 1:
        raise SystemExit("text check: Read was changed")
    # the setting's constants tie to the sheen's strength range
    if s.count("BloodSheenMin = 0.0f, BloodSheenMax = 4.0f, BloodSheenDefault = 0.0f;") != 1:
        raise SystemExit("text check: the setting's range is not 0..4, default 0")
    if "MaxStrength = 4.0f" not in b:
        raise SystemExit("text check: MaxStrength is not 4")
    # the key's default is off: nothing runs with the key untouched
    if c.count("R::IniStrength() = BbSettings::Get().graphics_blood_sheen.load(std::memory_order_relaxed);") != 1:
        raise SystemExit("text check: Wanted does not hand the setting over")
    # Wanted hands over BEFORE Load
    w = c.find("bool BloodSheen::Wanted()")
    if not (0 <= w < c.find("R::IniStrength() =", w) < c.find("return R::Load().strength > 0.0f;", w)):
        raise SystemExit("text check: Wanted reads the knobs before it hands the setting over")
    # the key row exists once and the table rows of the three variables name r128d
    row = [l for l in texts[R].split("\n") if l.startswith("| `graphics_blood_sheen` |")]
    if len(row) != 1 or not row[0].endswith("| `0` |"):
        raise SystemExit("text check: README row of graphics_blood_sheen")
    if texts[R].count("r128d") < 7:
        raise SystemExit("text check: README mentions r128d too few times")


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R128D_ROOT)" % ROOT)
    plan = []
    for path in (SS, SC, BH, BC, TB, TS, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            texts_check({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts_check(applied_texts())
            print("not applied; would apply (%d files, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        texts_check(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r128dtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r128dtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted")


main()
