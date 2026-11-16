# r111c_prints-visible: FEATURE fix on top of r111_footprints and r111b_footprints-pickup (owner 2026-11-15:
# "footprints that react to wet surfaces making wet foot prints, muddy, or bloody"; build 28 (b28): the
# pickup logic works, but nobody could see the prints). Still off unless BB_FOOTPRINTS is set (r111's knob),
# costs nothing more than r111 when off. Branch: visual/footprints.
#
# WHAT THE b28 NUMBERS SAY (read before the changes):
#  - The position read and its space are right. The log line "first hunter position ... camera at 0.00 4.00
#    -8.00: 105.49 m away, 44.82 m above" was told on the first frame the game's position could be read, when
#    the camera still held its start values (0 4 -8, the load screen). The same window's range line says
#    "camera 2.75 to 4.45 m away, 1.41 to 1.42 m above his position" (the window's own text: about 1.5 to 6 m
#    and 0.5 to 3 m is the same space), and the earlier show run (b24/b25) painted the magenta ring and the
#    cyan wet prints at his feet. So prints land where he walked. (r111c tells the camera line again once it
#    is within 12 m.)
#  - The print size is realistic and therefore small: a sole 0.26 x 0.096 m. At 1080p (y scale 2.5386, so
#    1371 px per radian-unit) a print 3 m from the camera is 44 px wide and, seen from 25 degrees above the
#    ground, about 50 px long; at 4 m 33 px; 0.017 m2 of ground a print, so about 800 to 2000 px of a 2.07 M
#    pixel picture: "1094 print pixels of 2073600" at the cp1 read-back is one or two faded prints, not a
#    broken pass. The pass itself works: cp1 had 1094 print pixels, the show run painted every print.
#  - The b28 pictures cannot show prints, by their framing: rx=255 turns the camera about 200 degrees a second
#    (look1 after 0.9 s = the hunter seen from the front, look3 after 1.8 s = the first direction again with
#    the hunter's back). In front of the hunter the trail lies behind his body at 4 to 10 m and 8 to 19 degrees
#    over the ground (a print 0.26 m long then shows 4 to 8 px of length, in grass); in the church the
#    camera's collision with the wall pulled it into the hunter's shoulder (cp1 look1). The prints are on the
#    camera's side of him: a third-person camera 3 to 4.5 m behind him looks down on them. So the new jobs do
#    not turn the camera: walk, tilt down a little, capture, and capture the same view again after the prints
#    have faded (the picture's own twin).
#  - The look in the dark: a wet print darkened the albedo by 50% (x0.5, which is x0.73 in sRGB bytes: 40
#    levels become 29, under the cobbles' own texture noise at 3 to 4 m) and a blood print took the albedo
#    toward (0.05, 0.006, 0.005) (r111b, made that dark so prints in the pool do not stand out). Modelled on the
#    graveyard stone (0.09 0.072 0.058) that print is (0.056, 0.016, 0.013): 0.30 of the stone's luminance, so
#    a dark patch: it would read IF it were in the picture. Only 1 of the 8 steps of gb1 lay in the pool
#    ("steps in blood 1"), where a print leaves the albedo alone by design.
#
# What changes:
#  - Blood prints get their red from the stone they lie on: red = 0.75 x the ground's linear red, at least
#    0.04 and at most 0.10 (the blood rule's own maximum is 0.12, so prints stay blood for the pickup rule and
#    the blood sheen), green 0.006, blue 0.005; cover 95%, gloss toward 0.72. On the graveyard's stone
#    (linear 0.09 0.072 0.058) the print comes out (0.069, 0.009, 0.008); on the church floor (0.125 0.109
#    0.087) (0.095, 0.011, 0.009). Modelled lit by a bluish night light (0.3 0.4 0.8) its luminance is 0.25
#    (graveyard) and 0.22 (church) of the stone's, against 0.30 and 0.25 of the r111b print (0.056, 0.016,
#    0.013 on the graveyard stone): the luminance contrast improves only a little, the change is the hue
#    (red over green 7.4 against 3.5, the stone's own is 1.2): a dark RED patch, not a dark patch. (A variant
#    with red 0.9 x the stone and green 0.012 was modelled too: its luminance ratio was worse, 0.38, so it
#    was dropped.) The modelling is arithmetic, not a measurement: the game's lighting is not in it.
#    Prints in the pool are still left alone (a print is never brighter than the blood it lies in).
#  - Wet prints darken the albedo by up to 60% (was 50%), raise the gloss toward 0.8 (was 0.62) and the
#    specular colour root toward 0.25 (was 0.2, f0 0.0625).
#  - The sole is 1.25 times larger (0.33 x 0.12 m, a hunter's boot with the cloak's hem; footprints.h boxes
#    0.2 m); the band a print lies on is 0.16 m (was 0.12, cobbles tilt by several cm across a sole).
#  - BB_FOOTPRINTS_GAIN (new, 0.25 to 4, default 1): a factor on every print's weight (strength x shape x
#    facing), so the look can be turned up in a slot job without a build (a TEST knob, part of the feature).
#  - Diagnosis lines (log): once at the start the gain and the look numbers; once when the camera first lies
#    within 12 m of the hunter (the first-hunter line's camera was the start value); once when prints first lie
#    on a pass's screen (how many, how far, how big the largest box is in pixels); every 600 frames one line
#    with the passes with prints, the prints sent, the distance range, the largest box and the read-backs that
#    showed print pixels (the old "recent frame" line named one arbitrary frame at the end of the run).
#
# Off (BB_FOOTPRINTS unset or 0): nothing of r111c runs (all of it is inside Footprints' own methods and its
# shader, made only when Wanted(); the third getenv is read in the same static Knobs read that r111 already
# does); the shader build footprints_comp changes (nothing else includes footprints_layout.h or is compiled
# from it), no other shader build and no other C++ unit changes except by the four footprints headers.
#
# Files edited (r111/r111b's own text; each old text found exactly once, replaced or kept with an insert):
# renderer_vulkan/footprints.h, vk_footprints.h, vk_footprints.cpp, host_shaders/footprints.comp,
# footprints_layout.h, engine/tests/test_footprints.cpp, README.md. New files: none.
#
# Order: needs r111 and r111b applied (refused otherwise: the old texts are theirs). To take r111b out again,
# revert r111c first (r111b's check and revert refuse files that r111c changed).
# Use: python -I -X utf8 r111c_prints-visible.py check | apply | revert
# Root: R111C_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r111c_backup next to this script; revert puts each old text back (each new text found by itself, exactly
# once).
import os, re, sys

ROOT = os.environ.get("R111C_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r111c_backup")
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

NEW = {}

# (path, old, new): `old` found exactly once; `new` replaces it. Applied when `new` is found exactly once.
EDITS = {
    LAYOUT: [
        # the band a print lies on
        (r'''#define FOOTPRINTS_PRINT_BAND_M 0.12
''',
         r'''// (r111c: 0.16, was 0.12: the graveyard's cobbles tilt by several cm across one sole)
#define FOOTPRINTS_PRINT_BAND_M 0.16
'''),
        # the sole's size
        (r'''#define FOOTPRINTS_EDGE 0.7
''',
         r'''#define FOOTPRINTS_EDGE 0.7
// (r111c) The sole is drawn this many times larger than the numbers above (0.33 x 0.12 m in all): at 1080p
// a print 3 to 4 m from the camera is then 33 to 44 px wide.
#define FOOTPRINTS_SOLE_SCALE 1.25
'''),
        # wet
        (r'''#define FOOTPRINTS_WET_DARKEN 0.5
#define FOOTPRINTS_WET_GLOSS 0.62
#define FOOTPRINTS_WET_SPEC_ROOT 0.2
''',
         r'''// (r111c: darken 0.6 was 0.5, gloss 0.8 was 0.62, specular root 0.25 was 0.2: a wet print on night stone
// was a few levels darker than the stone, under its noise)
#define FOOTPRINTS_WET_DARKEN 0.6
#define FOOTPRINTS_WET_GLOSS 0.8
#define FOOTPRINTS_WET_SPEC_ROOT 0.25
'''),
        # blood
        (r'''#define FOOTPRINTS_BLOOD_ALBEDO_R 0.05
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005
#define FOOTPRINTS_BLOOD_COVER 0.85
#define FOOTPRINTS_BLOOD_GLOSS 0.58
''',
         r'''// (r111c: the print's red follows the stone it lies on, so it reads as a dark red patch on any ground:
// red = the ground's linear red x BLOOD_RED_KEEP, between RED_MIN and RED_MAX (the blood rule's own maximum
// is 0.12, so prints stay blood for the pickup rule and the blood sheen); green and blue are low, ALBEDO_G
// and _B. ALBEDO_R is the typical print red (the stone's 0.09 x 0.75), kept for the tests.)
#define FOOTPRINTS_BLOOD_ALBEDO_R 0.07
#define FOOTPRINTS_BLOOD_ALBEDO_G 0.006
#define FOOTPRINTS_BLOOD_ALBEDO_B 0.005
#define FOOTPRINTS_BLOOD_RED_KEEP 0.75
#define FOOTPRINTS_BLOOD_RED_MIN 0.04
#define FOOTPRINTS_BLOOD_RED_MAX 0.10
#define FOOTPRINTS_BLOOD_COVER 0.95
#define FOOTPRINTS_BLOOD_GLOSS 0.72
'''),
    ],
    COMP: [
        (r'''    uint stamp;       // the host's frame + 1
    uint pad;
};
''',
         r'''    uint stamp;       // the host's frame + 1
    float gain;       // BB_FOOTPRINTS_GAIN (r111c): a factor on every print's weight
};
'''),
        (r'''            const float s = Sole(u, v) * pr.a.w;
''',
         r'''            const float s = Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE) * pr.a.w;
'''),
        (r'''        const float wet = clamp(weight[FOOTPRINTS_KIND_WET] * face * grain, 0.0, 1.0);
        const float mud = clamp(weight[FOOTPRINTS_KIND_MUD] * face * grain, 0.0, 1.0);
        const float blood = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * grain, 0.0, 1.0);
''',
         r'''        const float wet = clamp(weight[FOOTPRINTS_KIND_WET] * face * grain * gain, 0.0, 1.0);
        const float mud = clamp(weight[FOOTPRINTS_KIND_MUD] * face * grain * gain, 0.0, 1.0);
        const float blood = clamp(weight[FOOTPRINTS_KIND_BLOOD] * face * grain * gain, 0.0, 1.0);
'''),
        (r'''                    const vec3 blood_albedo = vec3(FOOTPRINTS_BLOOD_ALBEDO_R, FOOTPRINTS_BLOOD_ALBEDO_G,
                                                   FOOTPRINTS_BLOOD_ALBEDO_B);
''',
         r'''                    // (r111c) the red follows the stone's own red: a dark red patch on any ground
                    const vec3 blood_albedo =
                        vec3(clamp(a.r * FOOTPRINTS_BLOOD_RED_KEEP, FOOTPRINTS_BLOOD_RED_MIN,
                                   FOOTPRINTS_BLOOD_RED_MAX),
                             FOOTPRINTS_BLOOD_ALBEDO_G, FOOTPRINTS_BLOOD_ALBEDO_B);
'''),
    ],
    RULES: [
        (r'''static_assert(FOOTPRINTS_PUDDLE_GLOSS == 0.88 && FOOTPRINTS_PRINT_BAND_M == 0.12);
static_assert(FOOTPRINTS_WET_GLOSS == 0.62 && FOOTPRINTS_WET_SPEC_ROOT == 0.2 &&
              FOOTPRINTS_WET_DARKEN == 0.5);
''',
         r'''static_assert(FOOTPRINTS_PUDDLE_GLOSS == 0.88 && FOOTPRINTS_PRINT_BAND_M == 0.16);
static_assert(FOOTPRINTS_WET_GLOSS == 0.8 && FOOTPRINTS_WET_SPEC_ROOT == 0.25 &&
              FOOTPRINTS_WET_DARKEN == 0.6);
'''),
        (r'''static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_ALBEDO_R), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));
''',
         r'''static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_ALBEDO_R), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));
// (r111c) the print's red runs from RED_MIN to RED_MAX and every one of them is blood by that rule too.
static_assert(FOOTPRINTS_BLOOD_RED_MIN <= FOOTPRINTS_BLOOD_ALBEDO_R &&
              FOOTPRINTS_BLOOD_ALBEDO_R <= FOOTPRINTS_BLOOD_RED_MAX);
static_assert(BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_RED_MIN), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)) &&
              BloodAlbedo::IsBlood(float(FOOTPRINTS_BLOOD_RED_MAX), float(FOOTPRINTS_BLOOD_ALBEDO_G),
                                   float(FOOTPRINTS_BLOOD_ALBEDO_B)));
static_assert(FOOTPRINTS_SOLE_SCALE == 1.25 && FOOTPRINTS_BLOOD_RED_KEEP == 0.75 &&
              FOOTPRINTS_BLOOD_COVER == 0.95 && FOOTPRINTS_BLOOD_GLOSS == 0.72);
'''),
        (r'''inline constexpr float PrintBoxUpM = 0.15f;
/// The horizontal half extent of a print's box (metres): its sole fits in it at any heading.
inline constexpr float PrintBoxAcrossM = 0.16f;
static_assert(FOOTPRINTS_PRINT_BAND_M < PrintBoxUpM);
static_assert(FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU < PrintBoxAcrossM &&
              -(FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU) < PrintBoxAcrossM);
''',
         r'''inline constexpr float PrintBoxUpM = 0.2f;
/// The horizontal half extent of a print's box (metres): its sole (drawn FOOTPRINTS_SOLE_SCALE times
/// larger, r111c) fits in it at any heading.
inline constexpr float PrintBoxAcrossM = 0.2f;
static_assert(FOOTPRINTS_PRINT_BAND_M < PrintBoxUpM);
static_assert((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU) * FOOTPRINTS_SOLE_SCALE < PrintBoxAcrossM &&
              -(FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU) * FOOTPRINTS_SOLE_SCALE < PrintBoxAcrossM);
'''),
        (r'''struct Knobs {
    bool on = false;
''',
         r'''/// BB_FOOTPRINTS_GAIN (r111c): the accepted range.
inline constexpr double GainMin = 0.25, GainMax = 4.0;

struct Knobs {
    bool on = false;
'''),
        (r'''    bool coat_bad = false;    ///< BB_FOOTPRINTS_COAT held text that names no kind
};
''',
         r'''    bool coat_bad = false;    ///< BB_FOOTPRINTS_COAT held text that names no kind
    float gain = 1.0f;        ///< BB_FOOTPRINTS_GAIN (r111c): a factor on every print's weight
    bool gain_bad = false;    ///< BB_FOOTPRINTS_GAIN held something but a number from GainMin to GainMax
};
'''),
        (r'''inline Knobs Read(const char* on_text, const char* coat_text) {
''',
         r'''inline Knobs Read(const char* on_text, const char* coat_text, const char* gain_text = nullptr) {
'''),
        (r'''            k.coat_bad = true;
        }
    }
    return k;
}
''',
         r'''            k.coat_bad = true;
        }
    }
    // BB_FOOTPRINTS_GAIN: a number from GainMin to GainMax; anything else is 1 (said in the log).
    const char* gain = Detail::Trim(gain_text);
    if (gain != nullptr && *gain != '\0') {
        char* end = nullptr;
        const double g = std::strtod(gain, &end);
        if (end != gain && *Detail::Trim(end) == '\0' && g >= GainMin && g <= GainMax) {
            k.gain = float(g);
        } else {
            k.gain_bad = true;
        }
    }
    return k;
}
'''),
        (r'''    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"));
''',
         r'''    static const Knobs knobs = Read(std::getenv("BB_FOOTPRINTS"), std::getenv("BB_FOOTPRINTS_COAT"),
                                    std::getenv("BB_FOOTPRINTS_GAIN"));
'''),
        (r'''    std::uint32_t pad = 0;
};
static_assert(sizeof(Push) == 112);
''',
         r'''    float gain = 1.0f;                ///< BB_FOOTPRINTS_GAIN (r111c)
};
static_assert(sizeof(Push) == 112);
'''),
        (r'''//                       text: as unset (said in the log).
// No Vulkan here: tests/test_footprints.cpp builds it alone.
''',
         r'''//                       text: as unset (said in the log).
//   BB_FOOTPRINTS_GAIN  (r111c) a number from 0.25 to 4, default 1: a factor on every print's weight (its
//                       strength x shape x facing); other text: 1 (said in the log).
// Look (r111c): a blood print's red is 0.75 times the stone's own red (0.04 to 0.10), green 0.006, blue
// 0.005, cover 95%, gloss 0.72; a wet print darkens the albedo by up to 60%, gloss 0.8; the sole is drawn
// 1.25 times larger (0.33 x 0.12 m) on ground within 0.16 m of the print's height.
// No Vulkan here: tests/test_footprints.cpp builds it alone.
'''),
    ],
    VKH: [
        (r'''        u32 share_n = 0, share_last = 0, share_max = 0, share_sum = 0; ///< blood share at pickups, %
''',
         r'''        u32 share_n = 0, share_last = 0, share_max = 0, share_sum = 0; ///< blood share at pickups, %
        // (r111c) prints on a pass's screen, and what a read-back of the pass showed
        u32 sent_prints = 0, print_passes = 0, readbacks = 0, print_px_frames = 0, print_px_max = 0;
        float print_near_m = 0.0f, print_far_m = 0.0f; ///< camera to the prints sent
        int box_w = 0, box_h = 0;                      ///< the largest print box on a screen, px
'''),
        (r'''    std::array<bool, 3> told_pickup{}; ///< the first pickup of each kind is told
''',
         r'''    std::array<bool, 3> told_pickup{}; ///< the first pickup of each kind is told
    bool told_onscreen = false, told_camera = false; ///< (r111c) the first prints on a screen; the camera near
'''),
    ],
    VKC: [
        # the gain and look once-line, before the camera check of the constructor
        (r'''    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
''',
         r'''    BbReport::Printf("Footprints (r111c): print strength gain %.2f%s; sole %.2f x %.2f m; a blood print's red "
                     "is %.2f times the stone's (%.3f to %.3f), cover %.0f%%; a wet print darkens by up to %.0f%%\n",
                     double(k.gain),
                     k.gain_bad ? " (BB_FOOTPRINTS_GAIN is no number from 0.25 to 4: 1 used)"
                                : (k.gain != 1.0f ? " (BB_FOOTPRINTS_GAIN)" : ""),
                     double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                            FOOTPRINTS_SOLE_SCALE),
                     double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE),
                     double(FOOTPRINTS_BLOOD_RED_KEEP), double(FOOTPRINTS_BLOOD_RED_MIN),
                     double(FOOTPRINTS_BLOOD_RED_MAX), double(FOOTPRINTS_BLOOD_COVER) * 100.0,
                     double(FOOTPRINTS_WET_DARKEN) * 100.0);
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
'''),
        # prints on this pass's screen: how far, how big
        (r'''    R::Rect rect{};
    for (u32 i = 0; i < placed_count; ++i) {
''',
         r'''    R::Rect rect{};
    float near_print = 0.0f, far_print = 0.0f; // (r111c) camera to the prints sent
    int box_w = 0, box_h = 0;                  // (r111c) the largest print box, px
    for (u32 i = 0; i < placed_count; ++i) {
'''),
        (r'''        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
''',
         r'''        rect = R::Union(rect, r);
        { // (r111c) how far and how big the prints on this pass's screen are
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            near_print = count != 0 ? std::min(near_print, d) : d;
            far_print = count != 0 ? std::max(far_print, d) : d;
            box_w = std::max(box_w, int(r.x1 - r.x0));
            box_h = std::max(box_h, int(r.y1 - r.y0));
        }
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
'''),
        (r'''    bool sensing = false;
    if (hunter_known) {
''',
         r'''    if (count != 0) {
        ++stats.print_passes;
        stats.sent_prints += count;
        stats.print_near_m = stats.print_passes > 1 ? std::min(stats.print_near_m, near_print) : near_print;
        stats.print_far_m = stats.print_passes > 1 ? std::max(stats.print_far_m, far_print) : far_print;
        stats.box_w = std::max(stats.box_w, box_w);
        stats.box_h = std::max(stats.box_h, box_h);
        if (!told_onscreen) {
            told_onscreen = true;
            BbReport::Printf("Footprints (r111c): first prints on a pass's screen at frame %llu: %u of %u "
                             "placed, %.2f to %.2f m from the camera, the largest print box %d x %d px (a "
                             "print is %.2f x %.2f m)\n",
                             static_cast<unsigned long long>(frame), count, placed_count,
                             double(near_print), double(far_print), box_w, box_h,
                             double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU -
                                     (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) * FOOTPRINTS_SOLE_SCALE),
                             double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE));
        }
    }
    bool sensing = false;
    if (hunter_known) {
'''),
        (r'''    push.stamp = u32(frame + 1);
''',
         r'''    push.stamp = u32(frame + 1);
    push.gain = k.gain;
'''),
        # the read-backs that showed print pixels
        (r'''        sense = c;
        sense_fresh = true;
        ++stats.sense_fresh;
''',
         r'''        sense = c;
        sense_fresh = true;
        ++stats.sense_fresh;
        ++stats.readbacks; // (r111c) the pass's own count of print pixels in this read-back
        stats.print_px_frames += c[R::WordPrintPx] != 0u ? 1u : 0u;
        stats.print_px_max = std::max(stats.print_px_max, c[R::WordPrintPx]);
'''),
        # the camera line again once it is near
        (r'''        const bool in_water = R::InWater(plane, plane_y, pos[1]);
''',
         r'''        if (cam.valid && told_position && !told_camera) {
            // (r111c) the first line's camera may still hold its start values (0 4 -8 at the load)
            const float cx = cam.inv_view[3] - pos[0], cy = cam.inv_view[7] - pos[1];
            const float cz = cam.inv_view[11] - pos[2];
            const float cd = std::sqrt(cx * cx + cy * cy + cz * cz);
            if (cd <= 12.0f) {
                told_camera = true;
                BbReport::Printf("Footprints (r111c): hunter at %.2f %.2f %.2f, the camera %.2f m away and "
                                 "%.2f m above his position, the first time it is within 12 m: %s\n",
                                 double(pos[0]), double(pos[1]), double(pos[2]), double(cd), double(cy),
                                 (cd >= 1.5f && cd <= 6.0f && cy >= 0.5f && cy <= 3.0f)
                                     ? "the game's position and the picture agree"
                                     : "outside the 1.5 to 6 m, 0.5 to 3 m above window: look at the ring");
            }
        }
        const bool in_water = R::InWater(plane, plane_y, pos[1]);
'''),
        # the 600-frame line
        (r'''                     R::BloodSharePercent);
    stats = {};
''',
         r'''                     R::BloodSharePercent);
    BbReport::Printf("Footprints (r111c): prints on a pass's screen: %u passes, %u prints sent, %.2f to %.2f m "
                     "from the camera, the largest box %d x %d px; read-backs %u, %u of them with print pixels, "
                     "the most %u px; gain %.2f\n",
                     stats.print_passes, stats.sent_prints, double(stats.print_near_m),
                     double(stats.print_far_m), stats.box_w, stats.box_h, stats.readbacks,
                     stats.print_px_frames, stats.print_px_max, double(k.gain));
    stats = {};
'''),
    ],
    TEST: [
        (r'''        const Knobs bad = Read("1", "lava");
        assert(!bad.coat_forced && bad.coat_bad);
''',
         r'''        const Knobs bad = Read("1", "lava");
        assert(!bad.coat_forced && bad.coat_bad);
        // BB_FOOTPRINTS_GAIN (r111c): a number from 0.25 to 4; anything else is 1 and says so.
        assert(on.gain == 1.0f && !on.gain_bad);
        assert(Near(Read("1", nullptr, "2").gain, 2.0) && Near(Read("1", nullptr, " 0.25 ").gain, 0.25));
        assert(Near(Read("1", nullptr, "4").gain, 4.0) && !Read("1", nullptr, "4").gain_bad);
        assert(Read("1", nullptr, "").gain == 1.0f && !Read("1", nullptr, "").gain_bad);
        assert(Read("1", nullptr, "0.2").gain_bad && Read("1", nullptr, "5").gain_bad);
        assert(Read("1", nullptr, "x").gain_bad && Read("1", nullptr, "2x").gain_bad);
        assert(Read("1", nullptr, "nan").gain_bad && Read("1", nullptr, "inf").gain_bad);
        assert(Read("1", nullptr, "9").gain == 1.0f && Read("1", nullptr, "-1").gain == 1.0f);
        const Push gain_push{};
        assert(gain_push.gain == 1.0f && sizeof(Push) == 112);
'''),
    ],
    README: [
        ("(a sole about 0.26 m long)",
         "(a sole about 0.33 m long and 0.12 m wide)"),
        ("within 12 cm of the print's height",
         "within 16 cm of the print's height"),
        ("A wet print darkens the (linear) albedo by up to 50%, raises the gloss toward 0.62 and the specular colour toward f0 0.04 (never lowered)",
         "A wet print darkens the (linear) albedo by up to 60%, raises the gloss toward 0.8 and the specular colour toward f0 0.0625 (never lowered)"),
        ("a blood print takes the albedo toward a dark red (linear 0.05 0.006 0.005, about the graveyard pool's own colour) by up to 85%,",
         "a blood print takes the albedo toward a dark red whose red follows the stone's own red (0.75 times it, at least 0.04 and at most 0.10; green 0.006, blue 0.005, so it reads as a dark red patch on any stone and still counts as blood by the pickup rule) by up to 95%,"),
        ("raises the gloss toward 0.58 and the specular colour as wet",
         "raises the gloss toward 0.72 and the specular colour as wet"),
        ("with the disc's pixels in a recent frame.",
         "with the disc's pixels in a recent frame. The sole is drawn 1.25 times larger than its first numbers (0.33 x 0.12 m); at 1080p a print 3 to 4 m from the camera is 33 to 44 px wide, so it is small by nature: look at the ground between the camera and the hunter, not behind him. Lines of r111c: once at the start the gain and the look; once when the camera first lies within 12 m of the hunter (the first position line's camera can still hold its start values at the load); once when prints first lie on a pass's screen (how many, how far from the camera, how big the largest box is in pixels); and every 600 frames one line with the passes that had prints, the prints sent, their distance range and largest box, and the read-backs that showed print pixels (so a picture's absence of prints can be told from a pass that drew none)."),
        ("other text: as unset (the log says so) | unset |",
         "other text: as unset (the log says so) | unset |\n"
         "| `BB_FOOTPRINTS_GAIN` | Only with `BB_FOOTPRINTS` on. A number from 0.25 to 4: a factor on every print's weight (its strength times its shape times its facing, at most 1 after it), so the look can be turned up or down without a build; 2 doubles the weight of the faded and soft edges of a print and makes the middle of a strong one stay at the full change. Unset or empty: 1; other text or a number out of range: 1 (the log says so) | `1` |"),
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
                             "and 1; are r111 and r111b applied, and is this patch's own earlier version "
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
    rules, cpp, lay, comp, hdr = texts[RULES], texts[VKC], texts[LAYOUT], texts[COMP], texts[VKH]
    # The layout numbers, read from the layout, give what the README and the asserts say.
    nums = {m.group(1): float(m.group(2)) for m in re.finditer(r"#define (FOOTPRINTS_\w+) ([0-9.]+)\n", lay)}
    want = {"FOOTPRINTS_PRINT_BAND_M": 0.16, "FOOTPRINTS_SOLE_SCALE": 1.25, "FOOTPRINTS_WET_DARKEN": 0.6,
            "FOOTPRINTS_WET_GLOSS": 0.8, "FOOTPRINTS_WET_SPEC_ROOT": 0.25, "FOOTPRINTS_BLOOD_ALBEDO_R": 0.07,
            "FOOTPRINTS_BLOOD_ALBEDO_G": 0.006, "FOOTPRINTS_BLOOD_ALBEDO_B": 0.005,
            "FOOTPRINTS_BLOOD_RED_KEEP": 0.75, "FOOTPRINTS_BLOOD_RED_MIN": 0.04, "FOOTPRINTS_BLOOD_RED_MAX": 0.10,
            "FOOTPRINTS_BLOOD_COVER": 0.95, "FOOTPRINTS_BLOOD_GLOSS": 0.72}
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
    # The sole fits in a print's box at any heading, the band under its height.
    fore = (0.05 + 0.075) * nums["FOOTPRINTS_SOLE_SCALE"]
    heel = (0.09 + 0.048) * nums["FOOTPRINTS_SOLE_SCALE"]
    if not (fore < 0.2 and heel < 0.2 and nums["FOOTPRINTS_PRINT_BAND_M"] < 0.2):
        raise SystemExit("text check: the sole does not fit the 0.2 m print box")
    need(RULES, "PrintBoxUpM = 0.2f;")
    need(RULES, "PrintBoxAcrossM = 0.2f;")
    need(RULES, "FOOTPRINTS_PRINT_BAND_M == 0.16")
    # The shader: gain in the push block (replacing pad, the same 112 bytes), the scale, the red from the stone.
    need(COMP, "    float gain;       // BB_FOOTPRINTS_GAIN (r111c): a factor on every print's weight\n")
    need(COMP, "* face * grain * gain, 0.0, 1.0);\n", 3)
    need(COMP, "Sole(u / FOOTPRINTS_SOLE_SCALE, v / FOOTPRINTS_SOLE_SCALE)")
    need(COMP, "clamp(a.r * FOOTPRINTS_BLOOD_RED_KEEP, FOOTPRINTS_BLOOD_RED_MIN,")
    if "uint pad" in comp or "pad = 0" in rules:
        raise SystemExit("text check: the push block still has its pad word")
    need(RULES, "    float gain = 1.0f;                ///< BB_FOOTPRINTS_GAIN (r111c)\n")
    need(RULES, "static_assert(sizeof(Push) == 112);\n")
    need(VKC, "    push.gain = k.gain;\n")
    # The knob.
    need(RULES, 'std::getenv("BB_FOOTPRINTS_GAIN")')
    need(RULES, "GainMin = 0.25, GainMax = 4.0;")
    need(README, "`BB_FOOTPRINTS_GAIN`")
    # No leftover of the old look in the README.
    whole = texts[README]
    for gone in ("a sole about 0.26 m long", "within 12 cm of the print's height", "up to 50%, raises the gloss toward 0.62",
                 "(linear 0.05 0.006 0.005", "toward 0.58 and the specular"):
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
        if "r111c" in fmt:
            # (the gain line's longest %s text is longer than 12)
            extra = len(" (BB_FOOTPRINTS_GAIN is no number from 0.25 to 4: 1 used)") - 12 if "gain %.2f%s" in fmt else 0
            extra += len("outside the 1.5 to 6 m, 0.5 to 3 m above window: look at the ring") - 12 if "within 12 m: %s" in fmt else 0
            print("  r111c log line (wide %d): %s..." % (len(wide) + max(extra, 0), fmt[:50]))
            wide += "X" * max(extra, 0)
        if len(wide) > 300:
            raise SystemExit("text check: a log line may pass 300 characters (%d): %r" % (len(wide), fmt[:60]))
    # No tab, no CR in the edit texts.
    for path, eds in EDITS.items():
        for old, new in eds:
            if "\t" in new or "\r" in new:
                raise SystemExit("text check: an edit of %s has a tab or a CR" % path)
    # Every printf argument list of r111c's lines has as many conversions as arguments: counted by commas is
    # fragile, so the lines are kept short and the compiler's format check (BbReport::Printf) decides.


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use: python -I -X utf8 r111c_prints-visible.py check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R111C_ROOT)" % ROOT)
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
            tmp = full + ".r111ctmp"
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
        tmp = full + ".r111ctmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    print("reverted (%d files edited back)" % len(plan))


main()
