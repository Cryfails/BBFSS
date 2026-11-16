# r61_lamp-window-cost: BB_LAMP_SHADOW_WINDOW=2 (r60's centred window) made cheaper. 0 and 1 stay
# as they are, byte for byte (their two shader builds compile to the same SPIR-V as the tree's, and
# the pass records the same commands for them). The default stays 1 (LampWindowDefault). No fault
# of the apart path is fixed: the diagnosis is unconfirmed (see APART), and the lab gets a control run
# that tells a fault of 2 from lab noise. r65 is recommended with r61 (see vk_point_shadow.cpp below:
# without it the half-resolution resolve build is compiled at the first half-resolution pass).
# check|apply|revert.
#
# On top of <tree> as it is on 2026-11-15 (r53, r54, r57 and r60 applied). The tree: the one
# the environment variable R61_ROOT names, else the current directory. Every edit is an exact text
# found exactly once where it is applied, in order; revert applies them backwards, new for old, and
# gives the files back byte for byte. Line ends are kept (all six files are CRLF). Nothing is
# changed in place: every new text is written beside its target and moved over it, and a failure
# puts back what was already moved. The files as they were are in r61_orig beside this script, the
# patched ones (LF) in r61_work. r65 (vk_point_shadow.cpp, .h, the doc) and r62 (CMakeLists.txt)
# may be applied before or after this one: no hunk here touches a line of theirs (checked: r61 and
# r65 applied and reverted in both orders on a copy of the tree's files, and r62's CMake edits).
#
# WHY. r60's value 2 cost +0.08 to +0.13 ms in the lab and +0.16 to +0.20 ms in the game over 1
# (rough, while walking), above the bar of about +0.10 ms. The cost is not the 25-tap statistic
# (1 runs the same loop) but what comes with the second dispatch: the resolve repeats the tile list,
# reads the light targets, depth and every answer texel again (the tile's 144 and its own once more)
# for every workgroup that has a lamp tile, also where nothing is shadowed, and it runs in the trace's
# build, with its ray code and, probably, its register count.
#
# WHAT (each change is under #ifdef CENTRED or new C++; savings are estimates, not measured).
# "Exact in logic" below: the shader's logic gives every stored value as r60's did. In bits it is not
# proven: the centred build's SPIR-V changes too (85972 to 89716 bytes), and a driver may round a
# changed build differently (fused multiply-adds). The proof is GPU test step 2: the r60 lines of 2
# equal to this morning's up to the lab's repeat noise.
#  point_shadow_ray.comp, the resolve (MODE_RESOLVE):
#   1. No tile list. Each invocation loads its own pixel's texel of lamp_answers (r60 loaded it later,
#      and once more into the tile) and the workgroup goes on only where its trace answered a pixel
#      (group_count as a flag). Exact in logic: a workgroup without a tile has no answer (its trace stored
#      "none"), and in one with tiles and no answer r60's resolve wrote nothing (its pixels are not
#      live; no lamp light is left in them, the trace moved it; the -1 block answers of the half
#      build's first pass are what its trace stored). It now returns before the tuning words, the
#      light targets, depth and the tile. Saves the list (4 words a tile per invocation) everywhere
#      and all the rest in covered workgroups without a shadowed pixel: about 0.01 to 0.04 ms, by how
#      many there are (a guess: 30 to 60 % of covered workgroups).
#   2. The tile's ring only: invocation lid writes the texel it holds into cell lid + 2 (the place
#      lo + apart * lid is its own pixel, under the same test) and the workgroup loads the 80 ring
#      cells (one or two loads an invocation, not two or three of 144). Exact in logic: every cell gets the same
#      bits, decoded the same way. The ring is loaded right after the pixel's flag, before its own
#      light and depth loads, so all are in flight together (r60 loaded the tile after them; nothing
#      in between writes the answers or reads the tile). About 0.003 to 0.01 ms.
#   3. MODE_APART: the lamp light (snap0, snap1) is read only for answered pixels. Exact in logic: every other
#      pixel of a resolve that gets that far has none left (its trace moved it and zeroed snap0/1, or,
#      for the first pass's pixels in the second pass, the first pass did), so r60 read zeros there and
#      d0, d1, s0, s1 stayed 0. 8 bytes a pixel fewer in covered workgroups; about 0.002 ms.
#   4. No barrier after the group_trace flag in the resolve (it never reads group_trace before the tile's
#      barrier; HalfCount's slot is taken after it; `resolve` is the same for the whole workgroup), no
#      disc sample point (no ray), and no -1 block answer stored again by the half build's first resolve
#      (its trace stored that -1). Exact in logic. About 0.001 to 0.005 ms.
#   5. New builds (gpu/CMakeLists.txt): point_shadow_ray_resolve_comp (CENTRED=1 RESOLVE=1) and
#      point_shadow_ray_half_resolve_comp (HALF=1 CENTRED=1 RESOLVE=1): the centred build with every
#      dispatch a resolve (main takes MODE_RESOLVE as set and MODE_TRACE as clear; `resolve` is a
#      constant once a non-centred workgroup has returned), so no ray code is reachable (the SPIR-V
#      still holds 4 OpRayQuery ops; the saving needs the driver to drop that dead code) and the
#      driver may give it fewer registers and more workgroups at once. Same bindings and push
#      constants as the centred builds. NOT PROVEN BIT-EXACT: it is the same text and the same logic,
#      but a different build may round a few floating-point operations differently (whether the
#      driver fuses a multiply and an add), about 1 ulp of a 32-bit float per such operation. Where
#      that reaches what is stored it is usually at most one storage step (4.9e-4 in the 16-bit
#      history at 0.5 to 1, 1/128 in the 11-bit light at 0.5 to 1); rarely, a 1-ulp difference flips
#      a threshold of the resolve (`got > 0.01`, which decides `held`; `!(fa > 0.01) && lam_kept <=
#      0.0`, which clears w_f; `frames > 1.5`), which gives one pixel a larger difference for one
#      frame, up to the whole history weight, that then decays with the history over up to word 30's
#      frames. So there is no bound in values; the pass/fail test is the lab line "r61 resolve
#      build": the centred build's count at most the repeat's (with the control 0). Saving: 0 to
#      0.04 ms (a guess until the lab's r61 timing line, and only if the driver drops the dead code).
#  vk_point_shadow.cpp / .h: Ready makes point_shadow_ray_resolve_comp beside the centred build, and
#   HalfReady point_shadow_ray_half_resolve_comp beside the half centred build (where r60 makes its
#   own: at start with r65; without r65 at the first half-resolution pass, beside r60's own centred
#   build, so that stall gets a second pipeline compile: hence r65 is recommended with r61), unless
#   BB_LAMP_SHADOW_RESOLVE_BUILD=0 (read once by Ready; then, or if one cannot be made, the resolves run
#   the centred build, which r60 ran them in, said in the log; the centred build is exact in logic
#   against r60, not proven in bits). Flush's recorded pass: the resolve dispatches bind
#   the resolve build (and push the same descriptors and constants with its layout); the half pass's
#   second trace binds the centred build again. With BB_GPU_PROFILE=1 a split pass is recorded in parts
#   (2 at full resolution, 4 at half) with a profiler mark between them, so the resolves have a row of
#   their own, "Lighting: point shadows: resolve" (key 61); the traces, the setup and the barriers after
#   each trace stay in "Lighting: point shadows". Without the profiler, or without a split (0 and 1
#   always), the pass is one part and records what it recorded before (for a split pass one redundant
#   push of constants before the trace is gone). A log line "Ray traced lamps (r61): ..." when 2 is on.
#  docs/renderer-performance-0.9.43.md: a bullet "Cheaper centred lamp window (r61)" after r60's.
#  tests/test_rt_shadows.cpp (rt-shadow-test): --pipelines makes the two new builds; --lamps makes
#   them and runs a split pass's resolves with them, as the engine does (resolve_build), and:
#   - "Torch lab, r61 resolve build, ...": once (the first lattice case, 6.7 cm a frame, both builds),
#     in this order: the control, 1 with MODE_APART run again against r60's apart_1 run (after a run of
#     2, as apart_1 was); then 2 with MODE_APART run again against the r60 lattice run of 2: with the
#     resolve build again (the lab's repeat noise for 2), and with the centred build as r60 ran it (the
#     two builds' difference plus that noise); and a verdict: "the control does not repeat ...", "2
#     does not repeat where 1 does: a fault of 2's own ..." or "2 repeats as 1 does";
#   - "Torch lab, r61: ...": the pass's time with 2 in each build, full and half resolution, and the
#     resolves' part from timestamps around them (Vk::Span; the query pool has 5 queries now, the
#     other sections still use 0 and 1).
#   Every r60 line stays as it was (text and place); what it prints for 2 now comes from r61's pass.
#
# APART (the diagnosis of "MODE_APART changes the picture: would fail", 663 pixels, at most 0.0156):
#  UNCONFIRMED. The guess was run-to-run noise of the window-2 runs, not the apart path: the same check
#  gave 0 in the default lab; 7 of the 12 "2 against 1" lines differ by 2 to 5 pixels between the two
#  labs; apart and not apart are the same computation (cur0 0 + snap0 1 against cur0 1 + snap0 0). But
#  every line of 1 and 0 repeats exactly between the two labs while lines of 2 do not (line 19 of
#  r60_lamps_default.txt against r60_lamps_w2.txt: x8 1.023 against 1.022), and the lab is meant to be
#  deterministic: that points to a race in 2's path or to state carried over between lab runs, not to
#  noise. The exact operation is not found and nothing is changed for it here. The new "r61 resolve
#  build" line decides it: if its control (1 again) is 0 and its repeat of 2 is not, there is a real
#  fault left in value 2, to be found before the flip. Not done either: a fixed order of the tile list
#  (a guess at a source; the torch lab has one tile, so it cannot be it there, and it is the trace's
#  code, which 1 shares).
#
# THE FLIP (2 as the default, a later step after the game tests; not done here). Lines to change:
#  - engine/gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h:27
#      "inline constexpr std::uint32_t LampWindowDefault = 1;" -> 2 (the one line that flips it).
#  (line numbers: the tree before r61 / after r61)
#  - point_shadow_ray.comp line 1108 / 1217: "BB_LAMP_SHADOW_WINDOW=0 (word 0 bit 21 clear; the default
#      is 1, the window)" -> "the default is 2, the centred window".
#  - vk_point_shadow.cpp Ready, line 295 / 317: the r57 log text "; 1 (the default) = the 5x5 answers
#      of the workgroup bound the history ..." -> "1 = ..." (the r60 line prints LampWindowDefault itself).
#  - docs/renderer-performance-0.9.43.md (the same lines before and after): r57 bullet line 50 "default
#      1" and line 64 "which is why 1 stays the default"; r60 bullet lines 69-70 "the default is
#      `LampWindowDefault` in `lamp_shadow_tune.h`, 1"; r61 bullet lines 127-128 "The default stays
#      `LampWindowDefault` = 1.".
#  - tests/test_rt_shadows.cpp: line 2094 / 2173 "BB_LAMP_SHADOW_WINDOW=1 (the default) and =0 (to
#      try)"; lines 2396-2400 / 2522-2526 "(which: 0 the default ... 2 the default in the
#      half-resolution build ... 3 the default with BB_LAMP_SHADOW_WINDOW=0 ... printed beside the
#      default's bounds)"; lines 2460 and 2466 / 2586 and 2592 "the default's bounds" (the torch lab's
#      `soft` comes from ReadLampShadowTune, so after the flip its default runs are 2: those bounds are
#      then 2's own, and line 1710 / 1789's `checked` should be read again). test_lamp_shadow_tune.cpp
#      needs no edit (written against LampWindowDefault).
#
# HOW TO TEST (GPU; nothing of this was run here):
#  1. rt-shadow-test --pipelines: "RT pipelines: built" (the two new builds too).
#  2. rt-shadow-test --lamps with nothing set, then with BB_LAMP_SHADOW_WINDOW=2: every old check as
#     before. Must stay identical to this morning's r60_lamps_default.txt / r60_lamps_w2.txt: every r57
#     line, the r60 lines of 1 and 0, and, up to the repeat noise (a few pixels), the r60 lines of 2
#     ("2 against 1" means and counts, the r60 linger numbers 0.013 ... / 0.141 ...). The new lines:
#     "r61 resolve build": the control (first count) 0; the third count at most the second (0, 0 and 0
#     if the runs repeat; this is the pass/fail test of the resolve build, whose difference has no
#     bound in values); its verdict "2 repeats as 1 does" (else, with the control 0, a fault of 2's
#     own is left, see APART). Register counts per build (VK_KHR_pipeline_executable_properties)
#     would show the resolve build's benefit without timing noise; not added here. "r61:" the
#     time of 2 with its own resolve build against the centred build, and the resolves' part; the r60
#     timing line's =2 against this morning's 0.243-0.247 / 0.316-0.317 ms (target: within about
#     0.10 ms of =1).
#  3. Game (HQ GTAO, torch, DLSS Performance 4K, the r52 spot), BB_LAMP_SHADOW_WINDOW=2 with
#     BB_GPU_PROFILE=1: "Lighting: point shadows" + "Lighting: point shadows: resolve" against 1's
#     "Lighting: point shadows", at graphics_lamp_shadow_half 0 and 1; BB_LAMP_SHADOW_RESOLVE_BUILD=0 for
#     the build's share. The log's "Ray traced lamps (r61)" line says which build ran.
#
# CHECKED HERE (no GPU): glslangValidator --target-env vulkan1.3 of all six builds (plain, half,
# centred, half centred, resolve, half resolve) and spirv-val; the plain and half builds byte for byte
# the SPIR-V of r61_orig, which is byte for byte the tree's built headers; RESOLVE without CENTRED
# stops with its #error; clang++ -fsyntax-only of vk_point_shadow.cpp (the build's flags from
# engine/out/gpu/build.ninja; -Wall -Wextra -Wshadow: no new warning) and of test_rt_shadows.cpp
# (its -Wall -Werror); check/apply/revert on a copy, byte for byte, alone and with r65 and r62's CMake
# edits in both orders.

import os
import sys

ROOT = os.environ.get("R61_ROOT") or os.getcwd()
ROOT = ROOT.replace("\\", "/")
if not ROOT.endswith("/"):
    ROOT += "/"

COMP = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
CPP = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
HDR = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.h"
CMAKE = "engine/gpu/CMakeLists.txt"
DOC = "engine/docs/renderer-performance-0.9.43.md"
LAB = "engine/tests/test_rt_shadows.cpp"
TMP = ".r61tmp"  # a new text waits under this name beside its target (main)

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. Written with LF; the file's CRLF is put in.
EDITS = {
    COMP: [
        (r"""layout(set = 0, binding = 11, rg32ui) uniform uimage2D lamp_answers;
#endif
""",
         r"""layout(set = 0, binding = 11, rg32ui) uniform uimage2D lamp_answers;
#endif
#endif
#ifdef RESOLVE
// bbport (r61_lamp-window-cost): the resolve's own builds (point_shadow_ray_resolve_comp and
// point_shadow_ray_half_resolve_comp): the centred build in which every dispatch is a resolve
// (main takes MODE_RESOLVE as set and MODE_TRACE as clear), so the rays, the tile list and the
// trace's stores cannot be reached. The SPIR-V still holds them; the saving needs the driver to drop
// that dead code and give the build the registers of a pass that only loads and blends. Same bindings
// and push constants as the centred build; the host runs it for the resolves only
// (vk_point_shadow.cpp, BB_LAMP_SHADOW_RESOLVE_BUILD).
#ifndef CENTRED
#error "RESOLVE is a form of the CENTRED build"
#endif
"""),
        (r"""// outside the pass's rect or the screen has no answer: nothing traced it this frame.
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
""",
         r"""// outside the pass's rect or the screen has no answer: nothing traced it this frame.
// bbport (r61_lamp-window-cost): cell i of the tile, as r60 loaded every cell.
void loadCell(uint i, ivec2 lo, int apart) {
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

// bbport (r61_lamp-window-cost): the centre cell of invocation lid, (lid + 2), is the place
// lo + apart * lid, which is the invocation's own pixel; main has loaded that texel already (own,
// under the same test: own_in), so the invocation writes it there, and only the 80 cells of the
// ring around the workgroup are loaded (one or two loads an invocation, in place of r60's two or
// three of all 144 cells, 64 of which every invocation had loaded once more for itself). Every cell
// holds the same bits as r60's: the same texel, decoded the same way, or the same "no answer".
void loadTile(ivec2 lo, int apart, bool own_in, uvec2 own) {
    const uint centre = (gl_LocalInvocationID.y + 2u) * 12u + gl_LocalInvocationID.x + 2u;
    tile_answer[centre] = own_in ? uintBitsToFloat(own.x) : -1.0;
    tile_cast[centre] = own_in ? unpackHalf2x16(own.y).y : CAST_FREE;
    for (uint j = gl_LocalInvocationIndex; j < 80u; j += 64u) {
        // rows 0 and 1 (cells 0 to 23), rows 10 and 11 (120 to 143), then columns 0, 1, 10 and 11
        // of rows 2 to 9
        uint i = j < 24u ? j : j + 96u;
        if (j >= 48u) {
            const uint k = j - 48u;
            i = (2u + k / 4u) * 12u + ((k & 3u) < 2u ? (k & 3u) : (k & 3u) + 8u);
        }
        loadCell(i, lo, apart);
    }
"""),
        (r"""    // image), but casts no ray (tile_count below)
    const bool resolve_mode = (mode & MODE_RESOLVE) != 0u;
#endif
""",
         r"""    // image), but casts no ray (tile_count below)
#ifdef RESOLVE
    const bool resolve_mode = true; // bbport (r61_lamp-window-cost): every dispatch of this build
    const bool trace_mode = false;
#else
    const bool resolve_mode = (mode & MODE_RESOLVE) != 0u;
    const bool trace_mode = (mode & MODE_TRACE) != 0u;
#endif
    // bbport (r61_lamp-window-cost): the resolve lists no tile. Each invocation loads its own
    // pixel's texel of the answers (r60 loaded it below, and once more into the tile), and the
    // workgroup goes on only if its trace answered one of its pixels (group_count then 1, else 0).
    // In logic the same result as r60's list (in bits not proven: this build's SPIR-V is new): a
    // workgroup without a tile has no answer (its trace stored none),
    // and in one with tiles but no answer r60's resolve wrote nothing (its pixels are not live, no
    // lamp light is left in them, and the -1 block answers of the half-resolution build's first pass
    // are what its trace stored): it now returns here, before loading the tune, the light, depth and
    // the tile.
    uvec2 own = uvec2(0u);   // the texel (loaded where the pixel lies in the pass's rect)
    bool own_in = false;     // the pixel lies in the rect and on the screen (loadCell's test)
    bool own_answer = false; // r60's `live` after its load: in the rect, not the first pass's
                             // pixel (second pass), and the trace answered it
    if (resolve_mode) {
#ifdef HALF
        const ivec2 p = ivec2(gl_GlobalInvocationID.xy) * (first ? 2 : 1);
        const bool mine = !fill || ((p.x | p.y) & 1) != 0;
#else
        const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
        const bool mine = true;
#endif
        if (p.x >= rect.x && p.y >= rect.y && p.x < rect.z && p.y < rect.w) {
            own = imageLoad(lamp_answers, p).xy;
            own_in = all(lessThan(p, ivec2(size)));
            own_answer = mine && uintBitsToFloat(own.x) >= 0.0;
        }
        if (own_answer) {
            atomicOr(group_count, 1u);
        }
    } else
#endif
"""),
        (r"""#ifdef CENTRED
        if ((mode & MODE_TRACE) != 0u) { // bbport (r60_lamp-centred-window): no answer here
#ifdef HALF
""",
         r"""#ifdef CENTRED
        if (trace_mode) { // bbport (r60_lamp-centred-window): no answer here
#ifdef HALF
"""),
        (r"""    const bool centred = t_centred && (history_flags & HISTORY_BLEND) != 0u && t_view != 2u && t_view != 3u;
    const bool trace_only = (mode & MODE_TRACE) != 0u && centred;
    const bool resolve = resolve_mode && centred;
""",
         r"""    const bool centred = t_centred && (history_flags & HISTORY_BLEND) != 0u && t_view != 2u && t_view != 3u;
#ifdef RESOLVE
    // bbport (r61_lamp-window-cost): as below with resolve_mode set; past the return, centred
    if (!centred) {
        return;
    }
    const bool trace_only = false;
    const bool resolve = true;
#else
    const bool trace_only = trace_mode && centred;
    const bool resolve = resolve_mode && centred;
"""),
        (r"""        return;
    }
#ifdef HALF
""",
         r"""        return;
    }
#endif
#ifdef HALF
"""),
        (r"""    // tests below then hold for them again: where it answered, the trace changed none of their inputs.
    uvec2 stored = uvec2(0u);
    if (resolve && live) {
        stored = imageLoad(lamp_answers, px).xy;
        live = uintBitsToFloat(stored.x) >= 0.0;
    }
""",
         r"""    // tests below then hold for them again: where it answered, the trace changed none of their inputs.
    // bbport (r61_lamp-window-cost): the texel is the one loaded above (`stored` is read only for a
    // pixel that stays live), and the tile's ring is loaded here, before the pixel's own loads below,
    // so that they are in flight together (r60 loaded the whole tile after them; nothing between
    // writes the answers or reads the tile).
    const uvec2 stored = own;
    if (resolve) {
        live = live && own_answer;
        loadTile(group_lo, resolve_apart, own_in, own);
    }
"""),
        (r"""    if (apart) {
        if (px.x < int(size.x) && px.y < int(size.y)) {
            d0 = imageLoad(snap0, px).rgb;
""",
         r"""    if (apart) {
#ifdef CENTRED
        // bbport (r61_lamp-window-cost): the resolve reads the lamp light only of a pixel its trace
        // answered. No other pixel of a resolve that got this far has any left: its trace ran past
        // the tile list and moved it into the light targets, zeroing snap0 and snap1 (below: lit,
        // not live), or (the first pass's pixels, in the second pass) the first pass did. So r60's
        // loads gave lit false there, and d0, d1, s0 and s1 stay 0 as they gave.
        if ((!resolve || live) && px.x < int(size.x) && px.y < int(size.y)) {
#else
        if (px.x < int(size.x) && px.y < int(size.y)) {
#endif
            d0 = imageLoad(snap0, px).rgb;
"""),
        (r"""        origin = P + n * reach;
        if (soft) {
            xi = samplePoint(px, t_frame);
""",
         r"""        origin = P + n * reach;
#ifdef CENTRED
        if (soft && !resolve) // bbport (r61_lamp-window-cost): the resolve casts no ray
#else
        if (soft)
#endif
        {
            xi = samplePoint(px, t_frame);
"""),
        (r"""    }
    barrier();
#ifdef HALF
    if (!live) {
        if (first) {
            imageStore(half_answers, px >> 1, vec4(-1.0)); // no answer
""",
         r"""    }
#ifdef CENTRED
    // bbport (r61_lamp-window-cost): the resolve does not wait here: it never reads group_trace
    // before the barrier at its tile (its own branch below comes before the one that does, and
    // HalfCount's slot is taken after that barrier). `resolve` is the same for the whole workgroup.
    if (!resolve) {
        barrier();
    }
#else
    barrier();
#endif
#ifdef HALF
    if (!live) {
#ifdef CENTRED
        if (first && !resolve) { // bbport (r61_lamp-window-cost): the trace stored this -1 already
#else
        if (first) {
#endif
            imageStore(half_answers, px >> 1, vec4(-1.0)); // no answer
"""),
        (r"""        }
        if (resolve) {
            // bbport (r60_lamp-centred-window): the 5x5 answers around every pixel of the workgroup
            loadTile(group_lo, resolve_apart);
        } else {
            group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
""",
         r"""        }
        // bbport (r60_lamp-centred-window): the resolve's 5x5 answers around every pixel of the
        // workgroup are in its tile (bbport r61_lamp-window-cost: loaded above, with its own loads)
        if (!resolve) {
            group_answer[gl_LocalInvocationIndex] = live ? answer : -1.0;
"""),
    ],
    CPP: [
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
// bbport (r61_lamp-window-cost): the resolves' own builds of BB_LAMP_SHADOW_WINDOW=2
#include "video_core/host_shaders/point_shadow_ray_half_resolve_comp.h"
#include "video_core/host_shaders/point_shadow_ray_resolve_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_gpu_profiler.h" // bbport (r61_lamp-window-cost)
#include "video_core/renderer_vulkan/vk_instance.h"
"""),
        (r"""    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
""",
         r"""    }
    // bbport (r61_lamp-window-cost): with the centred build, the resolves' own build (the centred
    // build in which every dispatch is a resolve: its ray code cannot be reached, so the driver may
    // drop it and give the build fewer registers), unless BB_LAMP_SHADOW_RESOLVE_BUILD=0. Same
    // bindings and push constants as the centred build. Not made: the resolves run the centred build,
    // which r60 ran them in, said in the log.
    if (centred && ray_pipeline) {
        const char* const resolve_env = std::getenv("BB_LAMP_SHADOW_RESOLVE_BUILD");
        resolve_wanted = !resolve_env || resolve_env[0] != '0';
        if (resolve_wanted &&
            !EffectPass::Create(instance, resolve_set_layout, resolve_layout, resolve_pipeline,
                                {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                                 eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                                 eStorageImage, eStorageImage, eStorageImage, eStorageImage},
                                sizeof(Push), POINT_SHADOW_RAY_RESOLVE_COMP, "Ray traced lamps (resolve)", true)) {
            std::printf("Ray traced lamps (r61): the resolves' own build could not be made: they run the "
                        "centred build\n");
        }
    }
    if (ray_pipeline) { // bbport (r41_lamp-shadows, r42_lamp-soft)
"""),
        (r"""                    centred ? "yes" : "no", unsigned(LampWindowDefault));
    }
""",
         r"""                    centred ? "yes" : "no", unsigned(LampWindowDefault));
        // bbport (r61_lamp-window-cost): what the value 2 does to save time, when it is on
        if (centred) {
            std::printf("Ray traced lamps (r61): the centred window's resolve stops at once in a workgroup "
                        "its trace answered no pixel of, loads only the ring of its tile and no lamp light "
                        "it does not use (the same as r60 in logic, not yet proven in bits); its build: %s "
                        "(BB_LAMP_SHADOW_RESOLVE_BUILD; 0 = the centred build, which r60 ran them in)\n",
                        resolve_pipeline ? "its own" : resolve_wanted ? "the centred one (its own could not be made)"
                                                                      : "the centred one");
        }
    }
"""),
        (r"""                    "full-resolution pass keeps 2\n");
    }
""",
         r"""                    "full-resolution pass keeps 2\n");
    }
    // bbport (r61_lamp-window-cost): and the resolves' own build of it, as Ready makes the full one
    if (half_centred && resolve_wanted &&
        !EffectPass::Create(instance, half_resolve_set_layout, half_resolve_layout, half_resolve_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage, eStorageImage,
                             eStorageImage, eStorageImage, eAccelerationStructureKHR, eStorageImage,
                             eStorageImage, eStorageImage, eStorageBuffer, eStorageImage, eStorageImage,
                             eStorageImage},
                            sizeof(Push), POINT_SHADOW_RAY_HALF_RESOLVE_COMP,
                            "Ray traced lamps (half resolution, resolve)", true)) {
        std::printf("Ray traced lamps (r61): the half-resolution resolves' own build could not be made: "
                    "they run the centred build\n");
    }
"""),
        (r"""    }
    scheduler.RecordCrumb(
        {.name = "Point shadows"},
        [push, target_views, depth_view, sampler = *sampler, snap0 = *before[0].view,
         snap1 = *before[1].view, batch = std::move(batch), words = std::move(data),
""",
         r"""    }
    // bbport (r61_lamp-window-cost): the resolves of a split pass run their own build (made beside
    // the centred builds by Ready and HalfReady; null: the centred build, which r60 ran them in). With
    // BB_GPU_PROFILE=1 a split pass is recorded in parts with a mark between them, so that the
    // resolves have a row of their own ("Lighting: point shadows: resolve"): the trace and the
    // resolve at full resolution; the first half's trace, its resolve, the second half's trace and
    // its resolve at half resolution. Without the profiler, or a split, it is one part, as before.
    const bool own_resolve = split && (use_half ? bool(half_resolve_pipeline) : bool(resolve_pipeline));
    const int parts = split && GpuProfiler::Get() ? (use_half ? 4 : 2) : 0;
    auto record =
        [push, base_word = std::bit_cast<u32>(push.thickness_m), last_part = parts - 1, // bbport (r61)
         resolve_pipe = own_resolve ? (use_half ? *half_resolve_pipeline : *resolve_pipeline) : vk::Pipeline{},
         resolve_pipe_layout = own_resolve ? (use_half ? *half_resolve_layout : *resolve_layout)
                                           : vk::PipelineLayout{},
         target_views, depth_view, sampler = *sampler, snap0 = *before[0].view,
         snap1 = *before[1].view, batch = std::move(batch), words = std::move(data),
"""),
        (r"""         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{}, half_lay_out,
         half_count, half_clear](vk::CommandBuffer cmdbuf) mutable {
            for (int i = 0; i < 2; ++i) {
                if (!lay_out[i]) {
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
                    .image = history_images[i],
                    .subresourceRange = ColorRange,
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
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
                };
                cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            const vk::MemoryBarrier2 to_transfer{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
            if (clear_history) {
                const vk::MemoryBarrier2 history_free{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &history_free});
                const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
            }
            for (int i = 0; i < 2; ++i) { // bbport (r52_follow-soft)
                if (follow_lay_out[i]) {
                    const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                    cmdbuf.clearColorImage(follow_images[i], vk::ImageLayout::eGeneral, zero, ColorRange);
                }
            }
            for (u32 at = 0; at < words.size(); at += UpdateWords) {
                const u32 count = std::min<u32>(UpdateWords, u32(words.size()) - at);
                cmdbuf.updateBuffer(buffer, at * sizeof(u32), count * sizeof(u32), words.data() + at);
            }
            const vk::MemoryBarrier2 before{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                 vk::AccessFlagBits2::eShaderWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            const vk::DescriptorBufferInfo lights{buffer, 0, words.size() * sizeof(u32)};
""",
         r"""         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{}, half_lay_out,
         half_count, half_clear](vk::CommandBuffer cmdbuf, int part) mutable {
            // bbport (r61_lamp-window-cost): part: -1 the whole pass; else one part of the split pass
            // (above). The first part lays out, clears and fills what the pass uses, as the whole pass
            // does; every part binds its own pipeline, descriptors and constants.
            if (part <= 0) {
                for (int i = 0; i < 2; ++i) {
                    if (!lay_out[i]) {
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
                        .image = history_images[i],
                        .subresourceRange = ColorRange,
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
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
                    };
                    cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
                }
                const vk::MemoryBarrier2 to_transfer{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_transfer});
                if (clear_history) {
                    const vk::MemoryBarrier2 history_free{
                        .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                        .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                        .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                        .dstAccessMask = vk::AccessFlagBits2::eTransferWrite};
                    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &history_free});
                    const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                    cmdbuf.clearColorImage(history_cur_image, vk::ImageLayout::eGeneral, zero, ColorRange);
                }
                for (int i = 0; i < 2; ++i) { // bbport (r52_follow-soft)
                    if (follow_lay_out[i]) {
                        const vk::ClearColorValue zero{std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}};
                        cmdbuf.clearColorImage(follow_images[i], vk::ImageLayout::eGeneral, zero, ColorRange);
                    }
                }
                for (u32 at = 0; at < words.size(); at += UpdateWords) {
                    const u32 count = std::min<u32>(UpdateWords, u32(words.size()) - at);
                    cmdbuf.updateBuffer(buffer, at * sizeof(u32), count * sizeof(u32), words.data() + at);
                }
                const vk::MemoryBarrier2 before{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = Compute,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                     vk::AccessFlagBits2::eShaderWrite};
                cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            }
            const vk::DescriptorBufferInfo lights{buffer, 0, words.size() * sizeof(u32)};
"""),
        (r"""            if (half_pipe) {
                if (half_lay_out) {
                    const vk::ImageMemoryBarrier2 to_general{
""",
         r"""            if (half_pipe) {
                if (half_lay_out && part <= 0) {
                    const vk::ImageMemoryBarrier2 to_general{
"""),
        (r"""                }
                if (half_clear) { // the counters start at zero
                    cmdbuf.fillBuffer(half_count_buffer, 0, VK_WHOLE_SIZE, 0);
""",
         r"""                }
                if (half_clear && part <= 0) { // the counters start at zero
                    cmdbuf.fillBuffer(half_count_buffer, 0, VK_WHOLE_SIZE, 0);
"""),
        (r"""                                           .pImageInfo = &answers_info}};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipe);
                cmdbuf.pushDescriptorSetKHR(
                    vk::PipelineBindPoint::eCompute, half_pipe_layout, 0,
                    vk::ArrayProxy<const vk::WriteDescriptorSet>(half_with_answers ? 14u : 13u, half_writes.data()));
                push.first_light = table;
""",
         r"""                                           .pImageInfo = &answers_info}};
                // bbport (r61_lamp-window-cost): a build and its bindings (the resolves' own build
                // or the pass's)
                const auto bind = [&](vk::Pipeline pipe, vk::PipelineLayout pipe_layout) {
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipe);
                    cmdbuf.pushDescriptorSetKHR(
                        vk::PipelineBindPoint::eCompute, pipe_layout, 0,
                        vk::ArrayProxy<const vk::WriteDescriptorSet>(half_with_answers ? 14u : 13u, half_writes.data()));
                };
                bind(half_pipe, half_pipe_layout);
                const vk::PipelineLayout resolve_push_layout = resolve_pipe ? resolve_pipe_layout : half_pipe_layout;
                push.first_light = table;
"""),
        (r"""                push.rect = covered;
                const u32 mode = std::bit_cast<u32>(push.thickness_m) |
                                 (half_count ? ModeHalfCount : 0u);
                // bbport (r60_lamp-centred-window): split, each half as a trace and a resolve; the
""",
         r"""                push.rect = covered;
                const u32 mode = base_word | (half_count ? ModeHalfCount : 0u); // bbport (r61): as before
                // bbport (r60_lamp-centred-window): split, each half as a trace and a resolve; the
"""),
        (r"""                const u32 resolve = (mode & ~ModeHalfCount) | ModeResolve;
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst | trace);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(Push), &push);
                const u32 hx0 = u32(covered[0]) / 16, hy0 = u32(covered[1]) / 16;
                const u32 hx1 = (u32(covered[2]) + 15) / 16, hy1 = (u32(covered[3]) + 15) / 16;
                cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
                if (split) {
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFirst);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
""",
         r"""                const u32 resolve = (mode & ~ModeHalfCount) | ModeResolve;
                const u32 hx0 = u32(covered[0]) / 16, hy0 = u32(covered[1]) / 16;
                const u32 hx1 = (u32(covered[2]) + 15) / 16, hy1 = (u32(covered[3]) + 15) / 16;
                if (part <= 0) {
                    push.thickness_m = std::bit_cast<float>(mode | ModeHalfFirst | trace);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(hx0, hy0, 0, hx1 - hx0, hy1 - hy0, 1);
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                }
                if (split && (part < 0 || part == 1)) {
                    if (resolve_pipe) { // bbport (r61_lamp-window-cost)
                        bind(resolve_pipe, resolve_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFirst);
                    cmdbuf.pushConstants(resolve_push_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
"""),
        (r"""                }
                push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill | trace);
                cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(Push), &push);
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                if (split) {
                    between();
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFill);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
""",
         r"""                }
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
                const u32 gx1 = (u32(covered[2]) + 7) / 8, gy1 = (u32(covered[3]) + 7) / 8;
                if (part < 0 || part == 2) {
                    if (resolve_pipe && part < 0) { // bbport (r61_lamp-window-cost): the trace's build again
                        bind(half_pipe, half_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(mode | ModeHalfFill | trace);
                    cmdbuf.pushConstants(half_pipe_layout, vk::ShaderStageFlagBits::eCompute, 0,
"""),
        (r"""                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
""",
         r"""                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                    if (split) {
                        between();
                    }
                }
                if (split && (part < 0 || part == 3)) {
                    if (resolve_pipe) { // bbport (r61_lamp-window-cost)
                        bind(resolve_pipe, resolve_pipe_layout);
                    }
                    push.thickness_m = std::bit_cast<float>(resolve | ModeHalfFill);
                    cmdbuf.pushConstants(resolve_push_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
                if (part >= 0 && part != last_part) {
                    return; // bbport (r61_lamp-window-cost): what follows ends the last part
                }
"""),
        (r"""                push.rect = covered;
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
""",
         r"""                push.rect = covered;
                const u32 gx0 = u32(covered[0]) / 8, gy0 = u32(covered[1]) / 8;
"""),
        (r"""                if (split) { // bbport (r60_lamp-centred-window): the trace, then the resolve
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
            }
""",
         r"""                if (split) { // bbport (r60_lamp-centred-window): the trace, then the resolve
                    if (part <= 0) {
                        push.thickness_m = std::bit_cast<float>(base_word | ModeTrace);
                        cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                        cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                        between();
                    }
                    if (part < 0 || part == 1) {
                        // bbport (r61_lamp-window-cost): the resolves' own build, when there is one
                        if (resolve_pipe) {
                            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, resolve_pipe);
                            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, resolve_pipe_layout, 0,
                                                        vk::ArrayProxy<const vk::WriteDescriptorSet>(
                                                            ray_count, ray_writes.data()));
                        }
                        push.thickness_m = std::bit_cast<float>(base_word | ModeResolve);
                        cmdbuf.pushConstants(resolve_pipe ? resolve_pipe_layout : layout,
                                             vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                        cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                    }
                } else {
                    cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push), &push);
                    cmdbuf.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
                }
                batch.clear();
            }
            if (part >= 0 && part != last_part) {
                return; // bbport (r61_lamp-window-cost): what follows ends the last part
            }
"""),
        (r"""            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        });
}
""",
         r"""            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        };
    if (parts == 0) {
        scheduler.RecordCrumb({.name = "Point shadows"},
                              [record = std::move(record)](vk::CommandBuffer cmdbuf) mutable { record(cmdbuf, -1); });
        return;
    }
    // bbport (r61_lamp-window-cost): the parts in order, one closure shared by them (it holds the
    // pass's words and tiles once); the marks are written where each part starts
    const auto shared = std::make_shared<decltype(record)>(std::move(record));
    for (int part = 0; part < parts; ++part) {
        if (part > 0) {
            EffectPass::Mark(part % 2 != 0 ? 61 : 6, part % 2 != 0 ? "point shadows: resolve" : "point shadows");
        }
        scheduler.RecordCrumb({.name = "Point shadows"},
                              [shared, part](vk::CommandBuffer cmdbuf) { (*shared)(cmdbuf, part); });
    }
}
"""),
    ],
    HDR: [
        (r"""    bool answers_short = false;
    std::array<float, 12> last_view{}, pending_view{};
""",
         r"""    bool answers_short = false;
    // bbport (r61_lamp-window-cost): the resolves' own builds (point_shadow_ray_resolve_comp, made by
    // Ready, and point_shadow_ray_half_resolve_comp, made by HalfReady, beside the centred builds,
    // with the same bindings): the centred build in which every dispatch is a resolve, so its ray
    // code cannot be reached. resolve_wanted: BB_LAMP_SHADOW_RESOLVE_BUILD is not 0 (read once, by
    // Ready). A build that is null (not wanted or not made): its resolves run the centred build, which
    // r60 ran them in.
    bool resolve_wanted = false;
    vk::UniqueDescriptorSetLayout resolve_set_layout, half_resolve_set_layout;
    vk::UniquePipelineLayout resolve_layout, half_resolve_layout;
    vk::UniquePipeline resolve_pipeline, half_resolve_pipeline;
    std::array<float, 12> last_view{}, pending_view{};
"""),
    ],
    CMAKE: [
        (r"""add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_comp HALF=1 CENTRED=1)
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
""",
         r"""add_host_shader(point_shadow_ray.comp point_shadow_ray_half_centred_comp HALF=1 CENTRED=1)
# bbport (r61_lamp-window-cost): the resolves' own builds of 2 (every dispatch a resolve, no ray
# code); the first two builds above are unchanged.
add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_comp CENTRED=1 RESOLVE=1)
add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_comp HALF=1 CENTRED=1 RESOLVE=1)
add_host_shader(ssgi_gather_ray.comp ssgi_gather_ray_comp)
"""),
    ],
    DOC: [
        (r"""  bytes a pixel, 75 MB a frame at 1920x1080, about 0.05 to 0.12 ms on an RTX 4090 over the pass's 0.30 to 0.36 ms. No
  experiment bit gates it, so the switch does not change it.
""",
         r"""  bytes a pixel, 75 MB a frame at 1920x1080, about 0.05 to 0.12 ms on an RTX 4090 over the pass's 0.30 to 0.36 ms. No
  experiment bit gates it, so the switch does not change it.
- **Cheaper centred lamp window (r61).** Only `BB_LAMP_SHADOW_WINDOW=2` changes; 0 and 1 are as before
  (their two shader builds are byte for byte the same, and the pass records the same commands for them).
  In `point_shadow_ray.comp`, under `CENTRED`, the resolve (`MODE_RESOLVE`) no longer lists the lamp
  tiles: each invocation loads its own pixel's texel of the answers image, and a workgroup whose trace
  answered none of its pixels returns at once (before the tuning words, the light targets, depth and the
  tile); it loads only the 80 texels of the ring around the workgroup into its 12x12 tile, the centre
  coming from the texels it already holds; with `MODE_APART` it reads the lamp light only of answered
  pixels; it skips the barrier after the trace flag, the disc's sample point and the half-resolution
  block answers its trace had already stored as "none". In logic each of these leaves every value the
  pass writes as r60 wrote it (the reasons are in the shader's comments); in bits that is not proven,
  as the centred build's SPIR-V changes too (85972 to 89716 bytes) and a driver may round it
  differently. The proof is the torch lab's r60 lines of 2, which must stay as this morning's up to
  the lab's repeat noise. New builds `point_shadow_ray_resolve_comp`
  and `point_shadow_ray_half_resolve_comp` (`CENTRED=1 RESOLVE=1`, `gpu/CMakeLists.txt`): the centred
  build with every dispatch a resolve, so its ray code cannot be reached (the SPIR-V still holds it; the
  saving needs the driver to drop it) and the driver may give it fewer registers. `PointShadow::Ready`
  makes the full-resolution one at start; `HalfReady` makes the half-resolution one beside the half
  centred build, at start with r65, and without r65 at the first half-resolution pass, beside r60's own
  centred build, so that stall gets a second compile. The split pass runs its resolves with them;
  `BB_LAMP_SHADOW_RESOLVE_BUILD=0`, read once by `Ready`, or a build that cannot be made, runs them in
  the centred build, which r60 ran them in. Their logic is the same text, but a different build may
  round a few floating-point operations differently (the driver's choice of fused multiply-adds), so
  they are not proven to give the same bits. Where they differ it is usually at most one storage step
  of a value (the 16-bit history, the 11-bit light); rarely a 1-ulp difference flips a threshold of the
  resolve (`got > 0.01`, the `fa > 0.01` test that clears the follow weight, `frames > 1.5`), which
  gives one pixel a larger difference for one frame that then decays with the history. The pass or
  fail test is the torch lab's "r61 resolve build" line: the centred build's count at most the
  repeat's.
  With `BB_GPU_PROFILE=1` a split pass is recorded in parts with a profiler mark between them, so the
  resolves get a row of their own, "Lighting: point shadows: resolve" (the traces stay in "Lighting: point
  shadows"; without the profiler the pass is one part, as before). Expected saving (estimates, not
  measured): the early return 0.01 to 0.04 ms (how many covered workgroups have no shadowed pixel),
  the ring-only tile and the light it no longer reads about 0.005 to 0.015 ms, the resolve builds 0 to
  0.04 ms (registers; a guess until the lab's r61 timing line); in all about 0.02 to 0.08 ms of r60's
  0.08 to 0.13 ms (lab) or 0.16 to 0.20 ms (game) over 1. Memory and bindings as r60. The default stays
  `LampWindowDefault` = 1. No experiment bit gates it, so the switch does not change it.
"""),
    ],
    LAB: [
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_centred_comp.h"
// bbport (r61_lamp-window-cost): the resolves' own builds of BB_LAMP_SHADOW_WINDOW=2
#include "video_core/host_shaders/point_shadow_ray_half_resolve_comp.h"
#include "video_core/host_shaders/point_shadow_ray_resolve_comp.h"
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
"""),
        (r"""        VkQueryPoolCreateInfo query{.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 2};
        CHECK(vkCreateQueryPool(device, &query, nullptr, &stamps));
""",
         r"""        VkQueryPoolCreateInfo query{.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 5}; // bbport (r61): 2 to 4, Span
        CHECK(vkCreateQueryPool(device, &query, nullptr, &stamps));
"""),
        (r"""        CHECK(vkBeginCommandBuffer(cmd, &begin));
        vkCmdResetQueryPool(cmd, stamps, 0, 2);
    }
""",
         r"""        CHECK(vkBeginCommandBuffer(cmd, &begin));
        vkCmdResetQueryPool(cmd, stamps, 0, 5);
    }
"""),
        (r"""        return r == VK_SUCCESS ? double((t[1] - t[0]) & mask) * period / 1e6 : 0.0;
    }
""",
         r"""        return r == VK_SUCCESS ? double((t[1] - t[0]) & mask) * period / 1e6 : 0.0;
    }
    // bbport (r61_lamp-window-cost): after End, ms from timestamp a to timestamp b (both written in
    // that submission; 2 to 4 only by the torch lab's timing of the resolves)
    double Span(unsigned a, unsigned b) {
        std::array<std::uint64_t, 2> t{};
        const VkResult ra = vkGetQueryPoolResults(device, stamps, a, 1, 8, &t[0], 8, VK_QUERY_RESULT_64_BIT);
        const VkResult rb = vkGetQueryPoolResults(device, stamps, b, 1, 8, &t[1], 8, VK_QUERY_RESULT_64_BIT);
        return ra == VK_SUCCESS && rb == VK_SUCCESS ? double((t[1] - t[0]) & mask) * period / 1e6 : 0.0;
    }
"""),
        (r"""                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
""",
         r"""                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        // bbport (r61_lamp-window-cost): the resolves' own builds, with the centred builds' bindings
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_RESOLVE_COMP, sizeof(POINT_SHADOW_RAY_RESOLVE_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                         VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                        64, POINT_SHADOW_RAY_HALF_RESOLVE_COMP, sizeof(POINT_SHADOW_RAY_HALF_RESOLVE_COMP),
                        VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
        std::puts("RT pipelines: built");
"""),
        (r"""                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image lamp_answers = vk.MakeImage(W, H, VK_FORMAT_R32G32_UINT);
""",
         r"""                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            // bbport (r61_lamp-window-cost): the resolves' own builds (PointShadow::Ready and HalfReady
            // make them beside the centred ones, with the same bindings)
            Pipeline lamp_resolve = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_RESOLVE_COMP, sizeof(POINT_SHADOW_RAY_RESOLVE_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Pipeline half_resolve = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_ACCELERATION_STRUCTURE_KHR, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                                     VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE},
                                                    64, POINT_SHADOW_RAY_HALF_RESOLVE_COMP, sizeof(POINT_SHADOW_RAY_HALF_RESOLVE_COMP),
                                                    VK_PIPELINE_CREATE_DISPATCH_BASE_BIT);
            Image lamp_answers = vk.MakeImage(W, H, VK_FORMAT_R32G32_UINT);
"""),
        (r"""            bool half_count = true;
            const auto run = [&](const Views& v, const Pass& pass) {
""",
         r"""            bool half_count = true;
            // bbport (r61_lamp-window-cost): resolve_build: a split pass's resolves run their own build,
            // as the engine runs them unless BB_LAMP_SHADOW_RESOLVE_BUILD=0; false: the centred build, as
            // r60 ran them. split_stamps: a split pass also writes timestamps around its resolves, and
            // resolve_ms is then their time in the last pass (to the end of the pass for the last one).
            bool resolve_build = true;
            bool split_stamps = false;
            double resolve_ms = 0.0;
            const auto run = [&](const Views& v, const Pass& pass) {
"""),
        (r"""                    const Pipeline& p = centred ? half_centred : half; // bbport (r60)
                    vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.pipeline);
                    vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, p.layout, 0, centred ? 14 : 13, writes.data());
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
""",
         r"""                    const Pipeline& p = centred ? half_centred : half; // bbport (r60)
                    // bbport (r61_lamp-window-cost): the resolves' build (their own, or the centred one)
                    // and what is bound
                    const Pipeline& rp = split && resolve_build ? half_resolve : p;
                    const Pipeline* bound = &p;
                    const auto bind = [&](const Pipeline& q) {
                        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, q.pipeline);
                        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, q.layout, 0, centred ? 14 : 13, writes.data());
                        bound = &q;
                    };
                    bind(p);
                    const unsigned count = half_count ? 8u : 0u; // MODE_HALF_COUNT
"""),
        (r"""                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, x, y, 1);
""",
         r"""                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, bound->layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, x, y, 1);
"""),
        (r"""                    if (split) {
                        dispatch(mode | 2u | Resolve, (W + 15) / 16, (H + 15) / 16);
                        vk.Barrier();
                    }
""",
         r"""                    if (split) {
                        if (&rp != &p) bind(rp); // bbport (r61)
                        if (split_stamps) vk.Stamp(2);
                        dispatch(mode | 2u | Resolve, (W + 15) / 16, (H + 15) / 16);
                        if (split_stamps) vk.Stamp(3);
                        vk.Barrier();
                        if (&rp != &p) bind(p);
                    }
"""),
        (r"""                        vk.Barrier();
                        dispatch(mode | 4u | Resolve, (W + 7) / 8, (H + 7) / 8);
""",
         r"""                        vk.Barrier();
                        if (&rp != &p) bind(rp); // bbport (r61)
                        if (split_stamps) vk.Stamp(4);
                        dispatch(mode | 4u | Resolve, (W + 7) / 8, (H + 7) / 8);
"""),
        (r"""                        vk.Barrier();
                        word = mode | Resolve;
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, p.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
""",
         r"""                        vk.Barrier();
                        // bbport (r61_lamp-window-cost): the resolves' build (their own, or the centred one)
                        const Pipeline& rp = resolve_build ? lamp_resolve : p;
                        if (&rp != &p) {
                            vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, rp.pipeline);
                            vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, rp.layout, 0, 12, full_writes.data());
                        }
                        word = mode | Resolve;
                        std::memcpy(&push.thickness, &word, 4);
                        vkCmdPushConstants(vk.cmd, rp.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
                        if (split_stamps) vk.Stamp(2);
                        vkCmdDispatchBase(vk.cmd, 0, 0, 0, (W + 7) / 8, (H + 7) / 8, 1);
"""),
        (r"""                vk.Barrier();
                return vk.End();
            };
""",
         r"""                vk.Barrier();
                const double ms = vk.End();
                // bbport (r61_lamp-window-cost): the resolves' part of the pass
                if (split && split_stamps) resolve_ms = pass.half ? vk.Span(2, 3) + vk.Span(4, 1) : vk.Span(2, 1);
                return ms;
            };
"""),
        (r"""                                    centred_apart_fault = lc.name;
                                }
                            }
""",
         r"""                                    centred_apart_fault = lc.name;
                                }
                                // bbport (r61_lamp-window-cost): 1 once more (with MODE_APART, as apart_1 above,
                                // and after a run of 2, as apart_1 was): the control, 0 when the lab repeats bit
                                // for bit (r60's two labs printed the same lines of 1). Then 2 once more (with
                                // MODE_APART, as the run above), its resolves in their own build as above, and in
                                // the centred build as r60 ran them, each against the run above. The first of
                                // these is the lab's repeat noise for 2: where 1 repeats and 2 does not, value 2
                                // has a fault of its own (a race, or state carried over between runs), which
                                // would also explain r60's "MODE_APART changes the picture" with 2. The second is
                                // the two builds' difference and noise, and is meant to be no larger than the
                                // first.
                                at_apart = true;
                                const auto again_1 = moving(tunes[1], lc.move);
                                std::size_t differ_control = 0;
                                double most_control = 0.0;
                                for (std::size_t i = 0; i < apart_1.size(); ++i) {
                                    const double d = std::abs(double(again_1[i]) - double(apart_1[i]));
                                    differ_control += d > 0.0 ? 1 : 0;
                                    most_control = std::max(most_control, d);
                                }
                                const auto again_2 = moving(tunes[3], lc.move);
                                resolve_build = false;
                                const auto centred_build_2 = moving(tunes[3], lc.move);
                                resolve_build = true;
                                at_apart = false;
                                std::array<std::size_t, 2> differ_61{};
                                std::array<double, 2> most_61{};
                                for (std::size_t i = 0; i < last[3].size(); ++i) {
                                    const double d1 = std::abs(double(again_2[i]) - double(last[3][i]));
                                    const double d2 = std::abs(double(centred_build_2[i]) - double(last[3][i]));
                                    differ_61[0] += d1 > 0.0 ? 1 : 0;
                                    differ_61[1] += d2 > 0.0 ? 1 : 0;
                                    most_61[0] = std::max(most_61[0], d1);
                                    most_61[1] = std::max(most_61[1], d2);
                                }
                                const char* const repeat_what =
                                    differ_control != 0 ? "the control does not repeat: the lab itself is not deterministic here"
                                    : differ_61[0] != 0 ? "2 does not repeat where 1 does: a fault of 2's own (a race or carried state)"
                                                        : "2 repeats as 1 does";
                                std::printf("Torch lab, r61 resolve build, %s, %.1f cm a frame, %s: control, "
                                            "BB_LAMP_SHADOW_WINDOW=1 (MODE_APART) once more against its run above %zu pixels "
                                            "differ (most %.5f); =2 (MODE_APART) once more against the run above, its resolves "
                                            "in their own build again %zu pixels differ (most %.5f; the lab's repeat noise), in "
                                            "the centred build as r60 ran them %zu pixels differ (most %.5f) (printed only; 0, 0 "
                                            "and 0 expected, the third at most the second): %s\n",
                                            lc.name, speed * 100.0f, half_build ? "half-resolution build" : "full resolution",
                                            differ_control, most_control, differ_61[0], most_61[0], differ_61[1], most_61[1],
                                            repeat_what);
                            }
"""),
        (r"""                            window_best[0], window_best[2], window_best[1], window_best[3]);
            }
""",
         r"""                            window_best[0], window_best[2], window_best[1], window_best[3]);
                // bbport (r61_lamp-window-cost): =2 with its resolves in their own build (the engine's
                // default, as the r60 line above runs it) and in the centred build (as r60 ran them,
                // BB_LAMP_SHADOW_RESOLVE_BUILD=0), at full and at half resolution: the pass's time, settled
                // (frames 8 to 35, as above), and the resolves' part of it from timestamps around them (frames
                // 40 to 63; on frames of their own, so the pass's time above carries no extra timestamp).
                // Printed only.
                std::array<double, 4> build_best{1e9, 1e9, 1e9, 1e9}, resolve_best{1e9, 1e9, 1e9, 1e9};
                half_count = false;
                at_apart = true;
                for (int b = 0; b < 2; ++b) {
                    resolve_build = b == 0;
                    for (const bool h : {false, true}) {
                        const std::size_t at = std::size_t(b * 2 + (h ? 1 : 0));
                        restart();
                        at_half = h;
                        for (int i = 0; i < 64; ++i) {
                            split_stamps = i >= 36;
                            const double ms = frame(view, windows[1]);
                            if (i >= 8 && i < 36) build_best[at] = std::min(build_best[at], ms);
                            if (i >= 40) resolve_best[at] = std::min(resolve_best[at], resolve_ms);
                        }
                    }
                }
                split_stamps = false;
                resolve_build = true;
                at_half = false;
                at_apart = false;
                half_count = true;
                std::printf("Torch lab, r61: the area lamp with its history, BB_LAMP_SHADOW_WINDOW=2 with its resolves in "
                            "their own build %.3f ms (the resolves %.3f ms), in the centred build as r60 %.3f ms (the "
                            "resolves %.3f ms); the half-resolution build %.3f ms (the resolves %.3f ms), %.3f ms (the "
                            "resolves %.3f ms) (printed only)\n",
                            build_best[0], resolve_best[0], build_best[2], resolve_best[2], build_best[1], resolve_best[1],
                            build_best[3], resolve_best[3]);
            }
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
        COMP: ["void loadTile(ivec2 lo, int apart, bool own_in, uvec2 own) {", "#ifdef RESOLVE",
               "const bool trace_mode = (mode & MODE_TRACE) != 0u;"],
        CPP: ["POINT_SHADOW_RAY_RESOLVE_COMP,", "POINT_SHADOW_RAY_HALF_RESOLVE_COMP,",
              "BB_LAMP_SHADOW_RESOLVE_BUILD", "\"point shadows: resolve\""],
        HDR: ["vk::UniquePipeline resolve_pipeline, half_resolve_pipeline;"],
        CMAKE: ["add_host_shader(point_shadow_ray.comp point_shadow_ray_resolve_comp CENTRED=1 RESOLVE=1)",
                "add_host_shader(point_shadow_ray.comp point_shadow_ray_half_resolve_comp HALF=1 CENTRED=1 RESOLVE=1)"],
        DOC: ["**Cheaper centred lamp window (r61).**"],
        LAB: ["Pipeline lamp_resolve = vk.MakePipeline(", "Pipeline half_resolve = vk.MakePipeline(",
              "Torch lab, r61 resolve build", "Torch lab, r61: the area lamp"],
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
        print("usage: r61_lamp-window-cost.py check|apply|revert   (the tree: R61_ROOT, else the "
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
