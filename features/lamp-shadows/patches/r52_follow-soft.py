# r52_follow-soft: the ray traced lamp shadow pass looks a pixel's history up at both places a
# moving lamp's history can be, mixed by a follow state each pixel keeps, in place of one place
# picked by a yes/no vote of the 5x5 answers around the pixel. check|apply|revert.
#
# WHY (the confirmed cause of the "squares in moving torch shadows"): under a moving lamp
# (a carried torch) the averaging history of point_shadow_ray.comp is looked up either where the
# surface was or where the lamp's motion puts it, chosen by a hard vote ("carried": more near
# blockers than far ones) over a 5x5 window that is confined to the 8x8 compute workgroup (16x16
# pixels in the half-resolution build's first pass). The vote flips at workgroup lines, about 90%
# of the result is history that is written back, so the choice stays as square steps on the
# 8 px grid (16 px with the half-resolution path); in the game they went away with
# BB_LAMP_SHADOW_FOLLOW=0 and not with graphics_lamp_shadow_half=0.
#
# WHAT IT DOES (point_shadow_ray.comp, HISTORY_BLEND):
#  - Two R32F images beside the history (follow_prev / follow_cur, taken in turn with it): a
#    follow state per pixel, log-odds in [-5, 5]; above 0 what blocks the pixel's strongest lamp
#    moves with it, below 0 it stands, 0 no opinion.
#  - The pixel's own ray to its strongest lamp gives the evidence: +1 blocked within word 32
#    (BB_LAMP_SHADOW_CARRY) of the lamp, -1 blocked further off, 0 free or not cast. The state is
#    the one found in the history (its "moves" part where the lamp's motion puts it, its "stands"
#    part where the surface was) times 0.95, plus 3 times the evidence.
#  - Both places are read (the same projection and 4-tap depth test as blendHistory) and mixed
#    by w = logistic(state + how well each place fits this frame's answer). Where w is unsure and
#    the two places differ, the history is shortened. What is not followed trails as before:
#    the state's "moves" share by the lamp's whole step, its "stands" share by the far blockers'
#    swing; that slip bounds the frames by BB_LAMP_SHADOW_TRAIL as before.
#  - The state is made whole over the history taps found at each place. Where nothing is found
#    where the surface was, the other place is taken only where the state is above 0 (the
#    trail bounds only the share that is not followed). A lamp whose step is LampTrack::Lost
#    (it was not there the frame before) has no history under its shadows: nothing is looked
#    up for its pixels and the state starts again from the evidence.
#  - Nothing of w comes from the workgroup's shared answers. The 5x5 window still bounds the
#    history (BB_LAMP_SHADOW_CLAMP) and gives the far blockers' mean swing, which sets the
#    frame cap of the "stands" share (k_win): that one input is still confined to the
#    workgroup, as it is with BB_LAMP_SHADOW_FOLLOW=0.
#  - BB_LAMP_SHADOW_VIEW=6 under a moving lamp: green the share looked up where its motion puts
#    it, blue the rest, red the clamp as before; under a lamp that stands, dim: the state.
#
# THE KNOB: BB_LAMP_SHADOW_FOLLOW_SOFT, 0 or 1, default 1, read once at start
# (lamp_shadow_tune.h LampShadowTune::follow_soft), word 0 bit 20 of the sixteen tuning words
# (LampTuneFollowSoft). It reaches the shader only with the repair (MODE_REPAIR); with experiment
# 35184372088832 set the pass of before r41 runs and nothing of this. With
# BB_LAMP_SHADOW_FOLLOW=0 and the soft follow on, the soft branch still runs with one place only
# (the lamp's motion is zeroed on the host) and the state sets the slip; that is not the
# configuration of before r52 (that one is FOLLOW=0 with FOLLOW_SOFT=0). It is env-only, no
# experiment bit, so engine_previous_paths leaves it on: listed in
# engine/docs/renderer-performance-0.9.43.md under "Not restored by the switch".
# Log line at start: "Ray traced lamps (r52): soft follow yes/no ...".
# BIT OFF (BB_LAMP_SHADOW_FOLLOW_SOFT=0): the shader runs the old vote, slip and look-up
# statement for statement and stores nothing in the follow images: every new read, store and
# factor of r52 in the pass is under the bit; outside it only declarations moved up and the
# look-up's result went into `held` (same arguments, same short-circuit). Host side the two
# images (R32F, 4 bytes a pixel each) are still made, laid out, zeroed once and bound. This is
# shown at source level only, not on SPIR-V or a GPU.
# Host: vk_point_shadow.cpp makes the two images with the history (room counted with it:
# 2 * (8 + 4) bytes a pixel, also in BeginApart), lays them out and zeroes them on first use,
# binds them as 9 and 10 (half-resolution build: 11 and 12) in every ray traced lamp dispatch.
# Without a ray pipeline in use (lamp shadows off, no ray tracing) they are never made.
#
# NOT DONE: a centred window across workgroups or a second dispatch; instance classes in the
# TLAS; any change to HalfAnswer, the rays, carry_m or the clamp constants; R16F storage. The
# older draft r49 (word 0 bits 12-17) is not included: those bits stay unused; the evidence line
# has a comment where a per-pixel contact term could change the evidence. lamp-shadow-tune-test
# is still built by CMake only, not by build.sh --test (audit action 7, which adds the lab tests
# together). The seam numbers are printed, not checked: a bound needs a GPU run's numbers first.
# NOTHING HAS BEEN BUILT, RUN OR MEASURED: no game test, no GPU run of the labs, no timing.
#
# HOW TO TEST:
#  1. lamp-shadow-tune-test (knob default on, 0 off, only word 0 bit 20 changes).
#  2. rt-shadow-test --pipelines (builds the full and, new, the half-resolution lamp pipeline
#     with their r52 layouts). rt-shadow-test --lamps with BB_LAMP_SHADOW_FOLLOW_SOFT=0: every
#     existing line as before (the new "r52 seams" lines are added; the ms lines vary between
#     runs anyway) and the new check that the follow images stay 0; with 1 (or unset): the
#     follow images hold a state after the walk (the shader reads the host's bit), every
#     existing check passes, the walk/run penumbra and far errors no worse, the seam numbers of
#     the default down to the "looked up where the ground was only" level. --speed with 0 and 1.
#  3. Game, graphics_ao_quality=1 (HQ GTAO), torch out, the spot of squares_lamp_follow.jpg; a still
#     shot, a straight walk, a run, a stop; BB_LAMP_SHADOW_FOLLOW_SOFT=0 against 1 at
#     graphics_lamp_shadow_half=1 and 0. The no-steps reference is BB_LAMP_SHADOW_FOLLOW=0 with
#     BB_LAMP_SHADOW_FOLLOW_SOFT=0 (the case the game showed without steps), once per half
#     setting; FOLLOW=0 with FOLLOW_SOFT=1 is a case of its own. VIEW=6 walking: no
#     straight-edged blocks on the 8/16 px grid with 1. The normal picture: no steps on the grid.
#     Carried shadows (arm, weapon, stick) still move with the torch, no copy left on the floor;
#     VIEW=5 stays green under them. Static shadows under the moving torch (plants, rocks, wall
#     edges): no new ghost or doubled edge, and VIEW=5 shows no steps at the 8/16 px lines inside
#     them (their frame cap still takes the workgroup's far swing). Drawing the torch: no
#     speckle of old and new history in its first frames. BB_GPU_PROFILE=1, "Lighting: point
#     shadows", 0 against 1; the 600-frame half-resolution line keeps its ray counts; the r52 log
#     line, no validation errors.
#
# THE TREE: R52_ROOT, else the current directory (which must then be a source tree's root).
# Every file is guarded by the sha256 of its original and of its patched content: check says
# "not applied" or "applied" (or why neither), apply works only on seven originals (and says
# "already applied" on seven patched files), revert only on seven patched files and gives back
# the original bytes. Line ends are kept (all seven are CRLF). New texts are written beside
# their targets and moved over them; a failure puts back what was moved.

import hashlib
import os
import sys

ROOT = os.environ.get("R52_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"

COMP = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
TUNE = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"
HDR = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.h"
CPP = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
TEST = "engine/tests/test_lamp_shadow_tune.cpp"
LAB = "engine/tests/test_rt_shadows.cpp"
DOC = "engine/docs/renderer-performance-0.9.43.md"
TMP = ".r52tmp"

# sha256 of each file: (original, patched).
SUMS = {
    COMP: ('e4c024793956b8ddd6923d10516220c163a689e4213fe59bdf28e6873b000e51', 'c4c48bef62dda61af13be7ec086a51e2c295a64d8b491a872351735b4ddeaf52'),
    TUNE: ('f7f71d2305e59d9d5c5de03522c57b1aab1f0db534db8fb097f514032ac42d44', 'e9d458f128fa6850eb96f01e2d5b7a15ca9a6f0e92a9f89fb0e2897415b498e7'),
    HDR: ('b67e88497248a402744005a0bed2dc8a9506f1bb009239a1a0f2a7a67f562409', '528a322deba350036146addc778628b31c101a023d3b40eea0e7e0b9b5b04e57'),
    CPP: ('82ca5f728d5dc40acae8cf9261eac0c8fbd7a44adc996cdb8969e26eaed828cf', 'c16ef5da49d50f56c5a2db032d4920ff681c353c071c2412582aace4694f417b'),
    TEST: ('b0fbe15cc95306778e5c13ddcc2c4dd7b02fb31a9626571d692e5ff7e7dbd070', '3f469afb8af03f6ad6b8227fb7532fe091fe36f14b678bec3aae87b7ee8e3fa6'),
    LAB: ('2c3e37534cc79c672ef7c433aff73655916e0ffa78f8fccfb9d205b6dd9496c4', '6e712cf8975ad75e4cf849bff0bdcbf5987679091209d38de22ce5a041f4ae23'),
    DOC: ('11b19fecdf24091f871dd0f1818d1e162b7bc39ef10c392a8715a147d73d8ffd', '7b71efa1db16c76568ce091470cdd3b0d4071a42cd33a5ec1c52321d1c7295ff'),
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Written with LF; the file's CRLF is put in.
EDITS = {
    COMP: [
        # The follow state's images.
        (r"""#else
layout(set = 0, binding = 8, rgba16f) uniform writeonly image2D history_cur;
#endif
""",
         r"""#else
layout(set = 0, binding = 8, rgba16f) uniform writeonly image2D history_cur;
#endif
// bbport (r52_follow-soft): the follow state, one float a pixel, kept beside the history (two
// images taken in turn with it): how sure the pass is that what blocks the pixel's strongest
// lamp moves with that lamp, as log-odds (above 0 it does, below 0 it stands, 0 no opinion, at
// most FOLLOW_MOST either way). With word 0 bit 20 (t_follow_soft) written wherever the
// averaging (HISTORY_BLEND) writes its history and read only through history texels that passed
// the depth test (historyAt); without it neither read nor written.
#ifdef HALF
layout(set = 0, binding = 11, r32f) uniform readonly image2D follow_prev;
layout(set = 0, binding = 12, r32f) uniform image2D follow_cur;
#else
layout(set = 0, binding = 9, r32f) uniform readonly image2D follow_prev;
layout(set = 0, binding = 10, r32f) uniform writeonly image2D follow_cur;
#endif
"""),
        (r"""uint t_view = 0u;               // debug view (BB_LAMP_SHADOW_VIEW)
""",
         r"""uint t_view = 0u;               // debug view (BB_LAMP_SHADOW_VIEW)
bool t_follow_soft = false;     // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT
"""),
        (r"""    t_view = (f >> 8u) & 7u;
""",
         r"""    t_view = (f >> 8u) & 7u;
    t_follow_soft = (f & (1u << 20u)) != 0u; // bbport (r52_follow-soft); bits 12-17 are not used
"""),
        # The look-up at one place, not made whole, with the follow state there.
        (r"""    return true;
}

shared uint group_trace;
""",
         r"""    return true;
}

// bbport (r52_follow-soft): the follow share of the history, worked out per pixel from what the
// pixel has itself: its own ray's blocker, the follow state the history holds at the two places
// it may be looked up at, and how well each place fits this frame's answer. Nothing of it comes
// from the workgroup's shared answers.
const float FOLLOW_EVIDENCE = 3.0; // log-odds one blocked ray adds (near the lamp) or takes (far)
const float FOLLOW_MOST = 5.0;     // the state's bound either way (logistic: 0.993)
const float FOLLOW_KEEP = 0.95;    // the share of the state kept a frame; the rest fades to 0
const float FOLLOW_AGREE = 0.5;    // weight of this frame's answer's fit to each place (not kept)
const float UNSURE_FROM = 0.2;     // the history is shortened where the share is unsure and the
const float UNSURE_ALL = 0.6;      // two places differ: from, wholly
const float NEW_LAMP_STEP = 500.0; // m, half of LampTrack::Lost (1000 m): the step the host hands
                                   // for a lamp that was not there the frame before

// bbport (r52_follow-soft): the follow state the frame before left at q. A value the pass does
// not store (not a number, or beyond FOLLOW_MOST) counts as no opinion.
float stateAt(ivec2 q) {
    const float x = imageLoad(follow_prev, q).x;
    return abs(x) <= FOLLOW_MOST ? x : 0.0;
}

// bbport (r52_follow-soft): blendHistory's look-up at one place, not made whole: sum = the found
// taps' bilinear weights times (ratio, frames, fast), found = those weights' sum, lam = those
// weights times the follow state there. Nothing found: all three 0.
void historyAt(vec3 P, uint history_at, vec3 moved, out vec3 sum, out float found, out float lam) {
    sum = vec3(0.0);
    found = 0.0;
    lam = 0.0;
    const vec4 v = vec4(P, 1.0);
    const vec3 p = vec3(dot(row(history_at + 2u), v), dot(row(history_at + 6u), v), dot(row(history_at + 10u), v)) - moved;
    const vec4 clip = vec4(dot(row(history_at + 14u), vec4(p, 1.0)), dot(row(history_at + 18u), vec4(p, 1.0)),
                           dot(row(history_at + 22u), vec4(p, 1.0)), dot(row(history_at + 26u), vec4(p, 1.0)));
    if (!(clip.w > 1e-4)) {
        return;
    }
    const vec2 ndc = clip.xy / clip.w;
    const vec2 was = vec2(ndc.x * 0.5 + 0.5, 0.5 - ndc.y * 0.5) * size;
    if (any(lessThan(was, vec2(0.0))) || any(greaterThanEqual(was, size))) {
        return;
    }
    const vec2 centre = was - 0.5;
    const ivec2 h0 = ivec2(floor(centre));
    const vec2 part = centre - vec2(h0);
    for (int k = 0; k < 4; ++k) {
        const ivec2 o = ivec2(k & 1, k >> 1);
        const float w = (o.x == 0 ? 1.0 - part.x : part.x) * (o.y == 0 ? 1.0 - part.y : part.y);
        const ivec2 q = h0 + o;
        if (w > 0.004 && all(greaterThanEqual(q, ivec2(0))) && all(lessThan(q, ivec2(size)))) {
            const vec4 h = imageLoad(history_prev, q);
            if (h.g > 0.0 && abs(h.g - p.z) < 0.03 * p.z + 0.02) {
                sum += w * h.rba;
                found += w;
                lam += w * stateAt(q);
            }
        }
    }
}

shared uint group_trace;
"""),
        # The comment of the averaging: what the soft follow does.
        (r"""    //    that was not there the frame before (a very large step) has no history under its
    //    shadows.
    const float answer = ratio; // what this frame's rays said (view 1)
""",
         r"""    //    that was not there the frame before (a very large step) has no history under its
    //    shadows.
    //  - bbport (r52_follow-soft): with BB_LAMP_SHADOW_FOLLOW_SOFT (word 0 bit 20, the default)
    //    no vote picks the place. Each pixel keeps a follow state (follow_prev, follow_cur):
    //    its own blocked ray adds FOLLOW_EVIDENCE where the blocker lies within word 32 of the
    //    lamp and takes it away where it lies further off, and the state fades by FOLLOW_KEEP a
    //    frame; its "moves with the lamp" part is found where the lamp's motion puts it, its
    //    "stands" part where the surface was. The history is read at both places and mixed by
    //    w, the logistic of the state plus how well each place fits this frame's answer. What
    //    is not followed trails: the state's "moves" share by the lamp's whole step, its
    //    "stands" share by the swing of the far blockers around the pixel. Where w is unsure
    //    and the two places differ the history is shortened (UNSURE_FROM, UNSURE_ALL). Where
    //    nothing is found where the surface was, the other place is taken only with a state
    //    above 0. Under a lamp that was not there the frame before (NEW_LAMP_STEP) nothing is
    //    looked up. The 5x5 answers still bound the history (word 33) and give the swing,
    //    nothing else.
    const float answer = ratio; // what this frame's rays said (view 1)
"""),
        # A pixel that takes its block's answer takes its block pixel's follow state too.
        (r"""            imageStore(history_cur, px, vec4(ratio, P.z, h.b, h.a));
""",
         r"""            imageStore(history_cur, px, vec4(ratio, P.z, h.b, h.a));
            if (t_follow_soft) { // bbport (r52_follow-soft)
                imageStore(follow_cur, px, imageLoad(follow_cur, px & ~1));
            }
"""),
        # The look-up: the soft follow, or the vote of before (bit 20 clear) statement for
        # statement; then the part both share.
        (r"""        // carried: what shadows this place moves with the lamp. slip: how far the place the
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
""",
         r"""        float fast = answer;
        float held_ratio = 1.0, held_frames = 0.0, held_fast = 1.0;
        float slip = 0.0;
        bool held = false;
        // bbport (r52_follow-soft): unsure: 4 w (1 - w) times how far the two places' ratios lie
        // apart (0 with bit 20 clear); lam_kept: the follow state this pixel keeps (0 with bit
        // 20 clear).
        float unsure = 0.0;
        float lam_kept = 0.0;
        if (t_follow_soft) {
            // bbport (r52_follow-soft): the evidence of this pixel's own ray to its strongest
            // lamp: +1 blocked within word 32 of the lamp, -1 blocked further off, 0 free or not
            // cast. Taken while the lamp stands as well, so the state is there when it moves.
            // (A per-pixel contact term, a near blocker hit right above the receiver counted as
            // standing, would change e here; there is none.)
            float e = 0.0;
            if (top_at != 0u && top_left >= 0.0) {
                e = top_left < word(history_at + 32u) ? 1.0 : -1.0;
            }
            const bool two = top_moved != vec3(0.0);
            // A lamp that was not there the frame before has no history under its shadows (its
            // step is LampTrack::Lost): nothing is looked up, the state starts from the evidence.
            const bool new_lamp = top_step >= NEW_LAMP_STEP;
            float w_f = 0.0; // the share looked up where the lamp's motion puts it
            if ((history_flags & HISTORY_READ) != 0u && !new_lamp) {
                vec3 sa, sf;
                float fa, ff, la, lf;
                historyAt(P, history_at, vec3(0.0), sa, fa, la);
                sf = sa;
                ff = fa;
                lf = la;
                if (two) {
                    historyAt(P, history_at, top_moved, sf, ff, lf);
                }
                // The state's "moves with the lamp" part (above 0) is taken where the lamp's
                // motion puts it, its "stands" part (below 0) where the surface was, each made
                // whole over the taps found there (0 where none is); then faded, and moved by
                // this pixel's own evidence.
                const float la_whole = fa > 0.01 ? la / fa : 0.0, lf_whole = ff > 0.01 ? lf / ff : 0.0;
                const float prior = max(lf_whole, 0.0) + min(la_whole, 0.0);
                lam_kept = clamp(prior * FOLLOW_KEEP + FOLLOW_EVIDENCE * e, -FOLLOW_MOST, FOLLOW_MOST);
                if (two) {
                    float agree = 0.0;
                    if (fa > 0.01 && ff > 0.01) {
                        const float ra = sa.x / fa, rf = sf.x / ff;
                        const float ca = clamp(ra, 0.05, 0.95), cf = clamp(rf, 0.05, 0.95);
                        agree = FOLLOW_AGREE *
                                (answer * log(cf / ca) + (1.0 - answer) * log((1.0 - cf) / (1.0 - ca)));
                        unsure = abs(ra - rf);
                    }
                    w_f = 1.0 / (1.0 + exp(-(lam_kept + agree)));
                    // Nothing found where the surface was: the place the lamp's motion puts it
                    // is taken only where the state says what blocks the pixel moves with the
                    // lamp (the trail below bounds only the share that is not followed); else
                    // nothing is held and the pixel starts again.
                    if (!(fa > 0.01) && lam_kept <= 0.0) {
                        w_f = 0.0;
                    }
                    unsure *= 4.0 * w_f * (1.0 - w_f);
                }
                const float got = (1.0 - w_f) * fa + w_f * ff;
                if (got > 0.01) {
                    const vec3 both = (1.0 - w_f) * sa + w_f * sf;
                    held_ratio = both.x / got;
                    held_frames = both.y;
                    held_fast = both.z / got;
                    held = true;
                }
            } else {
                lam_kept = FOLLOW_EVIDENCE * e;
            }
            // What is not followed trails: the state's share that moves with the lamp by the
            // lamp's whole step, its share that stands by the far blockers' mean swing (0 with
            // no opinion); m a frame, as the vote's slip below.
            const float s = 1.0 / (1.0 + exp(-lam_kept));
            if (top_step > 0.0) {
                const float c_plus = max(2.0 * s - 1.0, 0.0), c_minus = max(1.0 - 2.0 * s, 0.0);
                const float k_win = far_n > 0.0 ? swing / far_n : 0.0;
                slip = (1.0 - w_f) * top_step * (c_plus + c_minus * k_win);
                looked = vec3(0.0, w_f, 1.0 - w_f);
            } else {
                looked = 0.25 * vec3(0.0, s, 1.0 - s);
            }
        } else {
            // carried: what shadows this place moves with the lamp. slip: how far the place the
            // history is looked up at is off for every frame it holds, m.
            const bool carried = near_n > far_n;
            const bool follows = carried && top_moved != vec3(0.0);
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
            held = (history_flags & HISTORY_READ) != 0u &&
                   blendHistory(P, history_at, follows ? top_moved : vec3(0.0), held_ratio, held_frames, held_fast);
        }
        if (held) {
"""),
        (r"""                frames = min(frames, trail / slip);
            }
            if (t_reject > 0.0 && frames > 1.5) {
""",
         r"""                frames = min(frames, trail / slip);
            }
            if (t_follow_soft) {
                // bbport (r52_follow-soft): a share that is a guess between two places apart
                frames *= 1.0 - smoothstep(UNSURE_FROM, UNSURE_ALL, unsure);
            }
            if (t_reject > 0.0 && frames > 1.5) {
"""),
        (r"""        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));
""",
         r"""        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));
        if (t_follow_soft) { // bbport (r52_follow-soft)
            imageStore(follow_cur, px, vec4(lam_kept));
        }
"""),
        (r"""        // that stands; red: how much of it this frame's answers around the pixel took away.
        // The history and the half-resolution answers hold the ratio as always.
""",
         r"""        // that stands; red: how much of it this frame's answers around the pixel took away.
        // bbport (r52_follow-soft): with the soft follow, 6 under a moving lamp: green the share
        // of the history looked up where its motion puts it, blue the rest; under a lamp that
        // stands, dim: the follow state (green moves with the lamp, blue stands).
        // The history and the half-resolution answers hold the ratio as always.
"""),
    ],
    TUNE: [
        (r"""    bool follow = true;          ///< BB_LAMP_SHADOW_FOLLOW: the history is looked up where a
                                 ///< moving lamp's motion puts it (LampTrack); 0: where the
                                 ///< surface was
""",
         r"""    bool follow = true;          ///< BB_LAMP_SHADOW_FOLLOW: the history is looked up where a
                                 ///< moving lamp's motion puts it (LampTrack); 0: where the
                                 ///< surface was
    bool follow_soft = true;     ///< bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT: under a
                                 ///< moving lamp the history is looked up at both places (where the
                                 ///< surface was, where the lamp's motion puts it) and mixed by a
                                 ///< follow state each pixel keeps; 0: one of them, picked by the
                                 ///< vote of the 5x5 answers around the pixel (r42)
"""),
        (r"""// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
""",
         r"""// Word 0 (point_shadow_ray.comp loadTune): bit 0 the new weights, bit 1 the game's lamps use the
// inverse-square curve, bits 8-10 the view (bits 4-6 were r41's rim rays: not used), bit 20 the
// soft follow (bbport r52_follow-soft, LampTuneFollowSoft; bits 12-17: not used). Word 3: the
// frame counter (the sample points' sequence). The other words of 1-9, floats: 1 clearance, 2
"""),
        (r"""inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 6;
""",
         r"""inline constexpr std::uint32_t LampTuneViewShift = 8, LampTuneViewMax = 6;
inline constexpr std::uint32_t LampTuneFollowSoft = 1u << 20; // bbport (r52_follow-soft)
"""),
        (r"""    tune.follow = Whole(get, "BB_LAMP_SHADOW_FOLLOW", tune.follow ? 1u : 0u, 1u) != 0;
""",
         r"""    tune.follow = Whole(get, "BB_LAMP_SHADOW_FOLLOW", tune.follow ? 1u : 0u, 1u) != 0;
    tune.follow_soft = Whole(get, "BB_LAMP_SHADOW_FOLLOW_SOFT", tune.follow_soft ? 1u : 0u, 1u) != 0; // r52
"""),
        (r"""                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift;
""",
         r"""                                std::min(tune.view, LampTuneViewMax) << LampTuneViewShift |
                                (tune.follow_soft ? LampTuneFollowSoft : 0u); // bbport (r52_follow-soft)
"""),
        (r"""                                              ///< before, m: no history holds under its shadows
""",
         r"""                                              ///< before, m: no history holds under its shadows
                                              ///< (bbport r52_follow-soft: point_shadow_ray.comp
                                              ///< NEW_LAMP_STEP is half of it; tied by this
                                              ///< comment only)
"""),
    ],
    HDR: [
        (r"""    bool history_fresh = false;
    std::array<float, 12> last_view{}, pending_view{};
""",
         r"""    bool history_fresh = false;
    // bbport (r52_follow-soft): the follow state beside the history (point_shadow_ray.comp
    // follow_prev, follow_cur), one R32F a pixel, taken in turn with it (history_index); made
    // with the history, laid out and zeroed on first use.
    std::array<OwnImage, 2> follow;
    std::array<bool, 2> follow_laid_out{};
    std::array<float, 12> last_view{}, pending_view{};
"""),
    ],
    CPP: [
        (r"""constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
""",
         r"""constexpr auto HistoryFormat = vk::Format::eR16G16B16A16Sfloat;
// bbport (r52_follow-soft): the follow state (a storage format every Vulkan device has)
constexpr auto FollowFormat = vk::Format::eR32Sfloat;
"""),
        (r"""    if (rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage},
""",
         r"""    // bbport (r52_follow-soft): bindings 9 and 10, the follow state
    if (rt_shadow.Capturing() &&
        !EffectPass::Create(instance, ray_set_layout, ray_layout, ray_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageImage},
"""),
        (r"""                    tune.self_m, tune.view);
    }
""",
         r"""                    tune.self_m, tune.view);
        std::printf("Ray traced lamps (r52): soft follow %s (BB_LAMP_SHADOW_FOLLOW_SOFT): under a moving "
                    "lamp the history is read where the surface was and where the lamp's motion puts it, "
                    "mixed per pixel by a follow state and by how well each fits this frame's ray (a mix "
                    "that is unsure where the two differ holds fewer frames), not by the 5x5 vote of its "
                    "workgroup; with BB_LAMP_SHADOW_FOLLOW=0 only where the surface was; 0 = the vote\n",
                    tune.follow_soft ? "yes" : "no");
    }
"""),
        (r"""// pass wants it: the ray pass's bindings, then the block answers (9) and the counters (10).
""",
         r"""// pass wants it: the ray pass's bindings, then the block answers (9) and the counters (10).
// bbport (r52_follow-soft): then the follow state (11, 12).
"""),
        (r"""                            eAccelerationStructureKHR, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer},
""",
         r"""                            eAccelerationStructureKHR, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer, eStorageImage, eStorageImage},
"""),
        (r"""    const u64 needed = (have ? 0 : 2 * 4 * pixels) + (have_history ? 0 : 2 * 8 * pixels);
""",
         r"""    // bbport (r52_follow-soft): the history's 8 bytes a pixel and the follow state's 4, twice
    const u64 needed = (have ? 0 : 2 * 4 * pixels) + (have_history ? 0 : 2 * (8 + 4) * pixels);
"""),
        (r"""        if (!history[0].image || history[0].width != width || history[0].height != height) {
            if (!EffectPass::HasRoom(instance, 2ull * 8 * width * height)) {
                data.clear();
                return;
            }
            for (int i = 0; i < 2; ++i) {
                EnsureImage(history[i], width, height, HistoryFormat, "Ray traced lamp history");
                history_laid_out[i] = false;
            }
""",
         r"""        // bbport (r52_follow-soft): the follow state is made with the history, its room counted
        // with it: without room for both, neither (and no pass).
        if (!history[0].image || history[0].width != width || history[0].height != height ||
            !follow[0].image || follow[0].width != width || follow[0].height != height) {
            if (!EffectPass::HasRoom(instance, 2ull * (8 + 4) * width * height)) {
                data.clear();
                return;
            }
            for (int i = 0; i < 2; ++i) {
                EnsureImage(history[i], width, height, HistoryFormat, "Ray traced lamp history");
                history_laid_out[i] = false;
                EnsureImage(follow[i], width, height, FollowFormat, "Ray traced lamp follow state");
                follow_laid_out[i] = false;
            }
"""),
        (r"""    std::array<bool, 2> lay_out{};
""",
         r"""    std::array<bool, 2> lay_out{};
    std::array<bool, 2> follow_lay_out{}; // bbport (r52_follow-soft)
"""),
        (r"""        lay_out = {!history_laid_out[0], !history_laid_out[1]};
        history_laid_out = {true, true};
""",
         r"""        lay_out = {!history_laid_out[0], !history_laid_out[1]};
        history_laid_out = {true, true};
        follow_lay_out = {!follow_laid_out[0], !follow_laid_out[1]};
        follow_laid_out = {true, true};
"""),
        (r"""        use_rays ? vk::Image(history[1].image) : vk::Image{}};
""",
         r"""        use_rays ? vk::Image(history[1].image) : vk::Image{}};
    // bbport (r52_follow-soft): the follow state, taken in turn with the history
    const vk::ImageView follow_prev = use_rays ? *follow[history_index ^ 1u].view : vk::ImageView{};
    const vk::ImageView follow_cur = use_rays ? *follow[history_index].view : vk::ImageView{};
    const std::array<vk::Image, 2> follow_images{
        use_rays ? vk::Image(follow[0].image) : vk::Image{},
        use_rays ? vk::Image(follow[1].image) : vk::Image{}};
"""),
        (r"""         history_images, lay_out, clear_history,
""",
         r"""         history_images, lay_out, clear_history,
         follow_prev, follow_cur, follow_images, follow_lay_out, // bbport (r52_follow-soft)
"""),
        (r"""            }
            const vk::MemoryBarrier2 to_transfer{
""",
         r"""            }
            // bbport (r52_follow-soft): the follow images on their first use, as the history's
            // (and zeroed below: nothing reads a texel the pass has not written, this keeps them
            // defined all the same)
            for (int i = 0; i < 2; ++i) {
                if (!follow_lay_out[i]) {
                    continue;
                }
                const vk::ImageMemoryBarrier2 to_general{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .oldLayout = vk::ImageLayout::eUndefined,
                    .newLayout = vk::ImageLayout::eGeneral,
                    .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                    .image = follow_images[i],
                    .subresourceRange = ColorRange,
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            const vk::MemoryBarrier2 to_transfer{
"""),
        (r"""                cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
            }
""",
         r"""                cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
            }
            for (int i = 0; i < 2; ++i) { // bbport (r52_follow-soft)
                if (follow_lay_out[i]) {
                    const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                    cmdbuf.clearColorImage(follow_images[i], vk::ImageLayout::eGeneral, zero, ColorRange);
                }
            }
"""),
        (r"""            const vk::DescriptorImageInfo cur_info{{}, history_cur, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 9> ray_writes{
""",
         r"""            const vk::DescriptorImageInfo cur_info{{}, history_cur, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo follow_prev_info{{}, follow_prev, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo follow_cur_info{{}, follow_cur, vk::ImageLayout::eGeneral};
            const std::array<vk::WriteDescriptorSet, 11> ray_writes{
"""),
        (r"""                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &cur_info}};
""",
         r"""                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &cur_info},
                // bbport (r52_follow-soft): the follow state
                vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_prev_info},
                vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &follow_cur_info}};
"""),
        (r"""                const std::array<vk::WriteDescriptorSet, 11> half_writes{
""",
         r"""                const std::array<vk::WriteDescriptorSet, 13> half_writes{
"""),
        (r"""                    vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                                           .pBufferInfo = &count_info}};
""",
         r"""                    vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageBuffer,
                                           .pBufferInfo = &count_info},
                    // bbport (r52_follow-soft): the follow state
                    vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_prev_info},
                    vk::WriteDescriptorSet{.dstBinding = 12, .descriptorCount = 1,
                                           .descriptorType = vk::DescriptorType::eStorageImage,
                                           .pImageInfo = &follow_cur_info}};
"""),
    ],
    TEST: [
        (r"""// (LampSoftnessRadius, BB_LAMP_SHADOW_SOFT winning) and a point lamp's steps (LampPassSteps).
""",
         r"""// (LampSoftnessRadius, BB_LAMP_SHADOW_SOFT winning) and a point lamp's steps (LampPassSteps).
// bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT and its bit in word 0.
"""),
        (r"""        assert(words[0] == 1u); // new weights, view 0
""",
         r"""        assert(words[0] == (1u | LampTuneFollowSoft)); // new weights, view 0, the soft follow (r52)
"""),
        (r"""        assert(other[0] == (2u | 4u << 8));
""",
         r"""        assert(other[0] == (2u | 4u << 8 | LampTuneFollowSoft));
"""),
        (r"""        assert(LampTuneWords(t, false, 0.0f)[0] == 6u << 8);
""",
         r"""        assert(LampTuneWords(t, false, 0.0f)[0] == (6u << 8 | LampTuneFollowSoft));
"""),
        (r"""    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
""",
         r"""    // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT is on unless the variable says 0 (out
    // of range is clamped, text that is not a whole number leaves the default). In the words it is
    // word 0's bit 20 and nothing else; bits 12-17 stay clear. (That the shader reads the same
    // bit is checked by rt-shadow-test --lamps: the follow images hold a state only with it.)
    {
        const LampShadowTune d = Read(std::array<Pair, 0>{});
        assert(d.follow_soft);
        const LampShadowTune off = Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "0"}}});
        assert(!off.follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "1"}}}).follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "7"}}}).follow_soft);
        assert(!Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "-2"}}}).follow_soft);
        assert(Read(std::array<Pair, 1>{{{"BB_LAMP_SHADOW_FOLLOW_SOFT", "no"}}}).follow_soft);
        // The other knobs are read as without it.
        LampShadowTune again = off;
        again.follow_soft = d.follow_soft;
        assert(LampTuneWords(again, false, 0.05f) == LampTuneWords(d, false, 0.05f));
        assert(off.follow == d.follow && off.radius_m == d.radius_m && off.view == d.view);
        const float c = std::cos(0.3f), s = std::sin(0.3f);
        const std::array<float, 12> view{c, 0.0f, -s, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, s, 0.0f, c, 3.0f};
        for (const float* v : {static_cast<const float*>(nullptr), view.data()}) {
            for (const bool inverse : {false, true}) {
                const auto on_words = LampTuneWords(d, inverse, 0.05f, v, 41u);
                const auto off_words = LampTuneWords(off, inverse, 0.05f, v, 41u);
                assert((on_words[0] ^ off_words[0]) == LampTuneFollowSoft);
                assert((on_words[0] & LampTuneFollowSoft) != 0 && (off_words[0] & LampTuneFollowSoft) == 0);
                assert((on_words[0] & (0x3Fu << 12)) == 0 && (off_words[0] & (0x3Fu << 12)) == 0);
                for (std::size_t k = 1; k < LampTuneWordCount; ++k) {
                    assert(on_words[k] == off_words[k]);
                }
            }
        }
        // Nor is it in the history block's words.
        assert(LampHistoryTail(d) == LampHistoryTail(off));
    }
    // The weight. Halfway to the radius the game's curve (1 - d/r)^2 gives a quarter, the old
"""),
    ],
    LAB: [
        # The three hand-made layouts of the lamp pass: two more storage images.
        (r"""                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                    64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP));
""",
         r"""                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 9, 10
                    64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP));
"""),
        # --pipelines builds the half-resolution lamp pipeline as well.
        (r"""    if (argc > 1 && std::strcmp(argv[1], "--pipelines") == 0) {
        std::puts("RT pipelines: built");
""",
         r"""    if (argc > 1 && std::strcmp(argv[1], "--pipelines") == 0) {
        // bbport (r52_follow-soft): the half-resolution lamp pass too, with the layout --lamps
        // gives it: the ray pass's bindings 0-8, the block answers (9), the counters (10), the
        // follow state (11, 12)
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
"""),
        (r"""                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                        64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP),
""",
         r"""                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 9, 10
                                        64, POINT_SHADOW_RAY_COMP, sizeof(POINT_SHADOW_RAY_COMP),
"""),
        (r"""                                             VK_DESCRIPTOR_TYPE_STORAGE_BUFFER},
                                            64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
""",
         r"""                                             VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                             VK_DESCRIPTOR_TYPE_STORAGE_IMAGE}, // bbport (r52_follow-soft): 11, 12
                                            64, POINT_SHADOW_RAY_HALF_COMP, sizeof(POINT_SHADOW_RAY_HALF_COMP),
"""),
        # The follow images: made beside the history, laid out, zeroed once.
        (r"""        std::array<Image, 2> history{vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT),
                                     vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT)};
""",
         r"""        std::array<Image, 2> history{vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT),
                                     vk.MakeImage(W, H, VK_FORMAT_R16G16B16A16_SFLOAT)};
        // bbport (r52_follow-soft): the follow state beside the history, taken in turn with it
        std::array<Image, 2> follow{vk.MakeImage(W, H, VK_FORMAT_R32_SFLOAT), vk.MakeImage(W, H, VK_FORMAT_R32_SFLOAT)};
"""),
        (r"""        for (auto& image : history) vk.ToGeneral(image.image);
        {
            VkClearColorValue zero{};
            const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
            vkCmdClearColorImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
        }
""",
         r"""        for (auto& image : history) vk.ToGeneral(image.image);
        for (auto& image : follow) vk.ToGeneral(image.image); // bbport (r52_follow-soft)
        {
            VkClearColorValue zero{};
            const VkImageSubresourceRange range{VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
            vkCmdClearColorImage(vk.cmd, zero_image.image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
            for (auto& image : follow) vkCmdClearColorImage(vk.cmd, image.image, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &range);
        }
"""),
        # The torch lab's writes: 13 for the half-resolution build, 11 for the full one.
        (r"""                std::array<VkWriteDescriptorSet, 11> writes{};
                for (unsigned k = 0; k < 11; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
""",
         r"""                std::array<VkWriteDescriptorSet, 13> writes{};
                for (unsigned k = 0; k < 13; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
"""),
        (r"""                writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[10].pBufferInfo = &counts;
""",
         r"""                writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER; writes[10].pBufferInfo = &counts;
                // bbport (r52_follow-soft): the follow state, taken in turn with the history:
                // bindings 11 and 12 of the half-resolution build, 9 and 10 of the full one
                VkDescriptorImageInfo follow_prev{{}, follow[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                VkDescriptorImageInfo follow_cur{{}, follow[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                writes[11].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[11].pImageInfo = &follow_prev;
                writes[12].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[12].pImageInfo = &follow_cur;
                std::array<VkWriteDescriptorSet, 11> full_writes{};
                std::copy_n(writes.begin(), 9, full_writes.begin());
                full_writes[9] = writes[11];
                full_writes[9].dstBinding = 9;
                full_writes[10] = writes[12];
                full_writes[10].dstBinding = 10;
"""),
        (r"""                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 11, writes.data());
""",
         r"""                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, half.layout, 0, 13, writes.data());
"""),
        (r"""                } else {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 9, writes.data());
""",
         r"""                } else {
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 11, full_writes.data());
"""),
        # The seam on the workgroups' grid, per mode of the carried torch's walk and run.
        (r"""                moved_held = Vulkan::LampHistoryFrames(tune) > 0.0f ? held_view(now, tune) : std::vector<float>{};
                return picture;
            };
""",
         r"""                moved_held = Vulkan::LampHistoryFrames(tune) > 0.0f ? held_view(now, tune) : std::vector<float>{};
                return picture;
            };
            // bbport (r52_follow-soft): the squares of a carried torch's shadows lay on the
            // workgroups' grid: 8 px, 16 px in the half-resolution build's first pass. Seam: the
            // mean step between neighbouring pixels across those lines (between column x - 1 and
            // x, or row y - 1 and y, where x or y is a multiple of `step`) minus the mean step
            // off every 8 px line (so the 16 px seam is not measured against the 8 px lines of
            // the half-resolution build's second pass), over the picture (all) and over the
            // steps that touch the reference's penumbra (0.05 to 0.95). About 0 where nothing
            // lines up with the grid. Printed only: no bound is checked.
            struct Seam { double all = 0, penumbra = 0; };
            const auto seam = [&](const std::vector<float>& picture, const std::vector<float>& reference, unsigned step) {
                std::array<double, 4> sum{}; // across the lines, elsewhere; the same in the penumbra
                std::array<std::size_t, 4> count{};
                const auto soft_ref = [&](std::size_t k) { return reference[k] > 0.05f && reference[k] < 0.95f; };
                const auto add = [&](std::size_t i, std::size_t j, bool across) {
                    const double d = std::abs(double(picture[i]) - double(picture[j]));
                    const std::size_t at = across ? 0 : 1;
                    sum[at] += d;
                    ++count[at];
                    if (soft_ref(i) || soft_ref(j)) {
                        sum[at + 2] += d;
                        ++count[at + 2];
                    }
                };
                for (unsigned y = 0; y < H; ++y) {
                    for (unsigned x = 0; x < W; ++x) {
                        const std::size_t i = std::size_t(y) * W + x;
                        if (x > 0 && (x % step == 0 || x % 8 != 0)) add(i, i - 1, x % step == 0);
                        if (y > 0 && (y % step == 0 || y % 8 != 0)) add(i, i - W, y % step == 0);
                    }
                }
                const auto mean = [&](std::size_t k) { return sum[k] / double(std::max<std::size_t>(count[k], 1)); };
                return Seam{mean(0) - mean(1), mean(2) - mean(3)};
            };
"""),
        # The shader reads the bit the host sets: the follow images hold a state only with it.
        (r"""                const auto alone = moving(plain, walk), all = moving(soft, walk);
                const auto all_held = moved_held;
""",
         r"""                const auto alone = moving(plain, walk), all = moving(soft, walk);
                const auto all_held = moved_held;
                // bbport (r52_follow-soft): word 0 bit 20 (LampTuneFollowSoft) is the bit the
                // shader reads: after this walk the follow images hold a state somewhere (the
                // carried torch's blocked rays) with it, and stay as zeroed without it (the pass
                // stores nothing there).
                if (checked) {
                    bool kept_state = false;
                    for (auto& image : follow) {
                        for (const float x : lab.Read(image, VK_FORMAT_R32_SFLOAT)) kept_state = kept_state || x != 0.0f;
                    }
                    if (kept_state != soft.follow_soft) {
                        std::fprintf(stderr, "BB_LAMP_SHADOW_FOLLOW_SOFT=%d, but the follow images %s\n",
                                     soft.follow_soft ? 1 : 0, kept_state ? "hold a state" : "hold nothing");
                        return 1;
                    }
                }
"""),
        (r"""                            held_mean(halved_held, moved_true), traced_share(halved_did));
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
""",
         r"""                            held_mean(halved_held, moved_true), traced_share(halved_did));
                {
                    // bbport (r52_follow-soft): the seams of the same pictures (new line; the
                    // line above is unchanged)
                    const Seam sa = seam(alone, moved_true, 8), sd = seam(all, moved_true, 8),
                               sc = seam(guarded, moved_true, 8), se = seam(untrailed, moved_true, 8),
                               sh8 = seam(halved, moved_true, 8), sh16 = seam(halved, moved_true, 16);
                    std::printf("Torch lab, the character goes with its torch, %.1f cm a frame, r52 seams "
                                "(BB_LAMP_SHADOW_FOLLOW_SOFT=%d): the mean step across the 8 px grid lines minus "
                                "the mean step elsewhere (all / penumbra): the history without its guards "
                                "%+.5f / %+.5f; the default %+.5f / %+.5f; looked up where the ground was only "
                                "%+.5f / %+.5f; with BB_LAMP_SHADOW_TRAIL=0 %+.5f / %+.5f; the default in the "
                                "half-resolution build %+.5f / %+.5f (across its 16 px lines %+.5f / %+.5f)\n",
                                speed * 100.0f, soft.follow_soft ? 1 : 0, sa.all, sa.penumbra, sd.all, sd.penumbra,
                                sc.all, sc.penumbra, se.all, se.penumbra, sh8.all, sh8.penumbra, sh16.all,
                                sh16.penumbra);
                }
                if (checked && !(d.all < a.all && d.penumbra < c.penumbra)) {
"""),
        # The lamp lab's writes: 11.
        (r"""                    VkDescriptorImageInfo history_cur{{}, history[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkWriteDescriptorSet, 9> writes{};
                    for (unsigned k = 0; k < 9; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
""",
         r"""                    VkDescriptorImageInfo history_cur{{}, history[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                    // bbport (r52_follow-soft): the follow state, taken in turn with the history
                    VkDescriptorImageInfo follow_prev{{}, follow[cur_history ^ 1].view, VK_IMAGE_LAYOUT_GENERAL};
                    VkDescriptorImageInfo follow_cur{{}, follow[cur_history].view, VK_IMAGE_LAYOUT_GENERAL};
                    std::array<VkWriteDescriptorSet, 11> writes{};
                    for (unsigned k = 0; k < 11; ++k) writes[k] = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = k, .descriptorCount = 1};
"""),
        (r"""                    writes[8].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[8].pImageInfo = &history_cur;
                    const auto snapshot = [&](std::array<int, 4> r) {
""",
         r"""                    writes[8].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[8].pImageInfo = &history_cur;
                    writes[9].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[9].pImageInfo = &follow_prev;
                    writes[10].descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE; writes[10].pImageInfo = &follow_cur;
                    const auto snapshot = [&](std::array<int, 4> r) {
"""),
        (r"""                        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 9, writes.data());
""",
         r"""                        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, lamp.layout, 0, 11, writes.data());
"""),
        # The lamp lab's old tuning: the soft follow has nothing to change there.
        (r"""                        same.self_m = 0.0f;
""",
         r"""                        same.self_m = 0.0f;
                        // (bbport r52_follow-soft: same.follow_soft stays at its default; these runs
                        // hand no history block, and without one the bit changes nothing.)
"""),
        # The lamp lab's area lamp with the soft follow as the environment has it.
        (r"""                        Vulkan::LampShadowTune repaired, point;
                        point.radius_m = 0.0f;
""",
         r"""                        Vulkan::LampShadowTune repaired, point;
                        point.radius_m = 0.0f;
                        // bbport (r52_follow-soft): BB_LAMP_SHADOW_FOLLOW_SOFT as the environment has
                        // it (0: the passes below run as before r52)
                        repaired.follow_soft = point.follow_soft =
                            Vulkan::ReadLampShadowTune([](const char* name) -> const char* { return std::getenv(name); })
                                .follow_soft;
"""),
    ],
    DOC: [
        (r"""- **Lamp history-reuse default.** `LANTERN_RT_LAMP_REUSE` now defaults to off (`vk_point_shadow.cpp:148`).
  The switch does not change it.
""",
         r"""- **Lamp history-reuse default.** `LANTERN_RT_LAMP_REUSE` now defaults to off (`vk_point_shadow.cpp:148`).
  The switch does not change it.
- **Soft follow of the lamp history under a moving lamp (r52).** In `point_shadow_ray.comp` `main()`
  (the history blend) the history is read through `historyAt()` where the surface was and where the
  lamp's motion puts it, mixed per pixel by a follow state kept in two R32F images beside the history,
  in place of r42's yes/no vote of the 5x5 answers in the workgroup. `BB_LAMP_SHADOW_FOLLOW_SOFT`,
  read once at start (`ReadLampShadowTune`, `LampShadowTune::follow_soft`), default 1, sets tuning
  word 0 bit 20 (`LampTuneFollowSoft`); 0 brings back the vote. No experiment bit gates it, so the
  switch does not change it. The two follow images are made with the lamp history either way.
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
        print("usage: r52_follow-soft.py check|apply|revert   (the tree: R52_ROOT, else the current directory)")
        return 2
    if not os.path.isfile(ROOT + CPP):
        print("not a source tree: %s (set R52_ROOT)" % ROOT)
        return 2
    if any(v is None for pair in SUMS.values() for v in pair):
        # (Only while the script is written: the sums of the texts as they are and as patched.)
        for path in EDITS:
            raw = open(ROOT + path, "rb").read()
            out, why = transform(path, raw, True)
            print("    %s: (%r, %r)," % (path, sha(raw), sha(out) if out else why))
        print("the sums are not filled in")
        return 3
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
            print("not applied (all seven files are the originals; the patch applies cleanly)")
            return 0
        if mode == "revert":
            print("not applied: nothing to revert")
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
            print("applied (all seven files are as the patch made them)")
            return 0
        if mode == "apply":
            print("already applied")
            return 0
    else:
        for path, s in states.items():
            print("%s: %s" % (path, s))
        print("neither applied nor not applied: nothing changed")
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
        print("failed (%s); putting back what was changed" % e)
        for path in done:
            with open(ROOT + path, "wb") as f:
                f.write(texts[path])
        for path in out:
            if os.path.exists(ROOT + path + TMP):
                os.remove(ROOT + path + TMP)
        return 1
    print("applied" if mode == "apply" else "reverted")
    return 0


sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
