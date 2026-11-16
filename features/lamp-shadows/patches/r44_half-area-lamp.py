# r44_half-area-lamp: the half-resolution ray traced lamp shadow pass (graphics_lamp_shadow_half /
# BB_LAMP_SHADOW_HALF, r32) gets the area lamp and the averaging history that r42 gave the
# full-resolution pass (point_shadow_ray.comp, lamp_shadow_tune.h, vk_point_shadow.cpp/.h, the
# menu's hint and its translations, the launcher's hint and its translations, two tests).
# check|apply|revert (revert restores byte for byte). On top of r1..r42 (r42_lamp-soft applied),
# with or without r43_copy-turns: it does not touch vk_rt_shadow.h/.cpp, and where r43 put its
# comment in bbport_settings.h it is anchored on the line after (the array's first line) alone.
# Where both go on: r43 first, then r44; back: r44 first, then r43 (r43's own anchor there does
# not hold while r44's comment stands). The tree: the one the environment variable R44_ROOT
# names; without it the current directory when that is the root of a source tree (run from
# there; the rounds before took <tree>/ whatever the directory), else
# <tree>/. Nothing is changed in place: every new text is written beside its
# target and moved over it, and a failure puts back what was already moved. Source files keep
# their CRLF line ends. The (old, new) pairs below were made from the copy the tests and the lab
# ran on (each old text is found exactly once when its turn comes, each new one exactly once on
# the way back).
#
# WHY. r42 made the lamp an area light for the full-resolution pass and left the half-resolution
# pass on point lamps without a history (the shader's HALF build forced the radius to 0 and
# compiled the averaging out; Flush zeroed the radius for a half pass): one bare area-lamp ray
# shared by the four pixels of a 2x2 block would be noise in blocks. So a game played with
# graphics_lamp_shadow_half=1 still showed what r42 was made to remove: the hard thin band a
# torch's stick throws, hard edges on every lamp shadow, and the log said "averaged on 0 frames".
#
# WHAT (design A of the reading of 2026-11-14: average at the block pixel, share the averaged
# answer, refine with each pixel's own history; no new image, binding or matrix: the half
# pipeline already had both history images bound, 7 and 8, and got the history block).
#  1. The shader's HALF build averages (HISTORY_BLEND) as the full-resolution build does. Its
#     first pass (pixel 2x,2y of every block, 8x8 block pixels a workgroup) casts the area-lamp
#     ray, blends it with the pixel's history (reprojection, the bound by the answers around the
#     pixel - here those of the blocks around it -, reject, a moving lamp's motion: all r42's
#     code, unchanged) and stores the AVERAGED ratio as the block's answer.
#  2. Its second pass decides as before (HalfAnswer: the 3x3 block answers within 1/64, the
#     block's pixel on the same surface). Averaged answers are 0 or 1 wherever light or shadow is
#     flat, so those blocks are shared as before. A pixel that takes its block's answer writes
#     the full-resolution history with that ratio, its own depth, and the block pixel's frame
#     count and recent mean (one read of the history image the first pass just wrote: binding 8
#     is no longer writeonly in the HALF build; same descriptor type), so a pixel that has to
#     trace on a later frame finds a history as old as its block's. Where the blocks differ (a
#     shadow's edge, a penumbra) the pixel casts its own ray to the lamp's disc and averages it
#     in its own history, exactly as a pixel of the full-resolution pass. What can go wrong with
#     this design is the saving, not the picture.
#  3. Without HISTORY_BLEND the HALF build keeps the point lamp (the radius is zeroed in main,
#     after the history flags are read): BB_LAMP_SHADOW_SOFT=0, BB_LAMP_SHADOW_HISTORY=0 (a
#     full-resolution pass shows the bare rays then; a half-resolution pass cannot share them),
#     a pass that does not take the frame's history, the experiment bit below.
#  4. Flush takes a pass's lamp radius from LampPassRadius (lamp_shadow_tune.h, tested): the
#     rule of r42 for full resolution, and for half resolution the area lamp when the pass
#     takes the history and averages. A half-resolution pass beside the history pass now counts
#     among the "passes beside it had point lamps" of the lamp line.
#  5. The menu's hint for "Half-resolution lamp shadows" says what the option does now (English
#     and Russian in bbport_overlay.cpp, eight translations in bbport_menu_i18n.cpp, which are
#     looked up by the English text). Its numbers of before (0.38 ms instead of 0.73 ms, about
#     +2.6% FPS, "still pictures showed no difference") were measured with point lamps and are
#     gone; no new number is claimed: the new pass has not been measured in the game.
#  6. The launcher's hint for the same option is another wording ("Faster ray traced lamp
#     shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose
#     its shadow. ..."). Its figure was measured with point lamps too, so it is taken out and
#     the rest stands ("Faster ray traced lamp shadows. An object thinner ..."): the English
#     text in launcher/windows/BloodborneLauncher/Views/GraphicsPage.cs:178 and
#     launcher/windows/LanternLauncher/Views/GraphicsPage.cs:179, and in the 13 files of
#     launcher/windows/BloodborneLauncher/Localization (de, es, fr, it, ja, ko, pl, pt-BR, ru,
#     tr, uk, zh-CN, zh-TW; line 1674, uk and zh-TW 1654, zh-CN 1862) the key, which is that
#     English text, and in the translation the clause or the sentence with the figure, nothing
#     else. The launcher was not built. A new figure goes into both menus once the pass has
#     been measured in the game.
#     NOT changed: the sun's hint (bbport_overlay.cpp, "With Half-resolution lamp shadows and
#     Fewer glossy reflection rays as well: 78.2 instead of 74.2 FPS there"), measured with the
#     old lamp pass.
#
# EXPERIMENT BIT 2305843009213693952 (bit 61; vk_point_shadow.cpp HalfPointsBit, read at every
# half-resolution pass). Set: the half-resolution pass of before r44, point lamps without a
# history (for pictures of before and after). Not in engine_previous_paths' mask
# (bbport_settings.h): set brings the hard-edged torch shadows back. The other bits stand:
# 72057594037927936 set = the pass at full resolution, 35184372088832 set = the pass of before
# r41.
#
# LOG LINES (how a game run shows the new path).
#   When the half pipeline is made: "Ray traced lamps (r32): half resolution (...) ready; at
#     half resolution the lamps are area lamps averaged over the frames as at full resolution
#     (r44: ...; experiment 2305843009213693952 set = point lamps without a history, as before
#     r44)".
#   At each change of what the lamps are, 24 times at most, "Ray traced lamps (r42): " and now
#     one of these for a half-resolution pass: "area lamps at half resolution
#     (graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF): one ray a lamp a frame for one pixel of
#     each 2x2 block and for every pixel where the blocks' averaged answers differ, averaged
#     over the frames in the pass's history; ..." / "point lamps without a history: the pass
#     runs at half resolution (...) and experiment 2305843009213693952 is set, the
#     half-resolution pass of before r44" / "point lamps without a history: the pass runs at
#     half resolution (...), where a lamp is an area lamp only when its answers are averaged
#     (BB_LAMP_SHADOW_HISTORY=0)".
#   Every 600 frames, the lamp line: "Ray traced lamps (r42): N lamp records in the pass, ...;
#     since the last such line the pass averaged on A frames and read its history on B of them
#     (C camera cuts), and P ray traced lamp passes beside it had point lamps; on H of the
#     averaged frames the pass ran at half resolution (r44); the brightest near lamps ...". With
#     the option on and the new path active: A = 600, B = 599 or 600, H = A. With the bit set:
#     A = 0, B = 0, H = 0 (as before r44).
#   Every 600 frames, the half-resolution line (r32) now ends: "; r44: S of the half-resolution
#     passes averaged area lamps over the frames (the others had point lamps: ...), the second
#     pass traced T% of its pixels". S does not count a pass whose radius Flush zeroed because
#     its history could not be read for 8 frames (the state line says "point lamps for now"
#     then), so S = the line's passes at half resolution says the passes had area lamps; B of
#     the lamp line says on how many frames they also had a history to read. T is the share the
#     cost goes with: the first pass always traces a quarter of the screen, the second pass T%
#     of the other three quarters (the same line gives the pixels and rays of both and why
#     pixels were traced).
#   The pass's GPU time: the "Lighting: point shadows" row of the GPU profile table, as before.
#
# THE LAB. tests/test_rt_shadows.cpp, "rt-shadow-test --lamps [directory]": the torch lab runs
# the half-resolution build with its history wherever it ran the full-resolution pass against a
# true picture: the still scene (check 6: the first frame, 16 and 48 frames, the stick's band,
# the bodies' shadows, the mean light, what the two passes did on the first and on the 48th
# frame), the torch carried at a run and at a walk, a figure walking under the still torch with
# one lamp and with two, a figure gone from one frame to the next with one lamp and with two, a
# lamp that flickers, a moving camera (checks 4 and 5); each must stay within 1.25 times the
# full-resolution pass's distance from the true picture, and a shadow that is gone must go as
# fast. Under the walking figure the error is also taken over pixel (2x,2y) of each block alone
# and over the other three (the first pass bounds a pixel's history by the answers of the
# blocks around it, twice as far apart as a full-resolution pixel's neighbours, so that pixel
# could trail behind a moving edge as dots): the first may not be more than 1.25 times the
# second. Check 6 also holds that the build without a history, and with the radius zeroed (the
# experiment bit's path), shows the point lamp's picture, and check 7 times the build (without
# its counters: they are in host memory in the lab, where the shader's atomic adds cost fifty
# times the pass).
# Numbers of the lab on the machine the patch was made on (1920x1080, a scene of 62560
# triangles where a ray costs next to nothing: the times say what the pass costs beside its
# rays, not what it costs in the game):
#   still scene, 48 frames, against the true picture (all pixels / penumbra / share more than
#     0.25 off): half resolution 0.0068 / 0.0444 / 0.01%, full resolution 0.0063 / 0.0439 /
#     0.00%; mean light 0.7402 (true 0.7410); the stick's band keeps 0.585 of the light (full
#     resolution 0.584, true 0.588, the point lamp 0.000);
#   its first frame (no history to read, as after a camera cut: bare rays, shared only where
#     those of the nine blocks around a pixel agree): half 0.0454 / 0.3384 / 7.15%, full 0.0460
#     / 0.3430 / 7.26%;
#   torch carried at a run (6.7 cm a frame), 16th frame: half 0.0207 / 0.0971 / 1.29%, full
#     0.0202 / 0.0963 / 1.27%; at a walk: half 0.0193 / 0.0974 / 1.61%, full 0.0190 / 0.0972 /
#     1.61%; camera moving 3 cm a frame: half 0.0127 / 0.0596 / 0.11%, full 0.0126 / 0.0587 /
#     0.10%; the lamp up to 2 cm off its place every frame: half 0.0138 / 0.0894 / 0.32%, full
#     0.0141 / 0.0888 / 0.30%;
#   a figure walking 5 cm a frame under the still torch, 16th frame: half 0.0113 / 0.0777 /
#     0.83%, full 0.0109 / 0.0772 / 0.82%; pixel (2x,2y) of each block alone 0.0111 / 0.0787 /
#     0.84%, the other three 0.0114 / 0.0774 / 0.82% (the full-resolution pass on the same
#     pixels: 0.0108 / 0.0769 / 0.81% and 0.0109 / 0.0773 / 0.83%). With a second lamp: half
#     0.0089 / 0.0132 / 0.14%, full 0.0081 / 0.0125 / 0.12%; pixel (2x,2y) alone 0.0084 /
#     0.0128 / 0.16%, the other three 0.0090 / 0.0133 / 0.14% (full 0.0081 / 0.0124 / 0.11% and
#     0.0081 / 0.0125 / 0.12%);
#   a figure gone, share of the old picture left after 1 / 2 / 4 / 8 / 16 frames: one lamp half
#     0.015 / 0.012 / 0.009 / 0.007 / 0.003, full 0.013 / 0.010 / 0.008 / 0.005 / 0.002; two
#     lamps half 0.144 / 0.124 / 0.099 / 0.069 / 0.033, full 0.141 / 0.121 / 0.097 / 0.068 /
#     0.032;
#   the second pass traced 17.0% of its pixels on the still scene's 48th frame (264666 of
#     1554909; 259940 because the blocks' answers differed), 13.5% on its first frame, 16.7 to
#     18.5% in the moving scenes; with point lamps (before r44) 2.0% (31563);
#   behind the walking figure, pixels more than 0.25 off whose three block mates are all within
#     0.1 (lone dots on pixel 2x,2y): half 219, full 86 of 2 million; with the second lamp 66
#     and 16. So the trail on the first pass's pixels is there and small; the shader was left;
#   times: full resolution, point lamp 0.104 ms, area lamp with its history 0.133 ms; half
#     resolution, point lamps (the bit set) 0.131 ms, area lamp with its history 0.176 ms. The
#     shader of before r44 in the same lab, half resolution: 0.112 ms (the full-resolution
#     point lamp 0.102 ms in that run). So with the bit set the pass is not quite the pass of
#     before r44 in time: about 0.02 ms more here with nothing of the averaging running (the
#     build now holds it), and a time taken with the bit set is not the time of before r44.
# tests/test_lamp_shadow_tune.cpp: LampPassRadius (full and half resolution, the pass that takes
# the history or not, the bit, BB_LAMP_SHADOW_HISTORY=0, BB_LAMP_SHADOW_SOFT=0).
#
# NOT MEASURED: the pass in the game (its time, the share its second pass traces there, the
# picture). Before r44 the half pass took 0.38 ms and the full pass 0.73 to 0.79 ms at the spot
# of the earlier measurements, with 0.62 million rays in the first pass and 0.48 million in the
# second. r44 adds the averaging's work (0.064 ms in the lab against the shader of before) and
# the rays of every penumbra pixel the old pass did not trace. For the old pass's time take
# the 0.38 ms on file, not a run with the bit set.

import os
import re
import sys

# The tree: R44_ROOT when it is set; else the current directory when that is the root of a
# source tree (the script is run from there); else <tree>/, as the rounds before.
ROOT = os.environ.get("R44_ROOT")
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

BIT = 61
VALUE = 1 << BIT  # 2305843009213693952
TMP = ".r44tmp"  # a new text waits under this name beside its target (main)

# No file is new in this round (apply makes none, revert removes none).
NEW_FILES = {}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    B + "host_shaders/point_shadow_ray.comp": [
        (r"""layout(set = 0, binding = 6) uniform accelerationStructureEXT scene;
layout(set = 0, binding = 7, rgba16f) uniform readonly image2D history_prev;
layout(set = 0, binding = 8, rgba16f) uniform writeonly image2D history_cur;
#ifdef HALF
// bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 only (the point_shadow_ray_half_comp build).
""",
         r"""layout(set = 0, binding = 6) uniform accelerationStructureEXT scene;
layout(set = 0, binding = 7, rgba16f) uniform readonly image2D history_prev;
#ifdef HALF
// bbport (r44_half-area-lamp): read as well: a pixel that takes its block's answer takes the
// age of that answer from what the first pass stored for the block's pixel.
layout(set = 0, binding = 8, rgba16f) uniform image2D history_cur;
#else
layout(set = 0, binding = 8, rgba16f) uniform writeonly image2D history_cur;
#endif
#ifdef HALF
// bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 only (the point_shadow_ray_half_comp build).
"""),
        (r"""// smear. A body covers all of it in its core and less towards its rim: a penumbra that widens
// with the distance behind the caster. No more rays than a point lamp casts. t_radius 0: the
// point lamp, the same ray every frame, no history (BB_LAMP_SHADOW_SOFT=0; and always in the
// half-resolution build, whose block answers must agree to be shared).
const uint MODE_REPAIR = 16u;
bool new_w = false;             // weights follow the game's falloff and the surface's facing
""",
         r"""// smear. A body covers all of it in its core and less towards its rim: a penumbra that widens
// with the distance behind the caster. No more rays than a point lamp casts. t_radius 0: the
// point lamp, the same ray every frame, no history (BB_LAMP_SHADOW_SOFT=0).
// bbport (r44_half-area-lamp): the half-resolution build has the area lamp too, where the pass
// averages (HISTORY_BLEND). Its first pass averages the pixel it traces for each 2x2 block as
// the full-resolution pass averages every pixel, and stores that averaged ratio as the block's
// answer: averaged answers are 0 or 1 outside a penumbra, so the blocks there agree and are
// shared as before; inside a penumbra they differ, and each pixel casts its own ray to the
// lamp's disc and averages it in its own history (the history images are of full resolution).
// So where a shadow has an edge or a penumbra every pixel is worked out as at full resolution,
// and only flat light or flat shadow is shared. Without HISTORY_BLEND the half-resolution build
// keeps the point lamp (main): one bare ray to a point of the disc, shared by four pixels,
// would be noise in blocks.
const uint MODE_REPAIR = 16u;
bool new_w = false;             // weights follow the game's falloff and the surface's facing
"""),
        (r"""    t_axis_a = vec3(word(at + 10u), word(at + 11u), word(at + 12u));
    t_axis_b = vec3(word(at + 13u), word(at + 14u), word(at + 15u));
#ifdef HALF
    t_radius = 0.0; // bbport (r42_lamp-soft): the half-resolution build keeps the point lamp
#endif
}

""",
         r"""    t_axis_a = vec3(word(at + 10u), word(at + 11u), word(at + 12u));
    t_axis_b = vec3(word(at + 13u), word(at + 14u), word(at + 15u));
}

"""),
        (r"""
shared uint group_trace;
#ifndef HALF
// bbport (r42_lamp-soft): averaging (HISTORY_BLEND), what each pixel of the workgroup found on
// this frame: its answer (the shadow ratio its rays gave; below 0: the pass does not shadow the
// pixel), and what blocked the ray to its strongest lamp if that lamp moves: -1 nothing (or the
// lamp stands), -2 something near the lamp (within word 32 of it), else how far the hit lies
// from the pixel over how far it lies from the lamp.
shared float group_answer[64];
shared float group_cast[64];
#endif

#ifdef HALF
""",
         r"""
shared uint group_trace;
// bbport (r42_lamp-soft): averaging (HISTORY_BLEND), what each pixel of the workgroup found on
// this frame: its answer (the shadow ratio its rays gave; below 0: the pass does not shadow the
// pixel), and what blocked the ray to its strongest lamp if that lamp moves: -1 nothing (or the
// lamp stands), -2 something near the lamp (within word 32 of it), else how far the hit lies
// from the pixel over how far it lies from the lamp.
// bbport (r44_half-area-lamp): in the half-resolution build too. Its first pass's workgroup
// holds the 8x8 block pixels of 16x16 pixels (the answers around a pixel are those of the
// blocks around it). In its second pass a pixel that took its block's answer gives that
// averaged ratio as its answer, and a pixel the first pass did has none.
shared float group_answer[64];
shared float group_cast[64];

#ifdef HALF
"""),
        (r"""    const uint history_at = floatBitsToUint(length_m);
    const uint history_flags = history_at != 0u ? data.d[history_at] : 0u;

#ifdef HALF
""",
         r"""    const uint history_at = floatBitsToUint(length_m);
    const uint history_flags = history_at != 0u ? data.d[history_at] : 0u;
#ifdef HALF
    // bbport (r44_half-area-lamp): a block's answer is shared by its pixels, so at half
    // resolution a lamp is an area lamp only where its answers are averaged over the frames
    if ((history_flags & HISTORY_BLEND) == 0u) {
        t_radius = 0.0;
    }
#endif

#ifdef HALF
"""),
        (r"""    uint lamps = 0u;
    float view_top = 0.0;
#ifdef HALF
    const bool blend = false; // bbport (r42_lamp-soft): the point lamp, see loadTune
#else
    const bool blend = (history_flags & HISTORY_BLEND) != 0u;
#endif
    uint top_at = 0u; // blend: the record of the pixel's strongest lamp (0: none)
    const bool exact = steps == 0u;
""",
         r"""    uint lamps = 0u;
    float view_top = 0.0;
    const bool blend = (history_flags & HISTORY_BLEND) != 0u;
    uint top_at = 0u; // blend: the record of the pixel's strongest lamp (0: none)
    const bool exact = steps == 0u;
"""),
        (r"""    float frames = 0.0;         // the frames of history in the ratio (view 5)
    vec3 looked = vec3(0.0, 0.0, 1.0); // view 6
#ifndef HALF
    if (blend) {
        // Words 12 to 15 of the strongest lamp's record: its motion, and how far that is.
""",
         r"""    float frames = 0.0;         // the frames of history in the ratio (view 5)
    vec3 looked = vec3(0.0, 0.0, 1.0); // view 6
    if (blend) {
        // Words 12 to 15 of the strongest lamp's record: its motion, and how far that is.
"""),
        (r"""            return;
        }
        // The 5x5 answers around the pixel, moved in from the workgroup's rim so that every
        // pixel has 25 places to ask (this pixel's own is always one of them).
""",
         r"""            return;
        }
#ifdef HALF
        if (half_why == HALF_TAKEN) {
            // bbport (r44_half-area-lamp): the block's averaged ratio goes on as this pixel's,
            // with the frames and the mean of the last few frames that the first pass stored
            // for the block's pixel: a pixel that has to cast its own ray on a later frame (a
            // shadow's edge reaches it) then finds a history as old as its block's and does not
            // start again from one ray.
            const vec4 h = imageLoad(history_cur, px & ~1);
            frames = max(h.b - 1.0, 0.0);
            imageStore(history_cur, px, vec4(ratio, P.z, h.b, h.a));
        } else {
#endif
        // The 5x5 answers around the pixel, moved in from the workgroup's rim so that every
        // pixel has 25 places to ask (this pixel's own is always one of them).
"""),
        (r"""        }
        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));
    } else
#endif
    if ((history_flags & HISTORY_WRITE) != 0u) {
        imageStore(history_cur, px, vec4(ratio, P.z, stable, 1.0));
    }
""",
         r"""        }
        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));
#ifdef HALF
        }
#endif
    } else if ((history_flags & HISTORY_WRITE) != 0u) {
        imageStore(history_cur, px, vec4(ratio, P.z, stable, 1.0));
    }
"""),
    ],
    R + "lamp_shadow_tune.h": [
        (r"""    }
    return tune.history / (1.0f - std::min(tune.history, 0.98f));
}

""",
         r"""    }
    return tune.history / (1.0f - std::min(tune.history, 0.98f));
}

/// bbport (r44_half-area-lamp): the lamp's radius for one ray traced lamp pass of a frame
/// (PointShadow::Flush); 0: a point lamp. The area lamp shows one ray's answer a frame, which
/// is noise until the history has averaged it: where the knobs ask for the averaging, only the
/// pass that takes the history has the area lamp (takes_history), and another pass of the frame
/// keeps the point lamp. A pass at half resolution (half) shares one answer among the pixels of
/// a 2x2 block, which only an averaged answer can be: it has the area lamp when it averages, and
/// the point lamp without the averaging (BB_LAMP_SHADOW_HISTORY=0, where a full-resolution pass
/// shows the bare rays) and while experiment 2305843009213693952 is set (half_points: the
/// half-resolution pass of before r44, point lamps without a history).
inline float LampPassRadius(const LampShadowTune& tune, bool takes_history, bool half, bool half_points) {
    const bool averages = LampHistoryFrames(tune) > 0.0f;
    if (half && (half_points || !averages)) {
        return 0.0f;
    }
    return averages && !takes_history ? 0.0f : tune.radius_m;
}

"""),
    ],
    R + "vk_point_shadow.h": [
        (r"""    // Since the last line that says where the lamps are: frames the pass averaged on, those of
    // them on which it read its history, camera cuts it did not read across, and ray traced
    // lamp passes that ran beside it with point lamps.
    u32 line_blend = 0, line_read = 0, line_cuts = 0, line_beside = 0;
    u32 lamp_line_frames = 480;
    void TrackLamps(u32 end, bool blend, bool read, bool line);
""",
         r"""    // Since the last line that says where the lamps are: frames the pass averaged on, those of
    // them on which it read its history, camera cuts it did not read across, and ray traced
    // lamp passes that ran beside it with point lamps. bbport (r44_half-area-lamp): line_half:
    // the frames of line_blend on which the pass ran at half resolution.
    u32 line_blend = 0, line_read = 0, line_cuts = 0, line_beside = 0, line_half = 0;
    u32 lamp_line_frames = 480;
    void TrackLamps(u32 end, bool blend, bool read, bool line);
"""),
        (r"""    // HalfReady makes the pipeline the first time a pass wants it. Experiment 72057594037927936
    // set: the full-resolution pass, as before.
    int half_env = -1;        ///< BB_LAMP_SHADOW_HALF: -1 not set, 1 for "1", 0 for anything else
    bool half_tried = false;  ///< HalfReady made its attempt
""",
         r"""    // HalfReady makes the pipeline the first time a pass wants it. Experiment 72057594037927936
    // set: the full-resolution pass, as before.
    // bbport (r44_half-area-lamp): the half-resolution pass has the area lamp too, averaged in
    // the history like the full-resolution pass's (Flush). Experiment 2305843009213693952 set:
    // point lamps without a history at half resolution, as before r44.
    int half_env = -1;        ///< BB_LAMP_SHADOW_HALF: -1 not set, 1 for "1", 0 for anything else
    bool half_tried = false;  ///< HalfReady made its attempt
"""),
        (r"""    u32 half_line_passes = 0;   ///< since the last line: half-resolution passes
    u32 half_line_full = 0;     ///< since the last line: apart passes at full resolution
    OwnImage half_answers;
    std::unique_ptr<VideoCore::Buffer> half_counts, half_readback;
""",
         r"""    u32 half_line_passes = 0;   ///< since the last line: half-resolution passes
    u32 half_line_full = 0;     ///< since the last line: apart passes at full resolution
    u32 half_line_soft = 0;     ///< since the last line: half-resolution passes that averaged area lamps (radius not zeroed)
    OwnImage half_answers;
    std::unique_ptr<VideoCore::Buffer> half_counts, half_readback;
"""),
    ],
    R + "vk_point_shadow.cpp": [
        (r"""constexpr u32 HalfSlots = 16;
constexpr u64 HalfOffBit = 72057594037927936ull;
constexpr u32 TileWords = 8;
constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
""",
         r"""constexpr u32 HalfSlots = 16;
constexpr u64 HalfOffBit = 72057594037927936ull;
// bbport (r44_half-area-lamp): set: a pass at half resolution has point lamps without a history,
// as before r44 (hard-edged shadows; for pictures of before and after). Read at every pass.
constexpr u64 HalfPointsBit = 2305843009213693952ull;
constexpr u32 TileWords = 8;
constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
"""),
        (r"""        }
    }
    // bbport (r42_lamp-soft): and what it does to the area lamp (see Flush)
    std::printf("Ray traced lamps (r32): half resolution (%s) %s; at half resolution the lamps "
                "stay points without a history (r42: BB_LAMP_SHADOW_SOFT and "
                "BB_LAMP_SHADOW_HISTORY act on the full-resolution pass only)\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
""",
         r"""        }
    }
    // bbport (r42_lamp-soft, r44_half-area-lamp): and what it does to the area lamp (see Flush)
    std::printf("Ray traced lamps (r32): half resolution (%s) %s; at half resolution the lamps "
                "are area lamps averaged over the frames as at full resolution (r44: one pixel "
                "of each 2x2 block is traced and averaged first, its answer is shared where the "
                "blocks around a pixel agree, every other pixel casts its own ray and keeps its "
                "own history; experiment 2305843009213693952 set = point lamps without a "
                "history, as before r44)\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
"""),
        (r"""                    "block's answer, %.0f traced at full resolution with %.0f rays (%.0f a block "
                    "near them had no answer, %.0f the answers differed, %.0f another surface), "
                    "%.0f from history; second-pass workgroups with no ray %.0f of %.0f\n",
                    half_frames, half_line_passes, half_line_full, counted, d[1], d[2], d[3],
                    d[4], d[5], d[6], d[10], d[11], d[12], d[7], d[9], d[8]);
        half_frames = 0;
        half_line_passes = 0;
        half_line_full = 0;
    }
    dispatch_flushes = 0;
""",
         r"""                    "block's answer, %.0f traced at full resolution with %.0f rays (%.0f a block "
                    "near them had no answer, %.0f the answers differed, %.0f another surface), "
                    "%.0f from history; second-pass workgroups with no ray %.0f of %.0f",
                    half_frames, half_line_passes, half_line_full, counted, d[1], d[2], d[3],
                    d[4], d[5], d[6], d[10], d[11], d[12], d[7], d[9], d[8]);
        // bbport (r44_half-area-lamp): whether the passes had the area lamp, and what share of
        // its pixels the second pass traced (the first pass always traces a quarter of the
        // screen: this share is what the half resolution saves or does not).
        const double second = d[4] + d[5] + d[7];
        std::printf("; r44: %u of the half-resolution passes averaged area lamps over the frames "
                    "(the others had point lamps: experiment 2305843009213693952 or "
                    "35184372088832 set, BB_LAMP_SHADOW_SOFT=0, BB_LAMP_SHADOW_HISTORY=0, not the "
                    "pass that takes the history, or a history that could not be read for 8 "
                    "frames), the second pass traced %.1f%% of its pixels\n",
                    half_line_soft, second > 0.0 ? 100.0 * d[5] / second : 0.0);
        half_frames = 0;
        half_line_passes = 0;
        half_line_full = 0;
        half_line_soft = 0;
    }
    dispatch_flushes = 0;
"""),
        (r"""                "within %.0f m of the camera; since the last such line the pass averaged on %u "
                "frames and read its history on %u of them (%u camera cuts), and %u ray traced "
                "lamp passes beside it had point lamps; the brightest near lamps (%s, reach, "
                "luminance, distance to the camera, records, moved since the frame before; "
                "then over the frames it was followed since the last line: how many, its mean "
                "step and its largest):",
                records, track.Count(), LampTrack::Most, untold, close, double(LampTrack::Near),
                line_blend, line_read, line_cuts, line_beside,
                camera.valid ? "world x y z" : "view space x y z, the camera is not known");
    for (const int index : track.Strongest()) {
""",
         r"""                "within %.0f m of the camera; since the last such line the pass averaged on %u "
                "frames and read its history on %u of them (%u camera cuts), and %u ray traced "
                "lamp passes beside it had point lamps; on %u of the averaged frames the pass "
                "ran at half resolution (r44); the brightest near lamps (%s, reach, "
                "luminance, distance to the camera, records, moved since the frame before; "
                "then over the frames it was followed since the last line: how many, its mean "
                "step and its largest):",
                records, track.Count(), LampTrack::Most, untold, close, double(LampTrack::Near),
                line_blend, line_read, line_cuts, line_beside, line_half,
                camera.valid ? "world x y z" : "view space x y z, the camera is not known");
    for (const int index : track.Strongest()) {
"""),
        (r"""    }
    std::printf("\n");
    line_blend = line_read = line_cuts = line_beside = 0;
    track.ClearSteps();
}
""",
         r"""    }
    std::printf("\n");
    line_blend = line_read = line_cuts = line_beside = line_half = 0;
    track.ClearSteps();
}
"""),
        (r"""    // frame, which is noise until the history has averaged it, so only the pass that takes the
    // history has it (with the lamps drawn apart, the default, that is the one pass that covers
    // the screen); another ray traced pass of the frame (`beside`) keeps the point lamp. So does
    // the pass at half resolution (r32): one area-lamp ray for a 2x2 block would show as noise
    // in blocks, and its second half traces at full resolution wherever the block answers
    // around a pixel differ, which in a penumbra of single rays is everywhere: the saving would
    // be gone. BB_LAMP_SHADOW_HISTORY=0 asks for the bare rays: then every full-resolution
    // pass has the area lamp.
    const bool history_pass = use_rays && !history_written && history_ours;
    const bool beside = use_rays && !use_half && !history_pass && LampHistoryFrames(tune) > 0.0f;
    LampShadowTune pass_tune = tune;
    if (use_half || beside) {
        pass_tune.radius_m = 0.0f;
    }
    if (use_rays) {
        table = u32(data.size());
""",
         r"""    // frame, which is noise until the history has averaged it, so only the pass that takes the
    // history has it (with the lamps drawn apart, the default, that is the one pass that covers
    // the screen); another ray traced pass of the frame (`beside`) keeps the point lamp.
    // BB_LAMP_SHADOW_HISTORY=0 asks for the bare rays: then every full-resolution pass has the
    // area lamp.
    // bbport (r44_half-area-lamp): the pass at half resolution (r32) has the area lamp as well
    // when it takes the history. r42 kept point lamps there (one area-lamp ray for a 2x2 block
    // would show as noise in blocks), which left the hard bands the area lamp was made to
    // remove in every game played with graphics_lamp_shadow_half. Now the pass's first half
    // averages the pixel it traces for a block in the history, as the full-resolution pass
    // does for every pixel, so a block's answer is an averaged ratio: 0 or 1 where light or
    // shadow is flat, where the second half shares it as before; where the blocks around a
    // pixel differ (a shadow's edge, a penumbra) every pixel casts its own ray and averages it
    // in its own history, which is of full resolution (point_shadow_ray.comp). What the half
    // resolution saves is then the flat part of the screen: the 600-frame line of the
    // half-resolution pass says what share of its pixels the second half traced. Without the
    // averaging a pass at half resolution has point lamps, and with experiment
    // 2305843009213693952 set (half_points) it is the pass of before r44: point lamps without
    // a history (LampPassRadius).
    const bool history_pass = use_rays && !history_written && history_ours;
    const bool half_points = use_half && BbToggle::Experiment(HalfPointsBit);
    const bool beside = use_rays && !half_points && !history_pass && LampHistoryFrames(tune) > 0.0f;
    LampShadowTune pass_tune = tune;
    pass_tune.radius_m = LampPassRadius(tune, history_pass, use_half, half_points);
    if (use_rays) {
        table = u32(data.size());
"""),
        (r"""            ++line_blend;
            line_read += (flags & HistoryRead) ? 1 : 0;
            unread = blend_unread > UnreadMost;
            if (unread) {
                data[tune_at + 2] = std::bit_cast<u32>(0.0f);
            }
        }
        // What the lamps are on this pass, logged at each change (SoftLines times at most).
        const int soft = !repair                                ? 0
                         : use_half                             ? 1
                         : !(tune.radius_m > 0.0f)              ? 2
                         : !(LampHistoryFrames(tune) > 0.0f)    ? 3
                         : unread                               ? 5
                                                                : 4;
        if (soft != std::exchange(soft_state, soft) && soft_lines < SoftLines) {
            static constexpr std::array<const char*, 6> What{
                "point lamps: experiment 35184372088832 is set, the pass of before r41",
                "point lamps without a history: the pass runs at half resolution "
                "(graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF), which keeps them",
                "point lamps without a history (BB_LAMP_SHADOW_SOFT=0)",
                "area lamps, one ray a lamp a frame, not averaged (BB_LAMP_SHADOW_HISTORY=0)",
""",
         r"""            ++line_blend;
            line_read += (flags & HistoryRead) ? 1 : 0;
            line_half += use_half ? 1 : 0; // bbport (r44_half-area-lamp): for the lamp line
            unread = blend_unread > UnreadMost;
            if (unread) {
                data[tune_at + 2] = std::bit_cast<u32>(0.0f);
            }
            // bbport (r44_half-area-lamp): for the half-resolution pass's line, which says
            // "area lamps": not a pass whose radius was just zeroed
            half_line_soft += use_half && !unread ? 1 : 0;
        }
        // What the lamps are on this pass, logged at each change (SoftLines times at most).
        // bbport (r44_half-area-lamp): 1, 6 and 7 are the pass at half resolution.
        const int soft = !repair                                ? 0
                         : half_points                          ? 1
                         : !(tune.radius_m > 0.0f)              ? 2
                         : !(LampHistoryFrames(tune) > 0.0f)    ? (use_half ? 6 : 3)
                         : unread                               ? 5
                         : use_half                             ? 7
                                                                : 4;
        if (soft != std::exchange(soft_state, soft) && soft_lines < SoftLines) {
            static constexpr std::array<const char*, 8> What{
                "point lamps: experiment 35184372088832 is set, the pass of before r41",
                "point lamps without a history: the pass runs at half resolution "
                "(graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF) and experiment "
                "2305843009213693952 is set, the half-resolution pass of before r44",
                "point lamps without a history (BB_LAMP_SHADOW_SOFT=0)",
                "area lamps, one ray a lamp a frame, not averaged (BB_LAMP_SHADOW_HISTORY=0)",
"""),
        (r"""                "point lamps for now: the pass could not read its history for 8 frames (no "
                "camera for the pass, or the history is made anew every frame)",
            };
            ++soft_lines;
""",
         r"""                "point lamps for now: the pass could not read its history for 8 frames (no "
                "camera for the pass, or the history is made anew every frame)",
                "point lamps without a history: the pass runs at half resolution "
                "(graphics_lamp_shadow_half or BB_LAMP_SHADOW_HALF), where a lamp is an area "
                "lamp only when its answers are averaged (BB_LAMP_SHADOW_HISTORY=0)",
                "area lamps at half resolution (graphics_lamp_shadow_half or "
                "BB_LAMP_SHADOW_HALF): one ray a lamp a frame for one pixel of each 2x2 block "
                "and for every pixel where the blocks' averaged answers differ, averaged over "
                "the frames in the pass's history; experiment 2305843009213693952 set = point "
                "lamps there, as before r44",
            };
            ++soft_lines;
"""),
    ],
    S + "bbport_settings.h": [
        (r"""inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20,
""",
         r"""// bbport (r44_half-area-lamp): nor is 61 (2305843009213693952; set = point lamps without a
// history in the half-resolution lamp shadow pass, vk_point_shadow.cpp HalfPointsBit), for the
// same reason: set brings the hard-edged torch shadows back.
inline constexpr int PreviousPathsBits[] = {5, 6, 7, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20,
"""),
    ],
    S + "bbport_overlay.cpp": [
        (r"""    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF as a setting. Live: vk_point_shadow.cpp reads
    // it at every lamps-apart pass and makes the half-resolution pipeline the first time.
    if (const char* label = Item("Half-resolution lamp shadows",
                                 "Тени ламп в половинном разрешении")) {
""",
         r"""    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF as a setting. Live: vk_point_shadow.cpp reads
    // it at every lamps-apart pass and makes the half-resolution pipeline the first time.
    // bbport (r44_half-area-lamp): the hint says what the option does now that the pass at half
    // resolution has the area lamp (soft shadows, averaged over the frames). The numbers of
    // before (0.38 ms instead of 0.73 ms, about +2.6% FPS) were measured with point lamps and are
    // gone until the new pass has been measured in the game.
    if (const char* label = Item("Half-resolution lamp shadows",
                                 "Тени ламп в половинном разрешении")) {
"""),
        (r"""        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels "
            "first, then every pixel where the answers around it differ. At one heavy spot the lamp "
            "shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures "
            "showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
            "Работает сразу, по умолчанию выкл. Нужны трассированные тени ламп. Сначала трассирует "
            "один луч на 2x2 пикселя, затем каждый пиксель там, где ответы вокруг него расходятся. "
            "В одном тяжёлом месте проход теней ламп занял 0.38 мс вместо 0.73 мс (около +2.6% "
            "FPS), на неподвижных кадрах разницы не видно; предмет тоньше примерно 2 пикселей может "
            "остаться без тени."));
        if (s.graphics_rt_point_shadows && s.graphics_lamp_shadow_half) {
            RayTracingNotice();
""",
         r"""        ImGui::EndDisabled();
        Hint(BbSettings::MenuText(
            "Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a "
            "lower cost: traces one pixel of every 2x2 block first, then every pixel where the "
            "answers around it differ, so shadow edges and soft rims are traced in full and only "
            "evenly lit or evenly dark areas share a block's answer. The saving depends on the "
            "view: large where lamp light is even, small where much of the picture is soft shadow. "
            "A shadow caster thinner than about 2 pixels can be missed.",
            "Работает сразу, по умолчанию выкл. Нужны трассированные тени ламп. Тени ламп остаются "
            "мягкими, но обходятся дешевле: сначала трассируется один пиксель каждого блока 2x2, "
            "затем каждый пиксель там, где ответы вокруг него расходятся, так что края теней и "
            "мягкие полутени трассируются полностью, а ответ блока берут только ровно освещённые "
            "или ровно тёмные участки. Выигрыш зависит от кадра: большой там, где свет ламп ровный, "
            "малый там, где большую часть кадра занимает мягкая тень. Предмет тоньше примерно 2 "
            "пикселей может остаться без тени."));
        if (s.graphics_rt_point_shadows && s.graphics_lamp_shadow_half) {
            RayTracingNotice();
"""),
    ],
    S + "bbport_menu_i18n.cpp": [
        (r"""    {"Half-resolution lamp shadows",
     "Sombras de lámparas a media resolución"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Al instante, desactivado por defecto. Requiere «Ray traced lamp shadows». Primero traza un rayo por cada 2x2 píxeles y luego cada píxel donde las respuestas a su alrededor difieren. En un punto exigente el pase de sombras de lámparas tardó 0.38 ms en vez de 0.73 ms (alrededor de +2.6% FPS) y en imágenes fijas no se vio diferencia; un objeto más fino que unos 2 píxeles puede perder su sombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objetos animados lejanos en el trazado de rayos: actualizar cada 8 fotogramas"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Sombras de lámparas a media resolución"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Al instante, desactivado por defecto. Requiere «Ray traced lamp shadows». Las sombras de lámparas siguen siendo suaves, con menor coste: primero traza un píxel de cada bloque de 2x2 y luego cada píxel donde las respuestas a su alrededor difieren, de modo que los bordes de las sombras y las penumbras se trazan por completo y solo las zonas iluminadas u oscuras de manera uniforme comparten la respuesta de un bloque. El ahorro depende de la vista: grande donde la luz de las lámparas es uniforme, pequeño donde gran parte de la imagen es sombra suave. Un objeto más fino que unos 2 píxeles puede perder su sombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objetos animados lejanos en el trazado de rayos: actualizar cada 8 fotogramas"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Sombras de lâmpadas em meia resolução"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Na hora, desligado por padrão. Requer “Ray traced lamp shadows”. Primeiro traça um raio a cada 2x2 pixels e depois cada pixel onde as respostas ao redor diferem. Em um ponto pesado o passe de sombras de lâmpadas levou 0.38 ms em vez de 0.73 ms (cerca de +2.6% FPS) e nas imagens paradas não se viu diferença; um objeto mais fino que cerca de 2 pixels pode ficar sem sombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objetos animados distantes no traçado de raios: atualizar a cada 8 quadros"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Sombras de lâmpadas em meia resolução"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Na hora, desligado por padrão. Requer “Ray traced lamp shadows”. As sombras de lâmpadas continuam suaves, com custo menor: primeiro traça um pixel de cada bloco de 2x2 e depois cada pixel onde as respostas ao redor diferem, de modo que as bordas das sombras e as penumbras são traçadas por inteiro e só as áreas iluminadas ou escuras por igual compartilham a resposta de um bloco. A economia depende da cena: grande onde a luz das lâmpadas é uniforme, pequena onde boa parte da imagem é sombra suave. Um objeto mais fino que cerca de 2 pixels pode ficar sem sombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objetos animados distantes no traçado de raios: atualizar a cada 8 quadros"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Ombres des lampes en demi-résolution"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Immédiat, désactivé par défaut. Nécessite « Ray traced lamp shadows ». Trace d'abord un rayon par bloc de 2x2 pixels, puis chaque pixel où les réponses autour de lui diffèrent. À un endroit exigeant, la passe d'ombres des lampes a pris 0.38 ms au lieu de 0.73 ms (environ +2.6% FPS) et aucune différence n'était visible sur les images fixes ; un objet plus fin qu'environ 2 pixels peut perdre son ombre."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objets animés lointains dans le lancer de rayons : mise à jour toutes les 8 images"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Ombres des lampes en demi-résolution"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Immédiat, désactivé par défaut. Nécessite « Ray traced lamp shadows ». Les ombres des lampes restent douces, pour un coût moindre : trace d'abord un pixel de chaque bloc de 2x2, puis chaque pixel où les réponses autour de lui diffèrent ; les bords des ombres et les pénombres sont donc tracés en entier, et seules les zones uniformément éclairées ou uniformément sombres partagent la réponse d'un bloc. Le gain dépend de la vue : important là où la lumière des lampes est uniforme, faible là où une grande partie de l'image est en ombre douce. Un objet plus fin qu'environ 2 pixels peut perdre son ombre."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Objets animés lointains dans le lancer de rayons : mise à jour toutes les 8 images"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Lampenschatten in halber Auflösung"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Sofort wirksam, standardmäßig aus. Benötigt „Ray traced lamp shadows“. Verfolgt zuerst einen Strahl je 2x2 Pixel, dann jedes Pixel, wo die Antworten um es herum abweichen. An einer anspruchsvollen Stelle brauchte der Lampenschatten-Durchgang 0.38 ms statt 0.73 ms (etwa +2.6% FPS), auf Standbildern war kein Unterschied zu sehen; ein Objekt dünner als etwa 2 Pixel kann seinen Schatten verlieren."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Entfernte animierte Objekte im Raytracing: jedes 8. Bild aktualisieren"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Lampenschatten in halber Auflösung"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Sofort wirksam, standardmäßig aus. Benötigt „Ray traced lamp shadows“. Lampenschatten bleiben weich, bei geringeren Kosten: Verfolgt zuerst ein Pixel jedes 2x2-Blocks, dann jedes Pixel, wo die Antworten um es herum abweichen; Schattenkanten und Halbschatten werden also vollständig verfolgt, und nur gleichmäßig helle oder gleichmäßig dunkle Flächen teilen sich die Antwort eines Blocks. Die Ersparnis hängt von der Ansicht ab: groß, wo das Lampenlicht gleichmäßig ist, klein, wo ein großer Teil des Bildes weicher Schatten ist. Ein Objekt dünner als etwa 2 Pixel kann seinen Schatten verlieren."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Entfernte animierte Objekte im Raytracing: jedes 8. Bild aktualisieren"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Ombre delle lampade a metà risoluzione"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Subito attivo, disattivato di default. Richiede «Ray traced lamp shadows». Prima traccia un raggio ogni 2x2 pixel, poi ogni pixel dove le risposte intorno a esso differiscono. In un punto pesante il passaggio delle ombre delle lampade ha richiesto 0.38 ms invece di 0.73 ms (circa +2.6% FPS) e nelle immagini ferme non si vedeva differenza; un oggetto più sottile di circa 2 pixel può perdere la sua ombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Oggetti animati lontani nel ray tracing: aggiorna ogni 8 fotogrammi"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Ombre delle lampade a metà risoluzione"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Subito attivo, disattivato di default. Richiede «Ray traced lamp shadows». Le ombre delle lampade restano morbide, a un costo minore: prima traccia un pixel di ogni blocco 2x2, poi ogni pixel dove le risposte intorno a esso differiscono, così i bordi delle ombre e le penombre sono tracciati per intero e solo le zone illuminate o scure in modo uniforme condividono la risposta di un blocco. Il risparmio dipende dalla vista: grande dove la luce delle lampade è uniforme, piccolo dove gran parte dell'immagine è ombra morbida. Un oggetto più sottile di circa 2 pixel può perdere la sua ombra."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Oggetti animati lontani nel ray tracing: aggiorna ogni 8 fotogrammi"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Cienie lamp w połowie rozdzielczości"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Działa od razu, domyślnie wył. Wymaga „Ray traced lamp shadows”. Najpierw śledzi jeden promień na 2x2 piksele, potem każdy piksel tam, gdzie odpowiedzi wokół niego się różnią. W jednym wymagającym miejscu przebieg cieni lamp zajął 0.38 ms zamiast 0.73 ms (około +2.6% FPS), a na nieruchomych obrazach nie było widać różnicy; obiekt cieńszy niż około 2 piksele może stracić cień."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Odległe animowane obiekty w śledzeniu promieni: aktualizuj co 8 klatek"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Cienie lamp w połowie rozdzielczości"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Działa od razu, domyślnie wył. Wymaga „Ray traced lamp shadows”. Cienie lamp pozostają miękkie przy niższym koszcie: najpierw śledzi jeden piksel z każdego bloku 2x2, potem każdy piksel tam, gdzie odpowiedzi wokół niego się różnią, więc krawędzie cieni i półcienie są śledzone w całości, a odpowiedź bloku dzielą tylko obszary równomiernie oświetlone lub równomiernie ciemne. Zysk zależy od widoku: duży tam, gdzie światło lamp jest równomierne, mały tam, gdzie dużą część obrazu zajmuje miękki cień. Obiekt cieńszy niż około 2 piksele może stracić cień."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Odległe animowane obiekty w śledzeniu promieni: aktualizuj co 8 klatek"},
"""),
        (r"""    {"Half-resolution lamp shadows",
     "Yarım çözünürlükte lamba gölgeleri"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.",
     "Anında, varsayılan olarak kapalı. “Ray traced lamp shadows” gerekir. Önce her 2x2 piksel için bir ışın izler, sonra çevresindeki yanıtların farklı olduğu her pikseli izler. Yoğun bir noktada lamba gölgesi geçişi 0.73 ms yerine 0.38 ms sürdü (yaklaşık %2.6 daha fazla FPS) ve durağan görüntülerde fark görülmedi; yaklaşık 2 pikselden ince bir nesne gölgesini kaybedebilir."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Işın izlemede uzaktaki animasyonlu nesneler: her 8 karede güncelle"},
""",
         r"""    {"Half-resolution lamp shadows",
     "Yarım çözünürlükte lamba gölgeleri"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.",
     "Anında, varsayılan olarak kapalı. “Ray traced lamp shadows” gerekir. Lamba gölgeleri yumuşak kalır, maliyet düşer: önce her 2x2 bloğun bir pikselini izler, sonra çevresindeki yanıtların farklı olduğu her pikseli izler; böylece gölge kenarları ve yarı gölgeler tam olarak izlenir, bir bloğun yanıtını yalnızca eşit biçimde aydınlık veya eşit biçimde karanlık alanlar paylaşır. Kazanç görüntüye bağlıdır: lamba ışığının eşit olduğu yerde büyük, görüntünün büyük bölümünün yumuşak gölge olduğu yerde küçüktür. Yaklaşık 2 pikselden ince bir nesne gölgesini kaybedebilir."},
    {"Far animated objects in ray tracing: update every 8th frame",
     "Işın izlemede uzaktaki animasyonlu nesneler: her 8 karede güncelle"},
"""),
        (r"""    {"Live, off by default. Needs Ultra (Ray Traced Shadows) in Shadow rendering method. Traces one ray per 2x2 pixels first, then every pixel where those rays differ. At one heavy spot the sun shadow pass took 0.24 ms instead of 0.56 ms and still pictures looked the same; a shadow caster thinner than about 2 pixels can be missed. With Half-resolution lamp shadows and Fewer glossy reflection rays as well: 78.2 instead of 74.2 FPS there.", "即时生效，默认关闭。需要在 “Shadow rendering method” 中选择 “Ultra (Ray Traced Shadows)”。先为每个 2x2 像素块计算一次 RT 阴影，再在这些结果不同之处计算每个像素。在一处负载较重的位置，平行光阴影通道耗时从 0.56 ms 降到 0.24 ms，静止画面看不出差别；比约 2 像素更细的物体可能丢掉阴影。与 “半分辨率 RT 灯光阴影” 和 “高光反射：减少 RT 计算” 一起开启时：该处从 74.2 FPS 提高到 78.2 FPS。"},
    {"Half-resolution lamp shadows", "半分辨率 RT 灯光阴影"},
    {"Live, off by default. Needs Ray traced lamp shadows. Traces one ray per 2x2 pixels first, then every pixel where the answers around it differ. At one heavy spot the lamp shadow pass took 0.38 ms instead of 0.73 ms (about +2.6% FPS) and still pictures showed no difference; a shadow caster thinner than about 2 pixels can be missed.", "即时生效，默认关闭。需要开启 “Ray traced lamp shadows”。先为每个 2x2 像素块计算一次 RT 阴影，再在附近结果不同之处计算每个像素。在一处负载较重的位置，灯光阴影通道耗时从 0.73 ms 降到 0.38 ms（约 +2.6% FPS），静止画面看不出差别；比约 2 像素更细的物体可能丢掉阴影。"},
    {"Far animated objects in ray tracing: update every 8th frame", "RT 中远处的动画物体：每 8 帧更新一次"},
    {"Live, off by default. Needs Ultra (Ray Traced Shadows), Ray traced lamp shadows or Ultra (RTGI). An animated object that was only in the far sun shadow bands updates its ray tracing shape every 8th frame instead of every frame; on screen it still moves every frame. At one heavy spot about +2.5% FPS. The cost: the ray traced shadow of such an object can be up to 7 frames old.", "即时生效，默认关闭。需要 “Ultra (Ray Traced Shadows)”、“Ray traced lamp shadows” 或 “Ultra (RTGI)”。只出现在平行光阴影远处 2 级中的动画物体，其 RT 形状改为每 8 帧更新一次，而不是每帧更新；在画面上它仍每帧运动。在一处负载较重的位置约 +2.5% FPS。缺点：这类物体的 RT 阴影最多可能落后 7 帧。"},
""",
         r"""    {"Live, off by default. Needs Ultra (Ray Traced Shadows) in Shadow rendering method. Traces one ray per 2x2 pixels first, then every pixel where those rays differ. At one heavy spot the sun shadow pass took 0.24 ms instead of 0.56 ms and still pictures looked the same; a shadow caster thinner than about 2 pixels can be missed. With Half-resolution lamp shadows and Fewer glossy reflection rays as well: 78.2 instead of 74.2 FPS there.", "即时生效，默认关闭。需要在 “Shadow rendering method” 中选择 “Ultra (Ray Traced Shadows)”。先为每个 2x2 像素块计算一次 RT 阴影，再在这些结果不同之处计算每个像素。在一处负载较重的位置，平行光阴影通道耗时从 0.56 ms 降到 0.24 ms，静止画面看不出差别；比约 2 像素更细的物体可能丢掉阴影。与 “半分辨率 RT 灯光阴影” 和 “高光反射：减少 RT 计算” 一起开启时：该处从 74.2 FPS 提高到 78.2 FPS。"},
    {"Half-resolution lamp shadows", "半分辨率 RT 灯光阴影"},
    {"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft, at a lower cost: traces one pixel of every 2x2 block first, then every pixel where the answers around it differ, so shadow edges and soft rims are traced in full and only evenly lit or evenly dark areas share a block's answer. The saving depends on the view: large where lamp light is even, small where much of the picture is soft shadow. A shadow caster thinner than about 2 pixels can be missed.", "即时生效，默认关闭。需要开启 “Ray traced lamp shadows”。灯光阴影保持柔和，开销更低：先计算每个 2x2 像素块中的一个像素，再在附近结果不同之处计算每个像素；因此阴影边缘和半影会完整计算，只有受光均匀或均匀处于阴影中的区域共用像素块的结果。节省多少取决于画面：灯光均匀处节省得多，画面大部分是柔和阴影时节省得少。比约 2 像素更细的物体可能丢掉阴影。"},
    {"Far animated objects in ray tracing: update every 8th frame", "RT 中远处的动画物体：每 8 帧更新一次"},
    {"Live, off by default. Needs Ultra (Ray Traced Shadows), Ray traced lamp shadows or Ultra (RTGI). An animated object that was only in the far sun shadow bands updates its ray tracing shape every 8th frame instead of every frame; on screen it still moves every frame. At one heavy spot about +2.5% FPS. The cost: the ray traced shadow of such an object can be up to 7 frames old.", "即时生效，默认关闭。需要 “Ultra (Ray Traced Shadows)”、“Ray traced lamp shadows” 或 “Ultra (RTGI)”。只出现在平行光阴影远处 2 级中的动画物体，其 RT 形状改为每 8 帧更新一次，而不是每帧更新；在画面上它仍每帧运动。在一处负载较重的位置约 +2.5% FPS。缺点：这类物体的 RT 阴影最多可能落后 7 帧。"},
"""),
    ],
    TESTS + "test_lamp_shadow_tune.cpp": [
        (r"""// bbport (r42_lamp-soft): the area lamp's knobs, the frames of history, and the lamps of a pass
// told apart and followed from one frame to the next (LampTrack).
#include <array>
#include <bit>
""",
         r"""// bbport (r42_lamp-soft): the area lamp's knobs, the frames of history, and the lamps of a pass
// told apart and followed from one frame to the next (LampTrack).
// bbport (r44_half-area-lamp): which pass of a frame has the area lamp (LampPassRadius).
#include <array>
#include <bit>
"""),
        (r"""        const auto tail = LampHistoryTail(t);
        assert(std::abs(F(tail[0]) - 9.0f) < 1e-4f && F(tail[1]) == 0.25f && F(tail[2]) == 1.5f && F(tail[3]) == 2.0f);
    }
    // A cut: the way back to the camera of the frame before is more than 2 m or about 20 degrees.
""",
         r"""        const auto tail = LampHistoryTail(t);
        assert(std::abs(F(tail[0]) - 9.0f) < 1e-4f && F(tail[1]) == 0.25f && F(tail[2]) == 1.5f && F(tail[3]) == 2.0f);
    }
    // bbport (r44_half-area-lamp): the lamp's radius for one pass of a frame (takes the history,
    // half resolution, experiment 2305843009213693952 set).
    {
        const LampShadowTune d;
        // Full resolution: the pass that takes the history has the area lamp, a pass beside it
        // the point lamp; the experiment bit is about the half resolution only.
        assert(LampPassRadius(d, true, false, false) == 0.1f);
        assert(LampPassRadius(d, false, false, false) == 0.0f);
        assert(LampPassRadius(d, true, false, true) == 0.1f);
        assert(LampPassRadius(d, false, false, true) == 0.0f);
        // Half resolution: the same, and point lamps while the bit is set (the pass of before).
        assert(LampPassRadius(d, true, true, false) == 0.1f);
        assert(LampPassRadius(d, false, true, false) == 0.0f);
        assert(LampPassRadius(d, true, true, true) == 0.0f);
        assert(LampPassRadius(d, false, true, true) == 0.0f);
        // What the pass averages follows from the radius it got: with the bit set no history.
        LampShadowTune pass = d;
        pass.radius_m = LampPassRadius(d, true, true, false);
        assert(std::abs(LampHistoryFrames(pass) - 9.0f) < 1e-4f);
        pass.radius_m = LampPassRadius(d, true, true, true);
        assert(LampHistoryFrames(pass) == 0.0f);
        // BB_LAMP_SHADOW_HISTORY=0: every full-resolution pass shows the bare rays; a pass at
        // half resolution cannot share them among a block's pixels and has point lamps.
        LampShadowTune bare;
        bare.history = 0.0f;
        bare.radius_m = 0.25f;
        assert(LampPassRadius(bare, true, false, false) == 0.25f && LampPassRadius(bare, false, false, false) == 0.25f);
        assert(LampPassRadius(bare, true, true, false) == 0.0f && LampPassRadius(bare, false, true, false) == 0.0f);
        assert(LampPassRadius(bare, true, true, true) == 0.0f);
        // BB_LAMP_SHADOW_SOFT=0: a point lamp in every pass.
        LampShadowTune point;
        point.radius_m = 0.0f;
        for (int k = 0; k < 8; ++k) {
            assert(LampPassRadius(point, (k & 1) != 0, (k & 2) != 0, (k & 4) != 0) == 0.0f);
        }
    }
    // A cut: the way back to the camera of the frame before is more than 2 m or about 20 degrees.
"""),
    ],
    TESTS + "test_rt_shadows.cpp": [
        (r"""            };
            Vulkan::LampTrack track;
            const auto run = [&](const Views& v, const Pass& pass) {
                auto* words = static_cast<float*>(lights.data);
""",
         r"""            };
            Vulkan::LampTrack track;
            // bbport (r44_half-area-lamp): whether the half-resolution build counts what it does
            // (MODE_HALF_COUNT). Off while it is timed: the counters are in host memory here, where
            // the shader's atomic adds cost fifty times the pass (the engine keeps them on the GPU
            // and counts one pass in eight).
            bool half_count = true;
            const auto run = [&](const Views& v, const Pass& pass) {
                auto* words = static_cast<float*>(lights.data);
"""),
        (r"""                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 11, writes.data());
                    unsigned word = mode | 2u | 8u; // MODE_HALF_FIRST | MODE_HALF_COUNT
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 15) / 16, (H + 15) / 16, 1);
                    vk.Barrier();
                    word = mode | 4u | 8u; // MODE_HALF_FILL | MODE_HALF_COUNT
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
""",
         r"""                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 11, writes.data());
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
                    unsigned word = mode | 2u | count; // MODE_HALF_FIRST
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 15) / 16, (H + 15) / 16, 1);
                    vk.Barrier();
                    word = mode | 4u | count; // MODE_HALF_FILL
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
"""),
        (r"""                track.End(false);
            };
            // One frame as the engine runs it. before: the camera of the frame before.
            const auto frame = [&](const Views& v, const Vulkan::LampShadowTune& tune, const Views* before = nullptr,
                                   bool follow = true) {
                const bool history = Vulkan::LampHistoryFrames(tune) > 0.0f;
                const double ms = run(v, {.tune = &tune, .frame = clock, .parity = history ? int(clock & 1u) : -1,
                                          .read = have_history && history, .before = before, .follow = follow});
                have_history = history;
                ++clock;
""",
         r"""                track.End(false);
            };
            // bbport (r44_half-area-lamp): at_half: `frame` and `held_view` run the half-resolution build
            // (with the same history block: PointShadow::Flush hands both builds the same words).
            // half_did: what its two passes did since the counters were last zeroed (the shader's
            // half_counts words); traced_share: the share of the second pass's pixels that cast their
            // own rays, in percent.
            bool at_half = false;
            using HalfDid = std::array<std::uint32_t, 16>;
            const auto half_zero = [&] { std::memset(half_counts.data, 0, 64); };
            const auto half_did = [&] {
                HalfDid did{};
                std::memcpy(did.data(), half_counts.data, 64);
                return did;
            };
            const auto traced_share = [](const HalfDid& did) {
                const double all = double(did[4]) + double(did[5]) + double(did[7]);
                return all > 0.0 ? 100.0 * double(did[5]) / all : 0.0;
            };
            // One frame as the engine runs it. before: the camera of the frame before.
            const auto frame = [&](const Views& v, const Vulkan::LampShadowTune& tune, const Views* before = nullptr,
                                   bool follow = true) {
                const bool history = Vulkan::LampHistoryFrames(tune) > 0.0f;
                const double ms = run(v, {.tune = &tune, .frame = clock, .parity = history ? int(clock & 1u) : -1,
                                          .read = have_history && history, .before = before, .follow = follow,
                                          .half = at_half});
                have_history = history;
                ++clock;
"""),
        (r"""                shown.view = 5;
                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .again = true});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
                for (float& p : picture) p = p > 0.75f ? -1.0f : 1.0f - 2.0f * p;
""",
         r"""                shown.view = 5;
                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .half = at_half, .again = true});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
                for (float& p : picture) p = p > 0.75f ? -1.0f : 1.0f - 2.0f * p;
"""),
        (r"""            // Mean difference from `reference`: over the picture, over the reference's penumbra
            // (0.05 to 0.95), and the share of pixels more than 0.25 off, in percent.
            struct Off { double all = 0, penumbra = 0, far = 0; };
            const auto off = [&](const std::vector<float>& picture, const std::vector<float>& reference) {
                Off o;
                std::size_t soft = 0;
                for (std::size_t i = 0; i < picture.size(); ++i) {
                    const double d = std::abs(double(picture[i]) - reference[i]);
                    o.all += d;
""",
         r"""            // Mean difference from `reference`: over the picture, over the reference's penumbra
            // (0.05 to 0.95), and the share of pixels more than 0.25 off, in percent.
            // bbport (r44_half-area-lamp): part 1: over pixel (2x, 2y) of every 2x2 block alone, which
            // the half-resolution build's first pass works out; part 0: over the other three, its
            // second pass's. A fault of one of the two passes shows as a difference between these.
            struct Off { double all = 0, penumbra = 0, far = 0; };
            const auto off = [&](const std::vector<float>& picture, const std::vector<float>& reference, int part = -1) {
                Off o;
                std::size_t soft = 0, count = 0;
                for (std::size_t i = 0; i < picture.size(); ++i) {
                    if (part >= 0 && int((i % W) % 2 == 0 && (i / W) % 2 == 0) != part) continue;
                    ++count;
                    const double d = std::abs(double(picture[i]) - reference[i]);
                    o.all += d;
"""),
        (r"""                    }
                }
                o.all /= double(picture.size());
                o.far *= 100.0 / double(picture.size());
                o.penumbra /= double(std::max<std::size_t>(soft, 1));
                return o;
""",
         r"""                    }
                }
                o.all /= double(std::max<std::size_t>(count, 1));
                o.far *= 100.0 / double(std::max<std::size_t>(count, 1));
                o.penumbra /= double(std::max<std::size_t>(soft, 1));
                return o;
"""),
        (r"""            point.radius_m = 0.0f;
            const Views view = camera(0.0f, 0.0f);

            // 1. The point lamp: the same picture whatever the frame counter, and no history.
""",
         r"""            point.radius_m = 0.0f;
            const Views view = camera(0.0f, 0.0f);
            // bbport (r44_half-area-lamp): how much further from the true picture the half-resolution
            // build may be than the full-resolution pass in the same scene (over all pixels, over the
            // penumbra) before a check fails.
            constexpr double HalfAllMost = 1.25, HalfPenumbraMost = 1.25;

            // 1. The point lamp: the same picture whatever the frame counter, and no history.
"""),
        (r"""            Views moved_view = view;
            std::vector<float> moved_held; // held_view of the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr) {
""",
         r"""            Views moved_view = view;
            std::vector<float> moved_held; // held_view of the last frame
            HalfDid moved_did{};           // at_half: what the two passes did on the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr) {
"""),
        (r"""                    }
                    place(now, walked, move.other * float(k));
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                }
                if (upscaled_out) *upscaled_out = std::move(held);
                moved_view = now;
""",
         r"""                    }
                    place(now, walked, move.other * float(k));
                    if (k == move.frames) half_zero();
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                }
                moved_did = half_did();
                if (upscaled_out) *upscaled_out = std::move(held);
                moved_view = now;
"""),
        (r"""                const auto untrailed = moving(loose, walk);
                const auto untrailed_held = moved_held;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), c = off(guarded, moved_true), d = off(all, moved_true),
                          e = off(untrailed, moved_true);
                const std::string tag = speed > 0.05f ? "run" : "walk";
                dump(tag + "_true", moved_true);
""",
         r"""                const auto untrailed = moving(loose, walk);
                const auto untrailed_held = moved_held;
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build
                at_half = true;
                const auto halved = moving(soft, walk);
                const auto halved_held = moved_held;
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), c = off(guarded, moved_true), d = off(all, moved_true),
                          e = off(untrailed, moved_true), h = off(halved, moved_true);
                const std::string tag = speed > 0.05f ? "run" : "walk";
                dump(tag + "_true", moved_true);
"""),
        (r"""                            "the history without its guards %.4f / %.4f / %.2f%%; the default %.4f / %.4f / %.2f%% "
                            "(history held in the penumbra: %.2f of what it may); looked up where the ground was only "
                            "%.4f / %.4f / %.2f%%; with BB_LAMP_SHADOW_TRAIL=0 %.4f / %.4f / %.2f%% (held %.2f)\n",
                            speed * 100.0f, a.all, a.penumbra, a.far, d.all, d.penumbra, d.far,
                            held_mean(all_held, moved_true), c.all, c.penumbra, c.far, e.all, e.penumbra, e.far,
                            held_mean(untrailed_held, moved_true));
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
                    std::fprintf(stderr, "the guards, or following the lamp, do not help a carried torch\n");
                    return 1;
                }
""",
         r"""                            "the history without its guards %.4f / %.4f / %.2f%%; the default %.4f / %.4f / %.2f%% "
                            "(history held in the penumbra: %.2f of what it may); looked up where the ground was only "
                            "%.4f / %.4f / %.2f%%; with BB_LAMP_SHADOW_TRAIL=0 %.4f / %.4f / %.2f%% (held %.2f); the "
                            "default in the half-resolution build %.4f / %.4f / %.2f%% (held %.2f; its second pass "
                            "traced %.1f%% of its pixels on that frame)\n",
                            speed * 100.0f, a.all, a.penumbra, a.far, d.all, d.penumbra, d.far,
                            held_mean(all_held, moved_true), c.all, c.penumbra, c.far, e.all, e.penumbra, e.far,
                            held_mean(untrailed_held, moved_true), h.all, h.penumbra, h.far,
                            held_mean(halved_held, moved_true), traced_share(halved_did));
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
                    std::fprintf(stderr, "the guards, or following the lamp, do not help a carried torch\n");
                    return 1;
                }
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a carried torch looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
"""),
        (r"""                const Move other{.other = 0.05f};
                const auto alone = moving(plain, other), all = moving(soft, other, &held);
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), d = off(all, moved_true), e = off(held, moved_true);
                const std::string tag = two ? "other_two_lamps" : "other";
                dump(tag + "_true", moved_true);
                dump(tag + "_history_alone", alone);
                dump(tag + "_default", all);
                dump(tag + "_default_upscaled", held);
                // And the frames one by one without a history, through the stand-in alone.
                Vulkan::LampShadowTune single = soft;
""",
         r"""                const Move other{.other = 0.05f};
                const auto alone = moving(plain, other), all = moving(soft, other, &held);
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build. Its
                // first pass bounds a pixel's history by the answers of the blocks around it, which
                // lie twice as far apart as the pixels around a full-resolution pixel, so behind a
                // shadow's moving edge that one pixel in four could trail as dots: its error is
                // given for those pixels and for the other three apart (off's part), beside the
                // full-resolution pass's on the same pixels.
                at_half = true;
                const auto halved = moving(soft, other);
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), d = off(all, moved_true), e = off(held, moved_true),
                          h = off(halved, moved_true);
                const std::array<Off, 2> half_part{off(halved, moved_true, 1), off(halved, moved_true, 0)},
                                         full_part{off(all, moved_true, 1), off(all, moved_true, 0)};
                const std::string tag = two ? "other_two_lamps" : "other";
                dump(tag + "_true", moved_true);
                dump(tag + "_history_alone", alone);
                dump(tag + "_default", all);
                dump(tag + "_default_upscaled", held);
                dump(tag + "_half", halved);
                // And the frames one by one without a history, through the stand-in alone.
                Vulkan::LampShadowTune single = soft;
"""),
        (r"""                    return 1;
                }
            }
            // A caster is gone from one frame to the next (the second figure, set 30 m off): how
""",
         r"""                    return 1;
                }
                std::printf("Torch lab, that figure under %s in the half-resolution build: %.4f / %.4f / %.2f%% (its second "
                            "pass traced %.1f%% of its pixels on that frame); pixel (2x,2y) of each block alone %.4f / "
                            "%.4f / %.2f%%, the other three %.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%% "
                            "and %.4f / %.4f / %.2f%%)\n",
                            two ? "the still torch and a second lamp" : "the still torch", h.all, h.penumbra, h.far,
                            traced_share(halved_did), half_part[0].all, half_part[0].penumbra, half_part[0].far,
                            half_part[1].all, half_part[1].penumbra, half_part[1].far, full_part[0].all,
                            full_part[0].penumbra, full_part[0].far, full_part[1].all, full_part[1].penumbra,
                            full_part[1].far);
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a moving caster looks worse in the half-resolution build than at full resolution (%s)\n",
                                 tag.c_str());
                    return 1;
                }
                if (checked && !(half_part[0].all < HalfAllMost * half_part[1].all &&
                                 half_part[0].penumbra < HalfPenumbraMost * half_part[1].penumbra)) {
                    std::fprintf(stderr, "behind a moving caster the half-resolution build's first-pass pixels trail the other "
                                         "three of their blocks (%s)\n", tag.c_str());
                    return 1;
                }
            }
            // A caster is gone from one frame to the next (the second figure, set 30 m off): how
"""),
        (r"""            for (const bool two : {false, true}) {
                second = two;
                std::array<std::array<double, 5>, 2> left{};
                place(view, 0.0f, 0.0f);
                const auto old_true = truth(view, soft, 64);
                place(view, 0.0f, 30.0f);
                const auto new_true = truth(view, soft, 64);
                for (int which = 0; which < 2; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 0 ? soft : plain;
                    restart();
                    place(view, 0.0f, 0.0f);
""",
         r"""            for (const bool two : {false, true}) {
                second = two;
                // (which: 0 the default, 1 the history without its guards; bbport r44_half-area-lamp:
                // 2 the default in the half-resolution build)
                std::array<std::array<double, 5>, 3> left{};
                place(view, 0.0f, 0.0f);
                const auto old_true = truth(view, soft, 64);
                place(view, 0.0f, 30.0f);
                const auto new_true = truth(view, soft, 64);
                for (int which = 0; which < 3; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 1 ? plain : soft;
                    at_half = which == 2;
                    restart();
                    place(view, 0.0f, 0.0f);
"""),
        (r"""                    }
                }
                std::printf("Torch lab, a figure is gone from one frame to the next, %s: share of the old picture left "
                            "where the true one changed, after 1 / 2 / 4 / 8 / 16 frames: the default %.3f / %.3f / %.3f "
                            "/ %.3f / %.3f; the history without its guards %.3f / %.3f / %.3f / %.3f / %.3f\n",
                            two ? "two lamps" : "one lamp", left[0][0], left[0][1], left[0][2], left[0][3], left[0][4],
                            left[1][0], left[1][1], left[1][2], left[1][3], left[1][4]);
                if (checked && !(left[0][1] < 0.2 && left[0][2] < 0.15 && left[0][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers (%s)\n", two ? "two lamps" : "one lamp");
                    return 1;
                }
""",
         r"""                    }
                }
                at_half = false;
                std::printf("Torch lab, a figure is gone from one frame to the next, %s: share of the old picture left "
                            "where the true one changed, after 1 / 2 / 4 / 8 / 16 frames: the default %.3f / %.3f / %.3f "
                            "/ %.3f / %.3f; the history without its guards %.3f / %.3f / %.3f / %.3f / %.3f; the default "
                            "in the half-resolution build %.3f / %.3f / %.3f / %.3f / %.3f\n",
                            two ? "two lamps" : "one lamp", left[0][0], left[0][1], left[0][2], left[0][3], left[0][4],
                            left[1][0], left[1][1], left[1][2], left[1][3], left[1][4], left[2][0], left[2][1],
                            left[2][2], left[2][3], left[2][4]);
                if (checked && !(left[0][1] < 0.2 && left[0][2] < 0.15 && left[0][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers (%s)\n", two ? "two lamps" : "one lamp");
                    return 1;
                }
                if (checked && !(left[2][1] < 0.2 && left[2][2] < 0.15 && left[2][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers in the half-resolution build (%s)\n",
                                 two ? "two lamps" : "one lamp");
                    return 1;
                }
"""),
        (r"""                const auto all_held = moved_held;
                const auto unfollowed = moving(soft, anchored);
                const auto moved_true = truth(moved_view, soft);
                wobble = {0, 0, 0};
                const Off d = off(all, moved_true), c = off(unfollowed, moved_true);
                dump("flicker_true", moved_true);
                dump("flicker_default", all);
                std::printf("Torch lab, the torch's lamp is up to 2 cm off its place, anew every frame, the 24th frame "
                            "against its true picture: the default %.4f / %.4f / %.2f%% (history held in the penumbra: "
                            "%.2f of what it may); looked up where the ground was only %.4f / %.4f / %.2f%%\n",
                            d.all, d.penumbra, d.far, held_mean(all_held, moved_true), c.all, c.penumbra, c.far);
            }

""",
         r"""                const auto all_held = moved_held;
                const auto unfollowed = moving(soft, anchored);
                // bbport (r44_half-area-lamp): the default once more in the half-resolution build
                at_half = true;
                const auto halved = moving(soft, shaken);
                const auto halved_held = moved_held;
                const HalfDid halved_did = moved_did;
                at_half = false;
                const auto moved_true = truth(moved_view, soft);
                wobble = {0, 0, 0};
                const Off d = off(all, moved_true), c = off(unfollowed, moved_true), h = off(halved, moved_true);
                dump("flicker_true", moved_true);
                dump("flicker_default", all);
                dump("flicker_half", halved);
                std::printf("Torch lab, the torch's lamp is up to 2 cm off its place, anew every frame, the 24th frame "
                            "against its true picture: the default %.4f / %.4f / %.2f%% (history held in the penumbra: "
                            "%.2f of what it may); looked up where the ground was only %.4f / %.4f / %.2f%%; the default "
                            "in the half-resolution build %.4f / %.4f / %.2f%% (held %.2f; its second pass traced %.1f%% "
                            "of its pixels on that frame)\n",
                            d.all, d.penumbra, d.far, held_mean(all_held, moved_true), c.all, c.penumbra, c.far, h.all,
                            h.penumbra, h.far, held_mean(halved_held, moved_true), traced_share(halved_did));
                if (checked && !(h.all < HalfAllMost * d.all && h.penumbra < HalfPenumbraMost * d.penumbra)) {
                    std::fprintf(stderr, "a flickering lamp looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
            }

"""),
        (r"""            // not (as if the camera had stood still).
            {
                std::array<Off, 2> offs{};
                std::vector<float> pan_true;
                for (const bool with_camera : {true, false}) {
                    restart();
                    Views before = view;
                    for (unsigned k = 0; k <= 24; ++k) {
                        const Views now = camera(0.03f * float(k), 0.0f);
                        place(now, 0.0f, 0.0f);
                        frame(now, soft, with_camera ? &before : nullptr);
                        before = now;
                    }
                    const auto picture = values();
                    if (with_camera) {
                        pan_true = truth(before, soft);
                        dump("pan_true", pan_true);
                        dump("pan_default", picture);
                    }
                    offs[with_camera ? 0 : 1] = off(picture, pan_true);
                }
                std::printf("Torch lab, the camera moves 3 cm a frame, the 25th frame against its true picture: %.4f / "
                            "%.4f / %.2f%%; with the history left where it was on screen %.4f / %.4f / %.2f%%\n",
                            offs[0].all, offs[0].penumbra, offs[0].far, offs[1].all, offs[1].penumbra, offs[1].far);
                if (checked && !(offs[0].penumbra < offs[1].penumbra)) {
                    std::fprintf(stderr, "the history does not follow the camera\n");
                    return 1;
                }
            }

            // 6. The half-resolution build keeps the point lamp whatever the radius.
            place(view, 0.0f, 0.0f);
            run(view, {.tune = &soft, .frame = 3, .half = true});
            {
                const auto half_picture = values();
                std::size_t differ = 0;
                for (std::size_t i = 0; i < half_picture.size(); ++i) {
                    differ += std::abs(half_picture[i] - point_picture[i]) > 1.0f / 64.0f ? 1 : 0;
                }
                std::printf("Torch lab: the half-resolution build with the default tuning differs from the point lamp at "
                            "full resolution on %zu pixels\n", differ);
                if (differ * 500 > half_picture.size()) {
                    std::fprintf(stderr, "the half-resolution build does not show the point lamp\n");
                    return 1;
                }
""",
         r"""            // not (as if the camera had stood still).
            {
                // (which: 0 the history follows the camera, 1 it does not; bbport r44_half-area-lamp:
                // 2 as 0 in the half-resolution build)
                std::array<Off, 3> offs{};
                std::vector<float> pan_true;
                HalfDid pan_did{};
                for (const int which : {0, 1, 2}) {
                    at_half = which == 2;
                    restart();
                    Views before = view;
                    for (unsigned k = 0; k <= 24; ++k) {
                        const Views now = camera(0.03f * float(k), 0.0f);
                        place(now, 0.0f, 0.0f);
                        if (k == 24) half_zero();
                        frame(now, soft, which != 1 ? &before : nullptr);
                        before = now;
                    }
                    const auto picture = values();
                    if (which == 0) {
                        pan_true = truth(before, soft);
                        dump("pan_true", pan_true);
                        dump("pan_default", picture);
                    } else if (which == 2) {
                        pan_did = half_did();
                        dump("pan_half", picture);
                    }
                    offs[std::size_t(which)] = off(picture, pan_true);
                }
                at_half = false;
                std::printf("Torch lab, the camera moves 3 cm a frame, the 25th frame against its true picture: %.4f / "
                            "%.4f / %.2f%%; with the history left where it was on screen %.4f / %.4f / %.2f%%; in the "
                            "half-resolution build %.4f / %.4f / %.2f%% (its second pass traced %.1f%% of its pixels on "
                            "that frame)\n",
                            offs[0].all, offs[0].penumbra, offs[0].far, offs[1].all, offs[1].penumbra, offs[1].far,
                            offs[2].all, offs[2].penumbra, offs[2].far, traced_share(pan_did));
                if (checked && !(offs[0].penumbra < offs[1].penumbra)) {
                    std::fprintf(stderr, "the history does not follow the camera\n");
                    return 1;
                }
                if (checked && !(offs[2].all < HalfAllMost * offs[0].all && offs[2].penumbra < HalfPenumbraMost * offs[0].penumbra)) {
                    std::fprintf(stderr, "a moving camera looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
            }

            // 6. The half-resolution build on the still scene (bbport r44_half-area-lamp; its
            // moving scenes are in 4 and 5).
            place(view, 0.0f, 0.0f);
            // Without a history it keeps the point lamp whatever the radius (one bare ray to a
            // point of the lamp's disc cannot be shared by the four pixels of a block), and it is the
            // picture of the radius zeroed: what the pass hands it while experiment
            // 2305843009213693952 is set, the half-resolution pass of before r44.
            HalfDid point_did{};
            {
                run(view, {.tune = &soft, .frame = 3, .half = true});
                const auto bare_picture = values();
                half_zero();
                run(view, {.tune = &point, .frame = 3, .half = true});
                point_did = half_did();
                const auto half_point = values();
                std::size_t differ = 0;
                for (std::size_t i = 0; i < half_point.size(); ++i) {
                    differ += std::abs(half_point[i] - point_picture[i]) > 1.0f / 64.0f ? 1 : 0;
                }
                std::printf("Torch lab: the half-resolution build with point lamps (the radius zeroed, as with experiment "
                            "2305843009213693952 set) differs from the point lamp at full resolution on %zu pixels; with "
                            "the default tuning and no history it shows %s\n",
                            differ, bare_picture == half_point ? "that same picture" : "another picture");
                if (differ * 500 > half_point.size() || bare_picture != half_point) {
                    std::fprintf(stderr, "the half-resolution build without a history does not show the point lamp\n");
                    return 1;
                }
            }
            // With its history it shows the area lamp: 48 frames as in 2, against the same true
            // picture and beside the full-resolution pass's numbers, and what its two passes did on
            // the first frame (no history yet: bare rays) and on the last.
            {
                restart();
                at_half = true;
                std::vector<float> half1, half16;
                HalfDid first_did{};
                for (unsigned k = 0; k < 48; ++k) {
                    if (k == 0 || k == 47) half_zero();
                    frame(view, soft);
                    if (k == 0) {
                        first_did = half_did();
                        half1 = values();
                    }
                    if (k == 15) half16 = values();
                }
                const HalfDid did = half_did();
                const auto half48 = values();
                const auto half_held = held_view(view, soft);
                at_half = false;
                dump("half_16_frames", half16);
                dump("half_48_frames", half48);
                const Off h16 = off(half16, reference), h48 = off(half48, reference);
                double half_mean = 0, half_band = 0;
                for (const float p : half48) half_mean += p / double(half48.size());
                for (const std::size_t i : band) half_band += half48[i] / double(std::max<std::size_t>(band.size(), 1));
                std::size_t half_dark = 0;
                for (const std::size_t i : body) half_dark += half48[i] < 0.25f ? 1 : 0;
                std::printf("Torch lab, the half-resolution build with its history, the still scene against the true "
                            "picture (all / penumbra / more than 0.25 off): 16 frames %.4f / %.4f / %.2f%%, 48 frames "
                            "%.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%% and %.4f / %.4f / %.2f%%); "
                            "history held in the penumbra %.2f of what it may; mean light %.4f (true %.4f); the stick's "
                            "band keeps %.3f of the light (at full resolution %.3f, true %.3f), %zu of the %zu dark pixels "
                            "of the bodies' shadows are still below 0.25\n",
                            h16.all, h16.penumbra, h16.far, h48.all, h48.penumbra, h48.far, off16.all, off16.penumbra,
                            off16.far, off48.all, off48.penumbra, off48.far, held_mean(half_held, reference), half_mean,
                            mean_true, half_band, band_light, band_true, half_dark, body.size());
                const auto tell = [&](const char* when, const HalfDid& n) {
                    std::printf("Torch lab, the half-resolution build, %s: the first pass traced %u pixels with %u rays; "
                                "of the second pass's pixels %u took their block's answer and %u cast their own rays (%u "
                                "rays; %u a block near them had no answer, %u the blocks' answers differed, %u another "
                                "surface): %.1f%% traced\n",
                                when, n[1], n[2], n[4], n[5], n[6], n[10], n[11], n[12], traced_share(n));
                };
                tell("point lamps without a history (before r44)", point_did);
                tell("the area lamp's first frame (no history to read)", first_did);
                tell("the area lamp's 48th frame", did);
                // The first frame has bare rays (so has the frame after a camera cut). The second pass
                // shares them only where those of the nine blocks around a pixel agree, so no block
                // stands out from the blocks around it; the frame is held to the bound of the other
                // scenes against the full-resolution pass's first frame.
                const Off h1 = off(half1, reference);
                dump("half_1_frame", half1);
                std::printf("Torch lab, the half-resolution build's first frame (no history to read) against the true "
                            "picture: %.4f / %.4f / %.2f%% (at full resolution %.4f / %.4f / %.2f%%)\n",
                            h1.all, h1.penumbra, h1.far, off1.all, off1.penumbra, off1.far);
                if (checked && !(h1.all < HalfAllMost * off1.all && h1.penumbra < HalfPenumbraMost * off1.penumbra)) {
                    std::fprintf(stderr, "the half-resolution build's first frame is worse than the full-resolution pass's\n");
                    return 1;
                }
                if (checked && (std::abs(half_mean - mean_true) > 0.004 || half_band < 0.5 || half_dark * 2 < body.size())) {
                    std::fprintf(stderr, "the half-resolution build does not show the area lamp: mean light %.4f against "
                                         "the true %.4f, %.3f of the light in the stick's band, %zu of %zu dark pixels\n",
                                 half_mean, mean_true, half_band, half_dark, body.size());
                    return 1;
                }
                if (checked && !(h48.all < HalfAllMost * off48.all && h48.penumbra < HalfPenumbraMost * off48.penumbra)) {
                    std::fprintf(stderr, "the still scene looks worse in the half-resolution build than at full resolution\n");
                    return 1;
                }
                // (A second pass that shared nothing would be the full-resolution pass in two
                // dispatches; one that traced nothing would have no penumbra.)
                if (checked && (did[4] == 0 || did[5] == 0 || did[5] >= did[4])) {
                    std::fprintf(stderr, "the half-resolution build's second pass shares too little, or traces nothing\n");
                    return 1;
                }
"""),
        (r"""            // taken in turn, the history's clear included.
            {
                std::array<double, 3> best{1e9, 1e9, 1e9};
                restart();
                for (int i = 0; i < 40; ++i) {
""",
         r"""            // taken in turn, the history's clear included.
            {
                std::array<double, 5> best{1e9, 1e9, 1e9, 1e9, 1e9};
                restart();
                for (int i = 0; i < 40; ++i) {
"""),
        (r"""                    best[2] = std::min(best[2], frame(view, soft));
                }
                std::printf("Torch lab: mode 0 of this shader (the experiment bit's path; not the shader before r41) %.3f ms, the point lamp %.3f ms, the area lamp with its "
                            "history %.3f ms\n", best[0], best[1], best[2]);
            }
            vk.destroy_as(vk.device, tlas.handle, nullptr);
""",
         r"""                    best[2] = std::min(best[2], frame(view, soft));
                }
                // bbport (r44_half-area-lamp): the half-resolution build, with point lamps (before
                // r44) and with the area lamp and its history (once that has settled: its first
                // frames trace more), without its counters
                restart();
                at_half = true;
                half_count = false;
                for (int i = 0; i < 48; ++i) {
                    best[3] = std::min(best[3], run(view, {.tune = &point, .frame = unsigned(i), .half = true}));
                    const double ms = frame(view, soft);
                    if (i >= 8) best[4] = std::min(best[4], ms);
                }
                half_count = true;
                at_half = false;
                std::printf("Torch lab: mode 0 of this shader (the experiment bit's path; not the shader before r41) %.3f ms, the point lamp %.3f ms, the area lamp with its "
                            "history %.3f ms; the half-resolution build: with point lamps %.3f ms, with the area lamp "
                            "and its history %.3f ms\n", best[0], best[1], best[2], best[3], best[4]);
            }
            vk.destroy_as(vk.device, tlas.handle, nullptr);
"""),
    ],
    LAUNCH + "BloodborneLauncher/Views/GraphicsPage.cs": [
        (r"""                L.T("Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default."),
""",
         r"""                L.T("Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default."),
"""),
    ],
    LAUNCH + "LanternLauncher/Views/GraphicsPage.cs": [
        (r"""                L.T("Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default."),
""",
         r"""                L.T("Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default."),
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/de.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Schnellere Raytracing-Lampenschatten: etwa +2,6 % FPS an einer anspruchsvollen Stelle. Ein Objekt dünner als etwa 2 Pixel kann seinen Schatten verlieren. Benötigt „Ray traced lamp shadows“ aus dem Spielmenü. Standardmäßig aus.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Schnellere Raytracing-Lampenschatten. Ein Objekt dünner als etwa 2 Pixel kann seinen Schatten verlieren. Benötigt „Ray traced lamp shadows“ aus dem Spielmenü. Standardmäßig aus.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/es.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Sombras de lámparas trazadas más rápidas: alrededor de +2,6 % de FPS en un punto exigente. Un objeto más fino que unos 2 píxeles puede perder su sombra. Requiere «Ray traced lamp shadows», que está en el menú del juego. Desactivado por defecto.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Sombras de lámparas trazadas más rápidas. Un objeto más fino que unos 2 píxeles puede perder su sombra. Requiere «Ray traced lamp shadows», que está en el menú del juego. Desactivado por defecto.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/fr.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Ombres des lampes tracées plus rapides : environ +2,6 % de FPS à un endroit exigeant. Un objet plus fin qu'environ 2 pixels peut perdre son ombre. Nécessite « Ray traced lamp shadows », qui se trouve dans le menu en jeu. Désactivé par défaut.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Ombres des lampes tracées plus rapides. Un objet plus fin qu'environ 2 pixels peut perdre son ombre. Nécessite « Ray traced lamp shadows », qui se trouve dans le menu en jeu. Désactivé par défaut.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/it.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Ombre delle lampade tracciate più veloci: circa +2,6% di FPS in un punto pesante. Un oggetto più sottile di circa 2 pixel può perdere la sua ombra. Richiede «Ray traced lamp shadows», che si trova nel menu in gioco. Disattivato per impostazione predefinita.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Ombre delle lampade tracciate più veloci. Un oggetto più sottile di circa 2 pixel può perdere la sua ombra. Richiede «Ray traced lamp shadows», che si trova nel menu in gioco. Disattivato per impostazione predefinita.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/ja.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "レイトレーシングによるランプの影が速くなります。負荷の高いある場面で FPS 約 +2.6% でした。約 2 ピクセルより細い物体は影が消えることがあります。ゲーム内メニューの「Ray traced lamp shadows」が必要です。既定ではオフです。",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "レイトレーシングによるランプの影が速くなります。約 2 ピクセルより細い物体は影が消えることがあります。ゲーム内メニューの「Ray traced lamp shadows」が必要です。既定ではオフです。",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/ko.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "레이 트레이싱 램프 그림자가 빨라집니다. 부하가 큰 한 장면에서 FPS가 약 +2.6% 올랐습니다. 약 2픽셀보다 얇은 물체는 그림자가 사라질 수 있습니다. 게임 내 메뉴의 'Ray traced lamp shadows'가 필요합니다. 기본값은 꺼짐입니다.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "레이 트레이싱 램프 그림자가 빨라집니다. 약 2픽셀보다 얇은 물체는 그림자가 사라질 수 있습니다. 게임 내 메뉴의 'Ray traced lamp shadows'가 필요합니다. 기본값은 꺼짐입니다.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/pl.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Szybsze śledzone cienie lamp: około +2,6% FPS w jednym wymagającym miejscu. Obiekt cieńszy niż około 2 piksele może stracić cień. Wymaga „Ray traced lamp shadows” z menu w grze. Domyślnie wyłączone.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Szybsze śledzone cienie lamp. Obiekt cieńszy niż około 2 piksele może stracić cień. Wymaga „Ray traced lamp shadows” z menu w grze. Domyślnie wyłączone.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/pt-BR.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Sombras de lâmpadas traçadas mais rápidas: cerca de +2,6% de FPS em um ponto pesado. Um objeto mais fino que cerca de 2 pixels pode ficar sem sombra. Requer “Ray traced lamp shadows”, que fica no menu do jogo. Desativado por padrão.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Sombras de lâmpadas traçadas mais rápidas. Um objeto mais fino que cerca de 2 pixels pode ficar sem sombra. Requer “Ray traced lamp shadows”, que fica no menu do jogo. Desativado por padrão.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/ru.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Более быстрые трассированные тени ламп: около +2,6% FPS в одном тяжёлом месте. Предмет тоньше примерно 2 пикселей может остаться без тени. Нужны «Трассированные тени ламп» из внутриигрового меню. По умолчанию выключено.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Более быстрые трассированные тени ламп. Предмет тоньше примерно 2 пикселей может остаться без тени. Нужны «Трассированные тени ламп» из внутриигрового меню. По умолчанию выключено.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/tr.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Daha hızlı ışın izlemeli lamba gölgeleri: yoğun bir noktada yaklaşık +%2,6 FPS. Yaklaşık 2 pikselden ince bir nesne gölgesini kaybedebilir. Oyun içi menüdeki \"Ray traced lamp shadows\" gerekir. Varsayılan olarak kapalıdır.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Daha hızlı ışın izlemeli lamba gölgeleri. Yaklaşık 2 pikselden ince bir nesne gölgesini kaybedebilir. Oyun içi menüdeki \"Ray traced lamp shadows\" gerekir. Varsayılan olarak kapalıdır.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/uk.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Швидші трасовані тіні ламп: близько +2,6% FPS в одному важкому місці. Предмет, тонший за приблизно 2 пікселі, може лишитися без тіні. Потрібно «Ray traced lamp shadows» із внутрішньоігрового меню. Типово вимкнено.",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "Швидші трасовані тіні ламп. Предмет, тонший за приблизно 2 пікселі, може лишитися без тіні. Потрібно «Ray traced lamp shadows» із внутрішньоігрового меню. Типово вимкнено.",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/zh-CN.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "更快的光线追踪灯光阴影：在一处负载较重的位置，帧率约 +2.6%。细于约 2 像素的物体可能失去阴影。需要开启游戏内菜单中的“Ray traced lamp shadows”。默认关闭。",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "更快的光线追踪灯光阴影。细于约 2 像素的物体可能失去阴影。需要开启游戏内菜单中的“Ray traced lamp shadows”。默认关闭。",
"""),
    ],
    LAUNCH + "BloodborneLauncher/Localization/zh-TW.json": [
        (r"""  "Faster ray traced lamp shadows: about +2.6% FPS at one heavy spot. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "更快的光線追蹤燈光陰影：在一處負擔較重的位置，FPS 約 +2.6%。細於約 2 像素的物件可能失去陰影。需要開啟遊戲內選單中的「Ray traced lamp shadows」。預設為關閉。",
""",
         r"""  "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow. Needs Ray traced lamp shadows, which is in the in-game menu. Off by default.": "更快的光線追蹤燈光陰影。細於約 2 像素的物件可能失去陰影。需要開啟遊戲內選單中的「Ray traced lamp shadows」。預設為關閉。",
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the half-resolution build of the shader has
    the averaging and keeps the point lamp without it; the pass reads the experiment bit once,
    as its own constant (vk_rt_shadow.h and .cpp are not touched), and the bit is not one of the
    master switch's; the menu's hint and its eight translations have the same English text, and
    so have the launcher's hint and its 13."""
    ok = True
    comp = texts[B + "host_shaders/point_shadow_ray.comp"]
    cpp = texts[R + "vk_point_shadow.cpp"]
    tune = texts[R + "lamp_shadow_tune.h"]
    nl = "\r\n" if "\r\n" in comp else "\n"
    # Both builds average: the shared answers and the blend are compiled for HALF too, and the
    # HALF build zeroes the radius in one place only, where the pass does not average.
    shared = comp.index("shared float group_answer[64];")
    if "const bool blend = false;" in comp or comp.count("const bool blend = (history_flags & HISTORY_BLEND) != 0u;") != 1 or \
            comp.rfind("#ifndef HALF", 0, shared) > comp.rfind("#endif", 0, shared) or \
            comp.count(fix("    if ((history_flags & HISTORY_BLEND) == 0u) {\n        t_radius = 0.0;\n    }\n#endif\n", nl)) != 1 or \
            comp.count("t_radius = 0.0;") != 2:
        print("the half-resolution build should average as the full-resolution one does, and keep the point lamp only "
              "where the pass does not average")
        ok = False
    # Every pixel of a workgroup reaches the averaging's barrier (no new barrier, no return
    # before it), and a pixel that takes its block's answer reads the block pixel's history,
    # which only the first pass writes.
    if comp.count("barrier();") != 4 or comp.count(fix("        if (!blend) {\n            return;", nl)) != 1 or \
            comp.count("imageLoad(history_cur, px & ~1)") != 1 or \
            comp.count("uniform image2D history_cur;") != 1 or comp.count("uniform writeonly image2D history_cur;") != 1 or \
            comp.count("const float HALF_AGREE = 1.0 / 64.0;") != 1:
        print("the half-resolution build's barrier, its read of the block pixel's history or its agreement bound are "
              "not as the patch made them")
        ok = False
    if cpp.count("constexpr u64 HalfPointsBit = %dull;" % VALUE) != 1 or cpp.count("BbToggle::Experiment(HalfPointsBit)") != 1 or \
            cpp.count("pass_tune.radius_m = LampPassRadius(tune, history_pass, use_half, half_points);") != 1 or \
            tune.count("inline float LampPassRadius(const LampShadowTune& tune, bool takes_history, bool half, bool half_points) {") != 1 or \
            "if (use_half || beside) {" in cpp:
        print("the pass should read experiment %d once (HalfPointsBit) and take its lamp's radius from LampPassRadius" % VALUE)
        ok = False
    if cpp.count("static constexpr std::array<const char*, 8> What{") != 1 or cpp.count("? (use_half ? 6 : 3)") != 1 or \
            cpp.count("line_half") != 3 or cpp.count("half_line_soft") != 3:
        print("the pass's state lines or its 600-frame counts are not as the patch made them")
        ok = False
    settings = texts[S + "bbport_settings.h"]
    bits = re.search(r"PreviousPathsBits\[\] = \{([^}]*)\}", settings)
    if not bits or BIT in [int(x) for x in re.findall(r"\d+", bits.group(1))]:
        print("bit %d is in PreviousPathsBits (or the list was not found)" % BIT)
        ok = False
    # The menu looks a hint's translation up by its English text.
    overlay = texts[S + "bbport_overlay.cpp"]
    at = overlay.find('"Live, off by default. Needs Ray traced lamp shadows. Lamp shadows stay soft')
    end = overlay.find('",', at)
    english = "".join(re.findall(r'"([^"]*)"', overlay[at:end + 1])) if at >= 0 and end >= 0 else None
    if not english or texts[S + "bbport_menu_i18n.cpp"].count('    {"%s",' % english) != 8 or \
            "0.38 ms instead of 0.73 ms" in texts[S + "bbport_menu_i18n.cpp"]:
        print("the menu's hint for the half-resolution lamp shadows and its eight translations do not have the same "
              "English text")
        ok = False
    # The launcher's hint for the option: the English text without the figure measured with
    # point lamps, once in each page and once as a key in each language file.
    hint = "Faster ray traced lamp shadows. An object thinner than about 2 pixels can lose its shadow."
    stale = "Faster ray traced lamp shadows: about"
    pages = [p for p in texts if p.endswith("/Views/GraphicsPage.cs")]
    catalogs = [p for p in texts if p.endswith(".json")]
    if (len(pages) != 2 or len(catalogs) != 13
            or any(texts[p].count('L.T("%s' % hint) != 1 or stale in texts[p] for p in pages)
            or any(texts[p].count('  "%s' % hint) != 1 or stale in texts[p] for p in catalogs)):
        print("the launcher's hint for the half-resolution lamp shadows is not the same new English text in its two "
              "pages and its 13 language files")
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
        print("usage: r44_half-area-lamp.py check|apply|revert   (the tree: R44_ROOT, else the current "
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
