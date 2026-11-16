# r111d_prints-readable: FEATURE fix on top of r111_footprints, r111b_footprints-pickup and
# r111c_prints-visible (owner 2026-11-15: "footprints that react to wet surfaces making wet foot prints,
# muddy, or bloody"; build 30 (b30): the pickup and the position work, 5 blood and 5 wet prints were
# placed and the read-back found 1716 and 1145 print pixels, but nobody could see the prints). Still off
# unless BB_FOOTPRINTS is set (r111's knob), still costs nothing when off. Branch: visual/footprints.
#
# WHAT THE b30 PICTURES SAY (read before the changes)
#  - The framing hid the trail. The camera stands 3.07 m behind the hunter and walks with him; the walk of
#    b30 (2 x 1.5 s at half stick, 5 prints, 0.75 m apart) left the prints 0.75 to 3.75 m behind him, that
#    is between him and the camera, so the last three lay at the lower picture edge and the older two
#    behind or under the camera. At the view of b30 (feet at y 1000 of 1080) the ground behind his heels is
#    the last 80 pixels. The twin job (gb0, camera yaw 150 px off) could not be compared at all. So the new
#    jobs look at the trail from the SIDE (the camera turned a quarter turn around him after the walk) and
#    take the off twin in the SAME game (below), so both pictures show the same view.
#  - The pool the blood comes from has linear albedo 0.021 0.006 0.005; the stone outside it 0.117 0.091 0.070
#    (b30's ground band means). A print of 0.75 x 0.117 = 0.088 red kept the stone's red nearly as it was:
#    only the green and the blue fell, a hue change under a bluish night light and a luminance change of
#    0.25 of the stone's (modelled, not measured). r111d makes the print darker (0.6 times the stone's red,
#    0.03 to 0.085): 0.17 of the stone's luminance by the same model under the moon (0.3 0.4 0.8) and 0.27
#    under a lamp (1 0.6 0.3). Arithmetic on the numbers above, the game's lighting is not in it.
#  - The coat wore off after 3 full prints (blood: 3 full, then 0.7: 10 prints; wet: 1 full, then 0.8: 13
#    prints), and b30's last read said "1 prints at full strength left" and "coat blood 0.36": by the time a
#    picture was taken the older prints had faded or were off the picture. A trail that is read from a short
#    walk has to hold several prints at full strength.
#  - The sole was two ellipses (0.33 x 0.12 m after r111c's scale): a blob, not a boot.
#
# WHAT CHANGES (all inside the footprints files; nothing else is touched)
#  - The sole is a boot print: a heel block (0.08 m across), a narrow waist (0.044 m) and a ball (0.11 m
#    across), 0.28 m long in all (u -0.14 to 0.14 m), the outline soft over about 1 cm (FOOTPRINTS_EDGE 0.82,
#    was 0.7). r111c's scale of 1.25 is back to 1.0: the numbers themselves give 0.28 x 0.11 m now. The box
#    of a print (0.2 m half extent across) still holds it at any heading.
#  - Coats (CoatRule): a blood coat leaves 4 full prints, then each step keeps 0.75 (13 prints in all, the
#    last 9 fading: 0.75 0.56 0.42 0.32 0.24 0.18 0.13 0.10 0.075); a wet coat 3 full, then 0.75 (12 prints:
#    9 fading). New helper CoatPrints(kind) counts them (the test and the log line use it, so the number in
#    the log is the rule's own).
#  - Blood print look: the red is 0.6 times the stone's (0.03 to 0.085; was 0.75, 0.04 to 0.10), green
#    0.006, blue 0.005 unchanged, cover 95% unchanged, gloss 0.78 (was 0.72). Prints stay blood by the
#    albedo rule (red 0.01 to 0.12 and at least 2.5 times green and blue), so the pickup rule and the blood
#    sheen still read them as blood. A wet print darkens by up to 65% (was 60%); gloss 0.8 and specular
#    root 0.25 unchanged.
#  - A print lives LifeS = 30 s (was 20 s): a short walk is read over several seconds.
#  - BB_FOOTPRINTS_GAIN now accepts 0 to 4 (was 0.25 to 4); 0 draws no print at all (the feature stays
#    on: it senses, places and counts as before). With the test tools' live knobs (gpu/shim/
#    bbport_live_knobs.h, BB_LIVE_KNOBS_FILE, present only in the test build; a feature branch without that
#    header reads the variable once as before) the game asks again every pass, so ONE running game can
#    show a view with the prints (1) and the same view without them (0): the job action
#    set:BB_FOOTPRINTS_GAIN=0 (the knob-off twin that b30 could not give). The gain is read through
#    R::Gain() where the push constants are made and in the 600-frame line; its once-line (r111d) is told
#    at the first pass and at each change.
#
# Off (BB_FOOTPRINTS unset or 0): nothing of r111d runs. Footprints is not made (Wanted() is false), the
# new Gain() is called from Footprints::Edit and OnFrameEnd only, and the live knob object is a static
# local of that function, made constant-initialised (no work at start). The shader build footprints_comp
# changes (nothing else includes footprints_layout.h or is compiled from it); no other shader build and no
# other C++ unit changes except by the footprints headers (footprints.h is included by vk_footprints.*
# and tests only). GPU cost: the shader does one more ellipse test (the waist) per print per pixel in the
# prints' boxes, a handful of ALU ops: not measurable against r111's estimate (0.02 to 0.08 ms at 1080p for
# a G-buffer pass with a print or the hunter on screen). Memory: none (no buffer, no image).
#
# Files edited (r111/r111b/r111c's own text; each old text found exactly once): renderer_vulkan/footprints.h,
# vk_footprints.h, vk_footprints.cpp, host_shaders/footprints.comp, footprints_layout.h,
# engine/tests/test_footprints.cpp, README.md. New files: none.
#
# Order: needs r111, r111b and r111c applied (refused otherwise: the old texts are theirs). To take r111c
# out again, revert r111d first (r111c's check and revert refuse files that r111d changed).
# Use: python -I -X utf8 r111d_prints-readable.py check | apply | revert
# Root: R111D_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111d_backup next to this script; revert puts each old text back (each new text found by itself, exactly
# once).
import os, re, sys

ROOT = os.environ.get("R111D_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111d_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
RULES = RV + "footprints.h"
VKH = RV + "vk_footprints.h"
VKC = RV + "vk_footprints.cpp"
COMP = HS + "footprints.comp"
LAYOUT = HS + "footprints_layout.h"
TEST = "engine/tests/test_footprints.cpp"
README = "README.md"
ORDER = [RULES, VKH, VKC, COMP, LAYOUT, TEST, README]

# (path, old, new): `old` found exactly once; `new` replaces it. Applied when `new` is found exactly once.
EDITS = {
    LAYOUT: [
        # the boot's sole
        (r'''#define FOOTPRINTS_HEEL_U -0.09
#define FOOTPRINTS_HEEL_RU 0.048
#define FOOTPRINTS_HEEL_RV 0.038
#define FOOTPRINTS_EDGE 0.7
// (r111c) The sole is drawn this many times larger than the numbers above (0.33 x 0.12 m in all): at 1080p
// a print 3 to 4 m from the camera is then 33 to 44 px wide.
#define FOOTPRINTS_SOLE_SCALE 1.25
''',
         r'''#define FOOTPRINTS_HEEL_U -0.095
#define FOOTPRINTS_HEEL_RU 0.045
#define FOOTPRINTS_HEEL_RV 0.04
// (r111d) A boot's sole: the heel block (u -0.14 to -0.05, 0.08 m across), the narrow waist (an ellipse
// at u WAIST_U with half axes WAIST_RU x WAIST_RV, 0.044 m across, bridging the gap between the heel and
// the ball) and the ball (u -0.03 to 0.14, 0.11 m across) make a print 0.28 m long and 0.11 m across at its
// widest (r111c's two ellipses drawn 1.25 times larger were a blob). Edges are soft only from EDGE of the
// radius out: 0.82 (was 0.7), about 1 cm.
#define FOOTPRINTS_WAIST_U -0.04
#define FOOTPRINTS_WAIST_RU 0.045
#define FOOTPRINTS_WAIST_RV 0.022
#define FOOTPRINTS_EDGE 0.82
// (r111d) The sole above is drawn at this scale: 1 (r111c drew r111's numbers 1.25 times larger; the
// numbers themselves now give the 0.28 x 0.11 m sole).
#define FOOTPRINTS_SOLE_SCALE 1.0
'''),
        (r'''#define FOOTPRINTS_FORE_U 0.05
#define FOOTPRINTS_FORE_RU 0.075
#define FOOTPRINTS_FORE_RV 0.048
''',
         r'''#define FOOTPRINTS_FORE_U 0.055
#define FOOTPRINTS_FORE_RU 0.085
#define FOOTPRINTS_FORE_RV 0.055
'''),
        # wet
        (r'''#define FOOTPRINTS_WET_DARKEN 0.6
''',
         r'''// (r111d: darken 0.65, was 0.6)
#define FOOTPRINTS_WET_DARKEN 0.65
'''),
        # blood
        (r'''#define FOOTPRINTS_BLOOD_ALBEDO_R 0.07
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005
#define FOOTPRINTS_BLOOD_RED_KEEP 0.75
#define FOOTPRINTS_BLOOD_RED_MIN 0.04
#define FOOTPRINTS_BLOOD_RED_MAX 0.10
#define FOOTPRINTS_BLOOD_COVER 0.95
#define FOOTPRINTS_BLOOD_GLOSS 0.72
''',
         r'''// (r111d: darker: red 0.6 times the stone's, 0.03 to 0.085, was 0.75 times, 0.04 to 0.10; ALBEDO_R is the
// typical print red, the stone's 0.1 x 0.6; gloss 0.78, was 0.72. Every red of the range is blood by the
// blood rule: at least 0.01, at most 0.12, at least 2.5 times the green and the blue.)
#define FOOTPRINTS_BLOOD_ALBEDO_R 0.06
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005
#define FOOTPRINTS_BLOOD_RED_KEEP 0.6
#define FOOTPRINTS_BLOOD_RED_MIN 0.03
#define FOOTPRINTS_BLOOD_RED_MAX 0.085
#define FOOTPRINTS_BLOOD_COVER 0.95
#define FOOTPRINTS_BLOOD_GLOSS 0.78
'''),
    ],
    COMP: [
        (r'''    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV));
    return max(fore, heel);
''',
         r'''    const float heel = Ellipse(vec2(u - FOOTPRINTS_HEEL_U, v), vec2(FOOTPRINTS_HEEL_RU, FOOTPRINTS_HEEL_RV));
    // (r111d) the waist joins the heel block and the ball: a boot's sole, not two blobs
    const float waist = Ellipse(vec2(u - FOOTPRINTS_WAIST_U, v), vec2(FOOTPRINTS_WAIST_RU, FOOTPRINTS_WAIST_RV));
    return max(max(fore, heel), waist);
'''),
    ],
    RULES: [
        (r'''// (wet), and with a test knob mud or blood; each fades out over LifeS (20 s).
''',
         r'''// (wet), and with a test knob mud or blood; each fades out over LifeS (30 s, r111d; was 20 s).
'''),
        (r'''// a full coat gives 3 full prints, then 0.7, 0.49 ... and is dry after 10 (7 of them fading). Water,
''',
         r'''// a full coat gives 3 full prints, then 0.7, 0.49 ... and is dry after 10 (7 of them fading). Water,
// (r111d: BloodFullPrints is 4 and BloodKeep 0.75: 4 full prints, then 0.75, 0.56 ... dry after 13, the
// last 9 fading; a wet coat leaves WetFullPrints (3) full prints, then keeps DryPerStep (0.75): 12 prints.)
'''),
        (r'''//   BB_FOOTPRINTS_GAIN  (r111c) a number from 0.25 to 4, default 1: a factor on every print's weight (its
//                       strength x shape x facing); other text: 1 (said in the log).
// Look (r111c): a blood print's red is 0.75 times the stone's own red (0.04 to 0.10), green 0.006, blue
// 0.005, cover 95%, gloss 0.72; a wet print darkens the albedo by up to 60%, gloss 0.8; the sole is drawn
// 1.25 times larger (0.33 x 0.12 m) on ground within 0.16 m of the print's height.
''',
         r'''//   BB_FOOTPRINTS_GAIN  (r111c, r111d) a number from 0 to 4, default 1: a factor on every print's weight (its
//                       strength x shape x facing; 0 draws no print); other text: 1 (said in the log). With
//                       the test tools' live knobs a running game asks again every pass (Gain()).
// Look (r111d): a blood print's red is 0.6 times the stone's own red (0.03 to 0.085), green 0.006, blue
// 0.005, cover 95%, gloss 0.78; a wet print darkens the albedo by up to 65%, gloss 0.8; the sole is a
// boot's (heel, waist, ball), 0.28 x 0.11 m, on ground within 0.16 m of the print's height.
'''),
        (r'''#include "blood_albedo.h"
''',
         r'''#include "blood_albedo.h"
// (r111d) The test tools' live knobs (branch dev/test-tools): with that header the gain is asked again every
// pass; without it (a feature branch) it is read once, as before.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h" // test tools (r84_live-test-knobs) only
#define BB_FOOTPRINTS_LIVE 1
#else
#define BB_FOOTPRINTS_LIVE 0
#endif
'''),
        (r'''static_assert(FOOTPRINTS_WET_GLOSS == 0.8 && FOOTPRINTS_WET_SPEC_ROOT == 0.25 &&
              FOOTPRINTS_WET_DARKEN == 0.6);
''',
         r'''static_assert(FOOTPRINTS_WET_GLOSS == 0.8 && FOOTPRINTS_WET_SPEC_ROOT == 0.25 &&
              FOOTPRINTS_WET_DARKEN == 0.65);
'''),
        (r'''static_assert(FOOTPRINTS_SOLE_SCALE == 1.25 && FOOTPRINTS_BLOOD_RED_KEEP == 0.75 &&
              FOOTPRINTS_BLOOD_COVER == 0.95 && FOOTPRINTS_BLOOD_GLOSS == 0.72);
''',
         r'''static_assert(FOOTPRINTS_SOLE_SCALE == 1.0 && FOOTPRINTS_BLOOD_RED_KEEP == 0.6 &&
              FOOTPRINTS_BLOOD_COVER == 0.95 && FOOTPRINTS_BLOOD_GLOSS == 0.78);
// (r111d) The boot: 0.28 m long (heel's back to the ball's front), 0.11 m across at the ball; the waist
// ellipse reaches from the heel block to the ball, so the three make one print.
static_assert((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                      FOOTPRINTS_SOLE_SCALE > 0.279 &&
              (FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                      FOOTPRINTS_SOLE_SCALE < 0.281);
static_assert(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE > 0.109 &&
              2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE < 0.111);
static_assert(FOOTPRINTS_WAIST_U - FOOTPRINTS_WAIST_RU < FOOTPRINTS_HEEL_U + FOOTPRINTS_HEEL_RU &&
              FOOTPRINTS_WAIST_U + FOOTPRINTS_WAIST_RU > FOOTPRINTS_FORE_U - FOOTPRINTS_FORE_RU &&
              FOOTPRINTS_WAIST_RV < FOOTPRINTS_HEEL_RV && FOOTPRINTS_WAIST_RV < FOOTPRINTS_FORE_RV);
static_assert(FOOTPRINTS_EDGE > 0.0 && FOOTPRINTS_EDGE < 1.0);
'''),
        (r'''inline constexpr float LifeS = 20.0f;      ///< a print fades out over this
inline constexpr float DryPerStep = 0.8f;  ///< the share of the coat a step leaves on the feet
''',
         r'''inline constexpr float LifeS = 30.0f;      ///< a print fades out over this (r111d: 30 s, was 20)
inline constexpr float DryPerStep = 0.75f; ///< the share of the coat a step leaves on the feet (r111d: 0.75, was 0.8)
'''),
        (r'''/// BB_FOOTPRINTS_GAIN (r111c): the accepted range.
inline constexpr double GainMin = 0.25, GainMax = 4.0;
''',
         r'''/// BB_FOOTPRINTS_GAIN (r111c): the accepted range (r111d: from 0, which draws no print).
inline constexpr double GainMin = 0.0, GainMax = 4.0;
'''),
        (r'''inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"));
    return knobs;
}
''',
         r'''inline const Knobs& Load() {
    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"));
    return knobs;
}

/// (r111d) The gain of BB_FOOTPRINTS_GAIN's text: the number, else 1 (as Read gives it).
inline float GainOfText(const char* text) {
    return Read("1", nullptr, text).gain;
}

/// (r111d) The gain to draw with now. With the test tools' live knobs (BB_LIVE_KNOBS_FILE) it is asked again
/// every call, so one running game can draw a view with its prints (1) and the same view without them (0);
/// without them it is Load().gain, read once.
inline float Gain() {
#if BB_FOOTPRINTS_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_FOOTPRINTS_GAIN", GainOfText};
    return knob.Get();
#else
    return Load().gain;
#endif
}
'''),
        (r'''inline constexpr std::uint32_t BloodFullPrints = 3; ///< a blood coat: this many full prints
inline constexpr float BloodKeep = 0.7f;            ///< then each step keeps this much
inline constexpr CoatRule RuleOf(Kind kind) {
    // (mud, which only the test coat makes, wears as wet does)
    return kind == Kind::Blood ? CoatRule{BloodFullPrints, BloodKeep} : CoatRule{1, DryPerStep};
}
''',
         r'''inline constexpr std::uint32_t BloodFullPrints = 4; ///< a blood coat: this many full prints (r111d: 4, was 3)
inline constexpr float BloodKeep = 0.75f;           ///< then each step keeps this much (r111d: 0.75, was 0.7)
inline constexpr std::uint32_t WetFullPrints = 3;   ///< (r111d) a wet coat: this many full prints (was 1)
inline constexpr CoatRule RuleOf(Kind kind) {
    // (mud, which only the test coat makes, wears as wet does)
    return kind == Kind::Blood ? CoatRule{BloodFullPrints, BloodKeep} : CoatRule{WetFullPrints, DryPerStep};
}
/// (r111d) The prints a coat of amount 1 leaves before the feet are dry: what TakeStep does, counted (the
/// first `full` at the whole amount, then each step keeps `keep`; dry below MinCoat).
inline constexpr std::uint32_t CoatPrints(Kind kind) {
    const CoatRule rule = RuleOf(kind);
    float amount = 1.0f;
    std::uint32_t full = rule.full, n = 0;
    while (amount >= MinCoat && n < 64) {
        ++n;
        if (full > 1) {
            --full;
        } else {
            amount *= rule.keep;
        }
    }
    return n;
}
'''),
    ],
    VKH: [
        (r'''    bool told_onscreen = false, told_camera = false; ///< (r111c) the first prints on a screen; the camera near
''',
         r'''    bool told_onscreen = false, told_camera = false; ///< (r111c) the first prints on a screen; the camera near
    float told_gain = -1.0f; ///< (r111d) the gain the last "gain now" line said (-1: none yet)
'''),
    ],
    VKC: [
        (r'''                     k.gain_bad ? " (BB_FOOTPRINTS_GAIN is no number from 0.25 to 4: 1 used)"
''',
         r'''                     k.gain_bad ? " (BB_FOOTPRINTS_GAIN is no number from 0 to 4: 1 used)"
'''),
        (r'''    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
''',
         r'''    BbReport::Printf("Footprints (r111d): boot sole %.2f x %.2f m (heel, waist, ball); a blood coat leaves %u full "
                     "prints then keeps %.2f a step (%u prints), a wet coat %u then %.2f (%u prints); prints "
                     "fade over %.0f s; gain 0 draws none\n",
                     double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                            FOOTPRINTS_SOLE_SCALE),
                     double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE), R::BloodFullPrints,
                     double(R::BloodKeep), R::CoatPrints(R::Kind::Blood), R::WetFullPrints,
                     double(R::DryPerStep), R::CoatPrints(R::Kind::Wet), double(R::LifeS));
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
'''),
        (r'''    push.gain = k.gain;
''',
         r'''    push.gain = R::Gain();
    if (push.gain != told_gain) { // (r111d) the first pass, and each change of the live gain
        told_gain = push.gain;
        BbReport::Printf("Footprints (r111d): print strength gain now %.2f%s\n", double(push.gain),
                         push.gain == 0.0f ? " (no print is drawn)" : "");
    }
'''),
        (r'''                     stats.print_px_frames, stats.print_px_max, double(k.gain));
''',
         r'''                     stats.print_px_frames, stats.print_px_max, double(R::Gain()));
'''),
    ],
    TEST: [
        (r'''        assert(Read("1", nullptr, "0.2").gain_bad && Read("1", nullptr, "5").gain_bad);
''',
         r'''        assert(Read("1", nullptr, "-0.1").gain_bad && Read("1", nullptr, "5").gain_bad);
        // (r111d) 0 is a gain: no print is drawn; the live knob's parser gives the same number.
        assert(Read("1", nullptr, "0").gain == 0.0f && !Read("1", nullptr, "0").gain_bad);
        assert(Read("1", nullptr, "0.2").gain == 0.2f && !Read("1", nullptr, "0.2").gain_bad);
        assert(GainOfText(nullptr) == 1.0f && GainOfText("0") == 0.0f && GainOfText(" 3 ") == 3.0f);
        assert(GainOfText("lots") == 1.0f && GainOfText("") == 1.0f && GainOfText("4.5") == 1.0f);
'''),
        (r'''            assert(kind == Kind::Wet && s < last);
''',
         r'''            assert(kind == Kind::Wet && s <= last);
'''),
        (r'''        // 0.8^n >= 0.06: n <= 12.6, so 13 prints (1, 0.8, ..., 0.8^12 = 0.0687)
        assert(prints == 13 && c.amount == 0.0f);
''',
         r'''        // r111d: 3 full prints, then 0.75^n >= 0.06 (n <= 9.8): 12 prints (1, 1, 1, 0.75, ..., 0.75^9 = 0.0751)
        assert(prints == 12 && c.amount == 0.0f && prints == int(CoatPrints(Kind::Wet)));
'''),
        (r'''        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 3u);
''',
         r'''        assert(c.kind == Kind::Blood && c.amount == 1.0f && c.source == Source::Blood && c.full == 4u);
'''),
        (r'''        // The feet leave the blood (nothing under them: the coat is kept): 3 full prints, then 0.7
        // of the amount a step, dry after 10 prints in all.
''',
         r'''        // The feet leave the blood (nothing under them: the coat is kept): 4 full prints, then 0.75
        // of the amount a step, dry after 13 prints in all (r111d; r111b had 3 full, then 0.7, 10 prints).
'''),
        (r'''        assert(prints == 10 && c.amount == 0.0f);
        assert(strength[0] == 1.0f && strength[1] == 1.0f && strength[2] == 1.0f);
        assert(Near(strength[3], 0.7) && Near(strength[4], 0.49) && Near(strength[9], 0.0823543));
''',
         r'''        assert(prints == 13 && c.amount == 0.0f && prints == int(CoatPrints(Kind::Blood)));
        assert(strength[0] == 1.0f && strength[1] == 1.0f && strength[2] == 1.0f && strength[3] == 1.0f);
        assert(Near(strength[4], 0.75) && Near(strength[5], 0.5625) && Near(strength[12], 0.0751, 1e-3));
        // (r111d) the walk of a short trail: 4 full prints, and 9 more fading over a long walk
        assert(CoatPrints(Kind::Blood) - BloodFullPrints == 9u && CoatPrints(Kind::Wet) - WetFullPrints == 9u);
'''),
        (r'''        assert(c.source == Source::Puddle && c.full == 1u);
''',
         r'''        assert(c.source == Source::Puddle && c.full == WetFullPrints);
'''),
        (r'''        // Blood and wet coats as a table: blood 3 full then 0.7; wet 1 full then 0.8.
        assert(RuleOf(Kind::Blood).full == 3u && Near(RuleOf(Kind::Blood).keep, 0.7));
        assert(RuleOf(Kind::Wet).full == 1u && Near(RuleOf(Kind::Wet).keep, 0.8));
''',
         r'''        // Blood and wet coats as a table (r111d): blood 4 full then 0.75; wet 3 full then 0.75.
        assert(RuleOf(Kind::Blood).full == 4u && Near(RuleOf(Kind::Blood).keep, 0.75));
        assert(RuleOf(Kind::Wet).full == 3u && Near(RuleOf(Kind::Wet).keep, 0.75));
'''),
        (r'''    // Fade: full at 0, half at LifeS / 2, none from LifeS on.
    {
        assert(Near(Fade(0.0), 1.0) && Near(Fade(10.0), 0.5) && Near(Fade(20.0), 0.0) && Near(Fade(99.0), 0.0));
        assert(Fade(2.0) > 0.96 && Fade(5.0) > Fade(15.0));
''',
         r'''    // Fade: full at 0, half at LifeS / 2, none from LifeS on (r111d: LifeS 30).
    {
        assert(LifeS == 30.0f);
        assert(Near(Fade(0.0), 1.0) && Near(Fade(15.0), 0.5) && Near(Fade(30.0), 0.0) && Near(Fade(99.0), 0.0));
        assert(Fade(2.0) > 0.98 && Fade(5.0) > Fade(15.0) && Fade(10.0) > 0.7);
'''),
    ],
    README: [
        (r'''his feet leave wet prints on the ground that fade out over 20 seconds: darker''',
         r'''his feet leave wet prints on the ground that fade out over 30 seconds: darker'''),
        (r'''(a sole about 0.33 m long and 0.12 m wide)''',
         r'''(a boot's sole about 0.28 m long and 0.11 m wide at the ball: a heel block, a narrow waist and a ball)'''),
        (r'''and each step leaves 0.8 of it on them; below 0.06 they are dry (so 13 prints after wading out).''',
         r'''and the first 3 prints leave the whole of it, then each step leaves 0.75 of it; below 0.06 they are dry (so 12 prints after wading out: 3 full, then 9 fading).'''),
        (r'''the first 3 prints leave the whole strength and each step after keeps 0.7 of it (0.7, 0.49, 0.34 for a full coat), and the feet are dry (below 0.06) after 10 prints.''',
         r'''the first 4 prints leave the whole strength and each step after keeps 0.75 of it (0.75, 0.56, 0.42 for a full coat), and the feet are dry (below 0.06) after 13 prints (4 full, then 9 fading).'''),
        (r'''wet prints work as before (13 prints).''',
         r'''a wet coat leaves 12 prints (3 full, then 9 fading).'''),
        (r'''The sole is drawn 1.25 times larger than its first numbers (0.33 x 0.12 m); at 1080p a print 3 to 4 m from the camera is 33 to 44 px wide, so it is small by nature: look at the ground between the camera and the hunter, not behind him.''',
         r'''The sole is a boot's (r111d: a heel block 0.08 m across, a narrow waist 0.044 m and a ball 0.11 m, 0.28 m long in all, the outline soft over about 1 cm); at 1080p a print 3 to 4 m from the camera is about 38 to 50 px across its width and, lying across the view, 96 to 128 px along its length (shorter by the angle over the ground when it points along the view), so it is small by nature and reads best from the side of the trail: a third-person camera 3 m behind a walking hunter sees the older prints at the bottom edge of the picture or under itself, so turn the camera a quarter turn around him after the walk. A print lives 30 seconds.'''),
        (r'''A wet print darkens the (linear) albedo by up to 60%, raises the gloss toward 0.8''',
         r'''A wet print darkens the (linear) albedo by up to 65%, raises the gloss toward 0.8'''),
        (r'''(0.75 times it, at least 0.04 and at most 0.10; green 0.006''',
         r'''(0.6 times it, at least 0.03 and at most 0.085; green 0.006'''),
        (r'''raises the gloss toward 0.72 and the specular colour as wet.''',
         r'''raises the gloss toward 0.78 and the specular colour as wet.'''),
        (r'''(so a picture's absence of prints can be told from a pass that drew none).''',
         r'''(so a picture's absence of prints can be told from a pass that drew none). Lines of r111d: once at the start the sole and how many prints each coat leaves (blood 13, wet 12); and "print strength gain now" at the first pass and at each change of the gain.'''),
        (r'''A number from 0.25 to 4: a factor on every print's weight''',
         r'''A number from 0 to 4 (0 draws no print at all; the feature stays on): a factor on every print's weight'''),
        (r'''Unset or empty: 1; other text or a number out of range: 1 (the log says so) | `1` |''',
         r'''Unset or empty: 1; other text or a number out of range: 1 (the log says so). In a build with the test tools' live knobs (`BB_LIVE_KNOBS_FILE`) a running game asks again every pass, so one game can show a view with its prints and the same view without them | `1` |'''),
    ],
}


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("REFUSED %s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def state_of(cur, eds, path):
    """'applied' (each new text once), 'clean' (each old text once, no new text), else refuse."""
    done = todo = 0
    for old, new in eds:
        co, cn = cur.count(old), cur.count(new)
        if cn == 1 and (co == 0 or new.find(old) >= 0 and co == 1):
            done += 1
        elif cn == 0 and co == 1:
            todo += 1
        else:
            raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1 and 0, or 0 or 1 "
                             "and 1; are r111, r111b and r111c applied, and is this patch's own earlier version "
                             "reverted?): %r" % (path, co, cn, old[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("REFUSED %s: %d of %d edits applied (mixed)" % (path, done, len(eds)))


def text_checks(texts):
    """Ties a compiler cannot check, on the full result."""
    def need(path, text, n=1):
        if texts[path].count(text) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d"
                             % (path, text, texts[path].count(text), n))
    rules, cpp, lay, comp = texts[RULES], texts[VKC], texts[LAYOUT], texts[COMP]
    nums = {m.group(1): float(m.group(2)) for m in re.finditer(r"#define (FOOTPRINTS_\w+) (-?[0-9.]+)\n", lay)}
    want = {"FOOTPRINTS_PRINT_BAND_M": 0.16, "FOOTPRINTS_SOLE_SCALE": 1.0, "FOOTPRINTS_WET_DARKEN": 0.65,
            "FOOTPRINTS_WET_GLOSS": 0.8, "FOOTPRINTS_WET_SPEC_ROOT": 0.25, "FOOTPRINTS_BLOOD_ALBEDO_R": 0.06,
            "FOOTPRINTS_BLOOD_ALBEDO_G": 0.006, "FOOTPRINTS_BLOOD_ALBEDO_B": 0.005,
            "FOOTPRINTS_BLOOD_RED_KEEP": 0.6, "FOOTPRINTS_BLOOD_RED_MIN": 0.03, "FOOTPRINTS_BLOOD_RED_MAX": 0.085,
            "FOOTPRINTS_BLOOD_COVER": 0.95, "FOOTPRINTS_BLOOD_GLOSS": 0.78, "FOOTPRINTS_EDGE": 0.82}
    for k, v in want.items():
        if nums.get(k) != v:
            raise SystemExit("text check: %s is %r in the layout, wanted %r" % (k, nums.get(k), v))

    # The blood rule (blood_albedo_layout.h numbers) holds for the print's whole red range.
    def is_blood(r, g, b):
        return 0.01 <= r <= 0.12 and r >= 2.5 * g and r >= 2.5 * b
    g, b = nums["FOOTPRINTS_BLOOD_ALBEDO_G"], nums["FOOTPRINTS_BLOOD_ALBEDO_B"]
    for red in (nums["FOOTPRINTS_BLOOD_RED_MIN"], nums["FOOTPRINTS_BLOOD_ALBEDO_R"], nums["FOOTPRINTS_BLOOD_RED_MAX"]):
        if not is_blood(red, g, b):
            raise SystemExit("text check: a blood print red of %r is not blood by the rule" % red)
    # The boot: 0.28 x 0.11 m, the waist bridges heel and ball, everything fits the 0.2 m print box.
    n = nums
    sc = n["FOOTPRINTS_SOLE_SCALE"]
    length = (n["FOOTPRINTS_FORE_U"] + n["FOOTPRINTS_FORE_RU"] - (n["FOOTPRINTS_HEEL_U"] - n["FOOTPRINTS_HEEL_RU"])) * sc
    width = 2 * n["FOOTPRINTS_FORE_RV"] * sc
    if not (abs(length - 0.28) < 1e-6 and abs(width - 0.11) < 1e-6):
        raise SystemExit("text check: the sole is %.4f x %.4f m, wanted 0.28 x 0.11" % (length, width))
    if not (n["FOOTPRINTS_WAIST_U"] - n["FOOTPRINTS_WAIST_RU"] < n["FOOTPRINTS_HEEL_U"] + n["FOOTPRINTS_HEEL_RU"]
            and n["FOOTPRINTS_WAIST_U"] + n["FOOTPRINTS_WAIST_RU"] > n["FOOTPRINTS_FORE_U"] - n["FOOTPRINTS_FORE_RU"]):
        raise SystemExit("text check: the waist does not bridge heel and ball")
    reach = max(n["FOOTPRINTS_FORE_U"] + n["FOOTPRINTS_FORE_RU"], -(n["FOOTPRINTS_HEEL_U"] - n["FOOTPRINTS_HEEL_RU"])) * sc
    if not (reach < 0.2 and n["FOOTPRINTS_PRINT_BAND_M"] < 0.2):
        raise SystemExit("text check: the sole does not fit the 0.2 m print box")
    # Coat counts: the numbers the README, the test and the log say are the rule's own (TakeStep, in float).
    import struct

    def f32(x):
        return struct.unpack("f", struct.pack("f", x))[0]

    def prints(full, keep):
        amount, count = f32(1.0), 0
        while amount >= f32(0.06) and count < 64:
            count += 1
            if full > 1:
                full -= 1
            else:
                amount = f32(amount * f32(keep))
        return count
    if prints(4, 0.75) != 13 or prints(3, 0.75) != 12:
        raise SystemExit("text check: the coat counts are %d and %d, not 13 and 12" % (prints(4, 0.75), prints(3, 0.75)))
    need(RULES, "BloodFullPrints = 4;")
    need(RULES, "BloodKeep = 0.75f;")
    need(RULES, "WetFullPrints = 3;")
    need(RULES, "DryPerStep = 0.75f;")
    need(RULES, "LifeS = 30.0f;")
    need(RULES, "GainMin = 0.0, GainMax = 4.0;")
    need(RULES, "#define BB_FOOTPRINTS_LIVE 1\n")
    need(RULES, "#define BB_FOOTPRINTS_LIVE 0\n")
    need(RULES, "static BbLiveKnobs::Knob<float> knob{\"BB_FOOTPRINTS_GAIN\", GainOfText};")
    need(RULES, "return Load().gain;\n")
    need(COMP, "const float waist = Ellipse(")
    need(COMP, "return max(max(fore, heel), waist);")
    need(COMP, "Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE)")
    need(VKC, "    push.gain = R::Gain();\n")
    if "k.gain)" in cpp.split("Footprints::OnFrameEnd")[1]:
        raise SystemExit("text check: OnFrameEnd still reads k.gain")
    # The README's numbers agree with the layout and the rules.
    whole = texts[README]
    for gone in ("fade out over 20 seconds", "a sole about 0.33 m long", "up to 60%, raises the gloss toward 0.8",
                 "(0.75 times it, at least 0.04", "toward 0.72 and the specular", "each step leaves 0.8 of it",
                 "(0.7, 0.49, 0.34 for a full coat)", "(13 prints)", "drawn 1.25 times larger"):
        if gone in whole:
            raise SystemExit("text check: README still says %r" % gone)
    # Log lines: prefix, and under 300 characters with wide numbers (the slot runner keeps 300).
    for m in re.finditer(r'BbReport::Printf\(((?:\s*"(?:[^"\\]|\\.)*")+)', cpp):
        fmt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))).replace("\\n", "")
        if not fmt.startswith("Footprints (r111"):
            raise SystemExit("text check: a log line without its prefix: %r" % fmt[:60])
        wide = re.sub(r"%[-+]?[0-9]*\.[0-9]+f", "X" * 9, fmt)
        wide = re.sub(r"%(?:ll)?[ud]", "X" * 7, wide)
        wide = re.sub(r"%s", "X" * 12, wide)
        wide = wide.replace("%%", "%")
        if "r111d" in fmt:
            print("  r111d log line (wide %d): %s..." % (len(wide), fmt[:50]))
        if "r111c" in fmt:
            extra = len(" (BB_FOOTPRINTS_GAIN is no number from 0 to 4: 1 used)") - 12 if "gain %.2f%s" in fmt else 0
            extra += len("outside the 1.5 to 6 m, 0.5 to 3 m above window: look at the ring") - 12 if "within 12 m: %s" in fmt else 0
            wide += "X" * max(extra, 0)
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    # The r111d printf with 9 conversions has 9 arguments (the compiler's format check decides the rest).
    mm = re.search(r'Footprints \(r111d\): boot sole.*?fade over %\.0f s; gain 0 draws none\\n",(.*?)\);', cpp, re.S)
    if not mm or mm.group(1).count("R::") != 9 or "FOOTPRINTS_FORE_U" not in mm.group(1):
        raise SystemExit("text check: the r111d once-line's arguments are not as expected")
    # No tab, no CR in the edit texts.
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111d_prints-readable.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111D_ROOT)" % ROOT)
    for need_path in (RULES, HS + "blood_albedo_layout.h"):
        if not os.path.exists(os.path.join(ROOT, need_path)):
            raise SystemExit("REFUSED: r111 and r111b are not applied (%s is missing)" % need_path)
    plan = []
    for path in ORDER:
        raw, eol, cur = load(path)
        plan.append((path, EDITS[path], raw, eol, cur, state_of(cur, EDITS[path], path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("REFUSED mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for old, new in eds:
                cur = cur.replace(old, new, 1)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            texts = {p[0]: p[4] for p in plan}
            text_checks(texts)
            print("applied (%d files edited; text checks pass)" % len(plan))
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r111dtmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        print("applied (%d files edited)" % len(plan))
        return
    if state != "applied":
        print("nothing to revert")
        return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for old, new in reversed(eds):
            if cur.count(new) != 1:
                raise SystemExit("%s: new text found %d times in the revert: %r" % (path, cur.count(new), new[:70]))
            cur = cur.replace(new, old, 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r111dtmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
