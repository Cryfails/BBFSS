# r130a_sheen-colour: lane LRT, task LRT-T07 wet blood sheen. Goals LRT-G065, LRT-G066/G067. Applies ON TOP of r129b
# (refuses a tree without it: anchor `#define BLOOD_SHEEN_FLAG_RIM_FULL 64u`; a tree that already has r130a reads as applied).
#
# Why: the moon's reflection on the pool comes back pink-red. The prime suspects (code and the b79 log, not yet proven in a
# picture): (1) r100i's tint multiplies the specular root by (0.85, 0.35, 0.30), so the film's red specular is about 5x the dry
# pool's and green and blue stay put; (2) SHOW's dimming (BB_BLOOD_SHEEN_DARKEN 0.5) multiplies a dark wet pixel by up to
# (0.85, 0.70, 0.70) AFTER the lighting and so reddens the highlight too. This patch adds live test knobs that separate the
# causes in one running game, and one fix value to compare (TINT=2, "clear film"). Default behaviour is b79's, bit for bit.
#
# Knobs (live through the live knobs file, test builds only; a build without that header keeps the defaults):
#   BB_BLOOD_SHEEN_TINT   1 or unset or other text: r100i (as b79); 0: no tint (the same root in all channels, f0 0.20 grey);
#                         2: clear film: specular grey ClearRoot 0.15 (f0 0.0225) by the wet weight, and the after-lighting
#                         dimming acts by the pixel's redness only (a light-coloured highlight keeps its colour).
#   BB_BLOOD_SHEEN_GLOSS  0..1, default 1: the share of the way the gloss goes to WET_GLOSS (0: the ground's own gloss).
#   BB_BLOOD_SHEEN_LEVEL  0..1, default 1: scales the normal levelling (0: the ground's own relief).
#   BB_BLOOD_SHEEN_DARKEN (r100e) is now live as well (same parser, same default 0.5).
#
# Files: host_shaders/blood_sheen_layout.h, host_shaders/blood_sheen.comp (EDIT and SHOW builds only; SNAPSHOT and MARK
# SPIR-V unchanged), renderer_vulkan/blood_sheen.h, vk_blood_sheen.cpp, engine/tests/test_blood_sheen.cpp, README.md.
# No new binding, image, buffer or pass; the push stays 8 words (EDIT reads the last word, never used in EDIT before, as two
# unorm16 shares: 0xFFFFFFFF = (1, 1)).
#
# Deviations from the draft (so that r129b's own check still passes on the result, and r129b still reads as applied):
#  - the levelling scale is the LAST factor of the `level` statement (`up_gate * scales.y`), not the first, so r100k's and
#    r129b's text check `const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *` still finds its text (x 1.0 is exact, so the default
#    output is identical);
#  - the 511 static_assert is a NEW line after r129b's `== 127u` line, which stays as it is;
#  - the new log calls are written `BbReport::Printf( // r130a` with the string on the next line: r129b's check counts the
#    lines that END with `BbReport::Printf(` (it wants exactly 5, each followed by an r129b prefix), and refuses a line holding
#    `BbReport::Printf("` without an r100/r128d prefix; neither sees them;
#  - r129b's edited lines (the `push.flags` line of Edit) are not edited: the tint flag and the scales are added AFTER it;
#  - the push word is the C++ field `darken` (the shader's `unused`), set with std::bit_cast.
# r100k's own old check (`m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws);` once, `show_due ... k.darken` line) no longer holds; r129b
# already said it supersedes r100k's check.
#
# Cost (an estimate, not measured): default: EDIT +1 unpack, 3 multiplies, 1 flag test per wet px; SHOW +1 flag test per wet
# px; CPU +4 atomic knob reads per frame; below 0.001 ms at 4K. TINT=2: SHOW +1 max and 1 divide per wet px, EDIT one fewer max.
# Off guarantee: graphics_blood_sheen=0 and BB_BLOOD_SHEEN unset: no BloodSheen object, no knob read, no pass, no log line.
#
# Log lines start "Blood sheen (r130a)".
# .fixed (short review): EDIT's scales take exactly 1.0 for a 0xFFFF half (GLSL's unpackUnorm divide may round 1 ulp low
# on a GPU), so unset GLOSS/LEVEL stay bit-exact. Revert an original-applied tree with the original first.
# Use: python -I -X utf8 r130a_sheen-colour.py check | apply | revert
# Root: R130A_ROOT, else <tree> (needs engine/gpu). Line ends kept (CRLF or LF; mixed refused). apply backs the originals
# up in r130a_backup next to this script. Each edit refuses unless its anchor / old text is found exactly once; a tree with some
# edits applied and some not is refused; text checks run on the result before anything is written; files are written through a
# temp file. revert puts back exactly what apply inserted or replaced. Revert order: this script, then r129b.
import os, sys

ROOT = os.environ.get("R130A_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r130a_backup")
TMP = ".r130atmp"
VC = "engine/gpu/shadps4/video_core/"
LAY = VC + "host_shaders/blood_sheen_layout.h"
COMP = VC + "host_shaders/blood_sheen.comp"
RV = VC + "renderer_vulkan/"
BH = RV + "blood_sheen.h"
BC = RV + "vk_blood_sheen.cpp"
TB = "engine/tests/test_blood_sheen.cpp"
R = "README.md"
CODE = (LAY, COMP, BH, BC, TB)

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new.
EDITS = {
LAY: [
("ins", "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n",
 "",
 r'''// r130a_sheen-colour: EDIT, a test knob (BB_BLOOD_SHEEN_TINT 0, live): the specular target is untinted (the root in all three
// channels, f0 0.20 grey): the probe of the red cast.
#define BLOOD_SHEEN_FLAG_TINT_OFF 128u
// r130a_sheen-colour: EDIT and SHOW, the fix value (BB_BLOOD_SHEEN_TINT 2): EDIT writes a clear film specular (CLEAR_ROOT,
// grey); SHOW weights the dimming by the pixel's redness.
#define BLOOD_SHEEN_FLAG_TINT_CLEAR 256u
'''),
("ins", "#define BLOOD_SHEEN_TINT_B 0.30\n",
 "",
 r'''// r130a_sheen-colour: the clear film's specular root (BB_BLOOD_SHEEN_TINT 2): f0 0.0225, grey, a liquid surface (about
// water's 0.02); it does not grow with the strength. The film's reflection keeps the light's colour; the red belongs to the
// body under it.
#define BLOOD_SHEEN_CLEAR_ROOT 0.15
'''),
],
COMP: [
("ins", "    const bool do_normal = (flags & BLOOD_SHEEN_FLAG_NORMAL) != 0u;\n",
 "",
 r'''    // r130a_sheen-colour: x gloss share, y level share (0xFFFFFFFF = 1, 1). EDIT never used `unused`; SHOW keeps its own meaning.
    // A half of 0xFFFF is set to exactly 1.0 (unpackUnorm's divide need not be exact on a GPU): the default stays bit-exact.
    const vec2 scales = mix(unpackUnorm2x16(unused), vec2(1.0), equal(uvec2(unused & 0xFFFFu, unused >> 16), uvec2(0xFFFFu)));
'''),
("rep",
 "            m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws); // r100h (r100j: rim weight): the film's value, the ground's may go down\n",
 "            m.r = mix(m.r, BLOOD_SHEEN_WET_GLOSS, ws * scales.x); // r100h (r100j: rim weight; r130a: gloss share): the film's value\n"),
("rep",
 r'''            const vec3 target = vec3(root) * vec3(BLOOD_SHEEN_TINT_R, BLOOD_SHEEN_TINT_G, BLOOD_SHEEN_TINT_B);
            s.r = max(s.r, mix(s.r, target.r, ws));
            s.gb = mix(s.gb, target.gb, ws);
''',
 r'''            // r130a_sheen-colour: TINT 2 (clear film): grey, may go down (the film replaces the ground); TINT 0: untinted target.
            if ((flags & BLOOD_SHEEN_FLAG_TINT_CLEAR) != 0u) {
                s.rgb = mix(s.rgb, vec3(BLOOD_SHEEN_CLEAR_ROOT), ws);
            } else {
                const vec3 tint = (flags & BLOOD_SHEEN_FLAG_TINT_OFF) != 0u
                    ? vec3(1.0) : vec3(BLOOD_SHEEN_TINT_R, BLOOD_SHEEN_TINT_G, BLOOD_SHEEN_TINT_B);
                const vec3 target = vec3(root) * tint;
                s.r = max(s.r, mix(s.r, target.r, ws));
                s.gb = mix(s.gb, target.gb, ws);
            }
'''),
("rep",
 "                                        up_gate;\n",
 "                                        up_gate * scales.y; // r130a_sheen-colour: the level share (x 1.0 is exact)\n"),
("rep",
 "                const vec3 mult = mix(vec3(1.0), vec3(BLOOD_SHEEN_DARKEN_RED, BLOOD_SHEEN_DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim);\n",
 r'''                // r130a_sheen-colour: TINT 2: the dimming acts by the pixel's redness (a light-coloured highlight keeps its colour)
                const float red_share = clamp((c.r - max(c.g, c.b)) / max(c.r, 1e-6), 0.0, 1.0);
                const float dim_k = (flags & BLOOD_SHEEN_FLAG_TINT_CLEAR) != 0u ? dim * red_share : dim;
                const vec3 mult = mix(vec3(1.0),
                                      vec3(BLOOD_SHEEN_DARKEN_RED, BLOOD_SHEEN_DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim_k);
'''),
],
BH: [
("ins", "//                         by their specular weight (fill squared times the rim share)\n",
 "",
 r'''//   BB_BLOOD_SHEEN_TINT   bbport (r130a): a live test knob (live knobs header only; else 1): 1, unset or other text: the
//                         r100i red specular tint; 0: no tint (the same root in all channels, f0 0.20 grey); 2: clear film
//                         (grey f0 0.0225, and the after-lighting dimming acts by the pixel's redness only)
//   BB_BLOOD_SHEEN_GLOSS  bbport (r130a): a live test knob, 0..1, default 1: the share of the way the gloss goes to the
//                         film's (0: the ground's own gloss)
//   BB_BLOOD_SHEEN_LEVEL  bbport (r130a): a live test knob, 0..1, default 1: scales the normal levelling (0: the ground's
//                         own relief)
//   BB_BLOOD_SHEEN_DARKEN is live as well (r130a, live knobs header only)
'''),
("ins", "inline constexpr std::uint32_t FlagRimFull = BLOOD_SHEEN_FLAG_RIM_FULL;     ///< r129b EDIT: rim pixels level by the fill weight\n",
 "",
 r'''inline constexpr std::uint32_t FlagTintOff = BLOOD_SHEEN_FLAG_TINT_OFF;       ///< r130a EDIT: the specular target is untinted
inline constexpr std::uint32_t FlagTintClear = BLOOD_SHEEN_FLAG_TINT_CLEAR;   ///< r130a EDIT: clear film; SHOW: dim by redness
'''),
("ins", "static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull) == 127u);\n",
 "",
 r'''static_assert((FlagShow | FlagSlot | FlagKeyed | FlagRuleAlbedo | FlagClear | FlagNormal | FlagRimFull | FlagTintOff |
               FlagTintClear) == 511u);
'''),
("ins", "static_assert(BLOOD_SHEEN_TINT_R == 0.85 && BLOOD_SHEEN_TINT_G == 0.35 && BLOOD_SHEEN_TINT_B == 0.30);\n",
 "",
 r'''// bbport (r130a_sheen-colour): the clear film's specular root (grey, f0 0.0225).
inline constexpr float ClearRoot = float(BLOOD_SHEEN_CLEAR_ROOT);
static_assert(BLOOD_SHEEN_CLEAR_ROOT == 0.15);
'''),
("rep",
 "inline SpecRoot WetSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f) {\n",
 "inline SpecRoot WetSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f,\n"
 "                        bool tint_off = false) { // r130a: tint_off = BB_BLOOD_SHEEN_TINT 0 (FlagTintOff)\n"),
("rep",
 "    const float tr = root * TintR, tg = root * TintG, tb = root * TintB;\n",
 "    const float tr = root * (tint_off ? 1.0f : TintR), tg = root * (tint_off ? 1.0f : TintG),\n"
 "                tb = root * (tint_off ? 1.0f : TintB);\n"),
("ins", "/// bbport (r100j_sheen-clean-rim): the share of the body's specular tint and gloss a made-wet pixel gets (the\n",
 r'''/// bbport (r130a_sheen-colour): BB_BLOOD_SHEEN_TINT's text: 0, 1 or 2 (spaces around it allowed); unset, empty or other text: 1.
inline int ReadTint(const char* text) {
    if (text == nullptr) {
        return 1;
    }
    while (*text == ' ') {
        ++text;
    }
    if (text[0] < '0' || text[0] > '2') {
        return 1;
    }
    const char* end = text + 1;
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? text[0] - '0' : 1;
}
/// bbport (r130a_sheen-colour): BB_BLOOD_SHEEN_GLOSS and BB_BLOOD_SHEEN_LEVEL's text: a number into 0..1; unset, empty or other
/// text: 1 (as ReadDarken, with the default 1).
inline float ReadShare(const char* text) {
    if (text == nullptr || text[0] == '\0') {
        return 1.0f;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return 1.0f;
    }
    while (*end == ' ') {
        ++end;
    }
    return *end == '\0' ? std::clamp(value, 0.0f, 1.0f) : 1.0f;
}
/// bbport (r130a_sheen-colour): the EDIT push word: the gloss share in the low 16 bits, the level share in the high 16, each
/// a unorm16 (GLSL unpackUnorm2x16: x low half); (1, 1) is 0xFFFFFFFF, which unpacks to exactly (1.0, 1.0).
inline std::uint32_t PackScales(float gloss, float level) {
    const auto unorm = [](float v) {
        return static_cast<std::uint32_t>(std::lround(std::clamp(v, 0.0f, 1.0f) * 65535.0f));
    };
    return unorm(gloss) | (unorm(level) << 16);
}
/// bbport (r130a_sheen-colour): a wet pixel's specular after the clear film (the shader's arithmetic): every channel moves to
/// ClearRoot by the wet weight (strength, at most 1, times `weight`); it may go down.
inline SpecRoot ClearSpec(float ground_r, float ground_g, float ground_b, float strength, float weight = 1.0f) {
    const float w = std::clamp(strength, 0.0f, 1.0f) * std::clamp(weight, 0.0f, 1.0f);
    return {ground_r + (ClearRoot - ground_r) * w, ground_g + (ClearRoot - ground_g) * w,
            ground_b + (ClearRoot - ground_b) * w};
}
/// bbport (r130a_sheen-colour): the redness of a lit pixel (the SHOW shader's red_share): 0 for a light-coloured highlight
/// (blue or green at least red), up to 1 for pure red.
inline float RedShare(float r, float g, float b) {
    return std::clamp((r - std::max(g, b)) / std::max(r, 1e-6f), 0.0f, 1.0f);
}
''',
 ""),
],
BC: [
("ins", "/// BB_BLOOD_SHEEN_PEAK (r100k_sheen-no-hot-spot): the lit scene's luminance ceiling for the picked pixels, 0: none.\n",
 r'''/// BB_BLOOD_SHEEN_TINT, _GLOSS, _LEVEL and _DARKEN (r130a_sheen-colour, live, test knobs): the film colour probes. Each is the
/// default (TINT 1, GLOSS 1, LEVEL 1, DARKEN the setting's) in a build without the live knobs header; each says its change in
/// the log. Their calls keep the string on the line after the call (r129b's text check wants it so).
int TintMode() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<int> knob{"BB_BLOOD_SHEEN_TINT", R::ReadTint};
    static int last = 1;
    const int now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): tint %s (BB_BLOOD_SHEEN_TINT %d)\n",
            now == 0 ? "off (untinted grey specular)" : (now == 2 ? "clear film (grey, dimming by redness)" : "r100i red"), now);
    }
    return now;
#else
    return 1;
#endif
}

float GlossShare() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_GLOSS", R::ReadShare};
    static float last = 1.0f;
    const float now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): gloss share %.2f (BB_BLOOD_SHEEN_GLOSS)\n", double(now));
    }
    return now;
#else
    return 1.0f;
#endif
}

float LevelShare() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_LEVEL", R::ReadShare};
    static float last = 1.0f;
    const float now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): level share %.2f (BB_BLOOD_SHEEN_LEVEL)\n", double(now));
    }
    return now;
#else
    return 1.0f;
#endif
}

float DarkenNow(const R::Knobs& k) {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_DARKEN", R::ReadDarken};
    static float last = k.darken;
    const float now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): dimming %.2f (BB_BLOOD_SHEEN_DARKEN, live)\n", double(now));
    }
    return now;
#else
    return k.darken;
#endif
}

''',
 ""),
("ins", r'''        "not the fill weight (BB_BLOOD_SHEEN_RIM_FULL=1, a test knob: as r100h-r100k)\n");
''',
 "",
 r'''    // bbport (r130a_sheen-colour): the film colour knobs, once.
    BbReport::Printf( // r130a
        "Blood sheen (r130a): film colour knobs (live, test): BB_BLOOD_SHEEN_TINT 1 = r100i red specular, 0 = untinted f0 0.20 "
        "grey, 2 = clear film (grey f0 0.0225, after-lighting dimming by redness only); BB_BLOOD_SHEEN_GLOSS and "
        "BB_BLOOD_SHEEN_LEVEL shares (1 = as r129b); BB_BLOOD_SHEEN_DARKEN now live\n");
'''),
("ins",
 "    push.flags = R::Flags(k, step.slot) | (normal_ok ? R::FlagNormal : 0u) | (RimFull() ? R::FlagRimFull : 0u); // r129b\n",
 "",
 r'''    {   // bbport (r130a_sheen-colour): the tint probe flags and the gloss and level shares (the shader's `unused` word)
        const int tint = TintMode();
        push.flags |= (tint == 0 ? R::FlagTintOff : 0u) | (tint == 2 ? R::FlagTintClear : 0u);
        push.darken = std::bit_cast<float>(R::PackScales(GlossShare(), LevelShare()));
    }
'''),
("rep",
 "    show_due = k.show || k.darken > 0.0f || PeakCap() > 0.0f; // the test view, the dimming or the ceiling (r100k)\n",
 "    show_due = k.show || DarkenNow(k) > 0.0f || PeakCap() > 0.0f; // the test view, the dimming or the ceiling (r100k, r130a)\n"),
("rep",
 r'''    push.flags = k.show ? R::FlagShow : 0u; // r100e: not the test view: the dimming (push.darken)
    push.darken = k.show ? 0.0f : k.darken * std::min(k.strength, 1.0f);
''',
 r'''    push.flags = k.show ? R::FlagShow : 0u; // r100e: not the test view: the dimming (push.darken)
    if (!k.show && TintMode() == 2) {
        push.flags |= R::FlagTintClear; // r130a: the dimming acts by the pixel's redness
    }
    push.darken = k.show ? 0.0f : DarkenNow(k) * std::min(k.strength, 1.0f); // r130a: live
'''),
("ins",
 r'''            words[2], RimFull() ? "the fill weight (BB_BLOOD_SHEEN_RIM_FULL)" : "their specular weight");
    }
''',
 "",
 r'''    {   // bbport (r130a_sheen-colour): the film colour knobs now
        const int tint = TintMode();
        BbReport::Printf( // r130a
            "Blood sheen (r130a): tint %d, gloss share %.2f, level share %.2f, dimming %.2f%s\n", tint,
            double(GlossShare()), double(LevelShare()), double(DarkenNow(R::Load())), tint == 2 ? ", by redness" : "");
    }
'''),
],
TB: [
("ins", '    std::puts("blood sheen: ok");\n',
 r'''    // bbport (r130a_sheen-colour): the film colour knobs: parsing, the packed shares, the clear film, the redness.
    {
        assert(ReadTint(nullptr) == 1 && ReadTint("") == 1 && ReadTint("1") == 1 && ReadTint("0") == 0 && ReadTint("2") == 2);
        assert(ReadTint("7") == 1 && ReadTint("x") == 1 && ReadTint(" 2 ") == 2 && ReadTint("20") == 1 && ReadTint("2x") == 1);
        assert(ReadShare(nullptr) == 1.0f && ReadShare("") == 1.0f && ReadShare("x") == 1.0f && ReadShare("0.5x") == 1.0f);
        assert(ReadShare("0") == 0.0f && ReadShare("0.25") == 0.25f && ReadShare(" 0.5 ") == 0.5f);
        assert(ReadShare("7") == 1.0f && ReadShare("-3") == 0.0f && ReadShare("nan") == 1.0f);
        assert(PackScales(1.0f, 1.0f) == 0xFFFFFFFFu && PackScales(0.0f, 1.0f) == 0xFFFF0000u);
        assert(PackScales(1.0f, 0.0f) == 0x0000FFFFu && PackScales(0.0f, 0.0f) == 0u && PackScales(9.0f, -1.0f) == 0x0000FFFFu);
        assert(FlagTintOff == 128u && FlagTintClear == 256u && Near(ClearRoot, 0.15, 1e-6));
        // the clear film: grey at weight 1 (strength 1), untouched at weight 0, and it may go down
        {
            const SpecRoot grey = ClearSpec(0.3f, 0.1f, 0.05f, 1.0f, 1.0f);
            assert(Near(grey.r, 0.15) && Near(grey.g, 0.15) && Near(grey.b, 0.15));
            const SpecRoot none = ClearSpec(0.3f, 0.1f, 0.05f, 1.0f, 0.0f);
            assert(none.r == 0.3f && none.g == 0.1f && none.b == 0.05f);
            assert(ClearSpec(0.6f, 0.6f, 0.6f, 1.0f).r < 0.6f);
        }
        // WetSpec: the default is r100i's; tint_off is grey (the same root in all channels)
        {
            const SpecRoot tinted = WetSpec(0.1f, 0.1f, 0.1f, 1.0f);
            assert(Near(tinted.r, 0.45 * 0.85) && Near(tinted.g, 0.45 * 0.35) && Near(tinted.b, 0.45 * 0.30));
            const SpecRoot same = WetSpec(0.1f, 0.1f, 0.1f, 1.0f, 1.0f, false);
            assert(same.r == tinted.r && same.g == tinted.g && same.b == tinted.b);
            const SpecRoot untinted = WetSpec(0.1f, 0.1f, 0.1f, 1.0f, 1.0f, true);
            assert(Near(untinted.r, 0.45) && Near(untinted.g, 0.45) && Near(untinted.b, 0.45));
        }
        // the redness: a moonlit highlight (blue at least red) has none, the red body most of it
        assert(RedShare(0.3f, 0.35f, 0.45f) == 0.0f && RedShare(0.5f, 0.5f, 0.5f) == 0.0f);
        assert(Near(RedShare(0.05f, 0.005f, 0.005f), 0.9) && RedShare(0.0f, 0.0f, 0.0f) == 0.0f && Near(RedShare(1.0f, 0.0f, 0.0f), 1.0));
    }

''',
 ""),
],
}

# the README: the new rows follow the RIM_FULL row (r129b's); the DARKEN row says it is live
ROW_RIM_TAIL = "pass | `0` |\n"
OLD_DARKEN_TAIL = ("`0`: that pass does not run. Unset or other text: the default. Cost: an estimate (not measured) of 0.05 ms "
                   "at 1080p internal")
NEW_DARKEN_TAIL = ("`0`: that pass does not run. Unset or other text: the default. Live in a test build (live knobs file, r130a_sheen-colour), "
                   "the log says each change. Cost: an estimate (not measured) of 0.05 ms at 1080p internal")
ROW_TINT = (
    "| `BB_BLOOD_SHEEN_TINT` | A test knob (r130a_sheen-colour; live, through the live knobs file of the test tools; a build without "
    "that header ignores it and it is 1 there). Why the moon's reflection on the pool is pink-red: `1` (or unset, or other text): "
    "the specular is tinted red as r100i did (f0 about 0.146, 0.025, 0.018); `0`: no tint (the same root in all channels, f0 0.20, "
    "grey): the probe; `2`: the clear film, a liquid's grey specular (f0 0.0225) so the reflection keeps the light's colour, and the "
    "after-lighting dimming acts only by the pixel's redness (the red body gets darker and redder, a blue-white highlight keeps "
    "its colour). The log says each change. Cost: one flag test in the wet-ground pass and in the dimming pass, one divide in the "
    "dimming pass with `2` (an estimate, not measured: below 0.002 ms at 4K) | `1` |")
ROW_GLOSS = (
    "| `BB_BLOOD_SHEEN_GLOSS` | A test knob (r130a_sheen-colour; live, test builds only). 0 to 1: the share of the way the wet pixels' "
    "gloss moves to the film's (`0`: the ground's own gloss, `1`: all the way, as before). Unset or other text: 1. The log says "
    "each change. Cost: one multiply in the wet-ground pass | `1` |")
ROW_LEVEL = (
    "| `BB_BLOOD_SHEEN_LEVEL` | A test knob (r130a_sheen-colour; live, test builds only). 0 to 1: scales how far the film levels the "
    "normal (`0`: the ground's own relief on the body and the rim, `1`: as before). Unset or other text: 1. The log says each "
    "change. Cost: one multiply in the wet-ground pass | `1` |")
README_EDITS = [
    ("rep", OLD_DARKEN_TAIL, NEW_DARKEN_TAIL),
    ("ins", "as cobbles do. It lets one running game take the rim with and without the change. The log says each change. Cost: one select in "
            "the wet-ground pass | `0` |\n", "", ROW_TINT + "\n" + ROW_GLOSS + "\n" + ROW_LEVEL + "\n"),
]
EDITS[R] = README_EDITS
ORDER = (LAY, COMP, BH, BC, TB, R)


def load(path):
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        raise SystemExit("REFUSED %s: missing" % path)
    raw = open(full, "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


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
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


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


def need(path, text, want, n=1):
    if text.count(want) != n:
        raise SystemExit("text check: %s holds %r %d times, wanted %d" % (path, want[:90], text.count(want), n))


def prereq(texts):
    # r129b must be in the tree this patch is laid on
    need(LAY, texts[LAY], "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n")
    need(BC, texts[BC], "bool RimFull() {")
    need(LAY, texts[LAY], "BLOOD_SHEEN_FLAG_TINT_OFF", 0)


def texts_check(texts):
    lay, comp, hdr, cpp, tst, rd = (texts[p] for p in (LAY, COMP, BH, BC, TB, R))
    need(LAY, lay, "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n")
    need(LAY, lay, "#define BLOOD_SHEEN_FLAG_TINT_OFF 128u\n")
    need(LAY, lay, "#define BLOOD_SHEEN_FLAG_TINT_CLEAR 256u\n")
    need(LAY, lay, "#define BLOOD_SHEEN_CLEAR_ROOT 0.15\n")
    need(LAY, lay, "#define BLOOD_SHEEN_TINT_R 0.85\n")
    # the shader: EDIT's scales, gloss, specular and levelling; SHOW's dimming
    need(COMP, comp, "const vec2 scales = mix(unpackUnorm2x16(unused), vec2(1.0), equal(uvec2(unused & 0xFFFFu, unused >> 16), uvec2(0xFFFFu)));")
    need(COMP, comp, "ws * scales.x);")
    need(COMP, comp, "s.rgb = mix(s.rgb, vec3(BLOOD_SHEEN_CLEAR_ROOT), ws);")
    need(COMP, comp, "s.gb = mix(s.gb, target.gb, ws);")
    need(COMP, comp, "const vec3 target = vec3(root) * tint;")
    need(COMP, comp, "up_gate * scales.y;")
    need(COMP, comp, "const float level = BLOOD_SHEEN_NORMAL_SMOOTH * w *")        # r100k's and r129b's text
    need(COMP, comp, "BLOOD_SHEEN_FLAG_RIM_FULL) != 0u ? 1.0 : wet * rim_k)")      # r129b's
    need(COMP, comp, "const float red_share = clamp((c.r - max(c.g, c.b)) / max(c.r, 1e-6), 0.0, 1.0);")
    need(COMP, comp, "DARKEN_OTHER, BLOOD_SHEEN_DARKEN_OTHER), dim_k);")
    need(COMP, comp, "barrier()", 2)
    # the header
    need(BH, hdr, "FlagTintClear) == 511u);")
    need(BH, hdr, "FlagRimFull) == 127u);")                                          # r129b's line is unchanged
    need(BH, hdr, "inline int ReadTint(const char* text)")
    need(BH, hdr, "inline float ReadShare(const char* text)")
    need(BH, hdr, "inline std::uint32_t PackScales(float gloss, float level)")
    need(BH, hdr, "inline SpecRoot ClearSpec(")
    need(BH, hdr, "inline float RedShare(float r, float g, float b)")
    need(BH, hdr, "bool tint_off = false) {")
    if not (0 <= hdr.find("struct SpecRoot") < hdr.find("inline SpecRoot ClearSpec(")):
        raise SystemExit("text check: ClearSpec before SpecRoot")
    # the engine
    need(BC, cpp, "(RimFull() ? R::FlagRimFull : 0u); // r129b\n")                  # r129b's line is unchanged
    need(BC, cpp, "push.darken = std::bit_cast<float>(R::PackScales(GlossShare(), LevelShare()));")
    need(BC, cpp, "show_due = k.show || DarkenNow(k) > 0.0f || PeakCap() > 0.0f;")
    need(BC, cpp, "push.darken = k.show ? 0.0f : DarkenNow(k) * std::min(k.strength, 1.0f);")
    need(BC, cpp, "push.flags |= R::FlagTintClear;")
    need(BC, cpp, "int TintMode() {")
    need(BC, cpp, "push.ratio = k.show ? 0.0f : PeakCap();")
    need(TB, tst, "bbport (r130a_sheen-colour): the film colour knobs")
    # log calls: r129b's rule (no `BbReport::Printf("` without an r100/r128d prefix; a call that ENDS the line with
    # `BbReport::Printf(` must be followed by an r129b prefix, exactly 5 of them) still holds, and mine are the 6 written
    # `BbReport::Printf( // r130a` followed by the r130a prefix
    lines = cpp.split("\n")
    mine = theirs = 0
    for i, line in enumerate(lines):
        if 'BbReport::Printf("' in line and "Blood sheen (r100" not in line and "Blood sheen (r128d)" not in line:
            raise SystemExit("text check: a log line r100k's check would refuse: %r" % line)
        if line.rstrip().endswith("BbReport::Printf("):
            if '"Blood sheen (r129b)' not in lines[i + 1]:
                raise SystemExit("text check: a split Printf without the r129b prefix: %r" % lines[i + 1])
            theirs += 1
        if "BbReport::Printf( // r130a" in line:
            if '"Blood sheen (r130a)' not in lines[i + 1]:
                raise SystemExit("text check: an r130a Printf without the r130a prefix: %r" % lines[i + 1])
            mine += 1
    if theirs != 5:
        raise SystemExit("text check: %d split r129b Printf calls, wanted 5 (r129b's own count)" % theirs)
    if mine != 6:
        raise SystemExit("text check: %d r130a Printf calls, wanted 6 (4 changes, once-line, 600 frames)" % mine)
    for key in ("TINT", "GLOSS", "LEVEL"):
        rows = [l for l in rd.split("\n") if l.startswith("| `BB_BLOOD_SHEEN_%s` |" % key)]
        if len(rows) != 1 or not rows[0].endswith("| `1` |"):
            raise SystemExit("text check: README row of BB_BLOOD_SHEEN_%s" % key)
    rows = [l for l in rd.split("\n") if l.startswith("| `BB_BLOOD_SHEEN_DARKEN` |")]
    if len(rows) != 1 or "r130a_sheen-colour" not in rows[0] or not rows[0].endswith("| `0.5` |"):
        raise SystemExit("text check: README row of BB_BLOOD_SHEEN_DARKEN")


def new_lines_check():
    # every new C++/GLSL line: no tab, ASCII, at most 150 columns (README lines are tables, exempt)
    for path in CODE:
        for e in EDITS[path]:
            for text in (e[1:] if e[0] == "ins" else e[2:]):
                for line in text.split("\n"):
                    if "\t" in line or any(ord(ch) > 127 for ch in line) or len(line) > 150:
                        raise SystemExit("new line check: %s: %r" % (path, line[:100]))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (no engine/gpu; set R130A_ROOT)" % ROOT)
    new_lines_check()
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur))
    lay_cur = plan[0][4]
    if "#define BLOOD_SHEEN_FLAG_RIM_FULL 64u\n" not in lay_cur:
        raise SystemExit("REFUSED: the tree has no r129b (no BLOOD_SHEEN_FLAG_RIM_FULL); apply r129b first")
    plan = [p + (state_of(p[4], p[1], p[0]),) for p in plan]
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state, nothing written: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if state == "clean":
        prereq({p[0]: p[4] for p in plan})

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
            print("already applied")
            return
        texts = applied_texts()
        texts_check(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(ROOT, path) + TMP, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            os.replace(full + TMP, full)
        print("applied")
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path in out:
        open(os.path.join(ROOT, path) + TMP, "wb").write(out[path])
    for path in out:
        full = os.path.join(ROOT, path)
        os.replace(full + TMP, full)
    print("reverted")


main()
