# r57_lamp-window: a knob, BB_LAMP_SHADOW_WINDOW (default 1, the pass as before), whose 0 makes the
# ray traced lamp shadow pass guard each pixel's history with what that pixel has itself, in place
# of the 5x5 answers of its compute workgroup ("Fix 1" of the second squares diagnosis,
# squares_diag2.json verdict.fix_spec, here as a setting to try, not as the default). check|apply|revert.
#
# WHY (the squares behind moving lamp shadows, best diagnosis, confidence medium): the ghost clamp
# of point_shadow_ray.comp bounds a pixel's history by the mean and deviation of the 5x5 answers
# around it, and the soft follow (r52) caps the frames of the history's "stands" share by the far
# blockers' mean swing in the same window. A compute pass sees only its own 8x8 workgroup, so the
# window starts at clamp(local - 2, 0, 3): each axis of the group has 4 windows, in runs of 3, 1, 1
# and 3 pixels, and every pixel of a run keeps or gives up its history together. Behind a moving
# shadow that leaves straight-sided cells fixed to the screen (8 px grid; in the half-resolution
# build the first pass's windows lie on a 16 px grid of block pixels, whose dots the second pass
# then spreads). Origins are absolute, so the grid does not move with the content.
#
# WHY NOT THE DEFAULT (two reviews, desk models, not a GPU run): without the window the bound is
# centred on the pixel's own lagging mean and is at least 0.18 wide on each side, so it cuts only a
# change of more than about 0.86 of the light at once (then one frame later than the window, by the
# reject). A smaller change, with one lamp or several (a penumbra that becomes lit, one lamp's part
# of two), fades like the history without its guards: share of the old value left after 1 / 2 / 4
# / 8 / 16 frames about 0.90 / 0.81 / 0.60 / 0.35 / 0.15 (two equal lamps), against 0 after 1
# frame with an agreeing window. The torch lab's existing check "a shadow that is gone lingers (two
# lamps)" (after 2 frames < 0.2, after 4 < 0.15) is therefore expected to FAIL with 0. With 1 (the
# default) the pass is the one of today, so the lab stays as today. Whether 0 removes the squares
# in the game, and whether its wakes are acceptable, is for a game test and the owner to judge; the
# fix that keeps a spatial guard is Fix 2 (a centred window in a resolve dispatch), not built here.
#
# WHAT IT DOES (point_shadow_ray.comp, HISTORY_BLEND; one source for the full and the HALF build,
# both passes of the latter):
#  - The 5x5 loop runs only when its sums are taken: t_window (word 0 bit 21) or the old vote
#    (BB_LAMP_SHADOW_FOLLOW_SOFT=0). The shared arrays are still written and the barrier is still
#    reached by every invocation (the branch is uniform: t_window and t_follow_soft come from the
#    tuning words).
#  - The clamp without the window: centred on the pixel's own mean of its last few frames
#    (m = fast = mix(answer, held_fast, FAST_KEEP)), spread = around * sqrt((m (1 - m) +
#    AROUND_FLOOR) / FAST_COUNT), FAST_COUNT = (1 + FAST_KEEP) / (1 - FAST_KEEP) = 4 (the effective
#    count of that mean). fitted, taken, frames and held_ratio as before. (The spec's hand number,
#    spread 0.62 at m = 0.5, is wrong for around = 1.6: it is 0.44.)
#  - The soft follow's slip without the window: the "stands" share's swing is one constant,
#    OWN_SWING = 1 (a blocker halfway between lamp and surface; a guess), for every pixel. Not the
#    pixel's own blocker as the spec said: that cap would act on the blocked (dark) frames only, so
#    dark answers would weigh more and a standing penumbra under a moving lamp would turn darker
#    (review M2's desk model: 0.5 -> 0.38). The cap still acts only through the follow state's
#    "stands" share (c_minus), which is 0 where no far blocker has hit the pixel lately.
#  - With t_window set every changed statement is the old one: the loop runs, the swing is the
#    window's mean, the bound the window's mean and deviation, same operands, same order. With the
#    repair off (MODE_REPAIR clear, experiment 35184372088832: the pass of before r41) t_window
#    keeps its initial value true.
#  - The half-resolution build at 0 still shares the answers of 3x3 blocks that agree (HalfAnswer)
#    and copies a taken block's history (HALF_TAKEN): only the full resolution pass is wholly free
#    of other pixels' answers.
#
# THE KNOB: BB_LAMP_SHADOW_WINDOW, 0 or 1, default 1 (the window, as before r57), read once at start
# (lamp_shadow_tune.h LampShadowTune::window), word 0 bit 21 of the sixteen tuning words
# (LampTuneWindow). Bits 12-17 and 20 are not touched. It reaches the shader only with the repair
# (MODE_REPAIR). Env only, no experiment bit, so engine_previous_paths leaves it as it is: listed in
# engine/docs/renderer-performance-0.9.43.md under "Not restored by the switch". With
# BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap keep the window by design (they have no
# per-pixel form): only FOLLOW_SOFT=1 (the default) gives a window-free pass. Log line at start:
# "Ray traced lamps (r57): window yes/no ...".
#
# rt-shadow-test --lamps (tests/test_rt_shadows.cpp), new lines only; every old line and check is
# unchanged, and with the default the pass is today's, so they should give today's numbers:
#  - "r57 lattice" lines in the walk loop. Cases: the carried torch, the torch's lamp walking past
#    standing casters, the carried torch with BB_LAMP_SHADOW_FOLLOW=0; both speeds; full and half;
#    each run three times: the history without its guards (the reference), WINDOW=1 and WINDOW=0,
#    whatever the environment says. Measured over the 16 moving frames on the steps where the
#    reference shows a penumbra or a wake: the mean step between neighbours folded by x and y.
#    Scores: the window-phase score (bins 0, 3, 4, 5 of the fold mod 8, where the window changes,
#    over bins 1, 2, 6, 7), and per fold (mod 8; also 16 and 2 in the half build) the largest over
#    the smallest bin. Checked with the defaults: the last frames with 0 and with 1 differ (else bit
#    21 does not reach the shader; the lab is deterministic); with the soft follow, 0's
#    window-phase score at most 1.1 times the reference's. Printed only (no number measured yet):
#    whether 1's score lies above 1.1 times the reference's in some case (the grid seen; "no case"
#    means the score is blind to it here), 0 over 1, and for the standing casters the last frame's
#    mean of picture minus truth over the true penumbra (a dark bias shows below 0).
#  - A line after "a figure is gone from one frame to the next": the same with WINDOW=0, not
#    checked. Run with BB_LAMP_SHADOW_WINDOW=0 in the environment, the old linger check is applied
#    to 0 and is expected to stop the lab there.
#
# NOT DONE: Fix 2; the spec's second lab test (a shifted camera); any change to HalfAnswer, the
# rays, the vote of FOLLOW_SOFT=0, the constants or the host bindings; R16F or memory changes.
# NOTHING HAS BEEN BUILT IN THE TREE OR RUN ON A GPU: no game test, no rt-shadow-test run, no
# timing. Checked here: both shader builds compile (glslang --target-env vulkan1.3, as the CMake
# rule) and pass spirv-val; with t_window made the constant true the optimised SPIR-V is today's;
# lamp-shadow-tune-test built by hand with clang++ passes; clang++ -fsyntax-only of
# vk_point_shadow.cpp and test_rt_shadows.cpp passes.
#
# HOW TO TEST:
#  1. lamp-shadow-tune-test (knob default 1, 0 off, only word 0 bit 21 changes).
#  2. rt-shadow-test --lamps unset (the default): every line that is not new and not a time the
#     same as today's (lamps1.txt). Read the new lines: is the grid seen with 1, is 0 near the
#     reference, the bias of the standing penumbra, the linger numbers with 0.
#  3. Game (HQ GTAO, torch out, DLSS Performance 4K, the r52 spot, walk 3): BB_LAMP_SHADOW_WINDOW=0
#     against unset at graphics_lamp_shadow_half=1 and 0, and FOLLOW=0 with half=1; VIEW=4, 5, 6
#     and normal: do the squares go away with 0, and how long are the wakes of carried and
#     standing shadows and of a spot lit by the torch and a street lamp together;
#     BB_GPU_PROFILE=1 "point shadows" row.
#
# THE TREE: R57_ROOT, else the current directory (which must then be a source tree's root); every
# message names it. Every file is guarded by the sha256 of its original and of its patched
# content: check says "not applied" or "applied" (or why neither), apply works only on all
# originals (and says "already applied" on all patched files), revert only on all patched files and
# gives back the original bytes (the edits taken back, then checked against the original sha256).
# Line ends are kept (all six files are CRLF). New texts are written beside their targets and moved
# over them; a failure puts back what was moved. r50b_leaf-matcher, r55 and r56 do not touch these
# six files, so the order of those patches against this one does not matter.

import hashlib
import os
import sys

ROOT = os.environ.get("R57_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"

COMP = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
TUNE = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
CPP = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
TEST = "engine/tests/test_lamp_shadow_tune.cpp"
LAB = "engine/tests/test_rt_shadows.cpp"
DOC = "engine/docs/renderer-performance-0.9.43.md"
TMP = ".r57tmp"

# sha256 of each file: (original, patched).
SUMS = {
    COMP: ('c4c48bef62dda61af13be7ec086a51e2c295a64d8b491a872351735b4ddeaf52', 'a76495f901ec5222c8eee2cd31aa30073172726fbc3410226cafa1962b8427a9'),
    TUNE: ('e9d458f128fa6850eb96f01e2d5b7a15ca9a6f0e92a9f89fb0e2897415b498e7', '7e37088ca701b400aa9bf2f855c51be35b4efb5b98cad17002ef9db41389aa4c'),
    CPP: ('c16ef5da49d50f56c5a2db032d4920ff681c353c071c2412582aace4694f417b', 'c2e45071fce3695f46642f6b9a3718dc9b5f0b2c480b30c4e2897eb45f0be0f3'),
    TEST: ('3f469afb8af03f6ad6b8227fb7532fe091fe36f14b678bec3aae87b7ee8e3fa6', '8261cb9f8620d6d999882d83ffcd098dcbb77244266c91d77f990fea929e4fd8'),
    LAB: ('6e712cf8975ad75e4cf849bff0bdcbf5987679091209d38de22ce5a041f4ae23', '9a00ac55bf35fc90803bdab583a672c2a5d721812fe955265971f78a77391618'),
    DOC: ('7b71efa1db16c76568ce091470cdd3b0d4071a42cd33a5ec1c52321d1c7295ff', '306ef16fab99fc0d75b855f7f5768ac4e24f3765bdcb4d2aa9aa966887592daa'),
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Written with LF; the file's CRLF is put in.
EDITS = {
    COMP: [
        (r"""bool t_follow_soft = false;     // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
""",
         r"""bool t_follow_soft = false;     // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT
bool t_window = true;           // bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW (true: the pass of before)
float t_clear = LAMP_CLEARANCE; // blind sphere at the lamp, m
"""),
        (r"""    t_follow_soft = (f & (1u << 20u)) != 0u; // bbport (r52_follow-soft); bits 12-17 are not used
    t_clear = word(at + 1u);
""",
         r"""    t_follow_soft = (f & (1u << 20u)) != 0u; // bbport (r52_follow-soft); bits 12-17 are not used
    t_window = (f & (1u << 21u)) != 0u;      // bbport (r57_lamp-window)
    t_clear = word(at + 1u);
"""),
        (r"""const float FAST_KEEP = 0.6; // the last frame's share in the mean of the last few frames
// The reject sets in at this share of t_reject. One ray that disagrees with the history moves
""",
         r"""const float FAST_KEEP = 0.6; // the last frame's share in the mean of the last few frames
// bbport (r57_lamp-window): how many frames that mean stands for (its variance is that of so many
// answers): (1 + FAST_KEEP) / (1 - FAST_KEEP), 4.
const float FAST_COUNT = (1.0 + FAST_KEEP) / (1.0 - FAST_KEEP);
// bbport (r57_lamp-window): without the window, the swing of the "stands" share under a moving
// lamp (the shadow's step over the lamp's): one value for every pixel, so that the cap of its
// frames does not depend on whether this frame's ray was blocked (a cap on the blocked frames
// alone weighs the dark answers more and darkens a standing penumbra). 1: a blocker halfway
// between the lamp and the surface. A guess, not measured.
const float OWN_SWING = 1.0;
// The reject sets in at this share of t_reject. One ray that disagrees with the history moves
"""),
        (r"""// answers are taken to have at the least (over the answers counted; 0.25 is a coin's), and how
// far the history may lie outside before it is given up (from, wholly).
const float AROUND_FLOOR = 0.05;
""",
         r"""// answers are taken to have at the least (over the answers counted; 0.25 is a coin's), and how
// far the history may lie outside before it is given up (from, wholly). bbport (r57_lamp-window):
// without the window, against the pixel's own last few frames (over FAST_COUNT).
const float AROUND_FLOOR = 0.05;
"""),
        (r"""    //    nothing else.
    const float answer = ratio; // what this frame's rays said (view 1)
""",
         r"""    //    nothing else.
    //  - bbport (r57_lamp-window): the 5x5 window cannot be centred on a pixel near the
    //    workgroup's rim, so every pixel of a run of 3, 1, 1 and 3 columns (or rows) shares one
    //    window, and a history kept or given up by it was kept or given up by the whole run: under
    //    a moving shadow that left squares fixed to the screen, on the 8 px grid (16 px in the
    //    half-resolution build's first pass, whose dots its second pass then spread). With
    //    BB_LAMP_SHADOW_WINDOW=0 (word 0 bit 21 clear; the default is 1, the window) no answer
    //    of another pixel reaches this one at full resolution (the half-resolution build still
    //    shares the answers of 3x3 blocks that agree, HalfAnswer, and copies a taken block's
    //    history): the bound is centred on the pixel's own mean of its last few frames with the
    //    deviation FAST_COUNT one-lamp answers (0 or 1) would have, and the swing that caps the
    //    frames of the "stands" share is OWN_SWING for every pixel. That bound is wide: it
    //    binds only a change of more than about 0.86 of the light at once, with one lamp or
    //    several, and a smaller one (a penumbra that becomes lit, one lamp's part of two) fades
    //    like the history without its guards, so the wake of a moving caster is no longer
    //    removed as above. With BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its swing still come
    //    from the window (they have no per-pixel form): only the soft follow makes the pass
    //    free of it.
    const float answer = ratio; // what this frame's rays said (view 1)
"""),
        (r"""        // The 5x5 answers around the pixel, moved in from the workgroup's rim so that every
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
""",
         r"""        // The 5x5 answers around the pixel, moved in from the workgroup's rim so that every
        // pixel has 25 places to ask (this pixel's own is always one of them). bbport
        // (r57_lamp-window): read only where something takes them (see above); the shared
        // arrays are still written and the barrier still reached by every invocation.
        float count = 0.0, sum = 0.0, sum2 = 0.0, near_n = 0.0, far_n = 0.0, swing = 0.0;
        if (t_window || !t_follow_soft) {
            const ivec2 around_lo = clamp(ivec2(gl_LocalInvocationID.xy) - 2, ivec2(0), ivec2(3));
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
"""),
        (r"""            // lamp's whole step, its share that stands by the far blockers' mean swing (0 with
            // no opinion); m a frame, as the vote's slip below.
            const float s = 1.0 / (1.0 + exp(-lam_kept));
""",
         r"""            // lamp's whole step, its share that stands by the far blockers' mean swing (0 with
            // no opinion; bbport r57_lamp-window: OWN_SWING without the window); m a frame, as
            // the vote's slip below.
            const float s = 1.0 / (1.0 + exp(-lam_kept));
"""),
        (r"""                const float c_plus = max(2.0 * s - 1.0, 0.0), c_minus = max(1.0 - 2.0 * s, 0.0);
                const float k_win = far_n > 0.0 ? swing / far_n : 0.0;
                slip = (1.0 - w_f) * top_step * (c_plus + c_minus * k_win);
                looked = vec3(0.0, w_f, 1.0 - w_f);
""",
         r"""                const float c_plus = max(2.0 * s - 1.0, 0.0), c_minus = max(1.0 - 2.0 * s, 0.0);
                // bbport (r57_lamp-window): without the window, OWN_SWING
                const float k = t_window ? (far_n > 0.0 ? swing / far_n : 0.0) : OWN_SWING;
                slip = (1.0 - w_f) * top_step * (c_plus + c_minus * k);
                looked = vec3(0.0, w_f, 1.0 - w_f);
"""),
        (r"""            if (around > 0.0) {
                const float mean = sum / count;
                const float spread = around * sqrt(max(sum2 / count - mean * mean, 0.0) + AROUND_FLOOR / count);
                const float fitted = clamp(held_ratio, min(mean - spread, answer), max(mean + spread, answer));
""",
         r"""            if (around > 0.0) {
                float mean, spread;
                if (t_window) {
                    mean = sum / count;
                    spread = around * sqrt(max(sum2 / count - mean * mean, 0.0) + AROUND_FLOOR / count);
                } else {
                    // bbport (r57_lamp-window): one lamp's answers are 0 or 1, so a mean of fast
                    // has the variance fast * (1 - fast) / FAST_COUNT (with two lamps or more the
                    // answers vary less). The bound is at least 0.18 wide on each side and fast
                    // lags the change: a change of less than about 0.86 is not bound (see main).
                    mean = fast;
                    spread = around * sqrt((fast * (1.0 - fast) + AROUND_FLOOR) / FAST_COUNT);
                }
                const float fitted = clamp(held_ratio, min(mean - spread, answer), max(mean + spread, answer));
"""),
    ],
    TUNE: [
        (r"""                                 ///< vote of the 5x5 answers around the pixel (r42)
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
""",
         r"""                                 ///< vote of the 5x5 answers around the pixel (r42)
    bool window = true;          ///< bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW: 1 (the default):
                                 ///< the history is bound by the 5x5 answers around the pixel and
                                 ///< the frames under a moving lamp are capped by their far
                                 ///< blockers' swing, as before r57; 0 (to try): by the pixel's own
                                 ///< last frames and one fixed swing. The window cannot be centred
                                 ///< near the 8x8 workgroup's rim and is the likely source of the
                                 ///< squares fixed to the screen behind moving shadows; without it
                                 ///< a change of less than about 0.86 of the light (a penumbra
                                 ///< that becomes lit, one lamp's part of two) is not cut but fades
                                 ///< like the unguarded history, with one lamp or several. With
                                 ///< BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap keep the
                                 ///< window either way (they have no per-pixel form)
    float carry_m = 2.5f;        ///< BB_LAMP_SHADOW_CARRY, 0..5: what blocks a moving lamp within
"""),
        (r"""// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used), bit 20 the
// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
""",
         r"""// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used), bit 20 the
// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used), bit 21 the
// window (bbport r57_lamp-window, LampTuneWindow). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
"""),
        (r"""inline constexpr std::uint32_t LampTuneFollowSoft = 1u << 20; // bbport (r52_follow-soft)
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
""",
         r"""inline constexpr std::uint32_t LampTuneFollowSoft = 1u << 20; // bbport (r52_follow-soft)
inline constexpr std::uint32_t LampTuneWindow = 1u << 21;     // bbport (r57_lamp-window)
// The least BB_LAMP_SHADOW_REJECT that is not 0: one ray that disagrees with the history moves
"""),
        (r"""    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
""",
         r"""    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
    tune.window = Whole(get, "BB_LAMP_SHADOW_WINDOW", tune.window ? 1u : 0u, 1u) != 0; // r57
    tune.carry_m = Number(get, "BB_LAMP_SHADOW_CARRY", tune.carry_m, 0.0f, 5.0f);
"""),
        (r"""                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift |
                                (tune.follow_soft ? LampTuneFollowSoft : 0u); // bbport (r52_follow-soft)
    return {flags,
""",
         r"""                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift |
                                (tune.follow_soft ? LampTuneFollowSoft : 0u) | // bbport (r52_follow-soft)
                                (tune.window ? LampTuneWindow : 0u);           // bbport (r57_lamp-window)
    return {flags,
"""),
    ],
    CPP: [
        (r"""                    tune.follow_soft ? "yes" : "no");
    }
""",
         r"""                    tune.follow_soft ? "yes" : "no");
        // bbport (r57_lamp-window)
        const char* const window_what =
            tune.window        ? "the 5x5 answers of the workgroup bound the history"
            : tune.follow_soft ? "at full resolution no answer of another pixel reaches a pixel (the half-resolution "
                                 "build still shares agreeing 3x3 blocks): its history is bound by its own last "
                                 "frames and capped by one fixed swing; a change of less than about 0.86 of the "
                                 "light is not cut but fades"
                               : "the history is bound by the pixel's own last frames, but with "
                                 "BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote and its cap still take the 5x5 answers";
        std::printf("Ray traced lamps (r57): window %s (BB_LAMP_SHADOW_WINDOW): %s; 1 (the default) = the 5x5 "
                    "answers of the workgroup bound the history and their far blockers cap its frames under a "
                    "moving lamp, as before r57\n",
                    tune.window ? "yes" : "no", window_what);
    }
"""),
    ],
    TEST: [
        (r"""// bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT and its bit in word 0.
#include <array>
""",
         r"""// bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT and its bit in word 0.
// bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW and its bit in word 0.
#include <array>
"""),
        (r"""        assert(words.size() == LampTuneWordCount);
        assert(words[0] == (1u | LampTuneFollowSoft)); // new weights, view 0, the soft follow (r52)
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
""",
         r"""        assert(words.size() == LampTuneWordCount);
        // new weights, view 0, the soft follow (r52), the window (bbport r57_lamp-window)
        assert(words[0] == (1u | LampTuneFollowSoft | LampTuneWindow));
        assert(F(words[1]) == 0.35f && F(words[2]) == 0.1f && words[3] == 0u);
"""),
        (r"""        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft));
        assert(F(other[9]) == 0.75f);
""",
         r"""        const auto other = LampTuneWords(t, true, 0.1f);
        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft | LampTuneWindow)); // (r57: the window)
        assert(F(other[9]) == 0.75f);
"""),
        (r"""        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft));
    }
""",
         r"""        t.view = 100;
        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft | LampTuneWindow));
    }
"""),
        (r"""                    assert(on_words[k] == off_words[k]);
                }
""",
         r"""                    assert(on_words[k] == off_words[k]);
                }
            }
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // bbport (r57_lamp-window): BB_LAMP_SHADOW_WINDOW is on (the window, as before r57) unless the
    // variable says 0 (out of range is clamped, text that is not a whole number leaves the
    // default). In the words it is word 0's bit 21 and nothing else: bits 12-17 stay clear and bit
    // 20 (the soft follow) keeps its own value. (That the shader reads the same bit is checked by
    // rt-shadow-test --lamps: its r57 lattice block fails when the pictures with 0 and with 1 are
    // the same.)
    {
        static_assert(LampTuneWindow == 1u << 21 && (LampTuneWindow & LampTuneFollowSoft) == 0);
        static_assert((LampTuneWindow & (0x3Fu << 12)) == 0 && (LampTuneWindow & (7u << LampTuneViewShift)) == 0);
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(d.window);
        assert((LampTuneWords(d, false, 0.05f)[0] & LampTuneWindow) == LampTuneWindow);
        const LampShadowTune off = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "0"}}});
        assert(!off.window);
        assert((LampTuneWords(off, false, 0.05f)[0] & LampTuneWindow) == 0);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "1"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "5"}}}).window);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "-1"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", "no"}}}).window);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_WINDOW", ""}}}).window);
        // Round trip: the bit the words carry gives the knob back, for both values of the soft
        // follow, and the other knobs are read as without it.
        LampShadowTune again = off;
        again.window = d.window;
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(off.follow_soft == d.follow_soft && off.around == d.around && off.view == d.view);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const bool soft : {false, true}) {
            for (const bool window : {false, true}) {
                LampShadowTune t = d;
                t.follow_soft = soft;
                t.window = window;
                t.view = 3;
                const auto words = LampTuneWords(t, true, 0.05f, view.data(), 77u);
                assert(((words[0] & LampTuneWindow) != 0) == window);
                assert(((words[0] & LampTuneFollowSoft) != 0) == soft);
                assert((words[0] & (0x3Fu << 12)) == 0);
                assert(((words[0] >> LampTuneViewShift) & 7u) == 3u);
                LampShadowTune other = t;
                other.window = !window;
                const auto flipped = LampTuneWords(other, true, 0.05f, view.data(), 77u);
                assert((words[0] ^ flipped[0]) == LampTuneWindow);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(words[k] == flipped[k]);
                }
"""),
    ],
    LAB: [
        (r"""                unsigned frames = 16;
                bool follow = true;
            };
            Views moved_view = view;
""",
         r"""                unsigned frames = 16;
                bool follow = true;
                bool carried = true; // bbport (r57_lamp-window): false: the torch's lamp walks, its carrier stands
            };
            // bbport (r57_lamp-window): the lattice score. The squares behind a moving shadow sat on
            // the workgroups' grid at 0, 3, 4 and 5 px of every 8 (and on even pixels in the
            // half-resolution build), which the r52 seams (the x mod 8 == 0 lines alone) miss. The
            // mean step between neighbours (column x - 1 to x, row y - 1 to y) is folded by x and by y
            // mod 16 over the moving frames, on the steps where the history without its guards shows
            // a penumbra or a wake on that frame (a value of 0.02 to 0.98 at either pixel; so every
            // case of one walk is measured on the same steps). Two scores: a fold's largest bin over
            // its smallest (any grid), and the window's own phases, the mean of the fold mod 8's
            // bins 0, 3, 4 and 5 (where the 5x5 window changes from one pixel to the next) over that
            // of bins 1, 2, 6 and 7. Both are near 1 with no grid, but shadows that stay put on the
            // screen (the carried torch's: camera, character and torch move together) lift some
            // bins in every run, the reference included: compare the runs, not the number with 1.
            struct Lattice {
                std::vector<std::uint8_t>* mask = nullptr; // per moving frame and pixel: measured there
                bool record = false;                       // this run sets the mask
                std::array<std::array<double, 16>, 2> sum{}, count{}; // [x, y][the coordinate mod 16]
            };
            const auto fold = [&](Lattice& lattice, const std::vector<float>& picture, unsigned k) {
                const std::size_t at = std::size_t(k) * W * H;
                if (lattice.record) {
                    lattice.mask->resize(at + std::size_t(W) * H);
                    for (std::size_t i = 0; i < picture.size(); ++i)
                        (*lattice.mask)[at + i] = picture[i] > 0.02f && picture[i] < 0.98f ? 1 : 0;
                }
                const std::uint8_t* m = lattice.mask->data() + at;
                for (unsigned y = 0; y < H; ++y) {
                    for (unsigned x = 0; x < W; ++x) {
                        const std::size_t i = std::size_t(y) * W + x;
                        if (x > 0 && (m[i] | m[i - 1]) != 0) {
                            lattice.sum[0][x % 16] += std::abs(double(picture[i]) - double(picture[i - 1]));
                            lattice.count[0][x % 16] += 1.0;
                        }
                        if (y > 0 && (m[i] | m[i - W]) != 0) {
                            lattice.sum[1][y % 16] += std::abs(double(picture[i]) - double(picture[i - W]));
                            lattice.count[1][y % 16] += 1.0;
                        }
                    }
                }
            };
            const auto lattice_bins = [](const Lattice& lattice, int axis, unsigned mod) {
                std::vector<double> bins(mod, 0.0);
                for (unsigned b = 0; b < mod; ++b) {
                    double sum = 0, count = 0;
                    for (unsigned j = b; j < 16; j += mod) {
                        sum += lattice.sum[std::size_t(axis)][j];
                        count += lattice.count[std::size_t(axis)][j];
                    }
                    bins[b] = sum / std::max(count, 1.0);
                }
                return bins;
            };
            const auto lattice_score = [&](const Lattice& lattice, int axis, unsigned mod) {
                const std::vector<double> bins = lattice_bins(lattice, axis, mod);
                const auto [lo, hi] = std::minmax_element(bins.begin(), bins.end());
                return *hi / std::max(*lo, 1e-12);
            };
            const auto window_score = [&](const Lattice& lattice, int axis) {
                const std::vector<double> b = lattice_bins(lattice, axis, 8);
                return (b[0] + b[3] + b[4] + b[5]) / std::max(b[1] + b[2] + b[6] + b[7], 1e-12);
            };
            Views moved_view = view;
"""),
        (r"""            HalfDid moved_did{};           // at_half: what the two passes did on the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr) {
                restart();
                Views now = view;
""",
         r"""            HalfDid moved_did{};           // at_half: what the two passes did on the last frame
            const auto moving = [&](const Vulkan::LampShadowTune& tune, const Move& move,
                                    std::vector<float>* upscaled_out = nullptr, Lattice* lattice = nullptr) {
                restart();
                Views now = view;
"""),
        (r"""                        wobble = {off(rng), 0.0f, off(rng)};
                    }
                    place(now, walked, move.other * float(k));
                    if (k == move.frames) half_zero();
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                }
                moved_did = half_did();
""",
         r"""                        wobble = {off(rng), 0.0f, off(rng)};
                    }
                    place(now, move.carried ? walked : 0.0f, move.other * float(k));
                    if (!move.carried) flame = TorchFlame + Vec3{0, 0, -walked};
                    if (k == move.frames) half_zero();
                    frame(now, tune, &before, move.follow);
                    if (upscaled_out) settle(held, values(), k == 1);
                    if (lattice) fold(*lattice, values(), k - 1);
                }
                moved_did = half_did();
"""),
        (r"""                    return 1;
                }
            }
            for (const bool two : {false, true}) {
""",
         r"""                    return 1;
                }
                // bbport (r57_lamp-window): the lattice scores (new lines; nothing above changes). Per
                // case and build: the history without its guards (no grid of its own: the reference),
                // BB_LAMP_SHADOW_WINDOW=1 (the default) and =0 (to try), whatever the environment says.
                // Checked (with the defaults):
                //  - the last frame's pictures with 1 and with 0 differ somewhere (else bit 21 does not
                //    reach the shader; the lab is deterministic, so equal pictures differ by 0);
                //  - with the soft follow, 0's window-phase score (x and y) at most 1.1 times the
                //    reference's (with BB_LAMP_SHADOW_FOLLOW_SOFT=0 the vote keeps the window).
                // Printed only, until a first run gives the numbers and their noise: whether 1's
                // window-phase score lies above 1.1 times the reference's (the grid the score is made
                // to see; "no" in every case means it does not see it here), and 0 against 1.
                {
                    struct LatticeCase {
                        const char* name;
                        Move move;
                        bool follow;
                    };
                    Move standing = walk;
                    standing.carried = false;
                    const std::array<LatticeCase, 3> cases{{{"the character goes with its torch", walk, soft.follow},
                                                            {"the torch's lamp walks past standing casters", standing,
                                                             soft.follow},
                                                            {"the character goes with its torch, BB_LAMP_SHADOW_FOLLOW=0",
                                                             walk, false}}};
                    std::string lattice_fault, same_fault;
                    bool grid_seen = false;
                    for (const LatticeCase& lc : cases) {
                        for (const bool half_build : {false, true}) {
                            std::array<Vulkan::LampShadowTune, 3> tunes{plain, soft, soft};
                            tunes[1].window = true;
                            tunes[0].window = tunes[2].window = false;
                            for (auto& t : tunes) t.follow = lc.follow;
                            std::vector<std::uint8_t> mask;
                            mask.reserve(std::size_t(lc.move.frames) * W * H);
                            std::array<Lattice, 3> lattices{};
                            for (std::size_t r = 0; r < 3; ++r) {
                                lattices[r].mask = &mask;
                                lattices[r].record = r == 0;
                            }
                            at_half = half_build;
                            std::array<std::vector<float>, 3> last;
                            for (std::size_t r = 0; r < 3; ++r) last[r] = moving(tunes[r], lc.move, nullptr, &lattices[r]);
                            at_half = false;
                            const std::vector<std::pair<int, unsigned>> folds =
                                half_build ? std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}, {0, 16}, {1, 16}, {0, 2}, {1, 2}}
                                           : std::vector<std::pair<int, unsigned>>{{0, 8}, {1, 8}};
                            std::array<std::string, 3> text;
                            std::array<double, 3> phase{}; // the window-phase score, the larger of x and y
                            for (std::size_t r = 0; r < 3; ++r) {
                                phase[r] = std::max(window_score(lattices[r], 0), window_score(lattices[r], 1));
                                char part[96];
                                std::snprintf(part, sizeof(part), "window phases %.3f; largest over smallest bin ",
                                              phase[r]);
                                text[r] = part;
                                bool first_fold = true;
                                for (const auto& [axis, mod] : folds) {
                                    std::snprintf(part, sizeof(part), "%s%c%u %.3f", first_fold ? "" : ", ",
                                                  axis == 0 ? 'x' : 'y', mod, lattice_score(lattices[r], axis, mod));
                                    text[r] += part;
                                    first_fold = false;
                                }
                            }
                            double apart = 0;
                            std::size_t apart_n = 0;
                            for (std::size_t i = 0; i < last[1].size(); ++i) {
                                const double d = std::abs(double(last[1][i]) - double(last[2][i]));
                                apart += d;
                                apart_n += d > 0.01 ? 1 : 0;
                            }
                            apart /= double(std::max<std::size_t>(last[1].size(), 1));
                            const bool seen = phase[1] > 1.1 * phase[0];
                            grid_seen = grid_seen || seen;
                            std::printf("Torch lab, r57 lattice, %s, %.1f cm a frame, %s (%u frames, on the steps where "
                                        "the history without its guards shows a penumbra or a wake; the mean step "
                                        "between neighbours: the window-phase score, bins 0, 3, 4, 5 over 1, 2, 6, 7 of "
                                        "the fold mod 8, the larger of x and y; and per fold mod %s the largest over the "
                                        "smallest bin): the history without its guards %s; BB_LAMP_SHADOW_WINDOW=1 %s; "
                                        "BB_LAMP_SHADOW_WINDOW=0 %s. 1 above 1.1 times the reference (the grid seen): "
                                        "%s; 0 over 1: %.3f; the last frame with 0 against 1: mean difference %.5f, "
                                        "%zu pixels apart by more than 0.01\n",
                                        lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                        lc.move.frames, half_build ? "8, 16 and 2" : "8", text[0].c_str(),
                                        text[1].c_str(), text[2].c_str(), seen ? "yes" : "no",
                                        phase[2] / std::max(phase[1], 1e-12), apart, apart_n);
                            if (!lc.move.carried) {
                                // A standing caster's penumbra under the walking lamp: is it darker or
                                // lighter on the mean than the true picture of the last frame (a frame
                                // cap that depends on this frame's ray would make it darker)?
                                const auto standing_true = truth(moved_view, soft, 64);
                                std::array<double, 3> bias{};
                                std::size_t n = 0;
                                for (std::size_t i = 0; i < standing_true.size(); ++i) {
                                    if (!(standing_true[i] > 0.05f && standing_true[i] < 0.95f)) continue;
                                    ++n;
                                    for (std::size_t r = 0; r < 3; ++r) bias[r] += double(last[r][i]) - standing_true[i];
                                }
                                for (double& b : bias) b /= double(std::max<std::size_t>(n, 1));
                                std::printf("Torch lab, r57, %s, %.1f cm a frame, %s: the last frame's mean of the picture "
                                            "minus the true one over the true penumbra (%zu pixels; below 0 darker; printed "
                                            "only): the history without its guards %+.4f; BB_LAMP_SHADOW_WINDOW=1 %+.4f; "
                                            "BB_LAMP_SHADOW_WINDOW=0 %+.4f\n",
                                            lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                            n, bias[0], bias[1], bias[2]);
                            }
                            const std::string where =
                                std::string(lc.name) + (half_build ? ", half-resolution build" : ", full resolution");
                            if (checked && same_fault.empty() && !(apart > 0.0)) same_fault = where;
                            if (checked && soft.follow_soft && lattice_fault.empty() && !(phase[2] <= 1.1 * phase[0])) {
                                lattice_fault = where;
                            }
                        }
                    }
                    std::printf("Torch lab, r57 lattice, %.1f cm a frame: the window's grid is seen by the score with "
                                "BB_LAMP_SHADOW_WINDOW=1 in %s case (printed only; \"no case\" means the score is blind "
                                "to it in this lab)\n",
                                speed * 100.0f, grid_seen ? "at least one" : "no");
                    if (!same_fault.empty()) {
                        std::fprintf(stderr, "BB_LAMP_SHADOW_WINDOW=0 and =1 give the same picture: word 0 bit 21 does not "
                                             "reach the shader (%s, %.1f cm a frame)\n", same_fault.c_str(), speed * 100.0f);
                        return 1;
                    }
                    if (!lattice_fault.empty()) {
                        std::fprintf(stderr, "without the window a moving shadow still lines up with the window's grid (%s, "
                                             "%.1f cm a frame)\n", lattice_fault.c_str(), speed * 100.0f);
                        return 1;
                    }
                }
            }
            for (const bool two : {false, true}) {
"""),
        (r"""                second = two;
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
""",
         r"""                second = two;
                // (which: 0 the default, 1 the history without its guards; bbport r44_half-area-lamp:
                // 2 the default in the half-resolution build; bbport r57_lamp-window: 3 the default
                // with BB_LAMP_SHADOW_WINDOW=0, printed only)
                std::array<std::array<double, 5>, 4> left{};
                place(view, 0.0f, 0.0f);
                const auto old_true = truth(view, soft, 64);
                place(view, 0.0f, 30.0f);
                const auto new_true = truth(view, soft, 64);
                Vulkan::LampShadowTune own = soft;
                own.window = false;
                for (int which = 0; which < 4; ++which) {
                    const Vulkan::LampShadowTune& tune = which == 1 ? plain : which == 3 ? own : soft;
                    at_half = which == 2;
                    restart();
"""),
        (r"""                            left[1][0], left[1][1], left[1][2], left[1][3], left[1][4], left[2][0], left[2][1],
                            left[2][2], left[2][3], left[2][4]);
                if (checked && !(left[0][1] < 0.2 && left[0][2] < 0.15 && left[0][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers (%s)\n", two ? "two lamps" : "one lamp");
""",
         r"""                            left[1][0], left[1][1], left[1][2], left[1][3], left[1][4], left[2][0], left[2][1],
                            left[2][2], left[2][3], left[2][4]);
                // bbport (r57_lamp-window): new line, no check (no bound exists for it yet; the
                // checks below take the knobs as the environment has them).
                std::printf("Torch lab, r57, a figure is gone from one frame to the next, %s: the same with "
                            "BB_LAMP_SHADOW_WINDOW=0 (not checked; the per-pixel bound cuts only a change of more than "
                            "about 0.86): %.3f / %.3f / %.3f / %.3f / %.3f\n",
                            two ? "two lamps" : "one lamp", left[3][0], left[3][1], left[3][2], left[3][3], left[3][4]);
                if (checked && !(left[0][1] < 0.2 && left[0][2] < 0.15 && left[0][2] < 0.5 * left[1][2])) {
                    std::fprintf(stderr, "a shadow that is gone lingers (%s)\n", two ? "two lamps" : "one lamp");
"""),
    ],
    DOC: [
        (r"""  switch does not change it. The two follow images are made with the lamp history either way.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
""",
         r"""  switch does not change it. The two follow images are made with the lamp history either way.
- **Window-free lamp history guard, to try (r57).** `BB_LAMP_SHADOW_WINDOW`, read once at start
  (`ReadLampShadowTune`, `LampShadowTune::window`), default 1, sets tuning word 0 bit 21
  (`LampTuneWindow`). 1 is the pass as before r57. With 0, in `point_shadow_ray.comp` `main()` (the
  history blend) the ghost clamp no longer takes the 5x5 answers of the pixel's 8x8 workgroup: it is
  centred on the pixel's own mean of its last few frames (`fast`), with the deviation `FAST_COUNT` (4)
  one-lamp answers would have. Under a moving lamp the frame cap of the soft follow's "stands" share
  takes one fixed swing (`OWN_SWING`, 1) in place of the window's mean. The window could not be centred
  near the workgroup's rim, so runs of 3, 1, 1 and 3 pixels shared one window; that is the likely source
  of the squares fixed to the screen behind moving shadows (diagnosis, not yet confirmed in the game).
  With `BB_LAMP_SHADOW_FOLLOW_SOFT=0` the vote and its cap still take the window (they have no per-pixel
  form), so only the soft follow gives a window-free pass; the half-resolution build still shares the
  answers of agreeing 3x3 blocks. Known cost to the picture with 0 (desk model, not a GPU run): the
  per-pixel bound cuts only a change of more than about 0.86 of the light at once, with one lamp or
  several; a smaller one (a penumbra that becomes lit, one lamp's part of two) fades like the history
  without its guards, about 16 frames in place of 1. So the torch lab's "a shadow that is gone lingers
  (two lamps)" check is expected to fail with 0, which is why 1 stays the default. No experiment bit
  gates it, so the switch does not change it. Expected cost with 0 and the soft follow (not measured):
  25 shared-memory reads a pixel fewer, a few ALU more; with `BB_LAMP_SHADOW_FOLLOW_SOFT=0` unchanged;
  no memory or binding change.
- **Startup-only items.** The motion store size and thread pinning are read once at start.
"""),
    ],
}

def sha(b):
    return hashlib.sha256(b).hexdigest()


def crlf(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def transform(path, raw, forward):
    """raw (bytes) with the file's edits applied (forward) or taken back; None and the reason."""
    t = raw.decode("utf-8")
    nl = "\r\n" if "\r\n" in t else "\n"
    pairs = EDITS[path] if forward else list(reversed(EDITS[path]))
    for old, new in pairs:
        a, b = (crlf(old, nl), crlf(new, nl)) if forward else (crlf(new, nl), crlf(old, nl))
        n = t.count(a)
        if n != 1:
            return None, "%s: anchor found %d times (want 1): %a" % (path, n, a[:100])
        t = t.replace(a, b)
    return t.encode("utf-8"), None


def state():
    """Per file: 'orig', 'patched' or the reason it is neither; and the bytes read."""
    states, texts = {}, {}
    for path in EDITS:
        full = ROOT + path
        if not os.path.isfile(full):
            states[path] = "missing (%s)" % full
            continue
        raw = open(full, "rb").read()
        texts[path] = raw
        h = sha(raw)
        orig, patched = SUMS[path]
        states[path] = "orig" if h == orig else "patched" if h == patched else "unknown content (sha256 %s)" % h
    return states, texts


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r57_lamp-window.py check|apply|revert   (the tree: R57_ROOT, else the current directory)")
        return 2
    if not os.path.isfile(ROOT + CPP):
        print("not a source tree: %s (set R57_ROOT)" % ROOT)
        return 2
    n = len(EDITS)
    states, texts = state()
    values = set(states.values())
    if values == {"orig"}:
        out = {}
        for path in EDITS:
            new, why = transform(path, texts[path], True)
            if new is None:
                print(why)
                return 1
            if sha(new) != SUMS[path][1]:
                print("%s: the patched text is not the one the patch was written for" % path)
                return 1
            back, why = transform(path, new, False)
            if back != texts[path]:
                print("%s: revert would not give back the original bytes" % path)
                return 1
            out[path] = new
        if mode == "check":
            print("not applied in %s (all %d files are the originals; the patch applies cleanly)" % (ROOT, n))
            return 0
        if mode == "revert":
            print("not applied in %s: nothing to revert" % ROOT)
            return 0
    elif values == {"patched"}:
        out = {}
        for path in EDITS:
            old, why = transform(path, texts[path], False)
            if old is None:
                print(why)
                return 1
            if sha(old) != SUMS[path][0]:
                print("%s: revert would not give back the original bytes" % path)
                return 1
            out[path] = old
        if mode == "check":
            print("applied in %s (all %d files are as the patch made them)" % (ROOT, n))
            return 0
        if mode == "apply":
            print("already applied in %s" % ROOT)
            return 0
    else:
        for path, s in states.items():
            print("%s: %s" % (path, s))
        print("neither applied nor not applied in %s: nothing changed" % ROOT)
        return 1
    # Nothing is changed in place: every new text goes to a file beside its target first, then
    # each is moved over its target. If a step fails, what was already moved is put back.
    done = []
    try:
        for path, b in out.items():
            with open(ROOT + path + TMP, "wb") as f:
                f.write(b)
        for path in out:
            os.replace(ROOT + path + TMP, ROOT + path)
            done.append(path)
    except OSError as e:
        print("failed in %s (%s); putting back what was changed" % (ROOT, e))
        for path in done:
            with open(ROOT + path, "wb") as f:
                f.write(texts[path])
        for path in out:
            if os.path.exists(ROOT + path + TMP):
                os.remove(ROOT + path + TMP)
        return 1
    print("%s in %s" % ("applied" if mode == "apply" else "reverted", ROOT))
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
