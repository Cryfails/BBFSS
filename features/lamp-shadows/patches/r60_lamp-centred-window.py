# r60_lamp-centred-window: BB_LAMP_SHADOW_WINDOW gains the value 2, the ghost clamp's 5x5 window
# centred on every pixel ("Fix 2" of the second squares diagnosis). 0 and 1 stay as r57 left
# them, word for word; the default stays 1 (LampWindowDefault in lamp_shadow_tune.h, one line to
# flip). check|apply|revert.
#
# WHY: the ray traced lamp shadow pass (point_shadow_ray.comp, HISTORY_BLEND) bounds a pixel's
# history by the 25 answers around it, and the soft follow caps the frames of the history's
# "stands" share by the far blockers' mean swing in the same window. A compute workgroup sees only
# its own 8x8 pixels, so the window is moved in from the rim (around_lo = clamp(lid - 2, 0, 3)):
# runs of 3, 1, 1 and 3 pixels share one window, and behind a moving shadow that leaves squares
# fixed to the screen (8 px; 16 px in the half-resolution build's first pass). r57's 0 removes the
# window but its per-pixel bound is too loose (it cuts only a change of more than about 0.86, so the
# two-lamp linger check fails with it: 0.903 / 0.814 against 0.141 / 0.121 with 1) and its swing is
# a guess (OWN_SWING). 2 keeps the window and centres it.
#
# WHAT (the design page is in the report; numbers are estimates):
#  - Two new shader builds of the same source, CENTRED=1: point_shadow_ray_centred_comp and
#    point_shadow_ray_half_centred_comp (gpu/CMakeLists.txt). Everything new in the shader is under
#    #ifdef CENTRED, so the two builds of today compile to the same SPIR-V as before (checked: byte
#    for byte). PointShadow::Ready / HalfReady make the centred builds instead when the knob is 2
#    (read once at start; restart to change). Ready falls back to the plain build (value 1) and
#    HalfReady to the plain half build (the half-resolution pass then has value 1 and does not
#    split; half_centred) when a centred build cannot be made; each says so in the log. They have
#    one binding more: an RG32UI image of the answers (11 in the full build, 13 in the half one),
#    made only with 2: 8 bytes a pixel, 16.6 MB at 1920x1080, 66.4 MB at 3840x2160. It is made at
#    the first ray traced pass's size when there is none, and given its size only by the pass that
#    splits (a ray pass of another size beside it does not make it anew; without room the pass runs
#    whole, value 1, said once in the log).
#  - The pass that averages (HISTORY_BLEND), not views 2 and 3, runs as a trace and a resolve
#    (push mode bits MODE_TRACE 32, MODE_RESOLVE 64; the host and the shader take the same
#    decision, and a split the shader does not take is done whole by its trace). The trace casts
#    the rays as today and stores, per pixel, its answer (float bits; below 0 none), a cast code
#    (half float: -1 free, -2 near the moving lamp, -3 near a lamp that stands, -4 further off and
#    the lamp stands, -5 HALF_TAKEN, 0..64 the far blocker's swing under a moving lamp) and the
#    strongest lamp's record / 16. The resolve casts no ray: it lists the tiles as its trace did
#    (so a workgroup without a tile returns in both, as with 1), re-reads the pixel's light and
#    depth (unchanged by the trace where it answered), loads a 12x12 tile of the answers (the
#    workgroup and 2 on every side; 144 texels for 64 pixels) into shared memory, and does the
#    history blend with the 5x5 window centred on the pixel: the bound, the soft follow's swing
#    (k_win, not OWN_SWING) and, with BB_LAMP_SHADOW_FOLLOW_SOFT=0, the vote. Full resolution:
#    trace, barrier, resolve (+1 dispatch, +1 barrier). Half resolution: trace and resolve of the
#    first half, then of the second (+2 dispatches, +2 barriers): the second half's trace reads
#    the block answers and the history the first half's resolve wrote. The second half's window
#    takes the first half's answers at the even pixels too (they lie in the image; the confined
#    window could not reach them: a deliberate difference, so at half resolution 2 differs from 1
#    in two ways). Counting (HalfCount) stays in the traces; the resolves clear ModeHalfCount.
#  - Why the window no longer moves with the grid: in the resolve, pixel p reads tile cell
#    (lid + 2 + d), which holds the answer at p + d (stride 1; first-pass pixels stride 2), for
#    d in [-2, 2]^2, in the same order wherever the workgroup starts; cells outside the pass's rect
#    or the screen hold "no answer", as a pixel the trace did not answer does. So its statistic is
#    a function of the answers at p + [-2..2]^2 alone. tests/test_lamp_shadow_tune.cpp has a CPU
#    model of that index arithmetic (a hand copy, not a test of the shader): 2 bit-identical to a
#    neighbourhood sum written on its own, for workgroup origin shifts 0..7, 4 rects and screens,
#    stride 1 and 2; 1 not. And the cast code's packing (half float and record / 16) round trip.
#  - lamp_shadow_tune.h: LampWindowDefault (= 1, static_assert <= 2), LampShadowTune::
#    window_centred, LampTuneCentred (word 0 bit 22, set only with bit 21; static_assert that it is
#    free), LampWindowValue, the read of 0..2 (3 or more: 2; below 0: 0; not a whole number: the
#    default). Bit 21's meaning is kept.
#  - Log: the r57 line keeps its "window yes/no" and says what 2 does; a new line "Ray traced
#    lamps (r60): centred window yes/no ..." with the cost (its effect said as meant, not measured);
#    one line when the answers image is made; one when a centred build or the image's room fails.
#  - Doc: a bullet in engine/docs/renderer-performance-0.9.43.md.
#  - tests/test_lamp_shadow_tune.cpp: value 2, the round trip, the old bits unchanged (0 and 1
#    give r57's word 0), asserts written against LampWindowDefault (a flip to 2 needs no test
#    edit; 0 needs the r57 asserts changed), the CPU model, the cast code.
#  - tests/test_rt_shadows.cpp (rt-shadow-test --lamps): the centred builds and their image, the
#    split dispatches, MODE_APART (Pass::apart, at_apart: the engine's lamps-apart pass, which the
#    lab did not run before). The lattice runs 2 (with MODE_APART) beside the reference, 1 and 0;
#    0's verdict (checked) is now the folds' bin ratios against the reference's (mod 8, and mod 16
#    at half resolution; mod 2 printed only): at most GridMost = 1.05 times it in every case
#    (r57's numbers: at most 1.004). Printed only until a GPU run gives their numbers: whether 2
#    lines up, judged only where 1 does ("blind" elsewhere); whether 2's picture differs from
#    1's; once, whether MODE_APART changes the picture of 1 or 2 (it must not); the linger numbers
#    of 2 (with MODE_APART) at full and half resolution beside the default's bounds; a timing line
#    for 1 and 2. The street-lamp section runs the plain build only (said in a comment).
#
# THE KNOB: BB_LAMP_SHADOW_WINDOW 0, 1 or 2 (default LampWindowDefault = 1), read once at start
# (ReadLampShadowTune). No experiment bit. To make 2 the default: LampWindowDefault = 2 in
# lamp_shadow_tune.h; then also: the r57 log line's text "1 (the default)", the doc bullets of
# r57 ("default 1") and r60 ("the default is ... 1"), and the lattice/linger lines of the lab that
# name "the default" (the torch lab's default runs then run 2; the tune test needs no edit).
#
# HOW TO TEST:
#  1. lamp-shadow-tune-test (done by hand here: passes, also with LampWindowDefault = 2).
#  2. rt-shadow-test --lamps with nothing set: every old check as today (0's lattice verdict is
#     now the bin ratios). Read the r60 lines: "r60 apart" 0 pixels differ; 2 "does not" line up
#     where 1 lines up; "2 and 1 give the same picture: no"; the linger numbers of 2 within the
#     default's bounds (r57: 0.141 / 0.121 / 0.097 with two lamps); the run time (r57 took more
#     than 120 s). Then make the printed r60 lines checks.
#  3. BB_LAMP_SHADOW_WINDOW=2 rt-shadow-test --lamps: every old check of the torch lab on 2.
#  4. Game (HQ GTAO, torch out, DLSS Performance 4K, the r52 spot, walk 3): BB_LAMP_SHADOW_WINDOW=2
#     against 1 and 0, at graphics_lamp_shadow_half=1 and 0, and FOLLOW=0; VIEW=4, 5, 6 and normal.
#     VIEW=6 at half resolution is judged against 0 (r57's N3 showed r52's weight w in squares there
#     with 0 too, which r60 does not touch). BB_GPU_PROFILE=1 "point shadows" row. The log lines of
#     r57 and r60.
#
# THE TREE: R60_ROOT, else the current directory; every message names it. Every edit is an exact
# text found exactly once where it is applied, in order; revert applies them backwards (no whole-
# file hash: r53 edits lamp_shadow_tune.h, the doc, the tune test and vk_point_shadow.cpp elsewhere,
# r58 gpu/CMakeLists.txt; both were checked to commute with these edits). check says "applies
# cleanly" or "already applied" (exit 0 both) or why neither (exit 1; on a mixed tree, each file's
# state: original, patched or neither). Line ends are kept (all eight files are CRLF). New texts
# are written beside their targets and moved over them; a failure puts back what was moved.
#
# NOT DONE: no GPU run (not allowed while the game test runs): the lab's new lines and the cost
# are not measured. Checked here: glslang --target-env vulkan1.3 of the four builds and spirv-val;
# the two old builds' SPIR-V byte for byte as the tree's; clang++ -fsyntax-only of
# vk_point_shadow.cpp and test_rt_shadows.cpp with the build's flags; lamp-shadow-tune-test built
# and run by hand.

import os
import sys

ROOT = os.environ.get("R60_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"

COMP = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
TUNE = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
CPP = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
HDR = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.h"
CMAKE = "engine/gpu/CMakeLists.txt"
DOC = "engine/docs/renderer-performance-0.9.43.md"
TEST = "engine/tests/test_lamp_shadow_tune.cpp"
LAB = "engine/tests/test_rt_shadows.cpp"
TMP = ".r60tmp"  # a new text waits under this name beside its target (main)

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Written with LF; the file's CRLF is put in.
EDITS = {
    COMP: [
        (r"""layout(set = 0, binding = 10, r32f) uniform writeonly image2D follow_cur;
#endif
""",
         r"""layout(set = 0, binding = 10, r32f) uniform writeonly image2D follow_cur;
#endif
#ifdef CENTRED
// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 only (the builds made with CENTRED,
// point_shadow_ray_centred_comp and point_shadow_ray_half_centred_comp; the two builds without it
// are the pass as before, word for word). The pass that averages runs as two dispatches of this
// shader: MODE_TRACE casts the rays and stores what they said here; MODE_RESOLVE casts none and does
// the rest (the history, the light) with the ghost clamp's window centred on every pixel (see main).
// One texel a pixel: x this frame's answer (its float bits; below 0: the pixel has none), y the cast
// code (castCode, a half float in the high 16 bits) and the strongest lamp's record / 16 (low 16).
#ifdef HALF
layout(set = 0, binding = 13, rg32ui) uniform uimage2D lamp_answers;
#else
layout(set = 0, binding = 11, rg32ui) uniform uimage2D lamp_answers;
#endif
#endif
"""),
        (r"""bool t_window = true;           // bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW (true: the pass of before)
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
""",
         r"""bool t_window = true;           // bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW (true: the pass of before)
#ifdef CENTRED
bool t_centred = false;         // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 (with t_window)
#endif
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
"""),
        (r"""    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)
    t_clear = word(at + 1u);
""",
         r"""    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)
#ifdef CENTRED
    t_centred = (f & (1u << 22u)) != 0u;     // bbport (r60_lamp-centred-window)
#endif
    t_clear = word(at + 1u);
"""),
        (r"""shared float group_cast[64];

#ifdef HALF
""",
         r"""shared float group_cast[64];

#ifdef CENTRED
// bbport (r60_lamp-centred-window): more bits of `mode` (vk_point_shadow.cpp ModeTrace, ModeResolve),
// set by the host only on the pass that averages (HISTORY_BLEND) with word 0 bit 22 set.
const uint MODE_TRACE = 32u;
const uint MODE_RESOLVE = 64u;
// What the trace stores of the ray to the pixel's strongest lamp: in one value the two things the
// blend below takes from it, the blocker (group_cast: -1 none, -2 near the moving lamp, else the far
// blocker's swing, 0 to 64; both only under a moving lamp) and the follow evidence e (+1 near, -1
// further off, 0 free; under a lamp that stands too).
const float CAST_FREE = -1.0;       // free, or no ray to the strongest lamp: blocker -1, e 0
const float CAST_NEAR = -2.0;       // blocked near the moving lamp: blocker -2, e +1
const float CAST_NEAR_STILL = -3.0; // blocked near the lamp, which stands: blocker -1, e +1
const float CAST_FAR_STILL = -4.0;  // blocked further off, the lamp stands: blocker -1, e -1
const float CAST_TAKEN = -5.0;      // HALF_TAKEN (the block's answer, no ray): blocker -1
                                    // (0 or more: blocked further off under the moving lamp, the
                                    // blocker's swing; e -1)
// The resolve's tile: the workgroup's 8x8 pixels (8x8 first-pass pixels, two apart, in the
// half-resolution build's first pass) and two more on every side, so that the 5x5 window of every
// pixel lies wholly in it, centred on the pixel.
const int TILE_SIDE = 12;
shared float tile_answer[144];
shared float tile_cast[144];

// The follow evidence e a cast code stands for.
float castEvidence(float c) {
    if (c >= 0.0 || (c < -3.5 && c > -4.5)) {
        return -1.0;
    }
    return c < -1.5 && c > -3.5 ? 1.0 : 0.0;
}

// The trace's texel for pixel p (one off the screen is not stored). answer below 0: none. top: the
// strongest lamp's record (0: none); records start on 16-word steps below 2^20 (vk_point_shadow.cpp
// static_asserts), anything else is stored as none.
void storeAnswer(ivec2 p, float answer, float code, uint top) {
    if (all(lessThan(p, ivec2(size)))) {
        const uint at = (top & 15u) == 0u && top < (1u << 20u) ? top >> 4u : 0u;
        imageStore(lamp_answers, p,
                   uvec4(floatBitsToUint(answer), (packHalf2x16(vec2(0.0, code)) & 0xFFFF0000u) | at, 0u, 0u));
    }
}

// The resolve's tile, loaded by the whole workgroup (every invocation calls it, and a barrier
// follows). lo: the workgroup's first pixel; apart: 1, or 2 between first-pass pixels. A place
// outside the pass's rect or the screen has no answer: nothing traced it this frame.
void loadTile(ivec2 lo, int apart) {
    for (uint i = gl_LocalInvocationIndex; i < 144u; i += 64u) {
        const ivec2 q = lo + apart * (ivec2(int(i % 12u), int(i / 12u)) - 2);
        float a = -1.0, c = CAST_FREE;
        if (all(greaterThanEqual(q, rect.xy)) && all(lessThan(q, rect.zw)) && all(lessThan(q, ivec2(size)))) {
            const uvec2 t = imageLoad(lamp_answers, q).xy;
            a = uintBitsToFloat(t.x);
            c = unpackHalf2x16(t.y).y;
        }
        tile_answer[i] = a;
        tile_cast[i] = c;
    }
}
#endif

#ifdef HALF
"""),
        (r"""#endif
    for (uint t = gl_LocalInvocationIndex; t < light_count; t += 64u) {
""",
         r"""#endif
#ifdef CENTRED
    // bbport (r60_lamp-centred-window): the resolve lists the tiles as its trace did (the same test,
    // so the same workgroups return below: one without a tile does in both, as with value 1, and
    // its trace has stored "no answer" for its pixels, which the windows around it read from the
    // image), but casts no ray (tile_count below)
    const bool resolve_mode = (mode & MODE_RESOLVE) != 0u;
#endif
    for (uint t = gl_LocalInvocationIndex; t < light_count; t += 64u) {
"""),
        (r"""#ifdef HALF
        if (first) {
            imageStore(half_answers, ivec2(gl_GlobalInvocationID.xy), vec4(-1.0)); // no answer
        }
""",
         r"""#ifdef HALF
#ifdef CENTRED
        if (first && !resolve_mode) { // (bbport r60_lamp-centred-window: the trace stored it)
#else
        if (first) {
#endif
            imageStore(half_answers, ivec2(gl_GlobalInvocationID.xy), vec4(-1.0)); // no answer
        }
#endif
#ifdef CENTRED
        if ((mode & MODE_TRACE) != 0u) { // bbport (r60_lamp-centred-window): no answer here
#ifdef HALF
            const ivec2 p = ivec2(gl_GlobalInvocationID.xy) * (first ? 2 : 1);
            if (!fill || ((p.x | p.y) & 1) != 0) { // (not over the first pass's pixel)
                storeAnswer(p, -1.0, CAST_FREE, 0u);
            }
#else
            storeAnswer(ivec2(gl_GlobalInvocationID.xy), -1.0, CAST_FREE, 0u);
#endif
        }
"""),
        (r"""    const bool overflow = listed > MAX_GROUP_TILES;
    const uint tile_count = overflow ? light_count : listed;
    const uint history_at = floatBitsToUint(length_m);
""",
         r"""    const bool overflow = listed > MAX_GROUP_TILES;
#ifdef CENTRED
    const uint tile_count = resolve_mode ? 0u : overflow ? light_count : listed; // (r60: the resolve weighs no lamp)
#else
    const uint tile_count = overflow ? light_count : listed;
#endif
    const uint history_at = floatBitsToUint(length_m);
"""),
        (r"""        t_radius = 0.0;
    }
#endif
""",
         r"""        t_radius = 0.0;
    }
#endif
#ifdef CENTRED
    // bbport (r60_lamp-centred-window): the two dispatches' roles, the same for the whole workgroup
    // (push constant, tuning word, history flags). Only the pass that averages has the window; views
    // 2 and 3 (lamps, rays) are drawn by one dispatch (the host does not split them). A split the
    // shader does not take is done whole by its trace dispatch, and its resolve does nothing.
    const bool centred = t_centred && (history_flags & HISTORY_BLEND) != 0u && t_view != 2u && t_view != 3u;
    const bool trace_only = (mode & MODE_TRACE) != 0u && centred;
    const bool resolve = resolve_mode && centred;
    if (resolve_mode && !centred) {
        return;
    }
#ifdef HALF
    const bool resolve_normal = first; // the first pass's block answer holds the normal
    // The window's places: first-pass pixels two apart in the first pass (25 answers within 4
    // pixels, as the workgroup-confined window had); every pixel in the second, whose window then
    // takes the first pass's answers too (the confined one could not: they were not in its
    // workgroup's shared arrays).
    const int resolve_apart = first ? 2 : 1;
#else
    const bool resolve_normal = false;
    const int resolve_apart = 1;
#endif
#endif
"""),
        (r"""    live = live && !done_first;
#endif
""",
         r"""    live = live && !done_first;
#endif
#ifdef CENTRED
    // bbport (r60_lamp-centred-window): the resolve shadows the pixels the trace answered for. The
    // tests below then hold for them again: where it answered, the trace changed none of their inputs.
    uvec2 stored = uvec2(0u);
    if (resolve && live) {
        stored = imageLoad(lamp_answers, px).xy;
        live = uintBitsToFloat(stored.x) >= 0.0;
    }
#endif
"""),
        (r"""    if (live) {
        n = surfaceNormal(uv, P);
""",
         r"""    if (live) {
#ifdef CENTRED
        if (!resolve || resolve_normal) // bbport (r60_lamp-centred-window): the resolve weighs no lamp
#endif
        n = surfaceNormal(uv, P);
"""),
        (r"""    }
    live = live && wsum > 0.0;

""",
         r"""    }
#ifdef CENTRED
    // bbport (r60_lamp-centred-window): the resolve listed no tile (wsum 0); its strongest lamp is the
    // one the trace found
    live = live && (resolve || wsum > 0.0);
    if (resolve) {
        top_at = live ? (stored.y & 0xFFFFu) << 4u : 0u;
    }
#else
    live = live && wsum > 0.0;
#endif

"""),
        (r"""        // (averaging: see above)
    } else if (group_trace != 0u) {
""",
         r"""        // (averaging: see above)
#ifdef CENTRED
    } else if (resolve) {
        // bbport (r60_lamp-centred-window): the answer the trace's rays gave (a block's answer:
        // the trace took it, CAST_TAKEN)
        ratio = uintBitsToFloat(stored.x);
#ifdef HALF
        half_why = unpackHalf2x16(stored.y).y < -4.5 ? HALF_TAKEN : HALF_FIRST_PIXEL;
#endif
#endif
    } else if (group_trace != 0u) {
"""),
        (r"""    //    free of it.
    const float answer = ratio; // what this frame's rays said (view 1)
""",
         r"""    //    free of it.
    //  - bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 (word 0 bits 21 and 22, the
    //    builds made with CENTRED) centres the window on every pixel: the pass that averages runs
    //    as a trace (MODE_TRACE: the rays, stored in lamp_answers) and a resolve (MODE_RESOLVE: the
    //    rest, with the 5x5 answers read from a 12x12 tile of lamp_answers), so a pixel's bound,
    //    swing and vote depend on the answers at its own 5x5 neighbourhood only, wherever the
    //    workgroups' rims lie: meant to leave none of the window's squares (not measured). The
    //    half-resolution build still shares the answers of 3x3 blocks that agree (HalfAnswer) and
    //    copies a taken block's history and follow state, as with 0 and 1. Every use of the window
    //    above holds as with value 1 (the soft follow's swing included, and the vote with
    //    BB_LAMP_SHADOW_FOLLOW_SOFT=0). In the second half-resolution pass the window also holds
    //    the first pass's answers at the pixels (2x, 2y) (value 1's could not reach them).
    const float answer = ratio; // what this frame's rays said (view 1)
"""),
        (r"""        }
        group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
        group_cast[gl_LocalInvocationIndex] = blocker;
        barrier();
""",
         r"""        }
#ifdef CENTRED
        if (trace_only) {
            // bbport (r60_lamp-centred-window): the trace stores this frame's answer, the cast code
            // (castEvidence: what the window reads of blocker, and e) and the strongest lamp, and
            // is done: the resolve does the rest once every workgroup's answers are stored. (The
            // whole workgroup returns here: no barrier is left to reach.)
            float code = CAST_FREE;
            if (live && top_at != 0u && top_left >= 0.0) {
                const bool near = top_left < word(history_at + 32u);
                if (top_step > 0.0) {
                    code = near ? CAST_NEAR : blocker;
                } else {
                    code = near ? CAST_NEAR_STILL : CAST_FAR_STILL;
                }
            }
#ifdef HALF
            if (live && half_why == HALF_TAKEN) {
                code = CAST_TAKEN;
            }
            if (live || !fill || ((px.x | px.y) & 1) != 0) { // (not over the first pass's answer)
                storeAnswer(px, live ? answer : -1.0, code, live ? top_at : 0u);
            }
            if (live) {
                HalfCount(first, group_trace == 0u ? (first ? 3u : 7u)
                                                   : (first ? 1u : (half_why == HALF_TAKEN ? 4u : 5u)),
                          half_why);
            }
#else
            storeAnswer(px, live ? answer : -1.0, code, live ? top_at : 0u);
#endif
            return;
        }
        if (resolve) {
            // bbport (r60_lamp-centred-window): the 5x5 answers around every pixel of the workgroup
            loadTile(group_lo, resolve_apart);
        } else {
            group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
            group_cast[gl_LocalInvocationIndex] = blocker;
        }
#else
        group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
        group_cast[gl_LocalInvocationIndex] = blocker;
#endif
        barrier();
"""),
        (r"""        float count = 0.0, sum = 0.0, sum2 = 0.0, near_n = 0.0, far_n = 0.0, swing = 0.0;
        if (t_window || !t_follow_soft) {
""",
         r"""        float count = 0.0, sum = 0.0, sum2 = 0.0, near_n = 0.0, far_n = 0.0, swing = 0.0;
#ifdef CENTRED
        if (resolve) {
            // bbport (r60_lamp-centred-window): the 5x5 answers centred on the pixel, from the
            // tile (cell (2, 2) is the workgroup's first pixel), in the same order wherever the
            // workgroup's rim lies: so a pixel's window, and what it binds, is that of its own
            // neighbourhood only, and moves with it. (t_window is set with bit 22: the bound, the
            // swing and the vote below take it as they took the confined one.) A cast code of a
            // lamp that stands (-3, -4) or of a taken block (-5) counts as neither near nor far,
            // as its blocker -1 did.
            const ivec2 own = ivec2(gl_LocalInvocationID.xy) + 2;
            for (int y = -2; y <= 2; ++y) {
                for (int x = -2; x <= 2; ++x) {
                    const int i = (own.y + y) * TILE_SIDE + own.x + x;
                    const float a = tile_answer[i];
                    if (a >= 0.0) {
                        count += 1.0;
                        sum += a;
                        sum2 += a * a;
                        if (top_step > 0.0) {
                            const float c = tile_cast[i];
                            if (c >= 0.0) {
                                far_n += 1.0;
                                swing += c;
                            } else if (c < -1.5 && c > -2.5) {
                                near_n += 1.0;
                            }
                        }
                    }
                }
            }
        } else
#endif
        if (t_window || !t_follow_soft) {
"""),
        (r"""            }
            const bool two = top_moved != vec3(0.0);
""",
         r"""            }
#ifdef CENTRED
            if (resolve) { // bbport (r60_lamp-centred-window): the trace's ray, in its cast code
                e = castEvidence(unpackHalf2x16(stored.y).y);
            }
#endif
            const bool two = top_moved != vec3(0.0);
"""),
    ],
    TUNE: [
        (r"""namespace Vulkan {

""",
         r"""namespace Vulkan {

/// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW when it is not set: 0 the pixel's own
/// last frames, 1 the 5x5 window confined to the 8x8 workgroup (r57, as before), 2 the window
/// centred on every pixel (one more dispatch, see LampShadowTune::window_centred). The one line to
/// change to make 2 the default; tests/test_lamp_shadow_tune.cpp follows it, and the torch lab's
/// default runs (tests/test_rt_shadows.cpp --lamps) then run value 2. 0 as the default also
/// needs the tune test's r57 asserts changed (they hold for a default with the window: 1 or 2).
inline constexpr std::uint32_t LampWindowDefault = 1;
static_assert(LampWindowDefault <= 2, "BB_LAMP_SHADOW_WINDOW has the values 0, 1 and 2");

"""),
        (r"""                                 ///< vote of the 5x5 answers around the pixel (r42)
    bool window = true;          ///< bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW: 1 (the default):
                                 ///< the history is bound by the 5x5 answers around the pixel and
""",
         r"""                                 ///< vote of the 5x5 answers around the pixel (r42)
    bool window = LampWindowDefault >= 1; ///< bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW: 1:
                                 ///< the history is bound by the 5x5 answers around the pixel and
"""),
        (r"""                                 ///< BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap keep the
                                 ///< window either way (they have no per-pixel form)
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
""",
         r"""                                 ///< BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap keep the
                                 ///< window either way (they have no per-pixel form).
                                 ///< bbport (r60_lamp-centred-window): 2 is 1 with window_centred
    bool window_centred = LampWindowDefault == 2; ///< bbport (r60_lamp-centred-window):
                                 ///< BB_LAMP_SHADOW_WINDOW=2 (with window): the 5x5 window is centred
                                 ///< on every pixel, wherever the workgroup's rim lies, meant to leave
                                 ///< none of its squares and to bind as the window of 1 does (not
                                 ///< measured). The pass that
                                 ///< averages runs as two dispatches (a trace, a resolve; four at
                                 ///< half resolution) with one image more, 8 bytes a pixel
                                 ///< (PointShadow::Flush). Read at start only (the pipelines are
                                 ///< picked then)
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
"""),
        (r"""// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used), bit 21 the
// window (bbport r57_lamp-window, LampTuneWindow). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
""",
         r"""// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used), bit 21 the
// window (bbport r57_lamp-window, LampTuneWindow), bit 22 the centred window (bbport
// r60_lamp-centred-window, LampTuneCentred; only with bit 21). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
"""),
        (r"""inline constexpr std::uint32_t LampTuneWindow = 1u << 21;     // bbport (r57_lamp-window)
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
""",
         r"""inline constexpr std::uint32_t LampTuneWindow = 1u << 21;     // bbport (r57_lamp-window)
inline constexpr std::uint32_t LampTuneCentred = 1u << 22;    // bbport (r60_lamp-centred-window)
// (Bit 22 is free: it is none of the bits above, the view's field, 12-17 or 20-21.)
static_assert((LampTuneCentred & (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft |
                                  LampTuneWindow | (7u << LampTuneViewShift) | (0x3Fu << 12))) == 0);
/// bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW as a number, 0 to 2.
inline constexpr std::uint32_t LampWindowValue(const LampShadowTune& tune) {
    return tune.window ? (tune.window_centred ? 2u : 1u) : 0u;
}
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
"""),
        (r"""    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
    tune.window = Whole(get, "BB_LAMP_SHADOW_WINDOW", tune.window ? 1u : 0u, 1u) != 0; // r57
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
""",
         r"""    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
    // r57; r60_lamp-centred-window: 2 the centred window (3 or more: 2, below 0: 0)
    const std::uint32_t window = Whole(get, "BB_LAMP_SHADOW_WINDOW", LampWindowValue(tune), 2u);
    tune.window = window >= 1;
    tune.window_centred = window == 2;
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
"""),
        (r"""                                (tune.follow_soft ? LampTuneFollowSoft : 0u) | // bbport (r52_follow-soft)
                                (tune.window ? LampTuneWindow : 0u);           // bbport (r57_lamp-window)
    return {flags,
""",
         r"""                                (tune.follow_soft ? LampTuneFollowSoft : 0u) | // bbport (r52_follow-soft)
                                (tune.window ? LampTuneWindow : 0u) |          // bbport (r57_lamp-window)
                                (tune.window && tune.window_centred ? LampTuneCentred : 0u); // bbport (r60)
    return {flags,
"""),
    ],
    CPP: [
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r32_lamp-half)
// bbport (r60_lamp-centred-window): the builds of BB_LAMP_SHADOW_WINDOW=2
#include "video_core/host_shaders/point_shadow_ray_centred_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
"""),
        (r"""constexpr u64 HalfOffBit = 72057594037927936ull;
// bbport (r44_half-area-lamp): set: a pass at half resolution has point lamps without a history,
""",
         r"""constexpr u64 HalfOffBit = 72057594037927936ull;
// bbport (r60_lamp-centred-window): two more bits of the same word, read only by the builds made
// with CENTRED (point_shadow_ray.comp MODE_TRACE, MODE_RESOLVE): the pass that averages runs as a
// trace, which stores every pixel's answer in `answers`, and a resolve, which centres the ghost
// clamp's 5x5 window on every pixel. Single bits below the tuning words' place, none taken.
constexpr u32 ModeTrace = 32, ModeResolve = 64;
static_assert(ModeResolve < 1u << TuneAtShift &&
              ((ModeTrace | ModeResolve) & (ModeApart | ModeRepair | ModeHalfFirst | ModeHalfFill |
                                            ModeHalfCount)) == 0);
// One texel a pixel: the answer's float bits and the cast code (a half float) beside the strongest
// lamp's record / 16 in 16 bits. A storage format every Vulkan device has: 8 bytes a pixel.
constexpr auto AnswersFormat = vk::Format::eR32G32Uint;
// The records start on 16-word steps (after ConstantWords, LightWords each) below 2^20.
static_assert(ConstantWords % 16 == 0 && LightWords == 16 && DataWords <= 1u << 20);
// bbport (r44_half-area-lamp): set: a pass at half resolution has point lamps without a history,
"""),
        (r"""    }
    // bbport (r52_follow-soft): bindings 9 and 10, the follow state
    if (rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
""",
         r"""    }
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2: the build with the centred window
    // and binding 11, its answers image. It cannot be made: the window of 1, said in the log.
    centred = tune.window && tune.window_centred;
    if (centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_CENTRED_COMP, "Ray traced lamps", true)) {
        std::printf("Ray traced lamps (r60): the centred window's pass could not be made: "
                    "BB_LAMP_SHADOW_WINDOW=1\n");
        centred = false;
        tune.window_centred = false;
    }
    // bbport (r52_follow-soft): bindings 9 and 10, the follow state
    if (!centred && rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
"""),
        (r"""                    tune.follow_soft ? "yes" : "no");
        // bbport (r57_lamp-window)
        const char* const window_what =
            tune.window        ? "the 5x5 answers of the workgroup bound the history"
            : tune.follow_soft ? "at full resolution no answer of another pixel reaches a pixel (the half-resolution "
""",
         r"""                    tune.follow_soft ? "yes" : "no");
        // bbport (r57_lamp-window); r60_lamp-centred-window: the window of 2
        const char* const window_what =
            tune.window && centred ? "the 5x5 answers centred on every pixel bound the history (2, the centred "
                                     "window: see the r60 line)"
            : tune.window      ? "the 5x5 answers of the workgroup bound the history"
            : tune.follow_soft ? "at full resolution no answer of another pixel reaches a pixel (the half-resolution "
"""),
        (r"""                    tune.window ? "yes" : "no", window_what);
    }
""",
         r"""                    tune.window ? "yes" : "no", window_what);
        // bbport (r60_lamp-centred-window): what the value 2 costs, said whether it is on or not
        std::printf("Ray traced lamps (r60): centred window %s (BB_LAMP_SHADOW_WINDOW=2; the default is %u): "
                    "the 5x5 answers that bound the history and cap its frames are centred on every "
                    "pixel, not confined to its 8x8 workgroup, meant to leave no squares fixed to the "
                    "screen behind moving shadows (not measured; the half-resolution build still shares "
                    "agreeing 3x3 blocks and copies a taken block's history); costs one dispatch and "
                    "barrier more (two at half resolution) and one image of 8 bytes a pixel (16.6 MB at "
                    "1920x1080, 66.4 MB at 3840x2160), made only with 2\n",
                    centred ? "yes" : "no", unsigned(LampWindowDefault));
    }
"""),
        (r"""    using enum vk::DescriptorType;
    if (ray_pipeline &&
        EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                            eStorageImage, eStorageImage, eStorageImage,
                            eAccelerationStructureKHR, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
                           sizeof(Push), POINT_SHADOW_RAY_HALF_COMP,
                           "Ray traced lamps (half resolution)", true)) {
        half_counts = std::make_unique<VideoCore::Buffer>(
""",
         r"""    using enum vk::DescriptorType;
    // bbport (r60_lamp-centred-window): with the centred window (Ready), its build: binding 13
    // its answers image. If it cannot be made, the plain build (the half-resolution pass then has
    // the window of 1 and does not split; the full-resolution pass keeps 2), said in the log.
    half_centred = ray_pipeline && centred &&
                   EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                                      {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                       eStorageImage, eStorageImage, eStorageImage,
                                       eAccelerationStructureKHR, eStorageImage, eStorageImage,
                                       eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                                       eStorageImage},
                                      sizeof(Push), POINT_SHADOW_RAY_HALF_CENTRED_COMP,
                                      "Ray traced lamps (half resolution)", true);
    if (ray_pipeline && centred && !half_centred) {
        std::printf("Ray traced lamps (r60): the centred window's half-resolution pass could not be made: "
                    "the half-resolution pass has the window of 1 (BB_LAMP_SHADOW_WINDOW=1), the "
                    "full-resolution pass keeps 2\n");
    }
    const bool made =
        ray_pipeline &&
        (half_centred || EffectPass::Create(instance, half_set_layout, half_layout, half_pipeline,
                                            {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                             eStorageImage, eStorageImage, eStorageImage,
                                             eAccelerationStructureKHR, eStorageImage, eStorageImage,
                                             eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
                                            sizeof(Push), POINT_SHADOW_RAY_HALF_COMP,
                                            "Ray traced lamps (half resolution)", true));
    if (made) {
        half_counts = std::make_unique<VideoCore::Buffer>(
"""),
        (r"""            history_written = false; // the new images hold nothing: this frame's history starts again
        }
    }
""",
         r"""            history_written = false; // the new images hold nothing: this frame's history starts again
        }
        // bbport (r60_lamp-centred-window): the centred window's answers (binding 11 of the full
        // build, which every ray traced pass binds), one image of 8 bytes a pixel. Made here, at
        // this pass's size, only when there is none: without room for it, no pass. Only the pass
        // that splits uses it and gives it its own size (below, once `split` is known), so a
        // pass of another size beside it (two ray passes of different size a frame) does not
        // make it anew. Nothing is read from it that the pass's trace did not write first
        // (point_shadow_ray.comp loadTile), so it is not cleared.
        if (centred && !answers.image) {
            if (!EffectPass::HasRoom(instance, 8ull * width * height)) {
                data.clear();
                return;
            }
            if (EnsureImage(answers, width, height, AnswersFormat, "Ray traced lamp answers")) {
                answers_laid_out = false;
                std::printf("Ray traced lamps (r60): the centred window's answers, %ux%u, %.1f MB\n", width,
                            height, 8.0 * width * height / 1e6);
            }
        }
    }
"""),
        (r"""    std::array<bool, 2> follow_lay_out{}; // bbport (r52_follow-soft)
    // (history_ours: above.)
""",
         r"""    std::array<bool, 2> follow_lay_out{}; // bbport (r52_follow-soft)
    // bbport (r60_lamp-centred-window): the pass runs as a trace and a resolve (the shader takes
    // the same decision: the pass averages, the centred window, not view 2 or 3)
    bool split = false;
    // (history_ours: above.)
"""),
        (r"""        u32 flags = blend ? HistoryWrite | HistoryBlend : lamp_reuse ? HistoryWrite : 0u;
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
""",
         r"""        u32 flags = blend ? HistoryWrite | HistoryBlend : lamp_reuse ? HistoryWrite : 0u;
        // bbport (r60_lamp-centred-window): the half-resolution pass splits only with its centred
        // build (HalfReady may have made the plain one)
        split = centred && (!use_half || half_centred) && blend && pass_tune.view != 2 && pass_tune.view != 3;
        constexpr std::array<float, 12> Identity{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
"""),
        (r"""    }
    if (use_rays) {
""",
         r"""    }
    // bbport (r60_lamp-centred-window): the pass that splits gives the answers image its size.
    // Without room for that, this pass runs whole (the shader then takes the window of 1), said
    // once in the log.
    if (split && (answers.width != width || answers.height != height)) {
        if (EffectPass::HasRoom(instance, 8ull * width * height) &&
            EnsureImage(answers, width, height, AnswersFormat, "Ray traced lamp answers")) {
            answers_laid_out = false;
            std::printf("Ray traced lamps (r60): the centred window's answers, %ux%u, %.1f MB\n", width, height,
                        8.0 * width * height / 1e6);
        } else {
            split = false;
            if (!std::exchange(answers_short, true)) {
                std::printf("Ray traced lamps (r60): no room for the centred window's answers at %ux%u: the "
                            "pass runs with the window of 1 until there is\n", width, height);
            }
        }
    }
    if (split) {
        answers_short = false;
    }
    if (use_rays) {
"""),
        (r"""        use_rays ? vk::Image(follow[1].image) : vk::Image{}};
    const auto device = instance.GetDevice();
""",
         r"""        use_rays ? vk::Image(follow[1].image) : vk::Image{}};
    // bbport (r60_lamp-centred-window): the centred window's answers (null without it)
    const bool with_answers = use_rays && centred;
    const bool answers_lay_out = with_answers && !std::exchange(answers_laid_out, true);
    const vk::ImageView answers_view = with_answers ? *answers.view : vk::ImageView{};
    const vk::Image answers_image = with_answers ? vk::Image(answers.image) : vk::Image{};
    const auto device = instance.GetDevice();
"""),
        (r"""         follow_prev, follow_cur, follow_images, follow_lay_out, // bbport (r52_follow-soft)
         // bbport (r32_lamp-half): null unless this pass runs in two halves
""",
         r"""         follow_prev, follow_cur, follow_images, follow_lay_out, // bbport (r52_follow-soft)
         with_answers, answers_lay_out, answers_view, answers_image, split, // bbport (r60)
         half_with_answers = with_answers && use_half && half_centred,     // bbport (r60)
         // bbport (r32_lamp-half): null unless this pass runs in two halves
"""),
        (r"""                    .image = follow_images[i],
                    .subresourceRange = ColorRange,
""",
         r"""                    .image = follow_images[i],
                    .subresourceRange = ColorRange,
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            if (answers_lay_out) { // bbport (r60_lamp-centred-window): on its first use
                const vk::ImageMemoryBarrier2 to_general{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstStageMask = Compute,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = answers_image,
                    .subresourceRange = ColorRange,
"""),
        (r"""            const vk::DescriptorImageInfo follow_cur_info{{}, follow_cur, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 11> ray_writes{
                writes[0], writes[1], writes[2], writes[3], writes[4], writes[5],
""",
         r"""            const vk::DescriptorImageInfo follow_cur_info{{}, follow_cur, vk::ImageLayout::eGeneral};
            // bbport (r60_lamp-centred-window): with the centred window's builds, binding 11 too
            const vk::DescriptorImageInfo answers_info{{}, answers_view, vk::ImageLayout::eGeneral};
            const u32 ray_count = with_answers ? 12u : 11u;
            const std::array<vk::WriteDescriptorSet, 12> ray_writes{
                writes[0], writes[1], writes[2], writes[3], writes[4], writes[5],
"""),
        (r"""                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_cur_info}};
            // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1: pixel (2x, 2y) of each 2x2 block
""",
         r"""                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_cur_info},
                vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &answers_info}};
            // bbport (r60_lamp-centred-window): between the trace and the resolve (and after the
            // resolve of the half-resolution build's first pass): what one dispatch wrote, the
            // next reads.
            const auto between = [&cmdbuf] {
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            };
            // bbport (r32_lamp-half): BB_LAMP_SHADOW_HALF=1: pixel (2x, 2y) of each 2x2 block
"""),
        (r"""                const vk::DescriptorBufferInfo count_info{half_count_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 13> half_writes{
                    ray_writes[0], ray_writes[1], ray_writes[2], ray_writes[3], ray_writes[4],
""",
         r"""                const vk::DescriptorBufferInfo count_info{half_count_buffer, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 14> half_writes{
                    ray_writes[0], ray_writes[1], ray_writes[2], ray_writes[3], ray_writes[4],
"""),
        (r"""                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_cur_info}};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipe);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_pipe_layout, 0,
                                            half_writes);
                push.first_light = table;
""",
         r"""                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_cur_info},
                    // bbport (r60_lamp-centred-window): the centred window's answers
                    vk::WriteDescriptorSet{.dstBinding = 13, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &answers_info}};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipe);
                cmdbuf.pushDescriptorSetKHR(
                    vk::PipelineBindPoint::eCompute, half_pipe_layout, 0,
                    vk::ArrayProxy<const vk::WriteDescriptorSet>(half_with_answers ? 14u : 13u, half_writes.data()));
                push.first_light = table;
"""),
        (r"""                                 (half_count ? ModeHalfCount : 0u);
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
""",
         r"""                                 (half_count ? ModeHalfCount : 0u);
                // bbport (r60_lamp-centred-window): split, each half as a trace and a resolve; the
                // second half's trace reads the block answers and the history the first half's
                // resolve wrote (HalfAnswer, a taken block's copy), so four dispatches. The
                // resolves count nothing (each pixel is counted once, by its trace).
                const u32 trace = split ? ModeTrace : 0u;
                const u32 resolve = (mode & ~ModeHalfCount) | ModeResolve;
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst | trace);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
"""),
        (r"""                                              vk::AccessFlagBits2::eShaderWrite);
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
""",
         r"""                                              vk::AccessFlagBits2::eShaderWrite);
                if (split) {
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFirst);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                    between();
                }
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill | trace);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
"""),
        (r"""                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                const vk::MemoryBarrier2 half_after{
""",
         r"""                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                if (split) {
                    between();
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFill);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
                const vk::MemoryBarrier2 half_after{
"""),
        (r"""            if (use_rays) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, ray_writes);
            } else {
""",
         r"""            if (use_rays) {
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                            vk::ArrayProxy<const vk::WriteDescriptorSet>(ray_count, ray_writes.data()));
            } else {
"""),
        (r"""                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                batch.clear();
""",
         r"""                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                if (split) { // bbport (r60_lamp-centred-window): the trace, then the resolve
                    const u32 mode = std::bit_cast<u32>(push.thickness_m);
                    push.thickness_m = std::bit_cast<float>(mode | ModeTrace);
                    cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                    between();
                    push.thickness_m = std::bit_cast<float>(mode | ModeResolve);
                    cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                }
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                batch.clear();
"""),
    ],
    HDR: [
        (r"""    std::array<bool, 2> follow_laid_out{};
    std::array<float, 12> last_view{}, pending_view{};
""",
         r"""    std::array<bool, 2> follow_laid_out{};
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 and its builds made (Ready): the
    // pass that averages runs as a trace and a resolve (point_shadow_ray.comp MODE_TRACE,
    // MODE_RESOLVE), with every pixel's answer in `answers` (RG32UI, 8 bytes a pixel; made by
    // Flush only while `centred`, sized by the pass that splits, laid out on first use, never
    // cleared). half_centred: HalfReady made the half-resolution build's centred form (else its
    // plain one, and the half-resolution pass does not split). answers_short: a pass that would
    // split had no room for the image (logged once).
    bool centred = false;
    bool half_centred = false;
    OwnImage answers;
    bool answers_laid_out = false;
    bool answers_short = false;
    std::array<float, 12> last_view{}, pending_view{};
"""),
    ],
    CMAKE: [
        (r"""add_host_shader(point_shadow_ray.comp point_shadow_ray_half_comp HALF=1)
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
""",
         r"""add_host_shader(point_shadow_ray.comp point_shadow_ray_half_comp HALF=1)
# bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds (trace and resolve); the
# two above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_comp CENTRED=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_comp HALF=1 CENTRED=1)
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
"""),
    ],
    DOC: [
        (r"""  no memory or binding change.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
""",
         r"""  no memory or binding change.
- **Centred lamp history window, to try (r60).** `BB_LAMP_SHADOW_WINDOW=2`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window_centred`; the default is `LampWindowDefault` in
  `lamp_shadow_tune.h`, 1), sets tuning word 0 bits 21 and 22 (`LampTuneWindow`, `LampTuneCentred`).
  0 and 1 are the passes of r57, word for word (their shader builds are unchanged). With 2 the ray
  traced lamp pass is made from the builds `point_shadow_ray_centred_comp` and
  `point_shadow_ray_half_centred_comp` (`CENTRED=1`), and the pass that averages runs as a trace
  (`MODE_TRACE`: the rays; every pixel's answer, cast code and strongest lamp go to one RG32UI image,
  binding 11, or 13 at half resolution) and a resolve (`MODE_RESOLVE`: no rays; it loads a 12x12 tile
  of that image, the workgroup and two pixels on every side, and does the history blend with the 5x5
  window centred on every pixel). The bound, the soft follow's swing and, with
  `BB_LAMP_SHADOW_FOLLOW_SOFT=0`, the vote all take the centred window, so a pixel's result depends on
  the answers at its own 5x5 neighbourhood only and not on where the 8x8 workgroup's rim lies. It is
  meant to leave no squares fixed to the screen and to cut the wake of a moving caster as 1 does;
  neither is measured yet. The half-resolution build still shares the answers of 3x3 blocks that
  agree and copies a taken block's history, as with 0 and 1. The half-resolution build runs four
  dispatches (trace and resolve of each half: the second half's trace reads what the first half's
  resolve wrote); its second half's window also takes the first half's answers at the pixels
  (2x, 2y), so at half resolution 2 differs from 1 in two ways (centring, and those answers). Views 2
  and 3 and passes that do not average are not split. Cost (estimate from memory traffic, not
  measured): 8 bytes a pixel more memory (16.6 MB at 1920x1080, 66.4 MB at 3840x2160), made only with
  2; one dispatch and barrier more (two at half resolution); the trace writes 8 bytes for every pixel
  of the pass, and in a workgroup with a lamp tile the resolve reads about 28 bytes a pixel more (the
  answers, depth and the light targets again; the tile's overlap mostly from L2): at most about 36
  bytes a pixel, 75 MB a frame at 1920x1080, about 0.05 to 0.12 ms on an RTX 4090 over the pass's 0.30 to 0.36 ms. No
  experiment bit gates it, so the switch does not change it.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
"""),
    ],
    TEST: [
        (r"""// bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW and its bit in word 0.
#include <array>
""",
         r"""// bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW and its bit in word 0.
// bbport (r60_lamp-centred-window): its value 2 (bit 22), and a CPU model of the ghost clamp's
// 5x5 statistic: centred on every pixel it does not change as the workgroups' grid moves.
#include <array>
"""),
        (r"""#include <utility>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
""",
         r"""#include <utility>
#include <vector>
#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
"""),
        (r"""}
} // namespace
""",
         r"""}

// bbport (r60_lamp-centred-window): word 0's window bits of the default (LampWindowDefault), so
// that the asserts below hold whichever of 1 and 2 is the default.
constexpr std::uint32_t DefaultWindowBits =
    (LampWindowDefault >= 1 ? LampTuneWindow : 0u) | (LampWindowDefault == 2 ? LampTuneCentred : 0u);

// bbport (r60_lamp-centred-window): a CPU model of the ghost clamp's 5x5 statistic (count, sum,
// sum of squares of the answers, point_shadow_ray.comp). It is a hand copy of the shader's index
// arithmetic (loadTile and the centred loop), not a test of the shader: a fault made in the
// shader alone is caught only by a GPU run (rt-shadow-test --lamps). What it checks: that tile
// arithmetic, written as the shader has it, gives every pixel the statistic of its own 5x5
// neighbourhood, which Direct works out on its own (its own bounds from the rect and the
// screen, its own test for an answer). Not modelled: the half-resolution fill pass (its window
// over the first pass's answers at even pixels, and its trace not storing over them), workgroups
// without a tile, the cast codes beside the answers (CastCode below checks their packing alone).
//
// The answers the trace stored, by pass pixel: pass pixel (x, y) is full pixel (apart x, apart y),
// apart 1, or 2 in the half-resolution build's first pass. Below 0: none. size and rect in full
// pixels, as the push block has them (the rect may reach past the screen).
struct Field {
    int apart = 1;
    std::array<int, 2> size{};               // the screen
    std::array<int, 4> rect{};               // the pass's rect
    int pw = 0, ph = 0;                      // pass pixels on the screen: (size + apart - 1) / apart
    int w = 0, h = 0;                        // pass pixels stored: more, so a read past the screen
                                             // finds an answer (and a missed clip shows)
    std::vector<float> answer;               // w * h
};
struct Stat {
    float count = 0.0f, sum = 0.0f, sum2 = 0.0f;
    bool operator==(const Stat&) const = default;
};
// The statistic of pass pixel (x, y) from its own 5x5 neighbourhood, in the shader's order, on
// its own: a neighbour counts where it lies in the rect and on the screen (as bounds on pass
// pixels, rounded up from the full pixels' bounds) and has an answer.
Stat Direct(const Field& f, int x, int y) {
    const auto up = [&](int v) { return (v + f.apart - 1) / f.apart; }; // the first pass pixel at or past v
    const int x0 = up(f.rect[0]), y0 = up(f.rect[1]);
    const int x1 = std::min(up(f.rect[2]), up(f.size[0])), y1 = std::min(up(f.rect[3]), up(f.size[1]));
    Stat s;
    for (int dy = -2; dy <= 2; ++dy) {
        for (int dx = -2; dx <= 2; ++dx) {
            const int nx = x + dx, ny = y + dy;
            if (nx < x0 || ny < y0 || nx >= x1 || ny >= y1) {
                continue;
            }
            const float a = f.answer[std::size_t(ny * f.w + nx)];
            if (a < 0.0f) {
                continue;
            }
            s.count += 1.0f;
            s.sum += a;
            s.sum2 += a * a;
        }
    }
    return s;
}
// BB_LAMP_SHADOW_WINDOW=2, as the shader: loadTile (full pixel q = lo + apart * (cell - 2), "no
// answer" outside the rect or the screen) and the centred loop (cell (lid + 2 + d), counted where
// a >= 0). lo: the workgroup's first full pixel; (lx, ly): the invocation.
Stat Centred(const Field& f, int lox, int loy, int lx, int ly) {
    std::array<float, 144> tile{};
    for (std::uint32_t i = 0; i < 144u; ++i) {
        const int qx = lox + f.apart * (int(i % 12u) - 2), qy = loy + f.apart * (int(i / 12u) - 2);
        float a = -1.0f;
        if (qx >= f.rect[0] && qy >= f.rect[1] && qx < f.rect[2] && qy < f.rect[3] && qx < f.size[0] &&
            qy < f.size[1]) {
            a = f.answer[std::size_t((qy / f.apart) * f.w + qx / f.apart)];
        }
        tile[i] = a;
    }
    Stat s;
    for (int y = -2; y <= 2; ++y) {
        for (int x = -2; x <= 2; ++x) {
            const float a = tile[std::size_t((ly + 2 + y) * 12 + lx + 2 + x)];
            if (a >= 0.0f) {
                s.count += 1.0f;
                s.sum += a;
                s.sum2 += a * a;
            }
        }
    }
    return s;
}
// BB_LAMP_SHADOW_WINDOW=1: the window moved in from the workgroup's rim (around_lo), over the
// workgroup's own answers only (its pixels in the rect and on the screen).
Stat Confined(const Field& f, int gx, int gy, int lx, int ly) {
    const int ax = std::clamp(lx - 2, 0, 3), ay = std::clamp(ly - 2, 0, 3);
    Stat s;
    for (int y = ay; y < ay + 5; ++y) {
        for (int x = ax; x < ax + 5; ++x) {
            const int px = gx + x, py = gy + y, fx = f.apart * px, fy = f.apart * py;
            if (fx < f.rect[0] || fy < f.rect[1] || fx >= f.rect[2] || fy >= f.rect[3] || fx >= f.size[0] ||
                fy >= f.size[1]) {
                continue;
            }
            const float a = f.answer[std::size_t(py * f.w + px)];
            if (a >= 0.0f) {
                s.count += 1.0f;
                s.sum += a;
                s.sum2 += a * a;
            }
        }
    }
    return s;
}
// Every pass pixel's statistic with the workgroups' origins shifted by `shift` pass pixels (as the
// picture moves under the fixed grid of 8x8 workgroups); centred: value 2, else value 1.
std::vector<Stat> Statistic(const Field& f, int shift, bool centred) {
    std::vector<Stat> out(std::size_t(f.pw * f.ph));
    for (int y = 0; y < f.ph; ++y) {
        for (int x = 0; x < f.pw; ++x) {
            const int gx = (x - shift + 8) / 8 * 8 - 8 + shift, gy = (y - shift + 8) / 8 * 8 - 8 + shift;
            out[std::size_t(y * f.pw + x)] = centred ? Centred(f, f.apart * gx, f.apart * gy, x - gx, y - gy)
                                                     : Confined(f, gx, gy, x - gx, y - gy);
        }
    }
    return out;
}

// bbport (r60_lamp-centred-window): the cast code's way through the answers image, written from
// the GLSL rules (not from the shader's text): packHalf2x16 puts the code, as a half float, in the
// high 16 bits (round to nearest even here; the code's classes do not depend on the rounding),
// the record / 16 goes in the low 16 bits, unpackHalf2x16(...).y reads the code back.
std::uint16_t ToHalf(float v) {
    const std::uint32_t b = std::bit_cast<std::uint32_t>(v);
    const std::uint32_t sign = (b >> 16) & 0x8000u;
    const std::uint32_t mag = b & 0x7FFFFFFFu;
    const int exp = int(mag >> 23) - 127 + 15;
    if (mag == 0u || exp < -10) {
        return std::uint16_t(sign);
    }
    assert(exp < 31); // the codes lie within -5 and 64
    std::uint32_t man = (mag & 0x7FFFFFu) | 0x800000u;
    const int shift = exp >= 1 ? 13 : 14 - exp;
    std::uint32_t h = man >> shift;
    const std::uint32_t rest = man & ((1u << shift) - 1u), halfway = 1u << (shift - 1);
    if (rest > halfway || (rest == halfway && (h & 1u) != 0u)) {
        ++h;
    }
    if (exp >= 1) {
        h = (std::uint32_t(exp) << 10) + (h - 0x400u); // (a carry out of the mantissa moves the exponent)
    }
    return std::uint16_t(sign | h);
}
float FromHalf(std::uint16_t h) {
    const int exp = (h >> 10) & 31;
    const float man = float(h & 0x3FFu);
    const float v = exp == 0 ? std::ldexp(man, -24) : std::ldexp(1.0f + man / 1024.0f, exp - 15);
    return (h & 0x8000u) != 0u ? -v : v;
}
// What the texel's y holds (storeAnswer) and what is read back of it (the resolve).
std::uint32_t PackCast(float code, std::uint32_t record) {
    const std::uint32_t at = (record & 15u) == 0u && record < (1u << 20) ? record >> 4 : 0u;
    return (std::uint32_t(ToHalf(code)) << 16) | at;
}
float CastOf(std::uint32_t y) { return FromHalf(std::uint16_t(y >> 16)); }
std::uint32_t RecordOf(std::uint32_t y) { return (y & 0xFFFFu) << 4; }
} // namespace
"""),
        (r"""        assert(words.size() == LampTuneWordCount);
        // new weights, view 0, the soft follow (r52), the window (bbport r57_lamp-window)
        assert(words[0] == (1u | LampTuneFollowSoft | LampTuneWindow));
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
""",
         r"""        assert(words.size() == LampTuneWordCount);
        // new weights, view 0, the soft follow (r52), the window (bbport r57_lamp-window; r60: of
        // the default)
        assert(words[0] == (1u | LampTuneFollowSoft | DefaultWindowBits));
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
"""),
        (r"""        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft | LampTuneWindow)); // (r57: the window)
        assert(F(other[9]) == 0.75f);
""",
         r"""        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft | DefaultWindowBits)); // (r57: the window)
        assert(F(other[9]) == 0.75f);
"""),
        (r"""        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft | LampTuneWindow));
    }
""",
         r"""        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft | DefaultWindowBits));
    }
"""),
        (r"""        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(d.window);
""",
         r"""        const LampShadowTune d = Read(std::array<Pair, 0>{});
        static_assert(LampWindowDefault == 1 || LampWindowDefault == 2); // (r60: either has the window)
        assert(d.window);
"""),
        (r"""        again.window = d.window;
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
""",
         r"""        again.window = d.window;
        again.window_centred = d.window_centred; // (r60)
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
"""),
        (r"""                t.window = window;
                t.view = 3;
""",
         r"""                t.window = window;
                t.window_centred = false; // (r60: bit 22 below)
                t.view = 3;
"""),
        (r"""        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
""",
         r"""        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 is the window (bit 21) centred
    // (bit 22); 3 or more is 2, below 0 is 0, text that is no whole number leaves the default
    // (LampWindowDefault). Bit 22 is set only with bit 21, and nothing else of the words moves with
    // it; 0 and 1 give the words they gave before r60. (That the shader reads it is checked by
    // rt-shadow-test --lamps: its lattice block fails when the pictures with 1 and 2 are the same.)
    {
        static_assert(LampTuneCentred == 1u << 22);
        static_assert((LampTuneCentred & (LampTuneWindow | LampTuneFollowSoft | (0x3Fu << 12) |
                                          (7u << LampTuneViewShift) | LampTuneNewWeights |
                                          LampTuneInverseSquare)) == 0);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(LampWindowValue(d) == LampWindowDefault);
        assert(d.window_centred == (LampWindowDefault == 2));
        const LampShadowTune two = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "2"}}});
        assert(two.window && two.window_centred && LampWindowValue(two) == 2u);
        const LampShadowTune one = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "1"}}});
        assert(one.window && !one.window_centred && LampWindowValue(one) == 1u);
        const LampShadowTune zero = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "0"}}});
        assert(!zero.window && !zero.window_centred && LampWindowValue(zero) == 0u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "5"}}})) == 2u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "-1"}}})) == 0u);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "two"}}})) == LampWindowDefault);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "2.5"}}})) == LampWindowDefault);
        assert(LampWindowValue(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", " 2 "}}})) == 2u);
        // The words of 0 and 1 are those of before r60 (bit 21 as r57 had it, no bit 22); 2 adds
        // bit 22 alone.
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const bool soft : {false, true}) {
            for (const std::uint32_t v : {0u, 4u, 6u}) {
                LampShadowTune t0 = zero, t1 = one, t2 = two;
                for (LampShadowTune* t : {&t0, &t1, &t2}) {
                    t->follow_soft = soft;
                    t->view = v;
                }
                const auto w0 = LampTuneWords(t0, true, 0.05f, view.data(), 9u);
                const auto w1 = LampTuneWords(t1, true, 0.05f, view.data(), 9u);
                const auto w2 = LampTuneWords(t2, true, 0.05f, view.data(), 9u);
                assert((w0[0] & (LampTuneWindow | LampTuneCentred)) == 0);
                assert((w1[0] & (LampTuneWindow | LampTuneCentred)) == LampTuneWindow);
                assert((w2[0] ^ w1[0]) == LampTuneCentred && (w1[0] ^ w0[0]) == LampTuneWindow);
                assert(((w2[0] & LampTuneFollowSoft) != 0) == soft && ((w2[0] >> LampTuneViewShift) & 7u) == v);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(w0[k] == w1[k] && w1[k] == w2[k]);
                }
                // r57's word 0, as LampTuneWords made it before r60
                const std::uint32_t r57 = (t1.weights ? LampTuneNewWeights : 0u) | LampTuneInverseSquare |
                                          v << LampTuneViewShift | (soft ? LampTuneFollowSoft : 0u);
                assert(w0[0] == r57 && w1[0] == (r57 | LampTuneWindow));
            }
        }
        // Bit 22 without the window is never written (2 is the window centred, not a window of its own).
        LampShadowTune odd = zero;
        odd.window_centred = true;
        assert((LampTuneWords(odd, false, 0.05f)[0] & (LampTuneWindow | LampTuneCentred)) == 0);
        assert(LampWindowValue(odd) == 0u);
        // Round trip: the value the bits carry reads back as the same knob.
        for (const LampShadowTune& t : {zero, one, two}) {
            const std::uint32_t w = LampTuneWords(t, false, 0.05f)[0];
            const std::uint32_t back = (w & LampTuneWindow) ? ((w & LampTuneCentred) ? 2u : 1u) : 0u;
            assert(back == LampWindowValue(t));
            char text[4] = {char('0' + back), 0, 0, 0};
            const std::array<Pair, 1> env{{{"BB_LAMP_SHADOW_WINDOW", text}}};
            const LampShadowTune again = Read(env);
            assert(LampWindowValue(again) == back && LampTuneWords(again, false, 0.05f) == LampTuneWords(t, false, 0.05f));
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(two) == LampHistoryTail(one) && LampHistoryTail(one) == LampHistoryTail(zero));
    }
    // bbport (r60_lamp-centred-window): the CPU model of the 5x5 statistic (only the tile's index
    // arithmetic: see Field). Fields of answers with holes (no answer), exact 0s and 1s (so a
    // count of "above 0" in place of "0 or more" shows), rects that do not cover the screen, end on
    // even and odd full pixels or reach past the screen (so a missed clip shows); the workgroups'
    // grid shifted by 0 to 7 pass pixels (full pixels 0 to 7; at the half-resolution build's first
    // pass, two apart, full pixels 0 to 14). Value 2 (the 12x12 tile, as point_shadow_ray.comp
    // loadTile and its centred loop index it) gives every pixel the statistic of its own 5x5
    // neighbourhood (Direct), to the bit, at every shift; value 1 (the window confined to the
    // workgroup) does not, and changes with the shift: the squares.
    {
        struct Case {
            std::array<int, 2> size;
            std::array<int, 4> rect;
        };
        constexpr std::array<Case, 4> cases{{{{122, 94}, {6, 10, 115, 88}},
                                             {{121, 93}, {3, 5, 140, 100}},
                                             {{64, 48}, {0, 0, 64, 48}},
                                             {{100, 70}, {17, 9, 58, 66}}}};
        for (const int apart : {1, 2}) {
            for (const Case& c : cases) {
                Field f;
                f.apart = apart;
                f.size = c.size;
                f.rect = c.rect;
                f.pw = (c.size[0] + apart - 1) / apart;
                f.ph = (c.size[1] + apart - 1) / apart;
                f.w = f.pw + 10;
                f.h = f.ph + 10;
                f.answer.resize(std::size_t(f.w * f.h));
                std::uint32_t seed = 12345u + std::uint32_t(apart) + std::uint32_t(c.size[0]);
                std::size_t zeros = 0;
                for (float& a : f.answer) {
                    seed = seed * 747796405u + 2891336453u;
                    const std::uint32_t r = (seed >> 9) & 0x3FFFu;
                    const std::uint32_t kind = r % 5u; // none, 0, 1, or (twice as often) a fraction
                    a = kind == 0u ? -1.0f : kind == 1u ? 0.0f : kind == 2u ? 1.0f : float(r & 0x3FFu) / 1023.0f;
                    zeros += a == 0.0f ? 1 : 0;
                }
                assert(zeros > 100);
                std::vector<Stat> direct(std::size_t(f.pw * f.ph));
                for (int y = 0; y < f.ph; ++y) {
                    for (int x = 0; x < f.pw; ++x) {
                        direct[std::size_t(y * f.pw + x)] = Direct(f, x, y);
                    }
                }
                const auto first1 = Statistic(f, 0, false);
                bool confined_differs = false, confined_moves = false;
                for (int shift = 0; shift < 8; ++shift) {
                    const auto centred = Statistic(f, shift, true);
                    const auto confined = Statistic(f, shift, false);
                    for (std::size_t i = 0; i < direct.size(); ++i) {
                        assert(centred[i] == direct[i]); // bit for bit
                        assert(std::memcmp(&centred[i], &direct[i], sizeof(Stat)) == 0);
                        confined_differs = confined_differs || !(confined[i] == direct[i]);
                        confined_moves = confined_moves || !(confined[i] == first1[i]);
                    }
                }
                assert(confined_differs && confined_moves);
                // A pixel's own answer is always in its window: count >= 1 where it has one and
                // lies in the rect.
                for (int y = 0; y < f.ph; ++y) {
                    for (int x = 0; x < f.pw; ++x) {
                        const int fx = apart * x, fy = apart * y;
                        const bool in = fx >= c.rect[0] && fy >= c.rect[1] && fx < c.rect[2] && fy < c.rect[3];
                        assert(!in || !(f.answer[std::size_t(y * f.w + x)] >= 0.0f) ||
                               direct[std::size_t(y * f.pw + x)].count >= 1.0f);
                    }
                }
            }
        }
    }
    // bbport (r60_lamp-centred-window): the cast code through the answers image (storeAnswer, read
    // back by the resolve): the classes the blend takes from it are those of the ray it stands for.
    // Written from the shader's rules in plain words: blocker "near" (-2 under a moving lamp), "far"
    // (0 or more: the swing), else none; the follow evidence e +1 near, -1 further off, 0 free or no
    // ray to the strongest lamp (a block's answer taken, -5, has none: it copies its block's state).
    {
        struct Want {
            float code;
            bool near, far;
            float e;
        };
        constexpr std::array<Want, 5> fixed{{{-1.0f, false, false, 0.0f},
                                             {-2.0f, true, false, 1.0f},
                                             {-3.0f, false, false, 1.0f},
                                             {-4.0f, false, false, -1.0f},
                                             {-5.0f, false, false, 0.0f}}};
        // What the resolve reads of a code (point_shadow_ray.comp: the centred loop and castEvidence)
        const auto near_of = [](float c) { return c < -1.5f && c > -2.5f; };
        const auto far_of = [](float c) { return c >= 0.0f; };
        const auto evidence = [](float c) {
            if (c >= 0.0f || (c < -3.5f && c > -4.5f)) {
                return -1.0f;
            }
            return c < -1.5f && c > -3.5f ? 1.0f : 0.0f;
        };
        const std::array<std::uint32_t, 4> records{0u, 16u, 48u * 16u, (1u << 20) - 16u};
        for (const std::uint32_t record : records) {
            for (const Want& w : fixed) {
                const std::uint32_t y = PackCast(w.code, record);
                const float c = CastOf(y);
                assert(c == w.code && RecordOf(y) == record);
                assert(near_of(c) == w.near && far_of(c) == w.far && evidence(c) == w.e);
            }
            // The far blocker's swing, 0 to 64: far, e -1, back within half a unit in the last place
            // of a half float (relative 2^-11).
            for (int k = 0; k <= 6400; ++k) {
                const float swing = k == 6400 ? 64.0f : float(k) * 0.01f + float(k % 7) * 1e-4f;
                const std::uint32_t y = PackCast(swing, record);
                const float c = CastOf(y);
                assert(far_of(c) && !near_of(c) && evidence(c) == -1.0f && RecordOf(y) == record);
                assert(std::abs(c - swing) <= std::max(swing * 0x1.0p-11f, 0x1.0p-25f));
            }
            assert(CastOf(PackCast(-0.0f, record)) == 0.0f && far_of(CastOf(PackCast(-0.0f, record))));
        }
        // A record off the 16-word steps, or past 2^20, is stored as none (0).
        assert(RecordOf(PackCast(-1.0f, 24u)) == 0u && RecordOf(PackCast(-1.0f, 1u << 20)) == 0u);
        // The half float of a whole number is exact.
        for (int k = -5; k <= 64; ++k) {
            assert(FromHalf(ToHalf(float(k))) == float(k));
        }
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
"""),
    ],
    LAB: [
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
// bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds
#include "video_core/host_shaders/point_shadow_ray_centred_comp.h"
#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
"""),
        (r"""                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
""",
         r"""                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        // bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds, as --lamps makes
        // them: the full one's bindings and its answers (11); the half one's and its answers (13)
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_CENTRED_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_HALF_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_HALF_CENTRED_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
"""),
        (r"""            std::memset(half_counts.data, 0, 64);
            vk.Begin();
            vk.ToGeneral(half_answers.image);
""",
         r"""            std::memset(half_counts.data, 0, 64);
            // bbport (r60_lamp-centred-window): the BB_LAMP_SHADOW_WINDOW=2 builds (a pass whose tuning
            // has window_centred runs them, as PointShadow::Ready picks them) and their answers image
            Pipeline lamp_centred = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_CENTRED_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Pipeline half_centred = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_HALF_CENTRED_COMP, sizeof(POINT_SHADOW_RAY_HALF_CENTRED_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image lamp_answers = vk.MakeImage(W, H, VK_FORMAT_R32G32_UINT);
            vk.Begin();
            vk.ToGeneral(lamp_answers.image);
            vk.ToGeneral(half_answers.image);
"""),
        (r"""                                               // are in the buffer), with this tuning: for a view of that frame
            };
""",
         r"""                                               // are in the buffer), with this tuning: for a view of that frame
                // bbport (r60_lamp-centred-window): MODE_APART, the engine's lamps-apart pass (the one
                // with the history): the light without the lamps in the targets (0 here), the lamps'
                // light in the snapshots (1), moved into the targets by the pass. The targets then
                // end as without it (0 + 1 * ratio, 1 where nothing is shadowed).
                bool apart = false;
            };
"""),
        (r"""                const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                vkCmdClearColorImage(vk.cmd, lamp_images[0].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                vkCmdClearColorImage(vk.cmd, lamp_images[2].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                const VkImageCopy whole{.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                    .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {W, H, 1}};
                vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[3].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                vk.Barrier();
""",
         r"""                const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
                const VkImageCopy whole{.srcSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                    .dstSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .extent = {W, H, 1}};
                if (pass.apart) { // bbport (r60_lamp-centred-window): cur0 0, snap0 1, cur1 and snap1 0
                    vkCmdClearColorImage(vk.cmd, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    for (const int k : {0, 2, 3})
                        vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[std::size_t(k)].image,
                                       VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                    mode |= 1u; // MODE_APART
                } else {
                    vkCmdClearColorImage(vk.cmd, lamp_images[0].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vkCmdClearColorImage(vk.cmd, lamp_images[2].image, VK_IMAGE_LAYOUT_GENERAL, &one, 1, &range);
                    vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[1].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                    vkCmdCopyImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, lamp_images[3].image, VK_IMAGE_LAYOUT_GENERAL, 1, &whole);
                }
                vk.Barrier();
"""),
        (r"""                VkDescriptorBufferInfo counts{half_counts.buffer, 0, 64};
                std::array<VkWriteDescriptorSet, 13> writes{};
                for (unsigned k = 0; k < 13; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
                writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[0].pBufferInfo = &data;
""",
         r"""                VkDescriptorBufferInfo counts{half_counts.buffer, 0, 64};
                std::array<VkWriteDescriptorSet, 14> writes{}; // bbport (r60): 13, the centred window's answers
                for (unsigned k = 0; k < 14; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
                writes[0].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[0].pBufferInfo = &data;
"""),
        (r"""                writes[12].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[12].pImageInfo = &follow_cur;
                std::array<VkWriteDescriptorSet, 11> full_writes{};
                std::copy_n(writes.begin(), 9, full_writes.begin());
""",
         r"""                writes[12].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[12].pImageInfo = &follow_cur;
                // bbport (r60_lamp-centred-window): the centred window's answers, binding 13 of the
                // half-resolution build and 11 of the full one (bound only with those builds)
                VkDescriptorImageInfo centred_answers{{}, lamp_answers.view, VK_IMAGE_LAYOUT_GENERAL};
                writes[13].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[13].pImageInfo = &centred_answers;
                std::array<VkWriteDescriptorSet, 12> full_writes{};
                std::copy_n(writes.begin(), 9, full_writes.begin());
"""),
        (r"""                full_writes[10].dstBinding = 10;
                LampPush push;
""",
         r"""                full_writes[10].dstBinding = 10;
                full_writes[11] = writes[13];
                full_writes[11].dstBinding = 11;
                // As PointShadow::Ready and Flush: the window centred (BB_LAMP_SHADOW_WINDOW=2) runs
                // its builds, and the pass that averages (not view 2 or 3) as a trace and a resolve.
                const bool centred = pass.tune && pass.tune->window && pass.tune->window_centred;
                const bool split = centred && pass.parity >= 0 && pass.tune->view != 2 && pass.tune->view != 3;
                constexpr unsigned Trace = 32u, Resolve = 64u; // MODE_TRACE, MODE_RESOLVE
                LampPush push;
"""),
        (r"""                if (pass.half) {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 13, writes.data());
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
                    unsigned word = mode | 2u | count; // MODE_HALF_FIRST
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 15) / 16, (H + 15) / 16, 1);
                    vk.Barrier();
                    word = mode | 4u | count; // MODE_HALF_FILL
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, half.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                } else {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 11, full_writes.data());
                    std::memcpy(&push.thickness, &mode, 4);
                    vkCmdPushConstants(vk.cmd, lamp.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                }
""",
         r"""                if (pass.half) {
                    const Pipeline& p = centred ? half_centred : half; // bbport (r60)
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.layout, 0, centred ? 14 : 13, writes.data());
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
                    // bbport (r60_lamp-centred-window): split, each half's trace and resolve (the
                    // resolves count nothing), as PointShadow::Flush records them
                    const auto dispatch = [&](unsigned word, unsigned x, unsigned y) {
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, x, y, 1);
                    };
                    dispatch(mode | 2u | count | (split ? Trace : 0u), (W + 15) / 16, (H + 15) / 16); // MODE_HALF_FIRST
                    vk.Barrier();
                    if (split) {
                        dispatch(mode | 2u | Resolve, (W + 15) / 16, (H + 15) / 16);
                        vk.Barrier();
                    }
                    dispatch(mode | 4u | count | (split ? Trace : 0u), (W + 7) / 8, (H + 7) / 8); // MODE_HALF_FILL
                    if (split) {
                        vk.Barrier();
                        dispatch(mode | 4u | Resolve, (W + 7) / 8, (H + 7) / 8);
                    }
                } else {
                    const Pipeline& p = centred ? lamp_centred : lamp; // bbport (r60)
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.layout, 0, centred ? 12 : 11, full_writes.data());
                    unsigned word = mode | (split ? Trace : 0u);
                    std::memcpy(&push.thickness, &word, 4);
                    vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                    vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                    if (split) {
                        vk.Barrier();
                        word = mode | Resolve;
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
                    }
                }
"""),
        (r"""            bool at_half = false;
            using HalfDid = std::array<std::uint32_t, 16>;
""",
         r"""            bool at_half = false;
            // bbport (r60_lamp-centred-window): at_apart: `frame` and `held_view` run the pass with
            // MODE_APART, as the engine runs its pass with the history (Pass::apart)
            bool at_apart = false;
            using HalfDid = std::array<std::uint32_t, 16>;
"""),
        (r"""                                          .read = have_history && history, .before = before, .follow = follow,
                                          .half = at_half});
                have_history = history;
""",
         r"""                                          .read = have_history && history, .before = before, .follow = follow,
                                          .half = at_half, .apart = at_apart});
                have_history = history;
"""),
        (r"""                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .half = at_half, .again = true});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
""",
         r"""                shown.view_gain = 0.5f;
                run(v, {.tune = &shown, .frame = clock - 1, .parity = int((clock - 1) & 1u), .half = at_half, .again = true,
                        .apart = at_apart});
                auto picture = values(); // red: (1 - held) / 2; a pixel the pass leaves alone keeps 1
"""),
        (r"""                // to see; "no" in every case means it does not see it here), and 0 against 1.
                {
                    struct LatticeCase {
""",
         r"""                // to see; "no" in every case means it does not see it here), and 0 against 1.
                // bbport (r60_lamp-centred-window): and BB_LAMP_SHADOW_WINDOW=2 (the window centred),
                // run with MODE_APART as the engine runs it (the others run without; the two modes
                // give the same picture, which the r60 apart line below compares once). 0's verdict is
                // now the folds' largest-over-smallest bin ratios, each against the reference's of the
                // same fold (r57's numbers: 0 within 1.005 of the reference's in every fold, 1 up to
                // 1.2 times it in the carried and walking-past cases; the window-phase score saw no
                // grid). A run "lines up with the grid" where a checked fold (x and y mod 8; at half
                // resolution mod 16 too; mod 2 is printed only) lies above GridMost times the
                // reference's. Checked (with the defaults): 0 never lines up with the soft follow.
                // Printed only, until a first GPU run gives their numbers (r57's rule: a check nobody
                // has measured could turn the default lab red): whether 2 lines up, judged only in a
                // case and build where 1 lines up ("blind" elsewhere: r57's numbers have 1 at 1.01 to
                // 1.06 with BB_LAMP_SHADOW_FOLLOW=0, too near the bound to see a grid); whether the
                // pictures with 2 and 1 differ (else bit 22 or the trace and resolve do not reach the
                // shader); whether MODE_APART changes the picture of 1 or 2.
                {
                    constexpr double GridMost = 1.05;
                    struct LatticeCase {
"""),
        (r"""                    std::string lattice_fault, same_fault;
                    bool grid_seen = false;
                    for (const LatticeCase& lc : cases) {
                        for (const bool half_build : {false, true}) {
                            std::array<Vulkan::LampShadowTune, 3> tunes{plain, soft, soft};
                            tunes[1].window = true;
                            tunes[0].window = tunes[2].window = false;
                            for (auto& t : tunes) t.follow = lc.follow;
""",
         r"""                    std::string lattice_fault, same_fault;
                    // bbport (r60_lamp-centred-window): printed only (see above)
                    std::string centred_fault, centred_same_fault, centred_apart_fault;
                    bool grid_seen = false;
                    unsigned judged_2 = 0, blind_2 = 0; // (case, build) pairs where 1 lines up; where it does not
                    for (const LatticeCase& lc : cases) {
                        for (const bool half_build : {false, true}) {
                            // (0 the reference, 1 BB_LAMP_SHADOW_WINDOW=1, 2 =0; bbport r60: 3 =2)
                            std::array<Vulkan::LampShadowTune, 4> tunes{plain, soft, soft, soft};
                            tunes[1].window = true;
                            tunes[0].window = tunes[2].window = false;
                            tunes[3].window = true;
                            tunes[0].window_centred = tunes[1].window_centred = tunes[2].window_centred = false;
                            tunes[3].window_centred = true;
                            for (auto& t : tunes) t.follow = lc.follow;
"""),
        (r"""                            mask.reserve(std::size_t(lc.move.frames) * W * H);
                            std::array<Lattice, 3> lattices{};
                            for (std::size_t r = 0; r < 3; ++r) {
                                lattices[r].mask = &mask;
""",
         r"""                            mask.reserve(std::size_t(lc.move.frames) * W * H);
                            std::array<Lattice, 4> lattices{};
                            for (std::size_t r = 0; r < 4; ++r) {
                                lattices[r].mask = &mask;
"""),
        (r"""                            at_half = half_build;
                            std::array<std::vector<float>, 3> last;
                            for (std::size_t r = 0; r < 3; ++r) last[r] = moving(tunes[r], lc.move, nullptr, &lattices[r]);
                            at_half = false;
""",
         r"""                            at_half = half_build;
                            std::array<std::vector<float>, 4> last;
                            for (std::size_t r = 0; r < 4; ++r) {
                                at_apart = r == 3; // bbport (r60): 2 as the engine runs it
                                last[r] = moving(tunes[r], lc.move, nullptr, &lattices[r]);
                            }
                            at_apart = false;
                            // bbport (r60_lamp-centred-window): once (the first case, the first speed, both
                            // builds): 1 with MODE_APART and 2 without, against the runs above. Every pixel
                            // the same is what the modes must give (the light the pass moves is 0 + 1 * ratio
                            // in both); a difference is the apart path of the trace or the resolve.
                            if (&lc == &cases[0] && speed == 0.067f) {
                                at_apart = true;
                                const auto apart_1 = moving(tunes[1], lc.move);
                                at_apart = false;
                                const auto plain_2 = moving(tunes[3], lc.move);
                                std::array<std::size_t, 2> differ{};
                                std::array<double, 2> most{};
                                for (std::size_t i = 0; i < last[1].size(); ++i) {
                                    const double d1 = std::abs(double(apart_1[i]) - double(last[1][i]));
                                    const double d2 = std::abs(double(plain_2[i]) - double(last[3][i]));
                                    differ[0] += d1 > 0.0 ? 1 : 0;
                                    differ[1] += d2 > 0.0 ? 1 : 0;
                                    most[0] = std::max(most[0], d1);
                                    most[1] = std::max(most[1], d2);
                                }
                                std::printf("Torch lab, r60 apart, %s, %.1f cm a frame, %s: the last frame with MODE_APART "
                                            "against without (printed only; the same is expected): BB_LAMP_SHADOW_WINDOW=1 "
                                            "%zu pixels differ (most %.5f), =2 %zu pixels differ (most %.5f)\n",
                                            lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                            differ[0], most[0], differ[1], most[1]);
                                if (checked && centred_apart_fault.empty() && (differ[0] != 0 || differ[1] != 0)) {
                                    centred_apart_fault = lc.name;
                                }
                            }
                            at_half = false;
"""),
        (r"""                                           : std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}};
                            std::array<std::string, 3> text;
                            std::array<double, 3> phase{}; // the window-phase score, the larger of x and y
                            for (std::size_t r = 0; r < 3; ++r) {
                                phase[r] = std::max(window_score(lattices[r], 0), window_score(lattices[r], 1));
""",
         r"""                                           : std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}};
                            // bbport (r60_lamp-centred-window): each run's largest checked fold ratio
                            // over the reference's of the same fold (mod 2 not checked)
                            std::array<double, 4> over{};
                            for (std::size_t r = 1; r < 4; ++r) {
                                for (const auto& [axis, mod] : folds) {
                                    if (mod == 2) continue;
                                    over[r] = std::max(over[r], lattice_score(lattices[r], axis, mod) /
                                                                    std::max(lattice_score(lattices[0], axis, mod), 1e-12));
                                }
                            }
                            std::array<std::string, 4> text;
                            std::array<double, 4> phase{}; // the window-phase score, the larger of x and y
                            for (std::size_t r = 0; r < 4; ++r) {
                                phase[r] = std::max(window_score(lattices[r], 0), window_score(lattices[r], 1));
"""),
        (r"""                            apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            const bool seen = phase[1] > 1.1 * phase[0];
""",
         r"""                            apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            // bbport (r60_lamp-centred-window): 2 against 1, as 0 against 1 above
                            double centred_apart = 0;
                            std::size_t centred_apart_n = 0;
                            for (std::size_t i = 0; i < last[1].size(); ++i) {
                                const double d = std::abs(double(last[1][i]) - double(last[3][i]));
                                centred_apart += d;
                                centred_apart_n += d > 0.01 ? 1 : 0;
                            }
                            centred_apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            const bool seen = phase[1] > 1.1 * phase[0];
"""),
        (r"""                                        phase[2] / std::max(phase[1], 1e-12), apart, apart_n);
                            if (!lc.move.carried) {
""",
         r"""                                        phase[2] / std::max(phase[1], 1e-12), apart, apart_n);
                            // bbport (r60_lamp-centred-window): 2 is judged only where 1 lines up
                            const bool sees = over[1] > GridMost;
                            std::printf("Torch lab, r60 lattice, %s, %.1f cm a frame, %s: BB_LAMP_SHADOW_WINDOW=2 (with "
                                        "MODE_APART) %s. The largest checked fold ratio (mod %s) over the reference's of "
                                        "the same fold (above %.2f: lines up with the grid): 1 %.3f (%s), 0 %.3f (%s), 2 "
                                        "%.3f (%s); the last frame with 2 against 1: mean difference %.5f, %zu pixels "
                                        "apart by more than 0.01\n",
                                        lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                        text[3].c_str(), half_build ? "8 and 16" : "8", GridMost, over[1],
                                        sees ? "lines up" : "does not", over[2], over[2] > GridMost ? "lines up" : "does not",
                                        over[3],
                                        !sees                ? "blind: 1 does not line up here"
                                        : over[3] > GridMost ? "lines up"
                                                             : "does not",
                                        centred_apart, centred_apart_n);
                            judged_2 += sees ? 1u : 0u;
                            blind_2 += sees ? 0u : 1u;
                            if (!lc.move.carried) {
"""),
        (r"""                            if (checked && same_fault.empty() && !(apart > 0.0)) same_fault = where;
                            if (checked && soft.follow_soft && lattice_fault.empty() && !(phase[2] <= 1.1 * phase[0])) {
                                lattice_fault = where;
                            }
                        }
""",
         r"""                            if (checked && same_fault.empty() && !(apart > 0.0)) same_fault = where;
                            // bbport (r60_lamp-centred-window): the verdict is the bin ratios (r57: the
                            // window-phase score within 1.1 times the reference's)
                            if (checked && soft.follow_soft && lattice_fault.empty() && !(over[2] <= GridMost)) {
                                lattice_fault = where;
                            }
                            if (checked && centred_same_fault.empty() && !(centred_apart > 0.0)) centred_same_fault = where;
                            if (checked && sees && centred_fault.empty() && !(over[3] <= GridMost)) centred_fault = where;
                        }
"""),
        (r"""                        return 1;
                    }
                }
            }
""",
         r"""                        return 1;
                    }
                    // bbport (r60_lamp-centred-window): printed only, until a first GPU run gives the
                    // numbers (each "would fail" below is to become a check then)
                    std::printf("Torch lab, r60 lattice, %.1f cm a frame (printed only): BB_LAMP_SHADOW_WINDOW=1 lines up "
                                "with the grid in %u of %u case and build pairs (2 is judged in those, blind in the "
                                "other %u); 2 lines up where 1 does: %s; 2 and 1 give the same picture: %s; MODE_APART "
                                "changes the picture: %s\n",
                                speed * 100.0f, judged_2, judged_2 + blind_2, blind_2,
                                centred_fault.empty() ? "no" : ("would fail (" + centred_fault + ")").c_str(),
                                centred_same_fault.empty() ? "no" : ("would fail (" + centred_same_fault + ")").c_str(),
                                centred_apart_fault.empty() ? "no" : ("would fail (" + centred_apart_fault + ")").c_str());
                }
            }
"""),
        (r"""                // 2 the default in the half-resolution build; bbport r57_lamp-window: 3 the default
                // with BB_LAMP_SHADOW_WINDOW=0, printed only)
                std::array<std::array<double, 5>, 4> left{};
                place(view, 0.0f, 0.0f);
""",
         r"""                // 2 the default in the half-resolution build; bbport r57_lamp-window: 3 the default
                // with BB_LAMP_SHADOW_WINDOW=0, printed only; bbport r60_lamp-centred-window: 4 and 5
                // with BB_LAMP_SHADOW_WINDOW=2 at full and at half resolution, with MODE_APART as the
                // engine runs it; printed beside the default's bounds, not yet checked)
                std::array<std::array<double, 5>, 6> left{};
                place(view, 0.0f, 0.0f);
"""),
        (r"""                own.window = false;
                for (int which = 0; which < 4; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 1 ? plain : which == 3 ? own : soft;
                    at_half = which == 2;
                    restart();
""",
         r"""                own.window = false;
                Vulkan::LampShadowTune centred = soft; // bbport (r60)
                centred.window = centred.window_centred = true;
                for (int which = 0; which < 6; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 1 ? plain : which == 3 ? own : which >= 4 ? centred : soft;
                    at_half = which == 2 || which == 5;
                    at_apart = which >= 4; // bbport (r60)
                    restart();
"""),
        (r"""                at_half = false;
                std::printf("Torch lab, a figure is gone from one frame to the next, %s: share of the old picture left "
""",
         r"""                at_half = false;
                at_apart = false;
                std::printf("Torch lab, a figure is gone from one frame to the next, %s: share of the old picture left "
"""),
        (r"""                    return 1;
                }
            }
            second = false;
""",
         r"""                    return 1;
                }
                // bbport (r60_lamp-centred-window): the window centred is meant to bind as the confined
                // one: the default's bounds (which 0 fails with two lamps), printed only until a first
                // GPU run gives the numbers
                const auto within = [&](std::size_t k) {
                    return left[k][1] < 0.2 && left[k][2] < 0.15 && left[k][2] < 0.5 * left[1][2];
                };
                std::printf("Torch lab, r60, a figure is gone from one frame to the next, %s: the same with "
                            "BB_LAMP_SHADOW_WINDOW=2 and MODE_APART %.3f / %.3f / %.3f / %.3f / %.3f (%s the default's "
                            "bounds); in the half-resolution build %.3f / %.3f / %.3f / %.3f / %.3f (%s them); printed "
                            "only\n",
                            two ? "two lamps" : "one lamp", left[4][0], left[4][1], left[4][2], left[4][3], left[4][4],
                            within(4) ? "within" : "outside", left[5][0], left[5][1], left[5][2], left[5][3], left[5][4],
                            within(5) ? "within" : "outside");
            }
            second = false;
"""),
        (r"""                            "and its history %.3f ms\n", best[0], best[1], best[2], best[3], best[4]);
            }
""",
         r"""                            "and its history %.3f ms\n", best[0], best[1], best[2], best[3], best[4]);
                // bbport (r60_lamp-centred-window): the area lamp with its history, the window confined
                // (1) and centred (2), at full and at half resolution (settled, without counters, with
                // MODE_APART as the engine runs it); printed only, a small scene
                std::array<Vulkan::LampShadowTune, 2> windows{soft, soft};
                windows[0].window = true;
                windows[0].window_centred = false;
                windows[1].window = windows[1].window_centred = true;
                std::array<double, 4> window_best{1e9, 1e9, 1e9, 1e9};
                half_count = false;
                at_apart = true;
                for (int w = 0; w < 2; ++w) {
                    for (const bool h : {false, true}) {
                        restart();
                        at_half = h;
                        for (int i = 0; i < 48; ++i) {
                            const double ms = frame(view, windows[std::size_t(w)]);
                            if (i >= 8) window_best[std::size_t(w * 2 + (h ? 1 : 0))] = std::min(window_best[std::size_t(w * 2 + (h ? 1 : 0))], ms);
                        }
                    }
                }
                at_half = false;
                at_apart = false;
                half_count = true;
                std::printf("Torch lab, r60: the area lamp with its history, BB_LAMP_SHADOW_WINDOW=1 %.3f ms, =2 %.3f ms; "
                            "the half-resolution build =1 %.3f ms, =2 %.3f ms (printed only)\n",
                            window_best[0], window_best[2], window_best[1], window_best[3]);
            }
"""),
        (r"""                unsigned torch_count = 0;
                const auto run_lamps = [&](bool per_tile, unsigned pick = 0, unsigned frame = 0, int parity = -1,
""",
         r"""                unsigned torch_count = 0;
                // bbport (r60_lamp-centred-window): this section runs the build without CENTRED only
                // (lamp.pipeline, one dispatch), which does not read word 0 bit 22: with
                // BB_LAMP_SHADOW_WINDOW=2 in the environment it measures the window of 1 here. The
                // torch lab (--lamps) runs the centred builds.
                const auto run_lamps = [&](bool per_tile, unsigned pick = 0, unsigned frame = 0, int parity = -1,
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts, quiet=False):
    """What the patched texts must hold; False (with the reason printed) when one does not."""
    ok = True

    def bad(msg):
        nonlocal ok
        ok = False
        if not quiet:
            print("check (%s): %s" % (ROOT, msg))

    for rel, t in texts.items():
        if not t.isascii():
            bad("a character that is not ASCII in %s" % rel)
    # each text in the patched file (the first of each list exactly once)
    musts = {
        COMP: ["const uint MODE_TRACE = 32u;", "const uint MODE_RESOLVE = 64u;",
               "t_centred = (f & (1u << 22u)) != 0u;"],
        TUNE: ["inline constexpr std::uint32_t LampWindowDefault = ", "LampTuneCentred = 1u << 22;",
               "static_assert(LampWindowDefault <= 2"],
        CPP: ["constexpr u32 ModeTrace = 32, ModeResolve = 64;", "POINT_SHADOW_RAY_HALF_CENTRED_COMP",
              "half_with_answers ? 14u : 13u"],
        HDR: ["OwnImage answers;", "bool half_centred = false;"],
        CMAKE: ["add_host_shader(point_shadow_ray.comp point_shadow_ray_centred_comp CENTRED=1)",
                "add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_comp HALF=1 CENTRED=1)"],
        DOC: ["**Centred lamp history window, to try (r60).**"],
        TEST: ["constexpr std::uint32_t DefaultWindowBits =", "Statistic(f, shift, true)", "PackCast("],
        LAB: ["Pipeline lamp_centred = vk.MakePipeline(", "POINT_SHADOW_RAY_CENTRED_COMP", "Torch lab, r60 lattice",
              "Torch lab, r60 apart"],
    }
    for rel, needles in musts.items():
        for k, needle in enumerate(needles):
            n = texts[rel].count(needle)
            if n < 1 or (k == 0 and n != 1):
                bad("%s holds %r %d times (want %s)" % (rel, needle, n, "1" if k == 0 else "1 or more"))
    return ok


def file_run(rel, mode):
    """One file's text after its edits in this mode (apply's for check), or (None, why)."""
    path = ROOT + rel
    if not os.path.isfile(path):
        return None, "no such file"
    t = open(path, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in t else "\n"
    pairs = EDITS[rel]
    for old, new in (pairs if mode != "revert" else reversed(pairs)):
        a, b = (fix(old, nl), fix(new, nl)) if mode != "revert" else (fix(new, nl), fix(old, nl))
        n = t.count(a)
        if n != 1:
            return None, "anchor found %d times (want 1): %a" % (n, a[:90])
        t = t.replace(a, b)
    return t, ""


def run(mode, quiet=False):
    """The patched (or restored) texts by path, or None with the reason printed."""
    out = {}
    for rel in EDITS:
        t, why = file_run(rel, mode)
        if t is None:
            if not quiet:
                print("%s in %s%s" % (why, ROOT, rel))
            return None
        out[rel] = t
    if mode != "revert":
        if not text_check(out, quiet):
            return None
    return out


def states():
    """Each file on its own: original (its edits apply), patched (they revert) or neither (why)."""
    for rel in EDITS:
        fwd, why = file_run(rel, "apply")
        back, _ = file_run(rel, "revert") if fwd is None else (None, "")
        state = ("original (applies cleanly)" if fwd is not None else
                 "patched (reverts cleanly)" if back is not None else "neither: " + why)
        print("  %s%s: %s" % (ROOT, rel, state))


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r60_lamp-centred-window.py check|apply|revert   (the tree: R60_ROOT, else the "
              "current directory)")
        return 2
    print("tree: %s" % ROOT)
    # run() only reads: nothing is written before every text of the mode is made.
    out = run(mode, quiet=True)
    if out is None:
        if mode != "revert" and run("revert", quiet=True) is not None:
            print("already applied in %s (revert would restore it)%s" % (ROOT, "" if mode == "check" else
                                                                        ": nothing written"))
            return 0 if mode == "check" else 1
        if mode == "revert" and run("check", quiet=True) is not None:
            print("not applied in %s: nothing to revert" % ROOT)
            return 1
        print("neither applied nor clean in %s (a mixed or changed tree); each file on its own:" % ROOT)
        states()
        # every file's anchors held: what the patched texts lack (text_check) says why
        run(mode, quiet=not all(file_run(rel, mode)[0] is not None for rel in EDITS))
        return 1
    if mode == "check":
        print("anchors OK in %s (applies cleanly)" % ROOT)
        return 0
    # Every new text goes to a file beside its target first, then each is moved over its target
    # (one rename a file). If a step fails, what was already moved is put back from the bytes read
    # at the start, so the tree is never left half patched.
    before = {rel: open(ROOT + rel, "rb").read() for rel in out}
    done = []
    try:
        for rel, t in out.items():
            with open(ROOT + rel + TMP, "w", encoding="utf-8", newline="") as f:
                f.write(t)
        for rel in out:
            os.replace(ROOT + rel + TMP, ROOT + rel)
            done.append(rel)
    except OSError as e:
        print("failed in %s (%s); putting back what was changed" % (ROOT, e))
        for rel in done:
            with open(ROOT + rel, "wb") as f:
                f.write(before[rel])
        for rel in out:
            if os.path.exists(ROOT + rel + TMP):
                os.remove(ROOT + rel + TMP)
        return 1
    print("%s in %s (%d files)" % ("applied" if mode == "apply" else "reverted", ROOT, len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
