# r45b_drawn-look-fixes: two corrections of the drawn look (r45_drawn-look). check|apply|revert
# (revert restores byte for byte). On top of r1..r45 (r45_drawn-look applied).
#  A. The strokes are painted on every surface that does not move BY ITSELF: a surface's vector
#     in the object motion image is compared with the shift the camera alone gives its pixel.
#     (Before, every surface with such a vector was taken for a moving one, and in the game that
#     is nearly the whole world: the look smoothed the picture and painted no strokes.)
#  B. The look paints before the FIRST of the game's transparent draws, also when that draw has
#     six indices or fewer (a particle system of a few particles used to be painted over).
# It touches eight files (the look's own, its hook in vk_rasterizer.cpp, its offline test) and
# nothing of vk_rt_shadow.*, rt_unproject.comp, bbport_toggles.h, vk_point_shadow.*,
# CMakeLists.txt or bbport_settings.h. The tree: the one the environment variable R45B_ROOT
# names; without it the current directory when that is the root of a source tree (run from
# there), else <tree>/. Nothing is changed in place: every new text is written beside its
# target and moved over it, and a failure puts back what was already moved. Source files keep
# their CRLF line ends. The (old, new) pairs below were made by machine from the copy of the
# files taken before the round's first edit and the tree the game was run on (each old text is
# found exactly once when its turn comes, each new one exactly once on the way back).
#
# WHY A. The object motion image holds, for every draw whose vertices of the frame before are
# known, where the pixel was (blue = 1 marks such a pixel). r45 read the mark as "this moves by
# itself" (a character, cloth) and gave such pixels the calm smoothing instead of strokes that
# are fixed to the world. The game keeps the vertices of the frame before for most of the world
# as well, so the mark was on walls, floor and buildings: the test view was grey everywhere and
# the picture only smoothed, by graphics_drawn_look_characters (0.3) of the strength. The
# design's item 9 says what was meant: a surface moves by itself when its vector differs from
# the camera's own reprojection of its pixel.
#
# WHY B. The look paints at the first blended draw without depth writes into the scene colour.
# The hook counted such a draw only with more than six indices (or instances), because a draw
# of six or fewer is how a full-screen pass looks. The game's particle systems are drawn with
# one index a particle (blended, depth tested, no depth written), and a system of a few
# particles is such a small draw: it came before the paint and was painted over.
#
# WHAT.
#  1. drawn_look_params.h: the block the passes get (Params) carries the camera of the frame
#     before as a turn (the vector part of a unit quaternion, back_turn), a shift in metres
#     (back_shift) and the lens' ratio (16 bits of `flags` from bit 16, 32768 = the same lens);
#     FlagPrevious says they are there. Make() gets the frame before's view and lens (Previous)
#     and leaves the flag off when there is none or when the step is no small one (a turn of
#     more than 120 degrees, a mirrored or skewed matrix, a lens ratio outside 0.5 to 2 or
#     different in x and y). The block stays at 128 bytes (static_assert; the limit of push
#     constants that every driver takes): the two ink knobs (outlines, ink_world), which no pass
#     reads yet, left it and stay in Knobs. ViewOf(flags) reads the test view (three bits), now
#     that `flags` has more above it. SmallTransparent() is the hook's rule as a pure function.
#  2. paint_common.glsl: the same block; cameraShift() (the shift in pixels the camera alone
#     gives a point, worked out as camera_motion.comp does); movesItself() gives a share 0..1:
#     0 below 0.25 pixels a frame of own motion, 1 from 1 pixel (at 1080 lines), 1 for every
#     marked pixel on a frame without the camera of the frame before (the old behaviour).
#  3. paint_strokes.comp: strokes and calm smoothing are mixed by that share (and the strength
#     by it between 1 and `characters`); the test view greys by it. paint_lock.comp: the same
#     test for the pixels it leaves out.
#  4. vk_drawn_look.cpp/.h: the camera a frame was painted with is kept for the next frame (not
#     across a frame that was not painted or with the look off); the line every 600 frames says
#     on how many frames it was there. OnSmallTransparent(): the hook names the small draw; when
#     it is the frame's first transparent draw, its fragment shader is named in the log once
#     ("Drawn look: a frame's first transparent draw is a small one ..."), so that a lighting
#     pass taken for a particle would show.
#  5. vk_rasterizer.cpp, the scene colour hook: a draw of six indices or fewer that is blended
#     (not bypassed), writes no depth and tests it with a function other than Always
#     (DrawnLookParams::SmallTransparent) is one of the transparents while the look is on:
#     OnSmallTransparent, then EffectsBlendedScene() (the indirect light's OnOpaqueScene, which
#     runs once a frame, then the look's OnBlendedScene) instead of EffectsSceneComposite(). The
#     full-screen passes (no blend, or depth test off or Always) go on to EffectsSceneComposite
#     as before. The condition starts with drawn_look_wanted: with graphics_drawn_look=0 the
#     branch is the old one, statement for statement. The upscaler's two calls
#     (OnBlendedSceneDraw, OnSceneComposite) are untouched in both states. With the look on and
#     the indirect light on, that light now goes in before this small draw as well (it has to
#     be in before the strokes), where it used to go in after it.
#  6. tests/test_drawn_look.cpp: a scene in which every surface has a vector (the camera stood
#     still, turned and walked, turned and zoomed): the world is painted exactly as without
#     vectors, a ball that moves 3 pixels by itself is smoothed; the same without the camera of
#     the frame before; Make()'s words (same camera, none, a cut, a lens of three times, a
#     mirrored camera, the zoom's bits, ViewOf); SmallTransparent's truth table.
#
# PROOF IN THE GAME (dev install, 3840x2160, DLSS Performance, 1920x1080 scene, Hunter's Dream
# spawn, the character not moved, RTX 4090). Test view (BB_DRAWN_LOOK_VIEW=1): coloured dabs on
# walls, floor, far buildings and the standing character, at the default camera, while the
# camera turns and in the top-down view; it was grey before. "Drawn look: of 600 frames, strokes
# painted before the transparents on 600 ...; what moves by itself told against the camera of
# the frame before on 600". "Drawn look: a frame's first transparent draw is a small one (1
# indices, ps 0000000071c96598)", and the composite pass is learned at once ("... fragment
# shader 000000000150b093 (number 1 of it in the frame)"). With the look off the log has no
# line of the look. Cost: strokes and colour lock 0.44 to 0.47 ms a frame at the default camera
# (0.38 top-down), copy and masks 0.07 ms; it was 0.18 + 0.07 ms while nothing was stroked.
#
# WHAT THIS ROUND FOUND AND DID NOT CHANGE IN THE TREE (nothing of it is the look's doing).
#  - The black dots on dark floor and cloth are not in the frame the engine presents: they are
#    made by the test script's screen copy. GDI+ fills the surface CopyFromScreen copies into
#    with RGB(13,11,12) and takes back only what differs, so screen pixels of exactly that
#    colour stay transparent black. Save-Shot in Test-BBFSSDev.ps1 (outside the tree) now clears
#    its bitmap to that colour first; the captures have no such dots since, look off or on.
#  - The torch flame is drawn after the paint and the look does not touch it. It is soft in the
#    upscaler's 1080-line input and in its 2160-line output, look off and on; small rectangular
#    steps on its rim come in after the upscaler, on some frames, look off as with it on. Which
#    of the game's passes at output size makes them was not found.
#  - The profile's row "Lighting: drawn look copy and masks" is there (0.07 ms a frame, once a
#    frame); the profile prints its 30 costliest rows only, BB_GPU_PROFILE_ROWS=250 shows it.

import os
import sys

# The tree: R45B_ROOT when it is set; else the current directory when that is the root of a
# source tree (the script is run from there); else <tree>/, as the rounds before.
ROOT = os.environ.get("R45B_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_drawn_look.cpp") \
        else "<tree>/"
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
S = G + "shim/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
H = B + "host_shaders/"
TESTS = E + "tests/"

TMP = ".r45btmp"  # a new text waits under this name beside its target (main)

# No file is new in this round (apply makes none, revert removes none).
NEW_FILES = {}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    R + "drawn_look_params.h": [
        (r"""
#include <algorithm>
#include <array>
#include <cstdint>

namespace Vulkan::DrawnLookParams {

/// The push constants of the drawn look's passes (host_shaders/paint_*.comp).
struct Params {
    std::array<float, 12> inv_view; ///< view to world, 3x4 rows
    std::array<float, 4> proj;      ///< x scale, y scale, z scale, z offset
""",
         r"""
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

namespace Vulkan::DrawnLookParams {

/// The push constants of the drawn look's passes (host_shaders/paint_*.comp). 128 bytes: what
/// every GPU takes, and all of it used. The ink's two knobs (Knobs::outlines, ink_world), which
/// no pass reads yet, gave their places to the camera of the frame before
/// (r45b_drawn-look-fixes).
struct Params {
    std::array<float, 12> inv_view; ///< view to world, 3x4 rows
    std::array<float, 4> proj;      ///< x scale, y scale, z scale, z offset
"""),
        (r"""    std::array<float, 2> jitter;    ///< the frame's viewport shift in pixels
    float strength;
    float brush;
    float outlines;
    float ink_world;
    float characters;
    float cell_bold;
    float cell_fine;
    std::uint32_t flags;
};
static_assert(sizeof(Params) == 112);

inline constexpr std::uint32_t FlagNormals = 1; ///< the G-buffer's world normals are bound
inline constexpr std::uint32_t FlagMotion = 2;  ///< this frame's object motion is bound
inline constexpr std::uint32_t ViewShift = 8;   ///< the test view, three bits from here

/// graphics_drawn_look_debug (BB_DRAWN_LOOK_VIEW). 1, 2 and 4 paint every stroke in a flat
/// colour of its own: with the sizes the look mixes, all fine, all bold. 3 is kept for the ink
""",
         r"""    std::array<float, 2> jitter;    ///< the frame's viewport shift in pixels
    float strength;
    float brush;
    float characters;
    float cell_bold;
    /// From this frame's view axes to those of the frame before: a turn (the vector part of its
    /// unit quaternion; the scalar part is positive) and then a shift in metres. FlagPrevious.
    std::array<float, 3> back_turn;
    float cell_fine;
    std::array<float, 3> back_shift;
    std::uint32_t flags;
};
static_assert(sizeof(Params) == 128);

inline constexpr std::uint32_t FlagNormals = 1; ///< the G-buffer's world normals are bound
inline constexpr std::uint32_t FlagMotion = 2;  ///< this frame's object motion is bound
/// The camera of the frame before is known (back_turn, back_shift, the zoom): what the object
/// motion says of a pixel is compared with what the camera's own move does to it.
inline constexpr std::uint32_t FlagPrevious = 4;
inline constexpr std::uint32_t ViewShift = 8;   ///< the test view, three bits from here
/// 16 bits from here: the projection's scale of the frame before over this frame's (a zoom),
/// as (ratio - 1) * 32768 + 32768. 32768: the same lens.
inline constexpr std::uint32_t ZoomShift = 16;
/// The test view in a block's flags (a View).
constexpr std::uint32_t ViewOf(std::uint32_t flags) {
    return (flags >> ViewShift) & 7u;
}

/// graphics_drawn_look_debug (BB_DRAWN_LOOK_VIEW). 1, 2 and 4 paint every stroke in a flat
/// colour of its own: with the sizes the look mixes, all fine, all bold. 3 is kept for the ink
"""),
        (r"""    float strength = 0.6f;
    float stroke_size = 1.0f;
    float texture = 1.0f;
    float outlines = 0.35f;
    float ink_world = 0.0f;
    float characters = 0.5f;
    int view = ViewOff;
};

/// The scene's `height` is the upscaler's input (render) height: its output has the same
/// picture on more pixels, so a stroke that is a set share of the render height is that share
/// of the screen whatever the upscaler mode.
inline Params Make(const Knobs& knobs, const std::array<float, 12>& inv_view,
                   const std::array<float, 4>& proj, std::uint32_t width, std::uint32_t height,
                   const std::array<float, 2>& jitter, bool normals, bool motion) {
    const float scale = float(height) / 2160.0f * knobs.stroke_size;
    return {
        .inv_view = inv_view,
        .proj = proj,
        .size = {float(width), float(height)},
        .jitter = jitter,
        .strength = knobs.strength,
        .brush = knobs.texture,
        .outlines = knobs.outlines,
        .ink_world = knobs.ink_world,
        .characters = knobs.characters,
        // Under two pixels a cell a stroke is no longer a shape.
        .cell_bold = std::max(BoldCellAt2160 * scale, 2.0f),
        .cell_fine = std::max(FineCellAt2160 * scale, 2.0f),
        .flags = (normals ? FlagNormals : 0u) | (motion ? FlagMotion : 0u) |
                 std::uint32_t(std::clamp(knobs.view, int(ViewOff), int(ViewMax))) << ViewShift,
    };
}

} // namespace Vulkan::DrawnLookParams
""",
         r"""    float strength = 0.6f;
    float stroke_size = 1.0f;
    float texture = 1.0f;
    float outlines = 0.35f; ///< the ink is not built: not among the passes' words
    float ink_world = 0.0f; ///< the same
    float characters = 0.5f;
    int view = ViewOff;
};

/// The camera a frame was drawn with, kept for the frame after it.
struct Previous {
    std::array<float, 12> view; ///< world to view, 3x4 rows
    std::array<float, 4> proj;  ///< x scale, y scale, z scale, z offset
};

/// (r45b_drawn-look-fixes) A draw of six indices or fewer into the scene colour is as small as a
/// full-screen pass. It is one of the game's transparents (a particle system of a few
/// particles: a card of fog, a few sparks) when it is blended, writes no depth and is tested
/// against the scene's depth; a full-screen pass over the scene is not blended, or does not
/// test the depth. The look paints before the first transparent draw of a frame.
/// `depth_always`: the depth test's function lets everything pass.
constexpr bool SmallTransparent(bool blend, bool blend_bypass, bool depth_write, bool depth_test,
                                bool depth_always) {
    return blend && !blend_bypass && !depth_write && depth_test && !depth_always;
}

/// The scene's `height` is the upscaler's input (render) height: its output has the same
/// picture on more pixels, so a stroke that is a set share of the render height is that share
/// of the screen whatever the upscaler mode.
/// `previous`: the camera of the frame before, or null when there was none (the first painted
/// frame, the frame after one that was not painted). Without it, and after a cut the words
/// cannot hold (a turn of more than 120 degrees, a lens more than twice or less than half as
/// long, a mirrored camera), FlagPrevious is not set.
inline Params Make(const Knobs& knobs, const std::array<float, 12>& inv_view,
                   const std::array<float, 4>& proj, std::uint32_t width, std::uint32_t height,
                   const std::array<float, 2>& jitter, bool normals, bool motion,
                   const Previous* previous = nullptr) {
    const float scale = float(height) / 2160.0f * knobs.stroke_size;
    Params params{
        .inv_view = inv_view,
        .proj = proj,
        .size = {float(width), float(height)},
        .jitter = jitter,
        .strength = knobs.strength,
        .brush = knobs.texture,
        .characters = knobs.characters,
        // Under two pixels a cell a stroke is no longer a shape.
        .cell_bold = std::max(BoldCellAt2160 * scale, 2.0f),
        .back_turn = {},
        .cell_fine = std::max(FineCellAt2160 * scale, 2.0f),
        .back_shift = {},
        .flags = (normals ? FlagNormals : 0u) | (motion ? FlagMotion : 0u) |
                 std::uint32_t(std::clamp(knobs.view, int(ViewOff), int(ViewMax))) << ViewShift |
                 32768u << ZoomShift,
    };
    if (!previous) {
        return params;
    }
    // previous view * this frame's inverse view: [turn | shift], 3x4 rows.
    double turn[3][3], shift[3];
    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j < 3; ++j) {
            turn[i][j] = 0.0;
            for (int k = 0; k < 3; ++k) {
                turn[i][j] += double(previous->view[i * 4 + k]) * double(inv_view[k * 4 + j]);
            }
        }
        shift[i] = double(previous->view[i * 4 + 3]);
        for (int k = 0; k < 3; ++k) {
            shift[i] += double(previous->view[i * 4 + k]) * double(inv_view[k * 4 + 3]);
        }
    }
    const double w = 0.5 * std::sqrt(std::max(1.0 + turn[0][0] + turn[1][1] + turn[2][2], 0.0));
    const double zoom_x = double(previous->proj[0]) / double(proj[0]);
    const double zoom = double(previous->proj[1]) / double(proj[1]);
    // (Written so that a number that is none fails every test.)
    if (!(w > 0.5) || !(zoom > 0.5 && zoom < 1.999) || !(std::abs(zoom_x - zoom) < 1e-3 * zoom)) {
        return params;
    }
    const double q[3] = {(turn[2][1] - turn[1][2]) / (4.0 * w), (turn[0][2] - turn[2][0]) / (4.0 * w),
                         (turn[1][0] - turn[0][1]) / (4.0 * w)};
    // A turn has a quaternion of length 1; a mirrored camera's "turn" has not.
    const double length2 = w * w + q[0] * q[0] + q[1] * q[1] + q[2] * q[2];
    if (!(std::abs(length2 - 1.0) < 1e-3) ||
        !(std::isfinite(shift[0]) && std::isfinite(shift[1]) && std::isfinite(shift[2]))) {
        return params;
    }
    params.back_turn = {float(q[0]), float(q[1]), float(q[2])};
    params.back_shift = {float(shift[0]), float(shift[1]), float(shift[2])};
    const auto zoom_bits = std::uint32_t(
        std::clamp(std::lround((zoom - 1.0) * 32768.0) + 32768l, 0l, 65535l));
    params.flags = (params.flags & ~(0xffffu << ZoomShift)) | zoom_bits << ZoomShift | FlagPrevious;
    return params;
}

} // namespace Vulkan::DrawnLookParams
"""),
    ],
    H + "paint_common.glsl": [
        (r"""    vec2 jitter;      // this frame's viewport shift in pixels (x right, y down)
    float strength;   // graphics_drawn_look_strength, 0..1
    float brush;      // graphics_drawn_look_texture, 0..1.2: the brush's marks in a stroke
    float outlines;   // graphics_drawn_look_outlines, 0..1 (ink)
    float ink_world;  // graphics_drawn_look_ink_world, 0..1 (ink)
    float characters; // graphics_drawn_look_characters, 0..1: the strength on what moves by itself
    float cell_bold;  // the cell of a bold stroke on the screen, pixels of the scene
    float cell_fine;  // the cell of a fine stroke
    uint flags;       // FLAG_*; bits 8..10: the test view (VIEW_*)
};

const uint FLAG_NORMALS = 1u; // normal_tex holds the G-buffer's world normals
const uint FLAG_MOTION = 2u;  // motion_tex holds this frame's object motion
const uint VIEW_STROKES = 1u; // every stroke in a flat colour of its own, sizes as the look mixes them
const uint VIEW_FINE = 2u;    // the same, every stroke at the fine size
const uint VIEW_BOLD = 4u;    // the same, every stroke at the bold size
""",
         r"""    vec2 jitter;      // this frame's viewport shift in pixels (x right, y down)
    float strength;   // graphics_drawn_look_strength, 0..1
    float brush;      // graphics_drawn_look_texture, 0..1.2: the brush's marks in a stroke
    float characters; // graphics_drawn_look_characters, 0..1: the strength on what moves by itself
    float cell_bold;  // the cell of a bold stroke on the screen, pixels of the scene
    // FLAG_PREVIOUS: from this frame's view axes to those of the frame before, a turn (the
    // vector part of its unit quaternion, the scalar part positive), then a shift in metres.
    vec3 back_turn;
    float cell_fine;  // the cell of a fine stroke
    vec3 back_shift;
    // FLAG_*; bits 8..10: the test view (VIEW_*); bits 16..31: the lens of the frame before
    // over this frame's, (ratio - 1) * 32768 + 32768.
    uint flags;
};

const uint FLAG_NORMALS = 1u; // normal_tex holds the G-buffer's world normals
const uint FLAG_MOTION = 2u;  // motion_tex holds this frame's object motion
const uint FLAG_PREVIOUS = 4u; // back_turn, back_shift and the lens' ratio are the frame before's
const uint VIEW_STROKES = 1u; // every stroke in a flat colour of its own, sizes as the look mixes them
const uint VIEW_FINE = 2u;    // the same, every stroke at the fine size
const uint VIEW_BOLD = 4u;    // the same, every stroke at the bold size
"""),
        (r"""    return clamp(mix(rgb, vec3(0.0), isnan(rgb)), 0.0, 60000.0);
}

// A texel of the object motion image (rg pixels, b 1 where a draw with vectors of its own wrote
// it, a the depth it wrote at) says the pixel at `depth` moves by itself: a character, or
// whatever else has a bone buffer, and nothing was drawn over it since (the test
// camera_motion.comp makes).
bool ownMotion(vec4 motion, float depth) {
    return motion.b > 0.99 && abs(motion.a - depth) < max(2e-7, (proj.z - depth) * 0.01);
}
""",
         r"""    return clamp(mix(rgb, vec3(0.0), isnan(rgb)), 0.0, 60000.0);
}

// A texel of the object motion image (rg pixels, previous - current; b 1 where a draw with
// vectors of its own wrote it, a the depth it wrote at) holds the vector of the pixel at
// `depth`: a draw whose vertices of the frame before are known wrote the pixel, and nothing was
// drawn over it since (the test camera_motion.comp makes). That is every character, and most of
// the world as well: walls and floors drawn through a bone buffer have such vectors too, and
// theirs say what the camera did.
bool ownMotion(vec4 motion, float depth) {
    return motion.b > 0.99 && abs(motion.a - depth) < max(2e-7, (proj.z - depth) * 0.01);
}
"""),
        (r"""vec3 viewPos(vec2 pixel, float z) {
    const vec2 ndc = (pixel - jitter) / size * 2.0 - 1.0;
    return vec3(ndc.x * z / proj.x, ndc.y * z / proj.y, z);
}

// Where a view position lies on the screen, in pixels of this frame (jitter put back).
""",
         r"""vec3 viewPos(vec2 pixel, float z) {
    const vec2 ndc = (pixel - jitter) / size * 2.0 - 1.0;
    return vec3(ndc.x * z / proj.x, ndc.y * z / proj.y, z);
}

// (r45b_drawn-look-fixes) The pixels by which the camera's own move from the frame before
// shifts a point that lies still at view position c: previous - current, without the jitter, as
// camera_motion.comp works it out and as the object motion image holds it. FLAG_PREVIOUS.
vec2 cameraShift(vec3 c) {
    const float w = sqrt(max(1.0 - dot(back_turn, back_turn), 0.0));
    const vec3 before =
        c + 2.0 * (w * cross(back_turn, c) + cross(back_turn, cross(back_turn, c))) + back_shift;
    const float zoom = 1.0 + (float(flags >> 16u) - 32768.0) / 32768.0;
    return (before.xy * zoom / max(before.z, 1e-4) - c.xy / max(c.z, 1e-4)) * proj.xy * 0.5 * size;
}

// A point counts as moving by itself from the first of these speeds, and fully from the
// second: pixels a frame on a scene of 1080 lines, against where the camera's own move puts it.
// Below the first lies what the depth's and the vectors' rounding makes of a still wall.
const vec2 MOVES_SPEED = vec2(0.25, 1.0);

// How much the pixel at `depth` moves by itself, 0..1: `motion` is its texel of the object motion
// image, `at` its centre (pixel + 0.5). A character that walks, a door that swings, a branch in
// the wind: 1. A wall, and a character that stands still: 0, whatever the camera does. Without
// the camera of the frame before nothing tells the two apart: what has a vector counts as
// moving for that frame, as it did before r45b for every frame.
float movesItself(vec4 motion, float depth, vec2 at) {
    if (!ownMotion(motion, depth)) {
        return 0.0;
    }
    if ((flags & FLAG_PREVIOUS) == 0u) {
        return 1.0;
    }
    const vec2 own = motion.rg - cameraShift(viewPos(at, viewZ(depth)));
    // A vector that is no number: the upscaler takes the camera's for it, so does the look.
    if (any(isnan(own)) || any(isinf(own))) {
        return 0.0;
    }
    return smoothstep(MOVES_SPEED.x, MOVES_SPEED.y, length(own) * 1080.0 / size.y);
}

// Where a view position lies on the screen, in pixels of this frame (jitter put back).
"""),
    ],
    H + "paint_strokes.comp": [
        (r"""float lum_floor;  // the frame's black (blackLevel)
float tone_floor; // the same as a tone (toneOf)
// In the test view (graphics_drawn_look_debug 1, 2 or 4) every dab has a flat colour of its
// own, grey where the surface moves by itself.
bool test_view = false;
bool test_grey = false;
// What shows between the look's dabs (calmColour), worked out for the first dab that needs it.
vec3 under = vec3(0.0);
bool have_under = false;
""",
         r"""float lum_floor;  // the frame's black (blackLevel)
float tone_floor; // the same as a tone (toneOf)
// In the test view (graphics_drawn_look_debug 1, 2 or 4) every dab has a flat colour of its
// own, grey by as much as the surface moves by itself (movesItself).
bool test_view = false;
float test_grey = 0.0;
// What shows between the look's dabs (calmColour), worked out for the first dab that needs it.
vec3 under = vec3(0.0);
bool have_under = false;
"""),
        (r"""        }
    }
    return depthNormal(pixel, c);
}

bool movesItself(ivec2 pixel, float depth) {
    return (flags & FLAG_MOTION) != 0u && ownMotion(texelFetch(motion_tex, pixel, 0), depth);
}

// How much fine detail lies around a place of the screen: 0 a plain surface, which takes bold
""",
         r"""        }
    }
    return depthNormal(pixel, c);
}

// How much fine detail lies around a place of the screen: 0 a plain surface, which takes bold
"""),
        (r"""            return own.rgb;
        }
        vec3 flat_colour = idColour(dab.id) * (1.0 + 0.5 * dab.idv);
        if (test_grey) {
            flat_colour = vec3(dot(flat_colour, LUMA));
        }
        return flat_colour * dabLuminance(rel, flat_n, plane, dab.offset, own.lum);
    }
    vec4 paint = vec4(0.0);
""",
         r"""            return own.rgb;
        }
        vec3 flat_colour = idColour(dab.id) * (1.0 + 0.5 * dab.idv);
        flat_colour = mix(flat_colour, vec3(dot(flat_colour, LUMA)), test_grey);
        return flat_colour * dabLuminance(rel, flat_n, plane, dab.offset, own.lum);
    }
    vec4 paint = vec4(0.0);
"""),
        (r"""    const float detail = view == VIEW_FINE ? 1.0 : view == VIEW_BOLD ? 0.0 : detailAt(uv);
    // What moves by itself would slide under strokes that lie still in the world: it is
    // smoothed instead, by its own share of the strength (the test view shows its dabs grey).
    const bool moving = movesItself(pixel, depth);
    test_grey = moving;
    const float amount = strength * (moving ? characters : 1.0);
    if (amount <= 0.0 && !test_view) {
        return;
    }
""",
         r"""    const float detail = view == VIEW_FINE ? 1.0 : view == VIEW_BOLD ? 0.0 : detailAt(uv);
    // What moves by itself would slide under strokes that lie still in the world: it is
    // smoothed instead, by its own share of the strength (the test view shows its dabs grey).
    // (r45b_drawn-look-fixes) Moving by itself is told against the camera's own move
    // (paint_common.glsl, movesItself): having a vector in the object motion image is not it,
    // most of the world has one, and all of that got smoothed and no strokes.
    const float moving = (flags & FLAG_MOTION) != 0u
                             ? movesItself(texelFetch(motion_tex, pixel, 0), depth,
                                           vec2(pixel) + 0.5)
                             : 0.0;
    test_grey = moving;
    const float amount = strength * mix(1.0, characters, moving);
    if (amount <= 0.0 && !test_view) {
        return;
    }
"""),
        (r"""                   vec4(strokeColour(uv, rel, n, flat_n, detail, own), scene.a));
        return;
    }
    const vec3 paint = moving ? calmColour(uv, cell_fine, own)
                              : strokeColour(uv, rel, n, flat_n, detail, own);
    const float keep = keepOwn(uv, paint, own, key);
    const vec3 rgb = mix(scene.rgb, paint, amount * (1.0 - keep));
    // A scene colour that is no number stays what it is.
""",
         r"""                   vec4(strokeColour(uv, rel, n, flat_n, detail, own), scene.a));
        return;
    }
    // Between still and moving (MOVES_SPEED) the strokes fade into the smoothed scene.
    vec3 paint = vec3(0.0);
    if (moving < 1.0) {
        paint = strokeColour(uv, rel, n, flat_n, detail, own);
    }
    if (moving > 0.0) {
        paint = mix(paint, calmColour(uv, cell_fine, own), moving);
    }
    const float keep = keepOwn(uv, paint, own, key);
    const vec3 rgb = mix(scene.rgb, paint, amount * (1.0 - keep));
    // A scene colour that is no number stays what it is.
"""),
    ],
    H + "paint_lock.comp": [
        (r"""        return;
    }
    if (characters <= 0.0 && (flags & FLAG_MOTION) != 0u &&
        ownMotion(texelFetch(motion_tex, pixel, 0), depth)) {
        return;
    }
    const vec2 uv = (vec2(pixel) + 0.5) / size;
""",
         r"""        return;
    }
    if (characters <= 0.0 && (flags & FLAG_MOTION) != 0u &&
        movesItself(texelFetch(motion_tex, pixel, 0), depth, vec2(pixel) + 0.5) >= 1.0) {
        return;
    }
    const vec2 uv = (vec2(pixel) + 0.5) / size;
"""),
    ],
    R + "vk_drawn_look.h": [
        (r"""#include <span>
#include <vector>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

""",
         r"""#include <span>
#include <vector>
#include "common/types.h"
#include "video_core/renderer_vulkan/drawn_look_params.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

"""),
        (r"""    /// it (a reflection in water, from a mirrored camera, with a depth of its own), and strokes
    /// painted there would leave the scene without any.
    /// The first blended draw without depth writes into the scene colour: the solid surfaces
    /// are in, the transparents start. The place the look is designed for.
    void OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                        std::array<float, 2> jitter);
    /// A full-screen pass over the scene colour with fragment shader `hash`. On a frame with
    /// transparents the first such pass after them is remembered (the fog composite; another
    /// one takes its place only after it came first on CompositeFrames such frames in a row);
    /// on a frame without any, the strokes are painted before that same pass, so the fog is
    /// left unpainted on both kinds of frame.
    void OnSceneComposite(u64 hash, VideoCore::ImageId color, VideoCore::ImageId depth,
                          std::array<float, 2> jitter);
    /// Right before the upscaler's trigger: the last chance of a frame that had neither. Fog
    /// and particles are in the scene by now and get painted; such frames are counted.
    void OnBeforeUpscaler(VideoCore::ImageId color, VideoCore::ImageId depth,
""",
         r"""    /// it (a reflection in water, from a mirrored camera, with a depth of its own), and strokes
    /// painted there would leave the scene without any.
    /// The first blended draw without depth writes into the scene colour: the solid surfaces
    /// are in, the transparents start. The place the look is designed for. A draw of six
    /// indices or fewer counts when it tests the depth (a particle system of a few particles;
    /// r45b_drawn-look-fixes: it used to be taken for a full-screen pass and painted over):
    /// DrawnLookParams::SmallTransparent.
    void OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                        std::array<float, 2> jitter);
    /// A full-screen pass over the scene colour with fragment shader `hash` (a draw of six
    /// indices or fewer that is not one of the transparents above). On a frame with
    /// transparents the first such pass after them is remembered (the fog composite; another
    /// one takes its place only after it came first on CompositeFrames such frames in a row);
    /// on a frame without any, the strokes are painted before that same pass, so the fog is
    /// left unpainted on both kinds of frame.
    void OnSceneComposite(u64 hash, VideoCore::ImageId color, VideoCore::ImageId depth,
                          std::array<float, 2> jitter);
    /// (r45b_drawn-look-fixes) The draw that OnBlendedScene is called for next is a small one
    /// (DrawnLookParams::SmallTransparent), with fragment shader `hash`: when it is the frame's
    /// first transparent draw the log names it, once a shader.
    void OnSmallTransparent(u64 hash, u32 indices);
    /// Right before the upscaler's trigger: the last chance of a frame that had neither. Fog
    /// and particles are in the scene by now and get painted; such frames are counted.
    void OnBeforeUpscaler(VideoCore::ImageId color, VideoCore::ImageId depth,
"""),
        (r"""    /// The full-screen passes of this frame so far, by shader, and the one that follows the
    /// transparents on the frames that have them (hash 0: none seen yet). `candidate` came
    /// first instead on the last `candidate_frames` such frames: a small sprite among the
    /// transparents is drawn as such a pass too, and must not take the fog composite's place
    /// for being first once.
    static constexpr u32 CompositeFrames = 30;
    std::array<FullScreenPass, 16> frame_passes{};
    u32 frame_pass_count = 0;
""",
         r"""    /// The full-screen passes of this frame so far, by shader, and the one that follows the
    /// transparents on the frames that have them (hash 0: none seen yet). `candidate` came
    /// first instead on the last `candidate_frames` such frames: a small sprite among the
    /// transparents that does not test the depth is drawn as such a pass too, and must not
    /// take the fog composite's place for being first once.
    static constexpr u32 CompositeFrames = 30;
    std::array<FullScreenPass, 16> frame_passes{};
    u32 frame_pass_count = 0;
"""),
        (r"""    /// For the line every 600 frames the look was wanted on.
    std::array<u32, ResultCount> results{};
    u32 frames = 0;
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) do: those may come
    /// and go with the place a frame is painted at.
""",
         r"""    /// For the line every 600 frames the look was wanted on.
    std::array<u32, ResultCount> results{};
    u32 frames = 0;
    /// (r45b_drawn-look-fixes) The camera the last frame was painted with, for the frame after
    /// it (DrawnLookParams::Make, `previous`). `last_camera_set`: this frame stored one;
    /// `last_camera_valid`: the frame before did. `previous_frames`: for the line every 600
    /// frames.
    DrawnLookParams::Previous last_camera{};
    bool last_camera_set = false;
    bool last_camera_valid = false;
    u32 previous_frames = 0;
    /// The small transparent draw OnSmallTransparent announced, and the shaders already named.
    u64 small_hash = 0;
    u32 small_indices = 0;
    bool small_pending = false;
    std::array<u64, 8> small_seen{};
    u32 small_seen_count = 0;
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) do: those may come
    /// and go with the place a frame is painted at.
"""),
    ],
    R + "vk_drawn_look.cpp": [
        (r"""    gbuffer_normal = normal;
}

void DrawnLook::OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                               std::array<float, 2> jitter) {
    if (!SceneDepth(depth)) {
        return;
    }
    blended_this_frame = true;
    Paint(AtBlended, color, depth, jitter);
""",
         r"""    gbuffer_normal = normal;
}

void DrawnLook::OnSmallTransparent(u64 hash, u32 indices) {
    small_hash = hash;
    small_indices = indices;
    small_pending = true;
}

void DrawnLook::OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                               std::array<float, 2> jitter) {
    const bool small = small_pending;
    small_pending = false;
    if (!SceneDepth(depth)) {
        return;
    }
    // The frame's first transparent draw is a small one: its state told it from a full-screen
    // pass (DrawnLookParams::SmallTransparent). Each shader that does this is named once, so a
    // lighting pass taken for a particle (the strokes would go in before the light is
    // complete) shows in the log.
    if (small && !blended_this_frame && frame_result == NotReached &&
        std::find(small_seen.begin(), small_seen.begin() + small_seen_count, small_hash) ==
            small_seen.begin() + small_seen_count) {
        if (small_seen_count < small_seen.size()) {
            small_seen[small_seen_count++] = small_hash;
            std::printf("Drawn look: a frame's first transparent draw is a small one (%u indices, "
                        "ps %016llx): blended, no depth written, depth tested; the strokes are "
                        "painted before it\n",
                        small_indices, static_cast<unsigned long long>(small_hash));
        }
    }
    blended_this_frame = true;
    Paint(AtBlended, color, depth, jitter);
"""),
        (r"""                             "on %u, before the fog composite (no transparents) on %u, before "
                             "the upscaler (neither: fog and particles painted too) on %u; not "
                             "painted: %u menu previews, %u without a camera, %u for want of "
                             "video memory, %u without a scene\n",
                             frames, results[AtBlended], results[AtComposite],
                             results[AtBeforeUpscaler], results[Preview], results[NoCamera],
                             results[NoRoom], results[NotReached]);
            results = {};
            frames = 0;
        }
        // The scene's depth is the last G-buffer pass's (as CameraMotion and the upscaler take
        // it): remembered, so that an earlier pass of a frame is known not to be the scene.
        if (gbuffer_depth && std::find(scene_depths.begin(), scene_depths.end(), gbuffer_depth) ==
""",
         r"""                             "on %u, before the fog composite (no transparents) on %u, before "
                             "the upscaler (neither: fog and particles painted too) on %u; not "
                             "painted: %u menu previews, %u without a camera, %u for want of "
                             "video memory, %u without a scene; what moves by itself told "
                             "against the camera of the frame before on %u\n",
                             frames, results[AtBlended], results[AtComposite],
                             results[AtBeforeUpscaler], results[Preview], results[NoCamera],
                             results[NoRoom], results[NotReached], previous_frames);
            results = {};
            frames = 0;
            previous_frames = 0;
        }
        // The camera the frame was painted with is the next frame's "frame before"; a frame
        // that was not painted leaves none.
        last_camera_valid = frame_result <= AtBeforeUpscaler && last_camera_set;
        // The scene's depth is the last G-buffer pass's (as CameraMotion and the upscaler take
        // it): remembered, so that an earlier pass of a frame is known not to be the scene.
        if (gbuffer_depth && std::find(scene_depths.begin(), scene_depths.end(), gbuffer_depth) ==
"""),
        (r"""            }
        }
    }
    was_wanted = wanted;
    frame_result = NotReached;
    blended_this_frame = false;
""",
         r"""            }
        }
    }
    if (!was_wanted) {
        last_camera_valid = false;
    }
    last_camera_set = false;
    small_pending = false;
    was_wanted = wanted;
    frame_result = NotReached;
    blended_this_frame = false;
"""),
        (r"""        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
        .stroke_size = s.graphics_drawn_look_stroke_size.load(std::memory_order_relaxed),
        .texture = s.graphics_drawn_look_texture.load(std::memory_order_relaxed),
        .outlines = s.graphics_drawn_look_outlines.load(std::memory_order_relaxed),
        .ink_world = s.graphics_drawn_look_ink_world.load(std::memory_order_relaxed),
        .characters = s.graphics_drawn_look_characters.load(std::memory_order_relaxed),
        .view = env_view >= 0 ? env_view
                              : s.graphics_drawn_look_debug.load(std::memory_order_relaxed),
    };
    const auto params = DrawnLookParams::Make(knobs, camera.inv_view, camera.proj, width, height,
                                              jitter, has_normal, has_motion);
    const u32 view = params.flags >> DrawnLookParams::ViewShift;
    // A test view shows the strokes' places in colours of its own: no colours to lock.
    const bool locked = view == DrawnLookParams::ViewOff || view == DrawnLookParams::ViewInk;
    // The inputs may come and go from frame to frame (a frame painted right before the upscaler
""",
         r"""        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
        .stroke_size = s.graphics_drawn_look_stroke_size.load(std::memory_order_relaxed),
        .texture = s.graphics_drawn_look_texture.load(std::memory_order_relaxed),
        .characters = s.graphics_drawn_look_characters.load(std::memory_order_relaxed),
        .view = env_view >= 0 ? env_view
                              : s.graphics_drawn_look_debug.load(std::memory_order_relaxed),
    };
    // (r45b_drawn-look-fixes) The camera of the frame before, when that frame was painted: the
    // object motion's vectors are told from the camera's own move with it.
    const auto params = DrawnLookParams::Make(knobs, camera.inv_view, camera.proj, width, height,
                                              jitter, has_normal, has_motion,
                                              last_camera_valid ? &last_camera : nullptr);
    last_camera = {camera.view, camera.proj};
    last_camera_set = true;
    previous_frames += (params.flags & DrawnLookParams::FlagPrevious) != 0;
    const u32 view = DrawnLookParams::ViewOf(params.flags);
    // A test view shows the strokes' places in colours of its own: no colours to lock.
    const bool locked = view == DrawnLookParams::ViewOff || view == DrawnLookParams::ViewInk;
    // The inputs may come and go from frame to frame (a frame painted right before the upscaler
"""),
    ],
    R + "vk_rasterizer.cpp": [
        (r"""                EffectsBlendedScene();
                upscaler->OnBlendedSceneDraw();
            } else if (regs.num_indices <= 6 && regs.num_instances.NumInstances() <= 1) {
                // A full-screen pass over the scene (the fog composite): the transparents are in.
                EffectsSceneComposite(pipeline);
                upscaler->OnSceneComposite();
            }
        }
""",
         r"""                EffectsBlendedScene();
                upscaler->OnBlendedSceneDraw();
            } else if (regs.num_indices <= 6 && regs.num_instances.NumInstances() <= 1) {
                // bbport (r45b_drawn-look-fixes): a particle system of six indices or fewer (a
                // card of fog, a few sparks) is as small a draw as a full-screen pass, and is one
                // of the transparents: blended, no depth written, tested against the scene's
                // depth. The drawn look paints before it as before a larger one (it was painted
                // over: one card of fog a frame at the place this was found, up to fifteen draws
                // in a level's first seconds) and does not take it for the fog composite. Only with
                // the look on; the upscaler's two calls are as they were.
                if (drawn_look_wanted &&
                    DrawnLookParams::SmallTransparent(
                        regs.blend_control[0].enable, regs.color_buffers[0].info.blend_bypass,
                        regs.depth_control.depth_write_enable, regs.depth_control.depth_enable,
                        regs.depth_control.depth_func == AmdGpu::CompareFunc::Always)) {
                    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
                    drawn_look->OnSmallTransparent(ps ? ps->pgm_hash : 0, regs.num_indices);
                    EffectsBlendedScene();
                } else {
                    // A full-screen pass over the scene (the fog composite): the transparents
                    // are in.
                    EffectsSceneComposite(pipeline);
                }
                upscaler->OnSceneComposite();
            }
        }
"""),
    ],
    TESTS + "test_drawn_look.cpp": [
        (r"""//  - the look keeps the picture's colours: the mean colour of every surface stays, the sky and
//    the alpha are not touched, a brighter or darker scene (another exposure) gets the same look;
//  - it flattens fine grit, leaves what moves by itself without strokes, and a colour that is no
//    number does not spread.
//
// drawn-look-test [picture.bmp]: with a path, four views of the scene are also written.
// drawn-look-test --picture in.bmp out [2]: the look on a picture (24-bit BMP, sRGB), laid on a
""",
         r"""//  - the look keeps the picture's colours: the mean colour of every surface stays, the sky and
//    the alpha are not touched, a brighter or darker scene (another exposure) gets the same look;
//  - it flattens fine grit, leaves what moves by itself without strokes, and a colour that is no
//    number does not spread;
//  - (r45b_drawn-look-fixes) what moves by itself is told against the camera's own move: a wall
//    with a vector in the object motion image gets its strokes whatever the camera does, a ball
//    that lies still does too, one that moves does not; and which small draws count as
//    transparents (DrawnLookParams::SmallTransparent).
//
// drawn-look-test [picture.bmp]: with a path, four views of the scene are also written.
// drawn-look-test --picture in.bmp out [2]: the look on a picture (24-bit BMP, sRGB), laid on a
"""),
        (r"""        }
        return rows;
    }
};

/// The projection's scales for a screen of this shape: 50 degrees from top to bottom.
""",
         r"""        }
        return rows;
    }
    /// World to view, 3x4 rows.
    std::array<float, 12> View() const {
        const std::array<Vec3, 3> axes{Right(), Down(), Forward()};
        std::array<float, 12> rows;
        for (int i = 0; i < 3; ++i) {
            for (int k = 0; k < 3; ++k) {
                rows[i * 4 + k] = float(axes[i][k]);
            }
            rows[i * 4 + 3] = float(-Dot(axes[i], pos));
        }
        return rows;
    }
};

/// The projection's scales for a screen of this shape: 50 degrees from top to bottom.
"""),
        (r"""/// just rough enough to count as detail, and the look goes from bold strokes to fine ones.
enum class Paint { Plain, Lit, Grit, Patches };

Scene MakeScene(const Lens& lens, const Camera& camera, Paint paint, float exposure = 1.0f) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    scene.surface.resize(size_t(w) * h);
""",
         r"""/// just rough enough to count as detail, and the look goes from bold strokes to fine ones.
enum class Paint { Plain, Lit, Grit, Patches };

/// What the object motion image holds for a scene. Without `before`: as the scenes of r45, the
/// ball alone has a vector, and it is zero. With `before` (the camera of the frame before and
/// its lens): the ball's vector is what the camera's own move makes of a still point there
/// plus `ball` pixels of its own, and with `world` every surface has a vector too, the
/// camera's: what the game's walls and floors drawn through a bone buffer have.
struct Vectors {
    const Camera* before = nullptr;
    const Lens* lens_before = nullptr;
    bool world = false;
    std::array<float, 2> ball{};
};

/// Where a world point lies on a camera's screen in pixels, without the jitter.
std::array<double, 2> Place(const Lens& lens, const Camera& camera, const Vec3& world) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    const double z = Dot(rel, camera.Forward());
    return {(Dot(rel, camera.Right()) * lens.xs / z * 0.5 + 0.5) * lens.width,
            (Dot(rel, camera.Down()) * lens.ys / z * 0.5 + 0.5) * lens.height};
}

Scene MakeScene(const Lens& lens, const Camera& camera, Paint paint, float exposure = 1.0f,
                const Vectors& vectors = {}) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    scene.surface.resize(size_t(w) * h);
"""),
        (r"""                scene.normal[i][k] = u8(std::lround((hit.normal[k] * 0.5 + 0.5) * 255.0));
            }
            scene.normal[i][3] = 255;
            if (hit.surface == Ball) {
                scene.motion[i] = {0.0f, 0.0f, 1.0f, scene.depth[i]};
            }
        }
    }
""",
         r"""                scene.normal[i][k] = u8(std::lround((hit.normal[k] * 0.5 + 0.5) * 255.0));
            }
            scene.normal[i][3] = 255;
            if (hit.surface == Ball && !vectors.before) {
                scene.motion[i] = {0.0f, 0.0f, 1.0f, scene.depth[i]};
            } else if (vectors.before && hit.surface != Sky &&
                       (vectors.world || hit.surface == Ball)) {
                // Previous - current, pixels, as the game's vertex positions give it.
                const auto now = Place(lens, camera, p);
                const auto then = Place(*vectors.lens_before, *vectors.before, p);
                const bool ball = hit.surface == Ball;
                scene.motion[i] = {float(then[0] - now[0]) + (ball ? vectors.ball[0] : 0.0f),
                                   float(then[1] - now[1]) + (ball ? vectors.ball[1] : 0.0f),
                                   1.0f, scene.depth[i]};
            }
        }
    }
"""),
        (r"""
    /// The colour lock runs with the look; a test view has no colours to lock.
    static bool ShowsLook(const Look::Params& params) {
        const u32 view = params.flags >> Look::ViewShift;
        return view == Look::ViewOff || view == Look::ViewInk;
    }

""",
         r"""
    /// The colour lock runs with the look; a test view has no colours to lock.
    static bool ShowsLook(const Look::Params& params) {
        const u32 view = Look::ViewOf(params.flags);
        return view == Look::ViewOff || view == Look::ViewInk;
    }

"""),
        (r"""    failed |= !ok;
}

Look::Params Words(const Lens& lens, const Camera& camera, int view, bool normals = true,
                   bool motion = false, float strength = 0.6f, float characters = 0.5f) {
    Look::Knobs knobs;
    knobs.strength = strength;
    knobs.characters = characters;
    knobs.view = view;
    return Look::Make(knobs, camera.InvView(), lens.Proj(), lens.width, lens.height,
                      camera.jitter, normals, motion);
}

/// Where a world point lies on the camera's screen (the pixel it falls in) and how deep.
""",
         r"""    failed |= !ok;
}

/// `before`, `lens_before`: the camera of the frame before and its lens (none: this frame's), or
/// no camera of the frame before.
Look::Params Words(const Lens& lens, const Camera& camera, int view, bool normals = true,
                   bool motion = false, float strength = 0.6f, float characters = 0.5f,
                   const Camera* before = nullptr, const Lens* lens_before = nullptr) {
    Look::Knobs knobs;
    knobs.strength = strength;
    knobs.characters = characters;
    knobs.view = view;
    Look::Previous previous{};
    if (before) {
        previous = {before->View(), (lens_before ? lens_before : &lens)->Proj()};
    }
    return Look::Make(knobs, camera.InvView(), lens.Proj(), lens.width, lens.height,
                      camera.jitter, normals, motion, before ? &previous : nullptr);
}

/// Where a world point lies on the camera's screen (the pixel it falls in) and how deep.
"""),
        (r"""               "what moves by itself is smoothed, not stroked");
    }
    {
        // A colour that is no number, an endless one and one below 0 stay where they are.
        Scene broken = MakeScene(lens, straight, Paint::Grit);
        const u32 at = (lens.height * 3 / 4) * lens.width + lens.width / 2;
""",
         r"""               "what moves by itself is smoothed, not stroked");
    }
    {
        // (r45b_drawn-look-fixes) Having a vector in the object motion image is not moving: in
        // the game most of the world has one (walls and floors drawn through a bone buffer),
        // and it says what the camera did. Every surface has such a vector here. The camera
        // stood still since the frame before, or turned and walked, or turned and zoomed: the
        // surfaces get the strokes they get without the image, pixel for pixel; a ball that
        // lies still gets them too; a ball that moves three pixels a frame is smoothed. Without
        // the camera of the frame before nothing tells still from moving, and all of it is
        // smoothed (what r45 did on every frame).
        const Lens longer{large.width, large.height, large.ys * 1.07};
        struct Case {
            const char* name;
            const Camera* before;
            const Lens* lens_before;
        };
        const Case cases[] = {{"the camera stood still", &first, &large},
                              {"the camera turned and walked", &walked, &large},
                              {"the camera turned and zoomed", &turned, &longer}};
        const Scene plain = MakeScene(large, first, Paint::Plain);
        const auto fixed = gpu.Run(plain, Words(large, first, Look::ViewOff, true, false, 1.0f));
        u32 world = 0, ball = 0, world_stroked = 0;
        for (u32 i = 0; i < pixels; ++i) {
            world += plain.surface[i] != Sky && plain.surface[i] != Ball;
            ball += plain.surface[i] == Ball;
            world_stroked += plain.surface[i] != Sky && plain.surface[i] != Ball &&
                             std::abs(Change(plain, fixed, i)) > 0.02;
        }
        bool ok = world > pixels / 2 && ball > 5000 && world_stroked > world / 4;
        for (const Case& c : cases) {
            const Vectors still{c.before, c.lens_before, true, {}};
            const Vectors rolls{c.before, c.lens_before, true, {3.0f, 0.0f}};
            const Scene at_rest = MakeScene(large, first, Paint::Plain, 1.0f, still);
            const Scene rolling = MakeScene(large, first, Paint::Plain, 1.0f, rolls);
            const auto words = Words(large, first, Look::ViewOff, true, true, 1.0f, 1.0f,
                                     c.before, c.lens_before);
            ok &= (words.flags & Look::FlagPrevious) != 0;
            const auto rest = gpu.Run(at_rest, words);
            const auto roll = gpu.Run(rolling, words);
            u32 world_off = 0, world_beside = 0, ball_off = 0, ball_marked = 0;
            for (u32 i = 0; i < pixels; ++i) {
                if (plain.surface[i] == Sky) {
                    continue;
                }
                if (plain.surface[i] == Ball) {
                    ball_off += !Same(rest[i], fixed[i]);
                    ball_marked += std::abs(Change(plain, roll, i)) > 0.02;
                } else {
                    // (Beside a smoothed ball the colour lock's means are other ones.)
                    world_off += !Same(rest[i], fixed[i]);
                    world_beside += !Same(roll[i], fixed[i]);
                }
            }
            std::printf("every surface has a vector, %s: %u of %u pixels of the world are not "
                        "the strokes they get without vectors; of the ball's %u pixels %u are "
                        "not when it lies still, and %u change by more than 2%% when it moves "
                        "3 pixels a frame (%u pixels of the world beside it are other ones "
                        "then)\n",
                        c.name, world_off, world, ball, ball_off, ball_marked, world_beside);
            ok &= world_off == 0 && ball_off == 0 && ball_marked < ball / 20 &&
                  world_beside < world / 100;
        }
        {
            const Vectors still{&walked, &large, true, {}};
            const Scene at_rest = MakeScene(large, first, Paint::Plain, 1.0f, still);
            const auto blind = gpu.Run(at_rest, Words(large, first, Look::ViewOff, true, true, 1.0f,
                                                      1.0f));
            u32 marked = 0;
            for (u32 i = 0; i < pixels; ++i) {
                marked += plain.surface[i] != Sky && plain.surface[i] != Ball &&
                          std::abs(Change(plain, blind, i)) > 0.02;
            }
            std::printf("the same without the camera of the frame before: %u pixels of the world "
                        "change by more than 2%% (%u with strokes)\n", marked, world_stroked);
            ok &= marked < world_stroked / 5;
        }
        Expect(ok, "a surface that lies still gets its strokes although it has a vector, "
                   "whatever the camera did; what moves against the camera's move does not");
    }
    {
        // The words of the camera of the frame before (DrawnLookParams::Make).
        const auto same = Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first);
        bool ok = (same.flags & Look::FlagPrevious) != 0 &&
                  (same.flags >> Look::ZoomShift) == 32768u;
        for (int k = 0; k < 3; ++k) {
            ok &= std::abs(same.back_turn[k]) < 1e-6f && std::abs(same.back_shift[k]) < 1e-5f;
        }
        const auto none = Words(large, first, Look::ViewOff, true, true);
        ok &= !(none.flags & Look::FlagPrevious) && (none.flags >> Look::ZoomShift) == 32768u;
        // A cut: the camera looks the other way; and a lens three times as long.
        Camera behind = first;
        behind.yaw += 3.0;
        const Lens tele{large.width, large.height, large.ys * 3.0};
        ok &= !(Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &behind).flags &
                Look::FlagPrevious);
        ok &= !(Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first, &tele).flags &
                Look::FlagPrevious);
        // A mirrored camera (a reflection's) is no turn of this one.
        Look::Previous mirrored{first.View(), large.Proj()};
        for (int k = 0; k < 4; ++k) {
            mirrored.view[4 + k] = -mirrored.view[4 + k];
        }
        ok &= !(Look::Make({}, first.InvView(), large.Proj(), large.width, large.height,
                           first.jitter, true, true, &mirrored).flags & Look::FlagPrevious);
        const Lens longer{large.width, large.height, large.ys * 1.07};
        const auto zoomed = Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first,
                                  &longer);
        ok &= (zoomed.flags & Look::FlagPrevious) != 0 &&
              std::abs(int(zoomed.flags >> Look::ZoomShift) - 32768 - int(0.07 * 32768.0)) <= 1;
        // The zoom's bits lie above the test view's: the view is read without them.
        ok &= Look::ViewOf(zoomed.flags) == u32(Look::ViewOff) &&
              Look::ViewOf(Words(large, first, Look::ViewBold, true, true, 0.6f, 0.5f, &first,
                                 &longer).flags) == u32(Look::ViewBold);
        Expect(ok, "the camera of the frame before becomes a turn, a shift and a zoom, and is "
                   "left out after a cut");
    }
    {
        // Which draws of six indices or fewer are transparents (the rasterizer's scene hook):
        // blended, not bypassed, no depth written, depth tested with a function that can fail.
        using Look::SmallTransparent;
        bool ok = SmallTransparent(true, false, false, true, false);
        u32 counted = 0;
        for (u32 bits = 0; bits < 32; ++bits) {
            const bool blend = bits & 1, bypass = bits & 2, write = bits & 4, test = bits & 8,
                       always = bits & 16;
            if (SmallTransparent(blend, bypass, write, test, always)) {
                ++counted;
                ok &= blend && !bypass && !write && test && !always;
            }
        }
        // A full-screen pass: not blended (a lighting pass, a copy), or blended without a depth
        // test or with one that always passes (the fog composite). A decal: it writes depth.
        ok &= counted == 1 && !SmallTransparent(false, false, false, true, false) &&
              !SmallTransparent(true, false, false, false, false) &&
              !SmallTransparent(true, false, false, true, true) &&
              !SmallTransparent(true, false, true, true, false) &&
              !SmallTransparent(true, true, false, true, false);
        static_assert(SmallTransparent(true, false, false, true, false));
        Expect(ok, "of the draws of six indices or fewer only a blended, depth-tested one that "
                   "writes no depth is a transparent");
    }
    {
        // A colour that is no number, an endless one and one below 0 stay where they are.
        Scene broken = MakeScene(lens, straight, Paint::Grit);
        const u32 at = (lens.height * 3 / 4) * lens.width + lens.width / 2;
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the block of the passes is the same in C++
    and GLSL and 128 bytes; one movesItself(), in paint_common.glsl, used by the strokes and by
    the lock; the rasterizer's hook paints before a small transparent draw only with the look
    on, by the one rule of drawn_look_params.h, and the upscaler's two calls are as they were
    (one OnBlendedSceneDraw, one OnSceneComposite)."""
    ok = True

    def need(what, *counts):
        nonlocal ok
        for text, part, want in counts:
            if text.count(part) != want:
                print("%s (%a found %d times, want %d)" % (what, part[:70], text.count(part), want))
                ok = False

    ras = texts[R + "vk_rasterizer.cpp"]
    nl = "\r\n" if "\r\n" in ras else "\n"
    small = fix("                if (drawn_look_wanted &&\n"
                "                    DrawnLookParams::SmallTransparent(\n"
                "                        regs.blend_control[0].enable, regs.color_buffers[0].info.blend_bypass,\n"
                "                        regs.depth_control.depth_write_enable, regs.depth_control.depth_enable,\n"
                "                        regs.depth_control.depth_func == AmdGpu::CompareFunc::Always)) {\n", nl)
    need("the scene hook should paint before a small transparent draw with the look on, by one condition, and "
         "leave the upscaler's two calls as they were",
         (ras, small, 1), (ras, "drawn_look->OnSmallTransparent(", 1), (ras, "upscaler->OnSceneComposite();", 1),
         (ras, "upscaler->OnBlendedSceneDraw();", 1), (ras, "EffectsSceneComposite(pipeline);", 1))
    # With the look off the new branch is not taken: its first operand is the frame's switch.
    at = ras.find(small)
    if at >= 0 and "} else if (regs.num_indices <= 6 && regs.num_instances.NumInstances() <= 1) {" not in ras[at - 1200:at]:
        print("the new condition is not inside the branch of the draws of six indices or fewer")
        ok = False

    words = texts[R + "drawn_look_params.h"]
    common = texts[H + "paint_common.glsl"]
    need("the block of the passes should be 128 bytes and carry the camera of the frame before",
         (words, "static_assert(sizeof(Params) == 128);", 1), (words, "    std::array<float, 3> back_turn;", 1),
         (words, "    std::array<float, 3> back_shift;", 1), (words, "inline constexpr std::uint32_t FlagPrevious = 4;", 1),
         (words, "constexpr bool SmallTransparent(", 1), (words, "constexpr std::uint32_t ViewOf(", 1),
         (common, "    vec3 back_turn;", 1), (common, "    vec3 back_shift;", 1),
         (common, "const uint FLAG_PREVIOUS = 4u;", 1))
    # The same order of the block's last eight words in both (the first 80 bytes are r45's).
    order_c = [words.find(w) for w in ("float strength;", "float brush;", "float characters;", "float cell_bold;",
                                       "std::array<float, 3> back_turn;", "float cell_fine;",
                                       "std::array<float, 3> back_shift;", "std::uint32_t flags;")]
    order_g = [common.find(w) for w in ("float strength;", "float brush;", "float characters;", "float cell_bold;",
                                        "vec3 back_turn;", "float cell_fine;", "vec3 back_shift;", "uint flags;")]
    if min(order_c) < 0 or min(order_g) < 0 or order_c != sorted(order_c) or order_g != sorted(order_g):
        print("the block of the passes is not in the same order in drawn_look_params.h and paint_common.glsl")
        ok = False

    strokes = texts[H + "paint_strokes.comp"]
    lock = texts[H + "paint_lock.comp"]
    need("there should be one movesItself(), in paint_common.glsl, used by the strokes and by the lock",
         (common, "float movesItself(vec4 motion, float depth, vec2 at) {", 1), (common, "vec2 cameraShift(vec3 c) {", 1),
         (strokes, "bool movesItself(", 0), (strokes, "? movesItself(texelFetch(motion_tex, pixel, 0), depth,", 1),
         (lock, "movesItself(texelFetch(motion_tex, pixel, 0), depth, vec2(pixel) + 0.5) >= 1.0", 1))

    look = texts[R + "vk_drawn_look.cpp"]
    head = texts[R + "vk_drawn_look.h"]
    need("the look should keep the camera a frame was painted with for the next frame and read the test view "
         "with ViewOf",
         (look, "last_camera_valid ? &last_camera : nullptr);", 1),
         (look, "const u32 view = DrawnLookParams::ViewOf(params.flags);", 1),
         (look, "params.flags >> DrawnLookParams::ViewShift", 0),
         (look, "void DrawnLook::OnSmallTransparent(u64 hash, u32 indices) {", 1),
         (head, "    void OnSmallTransparent(u64 hash, u32 indices);", 1),
         (head, "    DrawnLookParams::Previous last_camera{};", 1))

    test = texts[TESTS + "test_drawn_look.cpp"]
    need("the offline test should use ViewOf and hold the rule's truth table",
         (test, "params.flags >> Look::ViewShift", 0), (test, "Look::ViewOf(params.flags)", 1))
    if "using Look::SmallTransparent;" not in test or "static_assert(SmallTransparent(" not in test:
        print("the offline test does not hold SmallTransparent's truth table")
        ok = False
    return ok


def run(mode, quiet=False):
    """The patched (or restored) texts, or None with the reason printed."""
    out = {}
    for path, pairs in EDITS.items():
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
    for path, text in NEW_FILES.items():
        there = os.path.exists(path)
        if mode != "revert" and there:
            if not quiet:
                print("%s is there already" % path)
            return None
        if mode == "revert":
            # Removed only as this script wrote it.
            if not there or open(path, encoding="utf-8", newline="").read() != fix(text, "\r\n"):
                if not quiet:
                    print("%s is not there as this script writes it" % path)
                return None
    if mode != "revert" and not text_check(out):
        return None
    return out


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r45b_drawn-look-fixes.py check|apply|revert   (the tree: R45B_ROOT, else the current "
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
    if mode == "apply":
        for path, text in NEW_FILES.items():
            out[path] = fix(text, "\r\n")
    before = {}
    for path in out:
        before[path] = open(path, "rb").read() if os.path.exists(path) else None
    done = []
    try:
        for path, t in out.items():
            with open(path + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for path in out:
            os.replace(path + TMP, path)
            done.append(path)
        if mode == "revert":
            for path in NEW_FILES:
                before[path] = open(path, "rb").read()
                os.remove(path)
                done.append(path)
    except OSError as e:
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            if before[path] is None:
                os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(before[path])
        for path in out:
            if os.path.exists(path + TMP):
                os.remove(path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
