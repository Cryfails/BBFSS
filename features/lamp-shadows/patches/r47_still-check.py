# r47_still-check: a caster of the ray tracing scene that is held for still is looked at again,
# and one found moving is refit at every draw from then on (vk_rt_shadow.cpp/.h, a new header
# rt_still_check.h with its test, a new compute shader rt_still_sig.comp, one comment in
# bbport_settings.h, the shader and one test target in gpu/CMakeLists.txt, one offline check in
# tests/test_rt_shadows.cpp, one call in vk_rasterizer.cpp where a draw whose pipeline is still
# compiling is left out). check|apply|revert (revert restores byte for byte and removes the
# three new files). On top of r1..r44 with r46_lamp-cards applied (it anchors on r46's lines; on a
# tree without r46 check says so and changes nothing). Back: r47 first, then r46. The tree: the
# one the environment variable R47_ROOT names; without it the current directory when that is the
# root of a source tree (run from there), else <tree>/. Nothing is changed in place: every
# new text is written beside its target and moved over it, and a failure puts back what was
# already moved. Source files keep their CRLF line ends. Every old text below is found exactly
# once when its turn comes, every new one exactly once on the way back.
#
# WHY. With ray traced lamp shadows on, a sharp shadow shaped like the hand torch stays on the
# ground while the character and the torch move on. A caster counts as moving only by two signs
# of its draw: a skeleton, or a small bone palette whose bytes changed (PrepareDraw). Every other
# caster is built once, in the pose of the frame it was first drawn, and never captured again
# while it is drawn: its bottom-level structure keeps that pose for good. A prop the game places
# by a one-bone palette it writes on the GPU, by its model matrix, or that was first drawn in a
# passing pose, casts from where it was built. Whether the torch is such a caster is not known
# from the code; the looks find it out and the log line names it.
#
# WHAT.
#  1. A look. The draw of a caster held for still (built, has a BLAS, not moving, not a shared
#     copy) is captured once more as a probe: its vertices go to the positions buffer as any
#     capture's do, but nothing is built or copied from them (PrepareDraw returns its capture
#     param; RecordBuilds leaves it once its bounds are measured: it is not even brought to
#     world space, nothing else reads its positions). The entry, its BLAS, its world copy and
#     the scene's records stay as they are.
#  2. The signature. A new compute pass (rt_still_sig.comp, BEFORE rt_unproject.comp in the same
#     recorded block) gathers the world bounds of the vertices the mesh's triangles use, one
#     invocation an index. Not over the vertex range, as rt_unproject.comp walks it: the capture
#     writes only the vertices a draw's triangles use (emit_spirv_special.cpp), the rest of the
#     range holds an earlier frame's data and would read as a move. Eight words a signature in a
#     device local buffer (atomicMax of ordered keys, one thread a subgroup writes), zeroed by a
#     fill before the pass, copied after it to a host readable ring of four frames. The pass has
#     its own pipeline and descriptor layout (positions read only, signatures); rt_unproject.comp
#     and its layout are untouched.
#     The bounds are NOT taken from the scene's world positions. Those are made with one 3x4
#     matrix (view to world times the projection's inverse) whose entries hold the camera's
#     place times numbers of the size depth/near: for a camera a hundred metres from the
#     world's origin and a wall tens of metres away the sum cancels thousands of metres down to
#     the wall's place and rounds it by millimetres to centimetres, differently for every pose
#     of the camera (the tests: up to 47 mm for meshes 3 to 120 m away, 3.9 mm at 60 m on the
#     GPU, against a tolerance of 4 mm).
#     Every far wall would have read as moving whenever the camera moved, and would have been
#     refit for good. So the pass reads the positions as the capture stored them (clip space)
#     and brings them to the world in two parts (StillClipToWorld, StillPoint in
#     rt_still_check.h): to their place about the capture's camera (no large numbers: the
#     result is as exact as the stored clip position), then the camera's place is added. The
#     same mesh under two poses of the camera then differs by 0.03 mm at most (the test). The
#     pass needs subgroup arithmetic in compute shaders; a device without it gets no still
#     check and a line that says so ("Ray tracing still check (r47): off - ...").
#     Two kinds of capture are never measured (neither as a look nor as a reference): a mesh of
#     more than 4194240 indices (1398080 triangles: one dispatch takes no more), and a draw
#     that starts at another first instance than the entry was made with (its vertex shader
#     stores nothing; the line counts these as "drawn from another first instance").
#  3. The reference. The capture a BLAS of a caster held for still is built from gets a signature
#     too: the bounds the looks compare with. Each pass (camera, sun shadow) has its own
#     reference, since a sun pass's vertex shader may place the mesh with a bias; a look by the
#     pass that has none is compared with the other's under a wide tolerance (0.25 m) and, within
#     it, becomes that pass's reference.
#  4. Reading. At a frame's end the signatures of the frames whose submission the GPU has passed
#     are read without a wait: on a frame that has signatures to read the driver is asked once
#     how far the GPU is (the tick the scheduler remembers is only as new as the last wait
#     anywhere). At the latest those of the ring slot the coming frame writes again are read:
#     for that one the scheduler waits on a tick submitted four frames before, where it already
#     waits for the capture params. A look is read one to two frames after it was taken.
#  5. Found moving (bounds differ by more than the tolerance): with BB_RT_STILL=on a second look
#     is asked for at once, and when that one finds the caster moved as well the entry counts
#     as moving from then on (Entry::dynamic, as a skinned caster: refit at every draw, rebuilt
#     every rebuild_every frames), within a cap of triangles (BB_RT_STILL_MOVERS). One look
#     alone takes nothing: taking lasts for the life of the entry and beyond (its key is
#     remembered: an entry evicted and made again counts as moving at its first draw), so one
#     capture that went wrong must not do it. With count nothing is taken: the looks and the
#     log line only.
#  6. When. 2, 8 and 32 frames after the build, then every 64 to 95 frames (by the key), four
#     times more rarely for a caster without a palette the camera pass has not drawn for 8
#     frames. Three budgets of triangles a frame (the first look after a build; the two other
#     early looks; the looks in turn), so a level's load does not keep first looks waiting. A
#     caster over a budget waits a frame with its turn kept. Where the casters due in turn on a
#     frame are more than the budget lets through (4.4 million triangles of casters at 60000 a
#     frame: 74 frames), a look in turn is not due again before those have had theirs
#     (StillCrowd: the next look comes after that many frames, not after 64 to 95), so the
#     order in which the frame draws its casters cannot keep the late ones waiting for good.
#     The line prints the longest wait of a look and that number of frames.
#  7. No reference (built while the experiment bit was set, as a shared copy before an instance's
#     entry took it over, or its signature was lost): with on it is refit once, which makes the
#     BLAS current and gives the reference; with count the first look becomes the reference.
#  8. Lifetime. A signature on its way back points at its entry: Destroy takes an entry's out of
#     the four pending lists; a build or probe that was never recorded gives its count back at
#     the frame's end. No look while BB_RT_UPKEEP_FREEZE measures (r26). Shared copies (r43's
#     turns) are never looked at: they are rebuilt in turn. An instance's own entry (promoted by
#     its palette) is looked at like any other; the entry it adopts is admitted as moving if its
#     key is known to move.
#  9. A draw left out. The rasterizer leaves out a draw whose pipeline is still compiling
#     (vk_rasterizer.cpp, SkipUncompiledDraw) AFTER PrepareDraw set its capture up: no vertex
#     shader runs, the capture's range of the positions holds an earlier frame's data. The
#     rasterizer now says so (RtShadow::CaptureLeftOut, one call in that branch): the capture's
#     signature is given back, a probe is dropped and its look taken again at the caster's next
#     draw, and with BB_RT_STILL=on a build is dropped too (nothing is built from such
#     positions; the entry is built from its next draw that runs). With count the build stays
#     as it always was, unmeasured. Without this a first look at a caster whose build was left
#     out would have read as a move of metres.
# 10. Experiment 4611686018427387904 (bit 62, StillCheckOldBit in vk_rt_shadow.h) set = as
#     before: no probe, no signature, no pass, no copy, no read, no question to the driver; the
#     list of movers is not consulted; a left-out draw's build is recorded as it always was; a
#     caster the looks took as moving is held for still again at its next draw, and what the
#     looks knew of it is dropped (with the bit clear again it is refit once and looked at
#     anew). The bit is read at every draw. The pipeline and the two small buffers (64 KiB on
#     the GPU, 256 KiB for the host) are made at start either way unless BB_RT_STILL=off. Not
#     one of BbSettings::PreviousPathsBits: set brings the picture fault back.
#
# COST, not measured in the game. A probe makes its draw store its vertices: where the sun atlas
# would have skipped a cascade's draws, a probed caster's draw is kept for that frame (the sun
# atlas line's skip and kept-for-capture counts and the atlas pass time, bit set against clear,
# show it). The looks themselves: BB_RT_STILL_BUDGET + 2 x BB_RT_STILL_EARLY triangles a frame
# at most through the vertex shader and one compute dispatch a caster.
#
# KNOBS (environment variables, read once at start; out of range: clamped).
#   BB_RT_STILL            [on]      on|count|off  count: the looks and the log line, nothing is
#                                    taken as moving and no structure changes. off: nothing.
#   BB_RT_STILL_BUDGET     [60000]   triangles a frame looked at in turn (0..4000000)
#   BB_RT_STILL_EARLY      [100000]  the same for first looks, and once more for the two other
#                                    early looks (0..4000000)
#   BB_RT_STILL_TOLERANCE  [0.004]   metres the bounds may differ by (0.0005..0.1)
#   BB_RT_STILL_MOVERS     [400000]  the most triangles of living casters taken as moving
#                                    (0..16000000; 0: none is taken)
#   BB_RT_LAMP_LEAVE       [0]       diagnostic, a sum of classes whose instances lamp rays leave
#                                    out: 1 not drawn by the camera pass, 2 held for a sun
#                                    cascade, 4 shared copies, 8 instances' own entries, 16 held
#                                    for still by draw order, 32 moving and not shared, 64 r46's
#                                    cut-out cards (its default rule). Acts whatever the bits say.
#                                    Class 64 names what r46's rule 1 leaves out already: it
#                                    changes the picture only with r46's bit set or
#                                    BB_RT_LAMP_CARDS=0.
#
# LOG LINE, once every 600 frames with a scene, after r46's "Ray tracing cut-out cards" line:
#   "Ray tracing still check (r47): BB_RT_STILL=on (experiment 4611686018427387904 clear); a
#    frame A casters held for still captured again (B triangles; C first looks after a build, D
#    other early looks, E in turn; budgets ...), F waited for a budget (the longest wait of a
#    look W frames; the casters due in turn on the last frame need X frames at the budget), G
#    found no room, Y were drawn from another first instance; since the last line Z captures
#    left out with their draw, H refit once because nothing was known of the capture their BLAS
#    held, I builds measured, J signatures not usable, K looks found a caster moving (L for the
#    first time, M instance entries, N in the camera pass, O against the other pass's capture),
#    D2 of them asked for a second look, P taken as moving from now on (found so twice in a
#    row), Q not taken past the cap of ... triangles (R held by living casters), S known from
#    before and taken at their first draw, T held for still again; U casters known to move;
#    tolerance ...; lamp bit withheld by class alone (BB_RT_LAMP_LEAVE=0): V instances on the
#    last scene; moved farthest: mesh M (key K), N triangles, moved X m at look L, F frames after
#    the capture its BLAS was built from, box then (x y z)-(x y z), now (x y z)-(x y z), an
#    instance's own entry|known by draw order, by a camera pass draw|a sun shadow pass draw[
#    against the other pass's capture][, taken as moving]; ..." (up to four casters)
# What to read, standing with the torch after walking: a caster of the torch's size (a few
# hundred to a few thousand triangles) "moved" by decimetres or more "at look 1, 2 frames after
# the capture its BLAS was built from" was built in a passing pose; one found at a later look
# moves while drawn. "box then" is where its shadow came from, "now" where it is. A caster is
# "taken as moving" at the second of two looks in a row (D2 counts the first of them); K large
# while standing still with nothing moving in view, with moves of millimetres, would mean
# captures that do not repeat (not expected: see WHAT 2). X is 0 while a frame's casters due in
# turn fit the budget; W should stay near X. V counts only instances the diagnostic alone took
# out of lamp rays (not r46's cards, not r41's starved copies). r46's own line: with this patch
# at work more casters count as moving, so what its "old rule" numbers say is not what the
# engine did before both patches; read them with this patch's bit set.
#
# TEST. tests/test_rt_still_check.cpp (target rt-still-check-test): the keys' order, a
# signature's bounds, moves and tolerances, a capture's way from clip space to the world under
# two poses of the camera (144 cases, 3 to 120 m: the two-part way differs by 0.03 mm at most,
# the scene's one product by up to 47 mm), the looks' schedule and the crowd, the knobs, the
# classes. tests/test_rt_shadows.cpp --still (target rt-shadow-test, needs a GPU):
# rt_still_sig.comp and rt_unproject.comp as RecordBuilds runs them; the GPU's signature equals
# the header's word for word, a mesh captured again in place differs by 0, a moved one by its
# move, a still mesh under two poses of a perspective camera by less than 0.02 mm, and the
# positions end in world space.

import os
import re
import sys

# The tree: R47_ROOT when it is set; else the current directory when that is the root of a
# source tree (the script is run from there); else <tree>/, as the rounds before.
ROOT = os.environ.get("R47_ROOT")
if not ROOT:
    ROOT = os.getcwd() if os.path.isfile("engine/gpu/shadps4/video_core/renderer_vulkan/vk_rt_shadow.cpp") \
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

BIT = 62
VALUE = 1 << BIT  # 4611686018427387904
TMP = ".r47tmp"  # a new text waits under this name beside its target (main)

# The three files this round adds (apply writes them with CRLF line ends, revert removes them if
# they are still as written here).
NEW_FILES = {
    R + "rt_still_check.h": r"""// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r47_still-check): whether a caster of the ray tracing scene that is held for still
// has moved (RtShadow, vk_rt_shadow.cpp). No Vulkan here: tests/test_rt_still_check.cpp builds
// this header alone and runs the code the engine runs.
//
// A caster counts as moving only by two signs of its draw: a skeleton (a stride-16 buffer of 640
// bytes or more) or a small bone palette whose bytes changed. Every other caster is built once,
// in the pose of the frame it was first drawn, and never captured again while it is drawn: a
// prop moved by a one-bone palette, by its model matrix, or by a palette the game writes on the
// GPU (its bytes on the CPU never change) keeps the place of its first build in the scene and
// casts a lamp shadow that stays behind (a torch-shaped line on the ground while the torch is
// carried on).
//
// Now such a caster is looked at again in turn. Its draw is captured once more (a probe: nothing
// is built from it), the bounds of the vertices its triangles use are measured on the GPU in
// world space (host_shaders/rt_still_sig.comp, the signature), and they are compared with the
// bounds of the capture its bottom-level structure was built from. Past the tolerance on two
// looks in a row it counts as moving from then on, as a skinned caster does: refit at every
// draw. The first three looks come 2, 8 and 32 frames after the build (a caster first drawn in a
// passing pose is found on the first, and taken on the look that follows it at once), the later
// ones about once a second, four times more rarely for a caster the camera pass does not draw,
// and all of them more rarely while more casters are due than the budget lets through
// (StillCrowd).

#include <algorithm>
#include <array>
#include <bit>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

namespace Vulkan {

/// Signatures a frame, and the words of one (as rt_still_sig.comp writes them): 0-2 the
/// greatest inverted key of x, y, z (the least value), 3-5 the greatest key (the greatest
/// value), 6 the vertices taken, 7 those left out because a coordinate was not a finite number.
inline constexpr std::uint32_t StillSigsPerFrame = 2048;
inline constexpr std::uint32_t StillSigWords = 8;
/// The most indices of a mesh one dispatch of rt_still_sig.comp measures: every device runs
/// 65,535 work groups of its 64 threads, none need run more. A larger mesh is not looked at.
inline constexpr std::uint32_t StillSigIndicesMost = 65535u * 64u;
/// The looks of an entry that come early (StillNext), served from a budget of their own.
inline constexpr std::uint32_t StillEarlyChecks = 3;
/// BB_RT_STILL_BUDGET and BB_RT_STILL_EARLY: triangles a frame looked at again in turn, and for
/// the early looks; their most.
inline constexpr std::uint32_t StillBudget = 60000;
inline constexpr std::uint32_t StillEarly = 100000;
inline constexpr std::uint32_t StillBudgetMost = 4000000;
/// BB_RT_STILL_MOVERS: the most triangles of casters counted as moving by a look; its most.
inline constexpr std::uint32_t StillMovers = 400000;
inline constexpr std::uint32_t StillMoversMost = 16000000;
/// BB_RT_STILL_TOLERANCE, metres: a caster whose bounds differ by more has moved.
inline constexpr float StillTolerance = 0.004f;
inline constexpr float StillToleranceLeast = 0.0005f;
inline constexpr float StillToleranceMost = 0.1f;
/// The tolerance where the two captures come from different passes (the camera pass's draw
/// against a sun shadow pass's, whose vertex shader may place the mesh with a bias).
inline constexpr float StillCrossTolerance = 0.25f;
/// A caster counts as near while the camera pass drew it within this many frames.
inline constexpr std::uint32_t StillNearFrames = 8;
/// BB_RT_LAMP_LEAVE's most (seven classes, StillLeaveClasses).
inline constexpr std::uint32_t StillLeaveMost = 127;
/// The most frames StillCrowd gives (about a quarter of an hour).
inline constexpr std::uint32_t StillCrowdMost = 65536;

/// World bounds: least x, y, z, greatest x, y, z.
using StillBox = std::array<float, 6>;

/// A float as an unsigned number of the same order (-0 just below +0): what the shader's
/// atomicMax compares.
constexpr std::uint32_t StillKey(float value) {
    const std::uint32_t bits = std::bit_cast<std::uint32_t>(value);
    return (bits & 0x80000000u) != 0 ? ~bits : bits | 0x80000000u;
}
constexpr float StillUnkey(std::uint32_t key) {
    return std::bit_cast<float>((key & 0x80000000u) != 0 ? key & 0x7fffffffu : ~key);
}

/// One vertex into a signature, as rt_still_sig.comp does it (the tests compare the two).
constexpr void StillSigAdd(std::uint32_t* words, float x, float y, float z) {
    const std::array<float, 3> p{x, y, z};
    for (const float v : p) {
        if ((std::bit_cast<std::uint32_t>(v) & 0x7f800000u) == 0x7f800000u) {
            ++words[7];
            return;
        }
    }
    for (std::uint32_t k = 0; k < 3; ++k) {
        words[k] = std::max(words[k], ~StillKey(p[k]));
        words[3 + k] = std::max(words[3 + k], StillKey(p[k]));
    }
    ++words[6];
}

/// The bounds a signature holds. False when it holds none that can be compared: no vertex was
/// taken (the slot was never written), or one was left out (a caster with such a vertex would
/// seem to move whenever that vertex comes and goes).
constexpr bool DecodeStillSig(const std::uint32_t* words, StillBox& box) {
    if (words[6] == 0 || words[7] != 0) {
        return false;
    }
    for (std::uint32_t k = 0; k < 3; ++k) {
        box[k] = StillUnkey(~words[k]);
        box[3 + k] = StillUnkey(words[3 + k]);
    }
    return true;
}

/// For a capture's signature: what takes its clip space positions to world space, in two
/// parts. `inverse`: the inverse of the capture's projection (4x4 rows); `view_to_world`: its
/// view to world rows (3x4). `rows` (3x4) give the place of a clip space position relative to
/// the capture's camera, `origin` is the camera's place: world = rows * clip + origin.
/// Not the one 3x4 product the scene's positions are made with (RtShadow::ToWorld): the inverse
/// of a perspective projection rebuilds the 1 of a view space position from clip z and w, and
/// the product multiplies the camera's place by it: two terms of the size of (the camera's
/// distance from the world's origin) x depth / near plane that cancel. What their rounding
/// leaves (millimetres at 30 m, centimetres at 100 m) changes with every pose of the camera, so
/// a wall far away would read as moved whenever the camera did. The view space x, y and z come
/// from clip x, y and w without such terms, and the 1 is known.
constexpr void StillClipToWorld(const float* inverse, const float* view_to_world,
                                std::array<float, 12>& rows, std::array<float, 3>& origin) {
    for (std::uint32_t r = 0; r < 3; ++r) {
        for (std::uint32_t c = 0; c < 4; ++c) {
            double sum = 0.0;
            for (std::uint32_t k = 0; k < 3; ++k) {
                sum += double(view_to_world[r * 4 + k]) * double(inverse[k * 4 + c]);
            }
            rows[r * 4 + c] = float(sum);
        }
        origin[r] = view_to_world[r * 4 + 3];
    }
}
/// A clip space position's place in the world, as rt_still_sig.comp works it out.
constexpr std::array<float, 3> StillPoint(const std::array<float, 12>& rows,
                                          const std::array<float, 3>& origin, const float* clip) {
    std::array<float, 3> p{};
    for (std::uint32_t r = 0; r < 3; ++r) {
        p[r] = rows[r * 4] * clip[0] + rows[r * 4 + 1] * clip[1] + rows[r * 4 + 2] * clip[2] +
               rows[r * 4 + 3] * clip[3] + origin[r];
    }
    return p;
}

/// How far a caster moved between two captures: the greatest difference of the six bounds.
constexpr float StillMoved(const StillBox& a, const StillBox& b) {
    float most = 0.0f;
    for (std::uint32_t k = 0; k < 6; ++k) {
        const float d = a[k] > b[k] ? a[k] - b[k] : b[k] - a[k];
        most = d > most ? d : most;
    }
    return most;
}

/// The frames the casters whose look in turn was due on one frame need at the budget: `due`
/// triangles of them (looked at or kept waiting) against `budget` triangles a frame. 0 while
/// the budget lets them all through (and with no budget at all: no looks in turn).
constexpr std::uint32_t StillCrowd(std::uint64_t due, std::uint32_t budget) {
    if (budget == 0 || due <= budget) {
        return 0;
    }
    return std::uint32_t(std::min<std::uint64_t>((due + budget - 1) / budget, StillCrowdMost));
}

/// Frames from a look to the next one: `checks` looks were taken since the build, this one
/// counted (0: from the build to the first look). `key` spreads the later looks of the casters
/// over the frames; `nearby`: the camera pass draws it, or it has a bone palette (a prop).
/// `crowd` (StillCrowd): a look in turn does not come before the casters now waiting had
/// theirs. Without it the casters drawn first would take the budget again at every period and
/// those drawn last would never be looked at; with it all are, at the pace the budget allows.
constexpr std::uint32_t StillNext(std::uint32_t checks, std::uint64_t key, bool nearby,
                                  std::uint32_t crowd = 0) {
    constexpr std::array<std::uint32_t, StillEarlyChecks> early{2, 6, 24};
    if (checks < StillEarlyChecks) {
        return early[checks];
    }
    const std::uint32_t spread = std::uint32_t(key % 32);
    return std::max((64 + spread) * (nearby ? 1u : 4u), crowd + spread);
}

/// BB_RT_STILL: 2 on (the default, and for a text that is not understood), 1 count (the looks
/// and the log, nothing is counted as moving: the picture of before with the proof in the log),
/// 0 off.
enum : std::uint32_t { StillOff = 0, StillCount = 1, StillOn = 2 };
inline std::uint32_t ReadStillMode(const char* text) {
    if (!text) {
        return StillOn;
    }
    return std::strcmp(text, "off") == 0     ? StillOff
           : std::strcmp(text, "count") == 0 ? StillCount
                                             : StillOn;
}

/// BB_RT_STILL_TOLERANCE in metres, kept within its bounds; no text or not a number: the default.
inline float ReadStillTolerance(const char* text) {
    if (!text) {
        return StillTolerance;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    if (end == text || !std::isfinite(value)) {
        return StillTolerance;
    }
    return std::clamp(value, StillToleranceLeast, StillToleranceMost);
}

/// BB_RT_LAMP_LEAVE's classes of an instance of the scene (a diagnostic: lamp rays leave out
/// the instances of the classes the knob names, to tell which kind of caster throws a shadow):
/// 1 the camera pass does not draw it on this frame, 2 held for a sun cascade that is not drawn,
/// 4 a shared copy, 8 an instance's own entry (a prop known by its bone palette), 16 held for
/// still and known by its draw order, 32 moving and not a shared copy, 64 a cut-out card by
/// r46's default rule.
constexpr std::uint32_t StillLeaveClasses(bool camera, bool held, bool shared, bool instance,
                                          bool moving, bool card) {
    return (camera ? 0u : 1u) | (held ? 2u : 0u) | (shared ? 4u : 0u) | (instance ? 8u : 0u) |
           (!moving && !shared && !instance ? 16u : 0u) | (moving && !shared ? 32u : 0u) |
           (card ? 64u : 0u);
}

} // namespace Vulkan
""",
    H + "rt_still_sig.comp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r47_still-check): the world bounds of one captured mesh (RtShadow::RecordBuilds, before
// rt_unproject.comp brings its vertices to world space), into its signature: eight words that
// renderer_vulkan/rt_still_check.h reads (DecodeStillSig; StillPoint and StillSigAdd are this
// shader's sum on the CPU). One invocation an index of the mesh's triangle list: only the
// vertices its triangles use were written by the capture. The rest of its vertex range holds
// whatever an earlier frame left there, so the bounds cannot be gathered over the range (as
// rt_unproject.comp walks it). The slots are zeroed before the dispatch: every word only grows
// (the least value is kept as the greatest inverted key).
// The vertices are read as the capture stored them, in clip space, and brought to world space
// here in two parts: to their place about the capture's camera, then the camera's place is
// added. rt_unproject.comp's one matrix would round a far vertex by millimetres, differently for
// every pose of the camera (StillClipToWorld in rt_still_check.h says why), and a wall far away
// would seem to move whenever the camera does.

#version 460
#extension GL_EXT_buffer_reference : require
#extension GL_KHR_shader_subgroup_basic : require
#extension GL_KHR_shader_subgroup_arithmetic : require

layout(local_size_x = 64) in;

layout(buffer_reference, std430, buffer_reference_align = 4) readonly buffer Indices { uint i[]; };

layout(std430, set = 0, binding = 0) readonly buffer Positions { vec4 p[]; } positions;
layout(std430, set = 0, binding = 1) buffer Signatures { uint s[]; } signatures;

layout(push_constant) uniform Constants {
    vec4 row0;       // clip space to world space about the capture's camera (StillClipToWorld)
    vec4 row1;
    vec4 row2;
    vec3 origin;     // that camera's place in the world
    uint first;      // the mesh's first vertex in `positions`
    Indices indices; // its triangle list, relative to `first`
    uint count;      // indices
    uint slot;       // its signature
};

// A float as an unsigned number of the same order (StillKey).
uvec3 Key(vec3 v) {
    const uvec3 bits = floatBitsToUint(v);
    return mix(bits | uvec3(0x80000000u), ~bits, notEqual(bits & uvec3(0x80000000u), uvec3(0u)));
}

void main() {
    const uint id = gl_GlobalInvocationID.x;
    if (id >= count) {
        return;
    }
    const vec4 clip = positions.p[first + indices.i[id]];
    const vec3 p = vec3(dot(row0, clip), dot(row1, clip), dot(row2, clip)) + origin;
    // Not a finite number (all exponent bits set): counted and left out. 0 is below every key
    // and every inverted key of a finite number, so it leaves the greatest as it is.
    const bool finite = !any(equal(floatBitsToUint(p) & uvec3(0x7f800000u), uvec3(0x7f800000u)));
    const uvec3 key = Key(p);
    // One thread of each subgroup writes for all of it: the words are shared by the whole
    // dispatch, and seven atomics a vertex on the same seven words would queue up.
    const uvec3 least = subgroupMax(finite ? ~key : uvec3(0u));
    const uvec3 greatest = subgroupMax(finite ? key : uvec3(0u));
    const uint taken = subgroupAdd(finite ? 1u : 0u);
    const uint left = subgroupAdd(finite ? 0u : 1u);
    if (!subgroupElect()) {
        return;
    }
    const uint at = slot * 8u;
    for (uint k = 0u; k < 3u; ++k) {
        atomicMax(signatures.s[at + k], least[k]);
        atomicMax(signatures.s[at + 3u + k], greatest[k]);
    }
    atomicAdd(signatures.s[at + 6u], taken);
    atomicAdd(signatures.s[at + 7u], left);
}
""",
    TESTS + "test_rt_still_check.cpp": r"""// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r47_still-check): the looks at the ray tracing scene's casters held for still
// (rt_still_check.h): the order of the keys the shader compares, a signature's bounds, how far
// two captures differ, a capture's way from clip space to the world under two poses of the
// camera, when the next look comes, the knobs and BB_RT_LAMP_LEAVE's classes.
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"

using namespace Vulkan;

namespace {
using Sig = std::array<std::uint32_t, StillSigWords>;

// The signature of a mesh's vertices, each moved by `shift`.
Sig Measure(const std::array<std::array<float, 3>, 5>& mesh, float sx, float sy, float sz) {
    Sig sig{};
    for (const auto& p : mesh) {
        StillSigAdd(sig.data(), p[0] + sx, p[1] + sy, p[2] + sz);
    }
    return sig;
}

// A camera as the game's draws give it to RtShadow: view to world rows (3x4), the projection's
// inverse (4x4 rows), and what a vertex shader works with: world to view rows and the
// projection's four numbers. All in float, as the game holds them.
struct Camera {
    std::array<float, 12> view_to_world{}, world_to_view{};
    std::array<float, 16> inverse{};
    float p00 = 0, p11 = 0, a = 0, b = 0;
};
Camera MakeCamera(double yaw, double pitch, const std::array<double, 3>& at, double near_plane) {
    const double cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
    // The columns of view to world: the camera's right, up and back in the world.
    const double m[3][3] = {{cy, sy * sp, sy * cp}, {0.0, cp, -sp}, {-sy, cy * sp, cy * cp}};
    Camera c;
    for (int r = 0; r < 3; ++r) {
        double t = 0.0;
        for (int k = 0; k < 3; ++k) {
            c.view_to_world[r * 4 + k] = float(m[r][k]);
            c.world_to_view[r * 4 + k] = float(m[k][r]);
            t -= m[k][r] * at[k];
        }
        c.view_to_world[r * 4 + 3] = float(at[r]);
        c.world_to_view[r * 4 + 3] = float(t);
    }
    const double far_plane = 3000.0, p00 = 1.0 / std::tan(0.6), p11 = p00 * 16.0 / 9.0;
    const double a = far_plane / (near_plane - far_plane), b = near_plane * a;
    c.p00 = float(p00), c.p11 = float(p11), c.a = float(a), c.b = float(b);
    c.inverse = {float(1.0 / p00), 0, 0, 0, 0, float(1.0 / p11), 0, 0,
                 0, 0, 0, -1, 0, 0, float(1.0 / b), float(a / b)};
    return c;
}
// The clip space position a vertex shader stores for a point of the world.
std::array<float, 4> Clip(const Camera& c, const std::array<float, 3>& p) {
    std::array<float, 3> v{};
    for (int k = 0; k < 3; ++k) {
        v[k] = c.world_to_view[k * 4] * p[0] + c.world_to_view[k * 4 + 1] * p[1] +
               c.world_to_view[k * 4 + 2] * p[2] + c.world_to_view[k * 4 + 3];
    }
    return {c.p00 * v[0], c.p11 * v[1], c.a * v[2] + c.b, -v[2]};
}
// The one product the scene's positions are made with (RtShadow::ToWorld and
// rt_unproject.comp): what the signatures were first measured from.
std::array<float, 3> OneProduct(const Camera& c, const std::array<float, 4>& clip) {
    std::array<float, 3> p{};
    for (int r = 0; r < 3; ++r) {
        std::array<float, 4> row{};
        for (int col = 0; col < 4; ++col) {
            float sum = c.view_to_world[r * 4 + 3] * c.inverse[12 + col];
            for (int k = 0; k < 3; ++k) {
                sum += c.view_to_world[r * 4 + k] * c.inverse[k * 4 + col];
            }
            row[col] = sum;
        }
        p[r] = row[0] * clip[0] + row[1] * clip[1] + row[2] * clip[2] + row[3] * clip[3];
    }
    return p;
}
} // namespace

int main() {
    // Usable where the engine needs a constant; the layout the shader writes.
    static_assert(StillSigWords == 8 && StillSigsPerFrame == 2048 && StillEarlyChecks == 3);
    static_assert(StillKey(-1.0f) < StillKey(-0.0f) && StillKey(-0.0f) < StillKey(0.0f) &&
                  StillKey(0.0f) < StillKey(1.0f));
    static_assert(StillNext(0, 7, true) == 2 && StillNext(1, 7, false) == 6);

    // The keys keep the order of the floats, negative, zero and positive, and come back as the
    // same bits.
    const float inf = std::numeric_limits<float>::infinity();
    const std::array<float, 15> ordered{-inf, -3.0e38f, -1024.5f, -1.0f, -1.0e-30f,
                                        -std::numeric_limits<float>::denorm_min(), -0.0f, 0.0f,
                                        std::numeric_limits<float>::denorm_min(), 1.0e-30f,
                                        0.004f, 1.0f, 1024.5f, 3.0e38f, inf};
    for (std::size_t i = 0; i < ordered.size(); ++i) {
        const float v = ordered[i];
        assert(std::bit_cast<std::uint32_t>(StillUnkey(StillKey(v))) == std::bit_cast<std::uint32_t>(v));
        if (i + 1 < ordered.size()) {
            assert(StillKey(v) < StillKey(ordered[i + 1]));
        }
        // The least value is kept as the greatest inverted key.
        if (i > 0) {
            assert(~StillKey(v) < ~StillKey(ordered[i - 1]));
        }
    }
    // 0 is below every key and every inverted key of a finite number: a zeroed slot only grows.
    assert(StillKey(-std::numeric_limits<float>::max()) > 0 &&
           ~StillKey(std::numeric_limits<float>::max()) > 0);

    // A slot nothing was written to holds no bounds.
    StillBox box{};
    Sig empty{};
    assert(!DecodeStillSig(empty.data(), box));

    // A mesh on both sides of zero: the bounds are its least and greatest coordinates.
    const std::array<std::array<float, 3>, 5> mesh{{{-0.4f, 0.02f, 3.0f},
                                                    {0.5f, 0.10f, 2.2f},
                                                    {0.1f, -0.03f, 2.9f},
                                                    {-0.1f, 0.0f, 2.5f},
                                                    {0.45f, 0.09f, -0.0f}}};
    const Sig still = Measure(mesh, 0.0f, 0.0f, 0.0f);
    assert(still[6] == 5 && still[7] == 0 && DecodeStillSig(still.data(), box));
    assert(box[0] == -0.4f && box[1] == -0.03f && box[2] == -0.0f && box[3] == 0.5f &&
           box[4] == 0.10f && box[5] == 3.0f);
    // The order of the vertices does not matter (the shader's threads run in any order).
    Sig reversed{};
    for (std::size_t i = mesh.size(); i-- > 0;) {
        StillSigAdd(reversed.data(), mesh[i][0] + 0.0f, mesh[i][1] + 0.0f, mesh[i][2] + 0.0f);
    }
    assert(reversed == still);
    // -0 and +0 are two keys next to each other and the same place.
    Sig minus{}, plus{};
    StillSigAdd(minus.data(), -0.0f, -0.0f, -0.0f);
    StillSigAdd(plus.data(), 0.0f, 0.0f, 0.0f);
    StillBox at_minus{}, at_plus{};
    assert(minus != plus && DecodeStillSig(minus.data(), at_minus) &&
           DecodeStillSig(plus.data(), at_plus) && StillMoved(at_minus, at_plus) == 0.0f);

    // Captured again in the same place: no difference at all. Moved: the size of the move,
    // whichever way.
    StillBox again{}, moved{}, lifted{}, nudged{};
    assert(DecodeStillSig(Measure(mesh, 0.0f, 0.0f, 0.0f).data(), again));
    assert(StillMoved(box, again) == 0.0f);
    assert(DecodeStillSig(Measure(mesh, 0.5f, 0.0f, 0.0f).data(), moved));
    assert(std::abs(StillMoved(box, moved) - 0.5f) < 1e-6f && StillMoved(moved, box) == StillMoved(box, moved));
    assert(DecodeStillSig(Measure(mesh, 0.0f, -1.2f, 0.0f).data(), lifted));
    assert(std::abs(StillMoved(box, lifted) - 1.2f) < 1e-6f);
    // The tolerance: a millimetre is not a move, a centimetre is; a torch built lying on the
    // ground and carried a metre higher is one under the wide tolerance between the passes too.
    assert(DecodeStillSig(Measure(mesh, 0.001f, 0.0f, 0.0f).data(), nudged));
    assert(!(StillMoved(box, nudged) > StillTolerance));
    assert(DecodeStillSig(Measure(mesh, 0.0f, 0.0f, 0.01f).data(), nudged));
    assert(StillMoved(box, nudged) > StillTolerance && !(StillMoved(box, nudged) > StillCrossTolerance));
    assert(StillMoved(box, lifted) > StillCrossTolerance);
    // A caster that only turned in place moved too (its bounds changed).
    StillBox turned = box;
    turned[3] = box[3] - 0.2f;
    assert(StillMoved(box, turned) > StillTolerance);

    // A vertex that is not a finite number is counted and left out, and such a signature is
    // not compared: the caster would seem to move whenever that vertex comes and goes.
    Sig broken = still;
    StillSigAdd(broken.data(), std::numeric_limits<float>::quiet_NaN(), 0.0f, 0.0f);
    StillSigAdd(broken.data(), 0.0f, inf, 0.0f);
    StillSigAdd(broken.data(), 0.0f, 0.0f, -inf);
    assert(broken[6] == 5 && broken[7] == 3 && !DecodeStillSig(broken.data(), box));
    for (std::uint32_t k = 0; k < 6; ++k) {
        assert(broken[k] == still[k]);
    }

    // From clip space to the world. With nothing to undo, the rows are the view to world
    // turn and the origin its place.
    {
        const std::array<float, 16> same{1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1};
        const std::array<float, 12> place{1, 0, 0, 10.25f, 0, 1, 0, 1.5f, 0, 0, 1, -3.0f};
        std::array<float, 12> rows{};
        std::array<float, 3> origin{};
        StillClipToWorld(same.data(), place.data(), rows, origin);
        const std::array<float, 4> clip{0.5f, -2.0f, 4.0f, 1.0f};
        const auto p = StillPoint(rows, origin, clip.data());
        assert(origin[0] == 10.25f && origin[1] == 1.5f && origin[2] == -3.0f && rows[3] == 0.0f);
        assert(p[0] == 10.75f && p[1] == -0.5f && p[2] == 1.0f);
    }
    // A mesh that stands still, captured by the camera pass under two poses of the camera (the
    // camera a hundred metres from the world's origin, as in the game; moved and turned between
    // the captures), near and far, for three near planes. Its bounds must come out the same
    // within a fraction of the tolerance, and where the mesh stands; the one product the scene's
    // positions are made with gives bounds that differ by more than the tolerance far away,
    // which read as a move.
    float worst_new = 0.0f, worst_old = 0.0f, worst_place = 0.0f, worst_old_near = 0.0f;
    std::uint32_t old_over = 0, cases = 0, seed = 47;
    const auto random = [&] {
        seed = seed * 1664525u + 1013904223u;
        return double(seed >> 8) / double(1u << 24);
    };
    for (const double near_plane : {0.05, 0.1, 0.3}) {
        for (const double distance : {3.0, 30.0, 60.0, 120.0}) {
            for (int run = 0; run < 12; ++run, ++cases) {
                const std::array<double, 3> at{-22.0 + random(), -107.0 + random(), -26.0 + random()};
                const double yaw = 6.28 * random(), pitch = 0.6 * random() - 0.3;
                const Camera first = MakeCamera(yaw, pitch, at, near_plane);
                const Camera second = MakeCamera(yaw + 0.2, pitch - 0.05,
                                                 {at[0] + 0.3, at[1] + 0.1, at[2] - 0.2}, near_plane);
                // In front of the first camera (it looks along its -z).
                std::array<float, 3> centre{};
                for (int r = 0; r < 3; ++r) {
                    centre[r] = float(at[r] - double(first.view_to_world[r * 4 + 2]) * distance);
                }
                std::array<Sig, 2> sig_new{}, sig_old{};
                StillBox truth{};
                Sig sig_truth{};
                for (int v = 0; v < 200; ++v) {
                    const std::array<float, 3> p{centre[0] + float(2.0 * random() - 1.0),
                                                 centre[1] + float(2.0 * random() - 1.0),
                                                 centre[2] + float(2.0 * random() - 1.0)};
                    StillSigAdd(sig_truth.data(), p[0], p[1], p[2]);
                    const Camera* cameras[2] = {&first, &second};
                    for (int c = 0; c < 2; ++c) {
                        const auto clip = Clip(*cameras[c], p);
                        std::array<float, 12> rows{};
                        std::array<float, 3> origin{};
                        StillClipToWorld(cameras[c]->inverse.data(), cameras[c]->view_to_world.data(),
                                         rows, origin);
                        const auto q = StillPoint(rows, origin, clip.data());
                        StillSigAdd(sig_new[c].data(), q[0], q[1], q[2]);
                        const auto o = OneProduct(*cameras[c], clip);
                        StillSigAdd(sig_old[c].data(), o[0], o[1], o[2]);
                    }
                }
                std::array<StillBox, 2> box_new{}, box_old{};
                assert(DecodeStillSig(sig_truth.data(), truth));
                for (int c = 0; c < 2; ++c) {
                    assert(DecodeStillSig(sig_new[c].data(), box_new[c]));
                    assert(DecodeStillSig(sig_old[c].data(), box_old[c]));
                    worst_place = std::max(worst_place, StillMoved(truth, box_new[c]));
                }
                const float moved_new = StillMoved(box_new[0], box_new[1]);
                const float moved_old = StillMoved(box_old[0], box_old[1]);
                worst_new = std::max(worst_new, moved_new);
                worst_old = std::max(worst_old, moved_old);
                if (distance <= 3.0) {
                    worst_old_near = std::max(worst_old_near, moved_old);
                }
                old_over += moved_old > StillTolerance ? 1 : 0;
            }
        }
    }
    assert(worst_new < StillToleranceLeast / 4 && worst_place < StillToleranceLeast / 4);
    // The fault this guards against is there to be found: without it the test would prove
    // nothing.
    assert(old_over > 0 && worst_old > StillTolerance);

    // The looks: 2 frames after the build, 6 and 24 frames after the look before, then about
    // once a second, spread by the key; four times more rarely for a caster the camera pass does
    // not draw.
    assert(StillNext(0, 0, true) == 2 && StillNext(1, 0, true) == 6 && StillNext(2, 0, true) == 24);
    assert(StillNext(0, 99, false) == 2 && StillNext(2, 99, false) == 24);
    for (std::uint64_t key = 0; key < 200; ++key) {
        const std::uint32_t soon = StillNext(3, key, true), late = StillNext(200, key, false);
        assert(soon >= 64 && soon <= 95 && soon == 64 + key % 32 && late == 4 * soon);
        // More casters due than the budget lets through: a look in turn waits until those
        // now due had theirs, an early look does not.
        assert(StillNext(3, key, true, 10) == soon && StillNext(3, key, true, 500) == 500 + key % 32);
        assert(StillNext(3, key, false, 200) == late && StillNext(3, key, false, 500) == 500 + key % 32);
        assert(StillNext(0, key, true, 500) == 2 && StillNext(2, key, true, 500) == 24);
    }
    // The crowd: nothing while a frame's due casters fit the budget; else the frames they
    // need at it, rounded up and bounded. No budget: no looks in turn, nothing to put off.
    assert(StillCrowd(0, 60000) == 0 && StillCrowd(60000, 60000) == 0 && StillCrowd(60001, 60000) == 2);
    assert(StillCrowd(4400000, 60000) == 74 && StillCrowd(1000, 0) == 0);
    assert(StillCrowd(std::uint64_t(1) << 40, 1) == StillCrowdMost);
    // A mesh of more indices than one dispatch of the shader takes is not measured.
    static_assert(StillSigIndicesMost == 4194240 && (StillSigIndicesMost + 63) / 64 == 65535);

    // The knobs.
    assert(ReadStillMode(nullptr) == StillOn && ReadStillMode("on") == StillOn &&
           ReadStillMode("count") == StillCount && ReadStillMode("off") == StillOff &&
           ReadStillMode("") == StillOn && ReadStillMode("Count") == StillOn);
    assert(ReadStillTolerance(nullptr) == StillTolerance && ReadStillTolerance("") == StillTolerance &&
           ReadStillTolerance("x") == StillTolerance && ReadStillTolerance("nan") == StillTolerance &&
           ReadStillTolerance("0.01") == 0.01f && ReadStillTolerance("0") == StillToleranceLeast &&
           ReadStillTolerance("-1") == StillToleranceLeast && ReadStillTolerance("5") == StillToleranceMost);
    assert(StillTolerance > StillToleranceLeast && StillTolerance < StillToleranceMost &&
           StillCrossTolerance > StillToleranceMost);

    // BB_RT_LAMP_LEAVE's classes: (camera, held, shared, instance, moving, card).
    assert(StillLeaveClasses(true, false, false, false, false, false) == 16);  // a wall
    assert(StillLeaveClasses(false, false, false, false, false, false) == 17); // in the sun's pass alone
    assert(StillLeaveClasses(false, true, false, false, false, false) == 19);  // held for a cascade
    assert(StillLeaveClasses(true, false, true, false, true, false) == 4);     // a moving shared copy
    assert(StillLeaveClasses(true, false, false, true, false, false) == 8);    // a prop held for still
    assert(StillLeaveClasses(true, false, false, true, true, false) == 40);    // a prop found moving
    assert(StillLeaveClasses(true, false, false, false, true, false) == 32);   // a body
    assert(StillLeaveClasses(true, false, false, false, false, true) == 80);   // a plant
    std::uint32_t all = 0;
    for (std::uint32_t bits = 0; bits < 64; ++bits) {
        all |= StillLeaveClasses((bits & 1) != 0, (bits & 2) != 0, (bits & 4) != 0, (bits & 8) != 0,
                                 (bits & 16) != 0, (bits & 32) != 0);
    }
    assert(all == StillLeaveMost);

    std::printf("rt still check: ok (a mesh captured again in place differs by %.4f m, moved half "
                "a metre by %.4f m; tolerance %.4f m, %.2f m between the passes; looks %u frames "
                "after a build, %u and %u after the look before, then every %u to %u)\n",
                double(StillMoved(box, again)), double(StillMoved(again, moved)),
                double(StillTolerance), double(StillCrossTolerance), StillNext(0, 0, true),
                StillNext(1, 0, true), StillNext(2, 0, true), StillNext(3, 0, true),
                StillNext(3, 31, true));
    std::printf("rt still check: a still mesh under two poses of the camera, %u cases 3 to 120 m "
                "away: bounds differ by at most %.6f m (and from its true place by %.6f m); with "
                "the scene's one product by up to %.4f m (%.5f m at 3 m), past the tolerance in "
                "%u cases\n",
                cases, double(worst_new), double(worst_place), double(worst_old),
                double(worst_old_near), old_over);
    return 0;
}
""",
}

# Every (old, new) pair must match exactly once in the text it is applied to, in the order
# given; revert applies them backwards, new for old. In the files other rounds change as well
# (bbport_settings.h, gpu/CMakeLists.txt, tests/test_rt_shadows.cpp, vk_rasterizer.cpp) each old
# text is one or two whole lines, or the lines around the start of main.
EDITS = {
    S + "bbport_settings.h": [
        (r"""// set brings the plants' whole-polygon lamp shadows back.
""",
         r"""// set brings the plants' whole-polygon lamp shadows back.
// bbport (r47_still-check): nor is 62 (4611686018427387904; set = a ray tracing caster held for
// still is built once and never looked at again, vk_rt_shadow.h StillCheckOldBit), for the same
// reason: set brings the lamp shadow that stays where a carried torch was first drawn back.
"""),
    ],
    G + "CMakeLists.txt": [
        (r"""add_host_shader(rt_unproject.comp rt_unproject_comp)
""",
         r"""add_host_shader(rt_unproject.comp rt_unproject_comp)
# bbport (r47_still-check): the bounds of a captured mesh, for the looks at casters held for still
add_host_shader(rt_still_sig.comp rt_still_sig_comp)
"""),
        (r"""target_include_directories(rt-lamp-cards-test PRIVATE ..)
""",
         r"""target_include_directories(rt-lamp-cards-test PRIVATE ..)
# bbport (r47_still-check): whether a caster held for still has moved (rt_still_check.h)
add_executable(rt-still-check-test EXCLUDE_FROM_ALL ../tests/test_rt_still_check.cpp)
target_compile_options(rt-still-check-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(rt-still-check-test PRIVATE ..)
"""),
    ],
    TESTS + "test_rt_shadows.cpp": [
        (r"""#include <fstream>
""",
         r"""#include <fstream>
#include <limits>
"""),
        (r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
""",
         r"""#include "video_core/host_shaders/point_shadow_ray_half_comp.h" // bbport (r42_lamp-soft)
#include "video_core/host_shaders/rt_still_sig_comp.h" // bbport (r47_still-check)
"""),
        (r"""#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
""",
         r"""#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h" // bbport (r41_lamp-shadows)
#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
"""),
        (r"""}

int main(int argc, char** argv) {
""",
         r"""
// bbport (r47_still-check): --still: rt_still_sig.comp and rt_unproject.comp in the order
// RtShadow::RecordBuilds runs them (slots zeroed, bounds from the positions as the captures
// stored them, copy to the host, then to world space), on two meshes in one positions buffer.
// Each mesh's vertex range also holds vertices no triangle uses, filled as an earlier frame's
// capture would leave them, differently on every run. The signature the GPU writes must be the
// one rt_still_check.h makes of the vertices the triangles use, word for word; so a mesh
// captured again in place differs by nothing and a moved one by its move, whatever lies in the
// unused vertices. Then a mesh that stands still far from a perspective camera, captured under
// two poses of that camera: its bounds must not differ (the scene's own positions, made with
// one product, differ by more than the tolerance there).
bool StillLab(Vk& vk) {
    struct Unproject { float rows[12]; std::uint32_t first, count; };
    struct Sign { float rows[12]; float origin[3]; std::uint32_t first; std::uint64_t indices; std::uint32_t count, slot; };
    static_assert(sizeof(Unproject) == 56 && sizeof(Sign) == 80);
    // What takes a mesh's stored positions to the world: for the signature (two parts) and for
    // rt_unproject.comp (one product).
    struct Place { std::array<float, 12> rows{}; std::array<float, 3> origin{}; std::array<float, 12> product{}; };
    constexpr std::uint32_t Range = 600, Meshes = 2, Slots = 4, Words = Vulkan::StillSigWords;
    const Pipeline unproject = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(Unproject), RT_UNPROJECT_COMP, sizeof(RT_UNPROJECT_COMP));
    const Pipeline sign = vk.MakePipeline({VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER}, sizeof(Sign), RT_STILL_SIG_COMP, sizeof(RT_STILL_SIG_COMP));
    Buffer positions = vk.MakeBuffer(Meshes * Range * 16, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, true);
    Buffer sigs = vk.MakeBuffer(Slots * Words * 4, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, false);
    Buffer readback = vk.MakeBuffer(Slots * Words * 4, 0, true);
    // The triangles leave out every seventh vertex and the last hundred of the range.
    const auto unused = [](std::uint32_t v) { return v % 7 == 3 || v >= Range - 100; };
    std::vector<std::uint32_t> used, list;
    for (std::uint32_t v = 0; v < Range; ++v)
        if (!unused(v)) used.push_back(v);
    for (std::size_t i = 0; i + 2 < used.size(); ++i) list.insert(list.end(), {used[i], used[i + 1], used[i + 2]});
    Buffer indices = vk.MakeBuffer(list.size() * 4, 0, true);
    std::memcpy(indices.data, list.data(), list.size() * 4);
    std::mt19937 rng(47);
    std::uniform_real_distribution<float> coord(-2.0f, 2.0f);
    std::vector<float> local(Meshes * Range * 3);
    for (float& c : local) c = coord(rng);
    const float nan = std::numeric_limits<float>::quiet_NaN();
    bool ok = true;
    using Words8 = std::array<std::uint32_t, Words>;
    // One frame's commands over what the positions buffer holds: the GPU's signatures of the
    // two meshes and of a slot nothing writes to. Afterwards the positions are in world space.
    const auto run = [&](const std::array<Place, Meshes>& place) {
        vk.Begin();
        vkCmdFillBuffer(vk.cmd, sigs.buffer, 0, VK_WHOLE_SIZE, 0);
        vk.Barrier();
        const VkDescriptorBufferInfo position_info{positions.buffer, 0, VK_WHOLE_SIZE}, sig_info{sigs.buffer, 0, VK_WHOLE_SIZE};
        const std::array<VkWriteDescriptorSet, 2> writes{{
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 0, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &position_info},
            {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstBinding = 1, .descriptorCount = 1,
             .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &sig_info}}};
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, sign.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, sign.layout, 0, 2, writes.data());
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Sign push{{}, {}, m * Range, indices.address, std::uint32_t(list.size()), m};
            std::memcpy(push.rows, place[m].rows.data(), sizeof(push.rows));
            std::memcpy(push.origin, place[m].origin.data(), sizeof(push.origin));
            vkCmdPushConstants(vk.cmd, sign.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
            vkCmdDispatch(vk.cmd, (push.count + 63) / 64, 1, 1);
        }
        vk.Barrier();
        const VkBufferCopy copy{0, 0, Slots * Words * 4};
        vkCmdCopyBuffer(vk.cmd, sigs.buffer, readback.buffer, 1, &copy);
        vkCmdBindPipeline(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, unproject.pipeline);
        vk.push(vk.cmd, VK_PIPELINE_BIND_POINT_COMPUTE, unproject.layout, 0, 1, writes.data());
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Unproject push{{}, m * Range, Range};
            std::memcpy(push.rows, place[m].product.data(), sizeof(push.rows));
            vkCmdPushConstants(vk.cmd, unproject.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(push), &push);
            vkCmdDispatch(vk.cmd, (Range + 63) / 64, 1, 1);
        }
        vk.Barrier();
        vk.End();
        std::array<Words8, Meshes + 1> got{};
        std::memcpy(got.data(), readback.data, sizeof(got));
        return got;
    };
    // One capture of both meshes, each moved by its shift; `junk` is what the unused vertices
    // hold; `broken`: a vertex the second mesh's triangles use is not a number. The bounds, or
    // none where the signature holds none.
    const auto capture = [&](const std::array<Vec3, Meshes>& shift, float junk, bool broken) {
        auto* p = static_cast<float*>(positions.data);
        std::array<Words8, Meshes> want{};
        std::array<Place, Meshes> place{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            place[m].rows = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
            place[m].origin = {shift[m].x, shift[m].y, shift[m].z};
            place[m].product = {1, 0, 0, shift[m].x, 0, 1, 0, shift[m].y, 0, 0, 1, shift[m].z};
            for (std::uint32_t v = 0; v < Range; ++v) {
                const float* l = &local[(m * Range + v) * 3];
                float* at = p + (m * Range + v) * 4;
                at[0] = unused(v) ? junk * float(v + 1) : l[0];
                at[1] = unused(v) ? -junk : l[1];
                at[2] = unused(v) ? (v % 2 ? nan : junk) : l[2];
                at[3] = 1.0f;
            }
            if (broken && m == 1) p[(m * Range + used[5]) * 4 + 1] = nan;
            for (const std::uint32_t i : list) {
                const auto q = Vulkan::StillPoint(place[m].rows, place[m].origin, p + (m * Range + i) * 4);
                Vulkan::StillSigAdd(want[m].data(), q[0], q[1], q[2]);
            }
        }
        const auto got = run(place);
        std::array<Vulkan::StillBox, Meshes> boxes{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            if (got[m] != want[m]) {
                std::fprintf(stderr, "still check: mesh %u: the shader's signature is not rt_still_check.h's (vertices taken %u against %u, left out %u against %u)\n",
                             m, got[m][6], want[m][6], got[m][7], want[m][7]);
                ok = false;
            }
            if (Vulkan::DecodeStillSig(got[m].data(), boxes[m]) != !(broken && m == 1)) {
                std::fprintf(stderr, "still check: mesh %u: the signature %s\n", m, broken && m == 1 ? "of a mesh with a vertex that is not a number was taken" : "holds no bounds");
                ok = false;
            }
        }
        Vulkan::StillBox none{};
        if (Vulkan::DecodeStillSig(got[Meshes].data(), none)) {
            std::fprintf(stderr, "still check: a slot no mesh wrote to holds bounds\n");
            ok = false;
        }
        // The pass after the signatures brought the stored positions to world space.
        const float* l = &local[used[0] * 3];
        const float* w = p + used[0] * 4;
        if (w[0] != l[0] + shift[0].x || w[1] != l[1] + shift[0].y || w[2] != l[2] + shift[0].z) {
            std::fprintf(stderr, "still check: the positions are not in world space after the signatures\n");
            ok = false;
        }
        return boxes;
    };
    const Vec3 a{10.25f, 1.5f, -3.0f}, b{-4.0f, 0.5f, 7.0f};
    const auto first = capture({a, b}, 1.0e6f, false);
    const auto again = capture({a, b}, -3.0e5f, false);
    const auto moved = capture({Vec3{a.x + 0.5f, a.y - 1.0f, a.z + 0.02f}, b}, 77.0f, false);
    const auto nudged = capture({Vec3{a.x + 0.001f, a.y, a.z}, b}, 1.0e6f, false);
    capture({a, b}, 1.0e6f, true);
    const float same_a = Vulkan::StillMoved(first[0], again[0]), same_b = Vulkan::StillMoved(first[1], again[1]);
    const float far_a = Vulkan::StillMoved(first[0], moved[0]), far_b = Vulkan::StillMoved(first[1], moved[1]);
    const float near_a = Vulkan::StillMoved(first[0], nudged[0]);
    std::printf("Still check: %zu indices over %zu of %u vertices a mesh; captured again in place: %.6f m and %.6f m; one mesh moved by "
                "(0.5 -1 0.02): %.4f m, the other %.6f m; moved by 1 mm: %.5f m (tolerance %.4f m, %.2f m between the passes)\n",
                list.size(), used.size(), Range, double(same_a), double(same_b), double(far_a), double(far_b), double(near_a),
                double(Vulkan::StillTolerance), double(Vulkan::StillCrossTolerance));
    if (same_a != 0.0f || same_b != 0.0f || far_b != 0.0f) {
        std::fprintf(stderr, "still check: a mesh that did not move differs between two captures\n");
        ok = false;
    }
    if (std::abs(far_a - 1.0f) > 1e-4f || !(far_a > Vulkan::StillCrossTolerance)) {
        std::fprintf(stderr, "still check: a mesh moved by a metre is not found moved by a metre\n");
        ok = false;
    }
    if (near_a > Vulkan::StillTolerance || !(near_a > 0.0f)) {
        std::fprintf(stderr, "still check: a move of a millimetre is not within the tolerance, or not seen at all\n");
        ok = false;
    }

    // Two poses of a perspective camera about a hundred metres from the world's origin (as in
    // the game), near plane 0.1 m; the first mesh stands 60 m in front of it, the second 3 m,
    // neither moves. What a vertex shader stores (clip space, in float) goes through the GPU's
    // signature; beside it, on the CPU, the bounds of the positions rt_unproject.comp's one
    // product makes of the same captures.
    struct Camera {
        std::array<float, 12> view_to_world{}, world_to_view{};
        std::array<float, 16> inverse{};
        float p00 = 0, p11 = 0, a = 0, b = 0;
    };
    const auto camera_at = [](double yaw, double pitch, const std::array<double, 3>& at) {
        const double cy = std::cos(yaw), sy = std::sin(yaw), cp = std::cos(pitch), sp = std::sin(pitch);
        const double turn[3][3] = {{cy, sy * sp, sy * cp}, {0.0, cp, -sp}, {-sy, cy * sp, cy * cp}};
        Camera c;
        for (int r = 0; r < 3; ++r) {
            double t = 0.0;
            for (int k = 0; k < 3; ++k) {
                c.view_to_world[r * 4 + k] = float(turn[r][k]);
                c.world_to_view[r * 4 + k] = float(turn[k][r]);
                t -= turn[k][r] * at[k];
            }
            c.view_to_world[r * 4 + 3] = float(at[r]);
            c.world_to_view[r * 4 + 3] = float(t);
        }
        const double near_plane = 0.1, far_plane = 3000.0, p00 = 1.0 / std::tan(0.6), p11 = p00 * 16.0 / 9.0;
        const double za = far_plane / (near_plane - far_plane), zb = near_plane * za;
        c.p00 = float(p00), c.p11 = float(p11), c.a = float(za), c.b = float(zb);
        c.inverse = {float(1.0 / p00), 0, 0, 0, 0, float(1.0 / p11), 0, 0, 0, 0, 0, -1, 0, 0, float(1.0 / zb), float(za / zb)};
        return c;
    };
    const std::array<double, 3> eye{-22.3, -107.1, -26.1};
    const std::array<Camera, 2> cameras{camera_at(0.7, -0.1, eye), camera_at(0.9, -0.15, {eye[0] + 0.3, eye[1] + 0.1, eye[2] - 0.2})};
    const std::array<double, Meshes> ahead{60.0, 3.0};
    std::array<std::array<Vulkan::StillBox, Meshes>, 2> seen{}, product{};
    float off = 0.0f;
    for (std::uint32_t pose = 0; pose < 2; ++pose) {
        const Camera& c = cameras[pose];
        auto* p = static_cast<float*>(positions.data);
        std::array<Place, Meshes> place{};
        std::array<Words8, Meshes> want{}, old{};
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Vulkan::StillClipToWorld(c.inverse.data(), c.view_to_world.data(), place[m].rows, place[m].origin);
            for (int r = 0; r < 3; ++r) {
                for (int col = 0; col < 4; ++col) {
                    float sum = c.view_to_world[r * 4 + 3] * c.inverse[12 + col];
                    for (int k = 0; k < 3; ++k) sum += c.view_to_world[r * 4 + k] * c.inverse[k * 4 + col];
                    place[m].product[r * 4 + col] = sum;
                }
            }
            for (std::uint32_t v = 0; v < Range; ++v) {
                // The mesh in the world: in front of the first camera, the same for both poses.
                const float* l = &local[(m * Range + v) * 3];
                float world[3], view[3];
                for (int r = 0; r < 3; ++r) world[r] = float(eye[r] - double(cameras[0].view_to_world[r * 4 + 2]) * ahead[m]) + l[r];
                for (int k = 0; k < 3; ++k) view[k] = c.world_to_view[k * 4] * world[0] + c.world_to_view[k * 4 + 1] * world[1] + c.world_to_view[k * 4 + 2] * world[2] + c.world_to_view[k * 4 + 3];
                float* at = p + (m * Range + v) * 4;
                at[0] = c.p00 * view[0], at[1] = c.p11 * view[1], at[2] = c.a * view[2] + c.b, at[3] = -view[2];
                if (unused(v)) at[0] = 1.0e6f * float(pose + 1), at[1] = nan;
            }
            for (const std::uint32_t i : list) {
                const float* at = p + (m * Range + i) * 4;
                const auto q = Vulkan::StillPoint(place[m].rows, place[m].origin, at);
                Vulkan::StillSigAdd(want[m].data(), q[0], q[1], q[2]);
                const float* row = place[m].product.data();
                Vulkan::StillSigAdd(old[m].data(), row[0] * at[0] + row[1] * at[1] + row[2] * at[2] + row[3] * at[3],
                                    row[4] * at[0] + row[5] * at[1] + row[6] * at[2] + row[7] * at[3],
                                    row[8] * at[0] + row[9] * at[1] + row[10] * at[2] + row[11] * at[3]);
            }
        }
        const auto got = run(place);
        for (std::uint32_t m = 0; m < Meshes; ++m) {
            Vulkan::StillBox cpu{};
            if (!Vulkan::DecodeStillSig(got[m].data(), seen[pose][m]) || !Vulkan::DecodeStillSig(want[m].data(), cpu) ||
                !Vulkan::DecodeStillSig(old[m].data(), product[pose][m]) || got[m][6] != want[m][6]) {
                std::fprintf(stderr, "still check: pose %u, mesh %u: no bounds\n", pose, m);
                ok = false;
            }
            // The GPU may round a sum of products another way than the CPU: not word for word.
            off = std::max(off, Vulkan::StillMoved(seen[pose][m], cpu));
        }
    }
    const float far_seen = Vulkan::StillMoved(seen[0][0], seen[1][0]), near_seen = Vulkan::StillMoved(seen[0][1], seen[1][1]);
    const float far_product = Vulkan::StillMoved(product[0][0], product[1][0]), near_product = Vulkan::StillMoved(product[0][1], product[1][1]);
    std::printf("Still check: a still mesh under two poses of the camera: its bounds differ by %.6f m at 60 m and %.6f m at 3 m "
                "(the scene's one product: %.5f m and %.5f m); the GPU's bounds are within %.6f m of rt_still_check.h's\n",
                double(far_seen), double(near_seen), double(far_product), double(near_product), double(off));
    if (far_seen > Vulkan::StillToleranceLeast / 4 || near_seen > Vulkan::StillToleranceLeast / 4 || off > Vulkan::StillToleranceLeast / 4) {
        std::fprintf(stderr, "still check: a mesh that stands still reads as moved when the camera moves\n");
        ok = false;
    }
    for (Buffer* buffer : {&positions, &sigs, &readback, &indices}) vk.Free(*buffer);
    std::puts(ok ? "Still check: ok" : "Still check: FAILED");
    return ok;
}
}

int main(int argc, char** argv) {
"""),
        (r"""    std::printf("GPU: %s, %ux%u, atlas %u\n", vk.name, W, H, Atlas);
""",
         r"""    std::printf("GPU: %s, %ux%u, atlas %u\n", vk.name, W, H, Atlas);
    if (argc > 1 && std::strcmp(argv[1], "--still") == 0) { // bbport (r47_still-check)
        return StillLab(vk) ? 0 : 1;
    }
"""),
    ],
    R + "vk_rasterizer.cpp": [
        (r"""        if (SkipUncompiledDraw(pipeline)) {
""",
         r"""        if (SkipUncompiledDraw(pipeline)) {
            // bbport (r47_still-check): what this draw was to store for ray tracing
            // (EffectsCaptureDraw, above) is not stored
            if (dc.capture_draw) {
                rt_shadow->CaptureLeftOut(dc.push_data.motion_param,
                                          pipeline->GetGraphicsKey().motion_vectors);
            }
"""),
    ],
    R + "vk_rt_shadow.h": [
        (r"""#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
""",
         r"""#include "video_core/renderer_vulkan/rt_copy_turns.h" // bbport (r43_copy-turns)
#include "video_core/renderer_vulkan/rt_still_check.h" // bbport (r47_still-check)
"""),
        (r"""inline constexpr u64 LampCardsOldBit = 9223372036854775808ull;
""",
         r"""inline constexpr u64 LampCardsOldBit = 9223372036854775808ull;

// bbport (r47_still-check): experiment bit 62: set = a caster held for still is built once and
// never looked at again, as before (rt_still_check.h): no probes, no signatures, the casters a
// look found moving are held for still again, the list of them is not read. Read at every draw
// and every frame end. Set brings the picture fault back (a lamp shadow that stays where a
// carried torch was first drawn), so it is not one of BbSettings::PreviousPathsBits. Not bit 62
// of the other mask (BbToggle::CameraYFlip).
inline constexpr u64 StillCheckOldBit = 4611686018427387904ull;
"""),
        (r"""    u32 PrepareDraw(const Draw& draw);
""",
         r"""    u32 PrepareDraw(const Draw& draw);
    // bbport (r47_still-check): the draw PrepareDraw was last called for is left out by the
    // rasterizer after all (see the definition).
    void CaptureLeftOut(u32 motion_param, u32 mode);
"""),
        (r"""        u16 turn_back_run = 0;
""",
         r"""        u16 turn_back_run = 0;
        // bbport (r47_still-check): a caster held for still (not moving, not a shared copy) is
        // looked at again in turn (rt_still_check.h). still_ref: the world bounds of the capture
        // its BLAS was built from, as a camera pass draw gave them ([0]) and as a sun shadow
        // pass draw did ([1]), where still_has_ref; still_ref_frame: the frame of that capture.
        // still_next: the frame of its next look; still_checks: looks since the build (the
        // first ones come early); still_wait: its signatures on their way back from the GPU
        // (still_pending points at it). still_camera_frame: its last camera pass draw.
        // still_moved: a look found it moving and `dynamic` was set for that (taken back while
        // the experiment bit is set); still_seen: found moving at least once (the log's "for
        // the first time"); still_blind: the signature of its last capture held no bounds (a
        // vertex that is not a number): no looks until its BLAS is built anew. still_doubt: the
        // last look found it moved and asked for a second one, which decides (ReadStillSigs).
        std::array<StillBox, 2> still_ref{};
        std::array<bool, 2> still_has_ref{};
        u64 still_ref_frame = 0;
        u64 still_next = 0;
        u64 still_camera_frame = 0;
        u8 still_checks = 0;
        u8 still_wait = 0;
        bool still_moved = false;
        bool still_seen = false;
        bool still_blind = false;
        bool still_doubt = false;
"""),
        (r"""        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
""",
         r"""        u64 inputs = 0;    // bbport (r17_rt-upkeep): Draw::inputs of the capture
        // bbport (r47_still-check): the signature this capture's bounds go to (1 to
        // StillSigsPerFrame; 0: none), drawn by the camera pass (else by a sun shadow pass),
        // whether the BLAS is built from this capture (its bounds are the reference from then
        // on), and whether it is a probe: captured and measured only, nothing is built.
        // still_rows, still_origin: what takes the capture's clip space positions to world space
        // for the signature (StillClipToWorld; set with sig). param: its capture param, and
        // left_out: the rasterizer left its draw out, nothing is done with it (CaptureLeftOut).
        u32 sig = 0;
        bool still_camera = false;
        bool still_first = false;
        bool probe = false;
        bool left_out = false;
        u32 param = 0;
        std::array<float, 12> still_rows{};
        std::array<float, 3> still_origin{};
"""),
        (r"""    } turn_stats;
""",
         r"""    } turn_stats;
    // bbport (r47_still-check): the looks at the casters held for still (rt_still_check.h).
    // still_ready: the signature pipeline and its buffers are there (else no looks).
    // still_sigs: a frame's signatures on the GPU (device local, for the shader's atomics);
    // still_readback: their copies for the host, a ring of four frames like the capture
    // params. still_pending: the signatures recorded on each of those frames, and still_ticks
    // the tick of their submission: a frame's list is read once the GPU has passed its tick
    // (at the latest when the ring comes back to it) and points at entries until then, so
    // Destroy takes an entry's out. Per frame: the signatures taken, and the triangles looked
    // at in each lane (StillLanes: an entry's first look after a build, its other early looks,
    // the looks in turn; each lane has its budget, so a level's load, which queues three early
    // looks for every new caster, does not keep the first look of any of them waiting behind
    // the others). still_movers: the casters a look found moving, by the key of their entry
    // (the draw order key, or InstanceKey for an instance's own): one that is evicted and comes
    // back counts as moving at once. still_mover_triangles: those of the living entries so
    // counted, which BB_RT_STILL_MOVERS bounds (they are refit at every draw).
    // still_leave_count: instances BB_RT_LAMP_LEAVE alone left out of lamp rays in the records
    // last written. still_due, still_due_last: the triangles of the casters whose look in turn
    // was due on this frame so far and on the frame before, looked at or kept waiting: the next
    // look of each is put off while they are more than the budget (StillCrowd).
    bool still_ready = false;
    vk::UniqueDescriptorSetLayout still_set;
    vk::UniquePipelineLayout still_layout;
    vk::UniquePipeline still_pipeline;
    Buffer still_sigs, still_readback;
    struct StillPending {
        Entry* entry;
        u64 frame;
        u32 sig;
        bool camera;
        bool first;
    };
    std::array<std::vector<StillPending>, 4> still_pending;
    std::array<u64, 4> still_ticks{};
    static constexpr u32 StillLanes = 3;
    u32 still_sig_used = 0;
    std::array<u32, StillLanes> still_used{};
    std::unordered_set<u64> still_movers;
    u64 still_mover_triangles = 0;
    u32 still_leave_count = 0;
    u64 still_due = 0, still_due_last = 0;
    // What is done now: StillOff (also with the experiment bit set, or not ready), StillCount
    // or StillOn.
    [[nodiscard]] u32 StillNow() const;
    u32 TakeStillSig(Entry& entry);
    bool StillWorld(const float* constants, Build& build) const;
    void StillAdmit(Entry& entry, u64 id);
    void ReadStillSigs(u32 slot);
    // For the 600-frame line: a caster a look found moving (the four that moved farthest are
    // kept, each caster once), and the counts since the last line.
    struct StillFound {
        u64 id = 0, key = 0, mesh = 0, after = 0;
        u32 triangles = 0, checks = 0;
        float moved = 0.0f;
        StillBox then{}, now{};
        bool instance = false, camera = false, cross = false, taken = false;
    };
    struct StillStats {
        u64 probe_triangles = 0, waited = 0, no_room = 0, refits = 0, firsts = 0, unread = 0,
            found = 0, found_new = 0, found_instance = 0, found_camera = 0, found_cross = 0,
            taken = 0, not_taken = 0, known = 0, taken_back = 0, other_draw = 0, left_out = 0,
            doubted = 0, longest_wait = 0;
        std::array<u64, StillLanes> probes{};
        std::array<StillFound, 4> largest{};
    } still_stats;
"""),
    ],
    R + "vk_rt_shadow.cpp": [
        (r"""#include <cmath>
""",
         r"""#include <cmath>
#include <cstddef> // bbport (r47_still-check): offsetof
"""),
        (r"""#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
""",
         r"""#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_still_sig_comp.h"         // bbport (r47_still-check)
"""),
        (r"""    return level;
""",
         r"""    return level;
}
// bbport (r47_still-check): the knobs of the looks at casters held for still (rt_still_check.h),
// each read once. BB_RT_STILL: on (the default), count (the looks and the 600-frame line, but
// nothing is counted as moving: the picture and every structure as before, with the proof in the
// log) or off. BB_RT_STILL_BUDGET: triangles a frame looked at again in turn (default
// StillBudget, 60,000; at most StillBudgetMost; 0: none). BB_RT_STILL_EARLY: the same for the
// first look after a build, and once more for the other early looks (the first StillEarlyChecks;
// default StillEarly, 100,000). A caster whose turn finds its budget used up waits for the next
// frame. So that those drawn first do not take the budget again at every period while those
// drawn last wait for good, a look in turn does not come again before the casters that were due
// on the frame before had theirs (StillCrowd): where a scene holds more casters than the budget
// lets through at the usual pace, all of them are looked at, more rarely. The caster that
// crosses a budget is still looked at. BB_RT_STILL_TOLERANCE: metres its bounds may differ by
// (default StillTolerance, 0.004; StillToleranceLeast to StillToleranceMost).
// BB_RT_STILL_MOVERS: the most triangles of living casters the looks count as moving, which are
// refit at every draw (default StillMovers, 400,000; at most StillMoversMost; 0: none is taken).
u32 StillMode() {
    static const u32 mode = ReadStillMode(std::getenv("BB_RT_STILL"));
    return mode;
}
u32 StillLane(bool early) {
    static const u32 turn =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_BUDGET"), StillBudget, StillBudgetMost);
    static const u32 first =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_EARLY"), StillEarly, StillBudgetMost);
    return early ? first : turn;
}
float StillLimit() {
    static const float limit = ReadStillTolerance(std::getenv("BB_RT_STILL_TOLERANCE"));
    return limit;
}
u32 StillMoverCap() {
    static const u32 cap =
        ReadCopyTurnKnob(std::getenv("BB_RT_STILL_MOVERS"), StillMovers, StillMoversMost);
    return cap;
}
// BB_RT_LAMP_LEAVE, read once (default 0: nothing; at most StillLeaveMost): a diagnostic that
// tells which kind of caster throws a lamp shadow. Lamp rays leave out the instances of the
// classes it names (StillLeaveClasses: 1 not drawn by the camera pass, 2 held for a sun cascade,
// 4 shared copies, 8 instances' own entries, 16 held for still by draw order, 32 moving and not
// shared, 64 r46's cut-out cards). It acts whatever BB_RT_STILL and the experiment bits say.
u32 LampLeave() {
    static const u32 classes =
        ReadCopyTurnKnob(std::getenv("BB_RT_LAMP_LEAVE"), 0, StillLeaveMost);
    return classes;
"""),
        (r"""static_assert(sizeof(UnprojectPush) == 56);

""",
         r"""static_assert(sizeof(UnprojectPush) == 56);

// bbport (r47_still-check): rt_still_sig.comp's push constants: what takes a capture's clip
// space positions to world space (StillClipToWorld), the mesh's first vertex in `positions`,
// the address of its triangle list, its indices, its signature's place.
struct StillPush {
    std::array<float, 12> rows;
    std::array<float, 3> origin;
    u32 first;
    u64 indices;
    u32 count;
    u32 slot;
};
static_assert(sizeof(StillPush) == 80 && offsetof(StillPush, first) == 60 &&
              offsetof(StillPush, indices) == 64 && offsetof(StillPush, slot) == 76);

// The key of an instance's own entry (see PrepareDraw): its mesh key and its bone palette.
u64 InstanceKey(u64 key, u64 palette) {
    return XXH3_64bits_withSeed(&palette, sizeof(palette), key ^ 0xa24baed4963ee407ull);
}

"""),
        (r"""    Free(r25_readback);
""",
         r"""    Free(r25_readback);
    Free(still_sigs); // bbport (r47_still-check)
    Free(still_readback);
"""),
        (r"""    entry.scene_bytes = 0;
""",
         r"""    entry.scene_bytes = 0;
    // bbport (r47_still-check): its signatures still on their way back are not read (the lists
    // point at the entry), and it no longer counts against the cap of the casters found moving.
    if (entry.still_wait != 0) {
        for (auto& list : still_pending) {
            std::erase_if(list, [&](const StillPending& item) { return item.entry == &entry; });
        }
        entry.still_wait = 0;
    }
    if (entry.still_moved) {
        still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        entry.still_moved = false;
    }
"""),
        (r"""    std::memset(r25_readback.mapped, 0, R25Slots * sizeof(u32));
""",
         r"""    std::memset(r25_readback.mapped, 0, R25Slots * sizeof(u32));
    // bbport (r47_still-check): the signature pass and its buffers, unless BB_RT_STILL=off.
    // Without them there are no looks; ray tracing is as before. The copies the host reads lie
    // in memory it reads fast (Make's host buffers are for writing, as the sun VSM's Make notes
    // for its own readback).
    if (StillMode() != StillOff) {
        const vk::DeviceSize sig_bytes = vk::DeviceSize(StillSigsPerFrame) * StillSigWords * 4;
        const VkBufferCreateInfo readback_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = 4 * sig_bytes,
            .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo readback_alloc{.usage = VMA_MEMORY_USAGE_AUTO};
        readback_alloc.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        readback_alloc.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer readback{};
        VmaAllocationInfo readback_info{};
        // rt_still_sig.comp gathers a subgroup's bounds before one of its threads writes them:
        // the arithmetic subgroup operations in a compute shader, which a device need not have.
        const auto subgroup =
            instance.GetPhysicalDevice()
                .getProperties2<vk::PhysicalDeviceProperties2, vk::PhysicalDeviceSubgroupProperties>()
                .get<vk::PhysicalDeviceSubgroupProperties>();
        const bool subgroups =
            (subgroup.supportedStages & vk::ShaderStageFlagBits::eCompute) &&
            (subgroup.supportedOperations & vk::SubgroupFeatureFlagBits::eArithmetic);
        still_ready =
            subgroups &&
            EffectPass::Create(instance, still_set, still_layout, still_pipeline,
                               {eStorageBuffer, eStorageBuffer}, sizeof(StillPush),
                               RT_STILL_SIG_COMP, "Ray tracing still check") &&
            Make(still_sigs, sig_bytes, false,
                 VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                     VK_BUFFER_USAGE_TRANSFER_DST_BIT) &&
            vmaCreateBuffer(instance.GetAllocator(), &readback_ci, &readback_alloc, &readback,
                            &still_readback.allocation, &readback_info) == VK_SUCCESS;
        still_readback.buffer = readback;
        still_readback.mapped = readback_info.pMappedData;
        still_ready = still_ready && still_readback.mapped;
        if (still_ready) {
            std::memset(still_readback.mapped, 0, std::size_t(4 * sig_bytes));
        } else {
            std::printf("Ray tracing still check (r47): off - %s\n",
                        subgroups ? "no signature pipeline or buffer"
                                  : "this GPU has no subgroup arithmetic in compute shaders");
        }
    }
"""),
        (r"""    if (palette_draw) {
        instance_key = XXH3_64bits_withSeed(&draw.palette, sizeof(draw.palette), key ^ 0xa24baed4963ee407ull);
""",
         r"""    if (palette_draw) {
        instance_key = InstanceKey(key, draw.palette);
"""),
        (r"""                adopted->instance = true;
""",
         r"""                adopted->instance = true;
                StillAdmit(*adopted, instance_key); // bbport (r47_still-check)
"""),
        (r"""            stats.promoted += promote ? 1 : 0;
""",
         r"""            stats.promoted += promote ? 1 : 0;
            // bbport (r47_still-check): a caster a look found moving before it was evicted
            // counts as moving from its first draw
            StillAdmit(*slot, entry_key);
"""),
        (r"""    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
""",
         r"""    entry.card_camera = entry.card_camera || (draw.camera_pass && draw.alpha);
    // bbport (r47_still-check): the last camera pass draw of it, also when a sun cascade drew
    // it first on the frame (a caster the camera pass draws is looked at more often)
    if (draw.camera_pass) {
        entry.still_camera_frame = frame;
    }
"""),
        (r"""        }
    }
    if (entry.palette != draw.palette) {
""",
         r"""        }
    }
    // bbport (r47_still-check): what is done about casters held for still on this draw. With
    // the experiment bit set while the game runs, a caster the looks found moving is held for
    // still again, as before: its BLAS keeps the pose of its last refit. No bounds were taken
    // of that pose (a moving caster's captures are not measured), so what the looks knew of the
    // caster no longer holds: with the bit clear again it is refit once and looked at anew.
    const u32 still = StillNow();
    if (entry.still_moved && still != StillOn) {
        entry.dynamic = false;
        entry.still_moved = false;
        entry.still_has_ref = {};
        entry.still_doubt = false;
        entry.still_checks = 0;
        entry.still_next = frame;
        still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        ++still_stats.taken_back;
    }
    if (entry.palette != draw.palette) {
"""),
        (r"""        entry.dynamic = true;
    }
    const bool needs_data = !entry.built || entry.dynamic || entry.rebuilt ||
                            (need_scene && !entry.blas) ||
                            (entry.shadow && entry.world.buffer && !entry.copied &&
                             WorldCopies());
""",
         r"""        entry.dynamic = true;
        // bbport (r47_still-check): moving by its palette from now on, whatever the looks found
        // (nothing to take back, and not counted under their cap)
        if (entry.still_moved) {
            entry.still_moved = false;
            still_mover_triangles -= std::min<u64>(still_mover_triangles, entry.triangles);
        }
    }
    bool needs_data = !entry.built || entry.dynamic || entry.rebuilt ||
                      (need_scene && !entry.blas) ||
                      (entry.shadow && entry.world.buffer && !entry.copied && WorldCopies());
    // bbport (r47_still-check): a caster held for still (built, not moving, not a shared copy,
    // nothing else to capture it for) whose look is due is captured once more as a probe: its
    // vertices go to the positions like any capture's and RecordBuilds measures their bounds
    // (rt_still_sig.comp), but nothing is built or copied from them: the BLAS, the world copy
    // and the entry stay as they are, so the scene and the picture are those of a frame without
    // the look. A probe takes a capture param and room in the positions, never scratch or a
    // budget of builds; where its own budget (StillLane) or that room is used up it waits for
    // the next frame with its turn kept. Not while BB_RT_UPKEEP_FREEZE measures (r26).
    // still_refit: nothing is known of the capture its BLAS holds (it was built while the
    // experiment bit was set, as a shared copy before an instance's entry took it over, or its
    // signature was lost), so a look would have nothing to compare with. With BB_RT_STILL=on it
    // is refit once instead, as a moving caster is at every draw: the BLAS then holds the pose
    // of this frame and that capture's bounds are its reference. (With count it stays a probe,
    // whose bounds become the reference: no structure changes.)
    // Two kinds of capture are never measured, neither for a look nor for a reference: a mesh
    // of more indices than one dispatch of rt_still_sig.comp takes (still_fits), and a draw that
    // starts at another instance than the entry was made with (Param tells the vertex shader to
    // store the entry's instances: such a draw stores nothing, its range of the positions would
    // hold an earlier frame's and read as a move).
    bool still_refit = false;
    const bool still_fits = u64(entry.triangles) * 3 <= StillSigIndicesMost;
    const bool still_stored = draw.first_instance == entry.first_instance;
    if (still != StillOff && still_fits && !needs_data && need_scene && entry.still_wait == 0 &&
        !entry.still_blind && frame >= entry.still_next && r26_freeze == 0) {
        // The lane: the first look after a build, the other early looks, the looks in turn.
        const u32 lane =
            entry.still_checks == 0 ? 0u : entry.still_checks < StillEarlyChecks ? 1u : 2u;
        u32& used = still_used[lane];
        const u64 stored = u64(entry.vertices) * entry.instances;
        // What the looks in turn would need on this frame, looked at or not (StillCrowd).
        still_due += lane == 2 ? entry.triangles : 0;
        Build probe{&entry, positions_used, true, to_world};
        probe.probe = true;
        if (used >= StillLane(lane < 2)) {
            ++still_stats.waited;
        } else if (!still_stored) {
            ++still_stats.other_draw;
        } else if (still_sig_used >= StillSigsPerFrame || params_used >= MaxParams ||
                   positions_used + stored > MaxPositions ||
                   !StillWorld(draw.constants, probe)) {
            ++still_stats.no_room;
        } else if (still == StillOn && !entry.still_has_ref[0] && !entry.still_has_ref[1]) {
            used += entry.triangles;
            still_refit = true;
            needs_data = true;
        } else {
            used += entry.triangles;
            still_stats.longest_wait =
                std::max(still_stats.longest_wait, frame - entry.still_next);
            probe.param = Param(positions_used, entry);
            probe.sig = TakeStillSig(entry);
            probe.still_camera = draw.camera_pass;
            builds.push_back(probe);
            positions_used += u32(stored);
            const bool nearby =
                entry.palette != 0 || entry.still_camera_frame + StillNearFrames >= frame;
            entry.still_checks += entry.still_checks != 0xff ? 1 : 0;
            entry.still_next =
                frame + StillNext(entry.still_checks, entry.base, nearby,
                                  StillCrowd(still_due_last, StillLane(false)));
            ++still_stats.probes[lane];
            still_stats.probe_triangles += entry.triangles;
            entry.seen_frame = frame;
            frame_entries.push_back(&entry);
            return probe.param;
        }
    }
"""),
        (r"""    if (needs_data) {
        const bool update = need_scene && entry.blas && entry.built && !entry.rebuilt &&
                            frame - entry.built_frame < entry.rebuild_every &&
""",
         r"""    if (needs_data) {
        // bbport (r47_still-check): still_refit: a refit whatever the age of the build
        const bool update = need_scene && entry.blas && entry.built && !entry.rebuilt &&
                            (still_refit || frame - entry.built_frame < entry.rebuild_every) &&
"""),
        (r"""        builds.push_back({&entry, positions_used, update, to_world});
""",
         r"""        builds.push_back({&entry, positions_used, update, to_world});
        builds.back().param = param; // bbport (r47_still-check): see CaptureLeftOut
"""),
        (r"""        builds.back().inputs = draw.inputs;
""",
         r"""        builds.back().inputs = draw.inputs;
        // bbport (r47_still-check): the BLAS of a caster held for still is built from this
        // capture: its bounds are what the looks compare with (they arrive with the signature;
        // those of the capture before no longer hold), and its looks start again. Where the
        // capture cannot be measured (still_fits, still_stored above) nothing is known of it.
        if (still != StillOff && need_scene && !entry.dynamic && !entry.rebuilt) {
            if (still_fits && still_stored && StillWorld(draw.constants, builds.back())) {
                builds.back().sig = TakeStillSig(entry);
                builds.back().still_camera = draw.camera_pass;
                builds.back().still_first = true;
            }
            entry.still_has_ref = {};
            entry.still_blind = false;
            entry.still_doubt = false;
            entry.still_checks = 0;
            still_stats.refits += still_refit ? 1 : 0;
            entry.still_next = frame + StillNext(0, entry.base, true);
        }
"""),
        (r"""    const bool world_copies = WorldCopies();
    if (need_scene) {
""",
         r"""    const bool world_copies = WorldCopies();
    // bbport (r47_still-check): a probe builds nothing; a call that holds probes alone leaves
    // the scene as it is (no build to wait for, the instance records as written).
    const bool built_any = std::ranges::any_of(
        builds, [](const Build& b) { return !b.probe && !b.left_out; });
    if (need_scene && built_any) {
"""),
        (r"""        std::vector<std::pair<vk::Buffer, vk::BufferCopy>> copies;
""",
         r"""        std::vector<std::pair<vk::Buffer, vk::BufferCopy>> copies;
        // bbport (r47_still-check): the captures whose bounds are measured, and their
        // signatures' bytes in still_sigs (source) and in the frame's part of still_readback
        std::vector<StillPush> still;
        vk::BufferCopy still_copy;
"""),
        (r"""    const auto align = [&](u64 v) { return (v + scratch_align - 1) / scratch_align * scratch_align; };
    for (const Build& build : builds) {
        Entry& e = *build.entry;
""",
         r"""    const auto align = [&](u64 v) { return (v + scratch_align - 1) / scratch_align * scratch_align; };
    const u32 still_slot = u32(frame % 4);
    u32 sig_first = UINT32_MAX, sig_last = 0;
    for (const Build& build : builds) {
        Entry& e = *build.entry;
        // bbport (r47_still-check): the draw of this capture was left out (CaptureLeftOut): its
        // range of the positions was not written. Nothing is measured, built or copied from it;
        // like a build that was never recorded (OnFrameEnd), the entry is built at its next
        // draw.
        if (build.left_out) {
            if (!build.probe) {
                e.built = e.built && build.update;
                e.r17_inputs = 0;
            }
            continue;
        }
        // bbport (r47_still-check): the bounds of this capture are measured over the vertices
        // its triangles use, as it was stored (clip space, before the pass below brings it to
        // world space); the host reads them at a frame's end (ReadStillSigs). A probe is done
        // with that: its positions are read by nothing else.
        if (build.sig != 0) {
            job->still.push_back({build.still_rows, build.still_origin, build.store,
                                  e.indices.address, e.triangles * 3, build.sig - 1});
            still_pending[still_slot].push_back(
                {&e, frame, build.sig, build.still_camera, build.still_first});
            sig_first = std::min(sig_first, build.sig);
            sig_last = std::max(sig_last, build.sig);
        }
        if (build.probe) {
            continue;
        }
"""),
        (r"""    // pass recorded before it (with the ray traced sun: the game's shadow blur, ps 11ffdfb5).
""",
         r"""    // pass recorded before it (with the ray traced sun: the game's shadow blur, ps 11ffdfb5).
    // bbport (r47_still-check): this call's signatures (taken one after the other, so one run
    // of slots) and the tick the host waits for before it reads them
    if (!job->still.empty()) {
        const vk::DeviceSize sig_bytes = StillSigWords * 4;
        job->still_copy = vk::BufferCopy{
            (sig_first - 1) * sig_bytes,
            (vk::DeviceSize(still_slot) * StillSigsPerFrame + sig_first - 1) * sig_bytes,
            (sig_last - sig_first + 1) * sig_bytes};
        still_ticks[still_slot] = scheduler.CurrentTick();
    }
"""),
        (r"""        [job, positions = positions.buffer, unproject_pipeline = *unproject_pipeline,
         unproject_layout = *unproject_layout](vk::CommandBuffer cmdbuf) {
""",
         r"""        [job, positions = positions.buffer, unproject_pipeline = *unproject_pipeline,
         unproject_layout = *unproject_layout, still_sigs = still_sigs.buffer,
         still_readback = still_readback.buffer, still_pipeline = *still_pipeline,
         still_layout = *still_layout](vk::CommandBuffer cmdbuf) {
"""),
        (r"""            const vk::DescriptorBufferInfo position_info{positions, 0, VK_WHOLE_SIZE};
""",
         r"""            const vk::DescriptorBufferInfo position_info{positions, 0, VK_WHOLE_SIZE};
            // bbport (r47_still-check): the signatures: their slots zeroed, the bounds of each
            // capture gathered from its vertices as they were stored (before the pass below
            // overwrites them with their world space places), and the slots copied to where the
            // host reads them. Nothing here writes the positions.
            if (!job->still.empty()) {
                constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
                cmdbuf.fillBuffer(still_sigs, job->still_copy.srcOffset, job->still_copy.size, 0);
                EffectPass::MemoryBarrier(cmdbuf, Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
                const vk::DescriptorBufferInfo sig_info{still_sigs, 0, VK_WHOLE_SIZE};
                const std::array<vk::WriteDescriptorSet, 2> still_writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &position_info},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer,
                     .pBufferInfo = &sig_info},
                }};
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, still_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, still_layout, 0,
                                            still_writes);
                for (const StillPush& push : job->still) {
                    cmdbuf.pushConstants(still_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(push), &push);
                    cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
                }
                // The slots are written (for the copy), and the positions were read: the pass
                // below writes them only after these dispatches.
                EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          Compute | Transfer,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite |
                                              vk::AccessFlagBits2::eTransferRead);
                cmdbuf.copyBuffer(still_sigs, still_readback, job->still_copy);
                // The host reads the copy after the submission's tick; the next call's fill
                // comes after this copy.
                EffectPass::MemoryBarrier(cmdbuf, Transfer,
                                          vk::AccessFlagBits2::eTransferRead |
                                              vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost | Transfer,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eTransferWrite);
            }
"""),
        (r"""        });
    tlas_count = 0;
""",
         r"""        });
    if (built_any) { // bbport (r47_still-check): probes alone change nothing the scene holds
        tlas_count = 0;
    }
"""),
        (r"""    card_stats = {}; // bbport (r46_lamp-cards): of the records written now
""",
         r"""    card_stats = {}; // bbport (r46_lamp-cards): of the records written now
    const u32 lamp_leave = LampLeave(); // bbport (r47_still-check)
    still_leave_count = 0;
"""),
        (r"""        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card || stale ? 0 : LampMask)),
""",
         r"""        const bool stale = lamp_repair && entry->lamp_out && entry->rebuilt && entry->dynamic;
        // bbport (r47_still-check): BB_RT_LAMP_LEAVE (a diagnostic, off unless set): lamp rays
        // leave out the instances of the classes it names
        const bool leave =
            lamp_leave != 0 &&
            (lamp_leave &
             StillLeaveClasses((mask & CameraMask) != 0, kept, entry->rebuilt, entry->instance,
                               entry->dynamic,
                               LampCard(false, LampCardLevelDefault, entry->shadow_card,
                                        entry->dynamic, entry->card_shadow, cutout,
                                        entry->skinned))) != 0;
        // Counted where the knob alone withholds the lamp bit (not a card or a starved copy
        // that is left out anyway).
        still_leave_count += leave && !card && !stale ? 1 : 0;
        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card || stale || leave ? 0 : LampMask)),
"""),
        (r"""}

void RtShadow::OnFrameEnd() {
""",
         r"""}

// bbport (r47_still-check): what is done about the casters held for still right now. The
// experiment bit is read at each use, so old and new can be compared in one run.
u32 RtShadow::StillNow() const {
    return still_ready && !BbToggle::Experiment(StillCheckOldBit) ? StillMode() : u32(StillOff);
}

// bbport (r47_still-check): a signature of this frame for a capture of `entry` (1 to
// StillSigsPerFrame), or 0 when the frame's are used up. Until it is read or dropped the entry
// counts it (Entry::still_wait).
u32 RtShadow::TakeStillSig(Entry& entry) {
    if (still_sig_used >= StillSigsPerFrame) {
        return 0;
    }
    ++entry.still_wait;
    return ++still_sig_used;
}

// bbport (r47_still-check): for the signature of a capture drawn with `constants` (the
// projection at word 52, view to world at word 180, as ToWorld reads them): what takes its clip
// space positions to world space in rt_still_sig.comp (StillClipToWorld). False without an
// inverse of the projection.
bool RtShadow::StillWorld(const float* constants, Build& build) const {
    bool ok = false;
    const auto inverse = Invert(constants + 52, ok);
    if (!ok) {
        return false;
    }
    StillClipToWorld(inverse.data(), constants + 180, build.still_rows, build.still_origin);
    const auto finite = [](float v) { return std::isfinite(v); };
    return std::ranges::all_of(build.still_rows, finite) &&
           std::ranges::all_of(build.still_origin, finite);
}

// bbport (r47_still-check): the rasterizer left out the draw PrepareDraw last set a capture up
// for (its pipeline is still compiling: vk_rasterizer.cpp, SkipUncompiledDraw). No vertex shader
// ran, so nothing stored the draw's positions: their range holds what an earlier frame left
// there. A look would read that as a move, a reference taken from it would make every later
// look one, and a BLAS built from it holds no caster. So the capture's signature is given back;
// a probe is dropped and its look taken again at the caster's next draw; and with BB_RT_STILL=on
// the build is dropped too (RecordBuilds), so the entry is built from its next draw that runs.
// With count the build stays as it always was, only unmeasured. Nothing with the experiment bit
// set. `motion_param`, `mode`: the draw's push constant and its pipeline's motion mode, as
// EffectsCaptureDraw left them.
void RtShadow::CaptureLeftOut(u32 motion_param, u32 mode) {
    const u32 param =
        mode == Shader::MotionVectors::VertexBoth ? motion_param >> 16 : motion_param;
    const u32 still = StillNow();
    if (param == 0 || still == StillOff || builds.empty() || builds.back().param != param) {
        return;
    }
    Build& build = builds.back();
    Entry& entry = *build.entry;
    if (build.sig != 0) {
        build.sig = 0;
        entry.still_wait -= entry.still_wait != 0 ? 1 : 0;
    }
    ++still_stats.left_out;
    if (build.probe) {
        entry.still_checks -= entry.still_checks != 0 && entry.still_checks != 0xff ? 1 : 0;
        entry.still_next = frame;
        build.left_out = true;
    } else if (still == StillOn) {
        build.left_out = true;
    }
}

// bbport (r47_still-check): an entry that is new under the key `id`: when a look found the
// caster of that key moving before (still_movers) it counts as moving from the start, within
// the cap. (A shared copy's key is never in the list: copies are rebuilt in turn, not looked at.)
void RtShadow::StillAdmit(Entry& entry, u64 id) {
    if (StillNow() != StillOn || entry.dynamic || !still_movers.contains(id) ||
        still_mover_triangles + entry.triangles > StillMoverCap()) {
        return;
    }
    entry.dynamic = true;
    entry.still_moved = true;
    still_mover_triangles += entry.triangles;
    ++still_stats.known;
}

// bbport (r47_still-check): the signatures of one frame of the ring, once the GPU has written
// them. A capture the BLAS was built from gives the reference: the caster's bounds in that
// pose. A look's bounds are compared with it: past the tolerance the caster has moved since its
// BLAS was built, and (BB_RT_STILL=on, on the second look in a row that finds so, within the
// cap) counts as moving from now on, like a skinned one: PrepareDraw refits it at every draw.
// The two passes may place one mesh a little
// differently (a sun shadow pass's vertex shader may add a bias), so each pass has its own
// reference; a look by the pass that has none yet is compared with the other pass's under the
// wide tolerance (a caster built in a passing pose is off by far more) and, within it, becomes
// that pass's reference.
void RtShadow::ReadStillSigs(u32 slot) {
    const auto* words = static_cast<const u32*>(still_readback.mapped) +
                        std::size_t(slot) * StillSigsPerFrame * StillSigWords;
    const u32 still = StillNow();
    for (const StillPending& item : still_pending[slot]) {
        Entry& entry = *item.entry;
        entry.still_wait -= entry.still_wait != 0 ? 1 : 0;
        std::array<u32, StillSigWords> sig;
        std::memcpy(sig.data(), words + std::size_t(item.sig - 1) * StillSigWords, sizeof(sig));
        StillBox box;
        if (!DecodeStillSig(sig.data(), box)) {
            // A mesh with a vertex that is not a number: its bounds cannot be compared, so it
            // is not looked at again until its BLAS is built anew.
            entry.still_blind = true;
            ++still_stats.unread;
            continue;
        }
        const u32 pass = item.camera ? 0u : 1u;
        if (item.first) {
            entry.still_has_ref = {};
            entry.still_ref[pass] = box;
            entry.still_has_ref[pass] = true;
            entry.still_ref_frame = item.frame;
            ++still_stats.firsts;
            continue;
        }
        const bool cross = !entry.still_has_ref[pass];
        if (cross && !entry.still_has_ref[pass ^ 1u]) {
            // No reference at all (BB_RT_STILL=count, and built before the looks began or its
            // signature lost): this look is the first that can be compared with.
            entry.still_ref[pass] = box;
            entry.still_has_ref[pass] = true;
            entry.still_ref_frame = item.frame;
            continue;
        }
        const StillBox& then = entry.still_ref[cross ? pass ^ 1u : pass];
        const float moved = StillMoved(then, box);
        const float limit = cross ? std::max(StillLimit(), StillCrossTolerance) : StillLimit();
        if (!(moved > limit)) {
            entry.still_doubt = false;
            if (cross) {
                entry.still_ref[pass] = box;
                entry.still_has_ref[pass] = true;
            }
            continue;
        }
        ++still_stats.found;
        still_stats.found_new += entry.still_seen ? 0 : 1;
        still_stats.found_instance += entry.instance ? 1 : 0;
        still_stats.found_camera += item.camera ? 1 : 0;
        still_stats.found_cross += cross ? 1 : 0;
        entry.still_seen = true;
        const u64 id = entry.instance ? InstanceKey(entry.base, entry.palette) : entry.base;
        bool taken = false;
        if (still == StillOn && !entry.dynamic) {
            if (!entry.still_doubt) {
                // One look decides nothing that lasts for the life of the entry: one capture
                // that went wrong must not make a wall a moving caster. A second look is asked
                // for at once, and a caster is taken when that one finds it moved as well.
                entry.still_doubt = true;
                entry.still_next = frame;
                ++still_stats.doubted;
            } else if (still_mover_triangles + entry.triangles > StillMoverCap()) {
                ++still_stats.not_taken;
            } else {
                entry.still_doubt = false;
                entry.dynamic = true;
                entry.still_moved = true;
                still_mover_triangles += entry.triangles;
                if (still_movers.size() >= 65536) {
                    still_movers.clear();
                }
                still_movers.insert(id);
                ++still_stats.taken;
                taken = true;
            }
        }
        // For the line: the four that moved farthest, each caster once.
        const StillFound found{id, entry.base, entry.mesh, item.frame - entry.still_ref_frame,
                               entry.triangles, entry.still_checks, moved, then, box,
                               entry.instance, item.camera, cross, taken};
        // Its place: the one it has, else the first empty one, else the smallest move's.
        StillFound* place = nullptr;
        for (StillFound& kept : still_stats.largest) {
            if (kept.triangles != 0 && kept.id == id) {
                place = &kept;
                break;
            }
            if (!place || (place->triangles != 0 &&
                           (kept.triangles == 0 || kept.moved < place->moved))) {
                place = &kept;
            }
        }
        if (place->triangles != 0 && place->id == id) {
            const bool was_taken = place->taken;
            if (moved > place->moved) {
                *place = found;
            }
            place->taken = was_taken || taken;
        } else if (place->triangles == 0 || moved > place->moved) {
            *place = found;
        }
    }
    still_pending[slot].clear();
    still_ticks[slot] = 0;
}

void RtShadow::OnFrameEnd() {
"""),
        (r"""    stats.incomplete += !frame_entries.empty() && missed * 4 > u32(frame_entries.size()) ? 1 : 0;
    for (const Build& build : builds) {
""",
         r"""    stats.incomplete += !frame_entries.empty() && missed * 4 > u32(frame_entries.size()) ? 1 : 0;
    for (const Build& build : builds) {
        // bbport (r47_still-check): its signature was never recorded; a probe left the entry
        // and its BLAS as they were
        if (build.sig != 0) {
            build.entry->still_wait -= build.entry->still_wait != 0 ? 1 : 0;
        }
        if (build.probe) {
            continue;
        }
"""),
        (r"""        card_lookups = 0;
""",
         r"""        card_lookups = 0;
        // bbport (r47_still-check): the looks at the casters held for still since the last
        // line, and the casters that moved farthest between the capture their BLAS was built
        // from and a look: a caster built in a passing pose shows as one moved far at look 1,
        // two frames after that capture, with its bounds then and now.
        {
            const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
            static constexpr const char* still_modes[] = {"off", "count", "on"};
            const StillStats& s = still_stats;
            std::printf("Ray tracing still check (r47): BB_RT_STILL=%s (experiment "
                        "4611686018427387904 %s%s); a frame %.1f casters held for still captured "
                        "again (%.0f triangles; %.1f first looks after a build, %.1f other early "
                        "looks, %.1f in turn; budgets %u, %u and %u triangles), %.1f waited for "
                        "a budget (the longest wait of a look %llu frames; the casters due in "
                        "turn on the last frame need %u frames at the budget), %.2f found no "
                        "room, %.2f were drawn from another first instance; since the last line "
                        "%llu captures left out with their draw, %llu refit once because "
                        "nothing was known of the capture their BLAS held, %llu builds measured, "
                        "%llu signatures not usable, %llu looks found "
                        "a caster moving (%llu for the first time, %llu instance entries, %llu in "
                        "the camera pass, %llu against the other pass's capture), %llu of them "
                        "asked for a second look, %llu taken as moving from now on (found so "
                        "twice in a row), %llu not taken past the cap of %u triangles (%llu "
                        "held by living casters), %llu known from before and taken at their "
                        "first draw, %llu held for still again; %zu casters known to move; "
                        "tolerance %.4f m (%.2f m between the passes); lamp bit withheld by class "
                        "alone (BB_RT_LAMP_LEAVE=%u): %u instances on the last scene%s",
                        still_modes[StillMode()],
                        BbToggle::Experiment(StillCheckOldBit) ? "set" : "clear",
                        still_ready || StillMode() == StillOff ? "" : ", not ready",
                        double(s.probes[0] + s.probes[1] + s.probes[2]) / f,
                        double(s.probe_triangles) / f, double(s.probes[0]) / f,
                        double(s.probes[1]) / f, double(s.probes[2]) / f, StillLane(true),
                        StillLane(true), StillLane(false), double(s.waited) / f,
                        u(s.longest_wait), StillCrowd(still_due_last, StillLane(false)),
                        double(s.no_room) / f, double(s.other_draw) / f, u(s.left_out),
                        u(s.refits), u(s.firsts), u(s.unread), u(s.found), u(s.found_new),
                        u(s.found_instance), u(s.found_camera), u(s.found_cross), u(s.doubted),
                        u(s.taken), u(s.not_taken), StillMoverCap(), u(still_mover_triangles),
                        u(s.known), u(s.taken_back), still_movers.size(), double(StillLimit()),
                        double(std::max(StillLimit(), StillCrossTolerance)), LampLeave(),
                        still_leave_count, s.largest[0].triangles != 0 ? "; moved farthest:" : "");
            std::array<StillFound, 4> largest = s.largest;
            std::ranges::sort(largest, [](const StillFound& a, const StillFound& b) {
                return a.moved > b.moved;
            });
            for (const StillFound& m : largest) {
                if (m.triangles == 0) {
                    break;
                }
                std::printf(" mesh %016llx (key %016llx), %u triangles, moved %.3f m at look %u, "
                            "%llu frames after the capture its BLAS was built from, box then "
                            "(%.3f %.3f %.3f)-(%.3f %.3f %.3f), now (%.3f %.3f %.3f)-(%.3f %.3f "
                            "%.3f), %s, by %s%s%s;",
                            u(m.mesh), u(m.key), m.triangles, double(m.moved), m.checks,
                            u(m.after), double(m.then[0]), double(m.then[1]), double(m.then[2]),
                            double(m.then[3]), double(m.then[4]), double(m.then[5]),
                            double(m.now[0]), double(m.now[1]), double(m.now[2]),
                            double(m.now[3]), double(m.now[4]), double(m.now[5]),
                            m.instance ? "an instance's own entry" : "known by draw order",
                            m.camera ? "a camera pass draw" : "a sun shadow pass draw",
                            m.cross ? " against the other pass's capture" : "",
                            m.taken ? ", taken as moving" : "");
            }
            std::printf("\n");
            still_stats = {};
        }
"""),
        (r"""        slot_ticks[slot] = 0;
    }
""",
         r"""        slot_ticks[slot] = 0;
    }
    // bbport (r47_still-check): the signatures the GPU is done with are read, the oldest frame's
    // first: those of the ring slot the coming frame writes again (recorded four frames ago:
    // waited for like the capture params just above, which the GPU has long passed), and those
    // of the frames since whose tick the GPU has passed. No wait for these: the driver is asked
    // once how far the GPU is (the tick the scheduler knows is only as new as the last wait
    // anywhere), and only on a frame that has signatures to read; that answer serves the other
    // slots. An entry is not looked at again before its signature is read, so a late read
    // would put its first look off.
    bool asked = false;
    for (u32 age = 0; age < 4; ++age) {
        const u32 s = (slot + age) % 4;
        if (still_ticks[s] == 0) {
            continue;
        }
        if (age == 0) {
            scheduler.Wait(still_ticks[s]);
        } else {
            const bool passed = asked ? scheduler.GetWorkSemaphore()->IsFree(still_ticks[s])
                                      : scheduler.IsFree(still_ticks[s]);
            asked = true;
            if (!passed) {
                break;
            }
        }
        ReadStillSigs(s);
    }
    still_sig_used = 0;
    still_used = {};
    still_due_last = still_due;
    still_due = 0;
"""),
    ],
}


def fix(s, nl):
    return s.replace("\r\n", "\n").replace("\n", nl)


def text_check(texts):
    """What the patch relies on in the patched text: the experiment bit is the one the task gave,
    declared once, read in one place (StillNow) and named in the line, and is not one of the
    master switch's; every look, signature, admission and left-out capture asks StillNow, and
    only BB_RT_STILL=on takes a caster as moving (at the second look in a row), refits one or
    drops a build; the signatures are measured before the positions go to world space, and a
    probe or a left-out capture builds nothing; the shader, the engine and the header agree on a
    signature's layout and the push constants; the rasterizer tells of a draw it leaves out;
    Destroy takes an entry out of the pending lists; the lamp bit's line is r46's with the
    diagnostic added; the 600-frame line is there once; the C texts kept their line breaks; the
    shader, the header and the tests are registered."""
    ok = True
    scene = texts[R + "vk_rt_shadow.cpp"]
    raster = texts[R + "vk_rasterizer.cpp"]
    head = texts[R + "vk_rt_shadow.h"]
    cmake = texts[G + "CMakeLists.txt"]
    settings = texts[S + "bbport_settings.h"]
    lab = texts[TESTS + "test_rt_shadows.cpp"]
    still = NEW_FILES[R + "rt_still_check.h"]
    shader = NEW_FILES[H + "rt_still_sig.comp"]
    test = NEW_FILES[TESTS + "test_rt_still_check.cpp"]
    nl = "\r\n" if "\r\n" in scene else "\n"
    if VALUE != 4611686018427387904 or head.count("inline constexpr u64 StillCheckOldBit = %dull;" % VALUE) != 1 or \
            scene.count("BbToggle::Experiment(StillCheckOldBit)") != 2 or scene.count(str(VALUE)) != 1 or \
            scene.count("    return still_ready && !BbToggle::Experiment(StillCheckOldBit) ? StillMode() : u32(StillOff);") != 1:
        print("experiment %d is not declared once in vk_rt_shadow.h, read by StillNow and named in the line" % VALUE)
        ok = False
    bits = re.search(r"PreviousPathsBits\[\] = \{([^}]*)\}", settings)
    if not bits or BIT in [int(x) for x in re.findall(r"\d+", bits.group(1))]:
        print("bit %d is in PreviousPathsBits (or the list was not found)" % BIT)
        ok = False
    # With the bit set (StillNow() == StillOff) nothing of the patch runs at a draw: the probe,
    # the build's signature and the admission each ask it; taking and the one refit need StillOn.
    if scene.count("    const u32 still = StillNow();") != 3 or \
            scene.count("    if (still != StillOff && still_fits && !needs_data && need_scene && entry.still_wait == 0 &&") != 1 or \
            scene.count("        if (still != StillOff && need_scene && !entry.dynamic && !entry.rebuilt) {") != 1 or \
            scene.count("    if (StillNow() != StillOn || entry.dynamic || !still_movers.contains(id) ||") != 1 or \
            scene.count("    if (param == 0 || still == StillOff || builds.empty() || builds.back().param != param) {") != 1 or \
            scene.count("    } else if (still == StillOn) {" + nl + "        build.left_out = true;") != 1 or \
            scene.count("left_out = true;") != 2 or \
            scene.count("        } else if (still == StillOn && !entry.still_has_ref[0] && !entry.still_has_ref[1]) {") != 1 or \
            scene.count("entry.dynamic = true;") != 3 or scene.count("TakeStillSig(entry);") != 2:
        print("a look, a signature, an admission or a left-out capture does not ask StillNow, or BB_RT_STILL=on is not asked for where the scene changes")
        ok = False
    # A caster is taken as moving only with BB_RT_STILL=on, at the second look in a row.
    taking = scene.index("        if (still == StillOn && !entry.dynamic) {" + nl + "            if (!entry.still_doubt) {")
    if scene.count("        if (still == StillOn && !entry.dynamic) {") != 1 or \
            not taking < scene.index("                entry.still_doubt = true;") < \
            scene.index("                entry.still_moved = true;") or scene.count("entry.still_moved = true;") != 2:
        print("a caster is taken as moving without BB_RT_STILL=on or at one look alone")
        ok = False
    # RecordBuilds: a left-out capture is left first, a probe once it is measured and before
    # anything is unprojected or marked built; the signatures are measured before the positions
    # go to world space.
    measured = scene.index("        if (build.sig != 0) {" + nl + "            job->still.push_back({build.still_rows, build.still_origin, build.store,")
    if not scene.index("        if (build.left_out) {") < measured < \
            scene.index("        if (build.probe) {" + nl + "            continue;" + nl + "        }" + nl +
                        "        job->unproject.push_back({build.to_world, build.store, e.vertices * e.instances});" + nl +
                        "        e.built = true;") or scene.count("        if (build.left_out) {") != 1 or \
            scene.count("job->unproject.push_back(") != 1 or \
            not scene.index("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, still_pipeline);") < \
            scene.index("cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);"):
        print("RecordBuilds does not leave a probe or a left-out capture before anything is built, or measures after the unproject pass")
        ok = False
    if "inline constexpr std::uint32_t StillSigWords = 8;" not in still or "    const uint at = slot * 8u;" not in shader or \
            scene.count("static_assert(sizeof(StillPush) == 80 && offsetof(StillPush, first) == 60 &&" + nl +
                        "              offsetof(StillPush, indices) == 64 && offsetof(StillPush, slot) == 76);") != 1 or \
            ("    vec3 origin;     // that camera's place in the world" + "\n" +
             "    uint first;      // the mesh's first vertex in `positions`" + "\n" +
             "    Indices indices; // its triangle list, relative to `first`" + "\n") not in shader or \
            "    const vec3 p = vec3(dot(row0, clip), dot(row1, clip), dot(row2, clip)) + origin;" not in shader or \
            "inline constexpr std::uint32_t StillSigIndicesMost = 65535u * 64u;" not in still or \
            scene.count("    const bool still_fits = u64(entry.triangles) * 3 <= StillSigIndicesMost;") != 1 or \
            scene.count("{eStorageBuffer, eStorageBuffer}, sizeof(StillPush),") != 1 or \
            scene.count("vk::PhysicalDeviceSubgroupProperties") != 2 or \
            "static_assert(sizeof(Unproject) == 56 && sizeof(Sign) == 80);" not in lab:
        print("the shader, vk_rt_shadow.cpp and rt_still_check.h do not agree on a signature or the push constants")
        ok = False
    # The rasterizer's one call, in the branch that leaves a draw out.
    call = "        if (SkipUncompiledDraw(pipeline)) {" + nl
    if raster.count("rt_shadow->CaptureLeftOut(") != 1 or raster.count(call) != 1 or \
            not 0 < raster.index("rt_shadow->CaptureLeftOut(dc.push_data.motion_param,") - raster.index(call) < 400 or \
            head.count("    void CaptureLeftOut(u32 motion_param, u32 mode);") != 1:
        print("vk_rasterizer.cpp does not tell RtShadow of the draw it leaves out")
        ok = False
    if scene.count("std::erase_if(list, [&](const StillPending& item) { return item.entry == &entry; });") != 1 or \
            scene.count("    Free(still_sigs); // bbport (r47_still-check)") != 1:
        print("Destroy does not take an entry out of the pending lists, or the buffers are not freed")
        ok = False
    if scene.count(".mask = u8(mask | (card || stale || leave ? 0 : LampMask)),") != 1 or \
            scene.count("LampMask)),") != 1 or scene.count("const bool card = LampCard(cards_old, card_level,") != 1:
        print("the lamp bit's line is not r46's with BB_RT_LAMP_LEAVE added")
        ok = False
    if scene.count('std::printf("Ray tracing still check (r47): BB_RT_STILL=%s') != 1 or \
            'std::printf("' + chr(92) + 'n");' + nl + '            still_stats = {};' not in scene or \
            scene.count('std::printf("Ray tracing still check (r47): off - %s' + chr(92) + 'n",') != 1 or \
            'then every %u to %u)' + chr(92) + 'n",' not in test or \
            'between the passes)' + chr(92) + 'n",' not in lab:
        print("the 600-frame line is not there once, or a C escape lost its backslash on the way into the script")
        ok = False
    if cmake.count("add_host_shader(rt_still_sig.comp rt_still_sig_comp)") != 1 or \
            cmake.count("add_executable(rt-still-check-test EXCLUDE_FROM_ALL ../tests/test_rt_still_check.cpp)") != 1 or \
            scene.count('#include "video_core/host_shaders/rt_still_sig_comp.h"') != 1 or \
            head.count('#include "video_core/renderer_vulkan/rt_still_check.h"') != 1 or \
            '#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"' not in test or \
            lab.count('#include "gpu/shadps4/video_core/renderer_vulkan/rt_still_check.h"') != 1 or \
            lab.count('std::strcmp(argv[1], "--still") == 0') != 1:
        print("the shader, the new header or a test is not registered")
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


def below():
    """Whether r46_lamp-cards, which this round goes on top of, is in the tree."""
    try:
        head = open(R + "vk_rt_shadow.h", encoding="utf-8", newline="").read()
    except OSError:
        return False
    return "inline constexpr u64 LampCardsOldBit = " in head


def main(mode):
    if mode not in ("check", "apply", "revert"):
        print("usage: r47_still-check.py check|apply|revert   (the tree: R47_ROOT, else the current "
              "directory if it is a source tree's root, else <tree>/)")
        return 2
    out = run(mode, quiet=(mode == "check"))
    if out is None:
        if mode == "check":
            if run("revert", quiet=True) is not None:
                print("already applied (revert would restore the tree)")
            else:
                run("check")  # says which anchor
        if mode != "revert" and not below():
            print("r46_lamp-cards is not applied in %s: r47_still-check goes on top of it" % ROOT)
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
