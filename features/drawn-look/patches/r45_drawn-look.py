# r45_drawn-look: stages 1 and 2 of the "drawn look", an optional hand-painted look (brush strokes
# laid on the world's surfaces, in the spirit of V Rising). check|apply|revert (revert restores
# byte for byte). On top of r1..r42; r43 (which also edits gpu/CMakeLists.txt and
# shim/bbport_settings.h, away from this script's anchors) may be there or not. The tree is the
# directory the script is run from (its root: the one that holds engine/build.sh) unless the
# environment variable R45_ROOT names another root. Nothing is changed in place: every new text
# is written beside its target and moved over it, and a failure puts back what was already
# moved. Source files keep their CRLF line ends; the new files get CRLF. The (old, new) pairs
# below were made from the copy the build and the tests ran on (each old text is found exactly
# once when its turn comes, each new one exactly once on the way back).
#
# WHAT IS BUILT. The switch, the settings, the passes' place in the frame, a test view (stage 1)
# and the strokes themselves (stage 2). NOT built: ink lines, painted shadow edges. With the
# switch off (the default), or the strength at 0, nothing is made and nothing runs: no pipeline,
# no image, no pass; the rasterizer calls DrawnLook::OnFrameEnd (a few assignments) and reads one
# flag at three places of the frame.
#
#  1. Settings (bbport_settings.h/.cpp), all live, all saved, each clamped in Set():
#       graphics_drawn_look            0/1    0     the switch (menu: Picture tab, "Drawn look")
#       graphics_drawn_look_strength   0..1   0.6   how much of the strokes is laid over the
#                                                   game's picture; 0: no pass (menu: slider)
#       graphics_drawn_look_stroke_size 0.6..1.4 1.0 a factor on the strokes' size
#       graphics_drawn_look_texture    0..1.2 1.0   the brush's marks in a stroke
#       graphics_drawn_look_characters 0..1   0.5   share of the strength on what moves by itself
#                                                   (smoothed, not stroked); 0: left untouched
#       graphics_drawn_look_debug      0..4   0     the test view: 1, 2, 4 (3 kept for the ink)
#       _outlines 0..1 (0.35), _shadow_edges 0..1 (1.0), _ink_world 0..1 (0), _shadow_soft
#       0.05..0.3 (0.12), _quality 0/1 (1): parsed, clamped, saved, without effect so far.
#     BB_DRAWN_LOOK_VIEW=1|2|4 (environment) decides the test view instead of the ini key while
#     it is set and is never written to the ini. The colour grade keys of the design (A7,
#     graphics_grade_*) are NOT added: the owner's decision is that colours stay as they are.
#     "Game's own picture" (the menu's button) switches the look off.
#  2. renderer_vulkan/vk_drawn_look.h/.cpp, class DrawnLook, owned by the Rasterizer. A frame's
#     strokes are painted once, at the first of three places that comes (vk_rasterizer.cpp,
#     vk_rasterizer_effects.cpp):
#       a. Rasterizer::EffectsBlendedScene: the first blended draw without depth writes into the
#          scene colour (the design's P3: the solid surfaces and their light are in, fire, glows,
#          fog and particles are not), after SSGI's composite at the same place.
#       b. Rasterizer::EffectsSceneComposite (new): a full-screen pass over the scene colour. On
#          a frame with (a) the first such pass after it is remembered (its fragment shader's
#          hash, and which pass of that shader in the frame it is); on a frame without (a) the
#          strokes are painted before that same pass. So a frame without transparents is painted
#          before its fog composite, and a full-screen lighting pass earlier in the frame cannot
#          be mistaken for it. Only frames painted at (a) teach the pass, and once one is known
#          another takes its place only after it came first on 30 such frames in a row
#          (CompositeFrames): a sprite drawn as a full-screen pass among the transparents does
#          not become the composite for being first once.
#       c. Rasterizer::EffectsBeforeUpscaler: right before the upscaler's trigger, the last
#          chance (fog and particles get painted; counted in the log). There the normals come
#          from the depth.
#     (a) and (b) count only in the scene itself: the depth they come with must be the depth of
#     the last G-buffer pass of one of the last four frames (DrawnLook::SceneDepth; until one is
#     known any depth counts). A frame that draws the world a second time before the scene (a
#     reflection, with a depth of its own) is so not painted in the reflection and left without
#     strokes in the scene. This rests on the scene being the last G-buffer pass of a frame.
#     Not painted: a menu's 3D preview (CameraMotion::PreviewFrame), a frame without a camera.
#     Without the upscaler (BB_UPSCALER=none, or a GPU it cannot run on) none of the places
#     exists: DrawnLook::NoSceneHooks sets BbSettings' drawn_look_problem and the menu shows the
#     switch disabled with the reason.
#     Resources: nine compute pipelines and a sampler (linear between texels and levels), made
#     on the first frame the look is wanted on and kept; three RGBA16F images with all their
#     levels (the copy at the scene's size, the marks at half, the painted scene's means at a
#     quarter: 14 bytes a scene pixel together, 29 MB at 1920x1080, 52 MB at 2560x1440, 116 MB
#     at 3840x2160), made anew when the scene's size changes and released, with the cached views,
#     on the frame the look is switched off and when a pipeline or an image cannot be made.
#     Without the video memory for the images the frame is left unpainted, the menu shows "not
#     enough video memory at this render size", and the images are asked for again when the
#     scene's size changes or the look is switched off and on (not every frame); any other
#     failure switches the look off for the session.
#     Nothing depends on the output's size, on HDR or on frame generation: the passes work on
#     the scene colour before the upscaler.
#     Log (shad_log.txt, "Drawn look: ..."): "on at WxH, ..." when the size or the test view
#     changes and the first 8 times the inputs (normals, object motion) do; "the full-screen
#     pass after the transparents is ..." when the composite is learned or replaced; every 600
#     wanted frames where the frames were painted (at the transparents, at the composite, before
#     the upscaler, and not: preview, no camera, for want of video memory, not reached).
#  3. The passes, all compute, 8x8, push constants DrawnLookParams::Params (drawn_look_params.h,
#     112 bytes), in the order DrawnLook::Paint records them:
#       paint_prep.comp     0 scene colour  1 depth  2 the copy's level 0 (written: rgb the
#                           scene, a the view depth in metres, 0 sky)
#       paint_stats.comp    (half size) 0 the copy's level 0  1 the copy's level 1  2 the marks'
#                           level 0 (mean tone, its variance, which way its slopes run)
#       paint_mips.comp     (once a level) 0, 1 a level of the copy and of the marks (sampler2D)
#                           2, 3 the next level of each
#       paint_key.comp      (one group of 8x8, twice) plain: 0 the copy's level that is 64 texels
#                           or fewer on its longer side (texture2D)  1 the means' level 0 (its
#                           first 8x8 texels take the sums);  LAST: 0 the means' level 0
#                           1 the copy's last level, one texel (the key is written over it)
#       paint_strokes.comp  0 the copy, all levels (sampler2D)  1 depth  2 the G-buffer's world
#                           normals (FLAG_NORMALS)  3 this frame's object motion (FLAG_MOTION)
#                           4 the scene colour (image2D rgba16f; rgb rewritten, alpha kept)
#                           5 the marks, all levels (sampler2D)
#       paint_lock.comp     FIRST (quarter size): 0 the painted scene  1 the means' level 0;
#                           DOWN (once a level): 0 a level of the means  1 the next;
#                           plain: 0 the copy  1 depth  2 object motion  3 the scene colour
#                           (rewritten)  4 the means. Not run in a test view.
#     Where a flag is clear the copy is bound in that place and the shader does not read it.
#     BB_GPU_PROFILE=1 shows two rows: "Lighting: drawn look copy and masks" (prep, stats, mips)
#     and "Lighting: drawn look strokes and colour lock".
#  4. The look (paint_strokes.comp). Strokes belong to cells of the world (paint_common.glsl:
#     2^octave metres, one stroke a cell, three planes by the surface's normal with a blend band,
#     two octaves by the distance and by how squarely the plane is seen, with a cross-over), found
#     from the pixel's world position with the frame's jitter taken out; nothing depends on the
#     frame's number or on where the camera looks. Cell on the screen: 30 pixels for bold strokes
#     and 10 for fine ones at 2160 lines, times stroke_size, the same share of the picture at
#     every render size. Bold strokes on plain surfaces, fine ones where the marks show detail
#     (detailAt: read from the marks' level whose texels are two bold cells wide, with a dead
#     band, FINE_FROM, so that the frame's jitter does not move the line between the sizes).
#     The planes a pixel takes its strokes from follow the surface's normal with its bumps, but
#     only among the planes the surface itself (the normal from the depth) faces: a bumpy wall
#     keeps its strokes (planeShares). A stroke's colour is the scene's own: three reads along
#     the stroke from the copy's level whose texels are about as large as the stroke is wide,
#     each counted by how like the pixel it is (brightness in stops, hue, the depth the pixel's
#     surface has there). Then the brush's marks (mean 1): the stroke as a whole up to 4% (bold)
#     or 7% (fine) lighter or darker, and streaks along it, six across a stroke that is wide on
#     the screen, three across a narrower one, none across a thin one. A pixel far from its
#     stroke's brightness or hue keeps its own colour (thin lines sooner), and so does what glows
#     (4 stops over the frame's key and 1 over its place). What moves by itself (object motion)
#     is smoothed by strength x characters instead of stroked. The sky is not painted. The result
#     is mixed over the scene by the strength, and paint_lock.comp scales every place back to
#     the mean colour it had (over about a bold stroke's width, by at most 1.25): hue and
#     brightness stay. All thresholds are ratios (stops) or shares of the frame's key: the scene
#     is linear, before the game's exposure. The key (paint_key.comp, KEY_GAIN) is how bright the
#     frame's surfaces are: the mean tone of blocks of the picture without the sky, a block much
#     brighter than its neighbours (a lamp, a window, a pixel off the scale) counted as no more
#     than twice their tone. A plain mean of the frame rose with the sky and with a single
#     spark, and the black level and the glow rule with it.
#     NOT in the look: the design's light bands (brightness drawn toward steps). The first build
#     had them on absolute steps of a third of a stop, which made the picture depend on the
#     game's exposure (a scene 1.5 times as bright was banded elsewhere); they are taken out
#     until they can be laid against a base that moves with the scene.
#  5. The test view: every stroke in a flat colour of its own, at the brightness the scene has
#     at the stroke's middle; grey where the surface moves by itself (object motion); the scene
#     between strokes. 1: sizes as the look mixes them, 2: all fine, 4: all bold.
#  6. tests/test_drawn_look.cpp (ninja target drawn-look-test, plain Vulkan): the passes on a
#     synthetic scene (strokes stay on their surfaces under jitter and camera moves; mean colour
#     of every surface kept; grit flattened; the same picture at 8, 16 and 1.5 times the
#     brightness; a sky 500 times as bright and one pixel at 60000 change nothing on the ground;
#     the sizes of strokes stay under another jitter; a bumpy wall keeps its strokes; moving
#     things not stroked; broken pixels do not spread), and "--picture in.bmp out [2 | lines]":
#     the look on a 24-bit BMP (as it is, at half size, or at that many lines, e.g. 1440) with
#     colour statistics and GPU times. tests/test_settings.cpp and tests/test_effect_pipelines.cpp
#     cover the keys and the nine pipelines.
#
# FOR THE NEXT STAGES (ink lines, painted shadow edges).
#  - Profiler key 13 is kept free for the shadow edges' row (12 and 18 are the look's).
#  - `outlines` and `ink_world` are in the push constants and unused; graphics_drawn_look_debug 3
#    (ViewInk) shows the look until the ink's view is built. The copy (colour + view depth, all
#    levels) and the marks (b, a: which way the tone's slopes run) are there to be read.
#  - The sky is not painted (depth 1 returns early in the strokes and in the lock).
#  - The frame's key is one read for any pass: textureLod(the copy, vec2(0.5), 99.0).r, and
#    blackLevel(key) (paint_common.glsl) is the luminance that counts as black.
#  - What moves by itself is known per pixel and per frame only (object motion): a character
#    whose draw has no vectors on one frame (a change of its level of detail) is stroked on that
#    frame. The design's hold over frames (A6) belongs to stage 4 and is not built.
#  - The look has not been seen in the game yet: the constants at the top of paint_strokes.comp
#    (DETAIL_*, FINE_FROM, KEEP_*, BLEND_*, BRUSH_*, GLOW_STOPS), KEY_GAIN and TONE_MOST were set
#    on a screenshot laid on a floor and a wall.

import os
import re
import sys

ROOT = os.environ.get("R45_ROOT", os.getcwd()).replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
S = G + "shim/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"

TMP = ".r45tmp"  # a new text waits under this name beside its target (main)

# The new files, whole (written with CRLF line ends; revert removes one only as it is written here).
NEW_FILES = {
    B + "host_shaders/paint_common.glsl": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): shared by the drawn look's passes (paint_prep.comp, paint_stats.comp,
// paint_key.comp, paint_strokes.comp and paint_lock.comp, recorded by
// renderer_vulkan/vk_drawn_look.cpp). The look lays brush strokes ("dabs") on the scene's solid
// surfaces. A dab belongs to a place in the world, not to a place on the screen: every pixel finds its dabs from its own world position with the frame's jitter
// taken out, and nothing here depends on the frame's number. So a dab stays on its wall while
// the camera moves, and the upscaler and frame generation see it as they see a texture.
//
// The words of the block are made by DrawnLookParams::Make (renderer_vulkan/drawn_look_params.h).

layout(push_constant) uniform Constants {
    vec4 inv_view[3]; // view to world, rows (3x4): CameraMotion::PassMatrices
    vec4 proj;        // x scale, y scale, z scale, z offset (as camera_motion.comp)
    vec2 size;        // the scene in pixels
    vec2 jitter;      // this frame's viewport shift in pixels (x right, y down)
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

const float PI = 3.14159265358979;
const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722); // Rec.709
// Brightness below this share of the frame's key counts as black: differences down there do
// not show once the game has exposed the picture, and are not taken for detail.
const float BLACK_SHARE = 0.03;
// The frame's key (paint_key.comp): how bright the scene's surfaces are, as one number. It is
// the mean tone of the surfaces (toneOf, over blocks of the picture), cubed, times this. A plain
// mean of the picture would follow the sky and the lamps: a few of them outweigh a street of
// dark stone, and what counts as black would change with where the camera looks. The picture
// the look's numbers were set on (a night street with fog and a torch) had a plain mean this
// many times its mean tone cubed: with this factor the numbers mean there what they meant.
const float KEY_GAIN = 2.5;

// A dab in cells of its octave: one dab a cell, its centre in the cell's middle half, 1.2 cells
// from the middle to an end, a flat brush 0.35 to 0.45 as wide as long, its sides feathered over
// the outer FEATHER of the width, turned up to ANGLE_JITTER away from its plane's direction.
const float DAB_HALF_LENGTH = 1.2;
const float DAB_FEATHER = 0.25;
// The square of the farthest a dab reaches from its centre: half its length and half its
// greatest width (0.45 of the length), at right angles.
const float DAB_REACH2 = DAB_HALF_LENGTH * DAB_HALF_LENGTH * (1.0 + 0.45 * 0.45);
const float ANGLE_JITTER = 0.349; // 20 degrees
// On floors the strokes follow a slow field of directions: one turn of it is this many metres.
const float FLOW_METRES = 3.0;
// A second plane joins in where the surface leans this near to it (the ratio of the normal's
// second largest part to its largest); at 1 the two planes share the pixel half and half. A hard
// choice of one plane flickers where normal maps and the jitter move the normal across the line.
const float PLANE_BAND = 0.7;
// A plane seen at a flat angle (a floor far away) shows its strokes squashed: its cells grow by
// 1 / the square root of how squarely it is seen, so a stroke gets longer on the screen as it
// gets thinner, and no thinner than this would make it.
const float LEAN_MIN = 0.04;

float viewZ(float depth) {
    return proj.w / min(depth - proj.z, -1e-8);
}

// The luminance that counts as black in a frame with this key (the last level of the copy:
// paint_key.comp). The scene is linear and has not had the game's exposure yet: no fixed number
// would do.
float blackLevel(float key) {
    return BLACK_SHARE * key + 1e-9;
}

// A scene colour as the look's means take it: one that is no number, or below 0, would spread
// through every mean it is part of, so it is black.
vec3 soundColour(vec3 rgb) {
    return clamp(mix(rgb, vec3(0.0), isnan(rgb)), 0.0, 60000.0);
}

// A texel of the object motion image (rg pixels, b 1 where a draw with vectors of its own wrote
// it, a the depth it wrote at) says the pixel at `depth` moves by itself: a character, or
// whatever else has a bone buffer, and nothing was drawn over it since (the test
// camera_motion.comp makes).
bool ownMotion(vec4 motion, float depth) {
    return motion.b > 0.99 && abs(motion.a - depth) < max(2e-7, (proj.z - depth) * 0.01);
}

// The view position seen at a pixel (its centre: pixel + 0.5) at view depth z. The scene was
// drawn through a viewport shifted by the jitter: taken out here (camera_motion.comp).
vec3 viewPos(vec2 pixel, float z) {
    const vec2 ndc = (pixel - jitter) / size * 2.0 - 1.0;
    return vec3(ndc.x * z / proj.x, ndc.y * z / proj.y, z);
}

// Where a view position lies on the screen, in pixels of this frame (jitter put back).
vec2 viewToPixel(vec3 v) {
    const vec2 ndc = vec2(v.x * proj.x, v.y * proj.y) / max(v.z, 1e-4);
    return (ndc * 0.5 + 0.5) * size + jitter;
}

vec3 dirToWorld(vec3 v) {
    return vec3(dot(inv_view[0].xyz, v), dot(inv_view[1].xyz, v), dot(inv_view[2].xyz, v));
}

vec3 dirToView(vec3 w) {
    return inv_view[0].xyz * w.x + inv_view[1].xyz * w.y + inv_view[2].xyz * w.z;
}

vec3 cameraPos() {
    return vec3(inv_view[0].w, inv_view[1].w, inv_view[2].w);
}

// Metres one pixel covers in the middle of the screen at this distance, on a surface that faces
// the camera.
float metresPerPixel(float distance) {
    return 2.0 * distance / (abs(proj.y) * size.y);
}

uint pcg(uint v) {
    v = v * 747796405u + 2891336453u;
    const uint w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

uint cellHash(ivec2 cell, uint salt) {
    return pcg(uint(cell.x) + pcg(uint(cell.y) + pcg(salt)));
}

// 0..1 from a hash.
float unit(uint h) {
    return float(h >> 8u) * (1.0 / 16777216.0);
}

// What the look measures brightness in: the cube root of the luminance. Even steps of it are
// about even steps to the eye, and it needs no floor at black as a logarithm does.
float toneOf(vec3 rgb) {
    return pow(max(dot(rgb, LUMA), 0.0), 1.0 / 3.0);
}

// Value noise, 0..1, one cell a unit.
float vnoise(vec2 p) {
    const vec2 f = floor(p);
    const ivec2 c = ivec2(f);
    vec2 t = p - f;
    t = t * t * (3.0 - 2.0 * t);
    const float a = unit(cellHash(c, 977u));
    const float b = unit(cellHash(c + ivec2(1, 0), 977u));
    const float d = unit(cellHash(c + ivec2(0, 1), 977u));
    const float e = unit(cellHash(c + ivec2(1, 1), 977u));
    return mix(mix(a, b, t.x), mix(d, e, t.x), t.y);
}

// The two world axes a plane's strokes are laid out along; plane 0 faces world x, 1 world y
// (floors and ceilings: the world is y-up), 2 world z. On walls the second axis is world up.
vec2 planeAxes(vec3 p, int plane) {
    return plane == 0 ? p.zy : plane == 1 ? p.xz : p.xy;
}

// The planes a normal n asks for: `first` always, `second` with the share `second_share` (0
// away from the band, up to 0.5).
void strokePlanes(vec3 n, out int first, out int second, out float second_share) {
    const vec3 m = abs(n);
    first = m.x >= m.y ? (m.x >= m.z ? 0 : 2) : (m.y >= m.z ? 1 : 2);
    const vec3 rest = vec3(first == 0 ? -1.0 : m.x, first == 1 ? -1.0 : m.y,
                           first == 2 ? -1.0 : m.z);
    second = rest.x >= rest.y ? (rest.x >= rest.z ? 0 : 2) : (rest.y >= rest.z ? 1 : 2);
    second_share = 0.5 * smoothstep(PLANE_BAND, 1.0, rest[second] / max(m[first], 1e-4));
}

// The share of each plane in a pixel's strokes. `n` is the G-buffer's normal where there is one:
// smooth over a round column, where the depth's normal `flat_n` goes in steps from one flat side
// to the next, but with the bumps of a normal map in it. A bump that leans 40 degrees on a flat
// floor would hand a part of the floor to a wall's plane, whose strokes run across a floor as
// stripes: a plane gets no more than the surface itself (flat_n) leans toward it, and what a
// bump may not give goes to the surface's own plane. Where n and flat_n agree nothing changes:
// a plane that n gives a share is leant toward by PLANE_BAND or more.
vec3 planeShares(vec3 n, vec3 flat_n) {
    int first, second;
    float second_share;
    strokePlanes(n, first, second, second_share);
    vec3 shares = vec3(0.0);
    shares[first] = 1.0 - second_share;
    shares[second] = second_share;
    const vec3 m = abs(flat_n);
    const int own = m.x >= m.y ? (m.x >= m.z ? 0 : 2) : (m.y >= m.z ? 1 : 2);
    shares *= smoothstep(PLANE_BAND - 0.3, PLANE_BAND, m / max(m[own], 1e-4));
    shares[own] += max(1.0 - (shares.x + shares.y + shares.z), 0.0);
    return shares;
}

// The octaves a point takes its strokes from. A stroke keeps about the same size on the screen
// (cell_bold pixels a cell where `detail` is 0, cell_fine where it is 1), so its cell in the
// world grows with the distance: cells of 2^octave metres, the two octaves around the wanted
// size, `upper_share` of the larger one. Between a quarter and three quarters of the way the two
// cross over; outside that only one is there.
// `distance` is the point's distance from the camera, not its view depth: the depth of a point
// changes when the camera turns, and its strokes would cross over while nothing moved. (For it,
// a stroke near the screen's corners is larger by 1 / the cosine of the angle from the middle.)
// `lean`: how squarely the strokes' plane is seen from the camera, 0..1 (planeLean): it too
// depends on where the point lies and not on where the camera looks.
void strokeOctaves(float distance, float detail, float lean, out int octave,
                   out float upper_share) {
    const float cell_px = cell_bold * pow(cell_fine / cell_bold, detail);
    const float level =
        log2(cell_px * inversesqrt(max(lean, LEAN_MIN)) * metresPerPixel(distance));
    const float low = floor(level);
    octave = int(clamp(low, -14.0, 8.0));
    upper_share = smoothstep(0.25, 0.75, level - low);
}

// How squarely a plane's strokes are seen at a point `rel` from the camera: 1 face on, 0 edge on.
float planeLean(vec3 rel, int plane) {
    return abs(rel[plane]) / max(length(rel), 1e-6);
}

// A step along a plane's two axes (planeAxes) as a step in the world that stays on the surface
// with normal n: along the plane's own axis it follows the surface (a surface nearly edge on to
// the plane is followed as one that leans a little more to it).
vec3 planeStep(vec2 along, vec3 n, int plane) {
    vec3 move = plane == 0   ? vec3(0.0, along.y, along.x)
                : plane == 1 ? vec3(along.x, 0.0, along.y)
                             : vec3(along.x, along.y, 0.0);
    const float facing = max(abs(n[plane]), 0.2) * (n[plane] < 0.0 ? -1.0 : 1.0);
    move[plane] = -dot(n, move) / facing;
    return move;
}

struct Dab {
    float cover; // 0 outside, 1 inside, between on the feathered sides
    float s;     // along the dab, -1..1
    float t;     // across it, -1..1
    float idv;   // the dab's own random value, -0.5..0.5
    uint id;     // the dab's hash: the same for all its pixels, on every frame
    vec2 offset; // from the asked point to the dab's centre, along the plane's axes, metres
    vec2 reach;  // from the dab's centre to its end, along the plane's axes, metres
    float cell;  // the dab's cell in metres
};

// The dab on top at a world point, in one plane and one octave. `rel` is the point from the
// camera (world axes). The point's cell is found as whole cells of the camera plus the rest: a
// world coordinate of a kilometre has no bits left for a cell of a few millimetres.
// Each of the nine cells around the point has one dab; where several cover the point the one
// with the highest rank (a random number of its own) lies on top.
Dab findDab(vec3 rel, int plane, int octave) {
    const float cell_m = exp2(float(octave));
    const vec2 camera = planeAxes(cameraPos(), plane) / cell_m;
    const vec2 camera_cell = floor(camera);
    const vec2 q = (camera - camera_cell) + planeAxes(rel, plane) / cell_m;
    const vec2 q_cell = floor(q);
    const ivec2 base = ivec2(camera_cell) + ivec2(q_cell);
    const vec2 local = q - q_cell;
    const uint salt = uint(plane) + 3u * uint(octave + 64);
    Dab best;
    best.cover = 0.0;
    best.s = best.t = best.idv = 0.0;
    best.id = 0u;
    best.offset = best.reach = vec2(0.0);
    best.cell = cell_m;
    float best_rank = -1.0;
    for (int y = -1; y <= 1; ++y) {
        for (int x = -1; x <= 1; ++x) {
            const ivec2 cell = base + ivec2(x, y);
            const uint h0 = cellHash(cell, salt);
            const uint h1 = pcg(h0);
            const vec2 in_cell = 0.25 + 0.5 * vec2(unit(h0), unit(h1));
            const vec2 d = local - (vec2(x, y) + in_cell);
            // Farther from the dab's centre than its far corner: not in it, whichever way it is
            // turned (most of the nine cells end here, before their dab's angle is worked out).
            if (dot(d, d) >= DAB_REACH2) {
                continue;
            }
            const uint h2 = pcg(h1);
            const uint h3 = pcg(h2);
            // Walls: along world up. Floors: along the flow field where the dab's centre is.
            float angle = 0.5 * PI;
            if (plane == 1) {
                angle = PI * vnoise((vec2(cell) + in_cell) * (cell_m / FLOW_METRES));
            }
            angle += (unit(h2) * 2.0 - 1.0) * ANGLE_JITTER;
            const vec2 axis = vec2(cos(angle), sin(angle));
            const float s = dot(d, axis) / DAB_HALF_LENGTH;
            if (abs(s) >= 1.0) {
                continue;
            }
            const float half_width = DAB_HALF_LENGTH * mix(0.35, 0.45, unit(h3));
            const float t = dot(d, vec2(-axis.y, axis.x)) / half_width;
            // A flat brush: straight sides, ends rounded off over the last part of the length.
            const float s2 = s * s;
            const float e = t * t / (1.0 - s2 * s2);
            const float cover = 1.0 - smoothstep(1.0 - DAB_FEATHER, 1.0, e);
            const float rank = unit(h3 ^ 0x9e3779b9u);
            if (cover > 0.0 && rank > best_rank) {
                best_rank = rank;
                best.cover = cover;
                best.s = s;
                best.t = t;
                best.idv = unit(h1 ^ 0x85ebca6bu) - 0.5;
                best.id = h0;
                best.offset = -d * cell_m;
                best.reach = axis * (DAB_HALF_LENGTH * cell_m);
            }
        }
    }
    return best;
}
""",
    B + "host_shaders/paint_key.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the frame's key for the drawn look: how bright the scene's surfaces
// are, as one number. The look's thresholds are shares of it (what counts as black, what glows):
// the scene is linear and has not had the game's exposure yet. A plain mean of the picture (the
// copy's last level as paint_mips.comp leaves it) would not do: the sky and the lamps are many
// times as bright as stone at night, so what counted as black would rise when the camera looks
// up, and one pixel that is off the scale would move it too. The key is the mean tone (toneOf:
// the cube root of the luminance) of blocks of the picture, without the blocks that are all sky,
// cubed (and times KEY_GAIN, paint_common.glsl). A block much brighter than the blocks around
// it (a lamp, a window, a block that is partly sky) counts as no more than TONE_MOST times their
// mean tone.
// Two passes of this file, each one group of 8x8:
//   (neither) every invocation adds up its part of a small level of the copy (64 texels or
//             fewer on its longer side) and stores its sum: 8x8 sums or fewer
//   LAST      one invocation adds up the sums and writes the key over the copy's last level
// The sums are kept in the first texels of the means' level 0 (paint_lock.comp's image, which
// is written only after the strokes).
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

#if !defined(LAST)

layout(binding = 0) uniform texture2D prep_tex; // a small level of the copy: rgb, a view depth
layout(binding = 1, rgba16f) uniform writeonly image2D sums_img;

// Twice the tone: eight times the luminance.
const float TONE_MOST = 2.0;

// The tones of this invocation's blocks, each no more than `most`, and how many: r, g.
vec2 tones(ivec2 start, ivec2 end, float most) {
    vec2 sum = vec2(0.0);
    for (int y = start.y; y < end.y; ++y) {
        for (int x = start.x; x < end.x; ++x) {
            const vec4 block = texelFetch(prep_tex, ivec2(x, y), 0);
            // A depth of 0: nothing but sky under this texel.
            if (block.a > 0.0) {
                sum += vec2(min(toneOf(block.rgb), most), 1.0);
            }
        }
    }
    return sum;
}

void main() {
    const ivec2 parts = min(imageSize(sums_img), ivec2(8));
    const ivec2 part = ivec2(gl_GlobalInvocationID.xy);
    if (any(greaterThanEqual(part, parts))) {
        return;
    }
    const ivec2 from = textureSize(prep_tex, 0);
    const ivec2 start = part * from / parts, end = (part + 1) * from / parts;
    vec2 sum = tones(start, end, 1e30);
    if (sum.y > 0.0) {
        sum = tones(start, end, TONE_MOST * sum.x / sum.y);
    }
    imageStore(sums_img, part, vec4(sum, 0.0, 0.0));
}

#else

layout(binding = 0) uniform texture2D sums_tex;
layout(binding = 1, rgba16f) uniform writeonly image2D key_img; // the copy's last level

void main() {
    if (gl_GlobalInvocationID.xy != uvec2(0)) {
        return;
    }
    const ivec2 parts = min(textureSize(sums_tex, 0), ivec2(8));
    vec2 sum = vec2(0.0);
    for (int y = 0; y < parts.y; ++y) {
        for (int x = 0; x < parts.x; ++x) {
            sum += texelFetch(sums_tex, ivec2(x, y), 0).rg;
        }
    }
    // A frame of sky alone has no surface to paint: any key will do.
    const float tone = sum.y > 0.0 ? sum.x / sum.y : 0.0;
    imageStore(key_img, ivec2(0), vec4(vec3(KEY_GAIN * tone * tone * tone), 0.0));
}

#endif
""",
    B + "host_shaders/paint_lock.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's colour lock, after the stroke pass. A stroke takes
// the mean colour of what lies under it, but the pixels that keep their own colour (the dark
// joints between stones, a glint) are in that mean too and are then counted twice: a wall with
// dark joints would come out a little darker than it was, one with glints lighter. So every
// place of the picture is scaled back to the mean colour it had before the strokes, measured
// over about a bold stroke's width: narrow enough that a block of 64 pixels keeps its brightness
// (twice as wide left blocks up to 8% off on the tuning picture, this 4%), and each stroke still
// reads as the one colour it is.
// Three passes of this file:
//   FIRST  the painted scene's means, a quarter of the scene's size: what the copy's level 2
//          is of the scene before the strokes, texel for texel
//   DOWN   one more level of those means, as paint_mips.comp makes the copy's; down to one texel
//   (neither) the scene scaled by the copy's mean over the painted scene's mean
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

#if defined(FIRST)

layout(binding = 0) uniform texture2D scene_tex; // the scene colour with the strokes in
layout(binding = 1, rgba16f) uniform writeonly image2D to_img;

// The mean of 2x2 pixels: a texel of the copy's level 1 (paint_stats.comp).
vec3 halfTexel(ivec2 at) {
    vec3 sum = vec3(0.0);
    for (int i = 0; i < 4; ++i) {
        sum += soundColour(texelFetch(scene_tex, at * 2 + ivec2(i & 1, i >> 1), 0).rgb);
    }
    return sum * 0.25;
}

void main() {
    const ivec2 texel = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 to_size = imageSize(to_img);
    if (any(greaterThanEqual(texel, to_size))) {
        return;
    }
    // Where paint_mips.comp reads level 1 for this texel of level 2, and the four texels a
    // linear read mixes there (on an even size: the 4x4 pixels, each counted the same).
    const ivec2 half_size = max(ivec2(size) / 2, ivec2(1));
    const vec2 p = (vec2(texel) + 0.5) / vec2(to_size) * vec2(half_size) - 0.5;
    const ivec2 base = ivec2(floor(p));
    const vec2 f = p - vec2(base);
    vec3 sum = vec3(0.0);
    for (int i = 0; i < 4; ++i) {
        const ivec2 corner = ivec2(i & 1, i >> 1);
        const vec2 w = mix(1.0 - f, f, vec2(corner));
        sum += halfTexel(clamp(base + corner, ivec2(0), half_size - 1)) * (w.x * w.y);
    }
    imageStore(to_img, texel, vec4(sum, 1.0));
}

#elif defined(DOWN)

layout(binding = 0) uniform sampler2D from_tex; // a level of the means (linear, clamped)
layout(binding = 1, rgba16f) uniform writeonly image2D to_img;

void main() {
    const ivec2 texel = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 to_size = imageSize(to_img);
    if (any(greaterThanEqual(texel, to_size))) {
        return;
    }
    imageStore(to_img, texel, textureLod(from_tex, (vec2(texel) + 0.5) / vec2(to_size), 0.0));
}

#else

// The copy of the scene before the strokes, all its levels (paint_prep.comp).
layout(binding = 0) uniform sampler2D prep_tex;
layout(binding = 1) uniform texture2D depth_tex;  // depth 0..1, 1: sky
layout(binding = 2) uniform texture2D motion_tex; // FLAG_MOTION: this frame's object motion
layout(binding = 3, rgba16f) uniform image2D scene_img;
// The painted scene's means, all levels; level 0 is a quarter of the scene's size.
layout(binding = 4) uniform sampler2D lock_tex;

// A place is never scaled by more than this: the lock is there for a few per cent.
const float MOST = 1.25;
// The means are read from the level whose texels are a bold cell wide, plus this many levels.
// One level more (texels two cells wide) leaves the strokes a little flatter and the picture's
// blocks further from the brightness they had.
const float LOCK_LEVEL = 0.0;

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (pixel.x >= int(size.x) || pixel.y >= int(size.y)) {
        return;
    }
    // What the stroke pass did not touch stays untouched: the sky, and what moves by itself
    // when it gets no share of the look.
    const float depth = texelFetch(depth_tex, pixel, 0).r;
    if (depth >= 1.0) {
        return;
    }
    if (characters <= 0.0 && (flags & FLAG_MOTION) != 0u &&
        ownMotion(texelFetch(motion_tex, pixel, 0), depth)) {
        return;
    }
    const vec2 uv = (vec2(pixel) + 0.5) / size;
    // Texels a bold cell wide; the means' level 0 is the copy's level 2.
    const float level = max(log2(cell_bold) + LOCK_LEVEL, 2.0);
    // The copy's last level is one texel: the frame's key (paint_key.comp).
    const float black = blackLevel(textureLod(prep_tex, vec2(0.5), 99.0).r);
    const vec3 before = textureLod(prep_tex, uv, level).rgb;
    const vec3 after = textureLod(lock_tex, uv, level - 2.0).rgb;
    const vec3 scale = clamp((before + black) / (after + black), 1.0 / MOST, MOST);
    const vec4 scene = imageLoad(scene_img, pixel);
    imageStore(scene_img, pixel, vec4(scene.rgb * scale, scene.a));
}

#endif
""",
    B + "host_shaders/paint_mips.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): one more level of the drawn look's two images, each texel the mean
// of the 2x2 texels of the level above: the copy (rgb the scene, a the view depth) and the marks
// (paint_stats.comp). Run once a level down to one texel (the copy's one texel is then written
// again by paint_key.comp: the frame's key). The stroke pass takes a stroke's one
// colour from the level whose texels are about as large as the stroke is wide, which costs a
// few reads however large the stroke is, and reads the marks over a stroke's whole place.
// A level is read at the place of the new texel's middle, so that an odd size keeps every level
// over the same place of the picture.
#version 450

layout(local_size_x = 8, local_size_y = 8) in;

layout(binding = 0) uniform sampler2D prep_from;  // the copy's level n (linear, clamped)
layout(binding = 1) uniform sampler2D marks_from; // the marks' level n - 1
layout(binding = 2, rgba16f) uniform writeonly image2D prep_to;  // the copy's level n + 1
layout(binding = 3, rgba16f) uniform writeonly image2D marks_to; // the marks' level n

void main() {
    const ivec2 texel = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 to_size = imageSize(prep_to);
    if (any(greaterThanEqual(texel, to_size))) {
        return;
    }
    const vec2 uv = (vec2(texel) + 0.5) / vec2(to_size);
    imageStore(prep_to, texel, textureLod(prep_from, uv, 0.0));
    // The tone's variance under the new texel: the mean of the four variances and what their
    // four mean tones vary by.
    vec4 marks = textureLod(marks_from, uv, 0.0);
    const vec4 tones = textureGather(marks_from, uv, 0);
    const float mean = dot(tones, vec4(0.25));
    marks.g += max(dot(tones, tones) * 0.25 - mean * mean, 0.0);
    imageStore(marks_to, texel, marks);
}
""",
    B + "host_shaders/paint_prep.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's first pass. The stroke pass writes the scene colour
// in place while it reads other pixels of it, so it reads this copy instead: rgb the scene as it
// is before the strokes, a the view depth in metres (0: sky), which the stroke pass takes to
// tell whether another pixel lies on the same surface. The copy's smaller levels (paint_stats.comp,
// paint_mips.comp) are averages of this one: a colour that is no number, or below 0, would
// spread through them, so it is black here.
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

layout(binding = 0) uniform texture2D scene_tex; // RGBA16F, linear, before the game's exposure
layout(binding = 1) uniform texture2D depth_tex; // depth 0..1 (D3D projection), 1: sky
layout(binding = 2, rgba16f) uniform writeonly image2D prep_img;

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (pixel.x >= int(size.x) || pixel.y >= int(size.y)) {
        return;
    }
    const float depth = texelFetch(depth_tex, pixel, 0).r;
    const vec3 rgb = soundColour(texelFetch(scene_tex, pixel, 0).rgb);
    imageStore(prep_img, pixel, vec4(rgb, depth >= 1.0 ? 0.0 : viewZ(depth)));
}
""",
    B + "host_shaders/paint_stats.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's second pass, at half the scene's size. From the
// copy (paint_prep.comp) it makes the copy's level 1 (the mean of each 2x2 pixels) and the first
// level of the "marks", from which the stroke pass tells plain surfaces from detail:
//   r  the mean tone of the 2x2 pixels (toneOf: the cube root of the luminance)
//   g  how much the tone varies inside the 2x2 pixels (its variance); paint_mips.comp adds
//      what the means of a level's texels vary by, so every level holds the variance of all the
//      pixels under a texel (kept as a variance, not as a mean of squares: the difference of
//      two large numbers has no bits left in a half float)
//   b, a  which way the tone's slopes run, as a vector that adds up over a block where they all
//      run one way (an edge, a railing, a joint between stones) and cancels where they run every
//      way (grit): (gx^2 - gy^2, 2 gx gy) of the slope (gx, gy)
// One pass for both: they read the same 4x4 pixels.
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

layout(binding = 0) uniform texture2D prep_tex; // the copy's level 0
layout(binding = 1, rgba16f) uniform writeonly image2D half_img;  // the copy's level 1
layout(binding = 2, rgba16f) uniform writeonly image2D marks_img; // the marks' level 0

void main() {
    const ivec2 texel = ivec2(gl_GlobalInvocationID.xy);
    if (any(greaterThanEqual(texel, imageSize(half_img)))) {
        return;
    }
    const ivec2 last = ivec2(size) - 1;
    float tone[16];
    vec4 mean = vec4(0.0);
    for (int i = 0; i < 16; ++i) {
        const ivec2 at = ivec2(i & 3, i >> 2);
        const vec4 c = texelFetch(prep_tex, clamp(texel * 2 - 1 + at, ivec2(0), last), 0);
        tone[i] = toneOf(c.rgb);
        if (at.x == 1 || at.x == 2) {
            if (at.y == 1 || at.y == 2) {
                mean += c;
            }
        }
    }
    imageStore(half_img, texel, mean * 0.25);
    vec4 marks = vec4(0.0);
    for (int i = 0; i < 4; ++i) {
        const int k = 5 + (i & 1) + 4 * (i >> 1);
        const vec2 slope = 0.5 * vec2(tone[k + 1] - tone[k - 1], tone[k + 4] - tone[k - 4]);
        marks += vec4(tone[k], tone[k] * tone[k], slope.x * slope.x - slope.y * slope.y,
                      2.0 * slope.x * slope.y);
    }
    marks *= 0.25;
    marks.g = max(marks.g - marks.r * marks.r, 0.0);
    imageStore(marks_img, texel, marks);
}
""",
    B + "host_shaders/paint_strokes.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's stroke pass. It rewrites the scene colour's rgb in
// place, after the solid surfaces are drawn and before fire, glows, fog and particles are (those
// stay as the game draws them); the alpha is the game's data and is kept. The sky is not painted.
//
// Every pixel finds the brush strokes that lie on its place in the world (paint_common.glsl) and
// takes the colour of the one on top. A stroke has one colour: the scene's own, averaged over the
// stroke from the copy's small levels, so the fine grit of a surface goes and its hue and
// brightness stay. Large plain surfaces get bold strokes, places with detail fine ones
// (detailAt). What a stroke may not swallow keeps its own colour: a pixel much lighter or darker
// than its stroke or of another hue (an eye, a glint, a letter, a thin railing), and what glows.
// Nothing is tinted and no contrast is added: every step is a mean of the scene's colours or a
// change of brightness that is as often up as down.
//
// All thresholds are ratios of brightness (stops) or shares of the frame's key (paint_key.comp):
// the scene is linear and has not had the game's exposure yet, so no fixed brightness means
// anything, and a scene twice as bright gets the same look.
#version 450
#extension GL_EXT_samplerless_texture_functions : require
#extension GL_GOOGLE_include_directive : require

layout(local_size_x = 8, local_size_y = 8) in;

#include "paint_common.glsl"

// paint_prep.comp's copy and its smaller levels: rgb the scene before the strokes, a the view
// depth in metres (0: sky). Its last level, one texel, holds the frame's key (paint_key.comp).
// Linear between texels and levels, clamped.
layout(binding = 0) uniform sampler2D prep_tex;
layout(binding = 1) uniform texture2D depth_tex;  // depth 0..1 (D3D projection), 1: sky
// FLAG_NORMALS: the G-buffer's world normal, xyz * 2 - 1 (a length under 0.5: none here).
layout(binding = 2) uniform texture2D normal_tex;
// FLAG_MOTION: this frame's object motion: rg pixels (previous - current), b 1 where a draw
// with vectors of its own wrote the pixel, a the depth it wrote at.
layout(binding = 3) uniform texture2D motion_tex;
layout(binding = 4, rgba16f) uniform image2D scene_img;
// paint_stats.comp's marks and their smaller levels; level 0 is half the scene's size.
layout(binding = 5) uniform sampler2D marks_tex;

// A stroke blends the scene's colours that are like the pixel's own: within about this many
// stops at strength 0 and 1 (a wider net flattens more), and within this much of its hue (as
// shares of red, green and blue).
const vec2 BLEND_STOPS = vec2(0.3, 1.5);
const float BLEND_HUE = 0.06;
// A pixel this many stops from its stroke's brightness starts to keep its own colour, and
// keeps all of it from the second number on; on a thin line (LINE_*) the second pair holds.
const vec2 KEEP_STOPS = vec2(0.6, 1.2);
const vec2 KEEP_STOPS_LINE = vec2(0.3, 0.7);
const vec2 KEEP_HUE = vec2(0.05, 0.12);
// Detail, which takes fine strokes: the tone under a bold stroke varies by this share of itself
// (0.08 is about a third of a stop; grit stays below), or its slopes run one way this strongly
// (edges, railings, joints).
const vec2 DETAIL_ROUGH = vec2(0.09, 0.2);
const vec2 DETAIL_LINES = vec2(0.02, 0.05);
const vec2 LINE_SLOPE = vec2(0.03, 0.08);
// Strokes are bold up to the first of these numbers of detail and fine from the second on: most
// of the picture is one or the other, and there a little more or less detail from one frame to
// the next (the marks are measured on each frame's own pixels) changes nothing.
const vec2 FINE_FROM = vec2(0.25, 0.75);
// The brush's marks at graphics_drawn_look_texture 1: a stroke as a whole is up to this much
// lighter or darker (a bold one, a fine one: bold strokes of plain walls that differ by more
// read as scales), and streaks along it up to that much.
const vec2 BRUSH_VALUE = vec2(0.04, 0.07);
const float BRUSH_STREAKS = 0.05;
// A colour of the copy belongs to the pixel's surface while its depth is within this share of
// the depth that surface has there (all of it, none of it).
const vec2 SAME_DEPTH = vec2(0.01, 0.03);
// What glows is left unpainted: brighter than the frame's key by the first number of stops and
// than the place around it by the second (a lit wall is bright against the frame, not against
// its place); over one stop more it is left alone altogether.
const vec2 GLOW_STOPS = vec2(4.0, 1.0);

float lum_floor;  // the frame's black (blackLevel)
float tone_floor; // the same as a tone (toneOf)
// In the test view (graphics_drawn_look_debug 1, 2 or 4) every dab has a flat colour of its
// own, grey where the surface moves by itself.
bool test_view = false;
bool test_grey = false;
// What shows between the look's dabs (calmColour), worked out for the first dab that needs it.
vec3 under = vec3(0.0);
bool have_under = false;

float depthAt(ivec2 p) {
    return texelFetch(depth_tex, clamp(p, ivec2(0), ivec2(size) - 1), 0).r;
}

// The surface's world normal from the depth around the pixel, for a frame without the G-buffer's
// normals and for pixels the G-buffer has none for. Of the two neighbours on each axis the one
// nearer in depth is taken, so the normal does not lean across an edge.
vec3 depthNormal(ivec2 pixel, vec3 c) {
    vec3 px[2], py[2];
    for (int i = 0; i < 2; ++i) {
        const int s = i == 0 ? -1 : 1;
        const float dx = depthAt(pixel + ivec2(s, 0));
        const float dy = depthAt(pixel + ivec2(0, s));
        px[i] = viewPos(vec2(pixel + ivec2(s, 0)) + 0.5, dx >= 1.0 ? 1e6 : viewZ(dx));
        py[i] = viewPos(vec2(pixel + ivec2(0, s)) + 0.5, dy >= 1.0 ? 1e6 : viewZ(dy));
    }
    const vec3 ex = abs(px[1].z - c.z) < abs(c.z - px[0].z) ? px[1] - c : c - px[0];
    const vec3 ey = abs(py[1].z - c.z) < abs(c.z - py[0].z) ? py[1] - c : c - py[0];
    const vec3 n = cross(ey, ex);
    return dirToWorld(dot(n, n) > 1e-12 ? normalize(n) : -normalize(c));
}

// Only which way the surface faces matters here, not the normal's sign.
vec3 worldNormal(ivec2 pixel, vec3 c) {
    if ((flags & FLAG_NORMALS) != 0u) {
        const ivec2 last = textureSize(normal_tex, 0) - 1;
        const vec3 n = texelFetch(normal_tex, clamp(pixel, ivec2(0), last), 0).xyz * 2.0 - 1.0;
        if (dot(n, n) > 0.25) {
            return normalize(n);
        }
    }
    return depthNormal(pixel, c);
}

bool movesItself(ivec2 pixel, float depth) {
    return (flags & FLAG_MOTION) != 0u && ownMotion(texelFetch(motion_tex, pixel, 0), depth);
}

// How much fine detail lies around a place of the screen: 0 a plain surface, which takes bold
// strokes, 1 detail (carvings, faces, branches, windows), which takes fine ones. Read from the
// marks' level whose texels are two bold cells wide, about what a bold stroke covers and would
// swallow. The marks are measured on this frame's pixels, so they are the one thing in a
// stroke's place and size that is not fixed to the world: over a place of this width they
// change little with the jitter and with a turn of the camera (texels one cell wide changed the
// size of a third more of the picture from one jitter to the next), and FINE_FROM keeps what
// change there is to the line between plain and detailed.
float detailAt(vec2 uv) {
    const vec4 marks = textureLod(marks_tex, uv, log2(cell_bold));
    const float base = marks.r + tone_floor;
    const float detail =
        max(smoothstep(DETAIL_ROUGH.x, DETAIL_ROUGH.y, sqrt(marks.g) / base),
            smoothstep(DETAIL_LINES.x, DETAIL_LINES.y, sqrt(length(marks.ba)) / base));
    return smoothstep(FINE_FROM.x, FINE_FROM.y, detail);
}

// The pixel's own colour, as the strokes compare the scene around it with, and its surface.
struct Own {
    vec3 rgb;
    float lum;
    vec3 hue;    // its shares of red, green and blue (grey near black)
    float z;     // view depth, metres
    vec3 facing; // the surface's normal from the depth around the pixel, view axes
    float level; // that normal times the pixel's view position: the surface's plane
};

// The view depth the pixel's surface has at another place of the screen, were it flat.
float surfaceDepth(vec2 uv, Own own) {
    const float along = dot(own.facing, viewPos(uv * size, 1.0));
    return abs(along) > 1e-4 ? clamp(own.level / along, 0.5 * own.z, 2.0 * own.z) : own.z;
}

vec3 hueOf(vec3 rgb) {
    return (rgb + lum_floor) / (rgb.r + rgb.g + rgb.b + 3.0 * lum_floor);
}

float stopsBetween(float a, float b) {
    return log2((a + lum_floor) / (b + lum_floor));
}

// How much a colour read from the copy at view depth `z` counts for the pixel: all of it where
// it has the pixel's brightness and hue and lies at the depth the pixel's surface has there. A
// texel of a small level that is partly another surface's (a silhouette runs through it) has a
// depth between the two and the other's colour mixed in: SAME_DEPTH leaves it out.
float alike(vec4 there, float z, Own own) {
    const float stops = stopsBetween(dot(there.rgb, LUMA), own.lum);
    const float reach = mix(BLEND_STOPS.x, BLEND_STOPS.y, strength);
    const vec3 hue = hueOf(there.rgb) - own.hue;
    return exp(-0.5 * stops * stops / (reach * reach) -
               0.5 * dot(hue, hue) / (BLEND_HUE * BLEND_HUE)) *
           (1.0 - smoothstep(SAME_DEPTH.x, SAME_DEPTH.y, abs(there.a - z) / z));
}

// The scene around the pixel, smoothed over `radius` pixels without crossing an edge: what
// shows between strokes, and what a surface that moves by itself gets instead of strokes.
vec3 calmColour(vec2 uv, float radius, Own own) {
    const float level = log2(max(radius, 1.0));
    vec4 sum = vec4(own.rgb, 1.0) * 0.25;
    for (int i = 0; i < 4; ++i) {
        const vec2 at = uv + vec2((i & 1) * 2 - 1, (i >> 1) * 2 - 1) * (0.7 * radius) / size;
        const vec4 there = textureLod(prep_tex, at, level);
        const float w = alike(there, surfaceDepth(at, own), own);
        sum += vec4(there.rgb, 1.0) * w;
    }
    return sum.rgb / sum.a;
}

// `count` streaks side by side across a dab, each a little lighter or darker: -0.5..0.5.
float streaksAcross(Dab dab, float count, uint salt) {
    const float x = (dab.t * 0.5 + 0.5) * count;
    const float cell = floor(x);
    float f = x - cell;
    f = f * f * (3.0 - 2.0 * f);
    const uint at = dab.id + salt + uint(int(cell) + 8);
    return mix(unit(pcg(at)), unit(pcg(at + 1u)), f) - 0.5;
}

// The brush's marks in a dab: the dab as a whole a little lighter or darker than its colour, and
// streaks along it. Around 1: over many dabs the brightness stays what it was. `width`: the
// dab's width on the screen in pixels. Six streaks across a dab where each is a few pixels wide
// (a bold dab on a scene of 2160 lines); a narrower dab (a bold one at 1080 lines, a fine one at
// 2160) has three; where even those would be finer than two or three pixels they would flicker,
// and there are none. One count fades into the other as a dab's width changes with the distance.
// `detail`: 0 a bold dab, 1 a fine one.
float brushMarks(Dab dab, float width, float detail) {
    const float six = smoothstep(2.0, 4.0, width / 6.0);
    const float three = (1.0 - six) * smoothstep(2.0, 4.0, width / 3.0);
    float streak = 0.0;
    if (six > 0.0) {
        streak += six * streaksAcross(dab, 6.0, 0u);
    }
    if (three > 0.0) {
        streak += three * streaksAcross(dab, 3.0, 97u);
    }
    return 1.0 + brush * (2.0 * mix(BRUSH_VALUE.x, BRUSH_VALUE.y, detail) * dab.idv +
                          2.0 * BRUSH_STREAKS * streak);
}

// A dab's colour for the pixel: rgb, and in a how much of the dab is there (0: none of it, show
// what lies under it). The colour is read at three places along the dab, from the copy's level
// whose texels are about as large as the dab is wide, so the whole dab is nearly one colour;
// where the dab crosses an edge each pixel takes the side it is like.
// `px_per_m`: pixels a metre covers at the pixel; `lean`: how squarely the dab's plane is seen.
vec4 dabPaint(Dab dab, vec3 rel, vec3 n, int plane, float px_per_m, float lean, float detail,
              Own own) {
    const float squash = max(lean, LEAN_MIN);
    const float cell = dab.cell * px_per_m;
    const float level = log2(max(0.7 * cell * sqrt(squash), 1.0));
    vec4 sum = vec4(0.0);
    for (int i = -1; i <= 1; ++i) {
        const vec3 v = dirToView(rel + planeStep(dab.offset + dab.reach * (0.6 * float(i)), n, plane));
        if (v.z <= 0.01) {
            continue;
        }
        const vec2 uv = viewToPixel(v) / size;
        if (any(lessThan(uv, vec2(-0.01))) || any(greaterThan(uv, vec2(1.01)))) {
            continue;
        }
        const vec4 there = textureLod(prep_tex, uv, level);
        sum += vec4(there.rgb, 1.0) * alike(there, v.z, own);
    }
    if (sum.a < 1e-3) {
        return vec4(0.0);
    }
    // A dab thinner than a pixel or two on the screen (a fine one on a floor far away) is no
    // shape any more: it fades, and the smoothed scene shows.
    const float width = cell * squash;
    return vec4(sum.rgb / sum.a * brushMarks(dab, width, detail),
                dab.cover * smoothstep(0.02, 0.2, sum.a) * smoothstep(1.2, 2.5, width));
}

// The test view's colour for a dab: some hue of its own, luminance 1.
vec3 idColour(uint id) {
    const float hue = unit(id) * 6.0;
    const vec3 pure = clamp(abs(mod(hue + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    const vec3 c = mix(vec3(1.0), pure, 0.65);
    return c / dot(c, LUMA);
}

// The scene's luminance where a dab's centre lies, so that the whole dab gets one brightness and
// the test view is neither black nor blown out whatever the game's exposure is. `own` (the
// pixel's luminance) where the centre is off the screen, behind something else, or on another
// surface.
float dabLuminance(vec3 rel, vec3 n, int plane, vec2 offset, float own) {
    const vec3 v = dirToView(rel + planeStep(offset, n, plane));
    if (v.z <= 0.0) {
        return own;
    }
    const ivec2 p = ivec2(floor(viewToPixel(v)));
    if (any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, ivec2(size)))) {
        return own;
    }
    const vec4 there = texelFetch(prep_tex, p, 0);
    return abs(there.a - v.z) < 0.03 * v.z + 0.03 ? dot(there.rgb, LUMA) : own;
}

// What one dab gives the pixel. The look: its paint, and between dabs the smoothed scene. The
// test view: its flat colour, and between dabs the scene.
vec3 dabColour(Dab dab, vec2 uv, vec3 rel, vec3 flat_n, int plane, float px_per_m, float lean,
               float detail, Own own) {
    if (test_view) {
        if (dab.cover <= 0.0) {
            return own.rgb;
        }
        vec3 flat_colour = idColour(dab.id) * (1.0 + 0.5 * dab.idv);
        if (test_grey) {
            flat_colour = vec3(dot(flat_colour, LUMA));
        }
        return flat_colour * dabLuminance(rel, flat_n, plane, dab.offset, own.lum);
    }
    vec4 paint = vec4(0.0);
    if (dab.cover > 0.0) {
        paint = dabPaint(dab, rel, flat_n, plane, px_per_m, lean, detail, own);
    }
    if (paint.a < 1.0) {
        if (!have_under) {
            under = calmColour(uv, 0.5 * cell_fine, own);
            have_under = true;
        }
        paint.rgb = mix(under, paint.rgb, paint.a);
    }
    return paint.rgb;
}

// The colour the strokes give the pixel: the dabs of the planes its surface takes them from
// (planeShares) and of the two sizes around the one its `detail` asks for, mixed as their shares
// say. `n` (with the surface's bumps) and `flat_n` (the surface itself) pick the planes; flat_n
// says where a dab's other places lie.
vec3 strokeColour(vec2 uv, vec3 rel, vec3 n, vec3 flat_n, float detail, Own own) {
    const vec3 shares = planeShares(n, flat_n);
    const float distance = length(rel);
    const float px_per_m = 1.0 / metresPerPixel(distance);
    vec3 sum = vec3(0.0);
    for (int plane = 0; plane < 3; ++plane) {
        if (shares[plane] <= 0.0) {
            continue;
        }
        const float lean = planeLean(rel, plane);
        int octave;
        float upper_share;
        strokeOctaves(distance, detail, lean, octave, upper_share);
        for (int o = 0; o < 2; ++o) {
            const float share = shares[plane] * (o == 0 ? 1.0 - upper_share : upper_share);
            if (share <= 0.0) {
                continue;
            }
            const Dab dab = findDab(rel, plane, octave + o);
            sum += share * dabColour(dab, uv, rel, flat_n, plane, px_per_m, lean, detail, own);
        }
    }
    return sum;
}

// How much of its own colour the pixel keeps under the paint: all of it where it glows, and
// where it is far from the paint's brightness or hue (the stroke would swallow a detail). On a
// thin line of the picture a smaller difference is enough.
float keepOwn(vec2 uv, vec3 paint, Own own, float key) {
    const vec4 marks = textureLod(marks_tex, uv, 1.0);
    const float line = smoothstep(LINE_SLOPE.x, LINE_SLOPE.y,
                                  sqrt(length(marks.ba)) / (marks.r + tone_floor));
    const vec2 stops = mix(KEEP_STOPS, KEEP_STOPS_LINE, line);
    float keep = smoothstep(stops.x, stops.y, abs(stopsBetween(own.lum, dot(paint, LUMA))));
    keep = max(keep, smoothstep(KEEP_HUE.x, KEEP_HUE.y, length(own.hue - hueOf(paint))));
    // The scene around the pixel over a few pixels and over a large place (about 1/270 and
    // 1/17 of the picture's height).
    const float lines = log2(size.y);
    const float near = dot(textureLod(prep_tex, uv, lines - 8.1).rgb, LUMA);
    const float place = dot(textureLod(prep_tex, uv, lines - 4.1).rgb, LUMA);
    const float top = max(own.lum, near);
    const float glow = min(stopsBetween(top, key) - GLOW_STOPS.x,
                           stopsBetween(top, place) - GLOW_STOPS.y);
    return max(keep, smoothstep(0.0, 1.0, glow));
}

void main() {
    const ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    if (pixel.x >= int(size.x) || pixel.y >= int(size.y)) {
        return;
    }
    const float depth = texelFetch(depth_tex, pixel, 0).r;
    if (depth >= 1.0) {
        return;
    }
    const vec4 scene = imageLoad(scene_img, pixel);
    const vec2 uv = (vec2(pixel) + 0.5) / size;
    // The copy's last level is one texel: the frame's key.
    const float key = textureLod(prep_tex, vec2(0.5), 99.0).r;
    lum_floor = blackLevel(key);
    tone_floor = pow(lum_floor, 1.0 / 3.0);
    const float z = viewZ(depth);
    const vec3 c = viewPos(vec2(pixel) + 0.5, z);
    const vec3 rel = dirToWorld(c);
    const vec3 n = worldNormal(pixel, c);
    const uint view = (flags >> 8u) & 7u;
    test_view = view == VIEW_STROKES || view == VIEW_FINE || view == VIEW_BOLD;
    const float detail = view == VIEW_FINE ? 1.0 : view == VIEW_BOLD ? 0.0 : detailAt(uv);
    // What moves by itself would slide under strokes that lie still in the world: it is
    // smoothed instead, by its own share of the strength (the test view shows its dabs grey).
    const bool moving = movesItself(pixel, depth);
    test_grey = moving;
    const float amount = strength * (moving ? characters : 1.0);
    if (amount <= 0.0 && !test_view) {
        return;
    }
    Own own;
    own.rgb = max(scene.rgb, 0.0);
    own.lum = dot(own.rgb, LUMA);
    own.hue = hueOf(own.rgb);
    own.z = z;
    // The G-buffer's normal has the surface's bumps in it; where the surface itself lies comes
    // from the depth.
    const vec3 flat_n = (flags & FLAG_NORMALS) != 0u ? depthNormal(pixel, c) : n;
    own.facing = dirToView(flat_n);
    own.level = dot(own.facing, c);
    if (test_view) {
        imageStore(scene_img, pixel,
                   vec4(strokeColour(uv, rel, n, flat_n, detail, own), scene.a));
        return;
    }
    const vec3 paint = moving ? calmColour(uv, cell_fine, own)
                              : strokeColour(uv, rel, n, flat_n, detail, own);
    const float keep = keepOwn(uv, paint, own, key);
    const vec3 rgb = mix(scene.rgb, paint, amount * (1.0 - keep));
    // A scene colour that is no number stays what it is.
    if (!any(isnan(rgb))) {
        imageStore(scene_img, pixel, vec4(rgb, scene.a));
    }
}
""",
    R + "drawn_look_params.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r45_drawn-look): the words the drawn look's passes take (host_shaders/paint_common.glsl,
// the Constants block), and how the settings and the frame's camera become them. No Vulkan here:
// tests/test_drawn_look.cpp runs the passes with the same words.

#include <algorithm>
#include <array>
#include <cstdint>

namespace Vulkan::DrawnLookParams {

/// The push constants of the drawn look's passes (host_shaders/paint_*.comp).
struct Params {
    std::array<float, 12> inv_view; ///< view to world, 3x4 rows
    std::array<float, 4> proj;      ///< x scale, y scale, z scale, z offset
    std::array<float, 2> size;      ///< the scene in pixels
    std::array<float, 2> jitter;    ///< the frame's viewport shift in pixels
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
/// lines' view; until they are built it shows the look, as 0 does.
enum View : int { ViewOff = 0, ViewStrokes = 1, ViewFine = 2, ViewInk = 3, ViewBold = 4, ViewMax = 4 };

/// A stroke's cell on a screen of 2160 lines, in pixels, at stroke size 1.0 (a stroke is about
/// 2.4 cells long and one wide). The owner chose a mix: bold strokes on large plain surfaces,
/// fine ones where there is detail. Other resolutions keep the stroke's share of the picture.
inline constexpr float BoldCellAt2160 = 30.0f, FineCellAt2160 = 10.0f;

/// What the settings give a frame (BbSettings: the graphics_drawn_look_* keys).
struct Knobs {
    float strength = 0.6f;
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
    R + "vk_drawn_look.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_drawn_look.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "video_core/host_shaders/paint_key_comp.h"
#include "video_core/host_shaders/paint_key_last_comp.h"
#include "video_core/host_shaders/paint_lock_comp.h"
#include "video_core/host_shaders/paint_lock_down_comp.h"
#include "video_core/host_shaders/paint_lock_first_comp.h"
#include "video_core/host_shaders/paint_mips_comp.h"
#include "video_core/host_shaders/paint_prep_comp.h"
#include "video_core/host_shaders/paint_stats_comp.h"
#include "video_core/host_shaders/paint_strokes_comp.h"
#include "video_core/renderer_vulkan/drawn_look_params.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr vk::ImageSubresourceRange AllLevels{vk::ImageAspectFlagBits::eColor, 0,
                                              VK_REMAINING_MIP_LEVELS, 0, 1};
/// More levels than any scene has (a level a halving, down to one texel).
constexpr u32 MaxLevels = 16;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto Sampled = vk::DescriptorType::eCombinedImageSampler;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;

vk::DescriptorImageInfo Info(vk::ImageView view, vk::Sampler sampler = {}) {
    return {.sampler = sampler, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// The levels of an image this wide and high, down to one texel.
u32 LevelsOf(u32 width, u32 height) {
    return std::min(u32(std::bit_width(std::max(width, height))), MaxLevels);
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}
}

DrawnLook::DrawnLook(const Instance& instance_, Scheduler& scheduler_,
                     VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                     SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                     ObjectMotion& object_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_},
      object_motion{object_motion_} {
    // Not a key of its own in the ini: a test view that a menu change saved there would stay on.
    if (const char* env = std::getenv("BB_DRAWN_LOOK_VIEW")) {
        env_view = std::clamp(std::atoi(env), int(DrawnLookParams::ViewOff),
                              int(DrawnLookParams::ViewMax));
    }
}

DrawnLook::~DrawnLook() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool DrawnLook::Wanted() {
    const auto& s = BbSettings::Get();
    return s.graphics_drawn_look.load(std::memory_order_relaxed) &&
           s.graphics_drawn_look_strength.load(std::memory_order_relaxed) > 0.0f;
}

void DrawnLook::NoSceneHooks() {
    BbSettings::Get().drawn_look_problem = "the upscaler is not available (BB_UPSCALER=none, or "
                                           "this GPU cannot run it)";
}

void DrawnLook::Fail(const char* why) {
    failed = true;
    BbSettings::Get().drawn_look_problem = why;
    std::printf("Drawn look: off - %s\n", why);
    // Nothing is painted any more: what was made for it goes now, not when the switch does.
    ReleaseAll();
}

void DrawnLook::ReleaseAll() {
    ReleaseImage(prep_copy);
    ReleaseImage(marks);
    ReleaseImage(lock_means);
    ReleaseViews();
}

bool DrawnLook::SceneDepth(VideoCore::ImageId depth) const {
    return !scene_depths[0] ||
           std::find(scene_depths.begin(), scene_depths.end(), depth) != scene_depths.end();
}

bool DrawnLook::CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                           std::span<const u32> code, const char* name) {
    return EffectPass::Create(instance, pass.set_layout, pass.layout, pass.pipeline, types,
                              sizeof(DrawnLookParams::Params), code, name);
}

bool DrawnLook::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    // The strokes read their colours between the levels of the copy: a sampler of this class's
    // own (EffectPass::CreateSampler's reads one level).
    auto levels_sampler = instance.GetDevice().createSamplerUnique({
        .magFilter = vk::Filter::eLinear,
        .minFilter = vk::Filter::eLinear,
        .mipmapMode = vk::SamplerMipmapMode::eLinear,
        .addressModeU = vk::SamplerAddressMode::eClampToEdge,
        .addressModeV = vk::SamplerAddressMode::eClampToEdge,
        .addressModeW = vk::SamplerAddressMode::eClampToEdge,
        .maxLod = VK_LOD_CLAMP_NONE,
    });
    const bool made =
        levels_sampler.result == vk::Result::eSuccess &&
        EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
        CreatePass(prep, {SampledImage, SampledImage, StorageImage}, PAINT_PREP_COMP,
                   "Drawn look prep") &&
        CreatePass(stats, {SampledImage, StorageImage, StorageImage}, PAINT_STATS_COMP,
                   "Drawn look stats") &&
        CreatePass(mips, {Sampled, Sampled, StorageImage, StorageImage}, PAINT_MIPS_COMP,
                   "Drawn look mips") &&
        CreatePass(key_sums, {SampledImage, StorageImage}, PAINT_KEY_COMP,
                   "Drawn look key sums") &&
        CreatePass(key_last, {SampledImage, StorageImage}, PAINT_KEY_LAST_COMP,
                   "Drawn look key") &&
        CreatePass(strokes,
                   {Sampled, SampledImage, SampledImage, SampledImage, StorageImage, Sampled},
                   PAINT_STROKES_COMP, "Drawn look strokes") &&
        CreatePass(lock_first, {SampledImage, StorageImage}, PAINT_LOCK_FIRST_COMP,
                   "Drawn look lock means") &&
        CreatePass(lock_down, {Sampled, StorageImage}, PAINT_LOCK_DOWN_COMP,
                   "Drawn look lock levels") &&
        CreatePass(lock, {Sampled, SampledImage, SampledImage, StorageImage, Sampled},
                   PAINT_LOCK_COMP, "Drawn look lock");
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    sampler = std::move(levels_sampler.value);
    return true;
}

void DrawnLook::ReleaseImage(OwnImage& own) {
    if (own.image) {
        scheduler.DeferOperation([image = std::move(own.image), view = std::move(own.view),
                                  levels = std::move(own.levels)]() mutable {
            levels.clear();
            view.reset();
            image.Destroy();
        });
    }
    own.levels.clear();
    own.width = 0;
    own.height = 0;
}

bool DrawnLook::EnsureImage(OwnImage& own, u32 width, u32 height, vk::Format format,
                            const char* name) {
    if (own.image && own.width == width && own.height == height) {
        return false;
    }
    ReleaseImage(own);
    const auto device = instance.GetDevice();
    const u32 levels = LevelsOf(width, height);
    own.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    own.image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {width, height, 1},
        .mipLevels = levels,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(own.image), "Drawn look {}", name);
    own.view = Check<"create drawn look image view">(device.createImageViewUnique({
        .image = vk::Image(own.image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = AllLevels,
    }));
    for (u32 level = 0; level < levels; ++level) {
        own.levels.push_back(Check<"create drawn look level view">(device.createImageViewUnique({
            .image = vk::Image(own.image),
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, level, 1, 0, 1},
        })));
    }
    own.width = width;
    own.height = height;
    return true;
}

vk::ImageView DrawnLook::CachedView(const VideoCore::Image& image, vk::Format format,
                                    vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
            entry.last_use = ++view_uses;
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = format,
        .aspect = aspect,
        .view = Check<"create drawn look view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void DrawnLook::ReleaseViews() {
    const auto device = instance.GetDevice();
    for (auto& entry : view_cache) {
        if (entry.view) {
            scheduler.DeferOperation(
                [device, view = entry.view] { device.destroyImageView(view); });
        }
        entry = {};
    }
}

void DrawnLook::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal) {
    gbuffer_depth = depth;
    gbuffer_normal = normal;
}

void DrawnLook::OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                               std::array<float, 2> jitter) {
    if (!SceneDepth(depth)) {
        return;
    }
    blended_this_frame = true;
    Paint(AtBlended, color, depth, jitter);
}

void DrawnLook::OnSceneComposite(u64 hash, VideoCore::ImageId color, VideoCore::ImageId depth,
                                 std::array<float, 2> jitter) {
    // The passes of another view of the world (a reflection) are not the scene's: not counted.
    if (!SceneDepth(depth)) {
        return;
    }
    // Which of this shader's full-screen passes of the frame this one is. A frame with more
    // shaders than there is room for does not tell the later ones apart: they match nothing.
    u32 nth = ~0u;
    const auto seen = std::find_if(frame_passes.begin(), frame_passes.begin() + frame_pass_count,
                                   [hash](const FullScreenPass& pass) { return pass.hash == hash; });
    if (seen != frame_passes.begin() + frame_pass_count) {
        nth = seen->nth++;
    } else if (frame_pass_count < frame_passes.size()) {
        frame_passes[frame_pass_count++] = {hash, 1};
        nth = 0;
    }
    if (blended_this_frame) {
        // The first pass after the first transparents. On a frame that was painted before the
        // remembered pass (it had no transparents by then) this one comes after that pass: it
        // tells nothing.
        if (!composite_this_frame && frame_result != AtComposite) {
            composite_this_frame = true;
            if (composite.hash == hash && composite.nth == nth) {
                candidate_frames = 0;
            } else {
                if (candidate.hash != hash || candidate.nth != nth) {
                    candidate = {hash, nth};
                    candidate_frames = 0;
                }
                if (composite.hash == 0 || ++candidate_frames >= CompositeFrames) {
                    composite = candidate;
                    candidate_frames = 0;
                    // Areas differ in it; a game that changed it often would fill the log.
                    if (composite_changes < 8) {
                        ++composite_changes;
                        std::printf("Drawn look: the full-screen pass after the first "
                                    "transparents is ps %016llx (number %u of it in the "
                                    "frame): a frame without transparents is painted before "
                                    "that pass\n",
                                    static_cast<unsigned long long>(hash), nth + 1);
                    }
                }
            }
        }
        return;
    }
    if (composite.hash != 0 && composite.hash == hash && composite.nth == nth) {
        Paint(AtComposite, color, depth, jitter);
    }
}

void DrawnLook::OnBeforeUpscaler(VideoCore::ImageId color, VideoCore::ImageId depth,
                                 std::array<float, 2> jitter) {
    Paint(AtBeforeUpscaler, color, depth, jitter);
}

void DrawnLook::OnFrameEnd(bool wanted) {
    if (was_wanted) {
        ++results[frame_result];
        if (++frames >= 600) {
            BbReport::Printf("Drawn look: of %u frames, strokes painted before the transparents "
                             "on %u, before the fog composite (no transparents) on %u, before "
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
                                 scene_depths.end()) {
            scene_depths[scene_depth_next++ % scene_depths.size()] = gbuffer_depth;
        }
        if (!wanted) {
            // Switched off (or the strength set to 0): the images go, the pipelines are kept.
            ReleaseAll();
            last_view = last_inputs = ~0u;
            input_lines = 0;
            scene_depths = {};
            scene_depth_next = 0;
            // Switched on again, the memory is asked for again.
            if (refused_width != 0) {
                refused_width = refused_height = 0;
                BbSettings::Get().drawn_look_problem = nullptr;
            }
        }
    }
    was_wanted = wanted;
    frame_result = NotReached;
    blended_this_frame = false;
    composite_this_frame = false;
    frame_pass_count = 0;
    gbuffer_depth = {};
    gbuffer_normal = {};
}

void DrawnLook::Paint(Result place, VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                      std::array<float, 2> jitter) {
    if (frame_result <= AtBeforeUpscaler || failed || !color_id || !depth_id) {
        return;
    }
    // A frame with several G-buffer passes is a menu's 3D preview (character creation), which
    // the upscaler leaves alone too: its "scene" is one of the previews.
    if (camera_motion.PreviewFrame()) {
        frame_result = Preview;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid) {
        frame_result = NoCamera;
        return;
    }
    if (!Ready()) {
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        Fail("the scene colour is not RGBA16F");
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    // Too small to be the scene; the marks are made from 4x4 pixels of it.
    if (width < 16 || height < 16) {
        return;
    }
    // The marks are half as wide and high, the painted scene's means a quarter.
    const u32 half_width = width / 2, half_height = height / 2;
    // Eight bytes a texel; an image's smaller levels add a third; the marks have a quarter of
    // the scene's texels, the means a sixteenth.
    if (!prep_copy.image || prep_copy.width != width || prep_copy.height != height) {
        if (width == refused_width && height == refused_height) {
            frame_result = NoRoom;
            return;
        }
        if (!EffectPass::HasRoom(instance, 14ull * width * height)) {
            // Not for good: a smaller scene (another render scale or preset) may fit. The
            // images of the size before are of no use meanwhile.
            refused_width = width;
            refused_height = height;
            frame_result = NoRoom;
            BbSettings::Get().drawn_look_problem = "not enough video memory at this render size";
            std::printf("Drawn look: off - not enough video memory for a scene of %ux%u; asked "
                        "again when the scene's size changes or the look is switched off and "
                        "on\n", width, height);
            ReleaseAll();
            return;
        }
        if (refused_width != 0) {
            refused_width = refused_height = 0;
            BbSettings::Get().drawn_look_problem = nullptr;
        }
    }
    // The G-buffer's normals are the scene's while its lighting and transparents are drawn.
    // Right before the upscaler the game may have reused that target: the normal then comes
    // from the depth.
    VideoCore::Image* normal = nullptr;
    if (place != AtBeforeUpscaler && gbuffer_normal && gbuffer_depth == depth_id) {
        normal = &texture_cache.GetImage(gbuffer_normal);
        if (normal->info.pixel_format != vk::Format::eR8G8B8A8Unorm) {
            normal = nullptr;
        }
    }
    const SceneUseScope scene_use{"drawn look"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, normal_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the reduced scene colour is not a storage image");
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        if (normal && scene_targets.EligibleScene(*normal)) {
            VideoCore::ImageViewInfo normal_info;
            normal_info.format = normal->info.pixel_format;
            normal_view = scene_targets.ReadNext(gbuffer_normal, normal_info).view;
        }
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the scene colour is not a storage image");
            return;
        }
        color_view = CachedView(color, color.info.pixel_format, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, depth.info.pixel_format, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead);
        if (normal && normal->info.size.width >= width && normal->info.size.height >= height) {
            normal_view = CachedView(*normal, normal->info.pixel_format,
                                     vk::ImageAspectFlagBits::eColor);
            runtime.Transit(normal, vk::ImageLayout::eGeneral, Compute,
                            vk::AccessFlagBits2::eShaderRead);
        }
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // This frame's object motion, where the G-buffer pass wrote it at the scene's size (asked
    // first: PrepareRead would make an image where there is none).
    vk::ImageView motion_view{};
    bool has_motion = false;
    if (object_motion.Enabled() && object_motion.Image(width, height)) {
        motion_view = object_motion.PrepareRead(width, height, has_motion);
    }
    const bool has_normal = normal_view != vk::ImageView{};
    EnsureImage(prep_copy, width, height, vk::Format::eR16G16B16A16Sfloat, "scene copy");
    EnsureImage(marks, half_width, half_height, vk::Format::eR16G16B16A16Sfloat, "marks");
    EnsureImage(lock_means, width / 4, height / 4, vk::Format::eR16G16B16A16Sfloat, "means");
    frame_result = place;

    const auto& s = BbSettings::Get();
    const DrawnLookParams::Knobs knobs{
        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
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
    // has no G-buffer normals): their line is printed a few times, not on every change.
    const u32 inputs = params.flags & (DrawnLookParams::FlagNormals | DrawnLookParams::FlagMotion);
    const bool resized = width != last_width || height != last_height || view != last_view;
    if (resized || (inputs != last_inputs && input_lines < 8)) {
        input_lines += !resized;
        last_width = width;
        last_height = height;
        last_view = view;
        last_inputs = inputs;
        std::printf("Drawn look: on at %ux%u (%s), stroke cells %.1f and %.1f pixels, normals "
                    "from %s, object motion %s, %s\n",
                    width, height, reduced ? "reduced scene" : "the game's scene",
                    params.cell_bold, params.cell_fine, has_normal ? "the G-buffer" : "the depth",
                    has_motion ? "read" : "not there",
                    view == DrawnLookParams::ViewStrokes  ? "test view 1 (strokes, sizes as mixed)"
                    : view == DrawnLookParams::ViewFine   ? "test view 2 (strokes, all fine)"
                    : view == DrawnLookParams::ViewBold   ? "test view 4 (strokes, all bold)"
                                                          : "no test view");
    }

    // Each level's view, for the closures below.
    struct {
        std::array<vk::ImageView, MaxLevels> prep{}, marks{}, lock{};
        u32 count = 0; ///< the copy's levels; the marks have one fewer, the means two
    } levels;
    levels.count = u32(prep_copy.levels.size());
    for (u32 level = 0; level < levels.count; ++level) {
        levels.prep[level] = *prep_copy.levels[level];
    }
    for (u32 level = 0; level < marks.levels.size(); ++level) {
        levels.marks[level] = *marks.levels[level];
    }
    for (u32 level = 0; level < lock_means.levels.size(); ++level) {
        levels.lock[level] = *lock_means.levels[level];
    }
    // The key is told from the copy's level that is 64 texels or fewer on its longer side.
    u32 key_level = 0;
    while ((std::max(width, height) >> key_level) > 64) {
        ++key_level;
    }
    // Two rows in BB_GPU_PROFILE's table: what the strokes are made from, and the strokes
    // with the colour lock after them.
    EffectPass::Mark(18, "drawn look copy and masks");
    scheduler.RecordCrumb(
        {.name = "drawn look masks"},
        [params, width, height, half_width, half_height, levels, key_level, color_view,
         depth_view, sampler = *sampler, prep_image = vk::Image(prep_copy.image),
         marks_image = vk::Image(marks.image), lock_image = vk::Image(lock_means.image),
         prep_pipeline = *prep.pipeline, prep_layout = *prep.layout,
         stats_pipeline = *stats.pipeline, stats_layout = *stats.layout,
         mips_pipeline = *mips.pipeline, mips_layout = *mips.layout,
         sums_pipeline = *key_sums.pipeline, sums_layout = *key_sums.layout,
         key_pipeline = *key_last.pipeline,
         key_layout = *key_last.layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            // The three images are written anew every frame, every level of them; what the
            // frame before read of them is done.
            std::array<vk::ImageMemoryBarrier2, 3> to_general;
            to_general.fill({
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .subresourceRange = AllLevels,
            });
            to_general[0].image = prep_image;
            to_general[1].image = marks_image;
            to_general[2].image = lock_image;
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = u32(to_general.size()),
                                     .pImageMemoryBarriers = to_general.data()});
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout,
                                 std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(params), &params);
                cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
                EffectPass::ComputeBarrier(cmdbuf);
            };
            {
                const std::array infos{Info(color_view), Info(depth_view), Info(levels.prep[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2])};
                run(prep_pipeline, prep_layout, writes, width, height);
            }
            {
                const std::array infos{Info(levels.prep[0]), Info(levels.prep[1]),
                                       Info(levels.marks[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2])};
                run(stats_pipeline, stats_layout, writes, half_width, half_height);
            }
            // Level n of the copy and n - 1 of the marks are as large: each gives the next.
            for (u32 n = 1; n + 1 < levels.count; ++n) {
                const std::array infos{Info(levels.prep[n], sampler),
                                       Info(levels.marks[n - 1], sampler),
                                       Info(levels.prep[n + 1]), Info(levels.marks[n])};
                const std::array writes{Write(0, Sampled, &infos[0]), Write(1, Sampled, &infos[1]),
                                        Write(2, StorageImage, &infos[2]),
                                        Write(3, StorageImage, &infos[3])};
                run(mips_pipeline, mips_layout, writes, std::max(half_width >> n, 1u),
                    std::max(half_height >> n, 1u));
            }
            // The frame's key, over the copy's last level (one texel). Its sums wait in the
            // first texels of the means' image, which nothing else uses before the strokes.
            {
                const std::array infos{Info(levels.prep[key_level]), Info(levels.lock[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1])};
                run(sums_pipeline, sums_layout, writes, 8, 8);
            }
            {
                const std::array infos{Info(levels.lock[0]), Info(levels.prep[levels.count - 1])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1])};
                run(key_pipeline, key_layout, writes, 8, 8);
            }
        });
    EffectPass::Mark(12, "drawn look strokes and colour lock");
    scheduler.RecordCrumb(
        {.name = "drawn look"},
        [params, width, height, locked, levels, color_view, depth_view, sampler = *sampler,
         // A pass without normals or motion binds the copy in their place; its flags tell the
         // shader not to read them.
         normal_view = has_normal ? normal_view : *prep_copy.view,
         motion_view = has_motion ? motion_view : *prep_copy.view, prep_view = *prep_copy.view,
         marks_view = *marks.view, lock_view = *lock_means.view,
         strokes_pipeline = *strokes.pipeline,
         strokes_layout = *strokes.layout, first_pipeline = *lock_first.pipeline,
         first_layout = *lock_first.layout, down_pipeline = *lock_down.pipeline,
         down_layout = *lock_down.layout, lock_pipeline = *lock.pipeline,
         lock_layout = *lock.layout](vk::CommandBuffer cmdbuf) {
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout,
                                 std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(params), &params);
                cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            };
            {
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(normal_view),        Info(motion_view),
                                       Info(color_view),         Info(marks_view, sampler)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        Write(3, SampledImage, &infos[3]),
                                        Write(4, StorageImage, &infos[4]),
                                        Write(5, Sampled, &infos[5])};
                run(strokes_pipeline, strokes_layout, writes, width, height);
            }
            if (locked) {
                // The means' image: every level is written anew here (the key's sums in it
                // are done with).
                EffectPass::ComputeBarrier(cmdbuf);
                {
                    const std::array infos{Info(color_view), Info(levels.lock[0])};
                    const std::array writes{Write(0, SampledImage, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(first_pipeline, first_layout, writes, width / 4, height / 4);
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                for (u32 n = 0; n + 3 < levels.count; ++n) {
                    const std::array infos{Info(levels.lock[n], sampler),
                                           Info(levels.lock[n + 1])};
                    const std::array writes{Write(0, Sampled, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(down_pipeline, down_layout, writes, std::max(width >> (n + 3), 1u),
                        std::max(height >> (n + 3), 1u));
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(motion_view), Info(color_view),
                                       Info(lock_view, sampler)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        Write(3, StorageImage, &infos[3]),
                                        Write(4, Sampled, &infos[4])};
                run(lock_pipeline, lock_layout, writes, width, height);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

}
""",
    R + "vk_drawn_look.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look, an optional hand-painted look. Brush strokes fixed to
// the world are laid on the scene's solid surfaces before fire, glows, fog and particles are
// drawn, so those stay as the game draws them, and before the upscaler, the game's own colour
// processing and the HUD, which treat the strokes as they treat a texture. Colours are not
// changed. Off by default: graphics_drawn_look in lantern.ini and the menu's Picture tab. While
// it is off, or its strength is 0, the rasterizer calls nothing here but OnFrameEnd: no
// pipeline, no image, no pass.
//
// Built so far (stages 1 and 2 of the design): the switch, the passes' place in the frame, the
// strokes themselves (host_shaders/paint_strokes.comp), and a test view
// (graphics_drawn_look_debug) that paints every stroke in a flat colour of its own. Not built:
// ink lines, painted shadow edges.
//
// The passes, all compute, recorded in Paint:
//   paint_prep.comp     the scene colour and the view depth into the copy (the stroke pass
//                       rewrites the scene in place and must read it as it was)
//   paint_stats.comp    at half size: the copy's level 1 and the marks' level 0 (how much the
//                       picture varies under a stroke, and whether along lines)
//   paint_mips.comp     once a level: the smaller levels of both, down to one texel
//   paint_key.comp      twice: the frame's key (how bright its surfaces are, the sky and single
//                       bright pixels left out), written over the copy's last level
//   paint_strokes.comp  the strokes into the scene colour
//   paint_lock.comp     the painted scene's means (a quarter of the size, and their smaller
//                       levels), then every place scaled back to the mean colour it had

#pragma once

#include <array>
#include <initializer_list>
#include <span>
#include <vector>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class ObjectMotion;
class Runtime;
class SceneTargets;
class Scheduler;

class DrawnLook {
public:
    DrawnLook(const Instance& instance, Scheduler& scheduler,
              VideoCore::TextureCache& texture_cache, Runtime& runtime,
              SceneTargets& scene_targets, CameraMotion& camera_motion,
              ObjectMotion& object_motion);
    ~DrawnLook();

    /// The switch is on and the strength is above 0 (the rasterizer asks once a frame).
    [[nodiscard]] static bool Wanted();
    /// The scene's hooks below are never reached (no upscaler: BB_UPSCALER=none, or a GPU it
    /// cannot run on): the menu says so instead of offering a switch that does nothing.
    static void NoSceneHooks();

    /// A G-buffer pass's depth and world normals: the normals belong to the scene whose depth
    /// this is.
    void OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal);

    /// The three places a frame's strokes can be painted; the first that comes paints. The
    /// first two count only in the scene itself: a frame may draw the world a second time before
    /// it (a reflection in water, from a mirrored camera, with a depth of its own), and strokes
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
                          std::array<float, 2> jitter);

    /// `wanted`: Wanted() as the rasterizer read it for the frame that starts now.
    void OnFrameEnd(bool wanted);

private:
    /// How a frame went: where its strokes were painted, or why they were not.
    enum Result : u32 { AtBlended, AtComposite, AtBeforeUpscaler, Preview, NoCamera, NoRoom,
                        NotReached, ResultCount };
    /// An image with all its levels down to one texel.
    struct OwnImage {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;                ///< all levels
        std::vector<vk::UniqueImageView> levels; ///< each level alone
        u32 width = 0, height = 0;
    };
    struct Pass {
        vk::UniqueDescriptorSetLayout set_layout;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    struct ViewEntry {
        vk::Image image;
        u64 uid = 0;
        vk::Format format{};
        vk::ImageAspectFlags aspect{};
        vk::ImageView view;
        u64 last_use = 0;
    };
    /// A full-screen pass over the scene colour: its fragment shader, and which of that
    /// shader's passes in the frame it is (from 0). In frame_passes `nth` counts them.
    struct FullScreenPass {
        u64 hash = 0;
        u32 nth = 0;
    };

    bool Ready();
    bool CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                    std::span<const u32> code, const char* name);
    void Fail(const char* why);
    void ReleaseAll();
    [[nodiscard]] bool SceneDepth(VideoCore::ImageId depth) const;
    void Paint(Result place, VideoCore::ImageId color, VideoCore::ImageId depth,
               std::array<float, 2> jitter);
    bool EnsureImage(OwnImage& image, u32 width, u32 height, vk::Format format, const char* name);
    void ReleaseImage(OwnImage& image);
    vk::ImageView CachedView(const VideoCore::Image& image, vk::Format format,
                             vk::ImageAspectFlags aspect);
    void ReleaseViews();

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;
    ObjectMotion& object_motion;

    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;
    vk::UniqueSampler sampler; ///< linear between texels and between levels, clamped
    OwnImage prep_copy; ///< the scene before the strokes, view depth (paint_prep.comp)
    OwnImage marks;     ///< half the size: what tells plain surfaces from detail (paint_stats.comp)
    /// A quarter of the size: the painted scene's means (paint_lock.comp); before the strokes
    /// its first texels hold the key's sums (paint_key.comp).
    OwnImage lock_means;
    std::array<ViewEntry, 6> view_cache{};
    u64 view_uses = 0;
    VideoCore::ImageId gbuffer_depth, gbuffer_normal;
    /// BB_DRAWN_LOOK_VIEW: a test view that decides instead of the ini's
    /// graphics_drawn_look_debug while the variable is set; -1 without it.
    int env_view = -1;
    bool tried = false;
    bool failed = false;
    bool was_wanted = false;
    /// The scene's size the images were last refused at for want of video memory (0: none).
    /// Not asked again at that size; another size, or the look switched off and on, asks again.
    u32 refused_width = 0, refused_height = 0;
    /// The depths of the last G-buffer pass of recent frames: the scene's own (it is drawn
    /// last; none known yet: any depth counts).
    std::array<VideoCore::ImageId, 4> scene_depths{};
    u32 scene_depth_next = 0;
    Result frame_result = NotReached;
    bool blended_this_frame = false;   ///< OnBlendedScene was reached (painted or not)
    bool composite_this_frame = false; ///< the full-screen pass after it was seen
    /// The full-screen passes of this frame so far, by shader, and the one that follows the
    /// transparents on the frames that have them (hash 0: none seen yet). `candidate` came
    /// first instead on the last `candidate_frames` such frames: a small sprite among the
    /// transparents is drawn as such a pass too, and must not take the fog composite's place
    /// for being first once.
    static constexpr u32 CompositeFrames = 30;
    std::array<FullScreenPass, 16> frame_passes{};
    u32 frame_pass_count = 0;
    FullScreenPass composite{};
    FullScreenPass candidate{};
    u32 candidate_frames = 0;
    u32 composite_changes = 0;
    /// For the line every 600 frames the look was wanted on.
    std::array<u32, ResultCount> results{};
    u32 frames = 0;
    /// What the last painted frame ran with: a line is printed when the size or the test view
    /// changes, and the first few times the inputs (normals, object motion) do: those may come
    /// and go with the place a frame is painted at.
    u32 last_width = 0, last_height = 0, last_view = ~0u, last_inputs = ~0u;
    u32 input_lines = 0;
};

}
""",
    TESTS + "test_drawn_look.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's passes (paint_prep.comp, paint_stats.comp,
// paint_mips.comp, paint_key.comp, paint_strokes.comp, paint_lock.comp) on a synthetic scene,
// with the words the renderer gives them (DrawnLookParams::Make) and recorded as the renderer
// records them. Checked here:
//  - a stroke belongs to a place in the world: the test view, which paints every stroke in a flat
//    colour of its own, gives the same picture, moved, when the jitter or the camera moves, and
//    so does what the look itself changes in the picture;
//  - the look keeps the picture's colours: the mean colour of every surface stays, the sky and
//    the alpha are not touched, a brighter or darker scene (another exposure) gets the same look;
//  - it flattens fine grit, leaves what moves by itself without strokes, and a colour that is no
//    number does not spread.
//
// drawn-look-test [picture.bmp]: with a path, four views of the scene are also written.
// drawn-look-test --picture in.bmp out [2]: the look on a picture (24-bit BMP, sRGB), laid on a
// floor and a wall for want of its depth; writes out_before.bmp, out_after.bmp, out_full.bmp
// (strength 1) and out_sizes.bmp (test view 1), prints what the look does to the picture's
// colours and what the passes cost on this GPU. "2": at half the picture's size; a number of
// lines (1440): at that height.
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <span>
#include <string>
#include <vector>
#define VULKAN_HPP_NO_CONSTRUCTORS
#define VULKAN_HPP_NO_EXCEPTIONS
#define VULKAN_HPP_DISPATCH_LOADER_DYNAMIC 1
#include <vulkan/vulkan.hpp>
#include "video_core/host_shaders/paint_key_comp.h"
#include "video_core/host_shaders/paint_key_last_comp.h"
#include "video_core/host_shaders/paint_lock_comp.h"
#include "video_core/host_shaders/paint_lock_down_comp.h"
#include "video_core/host_shaders/paint_lock_first_comp.h"
#include "video_core/host_shaders/paint_mips_comp.h"
#include "video_core/host_shaders/paint_prep_comp.h"
#include "video_core/host_shaders/paint_stats_comp.h"
#include "video_core/host_shaders/paint_strokes_comp.h"
#include "video_core/renderer_vulkan/drawn_look_params.h"

VULKAN_HPP_DEFAULT_DISPATCH_LOADER_DYNAMIC_STORAGE

namespace {
using u8 = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using Vec3 = std::array<double, 3>;
using Half4 = std::array<u16, 4>;
using Rgb = std::array<float, 3>;
namespace Look = Vulkan::DrawnLookParams;

constexpr vk::ImageSubresourceRange Range{vk::ImageAspectFlagBits::eColor, 0,
                                          VK_REMAINING_MIP_LEVELS, 0, 1};
constexpr double Near = 0.1;

template <class T>
T Check(vk::ResultValue<T> result) {
    if (result.result != vk::Result::eSuccess) {
        std::fprintf(stderr, "Vulkan call failed: %s\n", vk::to_string(result.result).c_str());
        std::abort();
    }
    return std::move(result.value);
}

u16 ToHalf(float value) {
    u32 bits;
    std::memcpy(&bits, &value, 4);
    const u32 sign = (bits >> 16) & 0x8000u;
    const int exponent = int((bits >> 23) & 0xff) - 127 + 15;
    u32 mantissa = bits & 0x7fffffu;
    if (exponent <= 0) {
        if (exponent < -10) {
            return u16(sign);
        }
        mantissa = (mantissa | 0x800000u) >> (1 - exponent);
        return u16(sign | ((mantissa + 0x1000u) >> 13));
    }
    if (exponent >= 31) {
        return u16(sign | 0x7c00u);
    }
    return u16((sign | (u32(exponent) << 10) | (mantissa >> 13)) + ((mantissa >> 12) & 1u));
}

float FromHalf(u16 half) {
    const int exponent = (half >> 10) & 31;
    const float mantissa = float(half & 1023u) / 1024.0f;
    if (exponent == 31) {
        return mantissa != 0.0f ? NAN : (half & 0x8000u) ? -INFINITY : INFINITY;
    }
    const float value = exponent == 0 ? std::ldexp(mantissa, -14)
                                      : std::ldexp(1.0f + mantissa, exponent - 15);
    return (half & 0x8000u) ? -value : value;
}

Vec3 Add(const Vec3& a, const Vec3& b, double s = 1.0) {
    return {a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s};
}
double Dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/// View axes: x right, y down, z forward. The world is y-up, as the game's.
struct Camera {
    Vec3 pos{};
    double yaw = 0.0, pitch = 0.0; ///< radians; yaw 0 looks along world z
    std::array<float, 2> jitter{};

    Vec3 Forward() const {
        return {std::sin(yaw) * std::cos(pitch), std::sin(pitch), std::cos(yaw) * std::cos(pitch)};
    }
    Vec3 Right() const {
        return {std::cos(yaw), 0.0, -std::sin(yaw)};
    }
    Vec3 Down() const {
        const Vec3 f = Forward(), r = Right();
        return {-(f[1] * r[2] - f[2] * r[1]), -(f[2] * r[0] - f[0] * r[2]),
                -(f[0] * r[1] - f[1] * r[0])};
    }
    std::array<float, 12> InvView() const {
        const Vec3 r = Right(), d = Down(), f = Forward();
        std::array<float, 12> rows;
        for (int i = 0; i < 3; ++i) {
            rows[i * 4 + 0] = float(r[i]);
            rows[i * 4 + 1] = float(d[i]);
            rows[i * 4 + 2] = float(f[i]);
            rows[i * 4 + 3] = float(pos[i]);
        }
        return rows;
    }
};

/// The projection's scales for a screen of this shape: 50 degrees from top to bottom.
struct Lens {
    u32 width, height;
    double ys = 1.0 / std::tan(25.0 * 3.14159265358979 / 180.0);
    double xs = ys * double(height) / double(width);
    std::array<float, 4> Proj() const {
        return {float(xs), float(ys), 1.0f, float(-Near)};
    }
};

enum Surface : u8 { Sky, Floor, BackWall, SideWall, Column, Ball };

struct Hit {
    Surface surface = Sky;
    double t = 1e30; ///< the view depth: the ray's direction has view z 1
    Vec3 normal{0, 1, 0};
};

Hit Cast(const Vec3& o, const Vec3& d) {
    Hit hit;
    const auto take = [&](Surface surface, double t, const Vec3& normal) {
        if (t > Near && t < hit.t) {
            hit = {surface, t, normal};
        }
    };
    if (d[1] < 0.0) {
        const double t = -o[1] / d[1];
        const Vec3 p = Add(o, d, t);
        if (p[0] > -3.5 && p[0] < 12.0 && p[2] > -5.0 && p[2] < 9.0) {
            take(Floor, t, {0, 1, 0});
        }
    }
    if (d[2] > 0.0) {
        const double t = (9.0 - o[2]) / d[2];
        const Vec3 p = Add(o, d, t);
        if (p[1] > 0.0 && p[1] < 4.2 && p[0] > -3.5 && p[0] < 6.0) {
            take(BackWall, t, {0, 0, -1});
        }
    }
    if (d[0] < 0.0) {
        const double t = (-3.5 - o[0]) / d[0];
        const Vec3 p = Add(o, d, t);
        if (p[1] > 0.0 && p[1] < 4.2 && p[2] > -5.0 && p[2] < 9.0) {
            take(SideWall, t, {1, 0, 0});
        }
    }
    {
        // A round column: its normals turn from one stroke plane to the other.
        const double cx = 1.6, cz = 5.5, radius = 0.45;
        const double a = d[0] * d[0] + d[2] * d[2];
        const double b = (o[0] - cx) * d[0] + (o[2] - cz) * d[2];
        const double c = (o[0] - cx) * (o[0] - cx) + (o[2] - cz) * (o[2] - cz) - radius * radius;
        const double disc = b * b - a * c;
        if (a > 1e-12 && disc > 0.0) {
            const double t = (-b - std::sqrt(disc)) / a;
            const Vec3 p = Add(o, d, t);
            if (p[1] > 0.0 && p[1] < 3.4) {
                take(Column, t, {(p[0] - cx) / radius, 0.0, (p[2] - cz) / radius});
            }
        }
    }
    {
        // A ball that stands for a character: the motion image says it moves by itself.
        const Vec3 centre{-0.9, 0.95, 4.2};
        const double radius = 0.55;
        const Vec3 oc = Add(o, centre, -1.0);
        const double a = Dot(d, d), b = Dot(oc, d), c = Dot(oc, oc) - radius * radius;
        const double disc = b * b - a * c;
        if (disc > 0.0) {
            const double t = (-b - std::sqrt(disc)) / a;
            const Vec3 p = Add(o, d, t);
            take(Ball, t, {(p[0] - centre[0]) / radius, (p[1] - centre[1]) / radius,
                           (p[2] - centre[2]) / radius});
        }
    }
    return hit;
}

struct Scene {
    u32 width = 0, height = 0;
    std::vector<Half4> colour;                ///< RGBA16F: linear, alpha a pattern of its own
    std::vector<float> depth;                 ///< 1 - Near / view depth; 1: sky
    std::vector<std::array<u8, 4>> normal;    ///< world normal * 0.5 + 0.5
    std::vector<std::array<float, 4>> motion; ///< b 1 and a the depth on the ball
    std::vector<Surface> surface;
    std::vector<Vec3> world;

    Scene(u32 w, u32 h)
        : width{w}, height{h}, colour(size_t(w) * h), depth(size_t(w) * h), normal(size_t(w) * h),
          motion(size_t(w) * h) {}
};

u32 Hash(u32 v) {
    v = v * 747796405u + 2891336453u;
    const u32 w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

/// What a scene's surfaces look like. Plain: one flat colour a surface (there a stroke's colour
/// in the test view depends on nothing but which stroke it is). Lit: a lamp's light on them.
/// Grit: on top of the light, a fine pattern fixed to the world, 2.5 cm a speck, as a stone
/// texture has: what the look is there to flatten.
/// Patches: on top of the light, light and dark patches fixed to the world, 12 cm a patch, apart
/// by a share that rises and falls along the surfaces: somewhere on each of them the picture is
/// just rough enough to count as detail, and the look goes from bold strokes to fine ones.
enum class Paint { Plain, Lit, Grit, Patches };

Scene MakeScene(const Lens& lens, const Camera& camera, Paint paint, float exposure = 1.0f) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    scene.surface.resize(size_t(w) * h);
    scene.world.resize(size_t(w) * h);
    const Vec3 r = camera.Right(), dn = camera.Down(), f = camera.Forward();
    static constexpr Rgb Colours[] = {{0.05f, 0.07f, 0.12f}, {0.16f, 0.14f, 0.12f},
                                      {0.30f, 0.27f, 0.22f}, {0.22f, 0.20f, 0.19f},
                                      {0.34f, 0.33f, 0.30f}, {0.25f, 0.08f, 0.07f}};
    for (u32 y = 0; y < h; ++y) {
        for (u32 x = 0; x < w; ++x) {
            const double nx = (x + 0.5 - camera.jitter[0]) / w * 2.0 - 1.0;
            const double ny = (y + 0.5 - camera.jitter[1]) / h * 2.0 - 1.0;
            const Vec3 dir = Add(Add(f, r, nx / lens.xs), dn, ny / lens.ys);
            const Hit hit = Cast(camera.pos, dir);
            const u32 i = y * w + x;
            const Vec3 p = Add(camera.pos, dir, hit.t);
            Rgb c = Colours[hit.surface];
            float light = exposure;
            if (paint != Paint::Plain && hit.surface != Sky) {
                const Vec3 to_lamp = Add(Vec3{0.5, 2.6, 3.0}, p, -1.0);
                const double distance2 = Dot(to_lamp, to_lamp);
                const double facing = std::max(Dot(hit.normal, to_lamp) / std::sqrt(distance2), 0.0);
                light *= float(0.25 + 6.0 * facing / (1.0 + distance2));
            }
            if (paint == Paint::Grit && hit.surface != Sky) {
                const auto cell = [&](int k) { return u32(int(std::floor(p[k] * 40.0)) + 4096); };
                light *= 0.8f + 0.4f * float(Hash(cell(0) + Hash(cell(1) + Hash(cell(2)))) >> 8) /
                                    16777216.0f;
            }
            if (paint == Paint::Patches && hit.surface != Sky) {
                // (Not on a whole number where a surface lies: the walls and the floor do.)
                const auto cell = [&](int k) {
                    return u32(int(std::floor(p[k] * 8.0 + 0.37)) + 4096);
                };
                const double wave = std::fmod((p[0] + p[2] + 100.0) / 6.0, 1.0);
                const double apart = 0.2 + 0.5 * (1.0 - std::abs(2.0 * wave - 1.0));
                const bool up = Hash(cell(0) + Hash(cell(1) + Hash(cell(2)))) & 0x100u;
                light *= float(up ? 1.0 + apart : 1.0 - apart);
            }
            for (float& channel : c) {
                channel *= light;
            }
            scene.colour[i] = {ToHalf(c[0]), ToHalf(c[1]), ToHalf(c[2]),
                               ToHalf(float((x * 7 + y * 13) % 32) / 64.0f)};
            scene.surface[i] = hit.surface;
            scene.depth[i] = hit.surface == Sky ? 1.0f : float(1.0 - Near / hit.t);
            scene.world[i] = p;
            for (int k = 0; k < 3; ++k) {
                scene.normal[i][k] = u8(std::lround((hit.normal[k] * 0.5 + 0.5) * 255.0));
            }
            scene.normal[i][3] = 255;
            if (hit.surface == Ball) {
                scene.motion[i] = {0.0f, 0.0f, 1.0f, scene.depth[i]};
            }
        }
    }
    return scene;
}

/// An image with all its levels down to one texel, as vk_drawn_look.cpp makes its three.
struct Image {
    vk::UniqueImage image;
    vk::UniqueDeviceMemory memory;
    vk::UniqueImageView view;                ///< all levels
    std::vector<vk::UniqueImageView> levels; ///< each level alone
};

/// What the passes take on the GPU, in milliseconds.
struct Times {
    double masks = 0.0;   ///< the copy, the marks and their levels
    double strokes = 0.0; ///< the stroke pass
    double lock = 0.0;    ///< the colour lock: the painted scene's means, and the scaling
};

class Gpu {
public:
    Gpu() {
        static vk::detail::DynamicLoader loader;
        VULKAN_HPP_DEFAULT_DISPATCHER.init(
            loader.getProcAddress<PFN_vkGetInstanceProcAddr>("vkGetInstanceProcAddr"));
        const vk::ApplicationInfo app{.pApplicationName = "drawn-look-test",
                                      .apiVersion = VK_API_VERSION_1_3};
        instance = Check(vk::createInstanceUnique({.pApplicationInfo = &app}));
        VULKAN_HPP_DEFAULT_DISPATCHER.init(*instance);
        const auto gpus = Check(instance->enumeratePhysicalDevices());
        assert(!gpus.empty());
        physical = gpus[0];
        std::printf("device: %s\n", physical.getProperties().deviceName.data());
        period_ns = physical.getProperties().limits.timestampPeriod;
        const auto families = physical.getQueueFamilyProperties();
        u32 family = 0;
        while (family < families.size() &&
               !(families[family].queueFlags & vk::QueueFlagBits::eCompute)) {
            ++family;
        }
        assert(family < families.size());
        timed = families[family].timestampValidBits == 64;
        const float priority = 1;
        const vk::DeviceQueueCreateInfo queue_info{.queueFamilyIndex = family,
                                                   .queueCount = 1,
                                                   .pQueuePriorities = &priority};
        const char* extension = VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
        device = Check(physical.createDeviceUnique({.queueCreateInfoCount = 1,
                                                    .pQueueCreateInfos = &queue_info,
                                                    .enabledExtensionCount = 1,
                                                    .ppEnabledExtensionNames = &extension}));
        VULKAN_HPP_DEFAULT_DISPATCHER.init(*device);
        queue = device->getQueue(family, 0);
        pool = Check(device->createCommandPoolUnique(
            {.flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
             .queueFamilyIndex = family}));
        command = Check(device->allocateCommandBuffers(
            {.commandPool = *pool,
             .level = vk::CommandBufferLevel::ePrimary,
             .commandBufferCount = 1}))[0];
        queries = Check(device->createQueryPoolUnique(
            {.queryType = vk::QueryType::eTimestamp, .queryCount = 4}));
        // As vk_drawn_look.cpp makes them.
        using enum vk::DescriptorType;
        prep = MakePass({eSampledImage, eSampledImage, eStorageImage}, PAINT_PREP_COMP);
        stats = MakePass({eSampledImage, eStorageImage, eStorageImage}, PAINT_STATS_COMP);
        mips = MakePass({eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
                        PAINT_MIPS_COMP);
        key_sums = MakePass({eSampledImage, eStorageImage}, PAINT_KEY_COMP);
        key_last = MakePass({eSampledImage, eStorageImage}, PAINT_KEY_LAST_COMP);
        strokes = MakePass({eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage,
                            eStorageImage, eCombinedImageSampler},
                           PAINT_STROKES_COMP);
        lock_first = MakePass({eSampledImage, eStorageImage}, PAINT_LOCK_FIRST_COMP);
        lock_down = MakePass({eCombinedImageSampler, eStorageImage}, PAINT_LOCK_DOWN_COMP);
        lock = MakePass({eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
                         eCombinedImageSampler},
                        PAINT_LOCK_COMP);
        sampler = Check(device->createSamplerUnique(
            {.magFilter = vk::Filter::eLinear,
             .minFilter = vk::Filter::eLinear,
             .mipmapMode = vk::SamplerMipmapMode::eLinear,
             .addressModeU = vk::SamplerAddressMode::eClampToEdge,
             .addressModeV = vk::SamplerAddressMode::eClampToEdge,
             .addressModeW = vk::SamplerAddressMode::eClampToEdge,
             .maxLod = VK_LOD_CLAMP_NONE}));
    }

    /// The scene colour after the passes.
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params) {
        Load(scene);
        Begin();
        RecordMasks(params);
        RecordStrokes(params);
        if (ShowsLook(params)) {
            RecordLock(params);
        }
        const vk::BufferImageCopy region{
            .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .imageExtent = {width, height, 1}};
        command.copyImageToBuffer(*colour.image, vk::ImageLayout::eGeneral, *staging, region);
        Barrier();
        Submit();
        std::vector<Half4> out(size_t(width) * height);
        std::memcpy(out.data(), mapped, out.size() * sizeof(Half4));
        return out;
    }

    /// What the passes take on this GPU. An idle GPU runs its clock slow and speeds it up only
    /// under work, so a single run between two uploads tells nothing: each part is recorded
    /// `repeats` times in a row in one submission, after as many unmeasured rounds of all of
    /// them, and the best of three such submissions counts.
    Times Measure(const Scene& scene, const Look::Params& params, u32 repeats) {
        Load(scene);
        Times best{1e9, 1e9, 1e9};
        for (int round = 0; round < 3; ++round) {
            Begin();
            command.resetQueryPool(*queries, 0, 4);
            const auto stamp = [&](u32 query) {
                command.writeTimestamp(vk::PipelineStageFlagBits::eBottomOfPipe, *queries, query);
            };
            for (u32 i = 0; i < repeats; ++i) {
                RecordMasks(params);
                RecordStrokes(params);
                RecordLock(params);
            }
            stamp(0);
            for (u32 i = 0; i < repeats; ++i) {
                RecordMasks(params);
            }
            stamp(1);
            for (u32 i = 0; i < repeats; ++i) {
                RecordStrokes(params);
            }
            stamp(2);
            for (u32 i = 0; i < repeats; ++i) {
                RecordLock(params);
            }
            stamp(3);
            Submit();
            std::array<uint64_t, 4> stamps{};
            const auto read = device->getQueryPoolResults(
                *queries, 0, 4, sizeof(stamps), stamps.data(), sizeof(uint64_t),
                vk::QueryResultFlagBits::e64 | vk::QueryResultFlagBits::eWait);
            assert(read == vk::Result::eSuccess);
            const double ms = period_ns / 1e6 / repeats;
            best.masks = std::min(best.masks, double(stamps[1] - stamps[0]) * ms);
            best.strokes = std::min(best.strokes, double(stamps[2] - stamps[1]) * ms);
            best.lock = std::min(best.lock, double(stamps[3] - stamps[2]) * ms);
        }
        return best;
    }

    bool Timed() const {
        return timed;
    }

private:
    struct Pass {
        vk::UniqueDescriptorSetLayout set;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };

    /// The colour lock runs with the look; a test view has no colours to lock.
    static bool ShowsLook(const Look::Params& params) {
        const u32 view = params.flags >> Look::ViewShift;
        return view == Look::ViewOff || view == Look::ViewInk;
    }

    void Load(const Scene& scene) {
        Resize(scene.width, scene.height);
        Upload(colour, scene.colour.data(), scene.colour.size() * sizeof(Half4));
        Upload(depth, scene.depth.data(), scene.depth.size() * sizeof(float));
        Upload(normal, scene.normal.data(), scene.normal.size() * 4);
        Upload(motion, scene.motion.data(), scene.motion.size() * 16);
    }

    void Dispatch(const Pass& pass, const Look::Params& params,
                  std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
        command.bindPipeline(vk::PipelineBindPoint::eCompute, *pass.pipeline);
        command.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *pass.layout, 0, writes);
        command.pushConstants(*pass.layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
        command.dispatch((w + 7) / 8, (h + 7) / 8, 1);
        Barrier();
    }

    vk::DescriptorImageInfo Info(const vk::UniqueImageView& view, bool sampled = false) const {
        return {.sampler = sampled ? *sampler : vk::Sampler{},
                .imageView = *view,
                .imageLayout = vk::ImageLayout::eGeneral};
    }

    static vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                                        const vk::DescriptorImageInfo* image) {
        return {.dstBinding = binding,
                .descriptorCount = 1,
                .descriptorType = type,
                .pImageInfo = image};
    }

    // The three parts below: as vk_drawn_look.cpp records them.
    void RecordMasks(const Look::Params& params) {
        using enum vk::DescriptorType;
        const u32 half_width = width / 2, half_height = height / 2;
        {
            const std::array infos{Info(colour.view), Info(depth.view), Info(copy.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eSampledImage, &infos[1]),
                                    Write(2, eStorageImage, &infos[2])};
            Dispatch(prep, params, writes, width, height);
        }
        {
            const std::array infos{Info(copy.levels[0]), Info(copy.levels[1]),
                                   Info(marks.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1]),
                                    Write(2, eStorageImage, &infos[2])};
            Dispatch(stats, params, writes, half_width, half_height);
        }
        for (u32 n = 1; n + 1 < copy.levels.size(); ++n) {
            const std::array infos{Info(copy.levels[n], true), Info(marks.levels[n - 1], true),
                                   Info(copy.levels[n + 1]), Info(marks.levels[n])};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eCombinedImageSampler, &infos[1]),
                                    Write(2, eStorageImage, &infos[2]),
                                    Write(3, eStorageImage, &infos[3])};
            Dispatch(mips, params, writes, std::max(half_width >> n, 1u),
                     std::max(half_height >> n, 1u));
        }
        u32 key_level = 0;
        while ((std::max(width, height) >> key_level) > 64) {
            ++key_level;
        }
        {
            const std::array infos{Info(copy.levels[key_level]), Info(means.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(key_sums, params, writes, 8, 8);
        }
        {
            const std::array infos{Info(means.levels[0]), Info(copy.levels.back())};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(key_last, params, writes, 8, 8);
        }
    }

    void RecordStrokes(const Look::Params& params) {
        using enum vk::DescriptorType;
        // A pass without normals or motion gets the copy in their place, as in the renderer.
        const bool normals = params.flags & Look::FlagNormals;
        const bool moving = params.flags & Look::FlagMotion;
        const std::array infos{Info(copy.view, true),
                               Info(depth.view),
                               Info(normals ? normal.view : copy.view),
                               Info(moving ? motion.view : copy.view),
                               Info(colour.view),
                               Info(marks.view, true)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eSampledImage, &infos[2]),
                                Write(3, eSampledImage, &infos[3]),
                                Write(4, eStorageImage, &infos[4]),
                                Write(5, eCombinedImageSampler, &infos[5])};
        Dispatch(strokes, params, writes, width, height);
    }

    void RecordLock(const Look::Params& params) {
        using enum vk::DescriptorType;
        {
            const std::array infos{Info(colour.view), Info(means.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(lock_first, params, writes, width / 4, height / 4);
        }
        for (u32 n = 0; n + 1 < means.levels.size(); ++n) {
            const std::array infos{Info(means.levels[n], true), Info(means.levels[n + 1])};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(lock_down, params, writes, std::max(width >> (n + 3), 1u),
                     std::max(height >> (n + 3), 1u));
        }
        const bool moving = params.flags & Look::FlagMotion;
        const std::array infos{Info(copy.view, true), Info(depth.view),
                               Info(moving ? motion.view : copy.view), Info(colour.view),
                               Info(means.view, true)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eSampledImage, &infos[2]),
                                Write(3, eStorageImage, &infos[3]),
                                Write(4, eCombinedImageSampler, &infos[4])};
        Dispatch(lock, params, writes, width, height);
    }

    Pass MakePass(std::initializer_list<vk::DescriptorType> types, std::span<const u32> code) {
        Pass pass;
        std::vector<vk::DescriptorSetLayoutBinding> bindings;
        for (const auto type : types) {
            bindings.push_back({.binding = u32(bindings.size()),
                                .descriptorType = type,
                                .descriptorCount = 1,
                                .stageFlags = vk::ShaderStageFlagBits::eCompute});
        }
        pass.set = Check(device->createDescriptorSetLayoutUnique(
            {.flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
             .bindingCount = u32(bindings.size()),
             .pBindings = bindings.data()}));
        const vk::PushConstantRange push{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                         .offset = 0,
                                         .size = sizeof(Look::Params)};
        pass.layout = Check(device->createPipelineLayoutUnique({.setLayoutCount = 1,
                                                                .pSetLayouts = &*pass.set,
                                                                .pushConstantRangeCount = 1,
                                                                .pPushConstantRanges = &push}));
        const auto module = Check(device->createShaderModuleUnique(
            {.codeSize = code.size_bytes(), .pCode = code.data()}));
        pass.pipeline = Check(device->createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{.stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                                                        .module = *module,
                                                        .pName = "main"},
                                              .layout = *pass.layout}));
        return pass;
    }

    u32 MemoryType(u32 bits, vk::MemoryPropertyFlags flags) const {
        const auto properties = physical.getMemoryProperties();
        for (u32 i = 0; i < properties.memoryTypeCount; ++i) {
            if ((bits & (1u << i)) && (properties.memoryTypes[i].propertyFlags & flags) == flags) {
                return i;
            }
        }
        std::abort();
    }

    /// `all_levels`: with every level down to one texel, else the one.
    Image MakeImage(vk::Format format, vk::ImageUsageFlags usage, u32 w, u32 h, bool all_levels) {
        Image made;
        const u32 levels = all_levels ? u32(std::bit_width(std::max(w, h))) : 1;
        made.image = Check(device->createImageUnique(
            {.imageType = vk::ImageType::e2D,
             .format = format,
             .extent = {w, h, 1},
             .mipLevels = levels,
             .arrayLayers = 1,
             .samples = vk::SampleCountFlagBits::e1,
             .tiling = vk::ImageTiling::eOptimal,
             .usage = usage | vk::ImageUsageFlagBits::eSampled |
                      vk::ImageUsageFlagBits::eTransferDst}));
        const auto needs = device->getImageMemoryRequirements(*made.image);
        made.memory = Check(device->allocateMemoryUnique(
            {.allocationSize = needs.size,
             .memoryTypeIndex =
                 MemoryType(needs.memoryTypeBits, vk::MemoryPropertyFlagBits::eDeviceLocal)}));
        const auto bound = device->bindImageMemory(*made.image, *made.memory, 0);
        assert(bound == vk::Result::eSuccess);
        made.view = Check(device->createImageViewUnique({.image = *made.image,
                                                         .viewType = vk::ImageViewType::e2D,
                                                         .format = format,
                                                         .subresourceRange = Range}));
        for (u32 level = 0; level < levels; ++level) {
            made.levels.push_back(Check(device->createImageViewUnique(
                {.image = *made.image,
                 .viewType = vk::ImageViewType::e2D,
                 .format = format,
                 .subresourceRange = {vk::ImageAspectFlagBits::eColor, level, 1, 0, 1}})));
        }
        return made;
    }

    void Resize(u32 w, u32 h) {
        if (w == width && h == height) {
            return;
        }
        width = w;
        height = h;
        const auto storage = vk::ImageUsageFlagBits::eStorage;
        const auto half = vk::Format::eR16G16B16A16Sfloat;
        colour = MakeImage(half, storage | vk::ImageUsageFlagBits::eTransferSrc, w, h, false);
        copy = MakeImage(half, storage, w, h, true);
        marks = MakeImage(half, storage, w / 2, h / 2, true);
        means = MakeImage(half, storage, w / 4, h / 4, true);
        depth = MakeImage(vk::Format::eR32Sfloat, {}, w, h, false);
        normal = MakeImage(vk::Format::eR8G8B8A8Unorm, {}, w, h, false);
        motion = MakeImage(vk::Format::eR32G32B32A32Sfloat, {}, w, h, false);
        if (mapped) {
            device->unmapMemory(*staging_memory);
        }
        staging = Check(device->createBufferUnique(
            {.size = vk::DeviceSize(width) * height * 16,
             .usage = vk::BufferUsageFlagBits::eTransferSrc |
                      vk::BufferUsageFlagBits::eTransferDst}));
        const auto needs = device->getBufferMemoryRequirements(*staging);
        staging_memory = Check(device->allocateMemoryUnique(
            {.allocationSize = needs.size,
             .memoryTypeIndex =
                 MemoryType(needs.memoryTypeBits, vk::MemoryPropertyFlagBits::eHostVisible |
                                                      vk::MemoryPropertyFlagBits::eHostCoherent)}));
        const auto bound = device->bindBufferMemory(*staging, *staging_memory, 0);
        assert(bound == vk::Result::eSuccess);
        mapped = Check(device->mapMemory(*staging_memory, 0, VK_WHOLE_SIZE));
        Begin();
        std::array<vk::ImageMemoryBarrier, 7> to_general;
        const std::array<const Image*, 7> images{&colour, &copy,   &marks, &means,
                                                 &depth,  &normal, &motion};
        for (u32 i = 0; i < images.size(); ++i) {
            to_general[i] = {.dstAccessMask = vk::AccessFlagBits::eMemoryRead |
                                              vk::AccessFlagBits::eMemoryWrite,
                             .oldLayout = vk::ImageLayout::eUndefined,
                             .newLayout = vk::ImageLayout::eGeneral,
                             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                             .image = *images[i]->image,
                             .subresourceRange = Range};
        }
        command.pipelineBarrier(vk::PipelineStageFlagBits::eTopOfPipe,
                                vk::PipelineStageFlagBits::eAllCommands, {}, {}, {}, to_general);
        Submit();
    }

    void Upload(const Image& image, const void* data, size_t bytes) {
        std::memcpy(mapped, data, bytes);
        Begin();
        const vk::BufferImageCopy region{
            .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .imageExtent = {width, height, 1}};
        command.copyBufferToImage(*staging, *image.image, vk::ImageLayout::eGeneral, region);
        Barrier();
        Submit();
    }

    void Begin() {
        const auto begun = command.begin(vk::CommandBufferBeginInfo{});
        assert(begun == vk::Result::eSuccess);
    }

    /// Everything before is done before anything after starts.
    void Barrier() {
        const auto all = vk::AccessFlagBits::eMemoryRead | vk::AccessFlagBits::eMemoryWrite;
        const vk::MemoryBarrier barrier{.srcAccessMask = all, .dstAccessMask = all};
        command.pipelineBarrier(vk::PipelineStageFlagBits::eAllCommands,
                                vk::PipelineStageFlagBits::eAllCommands, {}, barrier, {}, {});
    }

    void Submit() {
        const auto ended = command.end();
        assert(ended == vk::Result::eSuccess);
        const auto submitted = queue.submit(
            vk::SubmitInfo{.commandBufferCount = 1, .pCommandBuffers = &command});
        assert(submitted == vk::Result::eSuccess);
        const auto idle = queue.waitIdle();
        assert(idle == vk::Result::eSuccess);
    }

    vk::UniqueInstance instance;
    vk::PhysicalDevice physical;
    vk::UniqueDevice device;
    vk::Queue queue;
    vk::UniqueCommandPool pool;
    vk::CommandBuffer command;
    vk::UniqueQueryPool queries;
    double period_ns = 1.0;
    bool timed = false;
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;
    vk::UniqueSampler sampler;
    u32 width = 0, height = 0;
    Image colour, copy, marks, means, depth, normal, motion;
    vk::UniqueBuffer staging;
    vk::UniqueDeviceMemory staging_memory;
    void* mapped = nullptr;
};

Rgb Colour(const Half4& pixel) {
    return {FromHalf(pixel[0]), FromHalf(pixel[1]), FromHalf(pixel[2])};
}

float Luminance(const Half4& pixel) {
    const Rgb c = Colour(pixel);
    return 0.2126f * c[0] + 0.7152f * c[1] + 0.0722f * c[2];
}

bool Same(const Half4& a, const Half4& b) {
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2];
}

/// Two pixels show the same stroke: every channel within a tenth of the larger.
bool Alike(const Half4& a, const Half4& b) {
    const Rgb x = Colour(a), y = Colour(b);
    for (int c = 0; c < 3; ++c) {
        if (std::abs(x[c] - y[c]) > 0.1f * std::max(x[c], y[c]) + 1e-4f) {
            return false;
        }
    }
    return true;
}

bool failed = false;

void Expect(bool ok, const char* what) {
    std::printf("%s: %s\n", ok ? "ok" : "FAILED", what);
    failed |= !ok;
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
bool Project(const Lens& lens, const Camera& camera, const Vec3& world, int& x, int& y,
             double& z) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    z = Dot(rel, camera.Forward());
    if (z <= Near) {
        return false;
    }
    const double px = (Dot(rel, camera.Right()) * lens.xs / z * 0.5 + 0.5) * lens.width +
                      camera.jitter[0];
    const double py = (Dot(rel, camera.Down()) * lens.ys / z * 0.5 + 0.5) * lens.height +
                      camera.jitter[1];
    x = int(std::floor(px));
    y = int(std::floor(py));
    return x >= 0 && y >= 0 && x < int(lens.width) && y < int(lens.height);
}

struct Share {
    u32 alike = 0, of = 0;
    double Part() const {
        return of ? double(alike) / of : 0.0;
    }
};

/// As strokeOctaves of paint_common.glsl: the smaller of the two stroke sizes a point takes,
/// and the share of the larger one; a point that takes only the larger one counts as taking the
/// next size alone.
struct Sizes {
    int octave;
    double upper_share;
    bool operator==(const Sizes& other) const {
        return octave == other.octave && std::abs(upper_share - other.upper_share) < 1e-3;
    }
};

/// `normal`: the surface's; its largest part names the plane the strokes lie in (strokePlanes).
Sizes SizesAt(const Lens& lens, const Vec3& world, const std::array<u8, 4>& normal,
              const Camera& camera, double cell_px) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    const double distance = std::sqrt(Dot(rel, rel));
    int plane = 0;
    for (int k = 1; k < 3; ++k) {
        if (std::abs(int(normal[k]) - 128) > std::abs(int(normal[plane]) - 128)) {
            plane = k;
        }
    }
    const double lean = std::max(std::abs(rel[plane]) / distance, 0.04);
    const double level =
        std::log2(cell_px / std::sqrt(lean) * 2.0 * distance / (lens.ys * lens.height));
    const double part = std::clamp((level - std::floor(level) - 0.25) / 0.5, 0.0, 1.0);
    const double share = part * part * (3.0 - 2.0 * part);
    return share >= 1.0 ? Sizes{int(std::floor(level)) + 1, 0.0}
                        : Sizes{int(std::floor(level)), share};
}

struct Shares {
    Share all;   ///< every pixel a stroke painted
    Share inner; ///< those with the same stroke on all eight pixels around them
    std::array<Share, 6> inner_of{}; ///< `inner` by Surface
};

/// Of the pixels of `a` that a stroke painted and that `b` sees too (the same surface at the
/// same depth), the share that shows the same stroke in `b` where the point lies there
/// (`follow`), or at the same place of the screen (not `follow`: what strokes stuck to the
/// screen would give). A point of `a` falls between the pixels of `b`, so at a stroke's edge
/// the nearest pixel of `b` may show the stroke beside it: the pixels inside a stroke tell
/// whether the strokes moved with their surfaces. A point the camera came nearer to, or went
/// away from, far enough to mix its two sizes of stroke otherwise is left out: there the look
/// crosses over from one size to the next, which is meant. `cell_px`: the frames' stroke cell.
Shares Compare(const Lens& lens, const Scene& a, const std::vector<Half4>& out_a,
               const Camera& camera_a, const Camera& camera_b, const Scene& b,
               const std::vector<Half4>& out_b, double cell_px, bool follow) {
    Shares shares;
    for (u32 y = 1; y + 1 < lens.height; ++y) {
        for (u32 x = 1; x + 1 < lens.width; ++x) {
            const u32 i = y * lens.width + x;
            if (a.surface[i] == Sky || Same(out_a[i], a.colour[i])) {
                continue;
            }
            int bx = int(x), by = int(y);
            double z = 0.0;
            if (follow && !Project(lens, camera_b, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * lens.width + u32(bx);
            if (b.surface[j] != a.surface[i]) {
                continue;
            }
            if (follow && std::abs(Near / (1.0 - double(b.depth[j])) - z) > 0.02 * z) {
                continue;
            }
            if (SizesAt(lens, a.world[i], a.normal[i], camera_a, cell_px) !=
                SizesAt(lens, a.world[i], a.normal[i], camera_b, cell_px)) {
                continue;
            }
            bool inner = true;
            for (int k = 0; k < 9; ++k) {
                inner &= Alike(out_a[i], out_a[i + (k / 3 - 1) * int(lens.width) + k % 3 - 1]);
            }
            const bool alike = Alike(out_a[i], out_b[j]);
            ++shares.all.of;
            shares.all.alike += alike;
            shares.inner.of += inner;
            shares.inner.alike += inner && alike;
            shares.inner_of[a.surface[i]].of += inner;
            shares.inner_of[a.surface[i]].alike += inner && alike;
        }
    }
    return shares;
}

/// How two lists of numbers go together, -1..1.
struct Together {
    double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    u32 n = 0;
    void Add(double x, double y) {
        sx += x, sy += y, sxx += x * x, syy += y * y, sxy += x * y;
        ++n;
    }
    double Value() const {
        const double vx = sxx - sx * sx / n, vy = syy - sy * sy / n;
        return vx > 0 && vy > 0 ? (sxy - sx * sy / n) / std::sqrt(vx * vy) : 0.0;
    }
};

/// What the look did to a pixel's brightness, as a ratio less 1.
double Change(const Scene& scene, const std::vector<Half4>& out, u32 i) {
    return double(Luminance(out[i])) / std::max(double(Luminance(scene.colour[i])), 1e-9) - 1.0;
}

/// Whether what the look changed in frame `a` is found again in frame `b`: where each point of
/// `a` lies in `b` (`follow`), and at the same place of the screen (`stuck`). Strokes that stay
/// on their surfaces give a high first number and a low second one. Without the ball: it gets no
/// strokes.
void LookTogether(const Lens& lens, const Scene& a, const std::vector<Half4>& out_a,
                  const Camera& camera_b, const Scene& b, const std::vector<Half4>& out_b,
                  Together& follow, Together& stuck) {
    for (u32 y = 0; y < lens.height; ++y) {
        for (u32 x = 0; x < lens.width; ++x) {
            const u32 i = y * lens.width + x;
            if (a.surface[i] == Sky || a.surface[i] == Ball) {
                continue;
            }
            int bx = 0, by = 0;
            double z = 0.0;
            if (!Project(lens, camera_b, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * lens.width + u32(bx);
            if (b.surface[j] != a.surface[i] || b.surface[i] != a.surface[i] ||
                std::abs(Near / (1.0 - double(b.depth[j])) - z) > 0.02 * z) {
                continue;
            }
            const double change = Change(a, out_a, i);
            follow.Add(change, Change(b, out_b, j));
            stuck.Add(change, Change(b, out_b, i));
        }
    }
}

u8 Display(float linear) {
    return u8(std::lround(std::pow(std::clamp(linear * 1.6f, 0.0f, 1.0f), 1.0f / 2.2f) * 255.0f));
}

/// Rows of 24-bit pixels (blue, green, red), top row first, as a BMP.
bool WriteBmp(const std::string& path, u32 width, u32 height, const std::vector<u8>& rows) {
    const u32 stride = (width * 3 + 3) & ~3u;
    u8 header[54] = {'B', 'M'};
    const auto put = [&](int at, u32 value) { std::memcpy(header + at, &value, 4); };
    put(2, u32(sizeof(header)) + stride * height);
    put(10, sizeof(header));
    put(14, 40);
    put(18, width);
    put(22, height);
    put(26, 1 | 24 << 16);
    put(34, stride * height);
    std::ofstream file(path, std::ios::binary);
    file.write(reinterpret_cast<const char*>(header), sizeof(header));
    std::vector<u8> line(stride);
    for (u32 y = height; y-- > 0;) {
        std::memcpy(line.data(), &rows[size_t(y) * width * 3], size_t(width) * 3);
        file.write(reinterpret_cast<const char*>(line.data()), stride);
    }
    return file.good();
}

/// Four pictures of one size as one BMP, two beside two.
void WritePicture(const char* path, u32 w, u32 h,
                  const std::array<const std::vector<Half4>*, 4>& parts) {
    const u32 width = w * 2, height = h * 2;
    std::vector<u8> rows(size_t(width) * height * 3);
    for (u32 y = 0; y < height; ++y) {
        for (u32 x = 0; x < width; ++x) {
            const auto& part = *parts[(y / h) * 2 + x / w];
            const Rgb c = Colour(part[(y % h) * w + x % w]);
            u8* out = &rows[(size_t(y) * width + x) * 3];
            out[0] = Display(c[2]);
            out[1] = Display(c[1]);
            out[2] = Display(c[0]);
        }
    }
    Expect(WriteBmp(path, width, height, rows), "the picture is written");
}

// --- the look on a picture ---

float FromSrgb(u8 value) {
    const float v = value / 255.0f;
    return v <= 0.04045f ? v / 12.92f : std::pow((v + 0.055f) / 1.055f, 2.4f);
}

u8 ToSrgb(float linear) {
    const float v = std::clamp(linear, 0.0f, 1.0f);
    return u8(std::lround((v <= 0.0031308f ? v * 12.92f : 1.055f * std::pow(v, 1 / 2.4f) - 0.055f) *
                          255.0f));
}

/// Linear sRGB as Oklab (L, a, b).
std::array<double, 3> Oklab(const Rgb& c) {
    const double l = std::cbrt(0.4122214708 * c[0] + 0.5363325363 * c[1] + 0.0514459929 * c[2]);
    const double m = std::cbrt(0.2119034982 * c[0] + 0.6806995451 * c[1] + 0.1073969566 * c[2]);
    const double s = std::cbrt(0.0883024619 * c[0] + 0.2817188376 * c[1] + 0.6299787005 * c[2]);
    return {0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s};
}

/// A 24-bit BMP's pixels as linear colours, top row first; empty if it is not one.
std::vector<Rgb> ReadBmp(const char* path, u32& width, u32& height) {
    std::ifstream file(path, std::ios::binary);
    u8 header[54];
    file.read(reinterpret_cast<char*>(header), sizeof(header));
    u32 offset, w, h;
    u16 bits;
    std::memcpy(&offset, header + 10, 4);
    std::memcpy(&w, header + 18, 4);
    std::memcpy(&h, header + 22, 4);
    std::memcpy(&bits, header + 28, 2);
    if (!file.good() || header[0] != 'B' || header[1] != 'M' || bits != 24 || int(h) <= 0) {
        return {};
    }
    width = w;
    height = h;
    const u32 stride = (w * 3 + 3) & ~3u;
    std::vector<u8> line(stride);
    std::vector<Rgb> pixels(size_t(w) * h);
    file.seekg(offset);
    for (u32 y = h; y-- > 0;) {
        file.read(reinterpret_cast<char*>(line.data()), stride);
        for (u32 x = 0; x < w; ++x) {
            pixels[size_t(y) * w + x] = {FromSrgb(line[x * 3 + 2]), FromSrgb(line[x * 3 + 1]),
                                         FromSrgb(line[x * 3])};
        }
    }
    return file.good() ? pixels : std::vector<Rgb>{};
}

/// The picture as a scene: a camera 1.6 m above a floor looks a little down at a wall 9 m
/// away, and the picture lies on both. `exposure`: the scene is that much brighter than the
/// picture, as a game's scene before its exposure is some factor away from what is shown.
/// The parts of the picture that the game draws after the strokes (the HUD: `hud`, rectangles
/// in shares of the picture) count as sky, which is not painted.
Scene PictureScene(const Lens& lens, const Camera& camera, const std::vector<Rgb>& picture,
                   float exposure, std::span<const std::array<float, 4>> hud) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    const Vec3 r = camera.Right(), dn = camera.Down(), f = camera.Forward();
    for (u32 y = 0; y < h; ++y) {
        for (u32 x = 0; x < w; ++x) {
            const u32 i = y * w + x;
            const double nx = (x + 0.5) / w * 2.0 - 1.0, ny = (y + 0.5) / h * 2.0 - 1.0;
            const Vec3 dir = Add(Add(f, r, nx / lens.xs), dn, ny / lens.ys);
            const double wall = (9.0 - camera.pos[2]) / dir[2];
            const double floor = dir[1] < 0.0 ? -camera.pos[1] / dir[1] : 1e30;
            const bool on_floor = floor < wall;
            bool in_hud = false;
            for (const auto& box : hud) {
                in_hud |= (x + 0.5f) / w >= box[0] && (x + 0.5f) / w < box[2] &&
                          (y + 0.5f) / h >= box[1] && (y + 0.5f) / h < box[3];
            }
            const Rgb& c = picture[i];
            scene.colour[i] = {ToHalf(c[0] * exposure), ToHalf(c[1] * exposure),
                               ToHalf(c[2] * exposure), ToHalf(1.0f)};
            scene.depth[i] = in_hud ? 1.0f : float(1.0 - Near / std::min(floor, wall));
            scene.normal[i] = on_floor ? std::array<u8, 4>{128, 255, 128, 255}
                                       : std::array<u8, 4>{128, 128, 0, 255};
        }
    }
    return scene;
}

/// Each 2x2 pixels of a picture as one, the mean of the linear colours.
std::vector<Rgb> Halved(const std::vector<Rgb>& picture, u32 width, u32 height) {
    std::vector<Rgb> half(size_t(width / 2) * (height / 2));
    for (u32 y = 0; y < height / 2; ++y) {
        for (u32 x = 0; x < width / 2; ++x) {
            Rgb sum{};
            for (int k = 0; k < 4; ++k) {
                const Rgb& c = picture[size_t(y * 2 + k / 2) * width + x * 2 + k % 2];
                for (int ch = 0; ch < 3; ++ch) {
                    sum[ch] += c[ch] * 0.25f;
                }
            }
            half[size_t(y) * (width / 2) + x] = sum;
        }
    }
    return half;
}

/// A picture at another height (the width goes with it): every new pixel the mean of the part
/// of the picture it covers.
std::vector<Rgb> Resized(const std::vector<Rgb>& picture, u32 width, u32 height, u32 new_width,
                         u32 new_height) {
    std::vector<Rgb> out(size_t(new_width) * new_height);
    const double sx = double(width) / new_width, sy = double(height) / new_height;
    for (u32 y = 0; y < new_height; ++y) {
        for (u32 x = 0; x < new_width; ++x) {
            const double x0 = x * sx, x1 = (x + 1) * sx, y0 = y * sy, y1 = (y + 1) * sy;
            std::array<double, 3> sum{};
            double weight = 0.0;
            for (u32 v = u32(y0); v < std::min(u32(std::ceil(y1)), height); ++v) {
                const double wy = std::min(y1, v + 1.0) - std::max(y0, double(v));
                for (u32 u = u32(x0); u < std::min(u32(std::ceil(x1)), width); ++u) {
                    const double w = wy * (std::min(x1, u + 1.0) - std::max(x0, double(u)));
                    const Rgb& c = picture[size_t(v) * width + u];
                    for (int ch = 0; ch < 3; ++ch) {
                        sum[ch] += c[ch] * w;
                    }
                    weight += w;
                }
            }
            out[size_t(y) * new_width + x] = {float(sum[0] / weight), float(sum[1] / weight),
                                              float(sum[2] / weight)};
        }
    }
    return out;
}

bool WriteScene(const std::string& path, const Lens& lens, const std::vector<Half4>& pixels,
                float exposure) {
    std::vector<u8> rows(size_t(lens.width) * lens.height * 3);
    for (size_t i = 0; i < pixels.size(); ++i) {
        const Rgb c = Colour(pixels[i]);
        rows[i * 3 + 0] = ToSrgb(c[2] / exposure);
        rows[i * 3 + 1] = ToSrgb(c[1] / exposure);
        rows[i * 3 + 2] = ToSrgb(c[0] / exposure);
    }
    return WriteBmp(path, lens.width, lens.height, rows);
}

/// What the look did to the picture's colours: the whole frame's mean, and every block of
/// `block` pixels (64 at 2160 lines, the design's check) that is not near black.
void ReportColours(const char* name, const Lens& lens, const Scene& scene,
                   const std::vector<Half4>& out, float exposure) {
    const u32 block = std::max(lens.height * 64 / 2160, 8u);
    std::array<double, 3> before{}, after{}, lab_before{}, lab_after{};
    u32 changed = 0, painted = 0;
    std::vector<double> light, lightness;
    double frame_luminance = 0.0;
    for (const Half4& pixel : scene.colour) {
        frame_luminance += Luminance(pixel) / exposure;
    }
    frame_luminance /= double(scene.colour.size());
    for (u32 by = 0; by + block <= lens.height; by += block) {
        for (u32 bx = 0; bx + block <= lens.width; bx += block) {
            std::array<double, 3> a{}, b{};
            double la = 0.0, lb = 0.0;
            for (u32 y = by; y < by + block; ++y) {
                for (u32 x = bx; x < bx + block; ++x) {
                    const u32 i = y * lens.width + x;
                    Rgb ca = Colour(scene.colour[i]), cb = Colour(out[i]);
                    for (int ch = 0; ch < 3; ++ch) {
                        ca[ch] /= exposure;
                        cb[ch] /= exposure;
                        a[ch] += ca[ch];
                        b[ch] += cb[ch];
                    }
                    const auto oa = Oklab(ca), ob = Oklab(cb);
                    la += oa[0];
                    lb += ob[0];
                    for (int ch = 0; ch < 3; ++ch) {
                        lab_before[ch] += oa[ch];
                        lab_after[ch] += ob[ch];
                    }
                    painted += scene.depth[i] < 1.0f;
                    changed += std::abs(Luminance(out[i]) - Luminance(scene.colour[i])) >
                               0.01f * Luminance(scene.colour[i]);
                }
            }
            for (int ch = 0; ch < 3; ++ch) {
                before[ch] += a[ch];
                after[ch] += b[ch];
            }
            const double n = double(block) * block;
            const double ya = (0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]) / n;
            const double yb = (0.2126 * b[0] + 0.7152 * b[1] + 0.0722 * b[2]) / n;
            // A block darker than a tenth of the frame's mean: a change there is a large
            // share of nearly nothing.
            if (ya > 0.1 * frame_luminance) {
                light.push_back(std::abs(yb / ya - 1.0) * 100.0);
                lightness.push_back(std::abs(lb / la - 1.0) * 100.0);
            }
        }
    }
    const auto spread = [](std::vector<double>& values, double& mean, double& p95, double& top) {
        std::sort(values.begin(), values.end());
        mean = 0.0;
        for (const double v : values) {
            mean += v;
        }
        mean /= double(values.size());
        p95 = values[values.size() * 95 / 100];
        top = values.back();
    };
    double m1, p1, t1, m2, p2, t2;
    spread(light, m1, p1, t1);
    spread(lightness, m2, p2, t2);
    const double all = double(scene.colour.size());
    std::printf("%s: frame mean linear R %+.2f%% G %+.2f%% B %+.2f%%; mean Oklab L %+.4f a "
                "%+.4f b %+.4f; %.1f%% of the %u painted pixels changed by more than 1%%\n",
                name, (after[0] / before[0] - 1.0) * 100.0, (after[1] / before[1] - 1.0) * 100.0,
                (after[2] / before[2] - 1.0) * 100.0, (lab_after[0] - lab_before[0]) / all,
                (lab_after[1] - lab_before[1]) / all, (lab_after[2] - lab_before[2]) / all,
                100.0 * changed / std::max(painted, 1u), painted);
    std::printf("%s: %zu blocks of %ux%u (those under a tenth of the frame's mean brightness "
                "left out): mean luminance changed by mean %.2f%% p95 %.2f%% max %.2f%%; mean "
                "Oklab L by mean %.2f%% p95 %.2f%% max %.2f%%\n",
                name, light.size(), block, block, m1, p1, t1, m2, p2, t2);
}

int PictureMain(int argc, char** argv) {
    u32 width = 0, height = 0;
    std::vector<Rgb> picture = ReadBmp(argv[2], width, height);
    if (picture.empty() || argc < 4) {
        std::puts("usage: drawn-look-test --picture in.bmp out [2 | lines]   (in.bmp: 24 bits a "
                  "pixel; 2: at half the size; lines: at that height, 1440 for one)");
        return 2;
    }
    if (argc > 4 && std::strcmp(argv[4], "2") == 0) {
        picture = Halved(picture, width, height);
        width /= 2;
        height /= 2;
    } else if (argc > 4 && std::atoi(argv[4]) >= 64) {
        const u32 new_height = u32(std::atoi(argv[4]));
        const u32 new_width = u32(std::lround(double(width) * new_height / height / 2.0)) * 2;
        picture = Resized(picture, width, height, new_width, new_height);
        width = new_width;
        height = new_height;
    }
    const std::string out = argv[3];
    Gpu gpu;
    const Lens lens{width, height};
    const Camera camera{.pos = {0.0, 1.6, 0.0}, .pitch = -0.035};
    // The game's HUD in the design's screenshot, as shares of the picture.
    static constexpr std::array<float, 4> Hud[] = {{0.052f, 0.050f, 0.232f, 0.208f},
                                                   {0.820f, 0.055f, 0.955f, 0.155f},
                                                   {0.872f, 0.012f, 0.995f, 0.034f}};
    const float exposure = 4.0f;
    const Scene scene = PictureScene(lens, camera, picture, exposure, Hud);
    const auto words = [&](float strength, int view) {
        return Words(lens, camera, view, true, false, strength);
    };
    std::printf("picture %ux%u, stroke cells %.1f and %.1f pixels\n", width, height,
                words(0.6f, 0).cell_bold, words(0.6f, 0).cell_fine);
    const auto after = gpu.Run(scene, words(0.6f, Look::ViewOff));
    const auto full = gpu.Run(scene, words(1.0f, Look::ViewOff));
    const auto sizes = gpu.Run(scene, words(0.6f, Look::ViewStrokes));
    ReportColours("strength 0.6", lens, scene, after, exposure);
    ReportColours("strength 1.0", lens, scene, full, exposure);
    for (const float times : {16.0f, 1.5f}) {
        // The same picture brighter, by a whole number of stops and by a part of one: the same
        // look.
        const Scene bright = PictureScene(lens, camera, picture, exposure * times, Hud);
        const auto again = gpu.Run(bright, words(0.6f, Look::ViewOff));
        u32 off = 0;
        for (size_t i = 0; i < after.size(); ++i) {
            off += std::abs(Luminance(again[i]) / times - Luminance(after[i])) >
                   0.02f * Luminance(after[i]) + 1e-4f;
        }
        std::printf("%.1f times as bright: %u of %zu pixels differ by more than 2%% from the "
                    "look on the picture as it is\n", times, off, after.size());
    }
    if (gpu.Timed()) {
        const u32 repeats = width * height > 3000000 ? 50 : 150;
        const Times look = gpu.Measure(scene, words(0.6f, Look::ViewOff), repeats);
        const Times full_look = gpu.Measure(scene, words(1.0f, Look::ViewOff), repeats);
        const Times test_view = gpu.Measure(scene, words(0.6f, Look::ViewBold), repeats);
        std::printf("GPU time at %ux%u (each part %u times in a row, best of 3): copy, marks "
                    "and levels %.3f ms, strokes %.3f ms (at strength 1: %.3f ms; the test "
                    "view's: %.3f ms), colour lock %.3f ms; the look together %.3f ms\n",
                    width, height, repeats, look.masks, look.strokes, full_look.strokes,
                    test_view.strokes, look.lock, look.masks + look.strokes + look.lock);
    }
    const bool written = WriteScene(out + "_before.bmp", lens, scene.colour, exposure) &&
                         WriteScene(out + "_after.bmp", lens, after, exposure) &&
                         WriteScene(out + "_full.bmp", lens, full, exposure) &&
                         WriteScene(out + "_sizes.bmp", lens, sizes, exposure);
    std::puts(written ? "pictures written" : "FAILED to write the pictures");
    return written ? 0 : 1;
}
} // namespace

int main(int argc, char** argv) {
    if (argc > 2 && std::strcmp(argv[1], "--picture") == 0) {
        return PictureMain(argc, argv);
    }
    Gpu gpu;
    const Lens lens{960, 540};
    const u32 n = lens.width * lens.height;
    // Looks straight at the back wall, ten metres away: every pixel of that wall is as deep.
    const Camera straight{.pos = {0.3, 1.6, -1.0}};
    const Scene scene = MakeScene(lens, straight, Paint::Plain);
    const auto bold = gpu.Run(scene, Words(lens, straight, Look::ViewBold));

    for (const int view : {int(Look::ViewOff), int(Look::ViewStrokes), int(Look::ViewFine),
                           int(Look::ViewBold)}) {
        const auto out = gpu.Run(scene, Words(lens, straight, view));
        u32 sky = 0, sky_changed = 0, alpha_changed = 0, surface = 0, painted = 0;
        for (u32 i = 0; i < n; ++i) {
            alpha_changed += out[i][3] != scene.colour[i][3];
            if (scene.surface[i] == Sky) {
                ++sky;
                sky_changed += !Same(out[i], scene.colour[i]);
            } else {
                ++surface;
                painted += !Same(out[i], scene.colour[i]);
            }
        }
        std::printf("%s %d: %u sky pixels, %u changed; %u alphas changed; %.1f%% of the %u "
                    "surface pixels changed\n",
                    view ? "test view" : "the look, view", view, sky, sky_changed, alpha_changed,
                    100.0 * painted / surface, surface);
        Expect(sky > n / 20 && sky_changed == 0, "the sky is not painted");
        Expect(alpha_changed == 0, "the alpha is kept");
        Expect(painted > surface * 0.6, "strokes cover most of the surfaces");
        if (view == Look::ViewOff) {
            // The view kept for the ink lines shows the look, as no view does.
            Expect(gpu.Run(scene, Words(lens, straight, Look::ViewInk)) == out,
                   "view 3 (kept for the ink lines) shows the look");
        }
    }
    {
        // The jitter moved by whole pixels: the same picture, moved by as much.
        Camera moved = straight;
        moved.jitter = {3.0f, -2.0f};
        const Scene scene_b = MakeScene(lens, moved, Paint::Plain);
        const auto out = gpu.Run(scene_b, Words(lens, moved, Look::ViewBold));
        u32 compared = 0, same = 0;
        for (u32 y = 2; y < lens.height; ++y) {
            for (u32 x = 0; x + 3 < lens.width; ++x) {
                const u32 i = y * lens.width + x, j = (y - 2) * lens.width + x + 3;
                if (scene.surface[i] != Sky && scene.surface[j] == scene.surface[i]) {
                    ++compared;
                    same += Alike(bold[i], out[j]);
                }
            }
        }
        std::printf("jitter (3, -2): %u of %u pixels show the same stroke 3 right and 2 up "
                    "(%.3f%%)\n", same, compared, 100.0 * same / compared);
        Expect(same > compared * 0.995, "a jitter of whole pixels moves the strokes with the scene");
    }
    {
        // The camera steps sideways, then up, by what moves the back wall a whole number of
        // pixels: the wall's strokes must move with the wall, pixel for pixel.
        const double z = 9.0 - straight.pos[2];
        const double cell_px = Words(lens, straight, Look::ViewBold).cell_bold;
        for (int axis = 0; axis < 2; ++axis) {
            const int pixels = axis == 0 ? 16 : 9;
            Camera moved = straight;
            moved.pos[axis] += axis == 0 ? pixels * 2.0 * z / (lens.xs * lens.width)
                                         : pixels * 2.0 * z / (lens.ys * lens.height);
            const Scene scene_b = MakeScene(lens, moved, Paint::Plain);
            const auto out = gpu.Run(scene_b, Words(lens, moved, Look::ViewBold));
            u32 compared = 0, same = 0, stuck = 0;
            for (u32 y = 0; y + (axis == 1 ? pixels : 0) < lens.height; ++y) {
                for (u32 x = axis == 0 ? pixels : 0; x < lens.width; ++x) {
                    const u32 i = y * lens.width + x;
                    const u32 j = axis == 0 ? i - pixels : i + pixels * lens.width;
                    // A point whose two sizes of stroke mix otherwise from the moved camera
                    // (the wall is seen a little less squarely from there) is left out.
                    if (scene.surface[i] == BackWall && scene_b.surface[j] == BackWall &&
                        scene_b.surface[i] == BackWall && !Same(bold[i], scene.colour[i]) &&
                        SizesAt(lens, scene.world[i], scene.normal[i], straight, cell_px) ==
                            SizesAt(lens, scene.world[i], scene.normal[i], moved, cell_px)) {
                        ++compared;
                        same += Alike(bold[i], out[j]);
                        stuck += Alike(bold[i], out[i]);
                    }
                }
            }
            std::printf("camera %.4f m %s: the back wall moved %d pixels; of %u painted pixels "
                        "%.3f%% show the same stroke there, %.1f%% at the same place of the "
                        "screen\n",
                        std::abs(moved.pos[axis] - straight.pos[axis]),
                        axis == 0 ? "to the right" : "up", pixels, compared,
                        100.0 * same / compared, 100.0 * stuck / compared);
            Expect(compared > 20000 && same > compared * 0.995 && stuck < compared * 0.3,
                   "the wall's strokes move with the wall");
        }
    }
    {
        // The normal from the depth (a frame painted right before the upscaler) picks the
        // same strokes on flat surfaces as the G-buffer's normal.
        const auto out = gpu.Run(scene, Words(lens, straight, Look::ViewBold, false));
        u32 compared = 0, same = 0;
        for (u32 i = 0; i < n; ++i) {
            if (scene.surface[i] == Floor || scene.surface[i] == BackWall ||
                scene.surface[i] == SideWall) {
                ++compared;
                same += Alike(bold[i], out[i]);
            }
        }
        std::printf("normals from the depth: %.2f%% of %u flat pixels as with the G-buffer's\n",
                    100.0 * same / compared, compared);
        Expect(same > compared * 0.97, "the depth's normal gives the same strokes on flat surfaces");
    }
    {
        // What moves by itself is marked: its strokes are grey in the test view. (A pixel
        // that one of its planes has no stroke for keeps a part of the ball's own colour.)
        const auto out = gpu.Run(scene, Words(lens, straight, Look::ViewBold, true, true));
        const auto colourful = [](const Half4& pixel) {
            const Rgb c = Colour(pixel);
            return std::max({c[0], c[1], c[2]}) - std::min({c[0], c[1], c[2]});
        };
        u32 ball = 0, grey = 0, grey_before = 0, tinted = 0, elsewhere = 0;
        for (u32 i = 0; i < n; ++i) {
            if (scene.surface[i] != Ball) {
                elsewhere += !Same(out[i], bold[i]);
            } else if (!Same(out[i], scene.colour[i])) {
                ++ball;
                grey += out[i][0] == out[i][1] && out[i][1] == out[i][2];
                grey_before += bold[i][0] == bold[i][1] && bold[i][1] == bold[i][2];
                tinted += colourful(out[i]) > colourful(scene.colour[i]) + 1e-3f;
            }
        }
        std::printf("object motion: %u painted pixels on the ball, %u grey (%u without the "
                    "motion image), %u more colourful than the ball; %u pixels changed "
                    "elsewhere\n", ball, grey, grey_before, tinted, elsewhere);
        Expect(ball > 1000 && grey > ball * 0.9 && tinted == 0 && grey_before < ball / 10 &&
                   elsewhere == 0,
               "surfaces that move by themselves are told apart");
    }
    // A camera that turns and tilts, then one that walks too, with jitters under a pixel: no
    // pixel falls on a pixel, so strokes are compared where each point of the first frame lies
    // in the second. Turning changes nothing about a point's strokes. A walking camera comes
    // nearer to some points: where that changes how a point mixes its two sizes of stroke
    // the point is not compared.
    const Lens large{1920, 1080};
    const Camera first{.pos = {0.3, 1.6, -1.0}, .yaw = 0.10, .pitch = -0.06, .jitter = {0.21f, -0.37f}};
    const Camera turned{.pos = first.pos, .yaw = 0.02, .pitch = -0.10, .jitter = {-0.42f, 0.13f}};
    const Camera walked{.pos = {0.75, 1.68, -0.55}, .yaw = 0.02, .pitch = -0.10,
                        .jitter = {-0.42f, 0.13f}};
    for (const int view : {int(Look::ViewBold), int(Look::ViewFine)}) {
        const Scene a = MakeScene(large, first, Paint::Plain);
        const auto words = Words(large, first, view);
        const double cell_px = view == Look::ViewFine ? words.cell_fine : words.cell_bold;
        const auto out_a = gpu.Run(a, words);
        for (const Camera* second : {&turned, &walked}) {
            const Scene b = MakeScene(large, *second, Paint::Plain);
            const auto out_b = gpu.Run(b, Words(large, *second, view));
            const Shares follow = Compare(large, a, out_a, first, *second, b, out_b, cell_px, true);
            const Shares stuck = Compare(large, a, out_a, first, *second, b, out_b, cell_px, false);
            const bool walks = second == &walked;
            std::printf("camera turned%s, test view %d at 1920x1080: where the point lies in "
                        "the second frame %.1f%% of %u pixels inside a stroke show the same "
                        "stroke (%.1f%% of all %u painted pixels); at the same place of the "
                        "screen %.1f%% (%.1f%%)\n",
                        walks ? " and walked" : "", view, 100.0 * follow.inner.Part(),
                        follow.inner.of, 100.0 * follow.all.Part(), follow.all.of,
                        100.0 * stuck.inner.Part(), 100.0 * stuck.all.Part());
            std::printf("  inside a stroke, by surface: floor %.1f%% of %u, back wall %.1f%% of "
                        "%u, side wall %.1f%% of %u, column %.1f%% of %u, ball %.1f%% of %u\n",
                        100.0 * follow.inner_of[Floor].Part(), follow.inner_of[Floor].of,
                        100.0 * follow.inner_of[BackWall].Part(), follow.inner_of[BackWall].of,
                        100.0 * follow.inner_of[SideWall].Part(), follow.inner_of[SideWall].of,
                        100.0 * follow.inner_of[Column].Part(), follow.inner_of[Column].of,
                        100.0 * follow.inner_of[Ball].Part(), follow.inner_of[Ball].of);
            Expect(follow.inner.of > 20000 && follow.inner.Part() > 0.99 &&
                       stuck.inner.Part() < 0.1,
                   "the strokes stay on their surfaces while the camera moves");
        }
    }
    {
        // Another render size (another upscaler mode): the strokes keep their share of the
        // picture, so a pixel of the small frame shows the stroke of the large frame's pixel
        // at the same place.
        const Scene big = MakeScene(large, straight, Paint::Plain);
        const auto out = gpu.Run(big, Words(large, straight, Look::ViewBold));
        u32 compared = 0, same = 0;
        for (u32 y = 0; y < lens.height; ++y) {
            for (u32 x = 0; x < lens.width; ++x) {
                const u32 i = y * lens.width + x, j = y * 2 * large.width + x * 2;
                if (scene.surface[i] != Sky && big.surface[j] == scene.surface[i] &&
                    !Same(bold[i], scene.colour[i])) {
                    ++compared;
                    same += Alike(bold[i], out[j]);
                }
            }
        }
        std::printf("960x540 against 1920x1080: %.1f%% of %u painted pixels show the same "
                    "stroke\n", 100.0 * same / compared, compared);
        Expect(same > compared * 0.7, "the strokes are the same at another render size");
    }

    // --- the look itself (no test view), on the lit scene with grit ---
    const Scene grit = MakeScene(large, first, Paint::Grit);
    const u32 pixels = large.width * large.height;
    for (const float strength : {0.6f, 1.0f}) {
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff, true, false, strength));
        // Every surface keeps its mean colour; the grit between neighbouring pixels of a
        // surface (how far their brightness is apart, in stops) gets less.
        std::array<std::array<double, 3>, 6> before{}, after{};
        std::array<double, 6> rough_before{}, rough_after{};
        std::array<u32, 6> count{}, pairs{};
        u32 unchanged_sky = 0, sky = 0, alpha_changed = 0;
        for (u32 i = 0; i < pixels; ++i) {
            const Surface s = grit.surface[i];
            alpha_changed += out[i][3] != grit.colour[i][3];
            if (s == Sky) {
                ++sky;
                unchanged_sky += Same(out[i], grit.colour[i]);
                continue;
            }
            const Rgb a = Colour(grit.colour[i]), b = Colour(out[i]);
            for (int ch = 0; ch < 3; ++ch) {
                before[s][ch] += a[ch];
                after[s][ch] += b[ch];
            }
            ++count[s];
            if (i % large.width + 1 < large.width && grit.surface[i + 1] == s) {
                rough_before[s] += std::abs(std::log2(Luminance(grit.colour[i]) /
                                                      Luminance(grit.colour[i + 1])));
                rough_after[s] += std::abs(std::log2(Luminance(out[i]) / Luminance(out[i + 1])));
                ++pairs[s];
            }
        }
        double worst = 0.0, least_calmed = 1.0;
        static constexpr const char* Names[] = {"sky", "floor", "back wall", "side wall", "column",
                                                "ball"};
        std::printf("the look at strength %.1f on the lit scene with grit, 1920x1080:\n", strength);
        for (int s = Floor; s <= Ball; ++s) {
            double off = 0.0;
            for (int ch = 0; ch < 3; ++ch) {
                off = std::max(off, std::abs(after[s][ch] / before[s][ch] - 1.0));
            }
            worst = std::max(worst, off);
            const double calmed = rough_after[s] / rough_before[s];
            least_calmed = std::min(least_calmed, 1.0 - calmed);
            std::printf("  %s: %u pixels, mean colour R %+.2f%% G %+.2f%% B %+.2f%%; grit "
                        "between neighbours %.3f -> %.3f stops (%.0f%% less)\n",
                        Names[s], count[s], (after[s][0] / before[s][0] - 1.0) * 100.0,
                        (after[s][1] / before[s][1] - 1.0) * 100.0,
                        (after[s][2] / before[s][2] - 1.0) * 100.0, rough_before[s] / pairs[s],
                        rough_after[s] / pairs[s], (1.0 - calmed) * 100.0);
        }
        Expect(worst < 0.01, "every surface keeps its mean colour within 1%");
        Expect(least_calmed > 0.25 * strength, "the grit is flattened on every surface");
        Expect(sky > 0 && unchanged_sky == sky && alpha_changed == 0,
               "the look leaves the sky and the alpha alone");
    }
    {
        // What the look changes stays on the surfaces while the camera turns and walks. On
        // the scene without grit: a speck of grit is smaller than a pixel far away, the two
        // frames see other specks in a pixel, and what the look takes away would differ by that.
        const auto words = [&](const Camera& camera) {
            return Words(large, camera, Look::ViewOff, true, false, 1.0f);
        };
        const Scene lit = MakeScene(large, first, Paint::Lit);
        const auto out_a = gpu.Run(lit, words(first));
        for (const Camera* second : {&turned, &walked}) {
            const Scene b = MakeScene(large, *second, Paint::Lit);
            const auto out_b = gpu.Run(b, words(*second));
            Together follow, stuck;
            LookTogether(large, lit, out_a, *second, b, out_b, follow, stuck);
            std::printf("the look, camera turned%s: what it changed in a pixel's brightness "
                        "goes together with the change where the point lies in the second "
                        "frame by %.3f, with the change at the same place of the screen by "
                        "%.3f (%u points; 1: the same, 0: unrelated)\n",
                        second == &walked ? " and walked" : "", follow.Value(), stuck.Value(),
                        follow.n);
            Expect(follow.n > 200000 && follow.Value() > 0.8 && stuck.Value() < 0.3,
                   "what the look changes stays on the surfaces while the camera moves");
        }
    }
    for (const float times : {8.0f, 1.5f}) {
        // Another exposure: the scene eight times as bright gets the same look, and so does
        // one brighter by a part of a stop (no step of the look lies at a brightness of its own).
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff));
        const Scene bright = MakeScene(large, first, Paint::Grit, times);
        const auto out_bright = gpu.Run(bright, Words(large, first, Look::ViewOff));
        u32 off = 0;
        for (u32 i = 0; i < pixels; ++i) {
            off += std::abs(Luminance(out_bright[i]) / times - Luminance(out[i])) >
                   0.01f * Luminance(out[i]);
        }
        std::printf("%.1f times as bright: %u of %u pixels differ by more than 1%%\n", times, off,
                    pixels);
        Expect(off < pixels / 1000, "the look does not depend on how bright the scene is");
    }
    {
        // What counts as black, and what as glowing, is told from the surfaces: not from the
        // sky, however bright, and not from a pixel or two that are off the scale.
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff));
        Scene bright_sky = grit;
        for (u32 i = 0; i < pixels; ++i) {
            if (bright_sky.surface[i] == Sky) {
                bright_sky.colour[i] = {ToHalf(40.0f), ToHalf(50.0f), ToHalf(60.0f),
                                        bright_sky.colour[i][3]};
            }
        }
        Scene spark = grit;
        const u32 at = (large.height * 3 / 4) * large.width + large.width / 2;
        spark.colour[at] = {ToHalf(60000.0f), ToHalf(60000.0f), ToHalf(60000.0f),
                            spark.colour[at][3]};
        const auto out_sky = gpu.Run(bright_sky, Words(large, first, Look::ViewOff));
        const auto out_spark = gpu.Run(spark, Words(large, first, Look::ViewOff));
        // Next to the sky and to the spark the picture differs, and so may the look: the
        // surfaces 150 pixels and more away from either are compared.
        std::vector<u8> near_sky(pixels, 0);
        const int reach = 150;
        for (u32 y = 0; y < large.height; y += 10) {
            for (u32 x = 0; x < large.width; x += 10) {
                if (grit.surface[y * large.width + x] != Sky) {
                    continue;
                }
                for (int v = std::max(int(y) - reach, 0);
                     v < std::min(int(y) + reach, int(large.height)); ++v) {
                    std::memset(&near_sky[size_t(v) * large.width + std::max(int(x) - reach, 0)], 1,
                                size_t(std::min(int(x) + reach, int(large.width)) -
                                       std::max(int(x) - reach, 0)));
                }
            }
        }
        u32 compared = 0, off_sky = 0, far = 0, off_spark = 0;
        for (u32 i = 0; i < pixels; ++i) {
            if (grit.surface[i] == Sky) {
                continue;
            }
            const float was = Luminance(out[i]);
            if (!near_sky[i]) {
                ++compared;
                off_sky += std::abs(Luminance(out_sky[i]) - was) > 0.01f * was;
            }
            const int dx = int(i % large.width) - int(at % large.width);
            const int dy = int(i / large.width) - int(at / large.width);
            if (std::abs(dx) > reach || std::abs(dy) > reach) {
                ++far;
                off_spark += std::abs(Luminance(out_spark[i]) - was) > 0.01f * was;
            }
        }
        std::printf("a sky some 500 times as bright: %u of %u surface pixels away from it differ "
                    "by more than 1%%; one pixel at 60000: %u of %u pixels away from it differ\n",
                    off_sky, compared, off_spark, far);
        Expect(compared > pixels / 4 && off_sky < compared / 1000,
               "a bright sky does not change the look on the surfaces");
        Expect(off_spark < far / 1000, "a pixel off the scale does not change the look elsewhere");
    }
    {
        // Bold or fine is settled for a whole stroke, and stays settled: the same camera with
        // another jitter under a pixel (the next frame of a still camera) takes the same size
        // of stroke at nearly every point, also where the picture is on the line between plain
        // and detailed. Which size a pixel shows is told from the test views: view 1 (the sizes
        // the look mixes) is there as view 4 (all bold), as view 2 (all fine), or between.
        Camera again = first;
        again.jitter = {-0.42f, 0.13f};
        const Scene a = MakeScene(large, first, Paint::Patches);
        const Scene b = MakeScene(large, again, Paint::Patches);
        enum : u8 { None, Bold, Fine, Between };
        const auto sizes = [&](const Scene& s, const Camera& camera) {
            const auto mixed = gpu.Run(s, Words(large, camera, Look::ViewStrokes));
            const auto all_bold = gpu.Run(s, Words(large, camera, Look::ViewBold));
            const auto all_fine = gpu.Run(s, Words(large, camera, Look::ViewFine));
            std::vector<u8> size(pixels, None);
            for (u32 i = 0; i < pixels; ++i) {
                if (s.surface[i] == Sky || Same(mixed[i], s.colour[i])) {
                    continue;
                }
                // A pixel that the bold and the fine view paint alike tells nothing.
                const bool as_bold = Alike(mixed[i], all_bold[i]);
                const bool as_fine = Alike(mixed[i], all_fine[i]);
                size[i] = as_bold && as_fine ? None : as_bold ? Bold : as_fine ? Fine : Between;
            }
            return size;
        };
        const auto size_a = sizes(a, first), size_b = sizes(b, again);
        std::array<u32, 4> count{};
        u32 compared = 0, same = 0, flipped = 0;
        for (u32 i = 0; i < pixels; ++i) {
            ++count[size_a[i]];
            int bx = 0, by = 0;
            double z = 0.0;
            if (size_a[i] == None || !Project(large, again, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * large.width + u32(bx);
            if (b.surface[j] != a.surface[i] || size_b[j] == None) {
                continue;
            }
            ++compared;
            same += size_a[i] == size_b[j];
            flipped += (size_a[i] == Bold && size_b[j] == Fine) ||
                       (size_a[i] == Fine && size_b[j] == Bold);
        }
        const u32 told = count[Bold] + count[Fine] + count[Between];
        std::printf("patches (the picture goes from plain to detailed and back): of %u pixels "
                    "%.1f%% take bold strokes, %.1f%% fine ones, %.1f%% something between. "
                    "Another jitter: %.2f%% of %u points take the same size, %.2f%% went from "
                    "bold to fine or back\n",
                    told, 100.0 * count[Bold] / told, 100.0 * count[Fine] / told,
                    100.0 * count[Between] / told, 100.0 * same / compared, compared,
                    100.0 * flipped / compared);
        Expect(count[Bold] > told / 10 && count[Fine] > told / 10,
               "the patches take bold strokes in places and fine ones in others");
        Expect(same > compared * 0.9 && flipped < compared / 50,
               "bold or fine stays settled from one jitter to the next");
    }
    {
        // A floor with bumps in its normals (a normal map: cobbles), leaning as far as 50
        // degrees: the floor itself is flat, and its strokes stay the floor's.
        Scene bumps = scene;
        u32 floor = 0, leaning = 0;
        for (u32 i = 0; i < n; ++i) {
            if (bumps.surface[i] != Floor) {
                continue;
            }
            ++floor;
            const Vec3& p = bumps.world[i];
            const u32 cell = Hash(u32(int(std::floor(p[0] * 20.0)) + 4096) +
                                  Hash(u32(int(std::floor(p[2] * 20.0)) + 4096)));
            if (cell & 0x100u) {
                ++leaning;
                const double angle = 50.0 * 3.14159265358979 / 180.0;
                const bool along_x = cell & 0x200u;
                const Vec3 normal{along_x ? std::sin(angle) : 0.0, std::cos(angle),
                                  along_x ? 0.0 : std::sin(angle)};
                for (int k = 0; k < 3; ++k) {
                    bumps.normal[i][k] = u8(std::lround((normal[k] * 0.5 + 0.5) * 255.0));
                }
            }
        }
        const auto out = gpu.Run(bumps, Words(lens, straight, Look::ViewBold));
        u32 same = 0;
        for (u32 i = 0; i < n; ++i) {
            same += bumps.surface[i] == Floor && Alike(bold[i], out[i]);
        }
        std::printf("a flat floor with bumps in its normals (%.0f%% of it leaning 50 degrees): "
                    "%.2f%% of %u floor pixels show the stroke they show without the bumps\n",
                    100.0 * leaning / floor, 100.0 * same / floor, floor);
        Expect(same > floor * 0.97, "bumps in the normals do not move a flat surface's strokes");
    }
    {
        // What moves by itself gets no strokes: smoothed by its own share of the strength,
        // and left alone at 0. The ball is plain here: smoothing a flat colour changes nothing
        // but at its rim, where a little of what lies behind it gets in (the small levels of
        // the copy know no silhouettes; the depth test keeps out all but a few per cent).
        const Scene plain = MakeScene(large, first, Paint::Plain);
        const auto with = gpu.Run(plain, Words(large, first, Look::ViewOff, true, true, 1.0f, 1.0f));
        const auto none = gpu.Run(plain, Words(large, first, Look::ViewOff, true, true, 1.0f, 0.0f));
        const auto fixed = gpu.Run(plain, Words(large, first, Look::ViewOff, true, false, 1.0f));
        u32 ball = 0, marked = 0, untouched = 0, stroked = 0;
        double most = 0.0;
        for (u32 i = 0; i < pixels; ++i) {
            if (plain.surface[i] == Ball) {
                ++ball;
                const double change = std::abs(Change(plain, with, i));
                most = std::max(most, change);
                marked += change > 0.02;
                untouched += Same(none[i], plain.colour[i]);
                stroked += std::abs(Change(plain, fixed, i)) > 0.02;
            }
        }
        std::printf("a ball that moves by itself: of %u pixels %u change their brightness by "
                    "more than 2%% (%u when it is not marked as moving), the most %.1f%%; with "
                    "graphics_drawn_look_characters 0, %u are untouched\n",
                    ball, marked, stroked, most * 100.0, untouched);
        Expect(ball > 5000 && marked < ball / 20 && most < 0.1 && stroked > ball / 4 &&
                   untouched == ball,
               "what moves by itself is smoothed, not stroked");
    }
    {
        // A colour that is no number, an endless one and one below 0 stay where they are.
        Scene broken = MakeScene(lens, straight, Paint::Grit);
        const u32 at = (lens.height * 3 / 4) * lens.width + lens.width / 2;
        broken.colour[at] = {0x7e00, 0x7e00, 0x7e00, broken.colour[at][3]};
        broken.colour[at + 40] = {0x7c00, 0x7c00, 0x7c00, broken.colour[at + 40][3]};
        broken.colour[at + 80] = {ToHalf(-2.0f), ToHalf(-2.0f), ToHalf(-2.0f),
                                  broken.colour[at + 80][3]};
        const auto out = gpu.Run(broken, Words(lens, straight, Look::ViewOff, true, false, 1.0f));
        u32 bad = 0;
        for (u32 i = 0; i < n; ++i) {
            const Rgb c = Colour(out[i]);
            bad += i != at && i != at + 40 && i != at + 80 &&
                   !(std::isfinite(c[0]) && std::isfinite(c[1]) && std::isfinite(c[2]) &&
                     c[0] >= 0.0f && c[1] >= 0.0f && c[2] >= 0.0f);
        }
        std::printf("three broken pixels in the scene: %u other pixels are no colour after the "
                    "look\n", bad);
        Expect(bad == 0, "a broken pixel does not spread");
    }
    if (argc > 1) {
        const Lens half{960, 540};
        const Scene lit = MakeScene(half, first, Paint::Grit);
        const auto look = gpu.Run(lit, Words(half, first, Look::ViewOff, true, true, 1.0f));
        const auto mixed = gpu.Run(lit, Words(half, first, Look::ViewStrokes, true, true));
        const auto all_bold = gpu.Run(lit, Words(half, first, Look::ViewBold, true, true));
        WritePicture(argv[1], half.width, half.height, {&lit.colour, &look, &mixed, &all_bold});
    }
    std::puts(failed ? "FAILED: drawn look" : "PASS: drawn look");
    return failed ? 1 : 0;
}
""",
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    S + "bbport_settings.h": [
        (r"""inline constexpr float DofIntensityMin = 0.0f, DofIntensityMax = 3.0f;
""", r"""inline constexpr float DofIntensityMin = 0.0f, DofIntensityMax = 3.0f;
// bbport (r45_drawn-look): the drawn look's keys (graphics_drawn_look_*) that do not run 0..1.
inline constexpr float DrawnLookStrengthDefault = 0.6f;
inline constexpr float DrawnLookStrokeSizeMin = 0.6f, DrawnLookStrokeSizeMax = 1.4f;
inline constexpr float DrawnLookTextureMax = 1.2f;
inline constexpr float DrawnLookOutlinesDefault = 0.35f, DrawnLookCharactersDefault = 0.5f;
inline constexpr float DrawnLookShadowSoftMin = 0.05f, DrawnLookShadowSoftMax = 0.3f,
                       DrawnLookShadowSoftDefault = 0.12f;
inline constexpr int DrawnLookDebugMax = 4; // DrawnLookParams::ViewMax (drawn_look_params.h)
"""),
        (r"""    std::atomic<bool> graphics_rt_far_refit{false};              // BB_RT_REFIT_EVERY=8
""", r"""    std::atomic<bool> graphics_rt_far_refit{false};              // BB_RT_REFIT_EVERY=8
    // bbport (r45_drawn-look): the drawn look, an optional hand-painted look (renderer_vulkan/
    // vk_drawn_look.h). All live. While the switch is off or the strength is 0 nothing of it
    // runs. The renderer reads the switch, strength, stroke_size, texture, characters and debug
    // so far; the others are parsed, clamped and saved for the parts of the look that are not
    // built yet (ink lines, painted shadow edges).
    std::atomic<bool> graphics_drawn_look{false};
    std::atomic<float> graphics_drawn_look_strength{DrawnLookStrengthDefault}; // 0..1; 0: no pass
    std::atomic<float> graphics_drawn_look_stroke_size{1.0f};  // 0.6..1.4, a factor on the strokes' size
    std::atomic<float> graphics_drawn_look_texture{1.0f};      // 0..1.2, the brush's marks in a stroke
    std::atomic<float> graphics_drawn_look_outlines{DrawnLookOutlinesDefault}; // 0..1, ink on characters
    std::atomic<float> graphics_drawn_look_shadow_edges{1.0f}; // 0..1; 0: the game's shadows as they are
    std::atomic<float> graphics_drawn_look_ink_world{0.0f};    // 0..1, ink on the world
    std::atomic<float> graphics_drawn_look_characters{DrawnLookCharactersDefault}; // 0..1, the strength on characters
    std::atomic<float> graphics_drawn_look_shadow_soft{DrawnLookShadowSoftDefault}; // 0.05..0.3
    std::atomic<int> graphics_drawn_look_quality{1};           // 0 low, 1 high
    // 0 the look; 1, 2, 4 the test view: every stroke in a flat colour of its own (sizes as the
    // look mixes them, all fine, all bold); 3 is kept for the ink lines' view.
    std::atomic<int> graphics_drawn_look_debug{0};
    // Why the drawn look cannot run, for the menu; null while it can. Set by the renderer.
    std::atomic<const char*> drawn_look_problem{nullptr};
"""),
    ],
    S + "bbport_settings.cpp": [
        (r"""    } else if (key == "graphics_rt_far_refit") {
        v.graphics_rt_far_refit = ZeroOrOne(key, value, false);
""", r"""    } else if (key == "graphics_rt_far_refit") {
        v.graphics_rt_far_refit = ZeroOrOne(key, value, false);
    } else if (key == "graphics_drawn_look") { // bbport (r45_drawn-look)
        v.graphics_drawn_look = ZeroOrOne(key, value, false);
    } else if (key == "graphics_drawn_look_strength") {
        v.graphics_drawn_look_strength = Clamp(std::isfinite(f) ? f : DrawnLookStrengthDefault, 0.0f, 1.0f);
    } else if (key == "graphics_drawn_look_stroke_size") {
        v.graphics_drawn_look_stroke_size =
            Clamp(std::isfinite(f) ? f : 1.0f, DrawnLookStrokeSizeMin, DrawnLookStrokeSizeMax);
    } else if (key == "graphics_drawn_look_texture") {
        v.graphics_drawn_look_texture = Clamp(std::isfinite(f) ? f : 1.0f, 0.0f, DrawnLookTextureMax);
    } else if (key == "graphics_drawn_look_outlines") {
        v.graphics_drawn_look_outlines = Clamp(std::isfinite(f) ? f : DrawnLookOutlinesDefault, 0.0f, 1.0f);
    } else if (key == "graphics_drawn_look_shadow_edges") {
        v.graphics_drawn_look_shadow_edges = Clamp(std::isfinite(f) ? f : 1.0f, 0.0f, 1.0f);
    } else if (key == "graphics_drawn_look_ink_world") {
        v.graphics_drawn_look_ink_world = Clamp(std::isfinite(f) ? f : 0.0f, 0.0f, 1.0f);
    } else if (key == "graphics_drawn_look_characters") {
        v.graphics_drawn_look_characters = Clamp(std::isfinite(f) ? f : DrawnLookCharactersDefault, 0.0f, 1.0f);
    } else if (key == "graphics_drawn_look_shadow_soft") {
        v.graphics_drawn_look_shadow_soft = Clamp(std::isfinite(f) ? f : DrawnLookShadowSoftDefault,
                                                  DrawnLookShadowSoftMin, DrawnLookShadowSoftMax);
    } else if (key == "graphics_drawn_look_quality") {
        v.graphics_drawn_look_quality = std::clamp(i, 0, 1);
    } else if (key == "graphics_drawn_look_debug") {
        v.graphics_drawn_look_debug = std::clamp(i, 0, DrawnLookDebugMax);
"""),
        (r"""    put("graphics_rt_far_refit",flag(v.graphics_rt_far_refit));
""", r"""    put("graphics_rt_far_refit",flag(v.graphics_rt_far_refit));
    put("graphics_drawn_look", flag(v.graphics_drawn_look)); // bbport (r45_drawn-look)
    put("graphics_drawn_look_strength", fixed(v.graphics_drawn_look_strength, 2));
    put("graphics_drawn_look_stroke_size", fixed(v.graphics_drawn_look_stroke_size, 2));
    put("graphics_drawn_look_texture", fixed(v.graphics_drawn_look_texture, 2));
    put("graphics_drawn_look_outlines", fixed(v.graphics_drawn_look_outlines, 2));
    put("graphics_drawn_look_shadow_edges", fixed(v.graphics_drawn_look_shadow_edges, 2));
    put("graphics_drawn_look_ink_world", fixed(v.graphics_drawn_look_ink_world, 2));
    put("graphics_drawn_look_characters", fixed(v.graphics_drawn_look_characters, 2));
    put("graphics_drawn_look_shadow_soft", fixed(v.graphics_drawn_look_shadow_soft, 2));
    put("graphics_drawn_look_quality", std::to_string(std::clamp(v.graphics_drawn_look_quality.load(), 0, 1)));
    put("graphics_drawn_look_debug",
        std::to_string(std::clamp(v.graphics_drawn_look_debug.load(), 0, DrawnLookDebugMax)));
"""),
    ],
    S + "bbport_overlay.cpp": [
        (r"""            Store(s.graphics_point_fog_glow_size, 0.08f, true);
            SyncRayTracing();
""", r"""            Store(s.graphics_point_fog_glow_size, 0.08f, true);
            Store(s.graphics_drawn_look, false, true); // bbport (r45_drawn-look)
            SyncRayTracing();
"""),
        (r"""    ImGui::EndDisabled();
}

// bbport (r39_master-debug): a measuring or tracing row of the Debug tab.""", r"""    ImGui::EndDisabled();
    // bbport (r45_drawn-look): the renderer's own pass, so not under the switch above, which
    // is for what the game's code does.
    Section("Drawn look", "Рисованный стиль");
    const char* const drawn_problem = s.drawn_look_problem.load();
    if (const char* label = Item("Drawn look (in development)", "Рисованный стиль (в разработке)")) {
        // While it cannot run it cannot be switched on; switched on, it can always be switched
        // off (the renderer then lets go of what it holds for it).
        ImGui::BeginDisabled(drawn_problem != nullptr && !s.graphics_drawn_look);
        Checkbox(label, s.graphics_drawn_look);
        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "An optional hand-painted look: brush strokes laid on the world's surfaces, bold on plain "
            "walls and floors, fine where there is detail. Fire, glows, fog, particles and the HUD stay "
            "as the game draws them, and colours are not changed. Applies at once. This build paints "
            "the strokes; ink lines and painted shadow edges are not built yet.",
            "Необязательный рисованный вид: мазки кисти ложатся на поверхности мира, крупные на ровных "
            "стенах и полах, мелкие там, где есть детали. Огонь, свечение, туман, частицы и интерфейс "
            "остаются такими, какими их рисует игра, цвета не меняются. Применяется сразу. В этой "
            "сборке рисуются мазки; контурные линии и рисованные края теней ещё не сделаны."));
        if (drawn_problem) {
            ImGui::TextDisabled("%s: %s", BbSettings::MenuText("Unavailable", "Недоступно"),
                                BbSettings::MenuText(drawn_problem));
        }
    }
    if (const char* label = Item("Drawn look strength", "Сила рисованного стиля")) {
        ImGui::BeginDisabled(drawn_problem != nullptr || !s.graphics_drawn_look);
        Slider(label, s.graphics_drawn_look_strength, 0.0f, 1.0f, "%.2f", ImGuiSliderFlags_AlwaysClamp);
        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "How much of the strokes is laid over the game's picture: 1 is the full look, lower values "
            "let more of the game's own picture through. At 0 the look does no work at all. Applies at "
            "once.",
            "Насколько мазки перекрывают изображение игры: 1 — стиль в полную силу, меньшие значения "
            "оставляют больше исходного изображения. При 0 стиль вообще не работает. Применяется "
            "сразу."));
    }
}

// bbport (r39_master-debug): a measuring or tracing row of the Debug tab."""),
    ],
    R + "vk_rasterizer.h": [
        (r"""#include "video_core/renderer_vulkan/vk_depth_of_field.h"
""", r"""#include "video_core/renderer_vulkan/vk_depth_of_field.h"
#include "video_core/renderer_vulkan/vk_drawn_look.h"
"""),
        (r"""    void EffectsBlendedScene();
""", r"""    void EffectsBlendedScene();
    void EffectsSceneComposite(const GraphicsPipeline* pipeline); // bbport (r45_drawn-look)
"""),
        (r"""    std::unique_ptr<FroyokBloom> froyok_bloom;
    bool effects_wanted = false;
""", r"""    std::unique_ptr<FroyokBloom> froyok_bloom;
    std::unique_ptr<DrawnLook> drawn_look; // bbport (r45_drawn-look)
    bool effects_wanted = false;
    /// bbport (r45_drawn-look): DrawnLook::Wanted() as EffectsOnFrameEnd read it. Apart from
    /// effects_wanted: wanting the look starts none of the other effects' work on every draw.
    bool drawn_look_wanted = false;
"""),
    ],
    R + "vk_rasterizer.cpp": [
        (r"""    upscaler = std::make_unique<TemporalUpscaler>(instance, scheduler, texture_cache, runtime,
                                                  *camera_motion, *scene_targets, *hdr_native);
""", r"""    upscaler = std::make_unique<TemporalUpscaler>(instance, scheduler, texture_cache, runtime,
                                                  *camera_motion, *scene_targets, *hdr_native);
    // bbport (r45_drawn-look): nothing of Vulkan is made here; its pipelines and its image are
    // made on the first frame the look is wanted on. Its places in the frame are found with the
    // upscaler's scene colour: without the upscaler there are none.
    drawn_look = std::make_unique<DrawnLook>(instance, scheduler, texture_cache, runtime,
                                             *scene_targets, *camera_motion, *object_motion);
    if (!upscaler->Enabled()) {
        DrawnLook::NoSceneHooks();
    }
"""),
        (r"""                // A full-screen pass over the scene (the fog composite): the transparents are in.
                upscaler->OnSceneComposite();
""", r"""                // A full-screen pass over the scene (the fog composite): the transparents are in.
                EffectsSceneComposite(pipeline);
                upscaler->OnSceneComposite();
"""),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r"""    effects_wanted = AnyWanted();
""", r"""    effects_wanted = AnyWanted();
    drawn_look_wanted = DrawnLook::Wanted(); // bbport (r45_drawn-look)
    drawn_look->OnFrameEnd(drawn_look_wanted);
"""),
        (r"""    if (gbuffer) {
        depth_of_field->Reset();
    }
    if (!effects_wanted) {
""", r"""    if (gbuffer) {
        depth_of_field->Reset();
        if (drawn_look_wanted) { // bbport (r45_drawn-look): cb 0 holds the world normals
            drawn_look->OnGBufferDraw(db_desc.first, cb_descs[0].first);
        }
    }
    if (!effects_wanted) {
"""),
        (r"""void Rasterizer::EffectsBlendedScene() {
    if (effects_wanted) {
        ssgi->OnOpaqueScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
}

void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
""", r"""void Rasterizer::EffectsBlendedScene() {
    if (effects_wanted) {
        ssgi->OnOpaqueScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
    // bbport (r45_drawn-look): after the indirect light is in: the strokes take the lit surface.
    if (drawn_look_wanted) {
        drawn_look->OnBlendedScene(cb_descs[0].first, db_desc.first, upscaler->Jitter());
    }
}

// bbport (r45_drawn-look): a full-screen pass over the scene colour is about to be drawn.
void Rasterizer::EffectsSceneComposite(const GraphicsPipeline* pipeline) {
    if (drawn_look_wanted) {
        drawn_look->OnSceneComposite(FragmentHash(pipeline), cb_descs[0].first, db_desc.first,
                                     upscaler->Jitter());
    }
}

void Rasterizer::EffectsBeforeUpscaler(u64 compute_hash) {
    // bbport (r45_drawn-look): before the volumetric light below, which is fog and stays
    // unpainted.
    if (drawn_look_wanted && compute_hash == upscaler->TriggerHash()) {
        drawn_look->OnBeforeUpscaler(upscaler->SceneColor(), camera_motion->Depth(),
                                     upscaler->Jitter());
    }
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""    if (FILENAME MATCHES "^ssgi")
        list(APPEND INCLUDES ${SHADER_SRC}/ssgi_common.glsl)
    endif()
""", r"""    if (FILENAME MATCHES "^ssgi")
        list(APPEND INCLUDES ${SHADER_SRC}/ssgi_common.glsl)
    endif()
    if (FILENAME MATCHES "^paint_")
        list(APPEND INCLUDES ${SHADER_SRC}/paint_common.glsl)
    endif()
"""),
        (r"""add_host_shader(contact_shadow.comp contact_shadow_comp)
""", r"""add_host_shader(contact_shadow.comp contact_shadow_comp)
# bbport (r45_drawn-look): the drawn look's passes (renderer_vulkan/vk_drawn_look.cpp)
add_host_shader(paint_prep.comp paint_prep_comp)
add_host_shader(paint_stats.comp paint_stats_comp)
add_host_shader(paint_mips.comp paint_mips_comp)
add_host_shader(paint_key.comp paint_key_comp)
add_host_shader(paint_key.comp paint_key_last_comp LAST=1)
add_host_shader(paint_strokes.comp paint_strokes_comp)
add_host_shader(paint_lock.comp paint_lock_first_comp FIRST=1)
add_host_shader(paint_lock.comp paint_lock_down_comp DOWN=1)
add_host_shader(paint_lock.comp paint_lock_comp)
"""),
        (r"""target_include_directories(lamp-shadow-tune-test PRIVATE ..)
""", r"""target_include_directories(lamp-shadow-tune-test PRIVATE ..)
# bbport (r45_drawn-look): the drawn look's passes on a synthetic scene (the strokes stay on
# their surfaces under the jitter and a camera move, the colours stay) or on a picture; plain
# Vulkan, no bbgpu.
add_executable(drawn-look-test EXCLUDE_FROM_ALL ../tests/test_drawn_look.cpp)
target_include_directories(drawn-look-test PRIVATE ${SHADER_INCLUDE} shadps4)
target_compile_options(drawn-look-test PRIVATE -UNDEBUG -Wall -Wextra -Werror -Wno-missing-field-initializers)
target_link_libraries(drawn-look-test PRIVATE Vulkan::Vulkan)
add_dependencies(drawn-look-test host_shaders)
"""),
    ],
    TESTS + "test_effect_pipelines.cpp": [
        (r"""#include "video_core/host_shaders/native_motion_blur_frag.h"
""", r"""#include "video_core/host_shaders/native_motion_blur_frag.h"
#include "video_core/host_shaders/paint_key_comp.h"
#include "video_core/host_shaders/paint_key_last_comp.h"
#include "video_core/host_shaders/paint_lock_comp.h"
#include "video_core/host_shaders/paint_lock_down_comp.h"
#include "video_core/host_shaders/paint_lock_first_comp.h"
#include "video_core/host_shaders/paint_mips_comp.h"
#include "video_core/host_shaders/paint_prep_comp.h"
#include "video_core/host_shaders/paint_stats_comp.h"
#include "video_core/host_shaders/paint_strokes_comp.h"
"""),
        (r"""        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},
""", r"""        // bbport (r45_drawn-look): as vk_drawn_look.cpp makes them (DrawnLookParams::Params)
        {"drawn look prep", PAINT_PREP_COMP, {eSampledImage, eSampledImage, eStorageImage}, 112},
        {"drawn look stats", PAINT_STATS_COMP, {eSampledImage, eStorageImage, eStorageImage}, 112},
        {"drawn look mips",
         PAINT_MIPS_COMP,
         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
         112},
        {"drawn look key sums", PAINT_KEY_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look key", PAINT_KEY_LAST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look strokes",
         PAINT_STROKES_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
        {"drawn look lock means", PAINT_LOCK_FIRST_COMP, {eSampledImage, eStorageImage}, 112},
        {"drawn look lock levels",
         PAINT_LOCK_DOWN_COMP,
         {eCombinedImageSampler, eStorageImage},
         112},
        {"drawn look lock",
         PAINT_LOCK_COMP,
         {eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
          eCombinedImageSampler},
         112},
        {"ssgi prep", SSGI_PREP_COMP, {eSampledImage, eStorageImage, eSampledImage}, 128},
"""),
    ],
    TESTS + "test_settings.cpp": [
        (r"""    // bbport (r39_master-debug): engine_previous_paths and the debug_* keys. Nothing above sets
""", r"""    // bbport (r45_drawn-look): the drawn look's keys. Nothing above sets them: off, with the
    // design's values; written back; read; saved after a change; a value outside its range is
    // the nearest end; a switch that is not 0 or 1 is off; no number is the default.
    assert(!s.graphics_drawn_look && s.graphics_drawn_look_strength == 0.6f &&
           s.graphics_drawn_look_stroke_size == 1.0f && s.graphics_drawn_look_texture == 1.0f &&
           s.graphics_drawn_look_outlines == 0.35f && s.graphics_drawn_look_shadow_edges == 1.0f &&
           s.graphics_drawn_look_ink_world == 0.0f && s.graphics_drawn_look_characters == 0.5f &&
           s.graphics_drawn_look_shadow_soft == 0.12f && s.graphics_drawn_look_quality == 1 &&
           s.graphics_drawn_look_debug == 0 && !s.drawn_look_problem.load());
    BbSettings::Save();
    {
        const std::string text = Read(path);
        for (const char* line :
             {"graphics_drawn_look=0\n", "graphics_drawn_look_strength=0.60\n",
              "graphics_drawn_look_stroke_size=1.00\n", "graphics_drawn_look_texture=1.00\n",
              "graphics_drawn_look_outlines=0.35\n", "graphics_drawn_look_shadow_edges=1.00\n",
              "graphics_drawn_look_ink_world=0.00\n", "graphics_drawn_look_characters=0.50\n",
              "graphics_drawn_look_shadow_soft=0.12\n", "graphics_drawn_look_quality=1\n",
              "graphics_drawn_look_debug=0\n"}) {
            assert(text.find(line) != std::string::npos);
        }
    }
    { std::ofstream file(path); file << "graphics_drawn_look=1\ngraphics_drawn_look_strength=0.25\n"
                                        "graphics_drawn_look_stroke_size=1.3\ngraphics_drawn_look_texture=1.1\n"
                                        "graphics_drawn_look_outlines=0.8\ngraphics_drawn_look_shadow_edges=0.5\n"
                                        "graphics_drawn_look_ink_world=0.4\ngraphics_drawn_look_characters=0.9\n"
                                        "graphics_drawn_look_shadow_soft=0.2\ngraphics_drawn_look_quality=0\n"
                                        "graphics_drawn_look_debug=4\n"; }
    BbSettings::Load();
    assert(s.graphics_drawn_look && s.graphics_drawn_look_strength == 0.25f &&
           s.graphics_drawn_look_stroke_size == 1.3f && s.graphics_drawn_look_texture == 1.1f &&
           s.graphics_drawn_look_outlines == 0.8f && s.graphics_drawn_look_shadow_edges == 0.5f &&
           s.graphics_drawn_look_ink_world == 0.4f && s.graphics_drawn_look_characters == 0.9f &&
           s.graphics_drawn_look_shadow_soft == 0.2f && s.graphics_drawn_look_quality == 0 &&
           s.graphics_drawn_look_debug == 4);
    s.graphics_drawn_look_strength = 0.0f; // the menu's slider at its lower end: the look does no work
    s.graphics_drawn_look_debug = 1;
    BbSettings::Save();
    {
        const std::string text = Read(path);
        assert(text.find("graphics_drawn_look=1\n") != std::string::npos);
        assert(text.find("graphics_drawn_look_strength=0.00\n") != std::string::npos);
        assert(text.find("graphics_drawn_look_stroke_size=1.30\n") != std::string::npos);
        assert(text.find("graphics_drawn_look_shadow_soft=0.20\n") != std::string::npos);
        assert(text.find("graphics_drawn_look_quality=0\n") != std::string::npos);
        assert(text.find("graphics_drawn_look_debug=1\n") != std::string::npos);
    }
    { std::ofstream file(path); file << "graphics_drawn_look=2\ngraphics_drawn_look_strength=7\n"
                                        "graphics_drawn_look_stroke_size=0.1\ngraphics_drawn_look_texture=9\n"
                                        "graphics_drawn_look_outlines=-1\ngraphics_drawn_look_shadow_edges=3\n"
                                        "graphics_drawn_look_ink_world=2\ngraphics_drawn_look_characters=-0.5\n"
                                        "graphics_drawn_look_shadow_soft=1\ngraphics_drawn_look_quality=5\n"
                                        "graphics_drawn_look_debug=9\n"; }
    BbSettings::Load();
    assert(!s.graphics_drawn_look && s.graphics_drawn_look_strength == 1.0f &&
           s.graphics_drawn_look_stroke_size == BbSettings::DrawnLookStrokeSizeMin &&
           s.graphics_drawn_look_texture == BbSettings::DrawnLookTextureMax &&
           s.graphics_drawn_look_outlines == 0.0f && s.graphics_drawn_look_shadow_edges == 1.0f &&
           s.graphics_drawn_look_ink_world == 1.0f && s.graphics_drawn_look_characters == 0.0f &&
           s.graphics_drawn_look_shadow_soft == BbSettings::DrawnLookShadowSoftMax &&
           s.graphics_drawn_look_quality == 1 && s.graphics_drawn_look_debug == BbSettings::DrawnLookDebugMax);
    { std::ofstream file(path); file << "graphics_drawn_look_stroke_size=9\ngraphics_drawn_look_shadow_soft=0\n"
                                        "graphics_drawn_look_quality=-3\ngraphics_drawn_look_debug=-1\n"; }
    BbSettings::Load();
    assert(s.graphics_drawn_look_stroke_size == BbSettings::DrawnLookStrokeSizeMax &&
           s.graphics_drawn_look_shadow_soft == BbSettings::DrawnLookShadowSoftMin &&
           s.graphics_drawn_look_quality == 0 && s.graphics_drawn_look_debug == 0);
    { std::ofstream file(path); file << "graphics_drawn_look=on\ngraphics_drawn_look_strength=nan\n"
                                        "graphics_drawn_look_stroke_size=inf\ngraphics_drawn_look_texture=nan\n"
                                        "graphics_drawn_look_outlines=nan\ngraphics_drawn_look_shadow_edges=nan\n"
                                        "graphics_drawn_look_ink_world=nan\ngraphics_drawn_look_characters=-inf\n"
                                        "graphics_drawn_look_shadow_soft=nan\n"; }
    s.graphics_drawn_look = true; // on before this Load: the fallback is off
    BbSettings::Load();
    assert(!s.graphics_drawn_look && s.graphics_drawn_look_strength == BbSettings::DrawnLookStrengthDefault &&
           s.graphics_drawn_look_stroke_size == 1.0f && s.graphics_drawn_look_texture == 1.0f &&
           s.graphics_drawn_look_outlines == BbSettings::DrawnLookOutlinesDefault &&
           s.graphics_drawn_look_shadow_edges == 1.0f && s.graphics_drawn_look_ink_world == 0.0f &&
           s.graphics_drawn_look_characters == BbSettings::DrawnLookCharactersDefault &&
           s.graphics_drawn_look_shadow_soft == BbSettings::DrawnLookShadowSoftDefault);
    // bbport (r39_master-debug): engine_previous_paths and the debug_* keys. Nothing above sets
"""),
    ],
    ROOT + "README.md": [
        (r"""| `graphics_dof_intensity` | Depth-of-field intensity | `1` |
""", r"""| `graphics_dof_intensity` | Depth-of-field intensity | `1` |
| `graphics_drawn_look` | Drawn look (in development): an optional hand-painted look, brush strokes laid on the world's surfaces, bold on plain walls and floors and fine where there is detail. Fire, glows, fog, particles and the HUD are not painted, colours are not changed. Ink lines and painted shadow edges are not built yet | off |
| `graphics_drawn_look_strength` | Drawn look strength, 0 to 1: how much of the strokes is laid over the game's picture (at 0 the look does no work) | `0.6` |
| `graphics_drawn_look_stroke_size` | Drawn look: size of the strokes, 0.6 to 1.4 | `1.0` |
| `graphics_drawn_look_texture` | Drawn look: the brush's marks in a stroke (each stroke a little lighter or darker, streaks along it), 0 to 1.2 | `1.0` |
| `graphics_drawn_look_characters` | Drawn look: share of the strength on characters and whatever else moves by itself, 0 to 1. They are smoothed, not stroked: strokes lie still in the world and a moving body would slide under them | `0.5` |
| `graphics_drawn_look_debug` | Drawn look test view while the look is on: `1` paints every stroke in a flat colour of its own, bold and fine as the look mixes them, `2` the same with all strokes fine, `4` with all strokes bold (`3` is kept for the ink lines) | `0` |
| `graphics_drawn_look_outlines`, `_shadow_edges`, `_ink_world`, `_shadow_soft`, `_quality` | Drawn look: kept for parts of the look that are not built yet (character ink, painted shadow edges and world ink 0 to 1, shadow softness 0.05 to 0.3, quality 0 or 1); read, clamped and saved, without effect so far | `0.35`, `1.0`, `0`, `0.12`, `1` |
"""),
        (r"""disabled with `BB_SKY_SEAM_FIX=0`.
""", r"""disabled with `BB_SKY_SEAM_FIX=0`. `BB_DRAWN_LOOK_VIEW=1`, `2` or `4` shows the drawn look's test view (as `graphics_drawn_look_debug`) while the look is on, without writing it to the ini.
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


# A pass: the header's name, its source, the define that picks it.
PASSES = (("paint_prep_comp", "paint_prep.comp", ""), ("paint_stats_comp", "paint_stats.comp", ""),
          ("paint_mips_comp", "paint_mips.comp", ""),
          ("paint_key_comp", "paint_key.comp", ""),
          ("paint_key_last_comp", "paint_key.comp", " LAST=1"),
          ("paint_strokes_comp", "paint_strokes.comp", ""),
          ("paint_lock_first_comp", "paint_lock.comp", " FIRST=1"),
          ("paint_lock_down_comp", "paint_lock.comp", " DOWN=1"),
          ("paint_lock_comp", "paint_lock.comp", ""))

KEYS = ("", "_strength", "_stroke_size", "_texture", "_outlines", "_shadow_edges", "_ink_world",
        "_characters", "_shadow_soft", "_quality", "_debug")


def text_check(texts):
    """What the patch relies on in the patched text: the shaders, the header that makes their
    words and the tests agree on the push block and its flags; every key is read once and saved
    once; every pass's shader is built and is in the pipeline test."""
    ok = True
    common = NEW_FILES[B + "host_shaders/paint_common.glsl"]
    strokes = NEW_FILES[B + "host_shaders/paint_strokes.comp"]
    params = NEW_FILES[R + "drawn_look_params.h"]
    settings = texts[S + "bbport_settings.cpp"]
    header = texts[S + "bbport_settings.h"]
    cmake = texts[G + "CMakeLists.txt"]
    pipelines = texts[TESTS + "test_effect_pipelines.cpp"]
    if "const uint FLAG_NORMALS = 1u;" not in common or "FlagNormals = 1;" not in params or \
            "const uint FLAG_MOTION = 2u;" not in common or "FlagMotion = 2;" not in params:
        print("the shaders and drawn_look_params.h do not agree on the flags")
        ok = False
    if "(flags >> 8u) & 7u" not in strokes or "ViewShift = 8;" not in params or \
            "ViewMax = 4 }" not in params or "DrawnLookDebugMax = 4;" not in header:
        print("the test view's bits or its largest number differ between the shader, "
              "drawn_look_params.h and bbport_settings.h")
        ok = False
    block = common[common.index("layout(push_constant)"):common.index("};")]
    size = sum({"vec4": 16, "vec2": 8, "float": 4, "uint": 4}[kind] * int(count or 1)
               for kind, count in re.findall(r"^ +(vec4|vec2|float|uint) \w+(?:\[(\d+)\])?;", block, re.M))
    if size != 112 or "static_assert(sizeof(Params) == 112);" not in params or \
            pipelines.count("112}") != len(PASSES):
        print("the push block is not 112 bytes in the shader, the header and the pipeline test")
        ok = False
    for key in KEYS:
        name = "graphics_drawn_look" + key
        if settings.count('key == "%s")' % name) != 1 or settings.count('put("%s",' % name) != 1 or \
                header.count(" %s{" % name) != 1:
            print("%s is not declared once, read once and saved once" % name)
            ok = False
    renderer = NEW_FILES[R + "vk_drawn_look.cpp"]
    for name, source, define in PASSES:
        line = "add_host_shader(%s %s%s)" % (source, name, define)
        symbol = name.upper()
        if cmake.count(line) != 1 or NEW_FILES.get(B + "host_shaders/" + source) is None or \
                pipelines.count(symbol + ",") != 1 or renderer.count(symbol + ",") != 1:
            print("%s is not built once by gpu/CMakeLists.txt, or not once in the pipeline test "
                  "and in vk_drawn_look.cpp" % name)
            ok = False
    if cmake.count('if (FILENAME MATCHES "^paint_")') != 1:
        print("gpu/CMakeLists.txt does not make the paint_ shaders depend on their shared file")
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
        print("usage: r45_drawn-look.py check|apply|revert   (run from the root of a source tree, "
              "or name it in R45_ROOT)")
        return 2
    if not os.path.exists(E + "build.sh"):
        print("%s is not the root of a source tree (no engine/build.sh): run the script from "
              "that root or name it in R45_ROOT" % ROOT)
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
