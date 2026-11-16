# r58_drawn-look-d2: step D2 of the drawn look's plan, the ink lines' second part. (A) Creases:
# ink on inner edges, where two surfaces meet at an angle (a box's corner, a wall's foot), found
# from the depth alone. (B) A limit on ink per area at High quality, so busy places (foliage,
# grates, railings) do not turn black. (C) Distance fades for both kinds of line. (D) The
# quality knob graphics_drawn_look_quality (0 low, 1 high, default high) becomes real, with a
# menu row "Drawn look ink quality" Low/High in all eight tables. Nothing of D3 to D5. Off by
# default as the whole look is: a player who has not switched the look on sees no change.
# check|apply|revert (revert restores byte for byte). On top of <tree> with
# r55_drawn-look-lines applied. The tree: the one the environment variable R58_ROOT names;
# without it the current directory. Nothing is changed in place: every new text is written beside
# its target and moved over it, and a failure puts back what was already moved. Files keep their
# line ends (CRLF). No new files.
#
# WHY. r55 drew silhouettes only: a box's corner, a wall's foot, a step seen from above got no
# line, and a railing seen along, a grate or a bush turned into a dark smear (the thin guard
# halves one thin thing's line, but a field of them is still all ink). Far away the lines need to
# fade before they become noise. The quality key was saved since r45 and read by nothing.
#
# WHAT.
#  1. drawn_look_params.h: Quality (Low 0, High 1) and Knobs::quality (High); Passes::ink_limit
#     (the ink at High); InkTune, the ink's numbers, each with an environment variable
#     (InkTuneNames, TuneValueOf, TunePairOf, InkTuneOf): read once, never saved, a value that is
#     no number or a pair that does not rise is the default, values are clamped; HalfBits and
#     HalfPair (floats to half floats, round to nearest even); MakeInk carries the tune as half
#     floats, two a word, in words no ink pass otherwise reads (cell_bold, back_turn, back_shift;
#     cell_fine stays free for D4's rim light) and, as a float in back_shift.z, DensityLevel (the
#     edges image's level the limit per area reads: 1.5 levels under a box of 16 pixels of a
#     1080-line scene); EdgeLevels (how many levels the edges image has: down to the one above
#     DensityLevel); EdgeBytesPerPixel (what the budget is asked for).
#  2. host_shaders/paint_ink.comp, four variants (CMakeLists.txt): Low (no define, one pass:
#     silhouettes along the x and y axes, creases, every line times 0.7); EDGES (High: each
#     pixel's lines as drawn (with their fades and weights, before ink_world) into the edges
#     image, RGBA8: r the silhouette before the thin guard, g the crease, b the silhouette; four
#     axes as r55); DOWN (one level of it from the one above: around each texel a tent two of its
#     texels wide, read texel by texel, so every texel above counts the same also where a side
#     is odd); APPLY (the lines into the scene colour, times 1 - smoothstep(0.20, 0.45, r + g),
#     r + g read at DensityLevel with a cubic B-spline (four linear reads) on each of the two
#     nearest levels: a weighting about as wide as a 16-pixel box that hardly changes with where
#     a place lies against the texels). The depth around a group of 8x8 pixels is read once into
#     shared memory (7 pixels around it), and when a pixel of the group looks for creases, the
#     face normals of the pixels within 3 of it once more (each was made about five times).
#     Creases: the face normal of the pixel and of each 4-neighbour out to
#     the crease's half width (1 at 1080 lines), each from the depth on the side where the raw
#     depth goes on in a straight line (a plane's does across the screen), so a pixel right at the
#     crease keeps its own face's normal; a crease from 30 degrees of bend, fully from 50
#     (1 - smoothstep(cos 50, cos 30, n_p . n_q)); not where the neighbour is off the pixel's plane
#     by the silhouettes' gap on either side; a line 1 pixel of a 1080-line scene wide over both
#     faces (it narrows with distance as the silhouettes do) at 0.5 of the silhouettes' weight.
#     Never the G-buffer's normals (their bumps would line every brick joint). Weight =
#     max(silhouette x line fade x the r55 far opacity, crease x 0.5 x crease fade) x ink_world x
#     (the limit per area at High, 0.7 at Low). A crease does not take the far opacity: its
#     pixels' cover already narrows with distance. Line fade 40..120 m (r55's), crease fade
#     20..50 m. Two faces that turn by 30 degrees or less get no crease (a round column of 12 or
#     more sides).
#  3. vk_drawn_look.cpp/.h: three more pipelines in Ready() (and RGBA8 storage asked for); the
#     edges image (EdgeLevels levels, not all), made only while the knobs ask for High and let go
#     when they ask for Low or the look goes off; without video memory for it the frame's lines are
#     drawn at Low and the log says so once a size; the ink crumb records Low's pass, or EDGES,
#     DOWN once a level and APPLY (one profile row, "Lighting: drawn look ink", as r55). The
#     quality read from the settings each painted frame; the tune once in the constructor, printed
#     once when any variable is set. The "on at" line names the quality; the 600-frame line counts
#     the frames with the limit and those at Low for want of memory. The quality's values and
#     default tied to BbSettings' by a static_assert.
#  4. bbport_settings.h/.cpp: DrawnLookQualityLow/High/Default; the key parsed strictly: a whole
#     number clamped to 0..1, anything else High with a note (atoi made a word 0, Low). Saved
#     clamped to DrawnLookQualityLow..High.
#  5. bbport_drawn_look_texts.h, bbport_overlay.cpp, bbport_menu_i18n.cpp: the switch's and the
#     ink row's hints say what the lines now do; a combo row "Drawn look ink quality" (Low, High)
#     under the ink row, disabled as the other rows while the look is off or cannot run; its texts
#     in all eight tables (the Chinese checked against LanternMenuSC-glyphs.txt). The quality
#     hint names the axes, the memory and the fall back to Low. The bare "Low" and "High" keys
#     carry a comment: one map serves every row.
#  6. Tests. test_drawn_look_rules.cpp: the quality default, PassesFor's ink_limit, MakeInk's
#     words and the tune unpacked, HalfBits (known values, ties, subnormals, round trip), the
#     tune's parsing and clamps (every variable above and below its range), a quality of 5 or -1
#     as High, DensityLevel, EdgeLevels. test_drawn_look.cpp (GPU): a box in the scene (Scene
#     flag with_box, off by default); High recorded as the renderer records it; creases on the
#     box's corners and foot (High and Low), none on its faces nor inside the round column, none
#     from bumpy G-buffer normals; Low at 0.7 of High; the crease weight 0 and both fades from the
#     tune; no creases on the box from about 50 m, its outline kept; a field of 1-pixel spikes
#     under weight 0.3 at High while a lone spike keeps its half-weight line; strips of 1-pixel
#     spikes, rows and columns, moved a pixel at a time across the texel grid (rows 500-575 at
#     1920x1080, where a level has an odd side of 135, and at 960x540): the limit's factor a few
#     pixels inside the edge varies by under 0.05 (the draft's shaders: 0.61 to 0.78); posts 3
#     pixels wide every 12 keep at least half of their weight under the limit. All r55 ink checks
#     now run at High. test_settings.cpp: a word and a fraction as the quality are High.
#     test_effect_pipelines.cpp: the three pipelines (31 in all).
#  7. README.md: the rows of graphics_drawn_look, _ink_world and _quality; the environment
#     paragraph.
#
# THE THIN GUARD (r55) is kept, as a complement: one thin thing (a lone branch) keeps its half
# weight, and the limit per area counts the silhouette before the guard, so a field of thin
# things counts as fully lined and is held back by the limit, not by the guard.
#
# SETTINGS AND KNOBS. graphics_drawn_look_quality 0 low or 1 high, default 1, live, menu row
# "Drawn look ink quality". Environment only, read once, never saved (default, range):
# BB_DRAWN_LOOK_CREASE_ANGLE=30,50 (5..85 degrees), BB_DRAWN_LOOK_CREASE_WIDTH=1 (0.25..3 pixels
# of a 1080-line scene), BB_DRAWN_LOOK_CREASE_WEIGHT=0.5 (0..1), BB_DRAWN_LOOK_CREASE_FADE=20,50
# (1..1000 m), BB_DRAWN_LOOK_LINE_FADE=40,120 (1..1000 m), BB_DRAWN_LOOK_DENSITY=0.20,0.45 (0..2),
# BB_DRAWN_LOOK_DENSITY_SIZE=16 (4..64 pixels of a 1080-line scene), BB_DRAWN_LOOK_LOW_FACTOR=0.7
# (0..1).
#
# COST, an estimate (nothing timed: no benchmarks while the machine runs captures). The plan
# gave D2 +0.04 to 0.08 ms at a 1920x1080 scene on an RTX 4090. This estimate is above it: at
# 1920x1080, Low about +0.02 to 0.04 ms over r55's pass (the face normals, about 3 a pixel from
# shared memory, and the crease compares) and High about +0.05 to 0.10 ms over Low (one more
# full-size pass writing 4 bytes a pixel, 3 small level passes reading up to 25 texels a texel,
# the apply pass with 8 linear reads, 5 more compute barriers), so D2 at High about +0.07 to
# 0.14 ms; at 3840x2160 about four times that. Memory at High: an RGBA8 image of about 5.3
# bytes a scene pixel with its levels (11 MB at 1920x1080, 44 MB at 3840x2160); none at Low.
#
# REVIEW FIXES (two adversarial reviews of the draft). DOWN read one linear tap at a texel's
# centre: where a level's side is odd (135 -> 67 at 1080 lines) whole rows counted twice or not
# at all, and the limit per area popped along the middle rows of the screen; now a tent over
# the true footprint. APPLY read one linear tap of a box-filtered level: its weighting changed
# with the grid (16-pixel steps that crawl); now a B-spline on a tent pyramid. The density
# counted lines at full strength: a far facade's faint lines held back a near pillar's outline;
# now it counts them as drawn. Creases took the far opacity on top of their narrowing cover and
# were all but gone from about 12 m; now only their own fade ends them. The face normals are
# shared within a group.
#
# NOT DONE: D3 to D5 (heavier ink on characters, the rim light, painted shadow edges); ink on
# frames painted right before the upscaler (as r55); no cost measured. r55's viewNormal falls back
# to the view direction for surfaces nearer than about 1.2 m at 1080 lines (an absolute threshold
# on the cross product), which may misplace silhouettes on steep near surfaces: left as it is.
#
# HOW TO TEST IN THE GAME. graphics_ao_quality=1; the look on, strength 0, ink lines 0.35 and
# 1.0; quality Low and High; BB_DRAWN_LOOK_VIEW=3 (the ink page); a busy place (foliage, a
# railing seen along, a grate); a far view (past 50 m and past 120 m); BB_GPU_PROFILE=1: the row
# "Lighting: drawn look ink" at Low and at High.
#
# NOT CHANGED: anything outside the drawn look (the lamp shadows, the sun shafts, the wind),
# paint_strokes.comp, paint_common.glsl, vk_temporal_upscaler.cpp, build.sh.

import os
import re
import sys

ROOT = os.environ.get("R58_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
VC = G + "shadps4/video_core/"
R = VC + "renderer_vulkan/"
HS = VC + "host_shaders/"
S = G + "shim/"
TESTS = E + "tests/"
GLYPHS = G + "third_party/fonts/LanternMenuSC-glyphs.txt"

TMP = ".r58tmp"  # a new text waits under this name beside its target (main)

# Other rounds' files: this one must not touch them.
FOREIGN = ("point_shadow_ray.comp", "lamp_shadow_tune.h", "vk_point_shadow.h", "vk_point_shadow.cpp",
           "test_lamp_shadow_tune.cpp", "test_rt_shadows.cpp", "vk_rt_shadow.h", "vk_rt_shadow.cpp",
           "emit_spirv_special.cpp", "runtime_info.h", "volumetric_light.comp", "point_volumetric.comp",
           "paint_strokes.comp", "paint_common.glsl", "vk_temporal_upscaler.cpp", "build.sh")


def foreign(path):
    name = path.rsplit("/", 1)[-1]
    return name in FOREIGN or "wind" in name or (path.startswith(HS) and name.startswith("rt_"))


def B(s):
    """A block written from the line after the opening quotes."""
    return s[1:] if s.startswith("\n") else s


NEW_FILES = {}

# Each file's changes, in order: (the text as r55 left it, the text after this round). Made from
# the difference of the two trees, each with the context that makes it unique.
EDITS = {}

EDITS[R + "drawn_look_params.h"] = [
    (B(r"""
#include <array>
#include <cmath>
"""),
     B(r"""
#include <array>
#include <bit>
#include <cmath>
""")),
    (B(r"""
/// takes the same block, three of its floats with other meanings (MakeInk).
"""),
     B(r"""
/// takes the same block, three of its floats with other meanings and (r58_drawn-look-d2) the
/// ink's numbers in seven words it does not otherwise read (MakeInk).
""")),
    (B(r"""

/// What the settings give a frame (BbSettings: the graphics_drawn_look_* keys).
"""),
     B(r"""

/// (r58_drawn-look-d2) graphics_drawn_look_quality, for the ink lines (paint_ink.comp). High:
/// silhouettes along the x, y and both diagonal axes, and the limit of ink per area (an edges
/// image, its levels and a last pass). Low: silhouettes along the x and y axes only, no limit
/// per area: every line at InkTune::low_factor of its weight instead. Creases with both.
enum Quality : int { QualityLow = 0, QualityHigh = 1 };

/// What the settings give a frame (BbSettings: the graphics_drawn_look_* keys).
""")),
    (B(r"""
    int view = ViewOff;
};
"""),
     B(r"""
    int view = ViewOff;
    int quality = QualityHigh; ///< (r58_drawn-look-d2) a Quality
};
""")),
    (B(r"""
    bool ink = false;     ///< paint_ink.comp, last
};
"""),
     B(r"""
    bool ink = false;     ///< paint_ink.comp, last
    /// (r58_drawn-look-d2) with the ink: High quality, the edges image, its levels and the limit
    /// per area (paint_ink.comp EDGES, DOWN, APPLY) in place of Low's one pass.
    bool ink_limit = false;
};
""")),
    (B(r"""
/// lines would be drawn over them where the surfaces behind have edges.
"""),
     B(r"""
/// lines would be drawn over them where the surfaces behind have edges. (r58_drawn-look-d2) The
/// ink at High quality with its limit per area; a quality other than Low is High, the default.
""")),
    (B(r"""
    return {.strokes = strokes,
            .lock = strokes && view == ViewOff,
            .ink = !before_upscaler && (knobs.ink_world > 0.0f || page)};
"""),
     B(r"""
    const bool ink = !before_upscaler && (knobs.ink_world > 0.0f || page);
    return {.strokes = strokes,
            .lock = strokes && view == ViewOff,
            .ink = ink,
            .ink_limit = ink && knobs.quality != QualityLow};
""")),
    (B(r"""
/// The ink pass's block: the frame's (Make) with three floats given other meanings
/// (paint_ink.comp's INK_WORLD, INK_CHARS, LINE_SCALE). The ink page (view 3) draws every line
/// at weight 1.
constexpr Params MakeInk(Params look, float ink_world, float outlines, float line_scale) {
"""),
     B(r"""
/// (r58_drawn-look-d2) The ink lines' numbers (paint_ink.comp), starting values to be judged in
/// the game. Each has an environment variable that sets another for tuning (InkTuneOf), read
/// once at the start and never saved; a value that is no number, or a pair that is not two
/// numbers rising, keeps the default, and a number out of its range is clamped.
struct InkTune {
    /// A bend between two faces is a crease from the first angle (degrees), fully from the
    /// second. BB_DRAWN_LOOK_CREASE_ANGLE=from,full (5..85). At 30, faces that turn by 30
    /// degrees or less get none: a round column of 12 or more sides is not lined facet by facet.
    std::array<float, 2> crease_deg{30.0f, 50.0f};
    /// A crease line's width over both faces, pixels of a 1080-line scene near the camera (it
    /// narrows with distance as the silhouettes do). BB_DRAWN_LOOK_CREASE_WIDTH (0.25..3).
    float crease_px = 1.0f;
    /// A crease's weight, a share of the silhouettes' (ink_world). BB_DRAWN_LOOK_CREASE_WEIGHT
    /// (0..1; 0: no creases).
    float crease_weight = 0.5f;
    /// Creases fade out between these distances (metres). BB_DRAWN_LOOK_CREASE_FADE=from,to
    /// (1..1000).
    std::array<float, 2> crease_fade_m{20.0f, 50.0f};
    /// Silhouettes fade out between these distances (r55's). BB_DRAWN_LOOK_LINE_FADE=from,to
    /// (1..1000).
    std::array<float, 2> line_fade_m{40.0f, 120.0f};
    /// The limit per area (High): where lines cover this share of the place around a pixel
    /// (silhouettes before the thin guard plus creases, each as dark as it is drawn), the lines
    /// there begin to fade; from the second share there are none. BB_DRAWN_LOOK_DENSITY=from,to
    /// (0..2).
    std::array<float, 2> density{0.20f, 0.45f};
    /// The size of that place: a smooth weighting about as wide as a box this many pixels of a
    /// 1080-line scene across (DensityLevel). BB_DRAWN_LOOK_DENSITY_SIZE (4..64).
    float density_px = 16.0f;
    /// Low quality: every line at this share of its weight (no limit per area).
    /// BB_DRAWN_LOOK_LOW_FACTOR (0..1).
    float low_factor = 0.7f;
};

/// The environment variables of InkTune, in the order of its fields.
inline constexpr const char* InkTuneNames[] = {
    "BB_DRAWN_LOOK_CREASE_ANGLE", "BB_DRAWN_LOOK_CREASE_WIDTH", "BB_DRAWN_LOOK_CREASE_WEIGHT",
    "BB_DRAWN_LOOK_CREASE_FADE",  "BB_DRAWN_LOOK_LINE_FADE",    "BB_DRAWN_LOOK_DENSITY",
    "BB_DRAWN_LOOK_DENSITY_SIZE", "BB_DRAWN_LOOK_LOW_FACTOR"};

/// Skips spaces and tabs.
inline const char* PastBlanks(const char* text) {
    while (*text == ' ' || *text == '\t') {
        ++text;
    }
    return text;
}

/// A number alone in the text (blanks around it allowed), clamped to lo..hi; `fallback` without
/// one.
inline float TuneValueOf(const char* text, float fallback, float lo, float hi) {
    if (!text) {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || *PastBlanks(end) != '\0' || !std::isfinite(value)) {
        return fallback;
    }
    return std::clamp(value, lo, hi);
}

/// "a,b": two numbers, each clamped to lo..hi, a below b after that; `fallback` otherwise.
inline std::array<float, 2> TunePairOf(const char* text, std::array<float, 2> fallback, float lo,
                                       float hi) {
    if (!text) {
        return fallback;
    }
    char* end = nullptr;
    const float a = std::strtof(text, &end);
    if (end == text || *PastBlanks(end) != ',' || !std::isfinite(a)) {
        return fallback;
    }
    const char* second = PastBlanks(end) + 1;
    const float b = std::strtof(second, &end);
    if (end == second || *PastBlanks(end) != '\0' || !std::isfinite(b)) {
        return fallback;
    }
    const std::array<float, 2> pair{std::clamp(a, lo, hi), std::clamp(b, lo, hi)};
    return pair[0] < pair[1] ? pair : fallback;
}

/// InkTune with what the environment sets (`get`: std::getenv, or a test's stand-in).
template <class Get>
InkTune InkTuneOf(Get get) {
    const InkTune d{};
    InkTune tune;
    tune.crease_deg = TunePairOf(get(InkTuneNames[0]), d.crease_deg, 5.0f, 85.0f);
    tune.crease_px = TuneValueOf(get(InkTuneNames[1]), d.crease_px, 0.25f, 3.0f);
    tune.crease_weight = TuneValueOf(get(InkTuneNames[2]), d.crease_weight, 0.0f, 1.0f);
    tune.crease_fade_m = TunePairOf(get(InkTuneNames[3]), d.crease_fade_m, 1.0f, 1000.0f);
    tune.line_fade_m = TunePairOf(get(InkTuneNames[4]), d.line_fade_m, 1.0f, 1000.0f);
    tune.density = TunePairOf(get(InkTuneNames[5]), d.density, 0.0f, 2.0f);
    tune.density_px = TuneValueOf(get(InkTuneNames[6]), d.density_px, 4.0f, 64.0f);
    tune.low_factor = TuneValueOf(get(InkTuneNames[7]), d.low_factor, 0.0f, 1.0f);
    return tune;
}

/// A float as the bits of a half float (IEEE 754 binary16), rounded to the nearest, ties to
/// even; past the largest half (65504) the largest, a number that is none 0. For the ink's
/// numbers, which paint_ink.comp unpacks with unpackHalf2x16.
constexpr std::uint16_t HalfBits(float value) {
    if (!(value == value)) {
        return 0;
    }
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(value);
    const std::uint32_t sign = (bits >> 16) & 0x8000u;
    const std::uint32_t magnitude = bits & 0x7fffffffu;
    if (magnitude >= 0x477ff000u) { // 65520 and more would round past the largest half
        return std::uint16_t(sign | 0x7bffu);
    }
    if (magnitude < 0x38800000u) { // under 2^-14: a subnormal half, or 0
        const float scaled = std::bit_cast<float>(magnitude) * 16777216.0f; // units of 2^-24
        const auto whole = std::uint32_t(scaled);
        const float rest = scaled - float(whole);
        const std::uint32_t rounded =
            whole + ((rest > 0.5f || (rest == 0.5f && (whole & 1u))) ? 1u : 0u);
        return std::uint16_t(sign | rounded);
    }
    const std::uint32_t exponent = (magnitude >> 23) - 112u; // 127 - 15
    const std::uint32_t mantissa = magnitude & 0x7fffffu;
    std::uint32_t half = (exponent << 10) | (mantissa >> 13);
    const std::uint32_t dropped = mantissa & 0x1fffu;
    if (dropped > 0x1000u || (dropped == 0x1000u && (half & 1u))) {
        ++half; // a carry into the exponent is the next power of two, as it should be
    }
    return std::uint16_t(sign | half);
}

/// (r58_drawn-look-d2) The level of the edges image whose read gives the limit per area its
/// place (paint_ink.comp placeAt) at a scene `height` lines high: a box of `density_px` pixels
/// of a 1080-line scene is 2^n pixels of this one, and each level is a tent two of its texels
/// wide over the one above, read with a cubic B-spline: that weighting is about as wide as such
/// a box DensityLevelBelow levels under n (a model of it along one axis gives the box's spread
/// within 5% at 540 to 2160 lines). 0 at least.
inline constexpr double DensityLevelBelow = 1.5;
inline float DensityLevel(std::uint32_t height, float density_px) {
    const double level =
        std::log2(double(density_px) * double(height) / 1080.0) - DensityLevelBelow;
    return level > 0.0 ? float(level) : 0.0f;
}

/// Two numbers as one word of the block: `low` in the low 16 bits (GLSL unpackHalf2x16's x).
constexpr float HalfPair(float low, float high) {
    return std::bit_cast<float>(std::uint32_t(HalfBits(low)) | std::uint32_t(HalfBits(high)) << 16);
}

/// The ink pass's block: the frame's (Make) with three floats given other meanings
/// (paint_ink.comp's INK_WORLD, INK_CHARS, LINE_SCALE). The ink page (view 3) draws every line
/// at weight 1. (r58_drawn-look-d2) The ink's numbers go as half floats, two a word, into words
/// of the strokes' cells and of the frame before's camera, which no ink pass reads: cell_bold
/// the crease angles' cosines (full, from); back_turn the crease width and weight, the crease
/// fade, the silhouettes' fade; back_shift the limit per area, its place's size (which the
/// shader does not read: it takes the level below) and Low's factor, and as a float the level
/// the limit per area reads at this scene's height (DensityLevel). cell_fine stays the strokes'
/// (the plan's rim light, D4, is to go there).
inline Params MakeInk(Params look, float ink_world, float outlines, float line_scale,
                      const InkTune& tune = {}) {
""")),
    (B(r"""
    return look;
}
"""),
     B(r"""
    constexpr double Degree = 3.14159265358979 / 180.0;
    look.cell_bold = HalfPair(float(std::cos(tune.crease_deg[1] * Degree)),
                              float(std::cos(tune.crease_deg[0] * Degree)));
    look.back_turn = {HalfPair(tune.crease_px, tune.crease_weight),
                      HalfPair(tune.crease_fade_m[0], tune.crease_fade_m[1]),
                      HalfPair(tune.line_fade_m[0], tune.line_fade_m[1])};
    look.back_shift = {HalfPair(tune.density[0], tune.density[1]),
                       HalfPair(tune.density_px, tune.low_factor),
                       DensityLevel(std::uint32_t(look.size[1]), tune.density_px)};
    return look;
}

/// (r58_drawn-look-d2) How many levels the edges image of a scene this large has (High): down
/// to the level above DensityLevel, for the read between two levels; never more than an image
/// of that size has, never fewer than one.
inline std::uint32_t EdgeLevels(std::uint32_t width, std::uint32_t height, float density_px) {
    const auto all = std::uint32_t(std::bit_width(std::max({width, height, 1u})));
    const auto below = std::uint32_t(std::floor(DensityLevel(height, density_px)));
    return std::max(std::min(below + 2u, all), 1u);
}
/// Bytes of video memory the edges image takes a scene pixel (RGBA8, its levels at most a third
/// more), rounded up: what DrawnLook asks the budget for.
inline constexpr std::uint32_t EdgeBytesPerPixel = 6;
""")),
]

EDITS[HS + "paint_ink.comp"] = [
    (B(r"""
// bbport (r55_drawn-look-lines): the drawn look's ink lines. Recorded by
"""),
     B(r"""
// bbport (r55_drawn-look-lines, r58_drawn-look-d2): the drawn look's ink lines. Recorded by
""")),
    (B(r"""
// A pixel gets ink where its surface stands in front of what lies behind it: taps along 4 axes,
// both ways, out to a pixel past the line's width, read the depth, and a tap counts when it is
// farther than the pixel's own plane, carried on to the tap, says it should be (by GAP of the
// pixel's depth). Only the depth decides, never the colour: a texture's cracks and joints get no
// line, and a cobble lip of 2 cm at 3 m is under GAP. The line lies on the near side, on the
// front surface's own pixels. Something that lies in front of what is behind it on both sides of
// an axis within those taps (narrower than about twice the line: a railing, a branch) gets half
// the weight along that axis. A line pixel's rgb is multiplied by mix(1, f, weight), with
// f = min(INK_OWN x its brightness, INK_KEY x the frame's key) / its brightness: one factor for
// the three channels, so its hue stays, and a scene twice as bright gets the same lines. What
// glows (the rule of paint_strokes.comp's keepOwn) gets no ink.
//
// The line's width is LINE_PX_ENV pixels of a 1080-line scene near the camera, narrowing with
// distance; how dark it is far away (`opacity`) is taken from that width in 1080-line pixels, so
// where lines show does not depend on the render size or on BB_DRAWN_LOOK_LINE. In this scene's
// pixels the width is times size.y / 1080 and LINE_SCALE; a line narrower than one pixel is
// drawn one pixel wide with its weight times its width.
//
// The block's words are the other passes' (paint_common.glsl); DrawnLookParams::MakeInk
// (drawn_look_params.h) gives three of its floats the meanings below.
"""),
     B(r"""
// Silhouettes (r55). A pixel gets ink where its surface stands in front of what lies behind it:
// taps along the axes, both ways, out to a pixel past the line's width, read the depth, and a
// tap counts when it is farther than the pixel's own plane, carried on to the tap, says it
// should be (by GAP of the pixel's depth). Only the depth decides, never the colour: a texture's
// cracks and joints get no line, and a cobble lip of 2 cm at 3 m is under GAP. The line lies on
// the near side, on the front surface's own pixels. Something that lies in front of what is
// behind it on both sides of an axis within those taps (narrower than about twice the line: a
// railing, a branch) gets half the weight along that axis (the thin guard).
//
// Creases (r58). A pixel also gets ink where its surface bends: the normal of its face and that
// of a neighbour along the x or y axis differ by CREASE_DEG.x or more (fully from CREASE_DEG.y),
// and the neighbour lies on the pixel's plane carried on (within GAP, on either side): a box's
// corner, a wall's foot on the floor. The normals come from the depth alone (never the
// G-buffer's normals, which carry the normal maps' bumps: cobble and brick joints would all be
// lined). Each normal is its own face's: of the two neighbours on an axis it takes the one on
// whose side the depth goes on in a straight line, as a plane's raw depth does across the
// screen, so a pixel right beside the crease does not lean towards the other face. A crease
// line lies on both faces, CREASE_PX wide in all, at CREASE_WEIGHT of the silhouettes' weight.
// Two faces that turn by CREASE_DEG.x or less get none: at 30 degrees, a round column of 12 or
// more sides is not lined facet by facet (one of 8 sides, 45 degrees a facet, would be).
//
// A line pixel's rgb is multiplied by mix(1, f, weight), with f = min(INK_OWN x its brightness,
// INK_KEY x the frame's key) / its brightness: one factor for the three channels, so its hue
// stays, and a scene twice as bright gets the same lines. What glows (the rule of
// paint_strokes.comp's keepOwn) gets no ink.
//
// The line's width is LINE_PX_ENV pixels of a 1080-line scene near the camera, narrowing with
// distance; how dark a silhouette is far away (`opacity`) is taken from that width in 1080-line
// pixels, so where lines show does not depend on the render size or on BB_DRAWN_LOOK_LINE. In
// this scene's pixels the width is times size.y / 1080 and LINE_SCALE; a line narrower than one
// pixel is drawn one pixel wide with its weight times its width. Silhouettes fade out between
// LINE_FADE_M, creases between CREASE_FADE_M (nearer: a crease is a small thing far away). A
// crease does not take `opacity`: its pixels' share of its narrowing width already thins it with
// distance, and with both it would be all but gone from about 12 m, before its own fade began.
//
// Four passes of this file (r58; graphics_drawn_look_quality):
//   (neither)  Low: in one pass, the lines found and drawn; silhouettes along the x and y axes
//              only; every line at LOW_FACTOR of its weight, no limit per area.
//   EDGES      High: each pixel's lines as drawn (`Drawn`: with their fades and weights, before
//              INK_WORLD) into the edges image's level 0 (rgba8): r the silhouette line before
//              the thin guard, g the crease line, b the silhouette line; silhouettes along the
//              x, y and both diagonal axes.
//   DOWN       High: one more level of the edges image: around each of its texels a tent as wide
//              as two of them over the level above (`down`).
//   APPLY      High: the lines into the scene colour, each times the limit per area: where r + g
//              around the pixel (`placeAt`: a smooth weighting about as wide as a box of
//              DENSITY_PX pixels of a 1080-line scene) is DENSITY.x or more (lines over that
//              share of the place), the lines there fade, and from DENSITY.y there are none. A
//              busy place (foliage, a grate, a railing seen along) does not turn dark; one thin
//              branch keeps its half-weight line (the thin guard), as its place is not busy. r
//              counts the line before the thin guard, so a field of thin things counts as fully
//              lined; both count a line as dark as it is drawn, so a far facade's faint lines do
//              not hold back the lines of what stands before it.
//
// The block's words are the other passes' (paint_common.glsl); DrawnLookParams::MakeInk
// (drawn_look_params.h) gives three of its floats the meanings below, and carries the ink's
// numbers (DrawnLookParams::InkTune, BB_DRAWN_LOOK_* for tuning) as half floats, two a word, in
// words no ink pass otherwise reads, and the edges image's level the limit per area reads
// (DrawnLookParams::DensityLevel) as a float.
""")),
    (B(r"""

#define INK_WORLD strength    // graphics_drawn_look_ink_world, 0..1 (1 in test view 3)
"""),
     B(r"""

#if defined(DOWN)

layout(binding = 0) uniform sampler2D from_tex; // a level of the edges image, read texel by texel
layout(binding = 1, rgba8) uniform writeonly image2D to_img;

// The level above's texels that one texel of this level weighs, along one axis: up to 7 (a
// side of 3 made into 1 is the widest tent, 3 texels each way).
const int DOWN_MOST = 7;

// The tent's weights along one axis for the texel at `at` of a level `ratio` times smaller
// than the level above (exactly 2, or 2 + 1/n where the side above is odd): 1 at the texel's
// centre, 0 at a texel of this level away. Such tents add up to 1 at every place, so every
// texel above counts the same in all, an odd side's included (a linear read at the texel's
// centre, as before, counted some rows of a side of 135 twice and others not at all); and the
// level is smooth enough that the read between its texels (placeAt) gives nearly the same
// wherever a place lies against the texel grid. Returns the level above's first texel weighed
// (one outside that level is read as the nearest inside, as a clamped read takes it).
int tent(int at, float ratio, out float weights[DOWN_MOST]) {
    const float centre = (float(at) + 0.5) * ratio;
    const int first = int(ceil(centre - ratio - 0.5));
    float total = 0.0;
    for (int k = 0; k < DOWN_MOST; ++k) {
        weights[k] = max(0.0, 1.0 - abs(float(first + k) + 0.5 - centre) / ratio);
        total += weights[k];
    }
    for (int k = 0; k < DOWN_MOST; ++k) {
        weights[k] /= total;
    }
    return first;
}

void main() {
    const ivec2 texel = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 to_size = imageSize(to_img);
    if (any(greaterThanEqual(texel, to_size))) {
        return;
    }
    const ivec2 from_size = textureSize(from_tex, 0);
    const vec2 ratio = vec2(from_size) / vec2(to_size);
    float wx[DOWN_MOST], wy[DOWN_MOST];
    const int x0 = tent(texel.x, ratio.x, wx);
    const int y0 = tent(texel.y, ratio.y, wy);
    vec4 sum = vec4(0.0);
    for (int j = 0; j < DOWN_MOST; ++j) {
        if (wy[j] <= 0.0) {
            continue;
        }
        vec4 row = vec4(0.0);
        for (int i = 0; i < DOWN_MOST; ++i) {
            if (wx[i] > 0.0) {
                const ivec2 at = clamp(ivec2(x0 + i, y0 + j), ivec2(0), from_size - 1);
                row += wx[i] * texelFetch(from_tex, at, 0);
            }
        }
        sum += wy[j] * row;
    }
    imageStore(to_img, texel, sum);
}

#else

#define INK_WORLD strength    // graphics_drawn_look_ink_world, 0..1 (1 in test view 3)
""")),
    (B(r"""
// paint_prep.comp's copy and its smaller levels (rgb the scene before the strokes); its last
// level, one texel, holds the frame's key (paint_key.comp). Linear between texels and levels.
"""),
     B(r"""
// (r58) The ink's numbers, two half floats a word (DrawnLookParams::MakeInk, InkTune).
vec2 tuneOf(float word) {
    return unpackHalf2x16(floatBitsToUint(word));
}
// x: the cosine of the angle from which a bend is fully a crease, y: of the angle it starts at.
#define CREASE_COS tuneOf(cell_bold)
#define CREASE_PX tuneOf(back_turn.x).x     // a crease line's width, both faces, 1080-line pixels
#define CREASE_WEIGHT tuneOf(back_turn.x).y // a crease's weight, a share of the silhouettes'
#define CREASE_FADE_M tuneOf(back_turn.y)   // creases fade out between these distances (metres)
#define LINE_FADE_M tuneOf(back_turn.z)     // silhouettes fade out between these distances
#define DENSITY tuneOf(back_shift.x)        // the limit per area: from, none from (r + g)
#define LOW_FACTOR tuneOf(back_shift.y).y   // Low: every line at this share of its weight
// The edges image's level the limit per area reads (DrawnLookParams::DensityLevel: its place,
// DENSITY_PX pixels of a 1080-line scene, at this render size), a float.
#define DENSITY_LEVEL back_shift.z

// paint_prep.comp's copy and its smaller levels (rgb the scene before the strokes); its last
// level, one texel, holds the frame's key (paint_key.comp). Linear between texels and levels.
#if defined(EDGES)
layout(binding = 0) uniform texture2D depth_tex; // depth 0..1 (D3D projection), 1: sky
layout(binding = 1, rgba8) uniform writeonly image2D edges_img;
#else
""")),
    (B(r"""

// A tap counts from the first share of the pixel's depth beyond its plane, fully from the
// second.
"""),
     B(r"""
#if defined(APPLY)
layout(binding = 3) uniform sampler2D edges_tex; // EDGES' and DOWN's levels (linear, clamped)
#endif
#endif

// A tap counts from the first share of the pixel's depth beyond its plane, fully from the
// second. (r58) A crease's neighbour off the plane by as much, on either side, is no crease.
""")),
    (B(r"""
const float LINE_NEAR_M = 4.0;
// Between these distances (metres) the lines fade out.
const vec2 ENV_FADE_M = vec2(40.0, 120.0);
// A fully inked pixel: its own brightness times INK_OWN, or the key times INK_KEY where that is
"""),
     B(r"""
const float LINE_NEAR_M = 4.0;
// A fully inked pixel: its own brightness times INK_OWN, or the key times INK_KEY where that is
""")),
    (B(r"""

float depthAt(ivec2 p) {
    return texelFetch(depth_tex, p, 0).r;
}

// The view position seen at pixel p (sky as very far).
"""),
     B(r"""

// How wide the line at view distance d is, in pixels of a 1080-line scene at line scale 1: from
// LINE_NEAR_M on it narrows, to half at four times that distance.
float narrowedAt(float d) {
    return clamp(sqrt(LINE_NEAR_M / d), 0.5, 1.0);
}

// How dark a line at view distance d can be: under one pixel of a 1080-line scene the line
// fades (none at 0.6): from about 9 m on at the near width, to a third from 16 m.
float opacityAt(float d) {
    return smoothstep(0.6, 1.0, LINE_PX_ENV * narrowedAt(d));
}

// The lines a pixel has, each a share 0..1 of the pixel: silhouettes before and after the thin
// guard, and creases.
struct Lines {
    float raw;    // the silhouette line before the thin guard (the limit per area counts it)
    float line;   // the silhouette line after it, the one drawn
    float crease; // the crease line
};

// (r58) The lines as drawn at view distance d, before INK_WORLD and the limit per area: the
// silhouettes with their fade and `opacity`, the creases with their weight and their own fade.
// The limit per area counts these, so it weighs a line as dark as it shows.
Lines drawnAt(Lines lines, float d) {
    const float line_fade = 1.0 - smoothstep(LINE_FADE_M.x, LINE_FADE_M.y, d);
    const float crease_fade = 1.0 - smoothstep(CREASE_FADE_M.x, CREASE_FADE_M.y, d);
    const float silhouette = line_fade * opacityAt(d);
    return Lines(lines.raw * silhouette, lines.line * silhouette,
                 lines.crease * CREASE_WEIGHT * crease_fade);
}

#if !defined(APPLY)

// (r58) The depth around a group of 8x8 pixels, read once into shared memory: every tap of a
// pixel lies within HALO pixels of it (silhouettes at most 7 away, a crease's neighbour at most
// CREASE_REACH and the neighbours its normal is made from 2 more). Out of the image the nearest
// pixel inside's depth is kept there, as the taps take it.
const int HALO = 7;
const int TILE = 8 + 2 * HALO;
const int CREASE_REACH = 3;
shared float tile_depth[TILE * TILE];
// Whether a pixel of the group looks for creases (0 or 1; main).
shared uint group_creases;

ivec2 tileOrigin() {
    return ivec2(gl_WorkGroupID.xy) * 8 - HALO;
}

void loadTile() {
    const ivec2 origin = tileOrigin();
    for (uint i = gl_LocalInvocationIndex; i < uint(TILE * TILE); i += 64u) {
        const ivec2 at = origin + ivec2(int(i) % TILE, int(i) / TILE);
        tile_depth[i] = texelFetch(depth_tex, clamp(at, ivec2(0), ivec2(size) - 1), 0).r;
    }
    if (gl_LocalInvocationIndex == 0u) {
        group_creases = 0u;
    }
    barrier();
}

// The depth at pixel p, which lies within HALO pixels of a pixel of this group.
float depthAt(ivec2 p) {
    const ivec2 at = p - tileOrigin();
    return tile_depth[at.y * TILE + at.x];
}

#else

float depthAt(ivec2 p) {
    return texelFetch(depth_tex, p, 0).r;
}

#endif

bool inside(ivec2 p) {
    return all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, ivec2(size)));
}

#if !defined(APPLY)

// The view position seen at pixel p (sky as very far).
""")),
    (B(r"""
    return viewPos(vec2(p) + 0.5, d >= 1.0 ? 1e6 : viewZ(d));
}

bool inside(ivec2 p) {
    return all(greaterThanEqual(p, ivec2(0))) && all(lessThan(p, ivec2(size)));
}
"""),
     B(r"""
    return viewPos(vec2(p) + 0.5, d >= 1.0 ? 1e6 : viewZ(d));
}
""")),
    (B(r"""
// How much the depth at pixel q lies beyond the plane (normal n, n . P = level) of the pixel
// at depth z, as a share 0..1 (GAP); `jump`: its depth over the pixel's, less 1. The sky is
// four times the pixel's depth. `apart`: the tap's distance in pixels.
float beyond(ivec2 q, vec3 n, float level, float z, float apart, float s, out float jump) {
"""),
     B(r"""
// The depth at pixel q against the plane (normal n, n . P = level) of the pixel at depth z:
// how far q lies beyond it, as a share of z. The sky is four times the pixel's depth. `apart`:
// the tap's distance in pixels. `jump`: q's depth over the pixel's, less 1.
float offPlane(ivec2 q, vec3 n, float level, float z, float apart, float s, out float jump) {
""")),
    (B(r"""
    return smoothstep(GAP.x, GAP.y, (zq - zhat) / z);
}

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (pixel.x >= int(size.x) || pixel.y >= int(size.y)) {
        return;
    }
    const float depth = depthAt(pixel);
    if (depth >= 1.0) {
        return;
    }
    const bool page = ((flags >> 8u) & 7u) == VIEW_INK;
    const float s = size.y / 1080.0;
    const float z = viewZ(depth);
    const vec3 c = viewPos(vec2(pixel) + 0.5, z);
    const float d = length(c);
    // The width in pixels of a 1080-line scene at line scale 1; under one such pixel the line
    // fades (none at 0.6): from about 9 m on at the near width.
    const float narrowed = LINE_PX_ENV * clamp(sqrt(LINE_NEAR_M / d), 0.5, 1.0);
    const float opacity = smoothstep(0.6, 1.0, narrowed);
"""),
     B(r"""
    return (zq - zhat) / z;
}

// How much the depth at pixel q lies beyond that plane, as a share 0..1 (GAP).
float beyond(ivec2 q, vec3 n, float level, float z, float apart, float s, out float jump) {
    return smoothstep(GAP.x, GAP.y, offPlane(q, n, level, z, apart, s, jump));
}

// (r58) The step from q (view position cq, raw depth dq) to its neighbour along `step` on the
// side whose raw depth goes on in a straight line through q (a plane's does: it is linear across
// the screen), so the step stays on q's own face beside a crease. A side with the sky or the
// image's border in its two pixels does not count; `ok` turns false when neither side does.
vec3 faceStep(ivec2 q, vec3 cq, float dq, ivec2 step, inout bool ok) {
    float bend_a = 1e30, bend_b = 1e30;
    if (inside(q - 2 * step)) {
        const float d1 = depthAt(q - step), d2 = depthAt(q - 2 * step);
        if (d1 < 1.0 && d2 < 1.0) {
            bend_a = abs(2.0 * d1 - d2 - dq);
        }
    }
    if (inside(q + 2 * step)) {
        const float d1 = depthAt(q + step), d2 = depthAt(q + 2 * step);
        if (d1 < 1.0 && d2 < 1.0) {
            bend_b = abs(2.0 * d1 - d2 - dq);
        }
    }
    if (bend_a >= 1e30 && bend_b >= 1e30) {
        ok = false;
        return vec3(1.0, 0.0, 0.0);
    }
    return bend_b < bend_a ? viewAt(q + step) - cq : cq - viewAt(q - step);
}

// (r58) The normal of q's own face from the depth, view axes, turned towards the camera; `ok`
// false where it cannot be told (the sky, a sliver of one or two pixels, the image's border).
vec3 faceNormal(ivec2 q, out bool ok) {
    const float dq = depthAt(q);
    ok = dq < 1.0;
    if (!ok) {
        return vec3(0.0, 0.0, -1.0);
    }
    const vec3 cq = viewPos(vec2(q) + 0.5, viewZ(dq));
    const vec3 ty = faceStep(q, cq, dq, ivec2(0, 1), ok);
    const vec3 tx = faceStep(q, cq, dq, ivec2(1, 0), ok);
    const vec3 n = cross(ty, tx);
    // (Measured against the steps' own lengths: near the camera a pixel's steps are tiny.)
    if (!ok || !(dot(n, n) > 1e-8 * dot(tx, tx) * dot(ty, ty))) {
        ok = false;
        return vec3(0.0, 0.0, -1.0);
    }
    const vec3 unit_n = normalize(n);
    return dot(unit_n, cq) > 0.0 ? -unit_n : unit_n;
}

// (r58) The face normals (faceNormal) of the pixels within CREASE_REACH of the group, made once
// into shared memory when a pixel of the group looks for creases (`wanted`): a crease compares
// each pixel's normal with its neighbours', and made pixel by pixel each normal was made about
// five times over. 0 where none can be told or the pixel is outside the image. Every
// invocation of the group calls it (it waits for them all).
const int NORMALS = 8 + 2 * CREASE_REACH;
shared vec3 tile_normal[NORMALS * NORMALS];

ivec2 normalsOrigin() {
    return ivec2(gl_WorkGroupID.xy) * 8 - CREASE_REACH;
}

void loadNormals(bool wanted) {
    if (wanted) {
        const ivec2 origin = normalsOrigin();
        for (uint i = gl_LocalInvocationIndex; i < uint(NORMALS * NORMALS); i += 64u) {
            const ivec2 q = origin + ivec2(int(i) % NORMALS, int(i) / NORMALS);
            bool ok = false;
            const vec3 n = inside(q) ? faceNormal(q, ok) : vec3(0.0);
            tile_normal[i] = ok ? n : vec3(0.0);
        }
    }
    barrier();
}

// The face normal at pixel q (within CREASE_REACH of the group), `ok` false where there is none.
vec3 normalAt(ivec2 q, out bool ok) {
    const ivec2 at = q - normalsOrigin();
    const vec3 n = tile_normal[at.y * NORMALS + at.x];
    ok = dot(n, n) > 0.5;
    return n;
}

// The lines at `pixel` (not sky; view depth z, view position c, distance d). `axes`: 2 (the x
// and y axes; Low) or 4 (and both diagonals; High). Only what `wanted` says is looked for.
Lines linesAt(ivec2 pixel, float z, vec3 c, float d, int axes, bool sil_wanted,
              bool crease_wanted) {
    Lines lines = Lines(0.0, 0.0, 0.0);
    const float s = size.y / 1080.0;
""")),
    (B(r"""
    const float width = narrowed * s * LINE_SCALE;
    const float drawn = max(width, 1.0);
    const float thinner = min(width, 1.0);
    const float fade = 1.0 - smoothstep(ENV_FADE_M.x, ENV_FADE_M.y, d);
    float line = 0.0;
    if (opacity > 0.0 && fade > 0.0 && INK_WORLD > 0.0) {
        const vec3 n = viewNormal(pixel, c);
        const float level = dot(n, c);
"""),
     B(r"""
    const float width = LINE_PX_ENV * narrowedAt(d) * s * LINE_SCALE;
    const float drawn = max(width, 1.0);
    const float thinner = min(width, 1.0);
    const vec3 n = viewNormal(pixel, c);
    const float level = dot(n, c);
    if (sil_wanted) {
""")),
    (B(r"""
        const int reach = int(min(ceil(drawn + 1.0), 7.0));
        const vec2 dirs[4] = vec2[4](vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.70710678, 0.70710678),
                                     vec2(0.70710678, -0.70710678));
        for (int i = 0; i < 4; ++i) {
"""),
     B(r"""
        const int reach = int(min(ceil(drawn + 1.0), float(HALO)));
        const vec2 dirs[4] = vec2[4](vec2(1.0, 0.0), vec2(0.0, 1.0), vec2(0.70710678, 0.70710678),
                                     vec2(0.70710678, -0.70710678));
        float line = 0.0, raw = 0.0;
        for (int i = 0; i < axes; ++i) {
""")),
    (B(r"""
            }
            line = max(line, la * mix(1.0, THIN_WEIGHT, smoothstep(THIN.x, THIN.y, fb)));
"""),
     B(r"""
            }
            raw = max(raw, max(la, lb));
            line = max(line, la * mix(1.0, THIN_WEIGHT, smoothstep(THIN.x, THIN.y, fb)));
""")),
    (B(r"""
    }
    float weight = line * thinner * opacity * INK_WORLD * fade;
"""),
     B(r"""
        lines.raw = raw * thinner;
        lines.line = line * thinner;
    }
    if (crease_wanted) {
        // A crease line lies on both faces, half of its width on each: a neighbour r pixels
        // away across it gives the share clamp(half + 1 - r, 0, 1) of this pixel.
        const float half_width = 0.5 * CREASE_PX * narrowedAt(d) * s * LINE_SCALE;
        bool ok;
        const vec3 np = normalAt(pixel, ok);
        const int reach = int(min(ceil(half_width), float(CREASE_REACH)));
        const ivec2 steps[4] = ivec2[4](ivec2(1, 0), ivec2(-1, 0), ivec2(0, 1), ivec2(0, -1));
        float crease = 0.0;
        for (int i = 0; i < 4 && ok; ++i) {
            for (int r = 1; r <= reach; ++r) {
                const ivec2 q = pixel + steps[i] * r;
                if (!inside(q)) {
                    break;
                }
                bool q_ok;
                const vec3 nq = normalAt(q, q_ok);
                if (!q_ok) {
                    continue;
                }
                float jump;
                const float off = smoothstep(GAP.x, GAP.y,
                                             abs(offPlane(q, n, level, z, float(r), s, jump)));
                const float bend = 1.0 - smoothstep(CREASE_COS.x, CREASE_COS.y, dot(np, nq));
                const float cover = clamp(half_width + 1.0 - float(r), 0.0, 1.0);
                crease = max(crease, bend * (1.0 - off) * cover);
            }
        }
        lines.crease = crease;
    }
    return lines;
}

#endif

#if !defined(EDGES)

// Draws the lines of `weight` into the scene colour at `pixel` (not sky), the ink page in test
// view 3; what glows gets none.
void ink(ivec2 pixel, float weight, bool page) {
""")),
    (B(r"""
    }
}
"""),
     B(r"""
    }
}

#endif

#if defined(APPLY)

// (r58) The edges image's level `level` at uv, weighted by a cubic B-spline over 4x4 of its
// texels (four linear reads). Unlike one linear read, whose weighting is one texel's box at a
// texel's centre and two boxes between centres, this weighting changes little with where uv
// lies against the texels: the limit per area does not step at the texels' borders as the
// camera moves.
vec4 smoothAt(vec2 uv, int level) {
    const vec2 texels = vec2(textureSize(edges_tex, level));
    const vec2 at = uv * texels - 0.5;
    const vec2 i = floor(at), f = at - i;
    const vec2 w0 = (1.0 - f) * (1.0 - f) * (1.0 - f) / 6.0;
    const vec2 w1 = (4.0 - 6.0 * f * f + 3.0 * f * f * f) / 6.0;
    const vec2 w3 = f * f * f / 6.0;
    const vec2 w2 = 1.0 - w0 - w1 - w3;
    const vec2 g0 = w0 + w1, g1 = w2 + w3;
    // Each pair of texels in one linear read, at the point between them their weights give.
    const vec2 h0 = (i - 0.5 + w1 / g0) / texels;
    const vec2 h1 = (i + 1.5 + w3 / g1) / texels;
    const float lod = float(level);
    return g0.y * (g0.x * textureLod(edges_tex, vec2(h0.x, h0.y), lod) +
                   g1.x * textureLod(edges_tex, vec2(h1.x, h0.y), lod)) +
           g1.y * (g0.x * textureLod(edges_tex, vec2(h0.x, h1.y), lod) +
                   g1.x * textureLod(edges_tex, vec2(h1.x, h1.y), lod));
}

// (r58) The lines around the pixel at uv: the edges image at DENSITY_LEVEL, between its two
// nearest levels (each weighted as smoothAt does). Each level is made of tents as wide as two
// of its texels (DOWN), so this weighting is about as wide as a box of DENSITY_PX pixels of a
// 1080-line scene (DensityLevel puts it 1.5 levels under that box's size).
vec4 placeAt(vec2 uv) {
    const int top = textureQueryLevels(edges_tex) - 1;
    const float level = clamp(DENSITY_LEVEL, 0.0, float(top));
    const int below = int(floor(level));
    const int above = min(below + 1, top);
    const vec4 near = smoothAt(uv, below);
    return above == below ? near : mix(near, smoothAt(uv, above), level - float(below));
}

#endif

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    const bool in_image = pixel.x < int(size.x) && pixel.y < int(size.y);
#if !defined(APPLY)
    // Every invocation of the group helps to read the depth and to make the face normals,
    // inside the image or not: both wait for the whole group.
    loadTile();
    const float depth = in_image ? depthAt(pixel) : 1.0;
    float z = 0.0, d = 0.0;
    vec3 c = vec3(0.0);
    bool sil_wanted = false, crease_wanted = false;
    if (depth < 1.0) {
        z = viewZ(depth);
        c = viewPos(vec2(pixel) + 0.5, z);
        d = length(c);
        // Only lines that would show are looked for (their fades end at a distance).
        sil_wanted = d < LINE_FADE_M.y && INK_WORLD > 0.0;
        crease_wanted = d < CREASE_FADE_M.y && CREASE_WEIGHT > 0.0 && INK_WORLD > 0.0;
    }
    if (crease_wanted) {
        atomicOr(group_creases, 1u);
    }
    barrier();
    loadNormals(group_creases != 0u);
#endif
    if (!in_image) {
        return;
    }
#if defined(APPLY)
    const float depth = depthAt(pixel);
#endif
    if (depth >= 1.0) {
#if defined(EDGES)
        // Every texel of level 0 is written: the image is new every frame.
        imageStore(edges_img, pixel, vec4(0.0));
#endif
        return;
    }
    const bool page = ((flags >> 8u) & 7u) == VIEW_INK;
#if defined(APPLY)
    // EDGES stored the lines as drawn (drawnAt): b the silhouette line, g the crease line.
    const vec4 at = texelFetch(edges_tex, pixel, 0);
    // The share of the place around the pixel that lines cover, r + g.
    const vec4 place = placeAt((vec2(pixel) + 0.5) / size);
    const float factor = 1.0 - smoothstep(DENSITY.x, DENSITY.y, place.r + place.g);
    ink(pixel, max(at.b, at.g) * INK_WORLD * factor, page);
#else
#if defined(EDGES)
    const Lines lines = drawnAt(linesAt(pixel, z, c, d, 4, sil_wanted, crease_wanted), d);
    imageStore(edges_img, pixel, vec4(lines.raw, lines.crease, lines.line, 0.0));
#else
    const Lines lines = drawnAt(linesAt(pixel, z, c, d, 2, sil_wanted, crease_wanted), d);
    ink(pixel, max(lines.line, lines.crease) * INK_WORLD * LOW_FACTOR, page);
#endif
#endif
}

#endif
""")),
]

EDITS[G + "CMakeLists.txt"] = [
    (B(r"""
add_host_shader(paint_ink.comp paint_ink_comp) # bbport (r55_drawn-look-lines)
add_host_shader(rt_shadow.comp rt_shadow_comp)
"""),
     B(r"""
add_host_shader(paint_ink.comp paint_ink_comp) # bbport (r55_drawn-look-lines)
# bbport (r58_drawn-look-d2): the ink at High quality, with its limit per area
add_host_shader(paint_ink.comp paint_ink_edges_comp EDGES=1)
add_host_shader(paint_ink.comp paint_ink_down_comp DOWN=1)
add_host_shader(paint_ink.comp paint_ink_apply_comp APPLY=1)
add_host_shader(rt_shadow.comp rt_shadow_comp)
""")),
]

EDITS[R + "vk_drawn_look.h"] = [
    (B(r"""
// Built so far (stages 1 and 2 of the design, and r55_drawn-look-lines): the switch, the passes'
// place in the frame, the strokes themselves (host_shaders/paint_strokes.comp), ink lines along
// the silhouettes of shapes (host_shaders/paint_ink.comp; with the strength at 0 they are drawn
// alone), and test views (BB_DRAWN_LOOK_VIEW, never saved) that paint every stroke in a flat
// colour of its own or show the ink lines alone on a grey page. Not built: ink on inner edges,
// heavier ink on characters, painted shadow edges.
"""),
     B(r"""
// Built so far (stages 1 and 2 of the design, r55_drawn-look-lines and r58_drawn-look-d2): the
// switch, the passes' place in the frame, the strokes themselves (host_shaders/
// paint_strokes.comp), ink lines along the silhouettes of shapes and (r58) on the creases where
// surfaces meet at an angle (host_shaders/paint_ink.comp; with the strength at 0 they are drawn
// alone), at two qualities (graphics_drawn_look_quality: High limits the ink per area), and
// test views (BB_DRAWN_LOOK_VIEW, never saved) that paint every stroke in a flat colour of its
// own or show the ink lines alone on a grey page. Not built: heavier ink on characters, painted
// shadow edges.
""")),
    (B(r"""
//                       alone; not on a frame painted right before the upscaler
"""),
     B(r"""
//                       alone; not on a frame painted right before the upscaler. Low quality:
//                       one pass. (r58) High: EDGES (each pixel's lines into the edges image),
//                       DOWN once a level of it, APPLY (the lines, limited per area)
""")),
    (B(r"""
    bool EnsureImage(OwnImage& image, u32 width, u32 height, vk::Format format, const char* name);
"""),
     B(r"""
    /// `levels`: 0 for all down to one texel (r58_drawn-look-d2: the edges image has fewer).
    bool EnsureImage(OwnImage& image, u32 width, u32 height, vk::Format format, const char* name,
                     u32 levels = 0);
""")),
    (B(r"""
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;
    vk::UniqueSampler sampler; ///< linear between texels and between levels, clamped
"""),
     B(r"""
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;
    /// (r58_drawn-look-d2) The ink at High quality: paint_ink.comp EDGES, DOWN and APPLY.
    Pass ink_edges, ink_down, ink_apply;
    vk::UniqueSampler sampler; ///< linear between texels and between levels, clamped
""")),
    (B(r"""
    OwnImage lock_means;
    std::array<ViewEntry, 6> view_cache{};
"""),
     B(r"""
    OwnImage lock_means;
    /// (r58_drawn-look-d2) High quality's edges image (rgba8): each pixel's ink lines, and the
    /// smaller levels the limit per area reads (DrawnLookParams::EdgeLevels). Made only while
    /// the knobs ask for High.
    OwnImage edges;
    std::array<ViewEntry, 6> view_cache{};
""")),
    (B(r"""
    float env_line = 1.0f;
    bool tried = false;
"""),
     B(r"""
    float env_line = 1.0f;
    /// (r58_drawn-look-d2) BB_DRAWN_LOOK_CREASE_* and the others (DrawnLookParams::InkTune):
    /// the ink's numbers, read once.
    DrawnLookParams::InkTune env_tune{};
    bool tried = false;
""")),
    (B(r"""
    u32 refused_width = 0, refused_height = 0;
    /// The depths of the last G-buffer pass of recent frames: the scene's own (it is drawn
"""),
     B(r"""
    u32 refused_width = 0, refused_height = 0;
    /// (r58_drawn-look-d2) The same for the edges image alone: at that size the lines are drawn
    /// at Low quality instead. Asked again at another size, or after the quality or the look
    /// was switched.
    u32 edges_refused_width = 0, edges_refused_height = 0;
    /// The depths of the last G-buffer pass of recent frames: the scene's own (it is drawn
""")),
    (B(r"""
    u32 ink_frames = 0; ///< (r55_drawn-look-lines) frames the ink lines were recorded on
    /// (r55_drawn-look-lines) This frame set BbSettings' drawn_look_ink_drawn (OnFrameEnd puts
"""),
     B(r"""
    u32 ink_frames = 0; ///< (r55_drawn-look-lines) frames the ink lines were recorded on
    u32 limit_frames = 0; ///< (r58_drawn-look-d2) of those, with the limit per area (High)
    u32 low_for_room = 0; ///< (r58) of those, at Low for want of room for the edges image
    /// (r55_drawn-look-lines) This frame set BbSettings' drawn_look_ink_drawn (OnFrameEnd puts
""")),
]

EDITS[R + "vk_drawn_look.cpp"] = [
    (B(r"""
#include <cstdlib>

"""),
     B(r"""
#include <cstdlib>
#include <iterator>

""")),
    (B(r"""
#include "video_core/host_shaders/paint_ink_comp.h"
"""),
     B(r"""
#include "video_core/host_shaders/paint_ink_apply_comp.h" // bbport (r58_drawn-look-d2)
#include "video_core/host_shaders/paint_ink_comp.h"
#include "video_core/host_shaders/paint_ink_down_comp.h"  // bbport (r58_drawn-look-d2)
#include "video_core/host_shaders/paint_ink_edges_comp.h" // bbport (r58_drawn-look-d2)
""")),
    (B(r"""
              DrawnLookParams::Knobs{}.characters == BbSettings::DrawnLookCharactersDefault);

"""),
     B(r"""
              DrawnLookParams::Knobs{}.characters == BbSettings::DrawnLookCharactersDefault);
// (r58_drawn-look-d2) The ink's quality: its values and default, the renderer's and the ini's.
static_assert(DrawnLookParams::Knobs{}.quality == BbSettings::DrawnLookQualityDefault &&
              DrawnLookParams::QualityLow == BbSettings::DrawnLookQualityLow &&
              DrawnLookParams::QualityHigh == BbSettings::DrawnLookQualityHigh);

""")),
    (B(r"""
    env_line = DrawnLookParams::LineScaleOf(std::getenv("BB_DRAWN_LOOK_LINE"));
}
"""),
     B(r"""
    env_line = DrawnLookParams::LineScaleOf(std::getenv("BB_DRAWN_LOOK_LINE"));
    // (r58_drawn-look-d2) The ink's numbers, for judging them in the game: environment only, so
    // a value tried once is not saved with the menu's next change. Printed once when any is set.
    env_tune = DrawnLookParams::InkTuneOf([](const char* name) { return std::getenv(name); });
    if (std::any_of(std::begin(DrawnLookParams::InkTuneNames),
                    std::end(DrawnLookParams::InkTuneNames),
                    [](const char* name) { return std::getenv(name) != nullptr; })) {
        const auto& t = env_tune;
        std::printf("Drawn look: ink numbers from the environment: creases from %.1f to %.1f "
                    "degrees, %.2f pixels wide, weight %.2f, fading %.0f..%.0f m; silhouettes "
                    "fading %.0f..%.0f m; limit per area %.2f..%.2f over %.1f pixels; Low's "
                    "factor %.2f\n",
                    t.crease_deg[0], t.crease_deg[1], t.crease_px, t.crease_weight,
                    t.crease_fade_m[0], t.crease_fade_m[1], t.line_fade_m[0], t.line_fade_m[1],
                    t.density[0], t.density[1], t.density_px, t.low_factor);
    }
}
""")),
    (B(r"""
    ReleaseImage(lock_means);
    ReleaseViews();
"""),
     B(r"""
    ReleaseImage(lock_means);
    ReleaseImage(edges); // bbport (r58_drawn-look-d2)
    ReleaseViews();
""")),
    (B(r"""
        CreatePass(ink, {Sampled, SampledImage, StorageImage}, PAINT_INK_COMP, "Drawn look ink");
"""),
     B(r"""
        CreatePass(ink, {Sampled, SampledImage, StorageImage}, PAINT_INK_COMP, "Drawn look ink") &&
        // (r58_drawn-look-d2) High quality's three passes and their edges image. RGBA8 storage is
        // core Vulkan; rg8 would need shaderStorageImageExtendedFormats, and three channels are
        // used.
        EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
        CreatePass(ink_edges, {SampledImage, StorageImage}, PAINT_INK_EDGES_COMP,
                   "Drawn look ink edges") &&
        CreatePass(ink_down, {Sampled, StorageImage}, PAINT_INK_DOWN_COMP,
                   "Drawn look ink edge levels") &&
        CreatePass(ink_apply, {Sampled, SampledImage, StorageImage, Sampled},
                   PAINT_INK_APPLY_COMP, "Drawn look ink apply");
""")),
    (B(r"""
                            const char* name) {
"""),
     B(r"""
                            const char* name, u32 level_count) {
""")),
    (B(r"""
    const u32 levels = LevelsOf(width, height);
"""),
     B(r"""
    const u32 levels = level_count == 0 ? LevelsOf(width, height)
                                        : std::min(level_count, LevelsOf(width, height));
""")),
    (B(r"""
                             "before the upscaler; ink lines on %u; what moves by itself told "
                             "against the camera of the frame before on %u\n",
"""),
     B(r"""
                             "before the upscaler; ink lines on %u (with the limit per area on "
                             "%u, at Low for want of video memory on %u); what moves by itself "
                             "told against the camera of the frame before on %u\n",
""")),
    (B(r"""
                             ink_frames, previous_frames);
"""),
     B(r"""
                             ink_frames, limit_frames, low_for_room, previous_frames);
""")),
    (B(r"""
            ink_frames = 0;
            previous_frames = 0;
"""),
     B(r"""
            ink_frames = 0;
            limit_frames = 0;
            low_for_room = 0;
            previous_frames = 0;
""")),
    (B(r"""
                BbSettings::Get().drawn_look_problem = nullptr;
            }
        }
    }
"""),
     B(r"""
                BbSettings::Get().drawn_look_problem = nullptr;
            }
            edges_refused_width = edges_refused_height = 0; // bbport (r58_drawn-look-d2)
        }
    }
""")),
    (B(r"""
        .view = env_view >= 0 ? env_view : int(DrawnLookParams::ViewOff),
    };
"""),
     B(r"""
        .view = env_view >= 0 ? env_view : int(DrawnLookParams::ViewOff),
        .quality = s.graphics_drawn_look_quality.load(std::memory_order_relaxed),
    };
""")),
    (B(r"""
    EnsureImage(lock_means, width / 4, height / 4, vk::Format::eR16G16B16A16Sfloat, "means");
    frame_result = place;
"""),
     B(r"""
    EnsureImage(lock_means, width / 4, height / 4, vk::Format::eR16G16B16A16Sfloat, "means");
    // (r58_drawn-look-d2) High quality's edges image. While the knobs ask for Low (whatever the
    // frame's place) it is let go, and the memory is asked for again when they ask for High.
    // Without room for it at this size the frame's lines are drawn as Low draws them: the look
    // itself goes on.
    bool limit = passes.ink_limit;
    bool low_room = false;
    if (!DrawnLookParams::PassesFor(knobs, false).ink_limit) {
        ReleaseImage(edges);
        edges_refused_width = edges_refused_height = 0;
    } else if (limit && (!edges.image || edges.width != width || edges.height != height)) {
        if (width == edges_refused_width && height == edges_refused_height) {
            limit = false;
            low_room = true;
        } else if (!EffectPass::HasRoom(instance, vk::DeviceSize(width) * height *
                                                      DrawnLookParams::EdgeBytesPerPixel)) {
            edges_refused_width = width;
            edges_refused_height = height;
            limit = false;
            low_room = true;
            ReleaseImage(edges);
            std::printf("Drawn look: not enough video memory for the ink's edges image at %ux%u: "
                        "the lines are drawn at Low quality; asked again when the scene's size "
                        "changes or the quality or the look is switched\n",
                        width, height);
        } else {
            edges_refused_width = edges_refused_height = 0;
        }
    }
    if (limit) {
        EnsureImage(edges, width, height, vk::Format::eR8G8B8A8Unorm, "ink edges",
                    DrawnLookParams::EdgeLevels(width, height, env_tune.density_px));
    }
    frame_result = place;
""")),
    (B(r"""
    const auto ink_params =
        DrawnLookParams::MakeInk(params, knobs.ink_world, knobs.outlines, knobs.line_scale);
"""),
     B(r"""
    const auto ink_params = DrawnLookParams::MakeInk(params, knobs.ink_world, knobs.outlines,
                                                     knobs.line_scale, env_tune);
""")),
    (B(r"""
        u32(passes.strokes) << 8 | u32(passes.ink) << 9;
"""),
     B(r"""
        u32(passes.strokes) << 8 | u32(passes.ink) << 9 | u32(limit) << 10;
""")),
    (B(r"""
        char ink_text[64];
        if (passes.ink) {
            std::snprintf(ink_text, sizeof(ink_text), "ink lines %.2f (line scale %.2f)",
                          ink_params.strength, knobs.line_scale);
"""),
     B(r"""
        char ink_text[112];
        if (passes.ink) {
            std::snprintf(ink_text, sizeof(ink_text), "ink lines %.2f (line scale %.2f, %s)",
                          ink_params.strength, knobs.line_scale,
                          limit      ? "quality high: limit per area"
                          : low_room ? "quality low: no video memory for high"
                                     : "quality low");
""")),
    (B(r"""
    ++ink_frames;
    // The upscaler's extra sharpening on this frame (DrawnLookParams::InkSharpen).
"""),
     B(r"""
    ++ink_frames;
    limit_frames += limit;
    low_for_room += low_room;
    // The upscaler's extra sharpening on this frame (DrawnLookParams::InkSharpen).
""")),
    (B(r"""
    ink_published = true;
    EffectPass::Mark(13, "drawn look ink");
"""),
     B(r"""
    ink_published = true;
    // (r58_drawn-look-d2) Each level of the edges image, for the closure.
    struct {
        std::array<vk::ImageView, MaxLevels> views{};
        u32 count = 0;
    } edge_levels;
    if (limit) {
        edge_levels.count = u32(edges.levels.size());
        for (u32 level = 0; level < edge_levels.count; ++level) {
            edge_levels.views[level] = *edges.levels[level];
        }
    }
    EffectPass::Mark(13, "drawn look ink");
""")),
    (B(r"""
        [ink_params, width, height, color_view, depth_view, sampler = *sampler,
         prep_view = *prep_copy.view, ink_pipeline = *ink.pipeline,
         ink_layout = *ink.layout](vk::CommandBuffer cmdbuf) {
            // The scene colour (the strokes' crumb) and the key (the masks') are written.
            EffectPass::ComputeBarrier(cmdbuf);
            const std::array infos{Info(prep_view, sampler), Info(depth_view), Info(color_view)};
            const std::array writes{Write(0, Sampled, &infos[0]), Write(1, SampledImage, &infos[1]),
                                    Write(2, StorageImage, &infos[2])};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, ink_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, ink_layout, 0, writes);
            cmdbuf.pushConstants(ink_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                 sizeof(ink_params), &ink_params);
            cmdbuf.dispatch((width + 7) / 8, (height + 7) / 8, 1);
"""),
     B(r"""
        [ink_params, width, height, limit, edge_levels, color_view, depth_view,
         sampler = *sampler, prep_view = *prep_copy.view,
         edges_image = limit ? vk::Image(edges.image) : vk::Image{},
         edges_view = limit ? *edges.view : vk::ImageView{}, ink_pipeline = *ink.pipeline,
         ink_layout = *ink.layout, edges_pipeline = *ink_edges.pipeline,
         edges_layout = *ink_edges.layout, down_pipeline = *ink_down.pipeline,
         down_layout = *ink_down.layout, apply_pipeline = *ink_apply.pipeline,
         apply_layout = *ink_apply.layout](vk::CommandBuffer cmdbuf) {
            // The scene colour (the strokes' crumb) and the key (the masks') are written.
            EffectPass::ComputeBarrier(cmdbuf);
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout,
                                 std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(ink_params), &ink_params);
                cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            };
            if (!limit) {
                // Low: found and drawn in one pass.
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(color_view)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2])};
                run(ink_pipeline, ink_layout, writes, width, height);
            } else {
                // High. The edges image is written anew every frame, every level of it; what
                // the frame before read of it is done.
                const vk::ImageMemoryBarrier2 to_general{
                    .srcStageMask = AllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eNone,
                    .dstStageMask = Compute,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .image = edges_image,
                    .subresourceRange = AllLevels,
                };
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                {
                    const std::array infos{Info(depth_view), Info(edge_levels.views[0])};
                    const std::array writes{Write(0, SampledImage, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(edges_pipeline, edges_layout, writes, width, height);
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                // Each level from the one above it (a tent two of its texels wide; paint_ink.comp
                // DOWN). Level n is max(size >> n, 1) on each side, as the image's levels are.
                for (u32 n = 1; n < edge_levels.count; ++n) {
                    const std::array infos{Info(edge_levels.views[n - 1], sampler),
                                           Info(edge_levels.views[n])};
                    const std::array writes{Write(0, Sampled, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(down_pipeline, down_layout, writes, std::max(width >> n, 1u),
                        std::max(height >> n, 1u));
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(color_view), Info(edges_view, sampler)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2]),
                                        Write(3, Sampled, &infos[3])};
                run(apply_pipeline, apply_layout, writes, width, height);
            }
""")),
]

EDITS[S + "bbport_settings.h"] = [
    (B(r"""
inline constexpr float DrawnLookInkWorldDefault = 0.35f; // bbport (r55_drawn-look-lines)
inline constexpr float LocalLightIntensityMin = 0.0f, LocalLightIntensityMax = 4.0f;
"""),
     B(r"""
inline constexpr float DrawnLookInkWorldDefault = 0.35f; // bbport (r55_drawn-look-lines)
// bbport (r58_drawn-look-d2): graphics_drawn_look_quality, the ink lines' quality
// (DrawnLookParams::Quality, which vk_drawn_look.cpp ties to these).
inline constexpr int DrawnLookQualityLow = 0, DrawnLookQualityHigh = 1,
                     DrawnLookQualityDefault = DrawnLookQualityHigh;
inline constexpr float LocalLightIntensityMin = 0.0f, LocalLightIntensityMax = 4.0f;
""")),
    (B(r"""
    // characters and (r55_drawn-look-lines) ink_world; outlines is handed to the ink pass, which
    // does not read it yet; the others are parsed, clamped and saved for the parts of the look
    // that are not built yet (painted shadow edges). The test views are BB_DRAWN_LOOK_VIEW only
"""),
     B(r"""
    // characters, (r55_drawn-look-lines) ink_world and (r58_drawn-look-d2) quality; outlines is
    // handed to the ink pass, which does not read it yet; the others are parsed, clamped and
    // saved for the parts of the look that are not built yet (painted shadow edges). The ink's
    // numbers for tuning are BB_DRAWN_LOOK_CREASE_* and the others (DrawnLookParams::InkTune),
    // never keys. The test views are BB_DRAWN_LOOK_VIEW only
""")),
    (B(r"""
    std::atomic<int> graphics_drawn_look_quality{1};           // 0 low, 1 high
"""),
     B(r"""
    std::atomic<int> graphics_drawn_look_quality{DrawnLookQualityDefault}; // 0 low, 1 high: the ink lines
""")),
]

EDITS[S + "bbport_settings.cpp"] = [
    (B(r"""
        v.graphics_drawn_look_quality = std::clamp(i, 0, 1);
"""),
     B(r"""
        // bbport (r58_drawn-look-d2): a whole number is clamped to 0 (low) .. 1 (high); anything
        // else is the default, high, with a note (atoi made a word 0: low).
        char* end = nullptr;
        const long quality = std::strtol(value.c_str(), &end, 10);
        if (value.empty() || !end || *end != '\0') {
            std::printf("Settings: unknown graphics_drawn_look_quality '%s' (expected 0 low or 1 "
                        "high); %d\n", value.c_str(), DrawnLookQualityDefault);
            v.graphics_drawn_look_quality = DrawnLookQualityDefault;
        } else {
            v.graphics_drawn_look_quality =
                int(std::clamp(quality, long(DrawnLookQualityLow), long(DrawnLookQualityHigh)));
        }
""")),
    (B(r"""
    put("graphics_drawn_look_quality", std::to_string(std::clamp(v.graphics_drawn_look_quality.load(), 0, 1)));
"""),
     B(r"""
    put("graphics_drawn_look_quality",
        std::to_string(std::clamp(v.graphics_drawn_look_quality.load(), DrawnLookQualityLow,
                                  DrawnLookQualityHigh)));
""")),
]

EDITS[S + "bbport_drawn_look_texts.h"] = [
    (B(r"""
// bbport (r55_drawn-look-lines): the drawn look's menu texts, English and Russian, in one place.
"""),
     B(r"""
// bbport (r55_drawn-look-lines, r58_drawn-look-d2): the drawn look's menu texts, English and
// Russian, in one place.
""")),
    (B(r"""
    "and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, "
    "fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line "
    "is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on "
    "characters, lines on inner edges and painted shadow edges.",
    "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных "
    "стенах и полах, мелкие там, где есть детали, а по краям форм идут контурные линии. Огонь, "
    "свечение, туман, частицы и интерфейс остаются такими, какими их рисует игра. Цвета не "
    "меняются; контурная линия — это собственный цвет поверхности, только темнее. Применяется "
    "сразу. Ещё не сделано: более густые контуры на персонажах, линии на внутренних рёбрах и "
"""),
     B(r"""
    "and floors, fine where there is detail, and ink lines along the edges of shapes and where "
    "surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws "
    "them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at "
    "once. Not built yet: heavier ink on characters and painted shadow edges.",
    "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных "
    "стенах и полах, мелкие там, где есть детали, а по краям форм и там, где поверхности сходятся "
    "под углом, идут контурные линии. Огонь, свечение, туман, частицы и интерфейс остаются такими, "
    "какими их рисует игра. Цвета не меняются; контурная линия — это собственный цвет поверхности, "
    "только темнее. Применяется сразу. Ещё не сделано: более густые контуры на персонажах и "
""")),
    (B(r"""
    "How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures "
    "against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance "
    "and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the "
    "look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening "
    "is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. "
    "Applies at once.",
    "Насколько темны контурные линии по краям форм: колонны, стены, ступени и фигуры на фоне того, "
    "что за ними. 0 — без линий. С расстоянием линии становятся тоньше и бледнее, а дальше 120 м "
    "исчезают; туман закрывает их так же, как и весь мир. Не рисуются в кадрах, где стиль "
    "накладывается прямо перед апскейлером. Пока линии рисуются, дополнительная резкость "
    "апскейлера снижается вплоть до половины. Цвета сохраняются: линия — это собственный цвет "
    "поверхности, только темнее. Применяется сразу."};
"""),
     B(r"""
    "How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures "
    "against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner "
    "of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; "
    "lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers "
    "the world. Not drawn on frames the look paints right before the upscaler. While lines are "
    "drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is "
    "the surface's own colour, darker. Applies at once.",
    "Насколько темны контурные линии: по краям форм (колонны, стены, ступени и фигуры на фоне "
    "того, что за ними) и, светлее, там, где две поверхности сходятся под углом (угол блока, низ "
    "стены). 0 — без линий. С расстоянием линии становятся тоньше и бледнее; линии на углах "
    "исчезают дальше 50 м, по краям — дальше 120 м; туман закрывает их так же, как и весь мир. Не "
    "рисуются в кадрах, где стиль накладывается прямо перед апскейлером. Пока линии рисуются, "
    "дополнительная резкость апскейлера снижается вплоть до половины. Цвета сохраняются: линия — "
    "это собственный цвет поверхности, только темнее. Применяется сразу."};
// bbport (r58_drawn-look-d2): the ink lines' quality (graphics_drawn_look_quality).
inline constexpr Text Quality{"Drawn look ink quality", "Качество контурных линий"};
inline constexpr Text QualityHint{
    "High: edges are looked for along rows, columns and both diagonals, and where many lines crowd "
    "together (foliage, grates, railings) they are made fainter, so busy places do not turn black; "
    "it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and "
    "draws as Low where there is not enough. Low: along rows and columns only (slanted lines come "
    "out a little thinner), every line a little lighter, no such limit; it costs less. High by "
    "default. Applies at once.",
    "Высокое: края ищутся по строкам, столбцам и обеим диагоналям, а там, где линий много (листва, "
    "решётки, перила), они становятся бледнее, чтобы такие места не чернели; занимает около 11 МБ "
    "видеопамяти при разрешении рендеринга 1080 строк (44 МБ при 2160 строках) и рисует как "
    "низкое, если памяти не хватает. Низкое: только по строкам и столбцам (наклонные линии выходят "
    "чуть тоньше), все линии чуть светлее, без такого ограничения; обходится дешевле. По умолчанию "
    "— высокое. Применяется сразу."};
inline constexpr Text QualityLow{"Low", "Низкое"};
inline constexpr Text QualityHigh{"High", "Высокое"};
""")),
    (B(r"""
                                      &Ink, &InkHint, &NoUpscaler, &NoPasses, &NotHalfFloat,
"""),
     B(r"""
                                      &Ink, &InkHint, &Quality, &QualityHint, &QualityLow,
                                      &QualityHigh, &NoUpscaler, &NoPasses, &NotHalfFloat,
""")),
]

EDITS[S + "bbport_overlay.cpp"] = [
    (B(r"""
        Hint(drawn_text(DrawnText::InkHint));
    }
"""),
     B(r"""
        Hint(drawn_text(DrawnText::InkHint));
    }
    // bbport (r58_drawn-look-d2): the ink lines' quality (graphics_drawn_look_quality,
    // DrawnLookParams::Quality). High limits the ink per area with an edges image and two more
    // passes; Low is one pass. The names are in the setting's order: 0 low, 1 high.
    if (const char* label = Item(DrawnText::Quality.english, DrawnText::Quality.russian)) {
        const char* names[] = {drawn_text(DrawnText::QualityLow),
                               drawn_text(DrawnText::QualityHigh)};
        static_assert(std::size(names) == BbSettings::DrawnLookQualityHigh + 1 &&
                      BbSettings::DrawnLookQualityLow == 0);
        int quality = std::clamp(s.graphics_drawn_look_quality.load(),
                                 BbSettings::DrawnLookQualityLow, BbSettings::DrawnLookQualityHigh);
        ImGui::BeginDisabled(drawn_problem != nullptr || !s.graphics_drawn_look);
        const bool changed = ImGui::Combo(label, &quality, names, int(std::size(names)));
        ImGui::EndDisabled();
        Store(s.graphics_drawn_look_quality, quality, changed);
        Hint(drawn_text(DrawnText::QualityHint));
    }
""")),
]

EDITS[S + "bbport_menu_i18n.cpp"] = [
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Un estilo dibujado a mano opcional: pinceladas sobre las superficies del mundo, amplias en paredes y suelos lisos, finas donde hay detalle, y líneas de tinta a lo largo de los bordes de las formas. El fuego, los brillos, la niebla, las partículas y la interfaz se quedan como los dibuja el juego. Los colores no cambian; una línea de tinta es el propio color de la superficie, más oscuro. Se aplica al instante. Aún no hecho: tinta más marcada en los personajes, líneas en los bordes interiores y bordes de sombra pintados."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Un estilo dibujado a mano opcional: pinceladas sobre las superficies del mundo, amplias en paredes y suelos lisos, finas donde hay detalle, y líneas de tinta a lo largo de los bordes de las formas y donde las superficies se juntan en ángulo. El fuego, los brillos, la niebla, las partículas y la interfaz se quedan como los dibuja el juego. Los colores no cambian; una línea de tinta es el propio color de la superficie, más oscuro. Se aplica al instante. Aún no hecho: tinta más marcada en los personajes y bordes de sombra pintados."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Qué tan oscuras son las líneas de tinta a lo largo de los bordes de las formas: pilares, paredes, escalones y figuras frente a lo que hay detrás. 0 es sin líneas. Con la distancia las líneas se vuelven más finas y más tenues, y desaparecen más allá de 120 m; la niebla las cubre como cubre el mundo. No se dibujan en los fotogramas que el estilo pinta justo antes del escalador. Mientras se dibujan líneas, la nitidez adicional del escalador se reduce hasta la mitad. Los colores se mantienen: una línea es el propio color de la superficie, más oscuro. Se aplica al instante."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Qué tan oscuras son las líneas de tinta: a lo largo de los bordes de las formas (pilares, paredes, escalones y figuras frente a lo que hay detrás) y, más claras, donde dos superficies se juntan en ángulo (la esquina de un bloque, el pie de una pared). 0 es sin líneas. Con la distancia las líneas se vuelven más finas y más tenues; las de las esquinas desaparecen más allá de 50 m, las de los bordes más allá de 120 m; la niebla las cubre como cubre el mundo. No se dibujan en los fotogramas que el estilo pinta justo antes del escalador. Mientras se dibujan líneas, la nitidez adicional del escalador se reduce hasta la mitad. Los colores se mantienen: una línea es el propio color de la superficie, más oscuro. Se aplica al instante."},
    {"Drawn look ink quality", "Calidad de las líneas de tinta"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Alta: los bordes se buscan a lo largo de filas, columnas y ambas diagonales y, donde se amontonan muchas líneas (follaje, rejillas, barandillas), se vuelven más tenues, para que los lugares cargados no se pongan negros; ocupa unos 11 MB de memoria de vídeo con una resolución de renderizado de 1080 líneas (44 MB con 2160 líneas) y dibuja como Baja si no hay suficiente. Baja: solo a lo largo de filas y columnas (las líneas inclinadas salen algo más finas), todas las líneas algo más claras, sin ese límite; cuesta menos. Alta por defecto. Se aplica al instante."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Baja"},
    {"High", "Alta"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Um estilo desenhado à mão opcional: pinceladas sobre as superfícies do mundo, largas em paredes e pisos lisos, finas onde há detalhes, e linhas de tinta ao longo das bordas das formas. Fogo, brilhos, névoa, partículas e a interface ficam como o jogo os desenha. As cores não mudam; uma linha de tinta é a própria cor da superfície, mais escura. Aplica-se na hora. Ainda não feito: tinta mais forte nos personagens, linhas nas bordas internas e bordas de sombra pintadas."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Um estilo desenhado à mão opcional: pinceladas sobre as superfícies do mundo, largas em paredes e pisos lisos, finas onde há detalhes, e linhas de tinta ao longo das bordas das formas e onde as superfícies se encontram em ângulo. Fogo, brilhos, névoa, partículas e a interface ficam como o jogo os desenha. As cores não mudam; uma linha de tinta é a própria cor da superfície, mais escura. Aplica-se na hora. Ainda não feito: tinta mais forte nos personagens e bordas de sombra pintadas."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Quão escuras são as linhas de tinta ao longo das bordas das formas: pilares, paredes, degraus e figuras diante do que está atrás delas. 0 é sem linhas. Com a distância as linhas ficam mais finas e mais fracas, e somem além de 120 m; a névoa as cobre como cobre o mundo. Não são desenhadas nos quadros que o estilo pinta logo antes do upscaler. Enquanto há linhas, a nitidez extra do upscaler é reduzida em até metade. As cores se mantêm: uma linha é a própria cor da superfície, mais escura. Aplica-se na hora."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Quão escuras são as linhas de tinta: ao longo das bordas das formas (pilares, paredes, degraus e figuras diante do que está atrás delas) e, mais claras, onde duas superfícies se encontram em ângulo (o canto de um bloco, o pé de uma parede). 0 é sem linhas. Com a distância as linhas ficam mais finas e mais fracas; as dos cantos somem além de 50 m, as das bordas além de 120 m; a névoa as cobre como cobre o mundo. Não são desenhadas nos quadros que o estilo pinta logo antes do upscaler. Enquanto há linhas, a nitidez extra do upscaler é reduzida em até metade. As cores se mantêm: uma linha é a própria cor da superfície, mais escura. Aplica-se na hora."},
    {"Drawn look ink quality", "Qualidade das linhas de tinta"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Alta: as bordas são procuradas ao longo das fileiras, das colunas e das duas diagonais e, onde muitas linhas se juntam (folhagem, grades, parapeitos), elas ficam mais fracas, para que lugares carregados não fiquem pretos; ocupa cerca de 11 MB de memória de vídeo com uma resolução de renderização de 1080 linhas (44 MB com 2160 linhas) e desenha como Baixa se não houver o bastante. Baixa: só ao longo das fileiras e das colunas (linhas inclinadas saem um pouco mais finas), todas as linhas um pouco mais claras, sem esse limite; custa menos. Alta por padrão. Aplica-se na hora."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Baixa"},
    {"High", "Alta"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Un style dessiné à la main facultatif : des coups de pinceau posés sur les surfaces du monde, larges sur les murs et sols unis, fins là où il y a du détail, et des traits d'encre le long des bords des formes. Le feu, les lueurs, le brouillard, les particules et l'interface restent tels que le jeu les dessine. Les couleurs ne changent pas ; un trait d'encre est la couleur propre de la surface, plus sombre. S'applique immédiatement. Pas encore fait : encre plus marquée sur les personnages, traits sur les arêtes intérieures et bords d'ombre peints."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Un style dessiné à la main facultatif : des coups de pinceau posés sur les surfaces du monde, larges sur les murs et sols unis, fins là où il y a du détail, et des traits d'encre le long des bords des formes et là où des surfaces se rejoignent en angle. Le feu, les lueurs, le brouillard, les particules et l'interface restent tels que le jeu les dessine. Les couleurs ne changent pas ; un trait d'encre est la couleur propre de la surface, plus sombre. S'applique immédiatement. Pas encore fait : encre plus marquée sur les personnages et bords d'ombre peints."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "La noirceur des traits d'encre le long des bords des formes : piliers, murs, marches et silhouettes devant ce qui se trouve derrière. 0 signifie aucun trait. Avec la distance les traits s'affinent et pâlissent, et disparaissent au-delà de 120 m ; le brouillard les recouvre comme il recouvre le monde. Pas de traits sur les images que le style peint juste avant l'upscaler. Tant que des traits sont dessinés, la netteté supplémentaire de l'upscaler est réduite de moitié au plus. Les couleurs sont gardées : un trait est la couleur propre de la surface, plus sombre. S'applique immédiatement."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "La noirceur des traits d'encre : le long des bords des formes (piliers, murs, marches et silhouettes devant ce qui se trouve derrière) et, plus clairs, là où deux surfaces se rejoignent en angle (le coin d'un bloc, le pied d'un mur). 0 signifie aucun trait. Avec la distance les traits s'affinent et pâlissent ; ceux des angles disparaissent au-delà de 50 m, ceux des bords au-delà de 120 m ; le brouillard les recouvre comme il recouvre le monde. Pas de traits sur les images que le style peint juste avant l'upscaler. Tant que des traits sont dessinés, la netteté supplémentaire de l'upscaler est réduite de moitié au plus. Les couleurs sont gardées : un trait est la couleur propre de la surface, plus sombre. S'applique immédiatement."},
    {"Drawn look ink quality", "Qualité des traits d'encre"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Haute : les bords sont cherchés le long des rangées, des colonnes et des deux diagonales, et là où beaucoup de traits se pressent (feuillage, grilles, garde-corps), ils sont atténués, pour que les endroits chargés ne virent pas au noir ; elle occupe environ 11 Mo de mémoire vidéo à une résolution de rendu de 1080 lignes (44 Mo à 2160 lignes) et dessine comme Basse s'il n'y en a pas assez. Basse : seulement le long des rangées et des colonnes (les traits obliques sortent un peu plus fins), tous les traits un peu plus clairs, sans cette limite ; coûte moins. Haute par défaut. S'applique immédiatement."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Basse"},
    {"High", "Haute"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Ein optionaler handgezeichneter Stil: Pinselstriche auf den Oberflächen der Welt, breit auf glatten Wänden und Böden, fein, wo es Details gibt, und Tuschelinien entlang der Kanten von Formen. Feuer, Leuchten, Nebel, Partikel und das HUD bleiben so, wie das Spiel sie zeichnet. Die Farben ändern sich nicht; eine Tuschelinie ist die eigene Farbe der Fläche, dunkler. Wirkt sofort. Noch nicht gebaut: kräftigere Tusche an Figuren, Linien an inneren Kanten und gemalte Schattenkanten."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Ein optionaler handgezeichneter Stil: Pinselstriche auf den Oberflächen der Welt, breit auf glatten Wänden und Böden, fein, wo es Details gibt, und Tuschelinien entlang der Kanten von Formen und dort, wo Flächen im Winkel aufeinandertreffen. Feuer, Leuchten, Nebel, Partikel und das HUD bleiben so, wie das Spiel sie zeichnet. Die Farben ändern sich nicht; eine Tuschelinie ist die eigene Farbe der Fläche, dunkler. Wirkt sofort. Noch nicht gebaut: kräftigere Tusche an Figuren und gemalte Schattenkanten."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Wie dunkel die Tuschelinien entlang der Kanten von Formen sind: Säulen, Wände, Stufen und Figuren vor dem, was hinter ihnen liegt. 0 heißt keine Linien. Mit der Entfernung werden die Linien dünner und blasser, jenseits von 120 m verschwinden sie; Nebel deckt sie zu, wie er die Welt zudeckt. Nicht gezeichnet in Bildern, die der Stil direkt vor dem Upscaler malt. Solange Linien gezeichnet werden, wird die zusätzliche Schärfung des Upscalers um bis zur Hälfte gesenkt. Die Farben bleiben: eine Linie ist die eigene Farbe der Fläche, dunkler. Wirkt sofort."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Wie dunkel die Tuschelinien sind: entlang der Kanten von Formen (Säulen, Wände, Stufen und Figuren vor dem, was hinter ihnen liegt) und, heller, dort, wo zwei Flächen im Winkel aufeinandertreffen (die Ecke eines Blocks, der Fuß einer Wand). 0 heißt keine Linien. Mit der Entfernung werden die Linien dünner und blasser; Linien an Ecken verschwinden jenseits von 50 m, Linien an Kanten jenseits von 120 m; Nebel deckt sie zu, wie er die Welt zudeckt. Nicht gezeichnet in Bildern, die der Stil direkt vor dem Upscaler malt. Solange Linien gezeichnet werden, wird die zusätzliche Schärfung des Upscalers um bis zur Hälfte gesenkt. Die Farben bleiben: eine Linie ist die eigene Farbe der Fläche, dunkler. Wirkt sofort."},
    {"Drawn look ink quality", "Qualität der Tuschelinien"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Hoch: Kanten werden entlang der Zeilen, der Spalten und beider Diagonalen gesucht, und wo sich viele Linien drängen (Laub, Gitter, Geländer), werden sie blasser, damit dichte Stellen nicht schwarz werden; belegt etwa 11 MB Videospeicher bei einer Renderauflösung von 1080 Zeilen (44 MB bei 2160 Zeilen) und zeichnet wie Niedrig, wenn nicht genug frei ist. Niedrig: nur entlang der Zeilen und Spalten (schräge Linien fallen etwas dünner aus), jede Linie etwas heller, ohne diese Grenze; kostet weniger. Standardmäßig hoch. Wirkt sofort."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Niedrig"},
    {"High", "Hoch"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Uno stile disegnato a mano facoltativo: pennellate stese sulle superfici del mondo, larghe su pareti e pavimenti lisci, sottili dove ci sono dettagli, e linee d'inchiostro lungo i bordi delle forme. Fuoco, bagliori, nebbia, particelle e HUD restano come li disegna il gioco. I colori non cambiano; una linea d'inchiostro è il colore stesso della superficie, più scuro. Si applica subito. Non ancora fatto: inchiostro più marcato sui personaggi, linee sugli spigoli interni e bordi d'ombra dipinti."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Uno stile disegnato a mano facoltativo: pennellate stese sulle superfici del mondo, larghe su pareti e pavimenti lisci, sottili dove ci sono dettagli, e linee d'inchiostro lungo i bordi delle forme e dove le superfici si incontrano ad angolo. Fuoco, bagliori, nebbia, particelle e HUD restano come li disegna il gioco. I colori non cambiano; una linea d'inchiostro è il colore stesso della superficie, più scuro. Si applica subito. Non ancora fatto: inchiostro più marcato sui personaggi e bordi d'ombra dipinti."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Quanto sono scure le linee d'inchiostro lungo i bordi delle forme: pilastri, muri, gradini e figure davanti a ciò che sta dietro. 0 significa nessuna linea. Con la distanza le linee si assottigliano e si schiariscono, e oltre 120 m spariscono; la nebbia le copre come copre il mondo. Non disegnate nei fotogrammi che lo stile dipinge subito prima dell'upscaler. Finché si disegnano linee, la nitidezza aggiuntiva dell'upscaler è ridotta fino alla metà. I colori restano: una linea è il colore stesso della superficie, più scuro. Si applica subito."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Quanto sono scure le linee d'inchiostro: lungo i bordi delle forme (pilastri, muri, gradini e figure davanti a ciò che sta dietro) e, più chiare, dove due superfici si incontrano ad angolo (lo spigolo di un blocco, il piede di un muro). 0 significa nessuna linea. Con la distanza le linee si assottigliano e si schiariscono; quelle sugli spigoli spariscono oltre 50 m, quelle sui bordi oltre 120 m; la nebbia le copre come copre il mondo. Non disegnate nei fotogrammi che lo stile dipinge subito prima dell'upscaler. Finché si disegnano linee, la nitidezza aggiuntiva dell'upscaler è ridotta fino alla metà. I colori restano: una linea è il colore stesso della superficie, più scuro. Si applica subito."},
    {"Drawn look ink quality", "Qualità delle linee d'inchiostro"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Alta: i bordi vengono cercati lungo righe, colonne ed entrambe le diagonali e, dove molte linee si affollano (fogliame, grate, ringhiere), diventano più tenui, così i punti fitti non diventano neri; occupa circa 11 MB di memoria video con una risoluzione di rendering di 1080 righe (44 MB con 2160 righe) e disegna come Bassa se non basta. Bassa: solo lungo righe e colonne (le linee oblique escono un po' più sottili), ogni linea un po' più chiara, senza questo limite; costa meno. Alta per impostazione predefinita. Si applica subito."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Bassa"},
    {"High", "Alta"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "Opcjonalny styl rysowany ręcznie: pociągnięcia pędzla na powierzchniach świata, szerokie na gładkich ścianach i podłogach, drobne tam, gdzie są szczegóły, oraz linie tuszu wzdłuż krawędzi kształtów. Ogień, poświata, mgła, cząsteczki i interfejs zostają takie, jak rysuje je gra. Kolory się nie zmieniają; linia tuszu to własny kolor powierzchni, tylko ciemniejszy. Działa od razu. Jeszcze nie zrobione: mocniejszy tusz na postaciach, linie na wewnętrznych krawędziach i malowane krawędzie cieni."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "Opcjonalny styl rysowany ręcznie: pociągnięcia pędzla na powierzchniach świata, szerokie na gładkich ścianach i podłogach, drobne tam, gdzie są szczegóły, oraz linie tuszu wzdłuż krawędzi kształtów i tam, gdzie powierzchnie stykają się pod kątem. Ogień, poświata, mgła, cząsteczki i interfejs zostają takie, jak rysuje je gra. Kolory się nie zmieniają; linia tuszu to własny kolor powierzchni, tylko ciemniejszy. Działa od razu. Jeszcze nie zrobione: mocniejszy tusz na postaciach i malowane krawędzie cieni."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Jak ciemne są linie tuszu wzdłuż krawędzi kształtów: filary, ściany, stopnie i postacie na tle tego, co jest za nimi. 0 to brak linii. Z odległością linie stają się cieńsze i bledsze, a dalej niż 120 m znikają; mgła zakrywa je tak, jak zakrywa świat. Nie są rysowane w klatkach, które styl maluje tuż przed upscalerem. Gdy linie są rysowane, dodatkowe wyostrzanie upscalera jest zmniejszane maksymalnie o połowę. Kolory zostają: linia to własny kolor powierzchni, tylko ciemniejszy. Działa od razu."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Jak ciemne są linie tuszu: wzdłuż krawędzi kształtów (filary, ściany, stopnie i postacie na tle tego, co jest za nimi) oraz, jaśniejsze, tam, gdzie dwie powierzchnie stykają się pod kątem (narożnik bloku, podstawa ściany). 0 to brak linii. Z odległością linie stają się cieńsze i bledsze; linie w narożnikach znikają dalej niż 50 m, linie na krawędziach dalej niż 120 m; mgła zakrywa je tak, jak zakrywa świat. Nie są rysowane w klatkach, które styl maluje tuż przed upscalerem. Gdy linie są rysowane, dodatkowe wyostrzanie upscalera jest zmniejszane maksymalnie o połowę. Kolory zostają: linia to własny kolor powierzchni, tylko ciemniejszy. Działa od razu."},
    {"Drawn look ink quality", "Jakość linii tuszu"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Wysoka: krawędzie są szukane wzdłuż wierszy, kolumn i obu przekątnych, a tam, gdzie tłoczy się wiele linii (liście, kraty, balustrady), stają się bledsze, żeby gęste miejsca nie czerniały; zajmuje około 11 MB pamięci wideo przy rozdzielczości renderowania 1080 linii (44 MB przy 2160 liniach) i rysuje jak Niska, gdy jej brakuje. Niska: tylko wzdłuż wierszy i kolumn (ukośne linie wychodzą nieco cieńsze), każda linia nieco jaśniejsza, bez tego ograniczenia; kosztuje mniej. Domyślnie wysoka. Działa od razu."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Niska"},
    {"High", "Wysoka"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "İsteğe bağlı elle çizilmiş bir görünüm: dünyanın yüzeylerine fırça darbeleri, düz duvar ve zeminlerde geniş, ayrıntı olan yerlerde ince, ve biçimlerin kenarları boyunca mürekkep çizgileri. Ateş, parıltılar, sis, parçacıklar ve arayüz oyunun çizdiği gibi kalır. Renkler değişmez; bir mürekkep çizgisi yüzeyin kendi renginin daha koyusudur. Hemen uygulanır. Henüz yapılmadı: karakterlerde daha belirgin mürekkep, iç kenarlarda çizgiler ve boyanmış gölge kenarları."},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "İsteğe bağlı elle çizilmiş bir görünüm: dünyanın yüzeylerine fırça darbeleri, düz duvar ve zeminlerde geniş, ayrıntı olan yerlerde ince, ve biçimlerin kenarları boyunca ve yüzeylerin açıyla birleştiği yerlerde mürekkep çizgileri. Ateş, parıltılar, sis, parçacıklar ve arayüz oyunun çizdiği gibi kalır. Renkler değişmez; bir mürekkep çizgisi yüzeyin kendi renginin daha koyusudur. Hemen uygulanır. Henüz yapılmadı: karakterlerde daha belirgin mürekkep ve boyanmış gölge kenarları."},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Biçimlerin kenarları boyunca mürekkep çizgilerinin ne kadar koyu olduğu: sütunlar, duvarlar, basamaklar ve figürler, arkalarında kalanın önünde. 0 çizgi yok demektir. Çizgiler uzaklıkla incelir ve solar, 120 m'nin ötesinde kaybolur; sis onları dünyayı örttüğü gibi örter. Stilin ölçekleyiciden hemen önce boyadığı karelerde çizilmez. Çizgiler çizilirken ölçekleyicinin ek keskinleştirmesi en fazla yarıya kadar azaltılır. Renkler korunur: bir çizgi yüzeyin kendi renginin daha koyusudur. Hemen uygulanır."},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "Mürekkep çizgilerinin ne kadar koyu olduğu: biçimlerin kenarları boyunca (sütunlar, duvarlar, basamaklar ve figürler, arkalarında kalanın önünde) ve daha açık olarak iki yüzeyin açıyla birleştiği yerlerde (bir bloğun köşesi, bir duvarın dibi). 0 çizgi yok demektir. Çizgiler uzaklıkla incelir ve solar; köşelerdeki çizgiler 50 m'nin, kenar çizgileri 120 m'nin ötesinde kaybolur; sis onları dünyayı örttüğü gibi örter. Stilin ölçekleyiciden hemen önce boyadığı karelerde çizilmez. Çizgiler çizilirken ölçekleyicinin ek keskinleştirmesi en fazla yarıya kadar azaltılır. Renkler korunur: bir çizgi yüzeyin kendi renginin daha koyusudur. Hemen uygulanır."},
    {"Drawn look ink quality", "Mürekkep çizgisi kalitesi"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "Yüksek: kenarlar satırlar, sütunlar ve iki köşegen boyunca aranır ve çok sayıda çizginin sıkıştığı yerlerde (yapraklar, ızgaralar, korkuluklar) çizgiler soluklaştırılır, böylece kalabalık yerler kararmaz; 1080 satırlık işleme çözünürlüğünde yaklaşık 11 MB video belleği kullanır (2160 satırda 44 MB) ve yeterli bellek yoksa Düşük gibi çizer. Düşük: yalnızca satırlar ve sütunlar boyunca (eğik çizgiler biraz daha ince çıkar), her çizgi biraz daha açık, böyle bir sınır yok; daha az maliyetlidir. Varsayılan yüksek. Hemen uygulanır."},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "Düşük"},
    {"High", "Yüksek"},
""")),
    (B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters, lines on inner edges and painted shadow edges.",
     "可选的手绘效果：在世界的表面上画上刷纹，平整的大面用大刷纹，细节多处用小刷纹，并在物体的边上画出暗边。火焰、发光、雾、粒子和界面保持游戏原画。颜色不变；暗边是表面自身的颜色，只是更暗。立即生效。尚未实现：角色身上更重的暗边、内部的边和手绘的阴影边。"},
"""),
     B(r"""
    {"An optional hand-drawn look: brush strokes laid on the world's surfaces, bold on plain walls and floors, fine where there is detail, and ink lines along the edges of shapes and where surfaces meet at an angle. Fire, glows, fog, particles and the HUD stay as the game draws them. Colours are not changed; an ink line is the surface's own colour, darker. Applies at once. Not built yet: heavier ink on characters and painted shadow edges.",
     "可选的手绘效果：在世界的表面上画上刷纹，平整的大面用大刷纹，细节多处用小刷纹，并在物体的边上和表面的转角处画出暗边。火焰、发光、雾、粒子和界面保持游戏原画。颜色不变；暗边是表面自身的颜色，只是更暗。立即生效。尚未实现：角色身上更重的暗边和手绘的阴影边。"},
""")),
    (B(r"""
    {"How dark the ink lines along the edges of shapes are: pillars, walls, steps and figures against what lies behind them. 0 is no lines. Lines grow thinner and fainter with distance and are gone beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "物体边上暗边的强度：物体、人物与后方景物之间的边。0 为没有暗边。暗边随距离变细变弱，超过 120 m 后不再画出；雾也会遮住暗边。效果在超分辨率算法之前才叠加的帧上没有暗边。画出暗边时，超分辨率算法的额外锐化最多降低一半。颜色保持不变：暗边是表面自身的颜色，只是更暗。立即生效。"},
"""),
     B(r"""
    {"How dark the ink lines are: along the edges of shapes (pillars, walls, steps and figures against what lies behind them) and, lighter, where two surfaces meet at an angle (the corner of a block, the foot of a wall). 0 is no lines. Lines grow thinner and fainter with distance; lines at corners are gone beyond 50 m, edge lines beyond 120 m; fog covers them as it covers the world. Not drawn on frames the look paints right before the upscaler. While lines are drawn, the upscaler's extra sharpening is lowered by up to half. Colours are kept: a line is the surface's own colour, darker. Applies at once.",
     "暗边的强度：物体的边上（物体、人物与后方景物之间的边），以及表面的转角处，转角处的暗边较弱。0 为没有暗边。暗边随距离变细变弱；转角处的暗边超过 50 m 后不再画出，物体边上的超过 120 m 后不再画出；雾也会遮住暗边。效果在超分辨率算法之前才叠加的帧上没有暗边。画出暗边时，超分辨率算法的额外锐化最多降低一半。颜色保持不变：暗边是表面自身的颜色，只是更暗。立即生效。"},
    {"Drawn look ink quality", "暗边质量"},
    {"High: edges are looked for along rows, columns and both diagonals, and where many lines crowd together (foliage, grates, railings) they are made fainter, so busy places do not turn black; it takes about 11 MB of video memory at a 1080-line render size (44 MB at 2160 lines) and draws as Low where there is not enough. Low: along rows and columns only (slanted lines come out a little thinner), every line a little lighter, no such limit; it costs less. High by default. Applies at once.",
     "高：在水平、垂直和对角方向上找边；暗边过多处的暗边会变弱，以免画面过暗；在 1080 行的渲染分辨率下约占 11 MB 显存（2160 行时 44 MB），显存不足时按低画。低：只在水平和垂直方向上找边（有些暗边会更细），所有暗边更弱一些，没有这一限制；开销更小。默认为高。立即生效。"},
    // The ink quality row's choices. The tables are one map keyed by the English, so these
    // forms (agreeing with "quality") would serve any later row's "Low" and "High"; such
    // a row needs keys of its own.
    {"Low", "低"},
    {"High", "高"},
""")),
]

EDITS[TESTS + "test_drawn_look_rules.cpp"] = [
    (B(r"""
// (LineScaleOf) and the factor on the upscaler's extra sharpening (InkSharpen). The passes
// themselves run in drawn-look-test, which needs a Vulkan GPU.
"""),
     B(r"""
// (LineScaleOf) and the factor on the upscaler's extra sharpening (InkSharpen); (r58_drawn-look-d2)
// the ink's quality in PassesFor, its numbers from the environment (InkTuneOf), their half
// floats in the ink pass's block (HalfBits, MakeInk) and the edges image's levels (DensityLevel,
// EdgeLevels).
// The passes themselves run in drawn-look-test, which needs a Vulkan GPU.
""")),
    (B(r"""
}
} // namespace
"""),
     B(r"""
}

/// (r58) A half float's value, as GLSL's unpackHalf2x16 gives it.
float HalfValue(std::uint16_t half) {
    const int exponent = (half >> 10) & 31;
    const float mantissa = float(half & 1023u) / 1024.0f;
    const float value = exponent == 0 ? std::ldexp(mantissa, -14)
                                      : std::ldexp(1.0f + mantissa, exponent - 15);
    return (half & 0x8000u) ? -value : value;
}

/// (r58) The two halves of a word of the ink pass's block: x the low 16 bits.
std::array<float, 2> Halves(float word) {
    std::uint32_t bits;
    std::memcpy(&bits, &word, 4);
    return {HalfValue(std::uint16_t(bits & 0xffffu)), HalfValue(std::uint16_t(bits >> 16))};
}

/// (r58) Within a half float's rounding of `want`.
bool NearHalf(float got, double want) {
    return std::abs(got - want) <= std::abs(want) / 1024.0 + 1e-7;
}

/// (r58) A stand-in for std::getenv: the variables in `set`, name=value.
struct Env {
    std::array<const char*, 16> set{};
    const char* operator()(const char* name) const {
        for (const char* entry : set) {
            const size_t n = entry ? std::strlen(name) : 0;
            if (entry && std::strncmp(entry, name, n) == 0 && entry[n] == '=') {
                return entry + n + 1;
            }
        }
        return nullptr;
    }
};
} // namespace
""")),
    (B(r"""
                  Look::Knobs{}.view == Look::ViewOff);
"""),
     B(r"""
                  Look::Knobs{}.view == Look::ViewOff &&
                  Look::Knobs{}.quality == Look::QualityHigh);
""")),
    (B(r"""
                    assert(p.ink == (!late && (ink > 0.0f || page)));
                }
"""),
     B(r"""
                    assert(p.ink == (!late && (ink > 0.0f || page)));
                    // (r58) High, the default: the ink with its limit per area; Low without.
                    assert(p.ink_limit == p.ink);
                    Look::Knobs low = KnobsOf(strength, ink, view);
                    low.quality = Look::QualityLow;
                    const Look::Passes q = Look::PassesFor(low, late);
                    assert(q.strokes == p.strokes && q.lock == p.lock && q.ink == p.ink &&
                           !q.ink_limit);
                    // A quality other than Low (none the settings give) is High.
                    for (const int other : {5, -1}) {
                        Look::Knobs odd = low;
                        odd.quality = other;
                        assert(Look::PassesFor(odd, late).ink_limit == p.ink);
                    }
                }
""")),
    (B(r"""
        assert(ink.strength == 0.35f && ink.brush == 0.8f && ink.characters == 1.6f);
        Look::Params rest = ink;
"""),
     B(r"""
        assert(ink.strength == 0.35f && ink.brush == 0.8f && ink.characters == 1.6f);
        // (r58) The ink's numbers fill cell_bold, back_turn and back_shift; every other word
        // is the frame's.
        Look::Params rest = ink;
""")),
    (B(r"""
        assert(std::memcmp(&rest, &look, sizeof(Look::Params)) == 0);
        assert(ink.flags == look.flags && SameBits(ink.cell_fine, look.cell_fine) &&
               SameBits(ink.cell_bold, look.cell_bold));
"""),
     B(r"""
        rest.cell_bold = look.cell_bold;
        rest.back_turn = look.back_turn;
        rest.back_shift = look.back_shift;
        assert(std::memcmp(&rest, &look, sizeof(Look::Params)) == 0);
        assert(ink.flags == look.flags && SameBits(ink.cell_fine, look.cell_fine));
""")),
    (B(r"""

    std::puts("PASS: drawn look rules");
"""),
     B(r"""

    // (r58) HalfBits: IEEE binary16, rounded to the nearest, ties to even.
    static_assert(Look::HalfBits(0.0f) == 0x0000 && Look::HalfBits(1.0f) == 0x3c00 &&
                  Look::HalfBits(0.5f) == 0x3800 && Look::HalfBits(-2.0f) == 0xc000);
    static_assert(Look::HalfBits(120.0f) == 0x5780 && Look::HalfBits(16.0f) == 0x4c00 &&
                  Look::HalfBits(1000.0f) == 0x63d0 && Look::HalfBits(65504.0f) == 0x7bff);
    static_assert(Look::HalfBits(0.7f) == 0x399a && Look::HalfBits(0.2f) == 0x3266 &&
                  Look::HalfBits(0.45f) == 0x3733);
    static_assert(Look::HalfBits(1e6f) == 0x7bff && Look::HalfBits(-1e6f) == 0xfbff);
    // A tie: 1 + 2^-11 lies halfway between 1 and the next half up, and goes to the even one.
    static_assert(Look::HalfBits(1.0f + 1.0f / 2048.0f) == 0x3c00 &&
                  Look::HalfBits(1.0f + 3.0f / 2048.0f) == 0x3c02);
    static_assert(Look::HalfBits(0x1p-24f) == 0x0001 && Look::HalfBits(0x1p-14f) == 0x0400 &&
                  Look::HalfBits(0x1p-25f) == 0x0000 && Look::HalfBits(0x3p-25f) == 0x0002);
    assert(Look::HalfBits(NAN) == 0);
    for (float v = 0.001f; v < 2000.0f; v *= 1.37f) {
        assert(NearHalf(HalfValue(Look::HalfBits(v)), v));
    }
    {
        const auto pair = Halves(Look::HalfPair(0.25f, 40.0f));
        assert(pair[0] == 0.25f && pair[1] == 40.0f);
    }

    // (r58) InkTune's defaults, as the plan has them, and what MakeInk carries of them.
    {
        constexpr Look::InkTune d{};
        static_assert(d.crease_deg[0] == 30.0f && d.crease_deg[1] == 50.0f && d.crease_px == 1.0f &&
                      d.crease_weight == 0.5f && d.crease_fade_m[0] == 20.0f &&
                      d.crease_fade_m[1] == 50.0f && d.line_fade_m[0] == 40.0f &&
                      d.line_fade_m[1] == 120.0f && d.density[0] == 0.20f &&
                      d.density[1] == 0.45f && d.density_px == 16.0f && d.low_factor == 0.7f);
        Look::InkTune tune;
        tune.crease_deg = {25.0f, 60.0f};
        tune.crease_px = 1.5f;
        tune.crease_weight = 0.25f;
        tune.crease_fade_m = {10.0f, 30.0f};
        tune.line_fade_m = {60.0f, 200.0f};
        tune.density = {0.3f, 0.9f};
        tune.density_px = 24.0f;
        tune.low_factor = 0.6f;
        const std::array<float, 12> inv_view{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const Look::Params look = Look::Make(Look::Knobs{}, inv_view, {1.2f, 2.1f, 1.0f, -0.1f},
                                             1920, 1080, {0.0f, 0.0f}, true, true);
        for (const Look::InkTune& t : {d, tune}) {
            const Look::Params ink = Look::MakeInk(look, 0.35f, 0.35f, 1.0f, t);
            const auto cosines = Halves(ink.cell_bold);
            assert(NearHalf(cosines[0], std::cos(t.crease_deg[1] * 3.14159265358979 / 180.0)) &&
                   NearHalf(cosines[1], std::cos(t.crease_deg[0] * 3.14159265358979 / 180.0)));
            const auto width = Halves(ink.back_turn[0]), crease_fade = Halves(ink.back_turn[1]),
                       line_fade = Halves(ink.back_turn[2]), density = Halves(ink.back_shift[0]),
                       place = Halves(ink.back_shift[1]);
            assert(NearHalf(width[0], t.crease_px) && NearHalf(width[1], t.crease_weight));
            assert(NearHalf(crease_fade[0], t.crease_fade_m[0]) &&
                   NearHalf(crease_fade[1], t.crease_fade_m[1]));
            assert(NearHalf(line_fade[0], t.line_fade_m[0]) &&
                   NearHalf(line_fade[1], t.line_fade_m[1]));
            assert(NearHalf(density[0], t.density[0]) && NearHalf(density[1], t.density[1]));
            assert(NearHalf(place[0], t.density_px) && NearHalf(place[1], t.low_factor));
            // The level the limit per area reads, as a float, at the block's scene height.
            assert(ink.back_shift[2] == Look::DensityLevel(1080, t.density_px));
        }
        // The defaults that are whole numbers go exactly (the shader's fades are r55's).
        const Look::Params ink = Look::MakeInk(look, 0.35f, 0.35f, 1.0f);
        assert(Halves(ink.back_turn[2])[0] == 40.0f && Halves(ink.back_turn[2])[1] == 120.0f &&
               Halves(ink.back_shift[1])[0] == 16.0f);
    }

    // (r58) The environment: a number alone (blanks allowed), clamped; a pair of rising numbers,
    // clamped; anything else keeps the default.
    assert(Look::TuneValueOf(nullptr, 0.5f, 0.0f, 1.0f) == 0.5f);
    assert(Look::TuneValueOf("", 0.5f, 0.0f, 1.0f) == 0.5f);
    assert(Look::TuneValueOf("0.25", 0.5f, 0.0f, 1.0f) == 0.25f);
    assert(Look::TuneValueOf(" 0.25 ", 0.5f, 0.0f, 1.0f) == 0.25f);
    assert(Look::TuneValueOf("7", 0.5f, 0.0f, 1.0f) == 1.0f);
    assert(Look::TuneValueOf("-7", 0.5f, 0.0f, 1.0f) == 0.0f);
    assert(Look::TuneValueOf("0.25x", 0.5f, 0.0f, 1.0f) == 0.5f);
    assert(Look::TuneValueOf("strong", 0.5f, 0.0f, 1.0f) == 0.5f);
    assert(Look::TuneValueOf("nan", 0.5f, 0.0f, 1.0f) == 0.5f);
    assert(Look::TuneValueOf("inf", 0.5f, 0.0f, 1.0f) == 0.5f);
    {
        const std::array<float, 2> d{20.0f, 50.0f};
        const auto pair = [&](const char* text) {
            return Look::TunePairOf(text, d, 1.0f, 1000.0f);
        };
        assert(pair(nullptr) == d && pair("") == d && pair("30") == d && pair("30,") == d);
        assert((pair("10,30") == std::array<float, 2>{10.0f, 30.0f}));
        assert((pair(" 10 , 30 ") == std::array<float, 2>{10.0f, 30.0f}));
        assert((pair("0,5000") == std::array<float, 2>{1.0f, 1000.0f}));
        assert(pair("30,10") == d && pair("30,30") == d && pair("2000,3000") == d);
        assert(pair("10,30,50") == d && pair("10;30") == d && pair("a,b") == d &&
               pair("nan,30") == d && pair("10,inf") == d);
    }
    {
        // Nothing set: the defaults; each variable reaches its field.
        const Look::InkTune none = Look::InkTuneOf(Env{});
        const Look::InkTune d{};
        assert(none.crease_deg == d.crease_deg && none.crease_px == d.crease_px &&
               none.crease_weight == d.crease_weight && none.crease_fade_m == d.crease_fade_m &&
               none.line_fade_m == d.line_fade_m && none.density == d.density &&
               none.density_px == d.density_px && none.low_factor == d.low_factor);
        Env env;
        env.set = {"BB_DRAWN_LOOK_CREASE_ANGLE=25,60", "BB_DRAWN_LOOK_CREASE_WIDTH=9",
                   "BB_DRAWN_LOOK_CREASE_WEIGHT=0.25", "BB_DRAWN_LOOK_CREASE_FADE=10,30",
                   "BB_DRAWN_LOOK_LINE_FADE=60,200",   "BB_DRAWN_LOOK_DENSITY=0.3,0.9",
                   "BB_DRAWN_LOOK_DENSITY_SIZE=1",     "BB_DRAWN_LOOK_LOW_FACTOR=0.6"};
        const Look::InkTune t = Look::InkTuneOf(env);
        assert((t.crease_deg == std::array<float, 2>{25.0f, 60.0f}) && t.crease_px == 3.0f &&
               t.crease_weight == 0.25f &&
               (t.crease_fade_m == std::array<float, 2>{10.0f, 30.0f}) &&
               (t.line_fade_m == std::array<float, 2>{60.0f, 200.0f}) &&
               (t.density == std::array<float, 2>{0.3f, 0.9f}) && t.density_px == 4.0f &&
               t.low_factor == 0.6f);
        // A pair out of order, or angles that clamp to the same: the default.
        Env bad;
        bad.set = {"BB_DRAWN_LOOK_CREASE_ANGLE=50,30", "BB_DRAWN_LOOK_DENSITY=0.5",
                   "BB_DRAWN_LOOK_CREASE_FADE=90,95.5x", "BB_DRAWN_LOOK_LINE_FADE=1,1"};
        const Look::InkTune b = Look::InkTuneOf(bad);
        assert(b.crease_deg == d.crease_deg && b.density == d.density &&
               b.crease_fade_m == d.crease_fade_m && b.line_fade_m == d.line_fade_m);
        Env angles;
        angles.set = {"BB_DRAWN_LOOK_CREASE_ANGLE=86,89"};
        assert(Look::InkTuneOf(angles).crease_deg == d.crease_deg);
        static_assert(std::size(Look::InkTuneNames) == 8);
        // Every variable out of its range, above and below: clamped to the range's ends.
        Env over;
        over.set = {"BB_DRAWN_LOOK_CREASE_ANGLE=10,90", "BB_DRAWN_LOOK_CREASE_WIDTH=0.1",
                    "BB_DRAWN_LOOK_CREASE_WEIGHT=5",    "BB_DRAWN_LOOK_CREASE_FADE=0,5",
                    "BB_DRAWN_LOOK_LINE_FADE=0,2000",   "BB_DRAWN_LOOK_DENSITY=-1,3",
                    "BB_DRAWN_LOOK_DENSITY_SIZE=100",   "BB_DRAWN_LOOK_LOW_FACTOR=2"};
        const Look::InkTune o = Look::InkTuneOf(over);
        assert((o.crease_deg == std::array<float, 2>{10.0f, 85.0f}) && o.crease_px == 0.25f &&
               o.crease_weight == 1.0f &&
               (o.crease_fade_m == std::array<float, 2>{1.0f, 5.0f}) &&
               (o.line_fade_m == std::array<float, 2>{1.0f, 1000.0f}) &&
               (o.density == std::array<float, 2>{0.0f, 2.0f}) && o.density_px == 64.0f &&
               o.low_factor == 1.0f);
        Env under;
        under.set = {"BB_DRAWN_LOOK_CREASE_ANGLE=0,40", "BB_DRAWN_LOOK_CREASE_WEIGHT=-1",
                     "BB_DRAWN_LOOK_LOW_FACTOR=-1", "BB_DRAWN_LOOK_CREASE_FADE=-5,2000"};
        const Look::InkTune u = Look::InkTuneOf(under);
        assert((u.crease_deg == std::array<float, 2>{5.0f, 40.0f}) && u.crease_weight == 0.0f &&
               u.low_factor == 0.0f &&
               (u.crease_fade_m == std::array<float, 2>{1.0f, 1000.0f}));
    }

    // (r58) The level the limit per area reads: 1.5 under the level of a box of 16 pixels of a
    // 1080-line scene (level 4 at 1080 lines, 5 at 2160, 3 at 540), 0 at least.
    static_assert(Look::DensityLevelBelow == 1.5);
    assert(Look::DensityLevel(1080, 16.0f) == 2.5f && Look::DensityLevel(2160, 16.0f) == 3.5f &&
           Look::DensityLevel(540, 16.0f) == 1.5f && Look::DensityLevel(1080, 4.0f) == 0.5f &&
           Look::DensityLevel(1080, 64.0f) == 4.5f);
    assert(std::abs(Look::DensityLevel(1440, 16.0f) - 2.915f) < 1e-3f);
    assert(Look::DensityLevel(540, 4.0f) == 0.0f && Look::DensityLevel(0, 16.0f) == 0.0f);
    // The edges image's levels: down to the one above that level, for the read between two.
    assert(Look::EdgeLevels(1920, 1080, 16.0f) == 4);
    assert(Look::EdgeLevels(3840, 2160, 16.0f) == 5);
    assert(Look::EdgeLevels(960, 540, 16.0f) == 3);
    assert(Look::EdgeLevels(2560, 1440, 16.0f) == 4); // level 2.92: levels 2 and 3 are read
    assert(Look::EdgeLevels(1920, 1080, 4.0f) == 2);
    assert(Look::EdgeLevels(1920, 1080, 64.0f) == 6);
    assert(Look::EdgeLevels(16, 16, 16.0f) == 2);   // level 0: levels 0 and 1 (weight 0)
    assert(Look::EdgeLevels(1, 1, 16.0f) == 1);     // an image of one texel has one level
    assert(Look::EdgeLevels(0, 0, 16.0f) == 1);
    static_assert(Look::EdgeBytesPerPixel * 3 >= 4 * 4); // RGBA8 and a third more for the levels

    std::puts("PASS: drawn look rules");
""")),
]

EDITS[TESTS + "test_drawn_look.cpp"] = [
    (B(r"""
//    jitter; on top of the strokes; the ink page (test view 3).
//
"""),
     B(r"""
//    jitter; on top of the strokes; the ink page (test view 3).
//  - (r58_drawn-look-d2) at High quality (paint_ink.comp EDGES, DOWN, APPLY, as the renderer
//    records them) and at Low (the one pass): creases on a box's 90 degree corners and at its
//    foot, none on its flat faces nor inside the round column, none from bumpy G-buffer normals;
//    a field of 1-pixel spikes held under 0.3 by the limit per area while a lone spike keeps its
//    line; Low at 0.7 of High; the crease weight and both fades taken from the ink's numbers
//    (DrawnLookParams::InkTune); no creases on the box seen from about 50 m; the limit per area
//    nearly the same wherever a busy place lies against the edges image's texels (rows and
//    columns of spikes moved a pixel at a time, at 1920x1080 and 960x540); evenly spaced posts
//    not thinned below half of Low's weight.
//
""")),
    (B(r"""
#include "video_core/host_shaders/paint_ink_comp.h"
"""),
     B(r"""
#include "video_core/host_shaders/paint_ink_apply_comp.h"
#include "video_core/host_shaders/paint_ink_comp.h"
#include "video_core/host_shaders/paint_ink_down_comp.h"
#include "video_core/host_shaders/paint_ink_edges_comp.h"
""")),
    (B(r"""
enum Surface : u8 { Sky, Floor, BackWall, SideWall, Column, Ball };
"""),
     B(r"""
// (r58_drawn-look-d2) Box: only in a scene made with `with_box`.
enum Surface : u8 { Sky, Floor, BackWall, SideWall, Column, Ball, Box, SurfaceCount };
""")),
    (B(r"""
Hit Cast(const Vec3& o, const Vec3& d) {
"""),
     B(r"""
Hit Cast(const Vec3& o, const Vec3& d, bool with_box = false) {
""")),
    (B(r"""
    }
    return hit;
"""),
     B(r"""
    }
    if (with_box) {
        // (r58_drawn-look-d2) A box a metre wide standing on the floor: 90 degree corners where
        // its faces meet each other and the floor (creases), its outline against the back wall.
        const Vec3 lo{3.0, 0.0, 4.0}, hi{4.0, 1.0, 5.0};
        double enter = -1e30, leave = 1e30;
        int axis = -1;
        bool hit_box = true;
        for (int k = 0; k < 3 && hit_box; ++k) {
            if (std::abs(d[k]) < 1e-12) {
                hit_box = o[k] > lo[k] && o[k] < hi[k];
                continue;
            }
            double t0 = (lo[k] - o[k]) / d[k], t1 = (hi[k] - o[k]) / d[k];
            if (t0 > t1) {
                std::swap(t0, t1);
            }
            if (t0 > enter) {
                enter = t0;
                axis = k;
            }
            leave = std::min(leave, t1);
        }
        if (hit_box && axis >= 0 && enter < leave) {
            Vec3 normal{0, 0, 0};
            normal[axis] = d[axis] > 0.0 ? -1.0 : 1.0;
            take(Box, enter, normal);
        }
    }
    return hit;
""")),
    (B(r"""
                const Vectors& vectors = {}) {
"""),
     B(r"""
                const Vectors& vectors = {}, bool with_box = false) {
""")),
    (B(r"""
                                      {0.34f, 0.33f, 0.30f}, {0.25f, 0.08f, 0.07f}};
"""),
     B(r"""
                                      {0.34f, 0.33f, 0.30f}, {0.25f, 0.08f, 0.07f},
                                      {0.28f, 0.22f, 0.16f}};
    static_assert(std::size(Colours) == SurfaceCount);
""")),
    (B(r"""
            const Hit hit = Cast(camera.pos, dir);
"""),
     B(r"""
            const Hit hit = Cast(camera.pos, dir, with_box);
""")),
    (B(r"""
        ink = MakePass({eCombinedImageSampler, eSampledImage, eStorageImage}, PAINT_INK_COMP);
        sampler = Check(device->createSamplerUnique(
"""),
     B(r"""
        ink = MakePass({eCombinedImageSampler, eSampledImage, eStorageImage}, PAINT_INK_COMP);
        ink_edges = MakePass({eSampledImage, eStorageImage}, PAINT_INK_EDGES_COMP);
        ink_down = MakePass({eCombinedImageSampler, eStorageImage}, PAINT_INK_DOWN_COMP);
        ink_apply = MakePass({eCombinedImageSampler, eSampledImage, eStorageImage,
                              eCombinedImageSampler},
                             PAINT_INK_APPLY_COMP);
        sampler = Check(device->createSamplerUnique(
""")),
    (B(r"""
    /// the ink lines' knobs (r55_drawn-look-lines; 0: no ink, as before).
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params, float ink_world = 0.0f,
                           float line_scale = 1.0f) {
"""),
     B(r"""
    /// the ink lines' knobs (r55_drawn-look-lines; 0: no ink, as before). (r58_drawn-look-d2)
    /// `quality`, `tune`: the ink's quality (High: its three passes) and numbers.
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params, float ink_world = 0.0f,
                           float line_scale = 1.0f, int quality = Look::QualityHigh,
                           const Look::InkTune& tune = {}) {
""")),
    (B(r"""
        const Look::Passes passes = Look::PassesFor(knobs, false);
        Load(scene);
"""),
     B(r"""
        knobs.quality = quality;
        const Look::Passes passes = Look::PassesFor(knobs, false);
        Load(scene);
        if (passes.ink_limit) {
            EnsureEdges(Look::EdgeLevels(width, height, tune.density_px));
        }
""")),
    (B(r"""
            RecordInk(Look::MakeInk(params, ink_world, knobs.outlines, line_scale));
"""),
     B(r"""
            RecordInk(Look::MakeInk(params, ink_world, knobs.outlines, line_scale, tune),
                      passes.ink_limit);
""")),
    (B(r"""
    /// (r55_drawn-look-lines) As vk_drawn_look.cpp records it, last.
    void RecordInk(const Look::Params& ink_params) {
        using enum vk::DescriptorType;
        const std::array infos{Info(copy.view, true), Info(depth.view), Info(colour.view)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eStorageImage, &infos[2])};
        Dispatch(ink, ink_params, writes, width, height);
"""),
     B(r"""
    /// (r55_drawn-look-lines) As vk_drawn_look.cpp records it, last. (r58_drawn-look-d2)
    /// `limit`: High, the edges image, its levels and the lines limited per area.
    void RecordInk(const Look::Params& ink_params, bool limit) {
        using enum vk::DescriptorType;
        if (!limit) {
            const std::array infos{Info(copy.view, true), Info(depth.view), Info(colour.view)};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eSampledImage, &infos[1]),
                                    Write(2, eStorageImage, &infos[2])};
            Dispatch(ink, ink_params, writes, width, height);
            return;
        }
        // Written anew every frame, every level, as in the renderer.
        const vk::ImageMemoryBarrier to_general{
            .dstAccessMask = vk::AccessFlagBits::eMemoryRead | vk::AccessFlagBits::eMemoryWrite,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = *edges.image,
            .subresourceRange = Range};
        command.pipelineBarrier(vk::PipelineStageFlagBits::eAllCommands,
                                vk::PipelineStageFlagBits::eAllCommands, {}, {}, {}, to_general);
        {
            const std::array infos{Info(depth.view), Info(edges.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(ink_edges, ink_params, writes, width, height);
        }
        for (u32 n = 1; n < edges.levels.size(); ++n) {
            const std::array infos{Info(edges.levels[n - 1], true), Info(edges.levels[n])};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(ink_down, ink_params, writes, std::max(width >> n, 1u),
                     std::max(height >> n, 1u));
        }
        const std::array infos{Info(copy.view, true), Info(depth.view), Info(colour.view),
                               Info(edges.view, true)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eStorageImage, &infos[2]),
                                Write(3, eCombinedImageSampler, &infos[3])};
        Dispatch(ink_apply, ink_params, writes, width, height);
    }

    /// (r58_drawn-look-d2) The edges image at this size with `levels` levels (rgba8, as the
    /// renderer makes it).
    void EnsureEdges(u32 levels) {
        if (edges.image && edges.levels.size() == levels && edges_width == width &&
            edges_height == height) {
            return;
        }
        edges = MakeImage(vk::Format::eR8G8B8A8Unorm, vk::ImageUsageFlagBits::eStorage, width,
                          height, true, levels);
        edges_width = width;
        edges_height = height;
""")),
    (B(r"""
    /// `all_levels`: with every level down to one texel, else the one.
    Image MakeImage(vk::Format format, vk::ImageUsageFlags usage, u32 w, u32 h, bool all_levels) {
        Image made;
        const u32 levels = all_levels ? u32(std::bit_width(std::max(w, h))) : 1;
"""),
     B(r"""
    /// `all_levels`: with every level down to one texel, else the one. (r58_drawn-look-d2)
    /// `level_count`: at most that many levels (0: no such limit).
    Image MakeImage(vk::Format format, vk::ImageUsageFlags usage, u32 w, u32 h, bool all_levels,
                    u32 level_count = 0) {
        Image made;
        u32 levels = all_levels ? u32(std::bit_width(std::max(w, h))) : 1;
        if (level_count != 0) {
            levels = std::min(levels, level_count);
        }
""")),
    (B(r"""
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;
    vk::UniqueSampler sampler;
"""),
     B(r"""
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock, ink;
    Pass ink_edges, ink_down, ink_apply; ///< (r58_drawn-look-d2) High quality's ink
    vk::UniqueSampler sampler;
""")),
    (B(r"""
    Image colour, copy, marks, means, depth, normal, motion;
    vk::UniqueBuffer staging;
"""),
     B(r"""
    Image colour, copy, marks, means, depth, normal, motion;
    Image edges; ///< (r58_drawn-look-d2) made by the first High run at a size
    u32 edges_width = 0, edges_height = 0;
    vk::UniqueBuffer staging;
""")),
    (B(r"""
    std::array<Share, 6> inner_of{}; ///< `inner` by Surface
"""),
     B(r"""
    std::array<Share, SurfaceCount> inner_of{}; ///< `inner` by Surface
""")),
    (B(r"""
                         "full line (half the weight)");
        }
    }
    if (argc > 1) {
"""),
     B(r"""
                         "full line (half the weight)");
        }

        // bbport (r58_drawn-look-d2): creases, the limit per area, the fades and the two
        // qualities. The weights are read from the ink page (test view 3), which is the key's
        // grey times 1 - weight on every pixel that is not sky, every line at ink 1.
        const auto page_of = [&](const Scene& in, const Camera& camera, int quality,
                                 const Look::InkTune& tune) {
            return gpu.Run(in, Words(large, camera, Look::ViewInk, true, false, 0.0f), 1.0f, 1.0f,
                           quality, tune);
        };
        const auto weights_of = [&](const Scene& in, const std::vector<Half4>& page) {
            std::vector<u16> greys;
            for (u32 i = 0; i < count; ++i) {
                if (in.surface[i] != Sky && plain(in, i)) {
                    greys.push_back(page[i][0]);
                }
            }
            assert(!greys.empty());
            std::sort(greys.begin(), greys.end());
            const double paper = FromHalf(greys[greys.size() / 2]);
            std::vector<double> weight(count, 0.0);
            for (u32 i = 0; i < count; ++i) {
                if (in.surface[i] != Sky) {
                    weight[i] = 1.0 - FromHalf(page[i][0]) / paper;
                }
            }
            return weight;
        };
        const auto normal_of = [](const Scene& in, u32 i) {
            return Vec3{in.normal[i][0] / 127.5 - 1.0, in.normal[i][1] / 127.5 - 1.0,
                        in.normal[i][2] / 127.5 - 1.0};
        };
        // The box's crease pixels: a 4-neighbour of the box or of the floor whose face turns by
        // 60 degrees or more and that lies within `apart_m` (no gap between them). Its face
        // pixels: 7x7 of the box, all of one face.
        const auto box_pixels = [&](const Scene& in, double apart_m, std::vector<u32>& creases,
                                    std::vector<u32>& faces) {
            creases.clear();
            faces.clear();
            for (u32 y = 3; y + 3 < h; ++y) {
                for (u32 x = 3; x + 3 < w; ++x) {
                    const u32 i = y * w + x;
                    if (in.surface[i] != Box) {
                        continue;
                    }
                    bool crease = false;
                    for (const u32 j : {i - 1, i + 1, i - w, i + w}) {
                        const Vec3 apart = Add(in.world[j], in.world[i], -1.0);
                        crease |= (in.surface[j] == Box || in.surface[j] == Floor) &&
                                  Dot(normal_of(in, i), normal_of(in, j)) < 0.5 &&
                                  Dot(apart, apart) < apart_m * apart_m;
                    }
                    if (crease) {
                        creases.push_back(i);
                    }
                    bool face = plain(in, i);
                    for (int dy = -3; face && dy <= 3; ++dy) {
                        for (int dx = -3; dx <= 3; ++dx) {
                            face &= in.normal[u32(int(y) + dy) * w + u32(int(x) + dx)] ==
                                    in.normal[i];
                        }
                    }
                    if (face) {
                        faces.push_back(i);
                    }
                }
            }
        };
        // The share of `pixels` with a weight of at least `least`, and their largest weight.
        const auto share_at = [](const std::vector<double>& weight, const std::vector<u32>& pixels,
                                 double least) {
            u32 at = 0;
            for (const u32 i : pixels) {
                at += weight[i] >= least;
            }
            return pixels.empty() ? 0.0 : double(at) / pixels.size();
        };
        const auto most_of = [](const std::vector<double>& weight, const std::vector<u32>& pixels) {
            double most = 0.0;
            for (const u32 i : pixels) {
                most = std::max(most, weight[i]);
            }
            return most;
        };
        const Look::InkTune tune{};
        const Scene boxed = MakeScene(large, straight, Paint::Lit, 1.0f, {}, true);
        std::vector<u32> creases, faces;
        box_pixels(boxed, 0.05, creases, faces);
        std::vector<u32> ball_rim;
        for (u32 i = 0; i < count; ++i) {
            if (rim(boxed, i, Ball, Sky)) {
                ball_rim.push_back(i);
            }
        }
        const auto high = weights_of(boxed, page_of(boxed, straight, Look::QualityHigh, tune));
        const auto low = weights_of(boxed, page_of(boxed, straight, Look::QualityLow, tune));
        {
            // The plain column's inside (a true cylinder: its facets at this distance turn by a
            // degree or two from pixel to pixel) and the box's faces.
            std::vector<u32> column_inside;
            for (u32 i = 0; i < count; ++i) {
                if (boxed.surface[i] == Column && plain(boxed, i)) {
                    column_inside.push_back(i);
                }
            }
            std::printf("creases (High): %u crease pixels of the box, %.0f%% at weight 0.1 or "
                        "more (largest %.3f); %u face pixels, largest weight %.4f; %u pixels "
                        "inside the column, largest weight %.4f\n",
                        u32(creases.size()), 100.0 * share_at(high, creases, 0.1),
                        most_of(high, creases), u32(faces.size()), most_of(high, faces),
                        u32(column_inside.size()), most_of(high, column_inside));
            std::printf("creases (Low): %.0f%% of the crease pixels at weight 0.07 or more; face "
                        "pixels at most %.4f, the column's inside at most %.4f\n",
                        100.0 * share_at(low, creases, 0.07), most_of(low, faces),
                        most_of(low, column_inside));
            Expect(creases.size() > 300 && share_at(high, creases, 0.1) >= 0.8,
                   "a box's 90 degree corners and its foot get a crease line (High)");
            Expect(share_at(low, creases, 0.07) >= 0.8, "and at Low");
            Expect(faces.size() > 2000 && most_of(high, faces) < 0.01 &&
                       most_of(low, faces) < 0.01,
                   "a box's flat faces get no crease");
            Expect(column_inside.size() > 5000 && most_of(high, column_inside) < 0.01 &&
                       most_of(low, column_inside) < 0.01,
                   "the round column's inside gets no crease");
        }
        {
            // Bumpy G-buffer normals on the back wall and the box (the game's normal maps):
            // the creases come from the depth alone, so the ink page is the same to the bit.
            Scene bumpy = boxed;
            for (u32 i = 0; i < count; ++i) {
                if (bumpy.surface[i] == BackWall || bumpy.surface[i] == Box) {
                    const u32 r = Hash(i);
                    for (int k = 0; k < 3; ++k) {
                        bumpy.normal[i][k] = u8((r >> (8 * k)) & 0xff);
                    }
                }
            }
            const auto flat_page = page_of(boxed, straight, Look::QualityHigh, tune);
            const auto bumpy_page = page_of(bumpy, straight, Look::QualityHigh, tune);
            u32 differ = 0, wall_plain = 0, wall_inked = 0;
            const auto bumpy_weight = weights_of(bumpy, bumpy_page);
            for (u32 i = 0; i < count; ++i) {
                differ += !(flat_page[i] == bumpy_page[i]);
                if (bumpy.surface[i] == BackWall && plain(bumpy, i)) {
                    ++wall_plain;
                    wall_inked += bumpy_weight[i] > 0.0;
                }
            }
            std::printf("bumpy G-buffer normals on the back wall and the box: %u pixels of the "
                        "ink page differ; %u of %u plain back wall pixels inked\n",
                        differ, wall_inked, wall_plain);
            Expect(differ == 0 && wall_plain > 50000 && wall_inked == 0,
                   "a wall with bumpy G-buffer normals gets no crease");
        }
        {
            // Low at LOW_FACTOR of High where the limit per area does not bite: the column's
            // straight sides against the back wall, found along the x axis by both.
            double sum_high = 0.0, sum_low = 0.0;
            u32 of = 0;
            for (u32 i = 0; i < count; ++i) {
                if (rim(boxed, i, Column, BackWall) &&
                    (boxed.surface[i - 1] == BackWall || boxed.surface[i + 1] == BackWall)) {
                    sum_high += high[i];
                    sum_low += low[i];
                    ++of;
                }
            }
            const double share = sum_high > 0.0 ? sum_low / sum_high : 0.0;
            std::printf("the column's sides (%u pixels): Low's weight %.3f of High's\n", of, share);
            Expect(of > 300 && share > 0.65 && share < 0.75, "Low draws a line at 0.7 of High");
        }
        {
            // The crease weight at 0 (BB_DRAWN_LOOK_CREASE_WEIGHT=0): no creases; the crease fade
            // at 1 to 2 m: none on the box 6 m away; the silhouettes' fade at 1 to 2 m: no ball
            // outline, the creases kept. Some crease pixels lie on a silhouette as well (the top
            // face seen at a grazing angle, against the front face falling away below it, as
            // r55 draws it): `pure` are those without one, the crease alone.
            Look::InkTune none = tune, near_creases = tune, near_lines = tune;
            none.crease_weight = 0.0f;
            near_creases.crease_fade_m = {1.0f, 2.0f};
            near_lines.line_fade_m = {1.0f, 2.0f};
            const auto w_none =
                weights_of(boxed, page_of(boxed, straight, Look::QualityHigh, none));
            const auto w_crease =
                weights_of(boxed, page_of(boxed, straight, Look::QualityHigh, near_creases));
            const auto w_lines =
                weights_of(boxed, page_of(boxed, straight, Look::QualityHigh, near_lines));
            std::vector<u32> pure;
            for (const u32 i : creases) {
                if (w_none[i] < 0.02) {
                    pure.push_back(i);
                }
            }
            std::printf("crease weight 0: %u of %u crease pixels left without a line (the others "
                        "on a silhouette too), %.0f%% of the ball's outline at 0.35 or more; "
                        "those %u at High's numbers: %.0f%% at 0.1 or more; crease fade 1..2 m: "
                        "they are at most %.4f; line fade 1..2 m: the ball's outline at most "
                        "%.4f, %.0f%% of the crease pixels at 0.1 or more\n",
                        u32(pure.size()), u32(creases.size()),
                        100.0 * share_at(w_none, ball_rim, 0.35), u32(pure.size()),
                        100.0 * share_at(high, pure, 0.1), most_of(w_crease, pure),
                        most_of(w_lines, ball_rim), 100.0 * share_at(w_lines, creases, 0.1));
            Expect(pure.size() >= creases.size() / 2 && share_at(high, pure, 0.1) >= 0.8 &&
                       share_at(w_none, ball_rim, 0.35) >= 0.9,
                   "the crease weight 0 takes the creases' line and keeps the silhouettes");
            Expect(most_of(w_crease, pure) < 0.02, "creases fade out at the crease fade");
            Expect(most_of(w_lines, ball_rim) < 0.02 && share_at(w_lines, creases, 0.1) >= 0.8,
                   "silhouettes fade out at the line fade, the creases stay");
        }
        {
            // Far: the box seen from about 50 m, past the crease fade (20 to 50 m), from above
            // (its top and front faces both in sight): the crease weight makes no difference
            // there. Seen level from about 45 m, its outline against the back wall (5 m behind
            // it), within the silhouettes' fade (40 to 120 m), keeps a faint line.
            const Camera above{.pos = {0.3, 20.0, -40.0}, .yaw = 0.0717, .pitch = -0.412};
            const Scene from_above = MakeScene(large, above, Paint::Lit, 1.0f, {}, true);
            std::vector<u32> far_creases, far_faces, far_rim;
            box_pixels(from_above, 0.25, far_creases, far_faces);
            Look::InkTune none = tune;
            none.crease_weight = 0.0f;
            const auto far_w =
                weights_of(from_above, page_of(from_above, above, Look::QualityHigh, tune));
            const auto far_none =
                weights_of(from_above, page_of(from_above, above, Look::QualityHigh, none));
            double far_apart = 0.0;
            for (const u32 i : far_creases) {
                far_apart = std::max(far_apart, std::abs(far_w[i] - far_none[i]));
            }
            const Camera level{.pos = {0.3, 1.6, -44.0}};
            const Scene distant = MakeScene(large, level, Paint::Lit, 1.0f, {}, true);
            for (u32 i = 0; i < count; ++i) {
                if (rim(distant, i, Box, BackWall)) {
                    far_rim.push_back(i);
                }
            }
            const auto level_w =
                weights_of(distant, page_of(distant, level, Look::QualityHigh, tune));
            std::printf("the box from about 50 m: %u crease pixels, the crease weight changes "
                        "them by %.4f at most; %u outline pixels against the back wall, largest "
                        "%.3f\n",
                        u32(far_creases.size()), far_apart, u32(far_rim.size()),
                        most_of(level_w, far_rim));
            Expect(far_creases.size() > 20 && far_apart < 0.02,
                   "no creases on the box from about 50 m");
            Expect(far_rim.size() > 20 && most_of(level_w, far_rim) > 0.05,
                   "the box's outline from about 45 m keeps a line");
        }
        {
            // The limit per area: a field of 1-pixel spikes (a grate seen from the front: every
            // second column 40% nearer than the back wall behind it) 160 rows high and 120
            // columns wide, and a lone spike 60 columns away from it.
            Scene spikes = lit;
            std::vector<int> spike(count, 0);
            u32 x0 = 0, y0 = 0;
            for (u32 y = 0; y + 160 < h && !x0; y += 10) {
                for (u32 x = 0; x + 200 < w && !x0; x += 10) {
                    bool wall = true;
                    for (u32 dy = 0; dy < 160 && wall; ++dy) {
                        for (u32 dx = 0; dx < 200 && wall; ++dx) {
                            wall = lit.surface[(y + dy) * w + x + dx] == BackWall;
                        }
                    }
                    if (wall) {
                        x0 = x;
                        y0 = y;
                    }
                }
            }
            assert(x0);
            const auto nearer = [&](u32 i, int kind) {
                const double t = Near / (1.0 - double(lit.depth[i]));
                spikes.depth[i] = float(1.0 - Near / (0.6 * t));
                spike[i] = kind;
            };
            for (u32 dy = 0; dy < 160; ++dy) {
                for (u32 dx = 0; dx < 120; dx += 2) {
                    nearer((y0 + dy) * w + x0 + dx, 1);
                }
                nearer((y0 + dy) * w + x0 + 180, 2);
            }
            double field[2] = {}, lone[2] = {};
            u32 field_of = 0, lone_of = 0;
            const int qualities[2] = {Look::QualityHigh, Look::QualityLow};
            for (int q = 0; q < 2; ++q) {
                const auto weight =
                    weights_of(spikes, page_of(spikes, straight, qualities[q], tune));
                field_of = lone_of = 0;
                // Away from the field's border, where its place is all of the field.
                for (u32 dy = 30; dy < 130; ++dy) {
                    for (u32 dx = 30; dx < 90; ++dx) {
                        const u32 i = (y0 + dy) * w + x0 + dx;
                        if (spike[i] == 1) {
                            field[q] += weight[i];
                            ++field_of;
                        }
                    }
                    const u32 i = (y0 + dy) * w + x0 + 180;
                    lone[q] += weight[i];
                    ++lone_of;
                }
                field[q] /= std::max(field_of, 1u);
                lone[q] /= std::max(lone_of, 1u);
            }
            std::printf("1-pixel spikes, every second column (%u pixels): mean weight %.3f at "
                        "High, %.3f at Low; a lone spike: %.3f at High, %.3f at Low\n",
                        field_of, field[0], field[1], lone[0], lone[1]);
            Expect(field[0] < 0.3, "a field of 1-pixel spikes stays under weight 0.3 (High)");
            Expect(lone[0] >= 0.3 && field[0] < 0.5 * lone[0],
                   "the limit per area does it: a lone spike keeps its line (half weight, the "
                   "thin guard)");
        }
        {
            // The limit per area where a busy place lies against the edges image's texels. A
            // wall square to the camera at 5 m fills the frame; spikes are pixels at 3 m, near
            // enough that their lines are as wide all across the frame (a line narrows only from
            // 4 m on), so the strips differ only in where they lie against the texels. Strips of
            // 1-pixel spikes every second or third row (or column), each strip's edge one pixel
            // further on than the one before (16 places against the texel grid, the middle rows
            // of a 1080-line frame among them, whose levels have an odd side of 135). The
            // limit's factor at a spike a few pixels inside the edge, the weight at High over
            // the weight without a limit, must be nearly the same in every strip: otherwise a
            // railing seen across steps and crawls as the camera moves. (A model of the draft
            // that read one linear tap of level 4 gave spreads of 0.26 to 0.76 here.)
            const auto wall_scene = [](const Lens& lens, const std::vector<u8>& spike) {
                Scene s{lens.width, lens.height};
                const u32 n = lens.width * lens.height;
                s.surface.assign(n, BackWall);
                s.world.assign(n, Vec3{0.0, 0.0, 0.0});
                for (u32 i = 0; i < n; ++i) {
                    s.depth[i] = float(1.0 - Near / (spike[i] ? 3.0 : 5.0));
                    s.colour[i] = {ToHalf(0.20f), ToHalf(0.18f), ToHalf(0.15f), ToHalf(0.5f)};
                    s.normal[i] = {128, 128, 0, 255};
                }
                return s;
            };
            // The weights of the ink page (view 3, ink 1): 1 - the page over its paper, the
            // middle value of the page (most of the wall has no line).
            const auto wall_weights = [&](const Lens& lens, const Scene& in, int quality,
                                          const Look::InkTune& t) {
                const auto page = gpu.Run(in, Words(lens, straight, Look::ViewInk, true, false,
                                                    0.0f),
                                          1.0f, 1.0f, quality, t);
                std::vector<u16> greys(page.size());
                for (size_t i = 0; i < page.size(); ++i) {
                    greys[i] = page[i][0];
                }
                std::nth_element(greys.begin(), greys.begin() + greys.size() / 2, greys.end());
                const double paper = FromHalf(greys[greys.size() / 2]);
                std::vector<double> weight(page.size());
                for (size_t i = 0; i < page.size(); ++i) {
                    weight[i] = 1.0 - FromHalf(page[i][0]) / paper;
                }
                return weight;
            };
            Look::InkTune no_limit = tune;
            no_limit.density = {1.9f, 2.0f}; // a share no place reaches
            // `across`: the strips' spikes run along x (rows: the edge moves down the rows), else
            // along y. `first`: the edge of the first strip, in rows (or columns); `every`: a
            // spike every that many rows (or columns). The factors at each of `insides` (pixels
            // from the edge, each a spike), strip by strip.
            const auto sweep = [&](const Lens& lens, bool across, u32 first, u32 every,
                                   std::array<u32, 3> insides, const char* what) {
                // The strips lie side by side along this side of the frame.
                const u32 along = across ? lens.width : lens.height;
                const u32 pitch = 120, side = 100, margin = 30, deep = 60;
                const u32 per_image = along / pitch;
                std::array<std::vector<double>, 3> factor;
                for (u32 k0 = 0; k0 < 16; k0 += per_image) {
                    std::vector<u8> spike(size_t(lens.width) * lens.height, 0);
                    const auto at = [&](u32 a, u32 b) { // a along the strips' side, b across
                        return across ? size_t(b) * lens.width + a : size_t(a) * lens.width + b;
                    };
                    const u32 count_here = std::min(per_image, 16 - k0);
                    for (u32 k = 0; k < count_here; ++k) {
                        const u32 edge = first + k0 + k;
                        for (u32 a = k * pitch + 10; a < k * pitch + 10 + side; ++a) {
                            for (u32 b = edge; b < edge + deep; b += every) {
                                spike[at(a, b)] = 1;
                            }
                        }
                    }
                    const Scene in = wall_scene(lens, spike);
                    const auto high = wall_weights(lens, in, Look::QualityHigh, tune);
                    const auto unlimited = wall_weights(lens, in, Look::QualityHigh, no_limit);
                    for (u32 k = 0; k < count_here; ++k) {
                        const u32 edge = first + k0 + k;
                        for (int o = 0; o < 3; ++o) {
                            double got = 0.0, of = 0.0;
                            for (u32 a = k * pitch + 10 + margin;
                                 a < k * pitch + 10 + side - margin; ++a) {
                                got += high[at(a, edge + insides[o])];
                                of += unlimited[at(a, edge + insides[o])];
                            }
                            factor[o].push_back(of > 0.0 ? got / of : 0.0);
                        }
                    }
                }
                std::printf("the limit per area against the texel grid, %s at %ux%u: factor at",
                            what, lens.width, lens.height);
                double spread = 0.0, deepest = 1.0;
                for (int o = 0; o < 3; ++o) {
                    const auto [lo, hi] = std::minmax_element(factor[o].begin(), factor[o].end());
                    std::printf(" %u px inside %.3f..%.3f;", insides[o], *lo, *hi);
                    spread = std::max(spread, *hi - *lo);
                    deepest = std::min(deepest, *lo);
                }
                std::printf(" largest spread %.3f\n", spread);
                Expect(deepest < 0.8 && spread < 0.05,
                       "the limit per area is nearly the same wherever a busy place lies against "
                       "the edges image's texels");
            };
            sweep(large, true, 500, 3, {3, 9, 18}, "rows of spikes");
            sweep(large, false, 900, 3, {3, 9, 18}, "columns of spikes");
            // At 540 lines a line is 0.75 pixels wide and counts 0.75: a spike every second row
            // makes the place as busy.
            const Lens half_lens{960, 540};
            sweep(half_lens, true, 250, 2, {2, 6, 10}, "rows of spikes");
        }
        {
            // Lines that are wanted and evenly spaced: posts three pixels wide every 12 pixels
            // on the wall above, 360 pixels across. The limit per area must not thin them much:
            // at High they keep at least half of the weight they have without it.
            const auto posts_scene = [&](u32 every) {
                Scene s{large.width, large.height};
                const u32 n = large.width * large.height;
                s.surface.assign(n, BackWall);
                s.world.assign(n, Vec3{0.0, 0.0, 0.0});
                for (u32 i = 0; i < n; ++i) {
                    const u32 x = i % large.width, y = i / large.width;
                    const bool post = x >= 780 && x < 1140 && y >= 400 && y < 700 &&
                                      (x - 780) % every < 3;
                    s.depth[i] = float(1.0 - Near / (post ? 3.0 : 5.0));
                    s.colour[i] = {ToHalf(0.20f), ToHalf(0.18f), ToHalf(0.15f), ToHalf(0.5f)};
                    s.normal[i] = {128, 128, 0, 255};
                }
                return s;
            };
            const Scene posts = posts_scene(12);
            Look::InkTune no_limit = tune;
            no_limit.density = {1.9f, 2.0f}; // a share no place reaches
            const auto run = [&](const Look::InkTune& t) {
                return gpu.Run(posts, Words(large, straight, Look::ViewInk, true, false, 0.0f),
                               1.0f, 1.0f, Look::QualityHigh, t);
            };
            const auto page_limit = run(tune), page_free = run(no_limit);
            const double paper = FromHalf(page_limit[100 * large.width + 100][0]);
            double limited = 0.0, unlimited = 0.0;
            for (u32 y = 450; y < 650; ++y) {
                for (u32 x = 840; x < 1080; ++x) {
                    const u32 i = y * large.width + x;
                    if ((x - 780) % 12 < 3) {
                        limited += 1.0 - FromHalf(page_limit[i][0]) / paper;
                        unlimited += 1.0 - FromHalf(page_free[i][0]) / paper;
                    }
                }
            }
            std::printf("posts 3 pixels wide every 12 pixels: weight at High %.3f of their "
                        "weight without the limit per area\n",
                        unlimited > 0.0 ? limited / unlimited : 0.0);
            Expect(unlimited > 0.0 && limited >= 0.5 * unlimited,
                   "posts every 12 pixels keep at least half of their weight under the limit per "
                   "area");
        }
    }
    if (argc > 1) {
""")),
]

EDITS[TESTS + "test_effect_pipelines.cpp"] = [
    (B(r"""
#include "video_core/host_shaders/paint_ink_comp.h"
"""),
     B(r"""
#include "video_core/host_shaders/paint_ink_apply_comp.h"
#include "video_core/host_shaders/paint_ink_comp.h"
#include "video_core/host_shaders/paint_ink_down_comp.h"
#include "video_core/host_shaders/paint_ink_edges_comp.h"
""")),
    (B(r"""
        // bytes since r45b; r55_drawn-look-lines: the ink pass)
"""),
     B(r"""
        // bytes since r45b; r55_drawn-look-lines: the ink pass; r58_drawn-look-d2: High's three)
""")),
    (B(r"""
         {eCombinedImageSampler, eSampledImage, eStorageImage},
         128},
"""),
     B(r"""
         {eCombinedImageSampler, eSampledImage, eStorageImage},
         128},
        {"drawn look ink edges", PAINT_INK_EDGES_COMP, {eSampledImage, eStorageImage}, 128},
        {"drawn look ink edge levels", PAINT_INK_DOWN_COMP, {eCombinedImageSampler, eStorageImage},
         128},
        {"drawn look ink apply",
         PAINT_INK_APPLY_COMP,
         {eCombinedImageSampler, eSampledImage, eStorageImage, eCombinedImageSampler},
         128},
""")),
]

EDITS[TESTS + "test_settings.cpp"] = [
    (B(r"""
                                        "graphics_drawn_look_shadow_soft=nan\n"; }
    s.graphics_drawn_look = true; // on before this Load: the fallback is off
"""),
     B(r"""
                                        "graphics_drawn_look_shadow_soft=nan\n"
                                        "graphics_drawn_look_quality=best\n"; }
    s.graphics_drawn_look = true; // on before this Load: the fallback is off
    assert(s.graphics_drawn_look_quality == 0); // low from the Load before
    BbSettings::Load();
    // (r58_drawn-look-d2) A quality that is no whole number is the default, high (atoi made a
    // word low); a number is clamped (5 and -3 above).
    assert(s.graphics_drawn_look_quality == BbSettings::DrawnLookQualityDefault &&
           BbSettings::DrawnLookQualityDefault == BbSettings::DrawnLookQualityHigh);
    { std::ofstream file(path); file << "graphics_drawn_look_quality=0.5\n"; }
    s.graphics_drawn_look_quality = 0;
    BbSettings::Load();
    assert(s.graphics_drawn_look_quality == BbSettings::DrawnLookQualityHigh);
    { std::ofstream file(path); file << "graphics_drawn_look=on\ngraphics_drawn_look_strength=nan\n"
                                        "graphics_drawn_look_stroke_size=inf\ngraphics_drawn_look_texture=nan\n"
                                        "graphics_drawn_look_outlines=nan\ngraphics_drawn_look_shadow_edges=nan\n"
                                        "graphics_drawn_look_ink_world=nan\ngraphics_drawn_look_characters=-inf\n"
                                        "graphics_drawn_look_shadow_soft=nan\n"; }
    s.graphics_drawn_look = true;
""")),
]

EDITS[ROOT + "README.md"] = [
    (B(r"""
| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on the world's surfaces, bold on plain walls and floors and fine where there is detail, and ink lines along the silhouettes of shapes. Fire, glows, fog, particles and the HUD are not painted, colours are not changed (an ink line is the surface's own colour, darker). Ink on inner edges, heavier ink on characters and painted shadow edges are not built yet | off |
"""),
     B(r"""
| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on the world's surfaces, bold on plain walls and floors and fine where there is detail, and ink lines along the silhouettes of shapes and on creases, where two surfaces meet at an angle. Fire, glows, fog, particles and the HUD are not painted, colours are not changed (an ink line is the surface's own colour, darker). Heavier ink on characters and painted shadow edges are not built yet | off |
""")),
    (B(r"""
| `graphics_drawn_look_ink_world` | Drawn look ink lines, 0 to 1: how dark the ink lines along the silhouettes of shapes are (pillars, walls, steps and figures against what lies behind them); 0 is no lines. A line is 1.5 pixels of a 1080-line picture wide near the camera and narrows from 4 m on; from about 9 m it grows fainter (to a third from 16 m), the same at every render size, and it fades out between 40 and 120 m. A line pixel's colour is multiplied by mix(1, f, weight), f = min(0.3 x its brightness, 0.05 x the frame's key) / its brightness, so its hue stays. Something nearer than what lies on both sides of it within about two line widths (a railing, a branch) gets half the weight. Not drawn on frames the look paints right before the upscaler. On a frame with lines the upscaler's extra sharpening is multiplied by 1 - 0.5 x the lines' weight (this value; 1 in the ink page). Every save since the look came wrote this key, then unread, as `0.00`: an existing lantern.ini keeps it at 0 until the menu row is set. Live; menu row "Drawn look ink lines" | `0.35` |
| `graphics_drawn_look_outlines`, `_shadow_edges`, `_shadow_soft`, `_quality` | Drawn look: kept for parts of the look that are not built yet (character ink, painted shadow edges 0 to 1, shadow softness 0.05 to 0.3, quality 0 or 1); read, clamped and saved, without effect so far | `0.35`, `1.0`, `0.12`, `1` |

Experimental environment-only toggles (no ini key): `BB_SKY_ZENITH_FIX=1` enables the sky zenith fix (off by default); `BB_SKY_SEAM_FIX` controls the sky seam fix, which is on by default and disabled with `BB_SKY_SEAM_FIX=0`. `BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view while the look is on: every stroke in a flat colour of its own, bold and fine as the look mixes them, all fine, all bold; `3` the ink page (no strokes, a grey page with the ink lines on it at full weight). A test view shows only while the look runs, that is with its strength or its ink lines above 0. `BB_DRAWN_LOOK_LINE=0.5` to `2` (default `1`) scales the ink lines' width in pixels (a line under one pixel is drawn one pixel wide, lighter); it does not change where lines show. Neither is written to the ini; a `graphics_drawn_look_debug` line left in it is kept and not read.
"""),
     B(r"""
| `graphics_drawn_look_ink_world` | Drawn look ink lines, 0 to 1: how dark the ink lines along the silhouettes of shapes are (pillars, walls, steps and figures against what lies behind them); 0 is no lines. A line is 1.5 pixels of a 1080-line picture wide near the camera and narrows from 4 m on; from about 9 m it grows fainter (to a third from 16 m), the same at every render size, and it fades out between 40 and 120 m. Creases are found from the depth alone, never from the G-buffer's bumpy normals: where the faces on either side of a pixel bend by 30 degrees or more (fully from 50; faces that turn by 30 degrees or less, such as a round column of 12 or more sides, get none), a line 1 pixel wide over both faces at half the silhouettes' weight; it narrows with distance as a silhouette does (each of its pixels covered the less) but does not grow fainter from 9 m, and it fades out between 20 and 50 m. A line pixel's colour is multiplied by mix(1, f, weight), f = min(0.3 x its brightness, 0.05 x the frame's key) / its brightness, so its hue stays. Something nearer than what lies on both sides of it within about two line widths (a railing, a branch) gets half the weight. At High quality (`graphics_drawn_look_quality`) the lines are also limited per area: where lines cover 20 % or more of the place around a pixel (a smooth weighting about as wide as a box 16 pixels of a 1080-line picture across, nearly the same wherever the place lies on the screen), they fade, and from 45 % there are none, so foliage, grates and railings seen along do not turn black; that share counts each line as dark as it is drawn (its fades included), a thin thing's line before its halving. Not drawn on frames the look paints right before the upscaler. On a frame with lines the upscaler's extra sharpening is multiplied by 1 - 0.5 x the lines' weight (this value; 1 in the ink page). Every save since the look came wrote this key, then unread, as `0.00`: an existing lantern.ini keeps it at 0 until the menu row is set. Live; menu row "Drawn look ink lines" | `0.35` |
| `graphics_drawn_look_quality` | Drawn look ink quality, `0` low or `1` high. High: silhouettes looked for along four axes (the screen's rows, columns and both diagonals) and the limit per area above, in three passes over an edges image (RGBA8 with its smaller levels, about 5.3 bytes a scene pixel: 11 MB at 1920x1080, 44 MB at 3840x2160). Low: two axes, no limit per area, every line at 0.7 of its weight, in one pass and no extra memory. Creases at both. Without video memory for the edges image the lines are drawn at Low and the log says so once a size. A whole number is clamped to 0 or 1; anything else (a word, a fraction) is high, with a note. Live; menu row "Drawn look ink quality" | `1` |
| `graphics_drawn_look_outlines`, `_shadow_edges`, `_shadow_soft` | Drawn look: kept for parts of the look that are not built yet (character ink, painted shadow edges 0 to 1, shadow softness 0.05 to 0.3); read, clamped and saved, without effect so far | `0.35`, `1.0`, `0.12` |

Experimental environment-only toggles (no ini key): `BB_SKY_ZENITH_FIX=1` enables the sky zenith fix (off by default); `BB_SKY_SEAM_FIX` controls the sky seam fix, which is on by default and disabled with `BB_SKY_SEAM_FIX=0`. `BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view while the look is on: every stroke in a flat colour of its own, bold and fine as the look mixes them, all fine, all bold; `3` the ink page (no strokes, a grey page with the ink lines on it at full weight). A test view shows only while the look runs, that is with its strength or its ink lines above 0. `BB_DRAWN_LOOK_LINE=0.5` to `2` (default `1`) scales the ink lines' width in pixels (a line under one pixel is drawn one pixel wide, lighter); it does not change where lines show. The ink's numbers can be tried without a rebuild (read once at the start, printed once in the log when any is set; a value that is no number, or a pair that does not rise, is the default; values are clamped to the range): `BB_DRAWN_LOOK_CREASE_ANGLE=30,50` (5 to 85 degrees: a crease from, fully from), `BB_DRAWN_LOOK_CREASE_WIDTH=1` (0.25 to 3 pixels of a 1080-line picture, both faces), `BB_DRAWN_LOOK_CREASE_WEIGHT=0.5` (0 to 1 of the silhouettes' weight; 0: no creases), `BB_DRAWN_LOOK_CREASE_FADE=20,50` and `BB_DRAWN_LOOK_LINE_FADE=40,120` (1 to 1000 m), `BB_DRAWN_LOOK_DENSITY=0.20,0.45` (0 to 2: the share of a place covered by lines where they start to fade, and where none are left), `BB_DRAWN_LOOK_DENSITY_SIZE=16` (4 to 64 pixels of a 1080-line picture), `BB_DRAWN_LOOK_LOW_FACTOR=0.7` (0 to 1). None of these is written to the ini; a `graphics_drawn_look_debug` line left in it is kept and not read.
""")),
]


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def literals(text):
    """Every run of adjacent C++ string literals in `text`, joined (escapes left as written)."""
    out = []
    for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"(?:\s*"(?:[^"\\\n]|\\.)*")*', text):
        out.append("".join(re.findall(r'"((?:[^"\\\n]|\\.)*)"', m.group(0))))
    return out


def text_of(header, name):
    """The English and the Russian of bbport_drawn_look_texts.h's constant `name`."""
    at = header.find("inline constexpr Text %s{" % name)
    if at < 0:
        return None
    block = header[at:header.find("};", at)]
    found = literals(block)
    return found if len(found) == 2 else None


def text_check(texts):
    """What the patch relies on in the patched text."""
    ok = True
    texts = {p: t.replace("\r\n", "\n") for p, t in texts.items()}
    if any(foreign(p) for p in list(EDITS) + list(NEW_FILES)):
        print("this round would touch another round's file")
        ok = False
    params = texts[R + "drawn_look_params.h"]
    if params.count("enum Quality : int { QualityLow = 0, QualityHigh = 1 };") != 1 or \
            params.count("int quality = QualityHigh;") != 1 or params.count("struct InkTune {") != 1 or \
            params.count(".ink_limit = ink && knobs.quality != QualityLow}") != 1:
        print("drawn_look_params.h: the quality, the tune or ink_limit is not there once")
        ok = False
    names = re.findall(r'"(BB_DRAWN_LOOK_[A-Z_]+)"', params[params.find("InkTuneNames[]"):][:400])
    readme = texts[ROOT + "README.md"]
    if len(names) != 8 or any(readme.count("`%s=" % n) != 1 for n in names) or \
            readme.count("| `graphics_drawn_look_quality` |") != 1 or "`_quality`" in readme:
        print("README.md: the quality's row or the eight tuning variables are not there once")
        ok = False
    ink = texts[HS + "paint_ink.comp"]
    if '#include "paint_common.glsl"' not in ink or ink.count("#if defined(DOWN)") != 1 or \
            ink.count("layout(binding = 1, rgba8) uniform writeonly image2D edges_img;") != 1 or \
            ink.count("layout(binding = 3) uniform sampler2D edges_tex;") != 1 or \
            "layout(binding = 2, rgba16f) uniform image2D scene_img;" not in ink or \
            "normal_tex" in ink or ink.count("vec4 placeAt(vec2 uv) {") != 1 or \
            ink.count("#define DENSITY_LEVEL back_shift.z") != 1 or \
            params.count("DensityLevel(std::uint32_t(look.size[1]), tune.density_px)};") != 1:
        print("paint_ink.comp is not the shader the passes are made for")
        ok = False
    cmake = texts[G + "CMakeLists.txt"]
    for line in ("add_host_shader(paint_ink.comp paint_ink_comp)",
                 "add_host_shader(paint_ink.comp paint_ink_edges_comp EDGES=1)",
                 "add_host_shader(paint_ink.comp paint_ink_down_comp DOWN=1)",
                 "add_host_shader(paint_ink.comp paint_ink_apply_comp APPLY=1)"):
        if cmake.count(line) != 1:
            print("CMakeLists.txt: %s is not there once" % line)
            ok = False
    look = texts[R + "vk_drawn_look.cpp"]
    for x in ('PAINT_INK_EDGES_COMP,', 'PAINT_INK_DOWN_COMP,', 'PAINT_INK_APPLY_COMP, "Drawn look ink apply"',
              "Knobs{}.quality == BbSettings::DrawnLookQualityDefault",
              ".quality = s.graphics_drawn_look_quality.load(std::memory_order_relaxed),",
              "knobs.line_scale, env_tune);", "ReleaseImage(edges); // bbport (r58_drawn-look-d2)",
              "EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm)"):
        if look.count(x) != 1:
            print("vk_drawn_look.cpp: %r is not there once" % x)
            ok = False
    paint = look.find("void DrawnLook::Paint(")
    at = [look.find(x, paint) for x in ("const auto passes = DrawnLookParams::PassesFor(", "    if (!Ready()) {",
                                        "bool limit = passes.ink_limit;", "EffectPass::Mark(18,",
                                        "EffectPass::Mark(12,", "EffectPass::Mark(13,")]
    if min(at) < 0 or at != sorted(at) or look.count("EffectPass::Mark(13,") != 1:
        print("vk_drawn_look.cpp: the passes are not recorded in the order strokes, lock, ink")
        ok = False
    h, cpp = texts[S + "bbport_settings.h"], texts[S + "bbport_settings.cpp"]
    if "std::atomic<int> graphics_drawn_look_quality{DrawnLookQualityDefault};" not in h or \
            "v.graphics_drawn_look_quality = std::clamp(i, 0, 1);" in cpp or \
            cpp.count("const long quality = std::strtol(value.c_str(), &end, 10);") != 1:
        print("bbport_settings: the quality's default or its strict reading is missing")
        ok = False
    # The menu: the row's texts are bbport_drawn_look_texts.h's, each English text in the eight
    # tables once, the old hints gone, the Chinese in the menu font.
    header = texts[S + "bbport_drawn_look_texts.h"]
    overlay = texts[S + "bbport_overlay.cpp"]
    i18n = texts[S + "bbport_menu_i18n.cpp"]
    for name in ("SwitchHint", "InkHint", "Quality", "QualityHint", "QualityLow", "QualityHigh"):
        pair = text_of(header, name)
        if not pair:
            print("bbport_drawn_look_texts.h: no %s" % name)
            ok = False
            continue
        if i18n.count('    {"%s",' % pair[0]) != 8:
            print("bbport_menu_i18n.cpp: %r is not in the eight tables once" % pair[0][:40])
            ok = False
        if "&%s," % name not in header[header.find("All[] = {"):] and "&%s}" % name not in header:
            print("bbport_drawn_look_texts.h: %s is not in All[] (settings-test checks All)" % name)
            ok = False
    if "lines on inner edges" in header + i18n or "Not built yet: heavier ink on characters, lines" in i18n:
        print("an old hint is still there")
        ok = False
    if overlay.count("Item(DrawnText::Quality.english, DrawnText::Quality.russian)") != 1 or \
            overlay.count("Store(s.graphics_drawn_look_quality, quality, changed);") != 1:
        print("bbport_overlay.cpp: the quality row is not there once")
        ok = False
    glyphs = set()
    if os.path.isfile(GLYPHS):
        glyphs = {int(x.strip()[2:], 16) for x in open(GLYPHS, encoding="utf-8").read().split(",") if x.strip()}
    else:
        print("cannot check the menu's Chinese text: %s is missing" % GLYPHS)
        ok = False
    zh = i18n[i18n.find("constexpr Entry kChinese[] = {"):]
    zh = zh[:zh.find("\n};\n")]
    block = zh[zh.find("// bbport (r55_drawn-look-lines)"):]
    missing = sorted({c for c in block if ord(c) > 0x7e and ord(c) not in glyphs})
    if glyphs and missing:
        print("the menu's Chinese text uses characters the menu font does not have: %s" % "".join(missing))
        ok = False
    pipelines = texts[TESTS + "test_effect_pipelines.cpp"]
    if pipelines.count('{"drawn look ink edges", PAINT_INK_EDGES_COMP,') != 1 or \
            pipelines.count("PAINT_INK_APPLY_COMP,") != 1:
        print("test_effect_pipelines.cpp: High's pipelines are not there")
        ok = False
    # The C escapes must have kept their backslash on the way into this script.
    bs = chr(92)
    gpu_test = texts[TESTS + "test_drawn_look.cpp"]
    if '"factor %.2f' + bs + 'n",' not in look or \
            '"high); %d' + bs + 'n", value.c_str(), DrawnLookQualityDefault);' not in cpp or \
            '"High, %.3f at Low; a lone spike: %.3f at High, %.3f at Low' + bs + 'n",' not in gpu_test or \
            '"graphics_drawn_look_quality=best' + bs + 'n"; }' not in texts[TESTS + "test_settings.cpp"] or \
            "RecordInk(Look::MakeInk(params, ink_world, knobs.outlines, line_scale, tune)," not in gpu_test or \
            'std::puts("PASS: drawn look rules");' not in texts[TESTS + "test_drawn_look_rules.cpp"]:
        print("a C escape lost its backslash, or a text is missing")
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
            if not a:
                print("internal: an edit with an empty side cannot be reverted")
                return None
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
        print("usage: r58_drawn-look-d2.py check|apply|revert   (the tree: R58_ROOT, else the current "
              "directory)")
        return 2
    # run() only reads: nothing is written before every text of the mode is made.
    out = run(mode, quiet=True)
    if out is None:
        if mode != "revert" and run("revert", quiet=True) is not None:
            print("already applied (revert would restore the tree)" if mode == "check"
                  else "already applied: nothing written")
        elif mode == "revert" and run("check", quiet=True) is not None:
            print("not applied: nothing to revert")
        else:
            run(mode)  # says which anchor, or what else is wrong
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
