# r42_lamp-soft: round 2 of the ray traced lamp shadow repair: the lamp is an area light, one ray
# a lamp a frame, averaged over the frames (point_shadow_ray.comp, lamp_shadow_tune.h,
# vk_point_shadow.cpp/.h, vk_rt_shadow.cpp, two tests). check|apply|revert (revert restores byte
# for byte). On top of r1..r41 (r41_lamp-shadows applied). The tree is <tree>/ unless the
# environment variable R42_ROOT names another root (a copy). Nothing is changed in place: every
# new text is written beside its target and moved over it, and a failure puts back what was
# already moved. Source files keep their CRLF line ends. The (old, new) pairs below were made
# from the copy the tests and the lab ran on (each old text is found exactly once when its turn
# comes, each new one exactly once on the way back).
#
# WHY. With r41 in the game (camera above a character who holds a hand torch) the body's shadow
# was darker, which was right, but the torch's own stick still threw a thin hard band, and
# r41's cure for it (rays to the lamp's rim, "one free rim ray = lit") could not tell a stick
# from a body: a radius large enough to remove the band (BB_LAMP_SHADOW_SOFT=0.15 with
# BB_LAMP_SHADOW_NEAR=1) ate the body's shadow too. A flame is not a point. A point lamp
# magnifies whatever is next to it (a stick, an arm, a weapon's handle) into a long hard band.
#
# WHAT.
#  1. Every traced lamp gets ONE ray a pixel a frame, as a point lamp does, but to a point of a
#     disc of radius BB_LAMP_SHADOW_SOFT around the lamp that faces the pixel. The point comes
#     from a sequence that covers the disc evenly over the frames (a different start for every
#     pixel, a step for every frame), so the pass gets a real frame counter (tuning word 3). No
#     rim rays: r41's knobs BB_LAMP_SHADOW_RIM, _SHARE and _NEAR are gone (set, they do
#     nothing). A pixel casts as many rays as with a point lamp. No point of the disc lies
#     lower over the pixel's own surface than the lamp's centre (or the ray's start): a lamp
#     that sits closer to a floor or a wall than its radius (a candle) would else have part of
#     its disc under that surface, and the surface would shadow itself.
#  2. One ray says lit or dark, which is noise in a penumbra. So the pass averages each pixel's
#     shadow ratio over the frames in the history image it already had (so far only used by
#     LANTERN_RT_LAMP_REUSE): the history is looked up where the surface was on the frame
#     before (the camera's motion; four texels, each only if it held this surface by its depth,
#     nothing from off the screen, nothing across a camera cut), and this frame's answer goes
#     in with a share of 1 / (frames held + 1), up to the frames BB_LAMP_SHADOW_HISTORY allows
#     (0.9: nine). So a pixel that comes into view settles in a few frames and then keeps a
#     steady average.
#  3. Ghosts (a caster or the lamp moved, and the history holds the shadow where it was):
#     - Clamp (BB_LAMP_SHADOW_CLAMP): the history may lie no further from the mean of this
#       frame's answers around the pixel (5x5, inside its 8x8 workgroup: what one compute pass
#       can see of its neighbours) than the knob times their deviation, nor than the pixel's
#       own answer. Where the answers are mixed (a penumbra) that binds nothing; where they
#       agree (ground a shadow has just left or reached, wholly or as one lamp's part of the
#       light) the history is brought to them at once and given up by as much as it lay
#       outside. This is what works where two lamps light a pixel: a lamp that has half the
#       weight moves the ratio by half, which no fixed threshold on the ratio can tell from
#       noise, but the answers around the pixel all moved by that half.
#     - Reject (BB_LAMP_SHADOW_REJECT): inside a penumbra, beside the long average the texel
#       keeps the mean of the last few frames; where the two are apart by the knob, the long
#       one is dropped. Two or three frames that agree against the history do that; one stray
#       ray does not (the same limit for a young history as for an old one: a lower one for
#       young histories dropped them on one ray and held the first frames' picture back).
#     - A moving lamp (a hand torch): the pass tells the lamps of a frame apart, finds each in
#       the frame before (LampTrack: one of this frame for one of that, nearest to where it
#       stood or to where its motion would have taken it, so two lights a few centimetres
#       apart that move together stay themselves) and gives every lamp record the lamp's
#       motion and step. The shadows of what the lamp is carried with (the carrier, its arm,
#       the stick) move as the lamp does; those of what stands still swing against it. The ray
#       to the pixel's strongest lamp tells the two apart where it is blocked: by something
#       within BB_LAMP_SHADOW_CARRY metres of the lamp, or further off; the blocked rays around
#       the pixel vote. Carried: the history is looked up where the lamp's motion puts it
#       (BB_LAMP_SHADOW_FOLLOW; exact for what is carried). Standing: it is looked up where
#       the surface was, and may hold no more frames than keep the shadow's swing within
#       BB_LAMP_SHADOW_TRAIL metres. A lamp that was not there the frame before has no history
#       under its shadows. So under a carried torch the carrier's own shadow keeps its history
#       and the shadows of standing things are noisier while it moves.
#  4. BB_LAMP_SHADOW_SOFT=0 is the point lamp: the same ray every frame, no history, the same
#     picture every frame.
#  5. Half resolution (graphics_lamp_shadow_half / BB_LAMP_SHADOW_HALF, r32) keeps the point
#     lamp without a history, in the shader's HALF build and in the pass: its first half
#     gives one answer for a 2x2 block, and one area-lamp ray for four pixels is noise in
#     blocks; its second half traces at full resolution wherever the block answers around a
#     pixel differ, which among single rays in a penumbra is everywhere, so the saving would
#     be gone. The log line of the half-resolution build says so; the menu text is not
#     changed. (Whether the pass runs at half resolution is now decided before its tuning: a
#     pass that asked for it and did not get it has the area lamp.)
#  6. Only the pass that takes the history has the area lamp (with the lamps drawn apart, the
#     default, that is the one pass that covers the screen). Another ray traced lamp pass of
#     the same frame (lamps not drawn apart, or a batch that could not go apart) keeps the
#     point lamp, because bare single rays would show as noise there; the 600-frame lamp line
#     counts those passes. With BB_LAMP_SHADOW_HISTORY=0 every full-resolution pass has the
#     bare area lamp. A pass that averages and cannot read its history for 8 frames in a row
#     (no camera for the pass, or the history image made anew every frame) has point lamps
#     until it can, and a state line says so.
#  7. LANTERN_RT_LAMP_REUSE=1 (off by default) has no effect while the history averages: its
#     history image is the same one. It works as before with BB_LAMP_SHADOW_SOFT=0 or
#     BB_LAMP_SHADOW_HISTORY=0.
#  8. r41's rule that left starved moving copies out of lamp rays is off unless
#     BB_LAMP_SHADOW_STALE=1: nothing in the code shows that such a copy is never the only
#     caster a ray would find, and in the game the band it was aimed at stayed. The counting
#     goes on, and the 600-frame "Ray tracing: ... shared copies" line now ends with how many
#     moving copies are starved, whether they are left out, and the four largest by mesh hash,
#     triangle count, camera pass or not, and age of their build.
#  9. Experiment 35184372088832 set is still the picture of before r41: no tuning words reach
#     the shader, so it runs with its old values, a point lamp, and no averaging. (The picture,
#     not the cost: the shader is larger than before r41, and in a reviewer's lab run mode 0 of
#     the shader as it was reviewed ran 0.01 to 0.05 ms slower than the shader of before r41.)
#
# KNOBS (environment variables, read once at start; a value out of range is clamped, one that
# is not a number leaves the default). New or changed in r42:
#   BB_LAMP_SHADOW_SOFT     [0.10]  0..0.5 m   the lamp's radius. 0: a point lamp, no history.
#   BB_LAMP_SHADOW_HISTORY  [0.9]   0..0.98    the frames before's share in the shadow ratio:
#                                              up to h / (1 - h) frames are held (0.9: 9,
#                                              0.8: 4, 0.95: 19). 0: this frame's rays alone.
#   BB_LAMP_SHADOW_CLAMP    [1.6]   0, 0.5..4  the history may lie this many deviations of
#                                              this frame's answers around the pixel from
#                                              their mean. Lower: ghosts go sooner, penumbrae
#                                              get noisier. 0: no such bound. A value between
#                                              0 and 0.5 counts as 0.5.
#   BB_LAMP_SHADOW_REJECT   [0.5]   0, 0.45..1 the history is dropped where the mean of the
#                                              last few frames is this far from it. 0: never.
#                                              A value between 0 and 0.45 counts as 0.45
#                                              (below that one stray ray would drop it).
#   BB_LAMP_SHADOW_FOLLOW   [1]     0|1        under a moving lamp, the history of what the
#                                              lamp is carried with is looked up where the
#                                              lamp's motion puts it. 0: always where the
#                                              surface was.
#   BB_LAMP_SHADOW_CARRY    [2.5]   0..5 m     what blocks a moving lamp within this distance
#                                              of it is taken to move with it (the carrier of a
#                                              hand torch, from the flame down to the feet).
#                                              0: nothing is.
#   BB_LAMP_SHADOW_TRAIL    [0.08]  0..2 m     how far the shadow of a standing thing may trail
#                                              under a moving lamp: where it swings s metres a
#                                              frame the history holds at most trail / s
#                                              frames. Higher: smoother and more smear. 0: a
#                                              lamp's motion does not shorten the history.
#   BB_LAMP_SHADOW_STALE    [0]     0|1        1: starved moving copies are left out of lamp
#                                              rays, as r41 did. 0: they stay in.
#   BB_LAMP_SHADOW_VIEW     [0]     0..6       debug views, see below.
# As r41 left them:
#   BB_LAMP_SHADOW_WEIGHTS  [1]     0|1        the game's falloff times N.L. 0: as before r41.
#   BB_LAMP_SHADOW_WRAP     [0.15]  0..1       N.L tolerance of the weights. 1: no N.L.
#   BB_LAMP_SHADOW_FLOOR    [0.05]  0..1       least facing factor of the weights.
#   BB_LAMP_SHADOW_CLEARANCE [0.35] 0.05..2 m  blind sphere at the lamp.
#   BB_LAMP_SHADOW_BIAS     [0.03]  0.005..0.2 m  ray start offset.
#   BB_LAMP_SHADOW_SELF     [0.06]  0..0.3 m   grazing self skip.
#   BB_LAMP_SHADOW_VIEW_GAIN [0.5]  0.01..16   brightness of the views.
# Gone: BB_LAMP_SHADOW_RIM, BB_LAMP_SHADOW_SHARE, BB_LAMP_SHADOW_NEAR.
#
# DEBUG VIEWS (BB_LAMP_SHADOW_VIEW, on pixels the pass shadows, in place of their light):
#   1  the shadow ratio as THIS frame's rays gave it (with the area lamp: the raw noise)
#   2  how many lamp records have weight on the pixel (1 blue, 2 green, 3 yellow, 4+ red)
#   3  rays the pixel cast (0 blue, 1 green, 2 yellow, 3+ red)
#   4  the ratio as it is used: averaged over the frames (the same as 1 without a history)
#   5  the frames of history in it: red none, green all it may hold; blue: this pass averages
#      nothing (point lamp, half resolution, a second pass of the frame, experiment bit)
#   6  where the history was looked up: green where a moving lamp's motion puts it (carried),
#      blue where the surface was under a moving lamp, dim under a lamp that stands; red on
#      top: how much of the history the answers around the pixel took away on this frame
#
# LOG LINES.
#   At start (replaces r41's): "Ray traced lamps (r42): weights ... area lamp radius R m, one
#     ray a lamp a frame, history H (up to N frames), kept within C deviations of the answers
#     around a pixel, reject, trail, follows moving lamps yes|no (what blocks one within D m of
#     it moves with it); starved moving copies stay in|are left out of lamp rays; clearance,
#     bias, self skip, view (BB_LAMP_SHADOW_*); experiment 35184372088832 set = the path before
#     r41".
#   At each change, 24 times at most: "Ray traced lamps (r42): " and one of: "point lamps:
#     experiment 35184372088832 is set, the pass of before r41" / "point lamps without a
#     history: the pass runs at half resolution (graphics_lamp_shadow_half or
#     BB_LAMP_SHADOW_HALF), which keeps them" / "point lamps without a history
#     (BB_LAMP_SHADOW_SOFT=0)" / "area lamps, one ray a lamp a frame, not averaged
#     (BB_LAMP_SHADOW_HISTORY=0)" / "area lamps, one ray a lamp a frame, averaged over the
#     frames in the pass's history" / "point lamps for now: the pass could not read its history
#     for 8 frames (no camera for the pass, or the history is made anew every frame)". (r41's
#     "repair on/off" line stays.)
#   Every 600 frames (the first two seconds in): "Ray traced lamps (r42): N lamp records in the
#     pass, M lamps told apart (the near ones first, 64 at most; U records are of more lamps
#     than that), K within 15 m of the camera; since the last such line the pass averaged on A
#     frames and read its history on B of them (C camera cuts), and P ray traced lamp passes
#     beside it had point lamps; the brightest near lamps (world x y z, reach, luminance,
#     distance to the camera, records, moved since the frame before; then over the frames it
#     was followed since the last line: how many, its mean step and its largest): (x y z) R m,
#     L, D m, n, m m (F frames, mean S m, most T m); ..." for up to four lamps: where the
#     torch's lamp sits against the flame, how many records one torch makes (a lamp is listed
#     once for every tile it reaches; lamps are told apart by place, reach and colour, so two
#     lights of one torch show as two), and whether the lamp wobbles while its carrier stands
#     (a mean step that is not 0).
#   The half-resolution line ends: "; at half resolution the lamps stay points without a
#     history (r42: BB_LAMP_SHADOW_SOFT and BB_LAMP_SHADOW_HISTORY act on the full-resolution
#     pass only)".
#   The 600-frame "Ray tracing: ... shared copies" line ends: "; N moving copies starved of
#     rebuilds, kept in lamp rays|left out of lamp rays (BB_LAMP_SHADOW_STALE=0|1), the
#     largest: mesh <hash>, T triangles, in the camera pass|not in the camera pass, built F
#     frames ago; ...".
#
# THE LAB. tests/test_rt_shadows.cpp: "rt-shadow-test --lamps [directory]" is the torch lab: a
# character with a hand torch seen from above, the pass run over many frames with its history
# as the engine hands it over (LampTrack and the history block's words included), the scene and
# the camera moved between frames, each picture compared with the mean of 128 single frames
# (the area lamp's true picture): the still scene after 1, 4, 16 and 48 frames, the torch
# carried at a run and at a walk, a figure walking under the still torch with one lamp and with
# two, a figure gone from one frame to the next, a flame whose lamp wobbles, a lamp 5 and 2 cm
# over bare ground, a moving camera, the half-resolution build. With a directory it writes the
# pictures there (PGM). It reads the BB_LAMP_SHADOW_* knobs, so a radius or a history blend can
# be tried there first (its checks are made for the defaults only).
# "--speed" times the default (the area lamp with its history) and the point lamp against mode
# 0 of this shader (the experiment bit's path, which is not the shader of before r41).
# tests/test_lamp_shadow_tune.cpp: the knobs, the words, the frames of history, the camera cut,
# LampTrack (two lamps close together that move as one, a flickering reach, a jump, more lamps
# than are told apart).

import os
import re
import sys

ROOT = os.environ.get("R42_ROOT", "<tree>/").replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"
E = ROOT + "engine/"
G = E + "gpu/"
B = G + "shadps4/video_core/"
R = B + "renderer_vulkan/"
TESTS = E + "tests/"

TMP = ".r42tmp"  # a new text waits under this name beside its target (main)

# No file is new in this round (apply makes none, revert removes none).
NEW_FILES = {}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old.
EDITS = {
    B + "host_shaders/point_shadow_ray.comp": [
        (r"""// the values below stay as they are here, which is the pass of before: the old weights, a point
// lamp, LAMP_CLEARANCE, the ray's start where it was, no view.
const uint MODE_REPAIR = 16u;
bool new_w = false;             // weights follow the game's falloff and the surface's facing
bool inv_sq = false;            // the game's lamps use the inverse-square curve
uint t_rim = 0u;                // rays to the rim of a strong lamp whose centre is blocked
uint t_view = 0u;               // debug view (BB_LAMP_SHADOW_VIEW)
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
float t_radius = 0.0;           // the lamp's radius, m
float t_share = 2.0;            // least share of the pixel's weight for rim rays
float t_self = 0.0;             // grazing self skip, m
float t_wrap = 0.0;             // N.L tolerance of the weights; 1: no N.L
""",
         r"""// the values below stay as they are here, which is the pass of before: the old weights, a point
// lamp, LAMP_CLEARANCE, the ray's start where it was, no view.
// bbport (r42_lamp-soft): the lamp is an area light. A flame is not a point: a point lamp
// magnifies a torch stick, an arm or a weapon handle next to the flame into a long hard band,
// and r41's answer (rays to the lamp's rim, one free ray = lit) could not tell a stick from a
// body: a radius that removed the stick's band ate the body's shadow. Now every traced lamp
// gets one ray a frame to a point of its disc (radius t_radius, facing the surface), the point
// taken from a sequence that covers the disc evenly over the frames (samplePoint), and the
// pixel's shadow ratio is averaged over the frames in the history image (HISTORY_BLEND). A thin
// caster near the lamp then covers a small part of the disc from every place: a faint wide
// smear. A body covers all of it in its core and less towards its rim: a penumbra that widens
// with the distance behind the caster. No more rays than a point lamp casts. t_radius 0: the
// point lamp, the same ray every frame, no history (BB_LAMP_SHADOW_SOFT=0; and always in the
// half-resolution build, whose block answers must agree to be shared).
const uint MODE_REPAIR = 16u;
bool new_w = false;             // weights follow the game's falloff and the surface's facing
bool inv_sq = false;            // the game's lamps use the inverse-square curve
uint t_view = 0u;               // debug view (BB_LAMP_SHADOW_VIEW)
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
float t_radius = 0.0;           // the lamp's radius, m; 0: a point
uint t_frame = 0u;              // the frame counter (the sample points' sequence)
float t_self = 0.0;             // grazing self skip, m
float t_wrap = 0.0;             // N.L tolerance of the weights; 1: no N.L
"""),
        (r"""float t_gain = 1.0;             // brightness of the view
float t_floor = 0.0;            // least facing factor of the weights
float t_near = 1.0;             // rim rays for a caster this near the lamp (share of the way)
// Two axes of the world, in view space (this pass works in view space): the rim pattern is laid
// out against them, so it stays put in the world when the camera turns.
vec3 t_axis_a = vec3(1.0, 0.0, 0.0);
vec3 t_axis_b = vec3(0.0, 1.0, 0.0);
uint rays_cast = 0u;            // rays this invocation cast (view 3)

// Called once a workgroup has a tile (an empty one reads nothing).
""",
         r"""float t_gain = 1.0;             // brightness of the view
float t_floor = 0.0;            // least facing factor of the weights
float t_reject = 0.0;           // the history is dropped where the last frames differ this much
// Two axes of the world, in view space (this pass works in view space): the lamp's disc is laid
// out against them.
vec3 t_axis_a = vec3(1.0, 0.0, 0.0);
vec3 t_axis_b = vec3(0.0, 1.0, 0.0);
uint rays_cast = 0u;            // rays this invocation cast (view 3)
// bbport (r42_lamp-soft): of the ray cast last, if it was blocked: from its start to the hit and
// from the hit on to its target, m (ray_left below 0: it was free, or not cast).
float ray_went = 0.0;
float ray_left = -1.0;

// Called once a workgroup has a tile (an empty one reads nothing).
"""),
        (r"""    new_w = (f & 1u) != 0u;
    inv_sq = (f & 2u) != 0u;
    t_rim = (f >> 4u) & 7u;
    t_view = (f >> 8u) & 3u;
    t_clear = word(at + 1u);
    t_radius = word(at + 2u);
    t_share = word(at + 3u);
    t_self = word(at + 4u);
    t_wrap = word(at + 5u);
""",
         r"""    new_w = (f & 1u) != 0u;
    inv_sq = (f & 2u) != 0u;
    t_view = (f >> 8u) & 7u;
    t_clear = word(at + 1u);
    t_radius = word(at + 2u);
    t_frame = data.d[at + 3u];
    t_self = word(at + 4u);
    t_wrap = word(at + 5u);
"""),
        (r"""    t_gain = word(at + 7u);
    t_floor = word(at + 8u);
    t_near = word(at + 9u);
    t_axis_a = vec3(word(at + 10u), word(at + 11u), word(at + 12u));
    t_axis_b = vec3(word(at + 13u), word(at + 14u), word(at + 15u));
}

""",
         r"""    t_gain = word(at + 7u);
    t_floor = word(at + 8u);
    t_reject = word(at + 9u);
    t_axis_a = vec3(word(at + 10u), word(at + 11u), word(at + 12u));
    t_axis_b = vec3(word(at + 13u), word(at + 14u), word(at + 15u));
#ifdef HALF
    t_radius = 0.0; // bbport (r42_lamp-soft): the half-resolution build keeps the point lamp
#endif
}

"""),
        (r"""
// bbport (r41_lamp-shadows): one ray from `origin` towards `target` (the lamp's centre or a
// point of its rim), blind within t_clear of the target. Below 0: free. Else blocked: how far
// along the way to the target the hit lies, 0 to 1 (a hit, not always the nearest: the ray stops
// at its first). (Before: visibility(), 1 free and 0 blocked, with LAMP_CLEARANCE; with the
""",
         r"""
// bbport (r41_lamp-shadows): one ray from `origin` towards `target` (the lamp's centre or a
// point of its disc), blind within t_clear of the target. Below 0: free. Else blocked: how far
// along the way to the target the hit lies, 0 to 1 (a hit, not always the nearest: the ray stops
// at its first). (Before: visibility(), 1 free and 0 blocked, with LAMP_CLEARANCE; with the
"""),
        (r"""    const float ray_len = length(ray_to);
    const float tmax = ray_len - t_clear;
    if (!(tmax > reach)) {
        return -1.0;
""",
         r"""    const float ray_len = length(ray_to);
    const float tmax = ray_len - t_clear;
    ray_left = -1.0;
    if (!(tmax > reach)) {
        return -1.0;
"""),
        (r"""        return -1.0;
    }
    return rayQueryGetIntersectionTEXT(query, true) / ray_len;
}

// bbport (r41_lamp-shadows): whether the lamp at L lights the surface at P: 1 or 0, nothing
// between (no noise, nothing to filter, and the half-resolution build's block answers keep
// agreeing). The ray to the lamp's centre is cast here, in straight code as before; the rays to
// its rim are cast later, in one loop for the pixel (rimLight): a ray query inside a loop that
// every lamp goes through made the whole pass slower, also with the repair off.
//  - Grazing self skip: the ray starts reach off the surface along a normal worked out from
//    depth, and at a flat angle it stays close to the surface it left for a long way: layered
""",
         r"""        return -1.0;
    }
    ray_went = rayQueryGetIntersectionTEXT(query, true);
    ray_left = ray_len - ray_went;
    return ray_went / ray_len;
}

// bbport (r42_lamp-soft): a point of the unit square for this pixel and frame. Over the frames
// a pixel walks the R2 sequence (steps of 1/1.3247 and 1/1.3247^2 of the square, in 32-bit
// fixed point so that it never loses its place): any run of frames covers the square evenly,
// which is what lets nine or so frames stand for the whole disc. Each pixel starts from a place
// of its own (interleaved gradient noise in each direction), so neighbours hold different
// points and what noise is left has no pattern the eye or the upscaler could follow.
vec2 samplePoint(ivec2 p, uint frame) {
    const vec2 q = vec2(p);
    const vec2 start = vec2(fract(52.9829189 * fract(dot(q, vec2(0.06711056, 0.00583715)))),
                            fract(52.9829189 * fract(dot(q.yx + vec2(19.0, 73.0), vec2(0.06711056, 0.00583715)))));
    const uvec2 walked = frame * uvec2(3242174889u, 2447445414u);
    return fract(start + vec2(walked >> 8u) * (1.0 / 16777216.0));
}

// bbport (r41_lamp-shadows, r42_lamp-soft): whether the lamp at L lights the surface at P, by
// one ray: 1 or 0.
//  - Grazing self skip: the ray starts reach off the surface along a normal worked out from
//    depth, and at a flat angle it stays close to the surface it left for a long way: layered
"""),
        (r"""//    along the normal by t_self * (1 - N.L)^2 more. (Lifted, not "hits count from further along
//    the ray": that would also pass a thin wall or prop standing next to the pixel.)
//  - wide: the lamp is a disc of radius t_radius facing the surface, not a point. Where the ray
//    to its centre is blocked, up to t_rim rays go to its rim, and one free ray means lit. A
//    caster thinner than about 2 * t_radius * (1 - q) then casts nothing, q being its distance
//    from the lamp over the receiver's: a point lamp magnified a torch stick, a weapon handle or
//    the torch head next to the flame into a long hard band across the ground. A wide caster
//    keeps its shadow, with each edge moved in by up to t_radius * (1 - q) / q on the receiver
//    (between half of that and all of it, by the edge's angle to the three rim points).
//  - t_near: all of that only where the caster is near the lamp, which is where a point lamp
//    magnifies it: the radius is whole up to q = t_near / 2 and falls to nothing at q = t_near
//    (q from the centre ray's hit). A caster further from the lamp keeps the point lamp's shadow
//    and costs no rim ray. 1: everywhere.
//  - The rim points are laid out against two axes of the world (t_axis_a, a horizontal one, and
//    t_axis_b, up), not of the view: against the view's they turned with the camera and so did
//    the eroded edges. Where the ray runs within 26 degrees of the first axis the second takes
//    over; that seam is fixed in the world.
// wide is asked only for a lamp that holds a share of the pixel's weight (w), so the extra rays
// go where a strong lamp is blocked by something near it; at most MAX_RIM_LAMPS lamps a pixel.
const uint MAX_RIM_LAMPS = 4u;
vec3 rim_from[MAX_RIM_LAMPS];    // the ray's start
vec3 rim_l[MAX_RIM_LAMPS];       // the lamp's centre
float rim_radius[MAX_RIM_LAMPS]; // the lamp's radius for this caster
float rim_w[MAX_RIM_LAMPS];      // the lamp's weight
uint rim_n = 0u;

float lampVisibility(vec3 P, vec3 n, vec3 origin, float reach, vec3 L, float w, bool wide) {
    vec3 from = origin;
    if (t_self > 0.0 && n != vec3(0.0)) {
""",
         r"""//    along the normal by t_self * (1 - N.L)^2 more. (Lifted, not "hits count from further along
//    the ray": that would also pass a thin wall or prop standing next to the pixel.)
//  - The lamp is a disc of radius t_radius that faces the surface, and the ray goes to the point
//    of it that xi names (uniform over the disc's area). The disc is laid out against two axes
//    of the world (t_axis_a, a horizontal one, and t_axis_b, up; where the ray runs within 26
//    degrees of the first the second takes over). t_radius 0: the ray goes to L.
//  - No point of the disc lies lower over the surface's own plane than the lamp's centre does
//    (or than the ray's start, where the centre is higher than that): a lamp that sits closer
//    to a floor, a table or a wall than its radius (a candle) would have part of its disc under
//    that surface, and the surface would shadow itself there (a lamp 5 cm over bare ground lost
//    a tenth of its light with a radius of 0.1 m, a quarter at 2 cm). Such a point is lifted
//    along the normal. A lamp higher than its radius over the plane is not touched, and a lamp
//    behind the surface keeps the part of its disc that looks over the edge (the soft rim of
//    the lit side of a body).
float lampVisibility(vec3 P, vec3 n, vec3 origin, float reach, vec3 L, vec2 xi) {
    vec3 from = origin;
    if (t_self > 0.0 && n != vec3(0.0)) {
"""),
        (r"""        from += n * (t_self * g * g);
    }
    const float hit = ray(from, reach, L);
    if (hit < 0.0) {
        return 1.0;
    }
    if (wide && rim_n < MAX_RIM_LAMPS) {
        float radius = t_radius;
        if (t_near < 1.0) {
            radius *= clamp(2.0 - 2.0 * (1.0 - hit) / t_near, 0.0, 1.0);
        }
        if (radius > 0.0) {
            rim_from[rim_n] = from;
            rim_l[rim_n] = L;
            rim_radius[rim_n] = radius;
            rim_w[rim_n] = w;
            ++rim_n;
        }
    }
    return 0.0;
}

// bbport (r41_lamp-shadows): the weight of the lamps lampVisibility noted (centre blocked by
// something near the lamp) that a ray to their rim reaches after all.
float rimLight(float reach) {
    float lit = 0.0;
    for (uint j = 0u; j < rim_n; ++j) {
        const vec3 dir = normalize(rim_l[j] - rim_from[j]);
        const vec3 across = cross(dir, abs(dot(dir, t_axis_a)) < 0.9 ? t_axis_a : t_axis_b);
        const float len2 = dot(across, across);
        if (!(len2 > 1e-6)) {
            continue;
        }
        const vec3 u = across * inversesqrt(len2);
        const vec3 v = cross(dir, u);
        for (uint i = 0u; i < t_rim; ++i) {
            const float a = 6.2831853 * (float(i) + 0.25) / float(t_rim);
            if (ray(rim_from[j], reach, rim_l[j] + rim_radius[j] * (cos(a) * u + sin(a) * v)) < 0.0) {
                lit += rim_w[j];
                break;
            }
        }
    }
    return lit;
}

""",
         r"""        from += n * (t_self * g * g);
    }
    vec3 target = L;
    if (t_radius > 0.0) {
        const vec3 dir = normalize(L - from);
        const vec3 across = cross(dir, abs(dot(dir, t_axis_a)) < 0.9 ? t_axis_a : t_axis_b);
        const float len2 = dot(across, across);
        if (len2 > 1e-6) {
            const vec3 u = across * inversesqrt(len2);
            const vec3 v = cross(dir, u);
            const float a = 6.2831853 * xi.y;
            target += (t_radius * sqrt(xi.x)) * (cos(a) * u + sin(a) * v);
            // (n zero: no normal, nothing is lifted)
            target += n * max(min(reach, dot(n, L - P)) - dot(n, target - P), 0.0);
        }
    }
    return ray(from, reach, target) < 0.0 ? 1.0 : 0.0;
}

"""),
        (r"""const uint HISTORY_READ = 1u;
const uint HISTORY_WRITE = 2u;
const float STABLE_FRAMES = 3.0;
const float STABLE_CHANGE = 0.05;

shared uint group_trace;

#ifdef HALF
""",
         r"""const uint HISTORY_READ = 1u;
const uint HISTORY_WRITE = 2u;
// bbport (r42_lamp-soft): the history averages the shadow ratio over the frames (texel: the
// ratio, view depth, frames it holds, the mean of the last few frames) in place of LANTERN_RT_
// LAMP_REUSE's "copy what a settled block held" (the ratio, view depth, settled frames, 1).
// Word 30 of the history block: the most frames a texel may hold; word 31: how far a moving
// lamp's shadows may trail, m; word 32: what blocks a moving lamp within this distance of it is
// taken to move with it, m; word 33: how many deviations of the answers around a pixel its
// history may lie from their mean (0: any). With it, words 12 to 14 of every lamp record: how
// far the lamp moved since the frame before, in that frame's view space (LampTrack::Shift;
// zero: it stands, or the pass does not follow lamps), and word 15: that distance, m
// (LampTrack::Step; very large: the lamp was not there the frame before).
const uint HISTORY_BLEND = 4u;
const float FAST_KEEP = 0.6; // the last frame's share in the mean of the last few frames
// The reject sets in at this share of t_reject. One ray that disagrees with the history moves
// the mean of the last few frames by 1 - FAST_KEEP = 0.4 at most, and must not drop the history
// (in a penumbra every other ray disagrees): lamp_shadow_tune.h keeps t_reject at 0.45 or more.
const float REJECT_FROM = 0.9;
// The history against this frame's answers around the pixel (see main): the variance a pixel's
// answers are taken to have at the least (over the answers counted; 0.25 is a coin's), and how
// far the history may lie outside before it is given up (from, wholly).
const float AROUND_FLOOR = 0.05;
const float AROUND_FROM = 0.05;
const float AROUND_ALL = 0.3;
const float STABLE_FRAMES = 3.0;
const float STABLE_CHANGE = 0.05;

// bbport (r42_lamp-soft): what the averaging history (HISTORY_BLEND) of the frame before holds
// for the surface at P: its shadow ratio, the frames in it (times the part of it that was
// found) and the mean of its last few frames. False: nothing (the place was off the screen, or
// held another surface).
//  - The place: where the surface was in the view of the frame before, and from there back by
//    `moved`, the motion of the pixel's strongest lamp: a torch's shadows of what is carried
//    with it (its carrier, on the ground and on the carrier itself) move as the torch does, so
//    that is where the frame before holds them. Zero for a lamp that stands.
//  - The four texels around that place, each only if it held this surface (by its depth),
//    weighted as a bilinear lookup and made whole again: an average carried over many frames
//    must not snap to whole pixels while the camera moves, and must not take in a neighbour's
//    history across a depth edge. (A still camera lands on its own texel: nothing is blurred.)
// main() calls it after its rays: called before them, what it finds had to be kept across the
// ray queries, and the pass measured slower for it even where nothing is averaged.
bool blendHistory(vec3 P, uint history_at, vec3 moved, out float ratio, out float frames, out float fast) {
    const vec4 v = vec4(P, 1.0);
    const vec3 p = vec3(dot(row(history_at + 2u), v), dot(row(history_at + 6u), v), dot(row(history_at + 10u), v)) - moved;
    const vec4 clip = vec4(dot(row(history_at + 14u), vec4(p, 1.0)), dot(row(history_at + 18u), vec4(p, 1.0)),
                           dot(row(history_at + 22u), vec4(p, 1.0)), dot(row(history_at + 26u), vec4(p, 1.0)));
    if (!(clip.w > 1e-4)) {
        return false;
    }
    const vec2 ndc = clip.xy / clip.w;
    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size;
    if (any(lessThan(was, vec2(0.0))) || any(greaterThanEqual(was, size))) {
        return false;
    }
    const vec2 centre = was - 0.5;
    const ivec2 h0 = ivec2(floor(centre));
    const vec2 part = centre - vec2(h0);
    vec3 sum = vec3(0.0);
    float found = 0.0;
    for (int k = 0; k < 4; ++k) {
        const ivec2 o = ivec2(k & 1, k >> 1);
        const float w = (o.x == 0 ? 1.0 - part.x : part.x) * (o.y == 0 ? 1.0 - part.y : part.y);
        const ivec2 q = h0 + o;
        if (w > 0.004 && all(greaterThanEqual(q, ivec2(0))) && all(lessThan(q, ivec2(size)))) {
            const vec4 h = imageLoad(history_prev, q);
            if (h.g > 0.0 && abs(h.g - p.z) < 0.03 * p.z + 0.02) {
                sum += w * h.rba;
                found += w;
            }
        }
    }
    if (!(found > 0.01)) {
        return false;
    }
    ratio = sum.x / found;
    frames = sum.y;
    fast = sum.z / found;
    return true;
}

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
"""),
        (r"""
    float wsum = 0.0;
    // bbport (r41_lamp-shadows): rim rays wanted at all; for view 2, the lamp records with weight
    // at the pixel (a lamp that two overlapping tiles of a batch list counts twice, as its
    // weight does) and the largest weight (top_w is not kept when every lamp is traced).
    const bool rim = t_rim > 0u && t_radius > 0.0;
    uint lamps = 0u;
    float view_top = 0.0;
    const bool exact = steps == 0u;
    float top_w = 0.0;
""",
         r"""
    float wsum = 0.0;
    // bbport (r41_lamp-shadows): for view 2, the lamp records with weight at the pixel (a lamp
    // that two overlapping tiles of a batch list counts twice, as its weight does) and the
    // largest weight (top_w is not kept when every lamp is traced).
    uint lamps = 0u;
    float view_top = 0.0;
#ifdef HALF
    const bool blend = false; // bbport (r42_lamp-soft): the point lamp, see loadTune
#else
    const bool blend = (history_flags & HISTORY_BLEND) != 0u;
#endif
    uint top_at = 0u; // blend: the record of the pixel's strongest lamp (0: none)
    const bool exact = steps == 0u;
    float top_w = 0.0;
"""),
        (r"""    float reach = 0.0;
    vec3 origin = vec3(0.0);
    uint seed = (uint(px.x) * 1973u + uint(px.y) * 9277u + frame_index * 26699u) | 1u;
    if (live) {
        n = surfaceNormal(uv, P);
""",
         r"""    float reach = 0.0;
    vec3 origin = vec3(0.0);
    // bbport (r42_lamp-soft): an area lamp's pixel picks its second lamp anew every frame, jitter
    // or not (the history averages the picks as it averages the disc's points).
    const bool soft = t_radius > 0.0;
    uint seed = (uint(px.x) * 1973u + uint(px.y) * 9277u + (soft ? t_frame : frame_index) * 26699u) | 1u;
    vec2 xi = vec2(0.0);
    if (live) {
        n = surfaceNormal(uv, P);
"""),
        (r"""        reach = bias_m + 0.0015 * P.z;
        origin = P + n * reach;
    }
    const ivec2 px_hi = px + 1;
""",
         r"""        reach = bias_m + 0.0015 * P.z;
        origin = P + n * reach;
        if (soft) {
            xi = samplePoint(px, t_frame);
        }
    }
    const ivec2 px_hi = px + 1;
"""),
        (r"""            wsum += w;
            ++lamps;
            view_top = max(view_top, w);
            if (exact) {
                exact_pending = true;
""",
         r"""            wsum += w;
            ++lamps;
            if (w > view_top) {
                view_top = w;
                top_at = at;
            }
            if (exact) {
                exact_pending = true;
"""),
        (r"""    float old_stable = 0.0;
    bool old_valid = false;
    if (live && (history_flags & HISTORY_READ) != 0u) {
        const vec4 v = vec4(P, 1.0);
        const vec3 p = vec3(dot(vec4(word(history_at + 2u), word(history_at + 3u), word(history_at + 4u),
""",
         r"""    float old_stable = 0.0;
    bool old_valid = false;
    // bbport (r42_lamp-soft): LANTERN_RT_LAMP_REUSE's history; the averaging one is looked up
    // after the rays (blendHistory)
    if (live && !blend && (history_flags & HISTORY_READ) != 0u) {
        const vec4 v = vec4(P, 1.0);
        const vec3 p = vec3(dot(vec4(word(history_at + 2u), word(history_at + 3u), word(history_at + 4u),
"""),
        (r"""    }
    const uint refresh = data.d[history_at + 1u];
    const bool due = history_flags == 0u ||
                     ((gl_WorkGroupID.x & 1u) + 2u * (gl_WorkGroupID.y & 1u)) == (refresh & 3u);
    if (live && (due || !old_valid || old_stable < STABLE_FRAMES)) {
""",
         r"""    }
    const uint refresh = data.d[history_at + 1u];
    // bbport (r42_lamp-soft): averaging, every pixel casts its ray every frame
    const bool due = history_flags == 0u || blend ||
                     ((gl_WorkGroupID.x & 1u) + 2u * (gl_WorkGroupID.y & 1u)) == (refresh & 3u);
    if (live && (due || !old_valid || old_stable < STABLE_FRAMES)) {
"""),
        (r"""            imageStore(snap1, px, vec4(0.0));
        }
        return;
    }
    float ratio;
    float stable;
#ifdef HALF
    uint half_why = 0u; // traced: why (HalfAnswer, or HALF_FIRST_PIXEL); 0 not traced
#endif
    if (group_trace != 0u) {
#ifdef HALF
        float taken = 1.0;
""",
         r"""            imageStore(snap1, px, vec4(0.0));
        }
        // bbport (r42_lamp-soft): averaging, every pixel of the workgroup goes on to the
        // barrier below (which all of them must reach), this one with no answer
        if (!blend) {
            return;
        }
    }
    float ratio = 1.0;
    float stable = 0.0;
    float top_went = 0.0, top_left = -1.0; // the ray to the strongest lamp (ray_went, ray_left)
#ifdef HALF
    uint half_why = 0u; // traced: why (HalfAnswer, or HALF_FIRST_PIXEL); 0 not traced
#endif
    if (!live) {
        // (averaging: see above)
    } else if (group_trace != 0u) {
#ifdef HALF
        float taken = 1.0;
"""),
        (r"""        if (exact) {
            if (exact_pending) {
                for (uint i = 0u; i < tile_count; ++i) {
                    const uint tile = overflow ? i : group_tiles[i];
""",
         r"""        if (exact) {
            if (exact_pending) {
                uint traced = 0u; // bbport (r42_lamp-soft): each lamp its own point of the disc
                for (uint i = 0u; i < tile_count; ++i) {
                    const uint tile = overflow ? i : group_tiles[i];
"""),
        (r"""                            continue;
                        }
                        vsum += w * lampVisibility(P, n, origin, reach, L, w, rim && w >= t_share * wsum);
                    }
                }
""",
         r"""                            continue;
                        }
                        vsum += w * lampVisibility(P, n, origin, reach, L,
                                                   fract(xi + float(traced++) * vec2(0.5545497, 0.3085170)));
                        if (at == top_at) {
                            top_went = ray_went;
                            top_left = ray_left;
                        }
                    }
                }
"""),
        (r"""            }
        } else {
            // bbport (r41_lamp-shadows): rim rays for the strongest lamp and for the picked one
            // (which stands for all the others), each only where it holds a share of the
            // pixel's weight
            vsum = top_w * lampVisibility(P, n, origin, reach, top_l, top_w, rim && top_w >= t_share * wsum);
            if (rest_w > 0.0) {
                vsum += rest_w *
                        lampVisibility(P, n, origin, reach, rest_l, rest_w, rim && rest_w >= t_share * wsum);
            }
        }
        if (rim_n != 0u) {
            vsum += rimLight(reach); // bbport (r41_lamp-shadows): the rim rays of the noted lamps
        }
        ratio = clamp(vsum / wsum, 0.0, 1.0);
""",
         r"""            }
        } else {
            // bbport (r42_lamp-soft): one ray for the strongest lamp and one for the picked one
            // (which stands for all the others), each to its own point of the lamp's disc
            vsum = top_w * lampVisibility(P, n, origin, reach, top_l, xi);
            top_went = ray_went;
            top_left = ray_left;
            if (rest_w > 0.0) {
                vsum += rest_w * lampVisibility(P, n, origin, reach, rest_l,
                                                fract(xi + vec2(0.5545497, 0.3085170)));
            }
        }
        ratio = clamp(vsum / wsum, 0.0, 1.0);
"""),
        (r"""        stable = old_stable;
    }
    if ((history_flags & HISTORY_WRITE) != 0u) {
        imageStore(history_cur, px, vec4(ratio, P.z, stable, 1.0));
""",
         r"""        stable = old_stable;
    }
    // bbport (r42_lamp-soft): this frame's answer goes into the average of the frames before.
    //  - A frame's share is 1 / (frames + 1): the first frames after a pixel comes into view (or
    //    into a lamp's reach) are a plain mean, so it settles in a few frames in place of
    //    holding its first ray's answer at 90%; later the share stays at 1 / (limit + 1).
    //  - Ghosts: when a caster or the lamp moves, the history holds the shadow where it was.
    //    One ray says little (in a penumbra it is lit or not by chance), but the 25 answers of
    //    this frame around the pixel (5x5, inside its workgroup, which is what a compute pass
    //    can see of its neighbours) say a lot where they agree: the history may lie no further
    //    from their mean than word 33 times their deviation (and never less than a coin's
    //    variance over their number allows, so a few answers that agree by chance bind little),
    //    or than the pixel's own answer. Where the answers are mixed (a penumbra, an edge) that
    //    binds nothing; where they agree (the ground a shadow has just left or just reached, in
    //    whole or as one lamp's part of the light) the history is brought to them at once, and
    //    given up by as much as it lay outside. That is what removes the wake of a moving
    //    caster, with one lamp or several.
    //  - Inside a penumbra the mean of the last few frames is kept beside the long one, and
    //    where the two are apart by t_reject (from REJECT_FROM of it on) the long one is given
    //    up: two or three frames that agree against the history do that, one stray ray does not.
    //  - Under a lamp that moves (a hand torch), the shadows of what is carried with it move
    //    as it does, and those of what stands still swing against it, by the lamp's step times
    //    (hit to pixel) / (hit to lamp). The ray to the pixel's strongest lamp says which it is
    //    where it is blocked: by something within word 32 of the lamp (the carrier's arm, body
    //    and stick, which throw the wide penumbrae that need the history most), or by something
    //    further off. The blocked rays around the pixel vote: more of the first kind, and the
    //    history is looked up where the lamp's motion puts it (exact for what is carried);
    //    else where the surface was, and it may hold no more frames than keep the swing within
    //    word 31 (BB_LAMP_SHADOW_TRAIL). With BB_LAMP_SHADOW_FOLLOW=0 it is always looked up
    //    where the surface was, and the first kind trails by the lamp's whole step. A lamp
    //    that was not there the frame before (a very large step) has no history under its
    //    shadows.
    const float answer = ratio; // what this frame's rays said (view 1)
    float frames = 0.0;         // the frames of history in the ratio (view 5)
    vec3 looked = vec3(0.0, 0.0, 1.0); // view 6
#ifndef HALF
    if (blend) {
        // Words 12 to 15 of the strongest lamp's record: its motion, and how far that is.
        vec3 top_moved = vec3(0.0);
        float top_step = 0.0;
        if (live && top_at != 0u) {
            top_moved = vec3(word(top_at + 12u), word(top_at + 13u), word(top_at + 14u));
            top_step = word(top_at + 15u);
        }
        float blocker = -1.0;
        if (top_step > 0.0 && top_left >= 0.0) {
            blocker = top_left < word(history_at + 32u) ? -2.0 : min(top_went / max(top_left, 0.05), 64.0);
        }
        group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
        group_cast[gl_LocalInvocationIndex] = blocker;
        barrier();
        if (!live) {
            return;
        }
        // The 5x5 answers around the pixel, moved in from the workgroup's rim so that every
        // pixel has 25 places to ask (this pixel's own is always one of them).
        const ivec2 around_lo = clamp(ivec2(gl_LocalInvocationID.xy) - 2, ivec2(0), ivec2(3));
        float count = 0.0, sum = 0.0, sum2 = 0.0, near_n = 0.0, far_n = 0.0, swing = 0.0;
        for (int y = around_lo.y; y < around_lo.y + 5; ++y) {
            for (int x = around_lo.x; x < around_lo.x + 5; ++x) {
                const float a = group_answer[y * 8 + x];
                if (a >= 0.0) {
                    count += 1.0;
                    sum += a;
                    sum2 += a * a;
                    if (top_step > 0.0) {
                        const float c = group_cast[y * 8 + x];
                        if (c >= 0.0) {
                            far_n += 1.0;
                            swing += c;
                        } else if (c < -1.5) {
                            near_n += 1.0;
                        }
                    }
                }
            }
        }
        // carried: what shadows this place moves with the lamp. slip: how far the place the
        // history is looked up at is off for every frame it holds, m.
        const bool carried = near_n > far_n;
        const bool follows = carried && top_moved != vec3(0.0);
        float slip = 0.0;
        if (top_step > 0.0) {
            if (carried) {
                slip = follows ? 0.0 : top_step;
            } else if (far_n > 0.0) {
                slip = top_step * swing / far_n;
            }
            looked = follows ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
        } else {
            looked = vec3(0.0, 0.2, 0.2);
        }
        float fast = answer;
        float held_ratio = 1.0, held_frames = 0.0, held_fast = 1.0;
        if ((history_flags & HISTORY_READ) != 0u &&
            blendHistory(P, history_at, follows ? top_moved : vec3(0.0), held_ratio, held_frames, held_fast)) {
            fast = mix(answer, held_fast, FAST_KEEP);
            frames = min(held_frames, word(history_at + 30u));
            const float trail = word(history_at + 31u);
            if (slip > 0.0 && trail > 0.0) {
                frames = min(frames, trail / slip);
            }
            if (t_reject > 0.0 && frames > 1.5) {
                // (A history of one frame is never dropped here: its ray and this one are all
                // there is.)
                frames *= 1.0 - smoothstep(REJECT_FROM * t_reject, t_reject, abs(fast - held_ratio));
            }
            const float around = word(history_at + 33u);
            if (around > 0.0) {
                const float mean = sum / count;
                const float spread = around * sqrt(max(sum2 / count - mean * mean, 0.0) + AROUND_FLOOR / count);
                const float fitted = clamp(held_ratio, min(mean - spread, answer), max(mean + spread, answer));
                const float taken = smoothstep(AROUND_FROM, AROUND_ALL, abs(fitted - held_ratio));
                frames *= 1.0 - taken;
                held_ratio = fitted;
                looked.r = taken;
            }
            ratio = mix(answer, held_ratio, frames / (frames + 1.0));
        }
        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));
    } else
#endif
    if ((history_flags & HISTORY_WRITE) != 0u) {
        imageStore(history_cur, px, vec4(ratio, P.z, stable, 1.0));
"""),
        (r"""    if (t_view != 0u) {
        // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_VIEW, on pixels the pass shadows, in place of
        // their light (the game multiplies it by the surface's colour). 1: the shadow ratio. 2:
        // how many lamp records have weight here (1 blue, 2 green, 3 yellow, 4 or more red),
        // dimmer the smaller the strongest one's share. 3: rays this pixel cast (0 blue, 1
        // green, 2 yellow, 3 or more red). The history and the half-resolution answers hold the
        // ratio as always.
        vec3 shown = vec3(ratio);
        if (t_view == 2u) {
            shown = stepColour(lamps - 1u) * (0.25 + 0.75 * view_top / wsum);
""",
         r"""    if (t_view != 0u) {
        // bbport (r41_lamp-shadows): BB_LAMP_SHADOW_VIEW, on pixels the pass shadows, in place of
        // their light (the game multiplies it by the surface's colour). 1: the shadow ratio as
        // this frame's rays gave it. 2: how many lamp records have weight here (1 blue, 2 green,
        // 3 yellow, 4 or more red), dimmer the smaller the strongest one's share. 3: rays this
        // pixel cast (0 blue, 1 green, 2 yellow, 3 or more red). bbport (r42_lamp-soft): 4: the
        // ratio as it is used, averaged over the frames (the same as 1 without a history). 5:
        // the frames of history in it, red none to green all it may hold (blue: this pass
        // averages nothing). 6: where the history was looked up: green where a moving lamp's
        // motion puts it, blue where the surface was under a moving lamp, dim under a lamp
        // that stands; red: how much of it this frame's answers around the pixel took away.
        // The history and the half-resolution answers hold the ratio as always.
        vec3 shown = vec3(answer);
        if (t_view == 2u) {
            shown = stepColour(lamps - 1u) * (0.25 + 0.75 * view_top / wsum);
"""),
        (r"""        } else if (t_view == 3u) {
            shown = stepColour(rays_cast);
        }
        out0 = shown * t_gain;
""",
         r"""        } else if (t_view == 3u) {
            shown = stepColour(rays_cast);
        } else if (t_view == 4u) {
            shown = vec3(ratio);
        } else if (t_view == 5u) {
            shown = vec3(0.0, 0.0, 1.0);
            if (blend) {
                const float held = clamp(frames / max(word(history_at + 30u), 1.0), 0.0, 1.0);
                shown = vec3(1.0 - held, held, 0.0);
            }
        } else if (t_view == 6u) {
            shown = looked;
        }
        out0 = shown * t_gain;
"""),
    ],
    R + "lamp_shadow_tune.h": [
        (r"""// sixteen words PointShadow::Flush appends to the pass's data, and the weight of a lamp as the
// shader works it out. No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it alone.

#include <algorithm>
""",
         r"""// sixteen words PointShadow::Flush appends to the pass's data, and the weight of a lamp as the
// shader works it out. No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it alone.
// bbport (r42_lamp-soft): the lamp is an area light now (one ray a frame to a point of its disc,
// averaged over frames in the pass's history); the rim rays of r41 and their knobs are gone.

#include <algorithm>
"""),
        (r"""#include <cstdint>
#include <cstdlib>

namespace Vulkan {
""",
         r"""#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace Vulkan {
"""),
        (r"""    float wrap = 0.15f;          ///< BB_LAMP_SHADOW_WRAP, 0..1: N.L tolerance; 1: no N.L
    float facing_floor = 0.05f;  ///< BB_LAMP_SHADOW_FLOOR, 0..1: least facing factor; 0: none
    float radius_m = 0.05f;      ///< BB_LAMP_SHADOW_SOFT, 0..0.3: the lamp's radius; 0: a point
    std::uint32_t rim = 3;       ///< BB_LAMP_SHADOW_RIM, 0..4: rays to the lamp's rim
    float share = 0.25f;         ///< BB_LAMP_SHADOW_SHARE, 0..1: least weight share for rim rays
    float near_part = 0.5f;      ///< BB_LAMP_SHADOW_NEAR, 0.05..1: rim rays for casters this near
                                 ///< the lamp (share of the way to the receiver); 1: everywhere
    float clearance_m = 0.35f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp
    float bias_m = 0.03f;        ///< BB_LAMP_SHADOW_BIAS, 0.005..0.2: ray start offset (the push block)
    float self_m = 0.06f;        ///< BB_LAMP_SHADOW_SELF, 0..0.3: grazing self skip
    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..3: debug view
    float view_gain = 0.5f;      ///< BB_LAMP_SHADOW_VIEW_GAIN, 0.01..16
};
""",
         r"""    float wrap = 0.15f;          ///< BB_LAMP_SHADOW_WRAP, 0..1: N.L tolerance; 1: no N.L
    float facing_floor = 0.05f;  ///< BB_LAMP_SHADOW_FLOOR, 0..1: least facing factor; 0: none
    float radius_m = 0.1f;       ///< BB_LAMP_SHADOW_SOFT, 0..0.5: the lamp's radius; 0: a point
    float history = 0.9f;        ///< BB_LAMP_SHADOW_HISTORY, 0..0.98: share of the frames before
                                 ///< in the shadow ratio; 0: this frame's ray alone
    float reject = 0.5f;         ///< BB_LAMP_SHADOW_REJECT, 0 or 0.45..1: the history is dropped
                                 ///< where the last frames' ratio is this far from it; 0: never
    float trail_m = 0.08f;       ///< BB_LAMP_SHADOW_TRAIL, 0..2: how far a moving lamp's shadows
                                 ///< may trail, metres; 0: its motion does not shorten the history
    bool follow = true;          ///< BB_LAMP_SHADOW_FOLLOW: the history is looked up where a
                                 ///< moving lamp's motion puts it (LampTrack); 0: where the
                                 ///< surface was
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
                                 ///< this distance of it is taken to move with it, metres
    float around = 1.6f;         ///< BB_LAMP_SHADOW_CLAMP, 0 or 0.5..4: the history may lie this
                                 ///< many deviations from this frame's answers around the
                                 ///< pixel; 0: anywhere
    bool stale = false;          ///< BB_LAMP_SHADOW_STALE: 1: starved moving shared copies are left
                                 ///< out of lamp rays (r41); 0: they stay in (vk_rt_shadow.cpp)
    float clearance_m = 0.35f;   ///< BB_LAMP_SHADOW_CLEARANCE, 0.05..2: blind sphere at the lamp
    float bias_m = 0.03f;        ///< BB_LAMP_SHADOW_BIAS, 0.005..0.2: ray start offset (the push block)
    float self_m = 0.06f;        ///< BB_LAMP_SHADOW_SELF, 0..0.3: grazing self skip
    std::uint32_t view = 0;      ///< BB_LAMP_SHADOW_VIEW, 0..6: debug view
    float view_gain = 0.5f;      ///< BB_LAMP_SHADOW_VIEW_GAIN, 0.01..16
};
"""),
        (r"""inline constexpr std::uint32_t LampTuneWordCount = 16;
// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 4-6 rim rays, bits 8-9 the view. Words 1-9, floats: clearance,
// radius, share, self skip, wrap, the inverse-square curve's core squared, view gain, facing
// floor, near part. Words 10-12 and 13-15: two axes of the world in view space, unit length and
// square to each other (the rim pattern's frame): world +x (horizontal) and world +y (up).
inline constexpr std::uint32_t LampTuneNewWeights = 1, LampTuneInverseSquare = 2;
inline constexpr std::uint32_t LampTuneRimShift = 4, LampTuneViewShift = 8;

using LampTuneGet = const char* (*)(const char*);
""",
         r"""inline constexpr std::uint32_t LampTuneWordCount = 16;
// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
// radius, 4 self skip, 5 wrap, 6 the inverse-square curve's core squared, 7 view gain, 8 facing
// floor, 9 reject. Words 10-12 and 13-15: two axes of the world in view space, unit length and
// square to each other (the frame the lamp's disc is laid out in): world +x (horizontal) and
// world +y (up).
inline constexpr std::uint32_t LampTuneNewWeights = 1, LampTuneInverseSquare = 2;
inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 6;
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
// the shader's mean of the last few frames by 0.4 (1 - FAST_KEEP), and the reject sets in at 0.9
// of the knob (REJECT_FROM): below 0.45 every such ray would drop the history, and the picture
// would stay as noisy as one frame's.
inline constexpr float LampRejectLeast = 0.45f;
// The least BB_LAMP_SHADOW_CLAMP that is not 0: below it the 25 answers around a pixel would
// bind its history inside a penumbra too, where they are a coin's throws.
inline constexpr float LampAroundLeast = 0.5f;

using LampTuneGet = const char* (*)(const char*);
"""),
        (r"""    tune.wrap = Number(get, "BB_LAMP_SHADOW_WRAP", tune.wrap, 0.0f, 1.0f);
    tune.facing_floor = Number(get, "BB_LAMP_SHADOW_FLOOR", tune.facing_floor, 0.0f, 1.0f);
    tune.radius_m = Number(get, "BB_LAMP_SHADOW_SOFT", tune.radius_m, 0.0f, 0.3f);
    tune.rim = Whole(get, "BB_LAMP_SHADOW_RIM", tune.rim, 4u);
    tune.share = Number(get, "BB_LAMP_SHADOW_SHARE", tune.share, 0.0f, 1.0f);
    tune.near_part = Number(get, "BB_LAMP_SHADOW_NEAR", tune.near_part, 0.05f, 1.0f);
    tune.clearance_m = Number(get, "BB_LAMP_SHADOW_CLEARANCE", tune.clearance_m, 0.05f, 2.0f);
    tune.bias_m = Number(get, "BB_LAMP_SHADOW_BIAS", tune.bias_m, 0.005f, 0.2f);
    tune.self_m = Number(get, "BB_LAMP_SHADOW_SELF", tune.self_m, 0.0f, 0.3f);
    tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, 3u);
    tune.view_gain = Number(get, "BB_LAMP_SHADOW_VIEW_GAIN", tune.view_gain, 0.01f, 16.0f);
    return tune;
""",
         r"""    tune.wrap = Number(get, "BB_LAMP_SHADOW_WRAP", tune.wrap, 0.0f, 1.0f);
    tune.facing_floor = Number(get, "BB_LAMP_SHADOW_FLOOR", tune.facing_floor, 0.0f, 1.0f);
    tune.radius_m = Number(get, "BB_LAMP_SHADOW_SOFT", tune.radius_m, 0.0f, 0.5f);
    tune.history = Number(get, "BB_LAMP_SHADOW_HISTORY", tune.history, 0.0f, 0.98f);
    tune.reject = Number(get, "BB_LAMP_SHADOW_REJECT", tune.reject, 0.0f, 1.0f);
    if (tune.reject > 0.0f) {
        tune.reject = std::max(tune.reject, LampRejectLeast);
    }
    tune.trail_m = Number(get, "BB_LAMP_SHADOW_TRAIL", tune.trail_m, 0.0f, 2.0f);
    tune.follow = Whole(get, "BB_LAMP_SHADOW_FOLLOW", tune.follow ? 1u : 0u, 1u) != 0;
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
    tune.around = Number(get, "BB_LAMP_SHADOW_CLAMP", tune.around, 0.0f, 4.0f);
    if (tune.around > 0.0f) {
        tune.around = std::max(tune.around, LampAroundLeast);
    }
    tune.stale = Whole(get, "BB_LAMP_SHADOW_STALE", tune.stale ? 1u : 0u, 1u) != 0;
    tune.clearance_m = Number(get, "BB_LAMP_SHADOW_CLEARANCE", tune.clearance_m, 0.05f, 2.0f);
    tune.bias_m = Number(get, "BB_LAMP_SHADOW_BIAS", tune.bias_m, 0.005f, 0.2f);
    tune.self_m = Number(get, "BB_LAMP_SHADOW_SELF", tune.self_m, 0.0f, 0.3f);
    tune.view = Whole(get, "BB_LAMP_SHADOW_VIEW", tune.view, LampTuneViewMax);
    tune.view_gain = Number(get, "BB_LAMP_SHADOW_VIEW_GAIN", tune.view_gain, 0.01f, 16.0f);
    return tune;
"""),
        (r"""/// matrix as 12 floats in rows of four (CameraMotion::Matrices::view, a VkTransformMatrixKHR):
/// its first two columns, made unit length. No matrix, or columns that are not finite, not of
/// about unit length or not square to each other: the view's own x and y axes (the rim pattern
/// then turns with the camera, as it did before the axes were handed over).
inline std::array<float, 6> LampTuneAxes(const float* view) {
    constexpr std::array<float, 6> Own{1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
""",
         r"""/// matrix as 12 floats in rows of four (CameraMotion::Matrices::view, a VkTransformMatrixKHR):
/// its first two columns, made unit length. No matrix, or columns that are not finite, not of
/// about unit length or not square to each other: the view's own x and y axes (the disc's frame
/// then turns with the camera).
inline std::array<float, 6> LampTuneAxes(const float* view) {
    constexpr std::array<float, 6> Own{1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f};
"""),
        (r"""}

/// What the shader reads at the place the mode word names. inverse_square, core: the lamp
/// falloff the game's shaders were patched to (startup_local_inverse_square,
/// startup_local_light_core). view: see LampTuneAxes.
inline std::array<std::uint32_t, LampTuneWordCount> LampTuneWords(const LampShadowTune& tune,
                                                                  bool inverse_square, float core,
                                                                  const float* view = nullptr) {
    const auto bits = [](float v) { return std::bit_cast<std::uint32_t>(v); };
    core = LampTuneCore(core);
""",
         r"""}

/// bbport (r42_lamp-soft): the frames of history a pixel's shadow ratio may hold: a frame's
/// share is 1 / (frames + 1), so BB_LAMP_SHADOW_HISTORY 0.9 is nine frames. 0: this frame's ray
/// alone, no history (a point lamp, or BB_LAMP_SHADOW_HISTORY=0).
inline float LampHistoryFrames(const LampShadowTune& tune) {
    if (!(tune.radius_m > 0.0f) || !(tune.history > 0.0f)) {
        return 0.0f;
    }
    return tune.history / (1.0f - std::min(tune.history, 0.98f));
}

/// What the shader reads at the place the mode word names. inverse_square, core: the lamp
/// falloff the game's shaders were patched to (startup_local_inverse_square,
/// startup_local_light_core). view: see LampTuneAxes. frame: the frame counter.
inline std::array<std::uint32_t, LampTuneWordCount> LampTuneWords(const LampShadowTune& tune,
                                                                  bool inverse_square, float core,
                                                                  const float* view = nullptr,
                                                                  std::uint32_t frame = 0) {
    const auto bits = [](float v) { return std::bit_cast<std::uint32_t>(v); };
    core = LampTuneCore(core);
"""),
        (r"""    const std::uint32_t flags = (tune.weights ? LampTuneNewWeights : 0u) |
                                (inverse_square ? LampTuneInverseSquare : 0u) |
                                std::min<std::uint32_t>(tune.rim, 7u) << LampTuneRimShift |
                                std::min<std::uint32_t>(tune.view, 3u) << LampTuneViewShift;
    return {flags,
            bits(tune.clearance_m),
            bits(tune.radius_m),
            bits(tune.share),
            bits(tune.self_m),
            bits(tune.wrap),
""",
         r"""    const std::uint32_t flags = (tune.weights ? LampTuneNewWeights : 0u) |
                                (inverse_square ? LampTuneInverseSquare : 0u) |
                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift;
    return {flags,
            bits(tune.clearance_m),
            bits(tune.radius_m),
            frame,
            bits(tune.self_m),
            bits(tune.wrap),
"""),
        (r"""            bits(tune.view_gain),
            bits(tune.facing_floor),
            bits(tune.near_part),
            bits(axes[0]),
            bits(axes[1]),
""",
         r"""            bits(tune.view_gain),
            bits(tune.facing_floor),
            bits(tune.reject),
            bits(axes[0]),
            bits(axes[1]),
"""),
        (r"""}

} // namespace Vulkan
""",
         r"""}

/// bbport (r42_lamp-soft): the last four words of the pass's history block (words 30 to 33,
/// point_shadow_ray.comp HISTORY_BLEND): the most frames a texel may hold, how far a moving
/// lamp's shadows may trail, within what distance of a moving lamp a caster is taken to move
/// with it, and how many deviations of the answers around a pixel its history may lie from
/// their mean.
inline constexpr std::uint32_t LampHistoryTailWords = 4;
inline std::array<std::uint32_t, LampHistoryTailWords> LampHistoryTail(const LampShadowTune& tune) {
    return {std::bit_cast<std::uint32_t>(LampHistoryFrames(tune)), std::bit_cast<std::uint32_t>(tune.trail_m),
            std::bit_cast<std::uint32_t>(tune.carry_m), std::bit_cast<std::uint32_t>(tune.around)};
}

/// bbport (r42_lamp-soft): whether the camera jumped between two frames: `back` is the way from
/// this frame's view space to that of the frame before (12 floats in rows of four, the history
/// block's words 2 to 13). More than 2 m or more than about 20 degrees in one frame is a cut
/// (a cutscene's change of shot, a warp), not a camera's motion: the history of the frame before
/// then shows another place, and what of it passes the depth test does so by chance.
inline bool LampCameraCut(const float* back) {
    const float moved2 = back[3] * back[3] + back[7] * back[7] + back[11] * back[11];
    const float trace = back[0] + back[5] + back[10];
    // (1 + 2 cos 20 degrees = 2.879; not finite counts as a cut.)
    return !(moved2 <= 4.0f) || !(trace >= 2.879f);
}

/// bbport (r42_lamp-soft): one lamp of a pass (LampTrack).
struct LampSeen {
    std::array<std::uint32_t, 7> key{}; ///< its place in view space, 1 / reach squared and its
                                        ///< colour, as the records hold them
    std::array<float, 3> world{};       ///< its place in the world
    std::array<float, 3> moved{};       ///< since the frame before, in the world; zero unless followed
    float radius = 0.0f;                ///< its reach, m
    float luma = 0.0f;                  ///< of its colour
    float away = 0.0f;                  ///< from the camera, m
    std::uint32_t records = 0;          ///< records of the pass that hold it (one a tile it reaches)
    bool followed = false;              ///< found in the frame before
    /// Since LampTrack::ClearSteps, along the frames it was followed: how many, and the sum
    /// and the largest of its steps, m (a flame's lamp that wobbles shows here).
    std::uint32_t steps = 0;
    float step_sum = 0.0f, step_most = 0.0f;
};

/// bbport (r42_lamp-soft): the lamps of the pass that holds the shadow history, told apart and
/// followed from one frame to the next. A hand torch moves with the one who carries it, and so do
/// the shadows it throws of its carrier, on the ground and on the carrier itself: a history
/// looked up where the ground was a frame ago holds them where they were, and they smear for as
/// long as it lasts. So the pass looks a pixel's history up where the pixel's strongest lamp
/// would put it: moved back by that lamp's motion (Shift, in the lamp records' words 12 to
/// 14), where what blocks the lamp there is near it (the shader decides, see its HISTORY_BLEND).
/// For what moves with the lamp that is exact; for a still caster under a moving lamp it is
/// not, which the shader bounds by the lamp's step (Step, word 15). The same list feeds the log
/// line that says where the lamps near the camera are.
/// A record: 16 words, the lamp's place in view space (3 floats), 1 / reach squared, its colour
/// (3 floats); two records are one lamp when those seven words are the same bits (a lamp is
/// listed once for every tile it reaches; two lights of a torch at one place with different
/// reach or colour are two lamps).
class LampTrack {
public:
    static constexpr std::uint32_t Most = 64; ///< lamps told apart in a pass; more are not followed
    static constexpr float Reach = 0.6f;      ///< a lamp further than this from every lamp of the
                                              ///< frame before is a new one, m
    static constexpr float Still = 0.002f;    ///< a lamp that moved less stands still, m
    static constexpr float Near = 15.0f;      ///< "near the camera", m
    static constexpr float Lost = 1000.0f;    ///< Step of a lamp that was not there the frame
                                              ///< before, m: no history holds under its shadows

    /// A pass begins. inv_view: its camera, view to world, 12 floats in rows of four; null: not
    /// known (nothing is followed this frame or the next).
    void Begin(const float* inv_view) {
        count = 0;
        slots.fill(0);
        matched = false;
        has_world = inv_view != nullptr;
        if (inv_view) {
            std::memcpy(to_world.data(), inv_view, sizeof(to_world));
        }
    }

    /// How far a record's lamp is from the camera, m (the pass adds the records of lamps within
    /// Near first, so that with more than Most lamps in a pass the near ones are followed).
    [[nodiscard]] static float Away(const std::uint32_t* record) {
        const float x = std::bit_cast<float>(record[0]), y = std::bit_cast<float>(record[1]),
                    z = std::bit_cast<float>(record[2]);
        return std::sqrt(x * x + y * y + z * z);
    }

    /// One record of the pass. Its lamp's index in Lamps(), or -1: no lamp (no reach), or more
    /// than Most.
    int Add(const std::uint32_t* record) {
        const float inv_r2 = std::bit_cast<float>(record[3]);
        if (!(inv_r2 > 0.0f) || !std::isfinite(inv_r2)) {
            return -1;
        }
        std::uint32_t at = (record[0] * 0x9E3779B1u ^ record[1] * 0x85EBCA77u ^ record[2] * 0xC2B2AE3Du) >> 24;
        for (std::uint32_t tries = 0; tries < slots.size(); ++tries, at = (at + 1) & 255u) {
            if (slots[at] == 0) {
                break;
            }
            LampSeen& lamp = lamps[slots[at] - 1u];
            if (std::equal(lamp.key.begin(), lamp.key.end(), record)) {
                ++lamp.records;
                return int(slots[at]) - 1;
            }
        }
        if (count >= Most) {
            return -1;
        }
        LampSeen& lamp = lamps[count];
        lamp = {};
        std::copy_n(record, lamp.key.size(), lamp.key.begin());
        const std::array<float, 3> v{std::bit_cast<float>(record[0]), std::bit_cast<float>(record[1]),
                                     std::bit_cast<float>(record[2])};
        for (int r = 0; r < 3; ++r) {
            lamp.world[r] = has_world ? to_world[r * 4] * v[0] + to_world[r * 4 + 1] * v[1] +
                                            to_world[r * 4 + 2] * v[2] + to_world[r * 4 + 3]
                                      : v[r];
        }
        lamp.radius = 1.0f / std::sqrt(inv_r2);
        lamp.luma = 0.299f * std::bit_cast<float>(record[4]) + 0.587f * std::bit_cast<float>(record[5]) +
                    0.114f * std::bit_cast<float>(record[6]);
        lamp.away = Away(record);
        lamp.records = 1;
        slots[at] = std::uint8_t(++count);
        return int(count) - 1;
    }

    /// After the pass's last record: finds each lamp in the frame before, one of this frame for
    /// one of that.
    ///  - A lamp can be one of the frame before that lies within Reach of it, or whose place
    ///    plus the step it made then does (a lamp that moves goes on moving).
    ///  - Each lamp takes the nearest such one that is free (nearer by place or by place plus
    ///    step; among equals the one of its own reach); where two want the same, the nearer has
    ///    it and the other looks again.
    ///  - Then pairs change partners where that brings both nearer in sum (of squares): two
    ///    lamps a few centimetres apart that set off together would else each take the other's
    ///    place of the frame before, or one of them none (a hand torch made of two lights).
    void Follow() {
        if (!has_world || !had_world) {
            return;
        }
        matched = true;
        std::array<int, Most> from{}, taken{};
        std::array<float, Most> gap{};
        from.fill(-1);
        taken.fill(-1);
        for (std::uint32_t round = 0; round < 6; ++round) {
            bool asked = false;
            std::array<int, Most> want{};
            want.fill(-1);
            for (std::uint32_t i = 0; i < count; ++i) {
                if (from[i] >= 0) {
                    continue;
                }
                float best = Far;
                for (std::uint32_t j = 0; j < before_count; ++j) {
                    if (taken[j] >= 0) {
                        continue;
                    }
                    const float d = Gap(lamps[i], before[j]);
                    if (d < best) {
                        best = d;
                        want[i] = int(j);
                    }
                }
                gap[i] = best;
                asked = asked || want[i] >= 0;
            }
            if (!asked) {
                break;
            }
            for (std::uint32_t i = 0; i < count; ++i) {
                if (want[i] < 0) {
                    continue;
                }
                const std::uint32_t j = std::uint32_t(want[i]);
                if (taken[j] < 0 || gap[i] < gap[std::uint32_t(taken[j])]) {
                    if (taken[j] >= 0) {
                        from[std::uint32_t(taken[j])] = -1;
                    }
                    taken[j] = int(i);
                    from[i] = int(j);
                }
            }
        }
        for (std::uint32_t sweep = 0; sweep < 4; ++sweep) {
            bool changed = false;
            for (std::uint32_t i = 0; i < count; ++i) {
                // (A lamp that stands where it stood has its own.)
                if (from[i] < 0 || gap[i] < Still * Still) {
                    continue;
                }
                for (std::uint32_t k = i + 1; k < count; ++k) {
                    if (from[k] < 0 || gap[k] < Still * Still) {
                        continue;
                    }
                    const float ik = Gap(lamps[i], before[std::uint32_t(from[k])]),
                                ki = Gap(lamps[k], before[std::uint32_t(from[i])]);
                    if (ik < Far && ki < Far && ik + ki < (gap[i] + gap[k]) * 0.999f) {
                        std::swap(from[i], from[k]);
                        gap[i] = ik;
                        gap[k] = ki;
                        changed = true;
                    }
                }
            }
            if (!changed) {
                break;
            }
        }
        for (std::uint32_t i = 0; i < count; ++i) {
            if (from[i] < 0) {
                continue;
            }
            LampSeen& lamp = lamps[i];
            const LampSeen& was = before[std::uint32_t(from[i])];
            lamp.followed = true;
            float d2 = 0.0f;
            for (int c = 0; c < 3; ++c) {
                d2 += (lamp.world[c] - was.world[c]) * (lamp.world[c] - was.world[c]);
            }
            if (d2 >= Still * Still) {
                for (int c = 0; c < 3; ++c) {
                    lamp.moved[c] = lamp.world[c] - was.world[c];
                }
            }
            const float step = d2 >= Still * Still ? std::sqrt(d2) : 0.0f;
            lamp.steps = was.steps + 1;
            lamp.step_sum = was.step_sum + step;
            lamp.step_most = std::max(was.step_most, step);
        }
    }

    [[nodiscard]] std::uint32_t Count() const noexcept {
        return count;
    }
    [[nodiscard]] const LampSeen& Lamp(std::uint32_t index) const noexcept {
        return lamps[index];
    }

    /// What the pass takes from a pixel's place in the view space of the frame before to find
    /// the history its strongest lamp's shadows left: the lamp's motion, turned into that view
    /// space. before_view: the camera of the frame before, world to view, 12 floats in rows of
    /// four. Zero for a lamp that stands still or is not followed.
    [[nodiscard]] std::array<float, 3> Shift(int index, const float* before_view) const {
        std::array<float, 3> out{};
        if (index < 0 || std::uint32_t(index) >= count || !before_view) {
            return out;
        }
        const auto& m = lamps[std::uint32_t(index)].moved;
        for (int r = 0; r < 3; ++r) {
            out[r] = before_view[r * 4] * m[0] + before_view[r * 4 + 1] * m[1] + before_view[r * 4 + 2] * m[2];
        }
        return out;
    }

    /// How far the lamp moved since the frame before, metres: the pass shortens the history
    /// under a moving lamp's shadows by it (BB_LAMP_SHADOW_TRAIL). Zero for a lamp that stands
    /// still. Lost for a lamp that was looked for in the frame before and not found (it is new,
    /// or it jumped): what the history holds under it was made without it. Zero again where
    /// that cannot be told: no frame before, a lamp beyond Most, or a frame before that had
    /// Most lamps (the lamp may have been one more).
    [[nodiscard]] float Step(int index) const {
        if (index < 0 || std::uint32_t(index) >= count) {
            return 0.0f;
        }
        const LampSeen& lamp = lamps[std::uint32_t(index)];
        if (!lamp.followed) {
            return matched && before_count < Most ? Lost : 0.0f;
        }
        const auto& m = lamp.moved;
        return std::sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]);
    }

    /// The up to four brightest lamps within Near of the camera (the nearer first among equals),
    /// as indices; -1: no more.
    [[nodiscard]] std::array<int, 4> Strongest() const {
        std::array<int, 4> out{-1, -1, -1, -1};
        for (std::uint32_t i = 0; i < count; ++i) {
            if (!(lamps[i].away <= Near)) {
                continue;
            }
            int held = int(i);
            for (int& slot : out) {
                if (slot < 0) {
                    slot = held;
                    break;
                }
                const LampSeen& a = lamps[std::uint32_t(held)];
                const LampSeen& b = lamps[std::uint32_t(slot)];
                if (a.luma > b.luma || (a.luma == b.luma && a.away < b.away)) {
                    std::swap(slot, held);
                }
            }
        }
        return out;
    }

    /// The steps counted along the lamps start again (after the log line that printed them).
    void ClearSteps() {
        for (std::uint32_t i = 0; i < count; ++i) {
            lamps[i].steps = 0;
            lamps[i].step_sum = lamps[i].step_most = 0.0f;
        }
    }

    /// The frame ends. kept: the pass ran with a history, so its lamps are "the frame before" of
    /// the next; false: the next frame follows nothing.
    void End(bool kept) {
        had_world = kept && has_world;
        before_count = had_world ? count : 0;
        if (had_world) {
            std::copy_n(lamps.begin(), count, before.begin());
        }
        count = 0;
        has_world = false;
    }

private:
    static constexpr float Far = 1e30f; ///< Gap of two lamps that cannot be one

    /// How far lamp `now` is from where lamp `was` (of the frame before) stood or would be had
    /// it gone on as it moved then, squared, plus a little for a different reach (which only
    /// decides between places equally near: a flame's reach may flicker); Far: beyond Reach.
    static float Gap(const LampSeen& now, const LampSeen& was) {
        float stood = 0.0f, went = 0.0f;
        for (int c = 0; c < 3; ++c) {
            const float d = now.world[c] - was.world[c];
            stood += d * d;
            went += (d - was.moved[c]) * (d - was.moved[c]);
        }
        const float least = std::min(stood, went);
        if (!(least <= Reach * Reach)) {
            return Far;
        }
        const float reach = std::log(std::max(now.radius, 1e-6f) / std::max(was.radius, 1e-6f));
        return least + 0.0625f * reach * reach;
    }

    std::array<LampSeen, Most> lamps{}, before{};
    std::array<std::uint8_t, 256> slots{};
    std::array<float, 12> to_world{};
    std::uint32_t count = 0, before_count = 0;
    bool has_world = false, had_world = false;
    bool matched = false; ///< Follow looked for this frame's lamps in the frame before
};

} // namespace Vulkan
"""),
    ],
    R + "vk_point_shadow.h": [
        (r"""    LampShadowTune tune;
    int repair_state = -1;
    bool tried = false;
    bool failed = false;
""",
         r"""    LampShadowTune tune;
    int repair_state = -1;
    // bbport (r42_lamp-soft): the area lamp. The lamps of the pass that takes the history, told
    // apart and followed from frame to frame (TrackLamps; track_index: the lamp of each record
    // of that pass, track_frame: the frame it last ran on); whether the history written on this
    // frame, and the one the frame before left, hold ratios averaged over the frames
    // (HistoryBlend) and not LANTERN_RT_LAMP_REUSE's; what the lamps were on the last pass that
    // could take the history (-1: none yet), for the log line at each change; frames since the
    // line that says where the lamps are (the first one comes two seconds in).
    LampTrack track;
    std::vector<s8> track_index;
    u32 track_frame = ~0u;
    bool history_blend = false, history_blended = false;
    int soft_state = -1;
    u32 soft_lines = 0;       ///< lines that said what the lamps are (at most SoftLines)
    u32 blend_unread = 0;     ///< frames in a row on which the averaging pass could not read its history
    // Since the last line that says where the lamps are: frames the pass averaged on, those of
    // them on which it read its history, camera cuts it did not read across, and ray traced
    // lamp passes that ran beside it with point lamps.
    u32 line_blend = 0, line_read = 0, line_cuts = 0, line_beside = 0;
    u32 lamp_line_frames = 480;
    void TrackLamps(u32 end, bool blend, bool read, bool line);
    bool tried = false;
    bool failed = false;
"""),
    ],
    R + "vk_point_shadow.cpp": [
        (r"""constexpr u32 WholeImageBatches = 4;
constexpr u32 SnapshotCell = 16;
constexpr u32 HistoryWords = 2 + 12 + 16; // what Flush adds for the first ray traced pass of a frame
constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
// bbport (r41_lamp-shadows): MODE_REPAIR, and where the place of the pass's tuning words
""",
         r"""constexpr u32 WholeImageBatches = 4;
constexpr u32 SnapshotCell = 16;
// What Flush adds for the first ray traced pass of a frame. bbport (r42_lamp-soft): four more
// words (LampHistoryTail): the most frames a texel of the history may hold, how far a moving
// lamp's shadows may trail, how near a moving lamp a caster is taken to move with it, and how
// far the history may lie from the answers around a pixel (point_shadow_ray.comp HISTORY_BLEND).
constexpr u32 HistoryWords = 2 + 12 + 16 + LampHistoryTailWords;
constexpr u32 ModeApart = 1;              // point_shadow_ray.comp MODE_APART
// bbport (r41_lamp-shadows): MODE_REPAIR, and where the place of the pass's tuning words
"""),
        (r"""constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr u32 HistoryRead = 1, HistoryWrite = 2;

std::array<float, 16> Invert(const u32* words, bool& ok) {
""",
         r"""constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr u32 HistoryRead = 1, HistoryWrite = 2;
// bbport (r42_lamp-soft): the history holds the shadow ratio averaged over the frames
// (point_shadow_ray.comp HISTORY_BLEND); frames between two lines that say where the lamps are.
constexpr u32 HistoryBlend = 4;
constexpr u32 LampLineFrames = 600;
// A pass that averages shows bare single rays on a frame on which it cannot read what the frame
// before left (the first frame, a new size, a cut). After this many such frames in a row its
// lamps are points until it can (Flush).
constexpr u32 UnreadMost = 8;
constexpr u32 SoftLines = 24; // the most "Ray traced lamps (r42): <state>" lines

std::array<float, 16> Invert(const u32* words, bool& ok) {
"""),
        (r"""        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows)
        std::printf("Ray traced lamps (r41): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s), lamp radius %.2f m with %u rim rays from share %.2f for casters within "
                    "%.2f of the way from the lamp, clearance %.2f m, bias %.3f m, self skip %.2f "
                    "m, view %u (BB_LAMP_SHADOW_*); experiment 35184372088832 set = the path "
                    "before\n",
                    tune.weights ? "as the game's falloff and facing" : "as before", tune.wrap,
                    tune.facing_floor,
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", tune.radius_m,
                    tune.rim, tune.share, tune.near_part, tune.clearance_m, tune.bias_m,
                    tune.self_m, tune.view);
    }
""",
         r"""        std::printf("Ray traced lamps: off - the pass could not be made\n");
    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
        std::printf("Ray traced lamps (r42): weights %s (wrap %.2f, floor %.2f, inverse-square "
                    "%s); area lamp radius %.2f m, one ray a lamp a frame, history %.2f (up to "
                    "%.1f frames), kept within %.1f deviations of the answers around a pixel, "
                    "reject %.2f, trail %.2f m, follows moving lamps %s (what blocks one within "
                    "%.2f m of it moves with it); starved moving copies %s lamp rays; clearance "
                    "%.2f m, bias %.3f m, self skip %.2f m, view %u (BB_LAMP_SHADOW_*); "
                    "experiment 35184372088832 set = the path before r41\n",
                    tune.weights ? "as the game's falloff and facing" : "as before", tune.wrap,
                    tune.facing_floor,
                    BbSettings::Get().startup_local_inverse_square ? "on" : "off", tune.radius_m,
                    tune.history, LampHistoryFrames(tune), tune.around, tune.reject, tune.trail_m,
                    tune.follow ? "yes" : "no", tune.carry_m,
                    tune.stale ? "are left out of" : "stay in", tune.clearance_m, tune.bias_m,
                    tune.self_m, tune.view);
    }
"""),
        (r"""        }
    }
    std::printf("Ray traced lamps (r32): half resolution (%s) %s\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
""",
         r"""        }
    }
    // bbport (r42_lamp-soft): and what it does to the area lamp (see Flush)
    std::printf("Ray traced lamps (r32): half resolution (%s) %s; at half resolution the lamps "
                "stay points without a history (r42: BB_LAMP_SHADOW_SOFT and "
                "BB_LAMP_SHADOW_HISTORY act on the full-resolution pass only)\n",
                half_env == 1 ? "BB_LAMP_SHADOW_HALF=1" : "graphics_lamp_shadow_half=1",
                half_made ? "ready" : "ignored - no pipeline");
"""),
        (r"""
void PointShadow::OnFrameEnd() {
    ++frame_index;
    if (history_written) {
""",
         r"""
void PointShadow::OnFrameEnd() {
    // bbport (r42_lamp-soft): this frame's lamps are "the frame before" of the next one when
    // its pass left an averaged history
    track.End(history_written && history_blend && track_frame == frame_index);
    ++lamp_line_frames;
    ++frame_index;
    if (history_written) {
"""),
        (r"""        last_valid = pending_valid;
        history_fresh = true;
    } else {
        history_fresh = false;
""",
         r"""        last_valid = pending_valid;
        history_fresh = true;
        history_blended = history_blend; // bbport (r42_lamp-soft)
    } else {
        history_fresh = false;
"""),
        (r"""}

void PointShadow::Flush(bool animate_noise) {
    if (tiles.empty()) {
""",
         r"""}

// bbport (r42_lamp-soft): the lamps of the pass that takes the history: its records are
// data[ConstantWords, end), LightWords each. blend: the pass averages over the frames; then
// every record gets, in words 12 to 14 (the pass reads words 0 to 6 of a record and nothing
// else; the game's records hold other things there, so they are always written), how far its
// lamp moved since the frame before, in that frame's view space, or zero
// (BB_LAMP_SHADOW_FOLLOW=0): the pass looks a pixel's history up where its strongest lamp's
// motion puts it (LampTrack); and in word 15 that distance in metres, which shortens the
// history under a moving lamp (BB_LAMP_SHADOW_TRAIL). read: there is a frame before to follow
// the lamps from. line: the log line that says where the lamps are.
void PointShadow::TrackLamps(u32 end, bool blend, bool read, bool line) {
    const auto camera = camera_motion.PassMatrices();
    const u32 records = end > ConstantWords ? (end - ConstantWords) / LightWords : 0u;
    track.Begin(camera.valid ? camera.inv_view.data() : nullptr);
    track_index.resize(records);
    // The lamps near the camera first: with more than LampTrack::Most lamps in a pass those
    // are the ones told apart and followed (a hand torch is always near). untold: records of
    // lamps beyond that number.
    u32 untold = 0;
    for (const bool close_first : {true, false}) {
        for (u32 k = 0; k < records; ++k) {
            const u32* record = data.data() + ConstantWords + k * LightWords;
            if ((LampTrack::Away(record) <= LampTrack::Near) != close_first) {
                continue;
            }
            track_index[k] = s8(track.Add(record));
            untold += track_index[k] < 0 && std::bit_cast<float>(record[3]) > 0.0f ? 1 : 0;
        }
    }
    if (blend) {
        if (read) {
            track.Follow();
        }
        for (u32 k = 0; k < records; ++k) {
            std::array<float, 3> shift{};
            if (read && tune.follow) {
                shift = track.Shift(track_index[k], last_view.data());
            }
            const float step = read ? track.Step(track_index[k]) : 0.0f;
            u32* record = data.data() + ConstantWords + k * LightWords;
            for (u32 c = 0; c < 3; ++c) {
                record[12 + c] = std::bit_cast<u32>(shift[c]);
            }
            record[15] = std::bit_cast<u32>(step);
        }
    }
    if (!line) {
        return;
    }
    lamp_line_frames = 0;
    u32 close = 0;
    for (u32 i = 0; i < track.Count(); ++i) {
        close += track.Lamp(i).away <= LampTrack::Near ? 1 : 0;
    }
    // (A lamp is told apart by its place, reach and colour: two lights of one torch at one
    // place are two lamps here. The steps: a flame whose lamp wobbles shows a mean step while
    // its carrier stands.)
    std::printf("Ray traced lamps (r42): %u lamp records in the pass, %u lamps told apart (the "
                "near ones first, %u at most; %u records are of more lamps than that), %u "
                "within %.0f m of the camera; since the last such line the pass averaged on %u "
                "frames and read its history on %u of them (%u camera cuts), and %u ray traced "
                "lamp passes beside it had point lamps; the brightest near lamps (%s, reach, "
                "luminance, distance to the camera, records, moved since the frame before; "
                "then over the frames it was followed since the last line: how many, its mean "
                "step and its largest):",
                records, track.Count(), LampTrack::Most, untold, close, double(LampTrack::Near),
                line_blend, line_read, line_cuts, line_beside,
                camera.valid ? "world x y z" : "view space x y z, the camera is not known");
    for (const int index : track.Strongest()) {
        if (index < 0) {
            break;
        }
        const LampSeen& lamp = track.Lamp(u32(index));
        std::printf(" (%.2f %.2f %.2f) %.1f m, %.2f, %.2f m, %u", lamp.world[0], lamp.world[1],
                    lamp.world[2], lamp.radius, lamp.luma, lamp.away, lamp.records);
        if (lamp.followed) {
            std::printf(", %.3f m (%u frames, mean %.4f m, most %.4f m);",
                        std::sqrt(lamp.moved[0] * lamp.moved[0] + lamp.moved[1] * lamp.moved[1] +
                                  lamp.moved[2] * lamp.moved[2]),
                        lamp.steps, lamp.steps ? lamp.step_sum / float(lamp.steps) : 0.0f,
                        lamp.step_most);
        } else {
            std::printf(", not followed;");
        }
    }
    std::printf("\n");
    line_blend = line_read = line_cuts = line_beside = 0;
    track.ClearSteps();
}

void PointShadow::Flush(bool animate_noise) {
    if (tiles.empty()) {
"""),
        (r"""    bool repair = false;
    u32 tune_at = 0;
    if (use_rays) {
        table = u32(data.size());
""",
         r"""    bool repair = false;
    u32 tune_at = 0;
    // One pass a frame can use the history. While the lamps are drawn apart that is their pass, the
    // one that covers the screen: a small batch before it (a lamp quad that could not go apart)
    // does not take it.
    const bool history_ours = batch_apart || (apart_draws == 0 && !apart_last_frame);
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    const bool half_on = half_env >= 0 ? half_env == 1
                                       : BbSettings::Get().graphics_lamp_shadow_half.load(
                                             std::memory_order_relaxed);
    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
    // lamps-apart pass in two halves (point_shadow_ray_half_comp), with the block answers in an
    // image of half the size.
    // bbport (r37_menu-options): half_on, above: BB_LAMP_SHADOW_HALF when set, else
    // graphics_lamp_shadow_half.
    // bbport (r42_lamp-soft): decided here, before the pass's tuning, which depends on it (it
    // was decided after: a pass that asked for the half resolution and did not get it, no
    // pipeline or no room, ran at full resolution with point lamps and said "half resolution").
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
    if (use_half && BbToggle::Experiment(HalfOffBit)) {
        use_half = false;
        ++half_line_full;
    }
    if (use_half) {
        const u32 half_width = (width + 1) / 2, half_height = (height + 1) / 2;
        if (half_answers.width != half_width || half_answers.height != half_height) {
            if (!EffectPass::HasRoom(instance, 8ull * half_width * half_height)) {
                use_half = false;
            } else if (EnsureImage(half_answers, half_width, half_height, HistoryFormat,
                                   "Ray traced lamp half answers")) {
                half_laid_out = false;
            }
        }
    }
    // bbport (r42_lamp-soft): the tuning of this pass. The area lamp shows one ray's answer a
    // frame, which is noise until the history has averaged it, so only the pass that takes the
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
"""),
        (r"""        }
        repair = !BbToggle::Experiment(LampRepairOffBit);
        if (repair) {
            const auto& settings = BbSettings::Get();
            // The scene the rays cross is in this camera's view space (RtShadow::PrepareScene,
            // true above, wrote its instances with this matrix): the world's axes for the rim
            // pattern, so that it does not turn with the camera.
            const auto camera = camera_motion.PassMatrices();
            const auto tune_words = LampTuneWords(tune, settings.startup_local_inverse_square,
                                                  settings.startup_local_light_core,
                                                  camera.valid ? camera.view.data() : nullptr);
            tune_at = u32(data.size());
            data.insert(data.end(), tune_words.begin(), tune_words.end());
""",
         r"""        }
        repair = !BbToggle::Experiment(LampRepairOffBit);
        line_beside += repair && beside ? 1 : 0; // bbport (r42_lamp-soft): for the lamp line
        if (repair) {
            const auto& settings = BbSettings::Get();
            // The scene the rays cross is in this camera's view space (RtShadow::PrepareScene,
            // true above, wrote its instances with this matrix): the world's axes for the
            // lamp's disc, so that it does not turn with the camera. bbport (r42_lamp-soft): and
            // the frame counter, which moves the point of the disc a ray goes to.
            const auto camera = camera_motion.PassMatrices();
            const auto tune_words = LampTuneWords(pass_tune, settings.startup_local_inverse_square,
                                                  settings.startup_local_light_core,
                                                  camera.valid ? camera.view.data() : nullptr,
                                                  frame_index);
            tune_at = u32(data.size());
            data.insert(data.end(), tune_words.begin(), tune_words.end());
"""),
        (r"""    bool clear_history = false;
    std::array<bool, 2> lay_out{};
    // One pass a frame can use the history. While the lamps are drawn apart that is their pass, the
    // one that covers the screen: a small batch before it (a lamp quad that could not go apart)
    // does not take it.
    const bool history_ours = batch_apart || (apart_draws == 0 && !apart_last_frame);
    if (use_rays && !history_written && history_ours) {
        const auto camera = camera_motion.PassMatrices();
""",
         r"""    bool clear_history = false;
    std::array<bool, 2> lay_out{};
    // (history_ours: above.)
    if (use_rays && !history_written && history_ours) {
        const auto camera = camera_motion.PassMatrices();
"""),
        (r"""        bool ok = false;
        const auto proj = Invert(data.data(), ok);
        u32 flags = lamp_reuse ? HistoryWrite : 0u;
        if (lamp_reuse && history_fresh && last_valid && camera.valid && ok) {
            flags |= HistoryRead;
        }
        history_at = u32(data.size());
""",
         r"""        bool ok = false;
        const auto proj = Invert(data.data(), ok);
        // bbport (r42_lamp-soft): the area lamp's history: the pass averages each pixel's shadow
        // ratio over the frames (HistoryBlend; `keep`: the most frames a texel may hold), which
        // takes the place of LANTERN_RT_LAMP_REUSE's history for as long as it is on. A history
        // of the other kind (the experiment bit or a setting changed) is not read.
        const float keep = repair ? LampHistoryFrames(pass_tune) : 0.0f;
        const bool blend = keep > 0.0f;
        const bool kept = blend || lamp_reuse;
        u32 flags = blend ? HistoryWrite | HistoryBlend : lamp_reuse ? HistoryWrite : 0u;
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        auto reproject = Identity;
        if (kept && history_fresh && history_blended == blend && last_valid && camera.valid &&
            ok) {
            reproject = Multiply(last_view, camera.inv_view);
            // bbport (r42_lamp-soft): an averaged history is not read across a cut (the camera
            // jumped: what of the frame before passes the depth test there does so by chance)
            if (blend && LampCameraCut(reproject.data())) {
                reproject = Identity;
                ++line_cuts;
            } else {
                flags |= HistoryRead;
            }
        }
        // bbport (r42_lamp-soft): a pass that averages and cannot read its history shows bare
        // single rays. For a frame or two that passes (the first frame, a new size, a cut); when
        // it goes on (no camera for the pass, or two ray passes of different size in every
        // frame, which make the history anew every time) the lamps are points until it can
        // read again: the tuning words are in `data` already, so their radius is zeroed there
        // (the pass still writes its history, so the first frame that can read it does).
        bool unread = false;
        if (blend) {
            blend_unread = (flags & HistoryRead) ? 0u : std::min(blend_unread + 1u, UnreadMost + 1u);
            ++line_blend;
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
                "area lamps, one ray a lamp a frame, averaged over the frames in the pass's "
                "history",
                "point lamps for now: the pass could not read its history for 8 frames (no "
                "camera for the pass, or the history is made anew every frame)",
            };
            ++soft_lines;
            std::printf("Ray traced lamps (r42): %s%s\n", What[std::size_t(soft)],
                        soft_lines == SoftLines ? " (the last time this is logged)" : "");
        }
        // (Before the lamps' records are written to: a batch without room for the block is
        // dropped as it was.)
        if (data.size() + HistoryWords > DataWords) {
            data.clear();
            return;
        }
        // The lamps of this pass, once a frame: followed for the history, and for the log line.
        // A pass that averages and comes after the frame's TrackLamps (the history was made
        // anew for it) has its lamps standing: words 12 to 15 of its records must not stay
        // what the game left there.
        if (const bool line = lamp_line_frames >= LampLineFrames; blend || line) {
            if (track_frame != frame_index) {
                track_frame = frame_index;
                TrackLamps(table, blend, (flags & HistoryRead) != 0, line);
            } else if (blend) {
                for (u32 at = ConstantWords; at + LightWords <= table; at += LightWords) {
                    std::fill_n(data.begin() + at + 12, 4, 0u);
                }
            }
        }
        history_at = u32(data.size());
"""),
        (r"""        data.push_back(flags);
        data.push_back(frame_index);
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const auto reproject = (flags & HistoryRead) ? Multiply(last_view, camera.inv_view) : Identity;
        for (const float v : reproject) {
            data.push_back(std::bit_cast<u32>(v));
""",
         r"""        data.push_back(flags);
        data.push_back(frame_index);
        for (const float v : reproject) {
            data.push_back(std::bit_cast<u32>(v));
"""),
        (r"""            data.push_back(std::bit_cast<u32>(v));
        }
        if (data.size() > DataWords) {
            data.clear();
            return;
        }
        pending_view = camera.view;
        pending_proj = proj;
        pending_valid = camera.valid && ok;
        history_written = lamp_reuse;
        clear_history = lamp_reuse;
    }
    if (use_rays) {
""",
         r"""            data.push_back(std::bit_cast<u32>(v));
        }
        // bbport (r42_lamp-soft): words 30 to 33 (the first: 0 unless the pass averages)
        auto tail = LampHistoryTail(pass_tune);
        tail[0] = std::bit_cast<u32>(keep);
        data.insert(data.end(), tail.begin(), tail.end());
        pending_view = camera.view;
        pending_proj = proj;
        pending_valid = camera.valid && ok;
        history_written = kept;
        history_blend = blend;
        clear_history = kept;
    }
    if (use_rays) {
"""),
        (r"""    }

    // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1 and experiment 72057594037927936 clear: the
    // lamps-apart pass in two halves (point_shadow_ray_half_comp), with the block answers in an
    // image of half the size.
    // bbport (r37_menu-options): BB_LAMP_SHADOW_HALF when set, else graphics_lamp_shadow_half.
    const bool half_on = half_env >= 0 ? half_env == 1
                                       : BbSettings::Get().graphics_lamp_shadow_half.load(
                                             std::memory_order_relaxed);
    bool use_half = use_rays && batch_apart && half_on && HalfReady();
    if (use_half && BbToggle::Experiment(HalfOffBit)) {
        use_half = false;
        ++half_line_full;
    }
    if (use_half) {
        const u32 half_width = (width + 1) / 2, half_height = (height + 1) / 2;
        if (half_answers.width != half_width || half_answers.height != half_height) {
            if (!EffectPass::HasRoom(instance, 8ull * half_width * half_height)) {
                use_half = false;
            } else if (EnsureImage(half_answers, half_width, half_height, HistoryFormat,
                                   "Ray traced lamp half answers")) {
                half_laid_out = false;
            }
        }
    }
    const bool half_lay_out = use_half && !std::exchange(half_laid_out, true);
    const bool half_count = use_half && (half_passes++ & 7u) == 0;
""",
         r"""    }

    // bbport (r32_lamp-half): the half resolution (use_half: decided above, r42_lamp-soft)
    const bool half_lay_out = use_half && !std::exchange(half_laid_out, true);
    const bool half_count = use_half && (half_passes++ & 7u) == 0;
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
""",
         r"""#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r42_lamp-soft)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
"""),
        (r"""constexpr u32 LampStaleSkips = 2;
constexpr u32 LampFreshBuilds = 3;

// bbport: experiment mask 256 (a diagnostic): copies of a mesh drawn more than once in a pass
""",
         r"""constexpr u32 LampStaleSkips = 2;
constexpr u32 LampFreshBuilds = 3;
// bbport (r42_lamp-soft): BB_LAMP_SHADOW_STALE, read once. 1: such copies are left out of lamp
// rays, as r41 did. 0, the default: they stay in, as before r41. Nothing here shows that a
// starved copy is never the only caster a lamp ray would find where it stands (the live copy
// "beside it" is another draw of the same mesh, not known to be the same object), and in the
// game the band the rule was aimed at stayed with 18 copies left out. The counting goes on
// either way, and the 600-frame line names the copies.
bool LampStaleOut() {
    static const bool out =
        ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); }).stale;
    return out;
}

// bbport: experiment mask 256 (a diagnostic): copies of a mesh drawn more than once in a pass
"""),
        (r"""    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
    const bool lamp_repair = !BbToggle::Experiment(LampRepairOffBit); // bbport (r41_lamp-shadows)
    for (u32 i = 0; i < count; ++i) {
        // bbport (r14_cascade_rt): a held entry, or a held one drawn only by the camera pass while
""",
         r"""    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
    // bbport (r41_lamp-shadows, r42_lamp-soft): with BB_LAMP_SHADOW_STALE=1 only
    const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
    for (u32 i = 0; i < count; ++i) {
        // bbport (r14_cascade_rt): a held entry, or a held one drawn only by the camera pass while
"""),
        (r"""        // (Entry::lamp_out), and the oldest moving copy's BLAS in frames.
        u64 shared_no_lamp = 0, shared_oldest = 0;
        const bool lamp_repair = !BbToggle::Experiment(LampRepairOffBit);
        std::unordered_set<u64> shared_meshes;
        for (const auto& item : entries) {
""",
         r"""        // (Entry::lamp_out), and the oldest moving copy's BLAS in frames.
        u64 shared_no_lamp = 0, shared_oldest = 0;
        const bool lamp_repair = LampStaleOut() && !BbToggle::Experiment(LampRepairOffBit);
        // bbport (r42_lamp-soft): the moving copies starved of rebuilds (Entry::lamp_out is kept
        // whatever BB_LAMP_SHADOW_STALE says), and the four of them with the most triangles.
        u64 shared_starved = 0;
        std::array<const Entry*, 4> starved{};
        std::unordered_set<u64> shared_meshes;
        for (const auto& item : entries) {
"""),
        (r"""                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
                shared_no_lamp += lamp_repair && e->lamp_out ? 1 : 0;
            }
        }
""",
         r"""                shared_oldest = std::max(shared_oldest, frame - e->built_frame);
                shared_no_lamp += lamp_repair && e->lamp_out ? 1 : 0;
                if (e->lamp_out) { // bbport (r42_lamp-soft)
                    ++shared_starved;
                    const Entry* held = e;
                    for (const Entry*& slot : starved) {
                        if (!slot || held->triangles > slot->triangles) {
                            std::swap(slot, held);
                        }
                        if (!held) {
                            break;
                        }
                    }
                }
            }
        }
"""),
        (r"""                    "frame: %llu of %zu meshes, %llu triangles, %llu moving, %llu with a palette, "
                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u; %llu left out of lamp rays (oldest %llu frames)\n",
                    double(stats.refit_triangles) / f, static_cast<unsigned long long>(shared),
                    shared_meshes.size(), static_cast<unsigned long long>(shared_triangles),
""",
         r"""                    "frame: %llu of %zu meshes, %llu triangles, %llu moving, %llu with a palette, "
                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u; %llu left out of lamp rays (oldest %llu frames); %llu moving copies "
                    "starved of rebuilds, %s (BB_LAMP_SHADOW_STALE=%d)%s",
                    double(stats.refit_triangles) / f, static_cast<unsigned long long>(shared),
                    shared_meshes.size(), static_cast<unsigned long long>(shared_triangles),
"""),
        (r"""                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget(),
                    static_cast<unsigned long long>(shared_no_lamp),
                    static_cast<unsigned long long>(shared_oldest));
        stats = {};
    }
""",
         r"""                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget(),
                    static_cast<unsigned long long>(shared_no_lamp),
                    static_cast<unsigned long long>(shared_oldest),
                    static_cast<unsigned long long>(shared_starved),
                    lamp_repair ? "left out of lamp rays" : "kept in lamp rays",
                    LampStaleOut() ? 1 : 0, starved[0] ? ", the largest:" : "");
        // bbport (r42_lamp-soft): which they are
        for (const Entry* e : starved) {
            if (!e) {
                break;
            }
            std::printf(" mesh %016llx, %u triangles, %s, built %llu frames ago;",
                        static_cast<unsigned long long>(e->mesh), e->triangles,
                        (e->mask & CameraMask) != 0 ? "in the camera pass" : "not in the camera pass",
                        static_cast<unsigned long long>(frame - e->built_frame));
        }
        std::printf("\n");
        stats = {};
    }
"""),
    ],
    TESTS + "test_lamp_shadow_tune.cpp": [
        (r"""// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
#include <array>
#include <bit>
""",
         r"""// bbport (r41_lamp-shadows): the tuning of the ray traced lamp shadow pass (lamp_shadow_tune.h):
// defaults, clamping, bad text, the words the shader reads and the weight it works out.
// bbport (r42_lamp-soft): the area lamp's knobs, the frames of history, and the lamps of a pass
// told apart and followed from one frame to the next (LampTrack).
#include <array>
#include <bit>
"""),
        (r"""    return std::abs(a - b) <= 1e-6f;
}
} // namespace

""",
         r"""    return std::abs(a - b) <= 1e-6f;
}

// A lamp record as the pass has it: its place in view space, 1 / reach squared, its colour.
std::array<std::uint32_t, 16> Record(float x, float y, float z, float reach, float grey = 1.0f) {
    std::array<std::uint32_t, 16> r{};
    const std::array<float, 7> f{x, y, z, 1.0f / (reach * reach), grey, grey, grey};
    for (std::size_t k = 0; k < f.size(); ++k) {
        r[k] = std::bit_cast<std::uint32_t>(f[k]);
    }
    return r;
}
} // namespace

"""),
        (r"""    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.radius_m == 0.05f && t.rim == 3u);
        assert(t.share == 0.25f && t.clearance_m == 0.35f && t.bias_m == 0.03f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        assert(t.facing_floor == 0.05f && t.near_part == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);
""",
         r"""    {
        const LampShadowTune t = Read(std::array<Pair, 0>{});
        assert(t.weights && t.wrap == 0.15f && t.facing_floor == 0.05f);
        assert(t.radius_m == 0.1f && t.history == 0.9f && t.reject == 0.5f && t.trail_m == 0.08f);
        assert(t.follow && !t.stale && t.carry_m == 2.5f && t.around == 1.6f);
        assert(t.self_m == 0.06f && t.view == 0u && t.view_gain == 0.5f);
        // The values of before where the shader had constants.
        assert(t.clearance_m == 0.35f && t.bias_m == 0.03f);
"""),
        (r"""    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_NEAR", "0.75"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.4"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "2"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.radius_m == 0.2f && t.rim == 4u);
        assert(t.share == 0.4f && t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 2u && t.view_gain == 4.0f);
        assert(t.facing_floor == 0.25f && t.near_part == 0.75f);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_NEAR", "0"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_RIM", "-2"},
            {"BB_LAMP_SHADOW_SHARE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
""",
         r"""    // Every knob read.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "1.5"},
            {"BB_LAMP_SHADOW_CLAMP", "2.5"},
            {"BB_LAMP_SHADOW_FLOOR", "0.25"},
            {"BB_LAMP_SHADOW_WEIGHTS", "0"},
            {"BB_LAMP_SHADOW_WRAP", "0.5"},
            {"BB_LAMP_SHADOW_SOFT", "0.2"},
            {"BB_LAMP_SHADOW_HISTORY", "0.8"},
            {"BB_LAMP_SHADOW_REJECT", "0.7"},
            {"BB_LAMP_SHADOW_TRAIL", "0.5"},
            {"BB_LAMP_SHADOW_FOLLOW", "0"},
            {"BB_LAMP_SHADOW_STALE", "1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0.2"},
            {"BB_LAMP_SHADOW_BIAS", "0.05"},
            {"BB_LAMP_SHADOW_SELF", "0.12"},
            {"BB_LAMP_SHADOW_VIEW", "4"},
            {"BB_LAMP_SHADOW_VIEW_GAIN", "4"},
        }});
        assert(!t.weights && t.wrap == 0.5f && t.facing_floor == 0.25f);
        assert(t.radius_m == 0.2f && t.history == 0.8f && t.reject == 0.7f && t.trail_m == 0.5f);
        assert(!t.follow && t.stale && t.carry_m == 1.5f && t.around == 2.5f);
        assert(t.clearance_m == 0.2f && t.bias_m == 0.05f);
        assert(t.self_m == 0.12f && t.view == 4u && t.view_gain == 4.0f);
    }
    // r41's rim knobs are gone: set, they change nothing.
    {
        const LampShadowTune t = Read(std::array<Pair, 3>{{
            {"BB_LAMP_SHADOW_RIM", "4"},
            {"BB_LAMP_SHADOW_SHARE", "0.9"},
            {"BB_LAMP_SHADOW_NEAR", "1"},
        }});
        const LampShadowTune d;
        assert(LampTuneWords(t, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(t.history == d.history && t.trail_m == d.trail_m && t.follow == d.follow && t.stale == d.stale);
    }
    // Out of range: clamped to the nearest end.
    {
        const LampShadowTune low = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "-1"},
            {"BB_LAMP_SHADOW_CLAMP", "-1"},
            {"BB_LAMP_SHADOW_FLOOR", "-1"},
            {"BB_LAMP_SHADOW_WEIGHTS", "-3"},
            {"BB_LAMP_SHADOW_WRAP", "-1"},
            {"BB_LAMP_SHADOW_SOFT", "-0.5"},
            {"BB_LAMP_SHADOW_HISTORY", "-1"},
            {"BB_LAMP_SHADOW_REJECT", "-1"},
            {"BB_LAMP_SHADOW_TRAIL", "-1"},
            {"BB_LAMP_SHADOW_FOLLOW", "-3"},
            {"BB_LAMP_SHADOW_STALE", "-1"},
            {"BB_LAMP_SHADOW_CLEARANCE", "0"},
            {"BB_LAMP_SHADOW_BIAS", "0"},
"""),
        (r"""            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.radius_m == 0.0f && low.rim == 0u);
        assert(low.share == 0.0f && low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        assert(low.facing_floor == 0.0f && low.near_part == 0.05f);
        const LampShadowTune high = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_NEAR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_RIM", "99"},
            {"BB_LAMP_SHADOW_SHARE", "2"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
""",
         r"""            {"BB_LAMP_SHADOW_VIEW_GAIN", "0"},
        }});
        assert(!low.weights && low.wrap == 0.0f && low.facing_floor == 0.0f);
        assert(low.radius_m == 0.0f && low.history == 0.0f && low.reject == 0.0f && low.trail_m == 0.0f);
        assert(!low.follow && !low.stale && low.carry_m == 0.0f && low.around == 0.0f);
        assert(low.clearance_m == 0.05f && low.bias_m == 0.005f);
        assert(low.self_m == 0.0f && low.view == 0u && low.view_gain == 0.01f);
        const LampShadowTune high = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "9"},
            {"BB_LAMP_SHADOW_CLAMP", "9"},
            {"BB_LAMP_SHADOW_FLOOR", "4"},
            {"BB_LAMP_SHADOW_WEIGHTS", "7"},
            {"BB_LAMP_SHADOW_WRAP", "3"},
            {"BB_LAMP_SHADOW_SOFT", "5"},
            {"BB_LAMP_SHADOW_HISTORY", "2"},
            {"BB_LAMP_SHADOW_REJECT", "3"},
            {"BB_LAMP_SHADOW_TRAIL", "9"},
            {"BB_LAMP_SHADOW_FOLLOW", "7"},
            {"BB_LAMP_SHADOW_STALE", "9"},
            {"BB_LAMP_SHADOW_CLEARANCE", "50"},
            {"BB_LAMP_SHADOW_BIAS", "1"},
"""),
        (r"""            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.radius_m == 0.3f && high.rim == 4u);
        assert(high.share == 1.0f && high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 3u && high.view_gain == 16.0f);
        assert(high.facing_floor == 1.0f && high.near_part == 1.0f);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
""",
         r"""            {"BB_LAMP_SHADOW_VIEW_GAIN", "1000"},
        }});
        assert(high.weights && high.wrap == 1.0f && high.facing_floor == 1.0f);
        assert(high.radius_m == 0.5f && high.history == 0.98f && high.reject == 1.0f && high.trail_m == 2.0f);
        assert(high.follow && high.stale && high.carry_m == 5.0f && high.around == 4.0f);
        assert(high.clearance_m == 2.0f && high.bias_m == 0.2f);
        assert(high.self_m == 0.3f && high.view == 6u && high.view_gain == 16.0f);
        // A reject that is on is never below the least that leaves a history standing, and
        // the same for the bound by the answers around a pixel.
        const LampShadowTune weak = Read(std::array<Pair, 2>{{{"BB_LAMP_SHADOW_REJECT", "0.1"},
                                                              {"BB_LAMP_SHADOW_CLAMP", "0.1"}}});
        assert(weak.reject == LampRejectLeast && LampRejectLeast * 0.9f > 0.4f);
        assert(weak.around == LampAroundLeast);
    }
    // Not a number (empty, words, a number with a tail, not finite): the default stays. Blanks
"""),
        (r"""    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 12>{{
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_NEAR", "0.5x"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_RIM", "two"},
            {"BB_LAMP_SHADOW_SHARE", "nan"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
""",
         r"""    // after a number are allowed.
    {
        const LampShadowTune t = Read(std::array<Pair, 16>{{
            {"BB_LAMP_SHADOW_CARRY", "near"},
            {"BB_LAMP_SHADOW_CLAMP", "1.6x"},
            {"BB_LAMP_SHADOW_FLOOR", "low"},
            {"BB_LAMP_SHADOW_WEIGHTS", "off"},
            {"BB_LAMP_SHADOW_WRAP", ""},
            {"BB_LAMP_SHADOW_SOFT", "0.2m"},
            {"BB_LAMP_SHADOW_HISTORY", "0.5x"},
            {"BB_LAMP_SHADOW_REJECT", "nan"},
            {"BB_LAMP_SHADOW_TRAIL", "far"},
            {"BB_LAMP_SHADOW_FOLLOW", "no"},
            {"BB_LAMP_SHADOW_STALE", "yes"},
            {"BB_LAMP_SHADOW_CLEARANCE", "inf"},
            {"BB_LAMP_SHADOW_BIAS", "0,05"},
"""),
        (r"""        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.rim == d.rim && t.share == d.share && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.near_part == d.near_part);
        assert(t.self_m == 0.12f);
    }
    // The words: flags, nine floats, two axes.
""",
         r"""        const LampShadowTune d;
        assert(t.weights == d.weights && t.wrap == d.wrap && t.radius_m == d.radius_m);
        assert(t.history == d.history && t.reject == d.reject && t.trail_m == d.trail_m);
        assert(t.follow == d.follow && t.stale == d.stale && t.clearance_m == d.clearance_m);
        assert(t.bias_m == d.bias_m && t.view == d.view && t.view_gain == d.view_gain);
        assert(t.facing_floor == d.facing_floor && t.carry_m == d.carry_m && t.around == d.around);
        assert(t.self_m == 0.12f);
    }
    // The frames of history: a frame's share is 1 / (frames + 1).
    {
        LampShadowTune t;
        assert(std::abs(LampHistoryFrames(t) - 9.0f) < 1e-4f);
        t.history = 0.5f;
        assert(Near(LampHistoryFrames(t), 1.0f));
        t.history = 0.98f;
        assert(std::abs(LampHistoryFrames(t) - 49.0f) < 1e-3f);
        t.history = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // this frame's ray alone
        t = {};
        t.radius_m = 0.0f;
        assert(LampHistoryFrames(t) == 0.0f); // a point lamp keeps no history
        // The last four words of the history block.
        static_assert(LampHistoryTailWords == 4);
        t = {};
        t.trail_m = 0.25f;
        t.carry_m = 1.5f;
        t.around = 2.0f;
        const auto tail = LampHistoryTail(t);
        assert(std::abs(F(tail[0]) - 9.0f) < 1e-4f && F(tail[1]) == 0.25f && F(tail[2]) == 1.5f && F(tail[3]) == 2.0f);
    }
    // A cut: the way back to the camera of the frame before is more than 2 m or about 20 degrees.
    {
        std::array<float, 12> back{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        assert(!LampCameraCut(back.data()));
        back[3] = 0.5f;
        back[11] = -1.5f; // a fast camera: 1.6 m in a frame
        assert(!LampCameraCut(back.data()));
        back[7] = 1.3f; // 2.05 m
        assert(LampCameraCut(back.data()));
        const auto turned = [](float degrees) {
            const float a = degrees * 0.01745329f, c = std::cos(a), s = std::sin(a);
            return std::array<float, 12>{c, 0, s, 0.1f, 0, 1, 0, 0, -s, 0, c, 0};
        };
        assert(!LampCameraCut(turned(5.0f).data()) && !LampCameraCut(turned(-18.0f).data()));
        assert(LampCameraCut(turned(25.0f).data()) && LampCameraCut(turned(180.0f).data()));
        back = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        back[5] = std::nanf("");
        assert(LampCameraCut(back.data()));
    }
    // The words: flags, nine floats, two axes.
"""),
        (r"""        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        assert(words[0] == (1u | 3u << 4)); // new weights, 3 rim rays, view 0
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.05f && F(words[3]) == 0.25f);
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
        assert(Near(F(words[6]), 0.0025f));
        assert(F(words[8]) == 0.05f && F(words[9]) == 0.5f);
""",
         r"""        const auto words = LampTuneWords(d, false, 0.05f);
        assert(words.size() == LampTuneWordCount);
        assert(words[0] == 1u); // new weights, view 0
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
        assert(F(words[4]) == 0.06f && F(words[5]) == 0.15f && F(words[7]) == 0.5f);
        // The frame counter goes into word 3 as it is, and changes nothing else.
        const auto later = LampTuneWords(d, false, 0.05f, nullptr, 0xC0000077u);
        assert(later[3] == 0xC0000077u);
        for (std::size_t k = 0; k < LampTuneWordCount; ++k) {
            assert(k == 3 || later[k] == words[k]);
        }
        assert(Near(F(words[6]), 0.0025f));
        assert(F(words[8]) == 0.05f && F(words[9]) == 0.5f);
"""),
        (r"""        LampShadowTune t;
        t.weights = false;
        t.rim = 4;
        t.view = 3;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 4 | 3u << 8));
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
""",
         r"""        LampShadowTune t;
        t.weights = false;
        t.view = 4;
        t.reject = 0.75f;
        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8));
        assert(F(other[9]) == 0.75f);
        assert(Near(F(other[6]), 0.01f));
        // A core that is not a positive number counts as 0, as in LocalFalloff::Patch.
"""),
        (r"""        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The rim count and the view cannot leave their fields.
        t.rim = 100;
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (7u << 4 | 3u << 8));
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
""",
         r"""        assert(F(LampTuneWords(d, true, -1.0f)[6]) == 0.0f);
        assert(F(LampTuneWords(d, true, std::nanf(""))[6]) == 0.0f);
        // The view cannot leave its field.
        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == 6u << 8);
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
"""),
        (r"""               LampWeight(d, false, 0.05f, 0.64f, 1.0f, true, 1.0f));
    }
    std::puts("lamp shadow tune: ok");
    return 0;
""",
         r"""               LampWeight(d, false, 0.05f, 0.64f, 1.0f, true, 1.0f));
    }
    // bbport (r42_lamp-soft): the lamps of a pass, told apart and followed.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        // The camera of the second frame stands 2 m along x: world = view + (2, 0, 0).
        constexpr std::array<float, 12> Moved{1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0};
        LampTrack track;
        // Frame 1: lamp A (listed for three tiles), lamp B, and a record with no reach.
        const auto a1 = Record(1.0f, 2.0f, 3.0f, 6.0f, 0.5f), b1 = Record(5.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        track.Begin(Same.data());
        assert(track.Add(a1.data()) == 0 && track.Add(b1.data()) == 1 && track.Add(a1.data()) == 0);
        assert(track.Add(a1.data()) == 0 && track.Count() == 2);
        std::array<std::uint32_t, 16> none{};
        assert(track.Add(none.data()) == -1 && track.Count() == 2);
        assert(track.Lamp(0).records == 3 && track.Lamp(1).records == 1);
        assert(Near(track.Lamp(0).radius, 6.0f) && Near(track.Lamp(0).luma, 0.5f));
        assert(Near(track.Lamp(1).away, std::sqrt(26.0f)));
        track.Follow(); // no frame before: nothing is followed, nothing shifts
        assert(!track.Lamp(0).followed && track.Shift(0, Same.data()) == (std::array<float, 3>{}));
        // The brightest first.
        assert(track.Strongest() == (std::array<int, 4>{1, 0, -1, -1}));
        track.End(true);
        // Frame 2: A went (0.1, 0, 0.05) in the world, B stands; the camera moved, so both
        // records hold other numbers. C is new; D stands where B does with twice its reach.
        const auto a2 = Record(1.1f - 2.0f, 2.0f, 3.05f, 6.0f, 0.5f), b2 = Record(3.0f, 1.0f, 0.0f, 4.0f, 2.0f);
        const auto c2 = Record(9.0f, 0.0f, 0.0f, 4.0f), d2 = Record(3.0f, 1.0f, 0.01f, 8.0f);
        track.Begin(Moved.data());
        assert(track.Add(a2.data()) == 0 && track.Add(b2.data()) == 1 && track.Add(c2.data()) == 2);
        assert(track.Add(d2.data()) == 3);
        track.Follow();
        assert(track.Lamp(0).followed && track.Lamp(1).followed);
        assert(!track.Lamp(2).followed && !track.Lamp(3).followed);
        assert(Near(track.Lamp(0).world[0], 1.1f) && Near(track.Lamp(0).moved[0], 0.1f));
        assert(Near(track.Lamp(0).moved[1], 0.0f) && Near(track.Lamp(0).moved[2], 0.05f));
        assert(track.Lamp(1).moved == (std::array<float, 3>{})); // it stands
        // The shift is the lamp's motion turned into the view of the frame before (here a
        // quarter turn about y), whatever that camera's place.
        constexpr std::array<float, 12> Turned{0, 0, -1, 7, 0, 1, 0, 8, 1, 0, 0, 9};
        const auto shift = track.Shift(0, Turned.data());
        assert(Near(shift[0], -0.05f) && Near(shift[1], 0.0f) && Near(shift[2], 0.1f));
        assert(track.Shift(1, Turned.data()) == (std::array<float, 3>{}));
        // The step is the length of the motion, with or without a view to turn it into. A
        // lamp that was looked for in the frame before and not found has no history: Lost.
        assert(Near(track.Step(0), std::sqrt(0.1f * 0.1f + 0.05f * 0.05f)));
        assert(track.Step(1) == 0.0f && track.Step(2) == LampTrack::Lost && track.Step(-1) == 0.0f);
        assert(track.Step(3) == LampTrack::Lost);
        // What a followed lamp did since the steps were last cleared.
        assert(track.Lamp(0).steps == 1 && Near(track.Lamp(0).step_most, track.Step(0)));
        assert(track.Lamp(1).steps == 1 && track.Lamp(1).step_sum == 0.0f && track.Lamp(2).steps == 0);
        assert(track.Shift(-1, Turned.data()) == (std::array<float, 3>{}));
        assert(track.Shift(0, nullptr) == (std::array<float, 3>{}));
        track.End(true);
        // Frame 3: two lamps near where A was: the nearer one is A, the other is new. A lamp
        // further than Reach from every lamp of the frame before is new.
        const auto a3 = Record(1.2f - 2.0f, 2.0f, 3.05f, 6.0f), e3 = Record(1.4f - 2.0f, 2.0f, 3.05f, 6.0f);
        const auto b3 = Record(3.0f + LampTrack::Reach + 0.1f, 1.0f, 0.0f, 4.0f);
        track.Begin(Moved.data());
        assert(track.Add(e3.data()) == 0 && track.Add(a3.data()) == 1 && track.Add(b3.data()) == 2);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Lamp(1).followed && !track.Lamp(2).followed);
        assert(Near(track.Lamp(1).moved[0], 0.1f));
        assert(track.Lamp(1).steps == 2 && Near(track.Lamp(1).step_sum, track.Lamp(1).step_most + 0.1f));
        track.ClearSteps();
        assert(track.Lamp(1).steps == 0 && track.Lamp(1).step_sum == 0.0f && track.Lamp(1).step_most == 0.0f);
        track.End(false); // the pass kept no history: the next frame follows nothing
        track.Begin(Moved.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f); // not looked for: not Lost
        track.End(true);
        // No camera: the lamps are listed in view space and not followed, on this frame or the next.
        track.Begin(nullptr);
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed && Near(track.Lamp(0).world[0], 1.2f - 2.0f));
        track.End(true);
        track.Begin(Same.data());
        assert(track.Add(a3.data()) == 0);
        track.Follow();
        assert(!track.Lamp(0).followed);
        track.End(true);
        // More lamps than it tells apart: the first Most keep their numbers, the rest have none.
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most + 6; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f, k == 5 ? 9.0f : 1.0f);
            assert(track.Add(r.data()) == (k < LampTrack::Most ? int(k) : -1));
        }
        const auto again = Record(7.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(again.data()) == 7 && track.Count() == LampTrack::Most);
        // Strongest: none of them is within Near of the camera.
        assert(track.Strongest() == (std::array<int, 4>{-1, -1, -1, -1}));
        track.End(false);
        // Strongest: by luminance, the nearer first among equals, four at most.
        track.Begin(Same.data());
        const std::array<std::array<std::uint32_t, 16>, 6> some{
            Record(0, 0, 5, 3, 1.0f), Record(0, 0, 2, 3, 1.0f), Record(0, 0, 9, 3, 4.0f),
            Record(0, 0, 14, 3, 0.2f), Record(0, 0, 16, 3, 50.0f), Record(1, 0, 3, 3, 0.5f)};
        for (const auto& r : some) {
            track.Add(r.data());
        }
        assert(track.Strongest() == (std::array<int, 4>{2, 1, 0, 5}));
        track.End(false);
        // Two lights at one place with different reach or colour are two lamps (a torch made
        // of two); the same seven words are one.
        track.Begin(Same.data());
        const auto wide = Record(1, 2, 3, 6.0f), small = Record(1, 2, 3, 1.5f), red = Record(1, 2, 3, 6.0f, 0.3f);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Add(red.data()) == 2);
        assert(track.Add(wide.data()) == 0 && track.Add(small.data()) == 1 && track.Count() == 3);
        assert(Near(LampTrack::Away(wide.data()), std::sqrt(14.0f)));
        track.End(false);
    }
    // Two lamps a few centimetres apart that move together (a hand torch made of two lights):
    // each is found again as itself, from the first moving frame on, and both have the step.
    // Before, each took the nearest place of the frame before: one of them the other's, with
    // a wrong step or one against the motion, and the other none.
    {
        constexpr std::array<float, 12> Same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
        const std::array<std::array<float, 2>, 5> cases{{{0.05f, 0.067f}, {0.05f, 0.03f}, {0.1f, 0.067f},
                                                         {0.02f, 0.01f}, {0.3f, 0.067f}}};
        for (const auto& [gap, step] : cases) {
            for (const bool second_first : {false, true}) {
                LampTrack track;
                for (int frame = 0; frame < 4; ++frame) {
                    const float x = step * float(frame);
                    const auto a = Record(x, 1.0f, 2.0f, 5.0f), b = Record(x + gap, 1.0f, 2.0f, 5.0f);
                    track.Begin(Same.data());
                    const int ia = second_first ? (track.Add(b.data()), track.Add(a.data())) : track.Add(a.data());
                    const int ib = track.Add(b.data());
                    track.Follow();
                    if (frame > 0) {
                        assert(track.Lamp(std::uint32_t(ia)).followed && track.Lamp(std::uint32_t(ib)).followed);
                        assert(std::abs(track.Step(ia) - step) < 1e-4f && std::abs(track.Step(ib) - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ia)).moved[0] - step) < 1e-4f);
                        assert(std::abs(track.Lamp(std::uint32_t(ib)).moved[0] - step) < 1e-4f);
                    }
                    track.End(true);
                }
            }
        }
        // A flame whose reach flickers (5 m, 6.6 m) while it is carried is one lamp all the same.
        LampTrack track;
        for (int frame = 0; frame < 4; ++frame) {
            const auto a = Record(0.05f * float(frame), 1.0f, 2.0f, frame & 1 ? 6.6f : 5.0f);
            track.Begin(Same.data());
            track.Add(a.data());
            track.Follow();
            assert(frame == 0 || (track.Lamp(0).followed && std::abs(track.Step(0) - 0.05f) < 1e-4f));
            track.End(true);
        }
        // A lamp that jumps further than Reach is new, and what the history holds under it is
        // not its own: Lost. Unless the frame before had as many lamps as are told apart (it
        // may have been one more of them): then nothing is known, and the step is 0.
        const auto jumped = Record(0.15f + LampTrack::Reach + 0.2f, 1.0f, 2.0f, 5.0f);
        track.Begin(Same.data());
        track.Add(jumped.data());
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == LampTrack::Lost);
        track.End(true);
        track.Begin(Same.data());
        for (std::uint32_t k = 0; k < LampTrack::Most; ++k) {
            const auto r = Record(float(k), 0.0f, 20.0f, 3.0f);
            track.Add(r.data());
        }
        track.End(true);
        track.Begin(Same.data());
        const auto stranger = Record(-5.0f, 0.0f, 20.0f, 3.0f), known = Record(3.0f, 0.0f, 20.0f, 3.0f);
        assert(track.Add(stranger.data()) == 0 && track.Add(known.data()) == 1);
        track.Follow();
        assert(!track.Lamp(0).followed && track.Step(0) == 0.0f);
        assert(track.Lamp(1).followed && track.Step(1) == 0.0f);
        track.End(false);
    }
    std::puts("lamp shadow tune: ok");
    return 0;
"""),
    ],
    TESTS + "test_rt_shadows.cpp": [
        (r"""#include "video_core/host_shaders/rt_lab_comp.h"
#include "video_core/host_shaders/point_shadow_ray_comp.h"
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
""",
         r"""#include "video_core/host_shaders/rt_lab_comp.h"
#include "video_core/host_shaders/point_shadow_ray_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/host_shaders/ssgi_gather_ray_comp.h"
"""),
        (r"""        }
    return mesh;
}

""",
         r"""        }
    return mesh;
}

// bbport (r42_lamp-soft): a box from a to b, `thick` across (a stick, an arm).
Mesh Beam(Vec3 a, Vec3 b, float thick) {
    Mesh mesh;
    const Vec3 dir = Norm(b + a * -1.0f);
    const Vec3 side = Norm(Cross(dir, std::abs(dir.y) < 0.9f ? Vec3{0, 1, 0} : Vec3{1, 0, 0})) * (thick * 0.5f);
    const Vec3 up = Norm(Cross(dir, side)) * (thick * 0.5f);
    for (int k = 0; k < 8; ++k) {
        mesh.vertices.push_back((k & 4 ? b : a) + side * (k & 1 ? 1.0f : -1.0f) + up * (k & 2 ? 1.0f : -1.0f));
    }
    mesh.indices = {0, 1, 3, 0, 3, 2, 4, 7, 5, 4, 6, 7, 0, 4, 5, 0, 5, 1,
                    2, 3, 7, 2, 7, 6, 0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3};
    return mesh;
}

// bbport (r42_lamp-soft): the torch lab's scene (rt-shadow-test --lamps): a character with a
// hand torch seen from above, as in the report the area lamp answers. The meshes, in this
// order: the ground; the character (a capsule 1.8 m tall, 0.6 m wide); its arm, 8 cm thick,
// from the shoulder to the raised hand; the torch's stick, 3.5 cm thick and 0.9 m long, from
// the hand up towards the flame; a blade at its hip, 5 cm thick, down to knee height; a second
// figure 1.5 m away; a post 8 cm thick; a low wall. The lamp sits at TorchFlame, 0.2 m off the
// stick's line (a stick that points at its lamp casts a dot, not a band) and above the head;
// the pass is blind within 0.35 m of a lamp. So the stick and the arm are thin casters near the
// lamp, the blade is a thin caster near the ground, and the two figures are bodies near and far.
constexpr unsigned TorchCharacter = 1, TorchArm = 2, TorchStick = 3, TorchBlade = 4, TorchOther = 5;
constexpr Vec3 TorchFlame{-0.72f, 2.1f, 0.55f};
std::vector<Mesh> MakeTorchScene() {
    std::vector<Mesh> scene;
    Mesh ground = Box({60, 1, 60}, 1200);
    ground.position = {0, -1, 0};
    scene.push_back(std::move(ground));
    Mesh body = Capsule(1.8f, 0.3f, 30000);
    body.skinned = true;
    scene.push_back(std::move(body));
    scene.push_back(Beam({-0.2f, 1.45f, -0.05f}, {-0.42f, 1.45f, -0.25f}, 0.08f));
    scene.push_back(Beam({-0.42f, 1.4f, -0.29f}, {-0.6f, 1.98f, 0.38f}, 0.035f));
    scene.push_back(Beam({0.35f, 0.9f, -0.1f}, {0.7f, 0.35f, -0.75f}, 0.05f));
    Mesh other = Capsule(1.8f, 0.3f, 30000);
    other.position = {1.5f, 0, 0.1f};
    other.skinned = true;
    scene.push_back(std::move(other));
    Mesh post = Box({0.08f, 2.5f, 0.08f}, 600);
    post.position = {-1.9f, 0, -0.5f};
    scene.push_back(std::move(post));
    Mesh wall = Box({5.0f, 1.2f, 0.3f}, 1200);
    wall.position = {0.3f, 0, 1.9f};
    scene.push_back(std::move(wall));
    return scene;
}

"""),
        (r"""        {{{5, 3, 30}, {-0.5f, -0.5f, 1}}},
    }};
    if (argc > 1 && std::strcmp(argv[1], "--speed") == 0) {
        const unsigned total = argc > 2 ? unsigned(std::strtoul(argv[2], nullptr, 10)) : 1500000u;
        Scene scene{vk, MakeScene(total, total / 1875)};
        scene.Create(Trace | Update);
        scene.Allocate();
""",
         r"""        {{{5, 3, 30}, {-0.5f, -0.5f, 1}}},
    }};
    // bbport (r42_lamp-soft): --lamps [directory]: the torch lab (below), with the lamp pass's
    // images and pipeline as --speed makes them.
    const bool torch_lab = argc > 1 && std::strcmp(argv[1], "--lamps") == 0;
    if (argc > 1 && (std::strcmp(argv[1], "--speed") == 0 || torch_lab)) {
        const unsigned total = argc > 2 && !torch_lab ? unsigned(std::strtoul(argv[2], nullptr, 10)) : 1500000u;
        Scene scene{vk, torch_lab ? MakeTorchScene() : MakeScene(total, total / 1875)};
        scene.Create(Trace | Update);
        scene.Allocate();
"""),
        (r"""            return e == 0 ? float(m) / 64.0f * std::ldexp(1.0f, -14) : std::ldexp(1.0f + float(m) / 64.0f, int(e) - 15);
        };
        std::vector<std::array<double, 3>> lamp_ms(variants.size()), sun_ms(variants.size());
        std::array<double, 3> per_tile_ms{}, pick_ms{}, reuse_ms{}, reuse_error{};
""",
         r"""            return e == 0 ? float(m) / 64.0f * std::ldexp(1.0f, -14) : std::ldexp(1.0f + float(m) / 64.0f, int(e) - 15);
        };
        if (torch_lab) {
            // bbport (r42_lamp-soft): the torch lab. One torch lamp at the flame of a hand torch,
            // the camera above and tilted down. It runs the lamp pass over many frames with its
            // history (the words PointShadow::Flush hands it: flags, frame, the way back to the
            // camera of the frame before, that camera's projection, the most frames a texel may
            // hold), moves the scene and the camera between frames, and compares what the pass
            // shows with the mean of many single frames (the area lamp's true picture). With a
            // directory it writes the pictures there (PGM, the shadow ratio as grey).
            const char* out_dir = argc > 2 ? argv[2] : nullptr;
            Pipeline half = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_BUFFER},
                                            64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
                                            VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image half_answers = vk.MakeImage((W + 1) / 2, (H + 1) / 2, VK_FORMAT_R16G16B16A16_SFLOAT);
            Buffer half_counts = vk.MakeBuffer(64, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
            std::memset(half_counts.data, 0, 64);
            vk.Begin();
            vk.ToGeneral(half_answers.image);
            vk.Stamp(0); vk.Stamp(1);
            vk.End();
            Tlas tlas = make_tlas(n, Fast);
            std::vector<Vec3> home;
            for (const Mesh& mesh : scene.meshes) home.push_back(mesh.position);
            auto* raw = static_cast<std::uint32_t*>(lights.data);
            constexpr unsigned LampAt = 16, TableAt = 48, HistoryAt = 64, TuneAt = 100;
            Vec3 flame = TorchFlame;
            // A second lamp that stands (reach 6 m, as bright as the torch); none unless `second`.
            // wobble: added to the torch lamp's place for one frame (a flame that flickers).
            bool second = false;
            constexpr Vec3 SecondLamp{1.2f, 2.3f, -1.6f};
            Vec3 wobble{0, 0, 0};
            const auto camera = [&](float pan, float along) {
                return MakeViews({0.2f + pan, 4.5f, -1.2f + along}, {0.0f, -0.97f, 0.26f}, sun);
            };
            // The character with its torch `walk` metres towards the camera's foot (-z), the
            // other figure `other` metres along z; stick false: without the torch's stick.
            const auto place = [&](const Views& v, float walk, float other, bool stick = true) {
                for (const unsigned i : {TorchCharacter, TorchArm, TorchStick, TorchBlade}) {
                    scene.meshes[i].position = home[i] + Vec3{0, i == TorchStick && !stick ? -100.0f : 0.0f, -walk};
                }
                scene.meshes[TorchOther].position = home[TorchOther] + Vec3{0, 0, other};
                flame = TorchFlame + Vec3{0, 0, -walk};
                build_tlas(tlas, v.view, Fast, false, 4);
                lab.Prepare(tlas.handle, v);
            };
            struct Pass {
                const Vulkan::LampShadowTune* tune = nullptr; // null: mode 0 (the experiment bit's path)
                unsigned frame = 0;
                int parity = -1;               // the history image written; -1: no history
                bool read = false;             // with a history: the frame before is read
                const Views* before = nullptr; // with read: the camera of the frame before (null: this one)
                bool follow = true;            // with read: the history is looked up where the lamp's motion puts it
                bool half = false;             // the half-resolution build, in its two passes
                bool again = false;            // the pass before once more (its lamps and history block as they
                                               // are in the buffer), with this tuning: for a view of that frame
            };
            Vulkan::LampTrack track;
            const auto run = [&](const Views& v, const Pass& pass) {
                auto* words = static_cast<float*>(lights.data);
                for (int r = 0; r < 4; ++r)
                    for (int k = 0; k < 4; ++k) words[r * 4 + k] = v.inv_proj.at(r, k);
                const unsigned lamps = second ? 2u : 1u;
                for (unsigned l = 0; l < lamps && !pass.again; ++l) {
                    const Vec3 at = l == 0 ? flame + wobble : SecondLamp;
                    std::array<float, 16> light{};
                    for (int r = 0; r < 3; ++r)
                        light[r] = v.view.at(r, 0) * at.x + v.view.at(r, 1) * at.y + v.view.at(r, 2) * at.z + v.view.at(r, 3);
                    light[3] = 1.0f / 36.0f;
                    light[4] = 1.0f; light[5] = 0.8f; light[6] = l == 0 ? 0.6f : 0.7f;
                    std::memcpy(raw + LampAt + 16 * l, light.data(), sizeof(light));
                }
                const std::array<std::uint32_t, 8> row{0u, 0u, W, H, LampAt, lamps, 0u, 0u};
                std::memcpy(raw + TableAt, row.data(), sizeof(row));
                unsigned mode = 0;
                if (pass.tune) {
                    const auto tune_words = Vulkan::LampTuneWords(*pass.tune, false, 0.05f, v.view.m.data(), pass.frame);
                    std::memcpy(raw + TuneAt, tune_words.data(), sizeof(tune_words));
                    mode = 16u | TuneAt << 8; // MODE_REPAIR | place << 8
                }
                if (pass.parity >= 0 && !pass.again) {
                    // What PointShadow::Flush does for the pass that holds the history.
                    const Views& was = pass.before ? *pass.before : v;
                    const Mat4 back = was.view * Inverse(v.view), to_world = Inverse(v.view);
                    track.Begin(to_world.m.data());
                    std::array<int, 2> index{};
                    for (unsigned l = 0; l < lamps; ++l) index[l] = track.Add(raw + LampAt + 16 * l);
                    if (pass.read) track.Follow();
                    for (unsigned l = 0; l < lamps; ++l) {
                        const auto moved = pass.read && pass.follow && pass.tune->follow ? track.Shift(index[l], was.view.m.data())
                                                                                         : std::array<float, 3>{};
                        std::memcpy(raw + LampAt + 16 * l + 12, moved.data(), sizeof(moved));
                        const float step = pass.read ? track.Step(index[l]) : 0.0f;
                        std::memcpy(raw + LampAt + 16 * l + 15, &step, 4);
                    }
                    track.End(true);
                    raw[HistoryAt] = 2u | 4u | (pass.read ? 1u : 0u); // HISTORY_WRITE | HISTORY_BLEND | HISTORY_READ
                    raw[HistoryAt + 1] = pass.frame;
                    std::memcpy(raw + HistoryAt + 2, back.m.data(), 48);
                    std::memcpy(raw + HistoryAt + 14, was.proj.m.data(), 64);
                    const auto tail = Vulkan::LampHistoryTail(*pass.tune); // words 30 to 33
                    std::memcpy(raw + HistoryAt + 30, tail.data(), sizeof(tail));
                    static_assert(HistoryAt + 30 + Vulkan::LampHistoryTailWords <= TuneAt);
                }
                vk.Begin();
                VkClearColorValue one{};
                one.float32[0] = one.float32[1] = one.float32[2] = 1.0f;
                const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                vkCmdClearColorImage(vk.cmd, lamp_images[0].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                vkCmdClearColorImage(vk.cmd, lamp_images[2].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                const VkImageCopy whole{.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                    .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {W, H, 1}};
                vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[3].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                vk.Barrier();
                VkDescriptorBufferInfo data{lights.buffer, 0, (TuneAt + Vulkan::LampTuneWordCount) * 4};
                VkDescriptorImageInfo depth{vk.sampler, lab.depth.view, VK_IMAGE_LAYOUT_GENERAL};
                std::array<VkDescriptorImageInfo, 4> images{};
                for (int k = 0; k < 4; ++k) images[k] = {{}, lamp_images[k].view, VK_IMAGE_LAYOUT_GENERAL};
                VkWriteDescriptorSetAccelerationStructureKHR as{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET_ACCELERATION_STRUCTURE_KHR,
                    .accelerationStructureCount = 1, .pAccelerationStructures = &tlas.handle};
                const int cur_history = pass.parity < 0 ? 0 : pass.parity;
                VkDescriptorImageInfo history_prev{{}, history[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo history_cur{{}, history[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo answers{{}, half_answers.view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorBufferInfo counts{half_counts.buffer, 0, 64};
                std::array<VkWriteDescriptorSet, 11> writes{};
                for (unsigned k = 0; k < 11; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
                writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[0].pBufferInfo = &data;
                writes[1].descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER; writes[1].pImageInfo = &depth;
                for (int k = 0; k < 4; ++k) { writes[2 + k].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[2 + k].pImageInfo = &images[k]; }
                writes[6].descriptorType = VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR; writes[6].pNext = &as;
                writes[7].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[7].pImageInfo = &history_prev;
                writes[8].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[8].pImageInfo = &history_cur;
                writes[9].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[9].pImageInfo = &answers;
                writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[10].pBufferInfo = &counts;
                LampPush push;
                push.first_light = TableAt;
                push.count = 1;
                push.rect = {0, 0, int(W), int(H)};
                push.steps = 1;
                push.frame = pass.frame;
                push.bias = pass.tune ? pass.tune->bias_m : 0.03f;
                if (pass.parity >= 0) {
                    const unsigned history_at = HistoryAt;
                    std::memcpy(&push.length, &history_at, 4);
                }
                vk.Stamp(0);
                if (pass.parity >= 0) {
                    VkClearColorValue zero{};
                    vkCmdClearColorImage(vk.cmd, history[cur_history].image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
                    vk.Barrier();
                }
                if (pass.half) {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 11, writes.data());
                    unsigned word = mode | 2u | 8u; // MODE_HALF_FIRST | MODE_HALF_COUNT
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 15) / 16, (H + 15) / 16, 1);
                    vk.Barrier();
                    word = mode | 4u | 8u; // MODE_HALF_FILL | MODE_HALF_COUNT
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                } else {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 9, writes.data());
                    std::memcpy(&push.thickness, &mode, 4);
                    vkCmdPushConstants(vk.cmd, lamp.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                }
                vk.Barrier();
                vk.Stamp(1);
                vk.Barrier();
                return vk.End();
            };
            const auto values = [&] {
                const auto bits = lab.Read(lamp_images[0], VK_FORMAT_R32_SFLOAT);
                std::vector<float> out(bits.size());
                for (std::size_t k = 0; k < bits.size(); ++k) {
                    std::uint32_t word;
                    std::memcpy(&word, &bits[k], 4);
                    out[k] = decode(word);
                }
                return out;
            };
            const auto dump = [&](const std::string& name, const std::vector<float>& picture) {
                if (out_dir) WritePgm((std::string(out_dir) + "/" + name + ".pgm").c_str(), picture);
            };
            // The frames in turn: the frame counter, and whether the frame before left a history.
            unsigned clock = 0;
            bool have_history = false;
            const auto restart = [&] {
                clock = 0;
                have_history = false;
                track.End(false);
            };
            // One frame as the engine runs it. before: the camera of the frame before.
            const auto frame = [&](const Views& v, const Vulkan::LampShadowTune& tune, const Views* before = nullptr,
                                   bool follow = true) {
                const bool history = Vulkan::LampHistoryFrames(tune) > 0.0f;
                const double ms = run(v, {.tune = &tune, .frame = clock, .parity = history ? int(clock & 1u) : -1,
                                          .read = have_history && history, .before = before, .follow = follow});
                have_history = history;
                ++clock;
                return ms;
            };
            // The frame `frame` just ran, once more as BB_LAMP_SHADOW_VIEW=5 shows it: for every pixel the
            // share of the frames its history may hold that it does hold (the pass writes the same history
            // again). Below 0: the pass does not shadow the pixel.
            const auto held_view = [&](const Views& v, const Vulkan::LampShadowTune& tune) {
                Vulkan::LampShadowTune shown = tune;
                shown.view = 5;
                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .again = true});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
                for (float& p : picture) p = p > 0.75f ? -1.0f : 1.0f - 2.0f * p;
                return picture;
            };
            // The area lamp's true picture: the mean of `count` frames, each one ray a lamp.
            const auto truth = [&](const Views& v, const Vulkan::LampShadowTune& tune, unsigned count = 128) {
                Vulkan::LampShadowTune single = tune;
                single.history = 0.0f;
                std::vector<float> mean(W * H, 0.0f);
                for (unsigned k = 0; k < count; ++k) {
                    run(v, {.tune = &single, .frame = 4096u + k});
                    const auto one = values();
                    for (std::size_t i = 0; i < one.size(); ++i) mean[i] += one[i] / float(count);
                }
                return mean;
            };
            // Mean difference from `reference`: over the picture, over the reference's penumbra
            // (0.05 to 0.95), and the share of pixels more than 0.25 off, in percent.
            struct Off { double all = 0, penumbra = 0, far = 0; };
            const auto off = [&](const std::vector<float>& picture, const std::vector<float>& reference) {
                Off o;
                std::size_t soft = 0;
                for (std::size_t i = 0; i < picture.size(); ++i) {
                    const double d = std::abs(double(picture[i]) - reference[i]);
                    o.all += d;
                    o.far += d > 0.25 ? 1 : 0;
                    if (reference[i] > 0.05f && reference[i] < 0.95f) {
                        o.penumbra += d;
                        ++soft;
                    }
                }
                o.all /= double(picture.size());
                o.far *= 100.0 / double(picture.size());
                o.penumbra /= double(std::max<std::size_t>(soft, 1));
                return o;
            };
            // The mean of `held` (held_view) over the reference's penumbra: how much history the pixels
            // that need it have. The error numbers alone rank a smeared picture above a noisy one.
            const auto held_mean = [&](const std::vector<float>& held, const std::vector<float>& reference) {
                double sum = 0;
                std::size_t soft = 0;
                for (std::size_t i = 0; i < held.size(); ++i) {
                    if (held[i] >= 0.0f && reference[i] > 0.05f && reference[i] < 0.95f) {
                        sum += held[i];
                        ++soft;
                    }
                }
                return sum / double(std::max<std::size_t>(soft, 1));
            };
            // A stand-in for the temporal upscaler that runs after the pass (still camera only):
            // each frame's picture goes into a running mean that keeps 0.8 of what it held.
            const auto settle = [](std::vector<float>& held, const std::vector<float>& one, bool first) {
                if (first) {
                    held = one;
                    return;
                }
                for (std::size_t i = 0; i < one.size(); ++i) held[i] = 0.8f * held[i] + 0.2f * one[i];
            };

            // The knobs as the environment has them (BB_LAMP_SHADOW_*), as the engine reads them:
            // a radius or a history blend can be tried here before the game is started. The
            // checks below are made for the defaults (checked) and left out otherwise.
            Vulkan::LampShadowTune soft = Vulkan::ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); });
            soft.view = 0;
            const Vulkan::LampShadowTune stock;
            const bool checked = soft.radius_m == stock.radius_m && soft.history == stock.history &&
                                 soft.reject == stock.reject && soft.trail_m == stock.trail_m &&
                                 soft.follow == stock.follow && soft.carry_m == stock.carry_m &&
                                 soft.around == stock.around && soft.weights == stock.weights &&
                                 soft.clearance_m == stock.clearance_m && soft.bias_m == stock.bias_m &&
                                 soft.self_m == stock.self_m;
            if (!checked) std::puts("Torch lab: BB_LAMP_SHADOW_* knobs differ from the defaults: numbers and pictures only, no checks");
            Vulkan::LampShadowTune point = soft;
            point.radius_m = 0.0f;
            const Views view = camera(0.0f, 0.0f);

            // 1. The point lamp: the same picture whatever the frame counter, and no history.
            place(view, 0.0f, 0.0f, false);
            run(view, {.tune = &point});
            const auto point_bare = values(); // without the stick
            place(view, 0.0f, 0.0f);
            run(view, {.tune = &point, .frame = 0});
            const auto point_picture = values();
            run(view, {.tune = &point, .frame = 7});
            if (values() != point_picture || Vulkan::LampHistoryFrames(point) != 0.0f) {
                std::fprintf(stderr, "the point lamp (BB_LAMP_SHADOW_SOFT=0) changes with the frame counter, or keeps a history\n");
                return 1;
            }
            dump("point", point_picture);
            // The stick's band: dark with the stick, lit without. The bodies' shadows: dark without it.
            std::vector<std::size_t> band, body;
            for (std::size_t i = 0; i < point_picture.size(); ++i) {
                if (point_bare[i] < 0.25f) body.push_back(i);
                else if (point_picture[i] < 0.25f && point_bare[i] > 0.75f) band.push_back(i);
            }

            // 2. The area lamp: one frame, the true picture, 16 and 48 frames of history.
            run(view, {.tune = &soft, .frame = 0});
            const auto one_frame = values();
            dump("area_1_frame", one_frame);
            const auto reference = truth(view, soft);
            dump("area_true", reference);
            restart();
            // (late: the plain mean of frames 33 to 48, for what the history adds to or takes from the
            // light where the true picture is nearly dark or nearly lit: a bound that pulled the history
            // towards the answers around a pixel would show there.)
            std::vector<float> after4, after16, after48, upscaled, late(W * H, 0.0f);
            for (unsigned k = 0; k < 48; ++k) {
                frame(view, soft);
                if (k == 3 || k == 15 || k >= 32) {
                    auto now = values();
                    if (k >= 32) {
                        settle(upscaled, now, k == 32);
                        for (std::size_t i = 0; i < now.size(); ++i) late[i] += now[i] / 16.0f;
                    }
                    if (k == 3) after4 = std::move(now);
                    else if (k == 15) after16 = std::move(now);
                    else if (k == 47) after48 = std::move(now);
                }
            }
            dump("area_16_frames", after16);
            dump("area_48_frames", after48);
            dump("area_48_frames_upscaled", upscaled);
            const Off off1 = off(one_frame, reference), off4 = off(after4, reference), off16 = off(after16, reference),
                      off48 = off(after48, reference), off_up = off(upscaled, reference);
            double mean_true = 0, mean48 = 0, band_point = 0, band_light = 0, band_true = 0;
            std::array<double, 2> lean{}; // late minus true where the true picture is 0.05 to 0.2, 0.8 to 0.95
            std::array<std::size_t, 2> lean_n{};
            for (std::size_t i = 0; i < reference.size(); ++i) {
                mean_true += reference[i] / double(reference.size());
                mean48 += after48[i] / double(reference.size());
                const int bin = reference[i] > 0.05f && reference[i] < 0.2f ? 0 : reference[i] > 0.8f && reference[i] < 0.95f ? 1 : -1;
                if (bin >= 0) {
                    lean[std::size_t(bin)] += double(late[i]) - reference[i];
                    ++lean_n[std::size_t(bin)];
                }
            }
            for (std::size_t b = 0; b < 2; ++b) lean[b] /= double(std::max<std::size_t>(lean_n[b], 1));
            for (const std::size_t i : band) {
                band_point += point_picture[i] / double(std::max<std::size_t>(band.size(), 1));
                band_light += after48[i] / double(std::max<std::size_t>(band.size(), 1));
                band_true += reference[i] / double(std::max<std::size_t>(band.size(), 1));
            }
            std::size_t body_dark = 0;
            for (const std::size_t i : body) body_dark += after48[i] < 0.25f ? 1 : 0;
            std::printf("Torch lab, radius %.2f m, history %.2f (%.0f frames): difference from the true picture (mean of "
                        "128 frames), all pixels / penumbra / share more than 0.25 off: one frame %.4f / %.4f / %.2f%%, "
                        "4 frames %.4f / %.4f / %.2f%%, 16 frames %.4f / %.4f / %.2f%%, 48 frames %.4f / %.4f / %.2f%%, "
                        "48 frames through the upscaler's stand-in %.4f / %.4f / %.2f%%; mean light true %.4f, after 48 "
                        "frames %.4f; the mean of frames 33 to 48 less the true picture where that is 0.05 to 0.2: "
                        "%+.4f, 0.8 to 0.95: %+.4f\n",
                        soft.radius_m, soft.history, Vulkan::LampHistoryFrames(soft), off1.all, off1.penumbra, off1.far,
                        off4.all, off4.penumbra, off4.far, off16.all, off16.penumbra, off16.far, off48.all, off48.penumbra,
                        off48.far, off_up.all, off_up.penumbra, off_up.far, mean_true, mean48, lean[0], lean[1]);
            std::printf("Torch lab: the stick's band (%zu pixels the point lamp leaves dark): light kept %.3f with the "
                        "point lamp, %.3f with the area lamp (true %.3f); the bodies' shadows (%zu pixels dark without "
                        "the stick): %zu still below 0.25 with the area lamp\n",
                        band.size(), band_point, band_light, band_true, body.size(), body_dark);
            if (checked && (std::abs(mean48 - mean_true) > 0.004 || std::abs(lean[0]) > 0.02 || std::abs(lean[1]) > 0.02)) {
                std::fprintf(stderr, "the history is biased: mean light %.4f against the true %.4f, off by %+.4f where "
                                     "that is nearly dark and %+.4f where it is nearly lit\n",
                             mean48, mean_true, lean[0], lean[1]);
                return 1;
            }
            if (checked && (band.empty() || band_light < 0.5 || body_dark * 2 < body.size())) {
                std::fprintf(stderr, "the area lamp keeps %.3f of the light in the stick's band (%zu pixels) and %zu of "
                                     "%zu dark pixels of the bodies' shadows\n",
                             band_light, band.size(), body_dark, body.size());
                return 1;
            }

            // 3. Raw frames (BB_LAMP_SHADOW_HISTORY=0) through the upscaler's stand-in alone.
            {
                Vulkan::LampShadowTune single = soft;
                single.history = 0.0f;
                std::vector<float> held;
                restart();
                for (unsigned k = 0; k < 16; ++k) {
                    frame(view, single);
                    settle(held, values(), k == 0);
                }
                const Off o = off(held, reference);
                dump("area_no_history_upscaled", held);
                std::printf("Torch lab: no history, 16 frames through the upscaler's stand-in: %.4f / %.4f / %.2f%%\n",
                            o.all, o.penumbra, o.far);
            }

            // 3b. A lamp that sits lower over a surface than its radius (a candle on the ground): the
            // surface must not shadow itself under the lamp's disc. The figures are 30 m off, the lamp
            // 5 cm and 2 cm over bare ground: the area lamp's light where the point lamp's is whole.
            {
                std::array<double, 2> kept{};
                unsigned slot = 0;
                for (const float height : {0.05f, 0.02f}) {
                    place(view, 30.0f, 30.0f);
                    wobble = Vec3{0.2f - flame.x, height - flame.y, 0.0f - flame.z};
                    run(view, {.tune = &point, .frame = 0});
                    const auto low_point = values();
                    const auto low_true = truth(view, soft, 32);
                    double sum = 0;
                    std::size_t lit = 0;
                    for (std::size_t i = 0; i < low_true.size(); ++i) {
                        if (low_point[i] > 0.999f) {
                            sum += low_true[i];
                            ++lit;
                        }
                    }
                    kept[slot++] = sum / double(std::max<std::size_t>(lit, 1));
                    if (height > 0.03f) dump("low_lamp_true", low_true);
                }
                wobble = {0, 0, 0};
                place(view, 0.0f, 0.0f);
                std::printf("Torch lab: a lamp 5 cm and 2 cm over bare ground, radius %.2f m: the area lamp keeps %.4f "
                            "and %.4f of the light where the point lamp's is whole\n", soft.radius_m, kept[0], kept[1]);
                if (checked && !(kept[0] > 0.98 && kept[1] > 0.98)) {
                    std::fprintf(stderr, "the ground shadows itself under a lamp that sits lower than its radius\n");
                    return 1;
                }
            }

            // 4. Motion. 24 still frames, then `frames` frames in which the character walks with its
            // torch (walk, metres a frame; the camera goes with it as the game's does), the second
            // figure walks under the lamps (other), or the torch's lamp is off its place by up to
            // `shake` metres, anew every frame (a flame that flickers); then the picture of the last
            // frame against the true picture of that moment. plain: the history without its guards
            // (BB_LAMP_SHADOW_CLAMP=0, BB_LAMP_SHADOW_REJECT=0, BB_LAMP_SHADOW_TRAIL=0); follow
            // false: looked up where the ground was, never where the lamp's motion puts it.
            Vulkan::LampShadowTune plain = soft;
            plain.around = 0.0f;
            plain.reject = 0.0f;
            plain.trail_m = 0.0f;
            struct Move {
                float walk = 0.0f, other = 0.0f, shake = 0.0f;
                unsigned frames = 16;
                bool follow = true;
            };
            Views moved_view = view;
            std::vector<float> moved_held; // held_view of the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr) {
                restart();
                Views now = view;
                wobble = {0, 0, 0};
                place(now, 0.0f, 0.0f);
                for (unsigned k = 0; k < 24; ++k) frame(now, tune);
                std::vector<float> held;
                std::mt19937 rng(11);
                for (unsigned k = 1; k <= move.frames; ++k) {
                    const float walked = move.walk * float(k);
                    const Views before = now;
                    now = camera(0.0f, -walked);
                    if (move.shake > 0.0f) {
                        std::uniform_real_distribution<float> off(-move.shake, move.shake);
                        wobble = {off(rng), 0.0f, off(rng)};
                    }
                    place(now, walked, move.other * float(k));
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                }
                if (upscaled_out) *upscaled_out = std::move(held);
                moved_view = now;
                auto picture = values();
                moved_held = Vulkan::LampHistoryFrames(tune) > 0.0f ? held_view(now, tune) : std::vector<float>{};
                return picture;
            };
            // (The true picture of the moment `moving` ended at: the scene and the lamp stand as its
            // last frame left them.)
            for (const float speed : {0.067f, 0.02f}) {
                // 6.7 cm a frame is a run (4 m/s at 60 frames a second), 2 cm a walk.
                const Move walk{.walk = speed};
                Move anchored = walk;
                anchored.follow = false;
                const auto alone = moving(plain, walk), all = moving(soft, walk);
                const auto all_held = moved_held;
                const auto guarded = moving(soft, anchored);
                Vulkan::LampShadowTune loose = soft;
                loose.trail_m = 0.0f;
                const auto untrailed = moving(loose, walk);
                const auto untrailed_held = moved_held;
                const auto moved_true = truth(moved_view, soft);
                const Off a = off(alone, moved_true), c = off(guarded, moved_true), d = off(all, moved_true),
                          e = off(untrailed, moved_true);
                const std::string tag = speed > 0.05f ? "run" : "walk";
                dump(tag + "_true", moved_true);
                dump(tag + "_history_alone", alone);
                dump(tag + "_not_followed", guarded);
                dump(tag + "_no_trail", untrailed);
                dump(tag + "_default", all);
                std::printf("Torch lab, the character goes with its torch, %.1f cm a frame (the camera with it), the 16th "
                            "moving frame against the true picture of that moment (all / penumbra / more than 0.25 off): "
                            "the history without its guards %.4f / %.4f / %.2f%%; the default %.4f / %.4f / %.2f%% "
                            "(history held in the penumbra: %.2f of what it may); looked up where the ground was only "
                            "%.4f / %.4f / %.2f%%; with BB_LAMP_SHADOW_TRAIL=0 %.4f / %.4f / %.2f%% (held %.2f)\n",
                            speed * 100.0f, a.all, a.penumbra, a.far, d.all, d.penumbra, d.far,
                            held_mean(all_held, moved_true), c.all, c.penumbra, c.far, e.all, e.penumbra, e.far,
                            held_mean(untrailed_held, moved_true));
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
                    std::fprintf(stderr, "the guards, or following the lamp, do not help a carried torch\n");
                    return 1;
                }
            }
            for (const bool two : {false, true}) {
                second = two;
                std::vector<float> held;
                const Move other{.other = 0.05f};
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
                single.history = 0.0f;
                std::vector<float> bare;
                const auto raw_frame = moving(single, other, &bare);
                const Off f = off(bare, moved_true), g = off(raw_frame, moved_true);
                dump(tag + "_no_history_upscaled", bare);
                std::printf("Torch lab, a figure walks under %s (5 cm a frame), the 16th moving frame against the true "
                            "picture of that moment: the history without its guards %.4f / %.4f / %.2f%%; the default "
                            "%.4f / %.4f / %.2f%%; one frame's rays alone %.4f / %.4f / %.2f%%; through the upscaler's "
                            "stand-in: the default %.4f / %.4f / %.2f%%, the rays alone %.4f / %.4f / %.2f%%\n",
                            two ? "the still torch and a second lamp" : "the still torch", a.all, a.penumbra, a.far,
                            d.all, d.penumbra, d.far, g.all, g.penumbra, g.far, e.all, e.penumbra, e.far, f.all,
                            f.penumbra, f.far);
                if (checked && !(d.all < a.all && d.all < g.all)) {
                    std::fprintf(stderr, "the history's guards do not help a moving caster (%s)\n", tag.c_str());
                    return 1;
                }
            }
            // A caster is gone from one frame to the next (the second figure, set 30 m off): how
            // much of the old picture is left where the true one changed by more than 0.15, after
            // 1, 2, 4, 8 and 16 frames. With one lamp, and with two (where a shadow is only a part
            // of the pixel's light).
            for (const bool two : {false, true}) {
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
                    for (unsigned k = 0; k < 24; ++k) frame(view, tune);
                    place(view, 0.0f, 30.0f);
                    unsigned slot = 0;
                    for (unsigned k = 1; k <= 16; ++k) {
                        frame(view, tune);
                        if (k != 1 && k != 2 && k != 4 && k != 8 && k != 16) continue;
                        const auto now = values();
                        double sum = 0;
                        std::size_t changed = 0;
                        for (std::size_t i = 0; i < now.size(); ++i) {
                            const double change = double(old_true[i]) - new_true[i];
                            if (std::abs(change) > 0.15) {
                                sum += (double(now[i]) - new_true[i]) / change;
                                ++changed;
                            }
                        }
                        left[which][slot++] = sum / double(std::max<std::size_t>(changed, 1));
                    }
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
            }
            second = false;
            // A flame that flickers: the torch's lamp is up to 2 cm off its place, anew every frame,
            // over a still scene.
            {
                const Move shaken{.shake = 0.02f, .frames = 24};
                Move anchored = shaken;
                anchored.follow = false;
                const auto all = moving(soft, shaken);
                const auto all_held = moved_held;
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

            // 5. The camera moves 3 cm a frame over a still scene: the history follows it (the
            // way back to the camera of the frame before), or, as a check that it matters, does
            // not (as if the camera had stood still).
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
            }

            // 7. The cost here (a small scene; --speed has the heavy one): the fastest of 40 runs
            // taken in turn, the history's clear included.
            {
                std::array<double, 3> best{1e9, 1e9, 1e9};
                restart();
                for (int i = 0; i < 40; ++i) {
                    best[0] = std::min(best[0], run(view, {.frame = unsigned(i)}));
                    best[1] = std::min(best[1], run(view, {.tune = &point, .frame = unsigned(i)}));
                    best[2] = std::min(best[2], frame(view, soft));
                }
                std::printf("Torch lab: mode 0 of this shader (the experiment bit's path; not the shader before r41) %.3f ms, the point lamp %.3f ms, the area lamp with its "
                            "history %.3f ms\n", best[0], best[1], best[2]);
            }
            vk.destroy_as(vk.device, tlas.handle, nullptr);
            vk.Free(tlas.instances); vk.Free(tlas.storage); vk.Free(tlas.scratch);
            std::puts(checked ? "torch lab: ok" : "torch lab: done, not checked");
            return 0;
        }
        std::vector<std::array<double, 3>> lamp_ms(variants.size()), sun_ms(variants.size());
        std::array<double, 3> per_tile_ms{}, pick_ms{}, reuse_ms{}, reuse_error{};
"""),
        (r"""        // tuning under MODE_REPAIR differs from mode 0 (picked); mean lamp light kept with the
        // inverse-square weights; pixels a torch leaves dark as a point lamp and repaired.
        std::array<std::array<double, 2>, 3> repair_ms{}, torch_ms{};
        std::array<std::array<double, 3>, 3> repair_kept{}, torch_kept{};
        std::array<std::array<std::size_t, 2>, 3> repair_differ{}, torch_dark{};
""",
         r"""        // tuning under MODE_REPAIR differs from mode 0 (picked); mean lamp light kept with the
        // inverse-square weights; pixels a torch leaves dark as a point lamp and repaired.
        // bbport (r42_lamp-soft): the default repair is the area lamp now: timed with its history
        // (third: as a point lamp, BB_LAMP_SHADOW_SOFT=0), its light and its dark pixels taken
        // from the mean of 16 frames.
        std::array<std::array<double, 3>, 3> repair_ms{}, torch_ms{};
        std::array<std::array<double, 3>, 3> repair_kept{}, torch_kept{};
        std::array<std::array<std::size_t, 2>, 3> repair_differ{}, torch_dark{};
"""),
        (r"""                    bool engine_bias = false;
                    bool torch = false;
                };
                constexpr unsigned MaxTorches = 8;
                const unsigned tune_at = used + 32;
                const unsigned torch_at = tune_at + Vulkan::LampTuneWordCount;
                unsigned torch_count = 0;
""",
         r"""                    bool engine_bias = false;
                    bool torch = false;
                    // bbport (r42_lamp-soft): with a history (parity) and a tuning: the history
                    // averages the ratio over the frames (HISTORY_BLEND), as the engine's does
                    // for the area lamp.
                    bool blend = false;
                };
                constexpr unsigned MaxTorches = 8;
                const unsigned tune_at = used + 30 + Vulkan::LampHistoryTailWords; // after the history block
                const unsigned torch_at = tune_at + Vulkan::LampTuneWordCount;
                unsigned torch_count = 0;
"""),
        (r"""                    if (more.tune) {
                        const auto tune_words =
                            Vulkan::LampTuneWords(*more.tune, more.inverse_square, 0.05f, views.view.m.data());
                        std::memcpy(reinterpret_cast<std::uint32_t*>(words) + tune_at, tune_words.data(),
                                    sizeof(tune_words));
""",
         r"""                    if (more.tune) {
                        const auto tune_words =
                            Vulkan::LampTuneWords(*more.tune, more.inverse_square, 0.05f, views.view.m.data(), frame);
                        std::memcpy(reinterpret_cast<std::uint32_t*>(words) + tune_at, tune_words.data(),
                                    sizeof(tune_words));
"""),
        (r"""                        std::memcpy(block + 2, identity.data(), sizeof(identity));
                        std::memcpy(block + 14, views.proj.m.data(), 64);
                    }
                    vk.Begin();
""",
         r"""                        std::memcpy(block + 2, identity.data(), sizeof(identity));
                        std::memcpy(block + 14, views.proj.m.data(), 64);
                        if (more.blend && more.tune) { // bbport (r42_lamp-soft): words 30 to 33
                            block[0] |= 4u;
                            const auto tail = Vulkan::LampHistoryTail(*more.tune);
                            std::memcpy(block + 30, tail.data(), sizeof(tail));
                        }
                    }
                    vk.Begin();
"""),
        (r"""                    vk.Barrier();
                    VkDescriptorBufferInfo data{lights.buffer, 0,
                                                (used + 32 + Vulkan::LampTuneWordCount + MaxTorches * 24) * 4};
                    VkDescriptorImageInfo depth{vk.sampler, lab.depth.view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkDescriptorImageInfo, 4> images{};
""",
         r"""                    vk.Barrier();
                    VkDescriptorBufferInfo data{lights.buffer, 0,
                                                (tune_at + Vulkan::LampTuneWordCount + MaxTorches * 24) * 4};
                    VkDescriptorImageInfo depth{vk.sampler, lab.depth.view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkDescriptorImageInfo, 4> images{};
"""),
        (r"""                    //    its tiles, which is not fixed (two runs of mode 0 differ on some pixels),
                    //    so there the difference is bounded, not zero.
                    //  - A lamp with a radius never darkens a pixel that a point lamp lights (a
                    //    free rim ray only ever lights).
                    //  - The torch lamps: one beside each character (a capsule 1.8 m tall and 0.6 m
                    //    wide), 0.45 m from its side at 1.4 m, reaching 5 m, as a hand torch is
                    //    held: the caster is near the lamp, which is where a point lamp magnifies
                    //    it and where the rim rays are spent (the street lamps stand metres from
                    //    what they shadow). The same checks, and the body keeps most of its
                    //    shadow.
                    //  - What the default repair costs against mode 0 of this same shader (the
                    //    experiment bit's path; the shader before r41 is not in this build), with
                    //    the engine's ray start offset, runs taken in turn.
                    {
                        build_tlas(tlas, views.view, variant.flags, variant.doubled, 4);
""",
         r"""                    //    its tiles, which is not fixed (two runs of mode 0 differ on some pixels),
                    //    so there the difference is bounded, not zero.
                    //  - bbport (r42_lamp-soft): the point lamp (BB_LAMP_SHADOW_SOFT=0) gives the
                    //    same picture whatever the frame counter; the area lamp's picture is the
                    //    mean of 16 frames here (one ray a lamp a frame, to a point of the lamp's
                    //    disc that moves with the frame counter).
                    //  - The torch lamps: one beside each character (a capsule 1.8 m tall and 0.6 m
                    //    wide), 0.45 m from its side at 1.4 m, reaching 5 m, as a hand torch is
                    //    held: the caster is near the lamp, which is where a point lamp magnifies
                    //    it (the street lamps stand metres from what they shadow). The same
                    //    checks, and the body keeps most of its shadow.
                    //  - What the default repair costs against mode 0 of this same shader (the
                    //    experiment bit's path; the shader before r41 is not in this build), with
                    //    the engine's ray start offset, runs taken in turn: the area lamp with
                    //    its history (cleared and written every frame, read from the second on),
                    //    and the point lamp.
                    {
                        build_tlas(tlas, views.view, variant.flags, variant.doubled, 4);
"""),
        (r"""                            run_lamps(false, 0, 0, -1, {.tune = &point, .torch = torch});
                            const auto with_point = lamp_values();
                            run_lamps(false, 0, 0, -1, {.tune = &repaired, .torch = torch});
                            const auto with_radius = lamp_values();
                            std::size_t darker = 0, dark_point = 0, dark_radius = 0;
                            for (std::size_t k = 0; k < with_point.size(); ++k) {
                                darker += with_radius[k] < with_point[k] ? 1 : 0;
                                dark_point += with_point[k] < 0.25f ? 1 : 0;
                                dark_radius += with_radius[k] < 0.25f ? 1 : 0;
                            }
                            if (darker != 0) {
                                std::fprintf(stderr, "a lamp with a radius left %zu pixels darker than a point lamp "
                                                     "(camera %zu, %s lamps)\n", darker, cam, torch ? "torch" : "street");
                                return 1;
                            }
                            (torch ? torch_kept : repair_kept)[cam] = {kept_before, kept(with_point), kept(with_radius)};
""",
         r"""                            run_lamps(false, 0, 0, -1, {.tune = &point, .torch = torch});
                            const auto with_point = lamp_values();
                            run_lamps(false, 0, 5, -1, {.tune = &point, .torch = torch});
                            if (lamp_values() != with_point) {
                                std::fprintf(stderr, "the point lamp's picture changes with the frame counter (camera "
                                                     "%zu, %s lamps)\n", cam, torch ? "torch" : "street");
                                return 1;
                            }
                            std::vector<float> with_radius(with_point.size(), 0.0f);
                            for (unsigned f = 0; f < 16; ++f) {
                                run_lamps(false, 0, f, -1, {.tune = &repaired, .torch = torch});
                                const auto one = lamp_values();
                                for (std::size_t k = 0; k < one.size(); ++k) with_radius[k] += one[k] / 16.0f;
                            }
                            std::size_t dark_point = 0, dark_radius = 0;
                            for (std::size_t k = 0; k < with_point.size(); ++k) {
                                dark_point += with_point[k] < 0.25f ? 1 : 0;
                                dark_radius += with_radius[k] < 0.25f ? 1 : 0;
                            }
                            (torch ? torch_kept : repair_kept)[cam] = {kept_before, kept(with_point), kept(with_radius)};
"""),
        (r"""                                }
                            }
                            std::vector<double> plain, fixed;
                            for (int i = 0; i < 40; ++i) {
                                plain.push_back(run_lamps(false, 1, unsigned(i), -1, {.engine_bias = true, .torch = torch}));
                                fixed.push_back(run_lamps(false, 1, unsigned(i), -1,
                                                          {.tune = &repaired, .engine_bias = true, .torch = torch}));
                            }
                            // The fastest run of each: this lab's lamp pass times jump between runs
""",
         r"""                                }
                            }
                            std::vector<double> plain, fixed, as_point;
                            for (int i = 0; i < 40; ++i) {
                                plain.push_back(run_lamps(false, 1, unsigned(i), -1, {.engine_bias = true, .torch = torch}));
                                fixed.push_back(run_lamps(false, 1, unsigned(i), i & 1,
                                                          {.tune = &repaired, .engine_bias = true, .torch = torch, .blend = true}));
                                as_point.push_back(run_lamps(false, 1, unsigned(i), -1,
                                                             {.tune = &point, .engine_bias = true, .torch = torch}));
                            }
                            // The fastest run of each: this lab's lamp pass times jump between runs
"""),
        (r"""                            // by several times, and the median moves with them.
                            (torch ? torch_ms : repair_ms)[cam] = {*std::min_element(plain.begin(), plain.end()),
                                                                   *std::min_element(fixed.begin(), fixed.end())};
                        }
                        // The inverse-square weights (startup_local_inverse_square): they run and
""",
         r"""                            // by several times, and the median moves with them.
                            (torch ? torch_ms : repair_ms)[cam] = {*std::min_element(plain.begin(), plain.end()),
                                                                   *std::min_element(fixed.begin(), fixed.end()),
                                                                   *std::min_element(as_point.begin(), as_point.end())};
                        }
                        // The inverse-square weights (startup_local_inverse_square): they run and
"""),
        (r"""                    reuse_ms[0], reuse_ms[1], reuse_ms[2], reuse_error[0], reuse_error[1], reuse_error[2]);
        // bbport (r41_lamp-shadows)
        std::printf("Lamps that hit (instances with the lamp bit), picked, repaired (r41, default tuning): %.3f %.3f "
                    "%.3f ms against %.3f %.3f %.3f ms of mode 0 of this shader (the experiment bit's path; the "
                    "fastest of 40 runs taken in turn, the engine's ray start offset); mean lamp light kept with "
                    "every lamp traced: mode 0 "
                    "%.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired %.4f %.4f %.4f, repaired "
                    "with inverse-square weights %.4f %.4f %.4f; the old "
                    "tuning under MODE_REPAIR gave mode 0's numbers with every lamp traced, and with picked lamps "
                    "differed on %zu %zu %zu pixels where two runs of mode 0 differed on %zu %zu %zu\n",
                    repair_ms[0][1], repair_ms[1][1], repair_ms[2][1], repair_ms[0][0], repair_ms[1][0],
                    repair_ms[2][0], repair_kept[0][0], repair_kept[1][0], repair_kept[2][0], repair_kept[0][1],
                    repair_kept[1][1], repair_kept[2][1], repair_kept[0][2], repair_kept[1][2], repair_kept[2][2],
""",
         r"""                    reuse_ms[0], reuse_ms[1], reuse_ms[2], reuse_error[0], reuse_error[1], reuse_error[2]);
        // bbport (r41_lamp-shadows)
        std::printf("Lamps that hit (instances with the lamp bit), picked, repaired (r42, default tuning: the area "
                    "lamp with its history): %.3f %.3f %.3f ms, as a point lamp %.3f %.3f %.3f ms, against %.3f %.3f "
                    "%.3f ms of mode 0 of this shader (the experiment bit's path; the "
                    "fastest of 40 runs taken in turn, the engine's ray start offset); mean lamp light kept with "
                    "every lamp traced: mode 0 "
                    "%.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired (16 frames) %.4f %.4f %.4f, "
                    "repaired with inverse-square weights %.4f %.4f %.4f; the old "
                    "tuning under MODE_REPAIR gave mode 0's numbers with every lamp traced, and with picked lamps "
                    "differed on %zu %zu %zu pixels where two runs of mode 0 differed on %zu %zu %zu\n",
                    repair_ms[0][1], repair_ms[1][1], repair_ms[2][1], repair_ms[0][2], repair_ms[1][2],
                    repair_ms[2][2], repair_ms[0][0], repair_ms[1][0],
                    repair_ms[2][0], repair_kept[0][0], repair_kept[1][0], repair_kept[2][0], repair_kept[0][1],
                    repair_kept[1][1], repair_kept[2][1], repair_kept[0][2], repair_kept[1][2], repair_kept[2][2],
"""),
        (r"""                    repair_differ[0][1], repair_differ[1][1], repair_differ[2][1], repair_differ[0][0],
                    repair_differ[1][0], repair_differ[2][0]);
        std::printf("Torch lamps (0.45 m from a character's side, reach 5 m), picked, repaired: %.3f %.3f %.3f ms "
                    "against %.3f %.3f %.3f ms of mode 0 of this shader; mean lamp light kept with every lamp traced: "
                    "mode 0 %.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired %.4f %.4f %.4f; dark "
                    "pixels repaired %zu %zu %zu, with a point lamp %zu %zu %zu\n",
                    torch_ms[0][1], torch_ms[1][1], torch_ms[2][1], torch_ms[0][0], torch_ms[1][0], torch_ms[2][0],
                    torch_kept[0][0], torch_kept[1][0], torch_kept[2][0], torch_kept[0][1], torch_kept[1][1],
                    torch_kept[2][1], torch_kept[0][2], torch_kept[1][2], torch_kept[2][2], torch_dark[0][1],
""",
         r"""                    repair_differ[0][1], repair_differ[1][1], repair_differ[2][1], repair_differ[0][0],
                    repair_differ[1][0], repair_differ[2][0]);
        std::printf("Torch lamps (0.45 m from a character's side, reach 5 m), picked, repaired: %.3f %.3f %.3f ms, "
                    "as a point lamp %.3f %.3f %.3f ms, "
                    "against %.3f %.3f %.3f ms of mode 0 of this shader; mean lamp light kept with every lamp traced: "
                    "mode 0 %.4f %.4f %.4f, repaired with a point lamp %.4f %.4f %.4f, repaired (16 frames) %.4f %.4f "
                    "%.4f; dark pixels repaired %zu %zu %zu, with a point lamp %zu %zu %zu\n",
                    torch_ms[0][1], torch_ms[1][1], torch_ms[2][1], torch_ms[0][2], torch_ms[1][2], torch_ms[2][2],
                    torch_ms[0][0], torch_ms[1][0], torch_ms[2][0],
                    torch_kept[0][0], torch_kept[1][0], torch_kept[2][0], torch_kept[0][1], torch_kept[1][1],
                    torch_kept[2][1], torch_kept[0][2], torch_kept[1][2], torch_kept[2][2], torch_dark[0][1],
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the shader, the pass and the tuning header
    agree on the history's flag and words and on the tuning words; nothing of r41's rim rays is
    left; the reject cannot be set off by one stray ray; the averaging pass's barrier is reached
    by every pixel of a workgroup; the half-resolution build has none of it."""
    ok = True
    comp = texts[B + "host_shaders/point_shadow_ray.comp"]
    cpp = texts[R + "vk_point_shadow.cpp"]
    tune = texts[R + "lamp_shadow_tune.h"]
    scene = texts[R + "vk_rt_shadow.cpp"]
    if "const uint MODE_REPAIR = 16u;" not in comp or "constexpr u32 ModeRepair = 16;" not in cpp:
        print("the shader and the pass do not agree on MODE_REPAIR")
        ok = False
    if "const uint HISTORY_BLEND = 4u;" not in comp or "constexpr u32 HistoryBlend = 4;" not in cpp:
        print("the shader and the pass do not agree on HISTORY_BLEND")
        ok = False
    if "constexpr u32 HistoryWords = 2 + 12 + 16 + LampHistoryTailWords;" not in cpp or \
            "LampHistoryTailWords = 4;" not in tune or \
            any("word(history_at + %du)" % k not in comp for k in (30, 31, 32, 33)) or \
            "word(history_at + 34u)" in comp or cpp.count("auto tail = LampHistoryTail(pass_tune);") != 1 or \
            cpp.count("data.insert(data.end(), tail.begin(), tail.end());") != 1:
        print("the shader and the pass do not agree on the history block's words 30 to 33")
        ok = False
    read = len(set(re.findall(r"word\(at \+ (\d+)u\)", comp[comp.index("void loadTune()"):comp.index("vec3 stepColour")])))
    if read != 14 or "t_frame = data.d[at + 3u];" not in comp or "LampTuneWordCount = 16;" not in tune or \
            tune.count("            bits(") != 14 or tune.count("            frame,\n") + tune.count("            frame,\r\n") != 1:
        print("the shader reads %d tuning floats, the header gives 14, a flag word and the frame counter" % read)
        ok = False
    if comp.count("rayQueryInitializeEXT(") != 1 or "rimLight" in comp or "t_rim" in comp or "t_share" in comp or \
            "tune.rim" in cpp or "near_part" in tune:
        print("something of r41's rim rays is left, or the shader starts its ray query in more than one place")
        ok = False
    if "vec3(word(top_at + 12u), word(top_at + 13u), word(top_at + 14u))" not in comp or \
            "record[12 + c] = std::bit_cast<u32>(shift[c]);" not in cpp or \
            "word(top_at + 15u)" not in comp or "record[15] = std::bit_cast<u32>(step);" not in cpp:
        print("the shader and the pass do not agree on where a lamp record holds the lamp's motion")
        ok = False
    # (One stray ray moves the mean of the last few frames by 1 - FAST_KEEP: the reject must set
    # in above that for a history of any age, so nothing may scale t_reject down again.)
    if "const float FAST_KEEP = 0.6;" not in comp or "const float REJECT_FROM = 0.9;" not in comp or \
            "LampRejectLeast = 0.45f;" not in tune or "YOUNG_REJECT" in comp or \
            comp.count("smoothstep(REJECT_FROM * t_reject, t_reject, abs(fast - held_ratio))") != 1:
        print("the reject's constants changed: REJECT_FROM x LampRejectLeast must stay above 1 - FAST_KEEP")
        ok = False
    # The averaging pass shares its answers inside a workgroup: every pixel of the workgroup must
    # reach that barrier (a pixel the pass does not shadow may not return before it), and the
    # half-resolution build, whose workgroups are laid out otherwise, has none of it.
    shared = comp.index("shared float group_answer[64];")
    if comp.count("barrier();") != 4 or comp.count("        if (!blend) {\n            return;") + \
            comp.count("        if (!blend) {\r\n            return;") != 1 or \
            comp.rindex("#ifndef HALF", 0, shared) < comp.rindex("#endif", 0, shared) or \
            "LampTuneViewMax = 6;" not in tune or "t_view = (f >> 8u) & 7u;" not in comp:
        print("the averaging pass's shared answers, its barrier or the views' bits are not as the patch made them")
        ok = False
    if cpp.count("LampCameraCut(reproject.data())") != 1 or "inline bool LampCameraCut(const float* back)" not in tune:
        print("the pass should not read its averaged history across a camera cut")
        ok = False
    if comp.count("const bool blend = false;") != 1 or comp.count("    t_radius = 0.0;") != 1:
        print("the half-resolution build should keep the point lamp without a history")
        ok = False
    if cpp.count("    if (use_half || beside) {") != 1 or cpp.index("bool use_half = ") > cpp.index("LampShadowTune pass_tune = tune;"):
        print("the pass should know whether it runs at half resolution before it makes its tuning")
        ok = False
    if scene.count("LampStaleOut()") != 4:
        print("vk_rt_shadow.cpp should define BB_LAMP_SHADOW_STALE's switch once and use it in three places")
        ok = False
    if "LampRepairOffBit" not in cpp or "!BbToggle::Experiment(LampRepairOffBit)" not in scene:
        print("experiment 35184372088832 (the path before r41) is not read any more")
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
        print("usage: r42_lamp-soft.py check|apply|revert   (R42_ROOT names another tree)")
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
