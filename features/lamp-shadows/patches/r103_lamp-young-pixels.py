# r103_lamp-young-pixels: FEATURE patch (lamp work; the owner's top complaint, 2026-11-15 19:55: "I see
# that the blocky edges of moving shadows still is there make the shadows not look smooth in motion").
# Off by default behind BB_LAMP_SHADOW_YOUNG=1 (environment, read once).
#
# Fault (mechanism 1 of the 2026-11-15 moving-edge study; a 4K capture confirmed ragged, hatched moving
# edges at half AND at full size): where the guards against trails (the reject, the window clamp, the
# trail cap, the unsure cut) give a pixel's history up at a moving shadow's edge, its ratio is
# mix(answer, held, frames / (frames + 1)) with frames near 0: this frame's bare ray, 0 or 1, for a
# frame or two. r93 (BB_LAMP_SHADOW_SPATIAL) misses this case where the area was settled (all lit or
# all dark): its share u is 0 there.
#
# What (point_shadow_ray.comp, only inside #ifdef CENTRED: the plain, half, cards and half cards builds
# compile to the same SPIR-V words; the centred, half centred, resolve and half resolve builds change):
#  - In the centred window's resolve, after every guard: young = 1 - smoothstep(0.5, 2.0, frames)
#    (frames = what the guards left; 1 at 0.5 frames or less, 0.74 at 1, 0 from 2 on). A young pixel
#    takes a mean of this frame's answers on its own surface by its young share: where a history was
#    found and the tile is at full pixels (full resolution, half-resolution second pass) the 5x5 mean
#    (youngMean: the pixel's answer and up to 24 neighbours within 2 px that have one and lie within
#    r93's plane tolerance, 1 cm + 0.5% of the distance); in the half-resolution first pass (taps 2 px
#    apart) r93's 3x3 (spatialMean; the same 2 px reach, so first-pass and fill pixels are blurred
#    alike); where no history was found r93's 3x3 (taps 1 px apart, 2 px in the half-resolution first
#    pass). A surface a moving camera uncovers (or every surface after a camera cut) is young on its
#    first two frames: the 3x3 on the first, 0.74 of the 5x5 on the second (frames 1), so its contact
#    shadows are spread by up to 2 px for those frames and sharpen again as the history fills.
#  - It goes in through r93's own blend: mean' = mix(r93's mean, young mean, young), share
#    u = max(r93's u, young). Without BB_LAMP_SHADOW_SPATIAL u = young and the mean is the young mean
#    alone: a pixel with 2 frames or more is left exactly as before, a pixel without history takes
#    r93's 3x3 as r93 would. With BB_LAMP_SHADOW_SPATIAL=1 a pixel without history is r93's, untouched.
#  - The rule runs only where the history may hold 2 frames or more (word 30 >= 2, i.e.
#    BB_LAMP_SHADOW_HISTORY >= 2/3; else every pixel would count as young and be blurred for good).
#  - BB_LAMP_SHADOW_YOUNG=2 (bit 28, a TEST SETTING): also, where the window clamp gives a history up,
#    it keeps the clamped value with taken x min(frames, 1) frames (at most 1) in place of none, as the
#    task asked. Not in 1, because the clamped value lies on the bound's edge toward the old shadow:
#    behind a shadow that left, a one-lamp window that agrees (mean 1) puts it at 1 - 0.072, so the
#    pixel shows 0.964 and fades as a plain mean (0.976, 0.982, ...); where a shadow arrives into a
#    window of mean 0.1 the clamped value is about 0.585 and the pixel shows about 0.34 instead of
#    0.1, fading over several frames: a trail. With 1 the clamp's cut pixel takes this frame's 5x5
#    mean (young 1), which carries nothing of the old shadow.
#  - Shared half-resolution pixels (HALF_TAKEN, which skip the blend): no code. A taken pixel's ratio is
#    the block's answer from half_answers, which the first pass's resolve stores AFTER this rule, so it
#    is the first-pass pixel's young mean when that pixel is young (not its bare ray); it copies that
#    pixel's frames and fast (its history age), so when the edge reaches it and it traces its own ray
#    it finds a young history and takes the 5x5 mean at 1 px. Filtered values agree within 1/64 only
#    where the area is really flat, so the chance agreement of bare 0/1 block answers (mechanism 2) is
#    rare too. With r101 (BB_LAMP_SHADOW_MOVING_EDGE=1) on as well: r101 tests the block's frames
#    (b > 1.5) and |fast - ratio| <= 0.125 with ratio now the filtered value.
#
# Guards (each still takes the RAW answer as before; only the sample blended into the history changes):
#  the reject (fast = mix(answer, held_fast, 0.6), raw), the window clamp's bound (25 raw answers and
#  the own-answer widening), the trail cap (trail / slip), the unsure cut, the soft follow's fit and
#  evidence (follow_cur written as before), the cast codes and the strongest lamp. `fast` is stored raw.
#  A cut pixel now shows this frame's same-surface mean, which carries nothing of the old shadow, so no
#  trail comes back; the spread is spatial (2 px), never temporal.
# Contact shadows of standing casters: under a standing lamp and camera their pixels hold the history's
#  limit (9 frames at 0.9), young is 0, nothing changes; under a moving camera the history is found by
#  reprojection and its frames kept (a contact's own answer equals its history, the clamp does not
#  fire), and a surface just uncovered is young for two frames (see above); under the walking torch the trail cap
#  is trail / slip with slip the swing of the blocker, near 0 at the contact, so the contact keeps its
#  frames; and the plane test leaves the caster's own pixels out of every mean.
#
# Host: NEW renderer_vulkan/lamp_young_pixels.h (parse, bits, the log lines, the counter). Hooks in
#  vk_point_shadow.cpp: one include, Ready's once-line (after r61's), Flush ORs the bits into word 0
#  (LampYoungBits: 0 unless the knob is set and BB_LAMP_SHADOW_WINDOW=2), the pass counter (after the
#  centred window's split is known; counted only where the history may hold 2 frames, as the shader's
#  rule), a line after the r42 lamp line, and a line in the r32 half-resolution block (half_counts
#  word 13, unused before). Word 0 bits 27 and 28: free (in use: 0, 1, 2-3 r101, 8-10 view, 12-17
#  r63, 20-22, 24 r91, 25 r92, 26 r93).
#
# Review 2026-11-15 (this .fixed.py; the draft r103_lamp-young-pixels.py is left as it was): rule and
#  hooks unchanged. Fixed: the shader comment, README row and script header said a surface just
#  uncovered is spread by one 1 px tap at most (false: 2 px apart in the half first pass, and its
#  second frame takes 0.74 of the 5x5); the pass counter now also needs LampHistoryFrames >= 2 (the
#  shader does nothing below it, the line said it ran); the half line says "a half-resolution pass"
#  (it divides by every half pass, resolved or not); the text check's #ifdef CENTRED test now ends a
#  CENTRED level at its #else.
#  ORDER: revert this patch BEFORE r93. r93's own revert does not see this patch and succeeds with it
#  in, leaving youngMean and the young block without spatial, spatial_u, spatialMean and
#  SPATIAL_PLANE_* (the shader no longer compiles; shown on a copy; this script's check then refuses).
#  Test block in test_lamp_shadow_tune.cpp; README row after BB_LAMP_SHADOW_SPATIAL's.
#
# Off (the default): the knob is 0 -> LampYoungBits is 0 -> word 0 as before -> t_young and t_young_keep
#  false -> the young branch (uniform) is skipped and young_keep is 0, so its branch is skipped: every
#  statement of before runs on the same values; no image, buffer, binding or dispatch is added; the host
#  adds one OR of 0, a call that adds 0 and two line calls that return at once.
#
# NEEDS r93 (r93_lamp-shadow-spatial.fixed.py) applied: four anchors are r93's lines (its blend, its
#  count reset, its test block's end, its README row) and the code uses r93's spatial, spatial_u and
#  spatialMean. r92 (r92_lamp-shadow-colour.fixed.py) may be applied before or after this patch: no
#  insert of this one lands between an r92 text and its anchor (r92 checks that they touch): r92
#  inserts before "held_ratio = fitted;", this one after "frames *= 1.0 - taken;", the line before;
#  r92 inserts before "track.ClearSteps();" and before the test's "lamp shadow tune: ok", this one
#  after r93's "line_spatial = 0;" and after r93's test block, which lie before those r92 texts.
#  (Proven on a copy in both orders.)
#
# Use: python -I -X utf8 r103_lamp-young-pixels.py check | apply | revert
# Root: R103_ROOT, else <tree>. Line ends kept (CRLF in the tree). apply backs the originals up in
# r103_backup next to this script; revert takes out exactly what apply inserted (each inserted text is
# found by itself, exactly once) and removes the new header.
import os, re, sys

ROOT = os.environ.get("R103_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r103_backup")
S = "engine/gpu/shadps4/video_core/host_shaders/point_shadow_ray.comp"
C = "engine/gpu/shadps4/video_core/renderer_vulkan/vk_point_shadow.cpp"
U = "engine/tests/test_lamp_shadow_tune.cpp"
R = "README.md"
NEW = "engine/gpu/shadps4/video_core/renderer_vulkan/lamp_young_pixels.h"

HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG, the lamp shadows' young pixels. Where the
// guards against trails (the reject, the window clamp, the trail cap, the unsure cut) give a pixel's
// history up at a moving shadow's edge, its ratio was this frame's bare ray, 0 or 1, for a frame or
// two: a ragged, hatched moving edge. 0 (the default): as before. 1: in the centred window's resolve
// (BB_LAMP_SHADOW_WINDOW=2, the default) a pixel the guards left fewer than 2 frames takes a mean of
// this frame's answers on its own surface by 1 - smoothstep(0.5, 2, frames) (point_shadow_ray.comp
// youngMean; word 0 bit 27). 2: 1, and where the window clamp gives a history up the pixel keeps the
// clamped value with up to one frame (bit 28; a test setting: that value lies at the edge of the
// clamp's bound toward the old shadow, so it can leave a faint trail). Read once, at the first call.
// No Vulkan here: tests/test_lamp_shadow_tune.cpp builds it.

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "lamp_shadow_tune.h"

namespace Vulkan {

/// Word 0 of the lamp pass's tuning words, read only by the CENTRED builds' resolve: bit 27 the young
/// pixels' mean, bit 28 the clamp's kept frame (the value 2). LampTuneWords leaves both clear;
/// PointShadow::Flush ORs them in after it (LampYoungBits).
inline constexpr std::uint32_t LampTuneYoung = 1u << 27, LampTuneYoungKeep = 1u << 28;
// Free: none of LampTuneWords' bits, the view's field or r63's card cap, nor r101's bits 2 and 3, r91's
// 24, r92's 25 or r93's 26 (LampTuneSpatial).
static_assert(((LampTuneYoung | LampTuneYoungKeep) &
               (LampTuneNewWeights | LampTuneInverseSquare | LampTuneFollowSoft | LampTuneWindow |
                LampTuneCentred | LampTuneSpatial | (7u << LampTuneViewShift) |
                (LampTuneCardCapMask << LampTuneCardCapShift) | (3u << 2) | (1u << 24) | (1u << 25))) == 0,
              "bbport (r103_lamp-young-pixels): word 0 bits 27 and 28 must be free");

/// BB_LAMP_SHADOW_YOUNG as a whole number 0 to 2 (3 or more: 2; below 0: 0); text that is not a whole
/// number, or nothing: 0.
inline std::uint32_t LampYoungParse(const char* text) {
    if (!text || !text[0]) {
        return 0;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    if (end == text || !LampTuneDetail::Ends(end)) {
        return 0;
    }
    return std::uint32_t(std::clamp(value, 0l, 2l));
}

/// The bits for a pass with the knob at `value`: none without the centred window (only its resolve
/// reads them; BB_LAMP_SHADOW_WINDOW 0 and 1 have no resolve).
inline constexpr std::uint32_t LampYoungBitsFor(std::uint32_t value, const LampShadowTune& tune) {
    return value == 0 || !tune.window || !tune.window_centred ? 0u
           : value == 1                                       ? LampTuneYoung
                                                              : (LampTuneYoung | LampTuneYoungKeep);
}

/// The knob, read once (the first call).
inline std::uint32_t LampYoungValue() {
    static const std::uint32_t value = LampYoungParse(std::getenv("BB_LAMP_SHADOW_YOUNG"));
    return value;
}

/// What PointShadow::Flush ORs into tuning word 0: 0 when the knob is off (the words as before).
inline std::uint32_t LampYoungBits(const LampShadowTune& tune) {
    return LampYoungBitsFor(LampYoungValue(), tune);
}

/// PointShadow::Ready, once, when the knob is set: on or off and why first (the slot runs keep 300
/// characters of a line). centred: the centred window's builds were made; spatial: BB_LAMP_SHADOW_SPATIAL.
inline void LampYoungStartLine(bool centred, bool spatial) {
    const std::uint32_t v = LampYoungValue();
    if (v == 0) {
        return;
    }
    std::printf("Ray traced lamps (r103): young pixels %s (BB_LAMP_SHADOW_YOUNG=%u%s): a pixel whose history "
                "the guards just gave up (fewer than 2 frames left) shows the mean of this frame's answers "
                "within 2 px on its surface (5x5; 3x3 without history and in the half-resolution first pass) "
                "by 1 - smoothstep(0.5, 2, frames), not its bare ray; every guard against trails takes the raw "
                "answer; BB_LAMP_SHADOW_SPATIAL=%u (1: the larger of the two shares); %s; nothing with sharp "
                "lamps, BB_LAMP_SHADOW_HISTORY below 2/3, views 2, 3 and 7\n",
                centred ? "on" : "off", unsigned(v),
                centred ? ""
                        : "; it needs the centred window, BB_LAMP_SHADOW_WINDOW=2, which this run does not have "
                          "(not set, or its build could not be made)",
                spatial ? 1u : 0u,
                v == 2 ? "2: where the clamp gives a history up it keeps the clamped value with one frame "
                         "(a test setting; can leave a faint trail)"
                       : "the clamp's cut stays as it was");
}

namespace LampYoungDetail {
inline std::uint32_t passes = 0; ///< passes whose resolve ran with bit 27 since the last line
} // namespace LampYoungDetail

/// PointShadow::Flush, once a pass: `ran` = the pass is split into the centred trace and resolve, has
/// the repair and bit 27, and its history may hold 2 frames (LampHistoryFrames, word 30: the shader's
/// own test).
inline void LampYoungPass(bool ran) {
    LampYoungDetail::passes += ran ? 1u : 0u;
}

/// PointShadow::TrackLamps, right after the r42 lamp line (a short line of its own, at its times),
/// when the knob is set.
inline void LampYoungLine() {
    if (LampYoungValue() != 0) {
        std::printf("Ray traced lamps (r103): %u ray traced lamp passes ran their resolve with the young "
                    "pixels' mean (BB_LAMP_SHADOW_YOUNG=%u) since the r42 line before\n",
                    unsigned(LampYoungDetail::passes), unsigned(LampYoungValue()));
    }
    LampYoungDetail::passes = 0;
}

/// PointShadow::OnFrameEnd's half-resolution block (every 600 frames), when the knob is set: young =
/// the rise of half_counts word 13 since its last line (the young pixels that took a mean in one 2x2
/// block in four, added by every half-resolution resolve; read with the counted passes' copy, so a
/// few passes late), passes = half-resolution passes in those frames (all of them, split into a
/// resolve or not).
inline void LampYoungHalfLine(double young, std::uint32_t passes, std::uint32_t frames) {
    if (LampYoungValue() == 0) {
        return;
    }
    std::printf("Ray traced lamps (r103): about %.0f young pixels per half-resolution pass took the "
                "same-surface mean (4 x those of one 2x2 block in four; %u passes in %u frames)\n",
                passes != 0 ? 4.0 * young / double(passes) : 0.0, unsigned(passes), unsigned(frames));
}

} // namespace Vulkan
'''

# (anchor, before, after): the anchor stays as it is; `before` goes in front of it, `after` behind it.
EDITS = {
S: [
("bool t_centred = false;         // bbport (r60_lamp-centred-window): BB_LAMP_SHADOW_WINDOW=2 (with t_window)\n",
 "",
 "bool t_young = false;           // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG (bit 27; the resolve)\n"
 "bool t_young_keep = false;      // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG=2 (bit 28)\n"),
("    t_centred = (f & (1u << 22u)) != 0u;     // bbport (r60_lamp-centred-window)\n",
 "",
 "    t_young = (f & (1u << 27u)) != 0u;       // bbport (r103_lamp-young-pixels)\n"
 "    t_young_keep = (f & (1u << 28u)) != 0u;  // bbport (r103_lamp-young-pixels)\n"),
("#endif\n\n#ifdef HALF\n// bbport (r32_lamp-half): more bits of `mode` (vk_point_shadow.cpp ModeHalf*).\n",
 r"""
// bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG (word 0 bit 27, bit 28 with the value 2; read
// by the resolve only, in main after the guards). A pixel the guards left `frames` of history (after
// the reject, the trail cap, the unsure cut and the clamp) is young by 1 - smoothstep(YOUNG_FROM,
// YOUNG_ALL, frames): 1 at half a frame or less, 0.74 at one, 0 from two on. The rule runs only where
// the history may hold YOUNG_ALL frames or more (word 30; else every pixel would stay young).
// youngMean: spatialMean's mean over the 5x5 answers of the tile at full pixels (apart 1: the
// full-resolution pass and the half-resolution second pass): this frame's answers of the pixel and of
// up to 24 neighbours within 2 px that have one and lie on its plane (spatialMean's SPATIAL_PLANE_M +
// SPATIAL_PLANE_REL; normal n, or from depth). The tile cells are those the window reads; the depth
// loads are new (8 of them spatialMean's). YOUNG_SLOT: half_counts word 13 (unused before): the young
// pixels of one 2x2 block in four that took a mean, added by every half-resolution resolve
// (vk_point_shadow.cpp: lamp_young_pixels.h LampYoungHalfLine).
const float YOUNG_FROM = 0.5;
const float YOUNG_ALL = 2.0;
#ifdef HALF
const uint YOUNG_SLOT = 13u;
#endif
float youngMean(ivec2 cell, ivec2 px, vec3 P, vec3 n, float answer) {
    const vec3 nn = n != vec3(0.0) ? n : surfaceNormal((vec2(px) + 0.5) / size, P);
    if (nn == vec3(0.0)) {
        return -1.0;
    }
    const float tol = SPATIAL_PLANE_M + SPATIAL_PLANE_REL * P.z;
    float sum = answer, count = 1.0;
    for (int y = -2; y <= 2; ++y) {
        for (int x = -2; x <= 2; ++x) {
            const float a = tile_answer[(cell.y + y) * TILE_SIDE + cell.x + x];
            if ((x | y) == 0 || !(a >= 0.0)) {
                continue;
            }
            const vec2 uv_q = (vec2(px + ivec2(x, y)) + 0.5) / size;
            const vec3 Q = viewPosAt(uv_q, textureLod(depth_tex, uv_q, 0.0).x);
            if (abs(dot(nn, Q - P)) < tol) {
                sum += a;
                count += 1.0;
            }
        }
    }
    return sum / count;
}
""",
 ""),
("                frames *= 1.0 - taken;\n",
 "#ifdef CENTRED\n"
 "                // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG=2 (bit 28, a test setting): where the\n"
 "                // clamp gives the history up it keeps the clamped value (fitted) with up to one frame,\n"
 "                // taken x the frames it had (at most 1), in place of none. fitted lies on the bound's edge\n"
 "                // toward the old shadow, so this can leave a faint trail; with 1 the cut pixel takes this\n"
 "                // frame's mean instead (the young pixels below).\n"
 "                const float young_keep = t_young_keep && resolve ? taken * min(frames, 1.0) : 0.0;\n"
 "#endif\n",
 "#ifdef CENTRED\n"
 "                if (young_keep > 0.0) { // bbport (r103_lamp-young-pixels)\n"
 "                    frames = max(frames, young_keep);\n"
 "                }\n"
 "#endif\n"),
("#ifdef CENTRED\n        if (spatial >= 0.0) {\n",
 "#ifdef CENTRED\n"
 "        // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG. Where the guards above left a pixel few\n"
 "        // frames (a moving shadow's edge: the reject, the clamp, the trail cap or the unsure cut gave its\n"
 "        // history up), its ratio was this frame's bare ray, 0 or 1: a ragged, hatched band on the moving\n"
 "        // edge. Here it takes a mean of this frame's answers on its own surface instead, by its young\n"
 "        // share (YOUNG_FROM, YOUNG_ALL): the 5x5 one (youngMean) where a history was found and the tile is\n"
 "        // at full pixels; in the half-resolution first pass (taps 2 px apart) spatialMean's 3x3, the same\n"
 "        // reach of 2 px; where no history was found (a surface just uncovered, a camera cut) spatialMean's\n"
 "        // 3x3 (resolve_apart: 1 px, 2 px in that first pass), as r93 takes it. Such a surface is young on\n"
 "        // its next frame too (frames 1: 0.74 of the 5x5), so its contact shadows spread by up to 2 px for\n"
 "        // two frames. It goes in through r93's blend below: the mean's share is max(r93's, young), and r93's\n"
 "        // mean moves to the young one by young; without bit 26 (BB_LAMP_SHADOW_SPATIAL=0) the share is\n"
 "        // young alone, so a pixel with 2 frames or more keeps its own answer as before; with bit 26 a\n"
 "        // pixel without history stays r93's. Every guard above took the raw answer, and `fast` (stored\n"
 "        // below) is still the raw answers' mean. (A pixel that took its block's answer, HALF_TAKEN, does\n"
 "        // not come here: it shows the block's first-pass pixel's ratio, which this rule made there.)\n"
 "        if (t_young && resolve && word(history_at + 30u) >= YOUNG_ALL) {\n"
 "            const float young = held ? 1.0 - smoothstep(YOUNG_FROM, YOUNG_ALL, frames) : 1.0;\n"
 "            if (young > 0.0 && (held || !t_spatial)) {\n"
 "                const ivec2 cell = ivec2(gl_LocalInvocationID.xy) + 2;\n"
 "                const float m = held && resolve_apart == 1 ? youngMean(cell, px, P, n, answer)\n"
 "                                : spatial >= 0.0          ? spatial\n"
 "                                                          : spatialMean(cell, px, P, n, answer, resolve_apart);\n"
 "                if (m >= 0.0) {\n"
 "                    spatial_u = spatial >= 0.0 ? max(spatial_u, young) : young;\n"
 "                    spatial = spatial >= 0.0 ? mix(spatial, m, young) : m;\n"
 "#ifdef HALF\n"
 "                    if (((px.x | px.y) & 2) == 0) { // the pixels of one 2x2 block in four, for the log\n"
 "                        atomicAdd(half_counts.n[YOUNG_SLOT], 1u);\n"
 "                    }\n"
 "#endif\n"
 "                }\n"
 "            }\n"
 "        }\n"
 "#endif\n",
 ""),
],
C: [
('#include "video_core/renderer_vulkan/vk_camera_motion.h"\n',
 '#include "video_core/renderer_vulkan/lamp_young_pixels.h" // bbport (r103_lamp-young-pixels)\n',
 ""),
("                        resolve_pipeline ? \"its own\" : resolve_wanted ? \"the centred one (its own could not be made)\"\n"
 "                                                                      : \"the centred one\");\n"
 "        }\n",
 "",
 "        LampYoungStartLine(centred, tune.spatial); // bbport (r103_lamp-young-pixels): only with the knob set\n"),
("            data.insert(data.end(), tune_words.begin(), tune_words.end());\n",
 "",
 "            data[tune_at] |= LampYoungBits(pass_tune); // bbport (r103_lamp-young-pixels): bits 27, 28; 0 when off\n"),
("    if (split) {\n        answers_short = false;\n    }\n",
 "",
 "    LampYoungPass(split && repair && LampYoungBits(pass_tune) != 0u && // bbport (r103_lamp-young-pixels)\n"
 "                  LampHistoryFrames(pass_tune) >= 2.0f);\n"),
("    line_spatial = 0; // bbport (r93_lamp-shadow-spatial)\n",
 "",
 "    LampYoungLine(); // bbport (r103_lamp-young-pixels): a short line after the r42 line, only with the knob set\n"),
("        half_frames = 0;\n",
 "        LampYoungHalfLine(d[13] * counted, half_line_passes, half_frames); // bbport (r103_lamp-young-pixels)\n",
 ""),
],
U: [
('#include "gpu/shadps4/video_core/renderer_vulkan/lamp_shadow_tune.h"\n',
 "",
 '#include "gpu/shadps4/video_core/renderer_vulkan/lamp_young_pixels.h" // bbport (r103_lamp-young-pixels)\n'),
("        assert(LampTuneSpatialBit(odd) == 0u);\n    }\n",
 "",
 r"""    // bbport (r103_lamp-young-pixels): BB_LAMP_SHADOW_YOUNG is 0 to 2 (3 or more: 2; below 0, text or
    // nothing: 0); its bits only with the centred window, and never in LampTuneWords (Flush ORs them in).
    {
        static_assert(LampTuneYoung == 1u << 27 && LampTuneYoungKeep == 1u << 28);
        assert(LampYoungParse(nullptr) == 0u && LampYoungParse("") == 0u && LampYoungParse("0") == 0u);
        assert(LampYoungParse("1") == 1u && LampYoungParse(" 2 ") == 2u && LampYoungParse("7") == 2u);
        assert(LampYoungParse("-1") == 0u && LampYoungParse("yes") == 0u && LampYoungParse("1x") == 0u);
        LampShadowTune t;
        t.window = true;
        t.window_centred = true;
        assert(LampYoungBitsFor(0u, t) == 0u && LampYoungBitsFor(1u, t) == LampTuneYoung &&
               LampYoungBitsFor(2u, t) == (LampTuneYoung | LampTuneYoungKeep));
        t.window_centred = false;
        assert(LampYoungBitsFor(1u, t) == 0u && LampYoungBitsFor(2u, t) == 0u);
        t.window = false;
        t.window_centred = true;
        assert(LampYoungBitsFor(2u, t) == 0u);
        const LampShadowTune d{};
        assert((LampTuneWords(d, true, 0.05f, nullptr, 9u)[0] & (LampTuneYoung | LampTuneYoungKeep)) == 0u);
    }
"""),
],
# README.md: readme_edit (the row after the BB_LAMP_SHADOW_SPATIAL row)
}

ROW = ("| `BB_LAMP_SHADOW_YOUNG` | Lamp shadows that move. `1`, with `BB_LAMP_SHADOW_WINDOW=2` (the default) and soft or "
       "softer lamps: a pixel whose history the guards against trails just gave up (fewer than 2 frames left: at a "
       "moving shadow's edge) shows the mean of this frame's shadow answers within 2 pixels on its own surface (within "
       "1 cm plus 0.5% of the distance of its plane), by 1 - smoothstep(0.5, 2, frames) (all of it at half a frame or "
       "less, none from 2 frames on), instead of its own single ray, 0 or 1, so a moving edge is not ragged and "
       "hatched. A pixel with no history at all takes the 3x3 mean, as `BB_LAMP_SHADOW_SPATIAL=1` does, and on its "
       "next frame (one frame of history) 0.74 of the wider mean, so a surface just uncovered, or everything after a "
       "camera cut, is spread by up to 2 pixels for two frames. At "
       "half resolution (`graphics_lamp_shadow_half=1`) the pixel the first pass traces in each 2x2 block takes the "
       "3x3 of its neighbouring blocks' pixels (2 pixels apart), and the block's other pixels that share its answer "
       "show that value. With `BB_LAMP_SHADOW_SPATIAL=1` the larger of the two shares is taken; with it off a pixel "
       "with 2 frames or more is left as before. The guards themselves still take each pixel's own answer. Nothing "
       "with `BB_LAMP_SHADOW_WINDOW` 0 or 1, sharp lamps, `BB_LAMP_SHADOW_HISTORY` below 2/3 (a history of fewer than "
       "2 frames) or `BB_LAMP_SHADOW_VIEW` 2, 3 or 7. `2` (a test setting): also, where the window clamp gives a "
       "history up, the pixel keeps the clamped value with up to one frame; that value lies toward the old shadow, so "
       "it can leave a faint trail. Read at start. Log: \"(r103)\" lines. `0`: as before | `0` |\n")


def readme_edit(text):
    """The README row goes after the BB_LAMP_SHADOW_SPATIAL row (r93's; the whole line is the anchor)."""
    lines = [l for l in text.split("\n") if l.startswith("| `BB_LAMP_SHADOW_SPATIAL` |")]
    if len(lines) != 1:
        raise SystemExit("README.md: the BB_LAMP_SHADOW_SPATIAL row is there %d times, wanted 1 (r93 first)"
                         % len(lines))
    return (lines[0] + "\n", "", ROW)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    if path == R:
        return [readme_edit(text)]
    return EDITS[path]


def text_checks(texts):
    """The ties a compiler cannot check."""
    s = texts[S]
    for want, n in (("(1u << 27u)", 1), ("(1u << 28u)", 1), ("float youngMean(", 1),
                    ("const float YOUNG_FROM = 0.5;", 1), ("const float YOUNG_ALL = 2.0;", 1),
                    ("const uint YOUNG_SLOT = 13u;", 1), ("youngMean(cell, px, P, n, answer)", 1),
                    ("float spatialMean(", 1), ("float spatial_u = 1.0;", 1),
                    ("mix(answer, spatial, spatial_u)", 1), ("const uint HALF_SLOTS = ", 1)):
        if s.count(want) != n:
            raise SystemExit("text check: %s holds %r %d times, wanted %d" % (S, want, s.count(want), n))
    # every r103 line of the shader lies inside #ifdef CENTRED (the other builds keep their SPIR-V words);
    # (r101's HALF_YOUNG and its comments are r101's, inside #ifdef HALF)
    mine = re.compile(r"r103|\b(t_young|t_young_keep|youngMean|young_keep|YOUNG_FROM|YOUNG_ALL|YOUNG_SLOT)\b")
    stack = []
    for line in s.split("\n"):
        st = line.strip()
        if st.startswith("#if"):
            stack.append(st == "#ifdef CENTRED")
        elif st.startswith("#else") or st.startswith("#elif"):
            stack[-1] = False  # (review) the other branch of an #ifdef CENTRED is not CENTRED code
        elif st.startswith("#endif"):
            stack.pop()
        elif mine.search(line) and not any(stack) and "r101" not in line and "HALF_YOUNG" not in line:
            raise SystemExit("text check: r103 shader line outside #ifdef CENTRED: %r" % line)
    # word 13 of half_counts is no slot anyone else writes (r101: 13 unused, 14 HALF_YOUNG)
    if "half_counts.n[13" in s or "half_n[13" in s or "HALF_YOUNG = 4u" in s:
        raise SystemExit("text check: half_counts word 13 is in use")
    # the order in main: the clamp's keep, r103's young block, r93's blend, the history store
    a = s.find("frames = max(frames, young_keep);")
    b = s.find("if (t_young && resolve && word(history_at + 30u) >= YOUNG_ALL) {")
    c = s.find("mix(answer, spatial, spatial_u)")
    d = s.find("        imageStore(history_cur, px, vec4(ratio, P.z, frames + 1.0, fast));")
    e = s.find("float spatial_u = 1.0;")
    if not (0 <= e < a < b < c < d):
        raise SystemExit("text check: spatial_u, the keep, the young block, r93's blend and the store are out of order")
    # the youngMean function lies after spatialMean (it uses r93's plane constants)
    if not (0 <= s.find("const float SPATIAL_PLANE_REL") < s.find("float youngMean(")):
        raise SystemExit("text check: youngMean is not after r93's constants")
    if "YOUNG_FROM, YOUNG_ALL" not in s or "smoothstep(0.5, 2" not in ROW or "smoothstep(0.5, 2" not in HEADER:
        raise SystemExit("text check: README row, header and shader constants disagree")
    cs = texts[C]
    if cs.find("LampYoungLine();") < cs.find("line_spatial = 0; // bbport (r93_lamp-shadow-spatial)"):
        raise SystemExit("text check: the r103 line is not after r93's line")
    if cs.find("LampYoungHalfLine(") < cs.find("half_last = now;"):
        raise SystemExit("text check: the r103 half line is not after the half counts are read")


def state_of(cur, eds, path):
    """'applied' (anchor once, every inserted text once), 'clean' (anchor once, none of them), else refuse.
    Inserted texts are found by themselves, not next to their anchor (another patch may insert next to
    the same anchor)."""
    done = todo = 0
    for anchor, before, after in eds:
        parts = [t for t in (before, after) if t]
        na, counts = cur.count(anchor), [cur.count(t) for t in parts]
        if na == 1 and all(k == 1 for k in counts):
            done += 1
        elif na == 1 and all(k == 0 for k in counts):
            todo += 1
        else:
            raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                             % (path, na, counts, anchor[:70]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R103_ROOT)" % ROOT)
    new_full = os.path.join(ROOT, NEW)
    header = HEADER.replace("\n", "\r\n").encode("utf-8")
    new_there = os.path.exists(new_full)
    new_ours = new_there and open(new_full, "rb").read() == header
    plan = []
    for path in (S, C, U, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    if state == "applied" and not new_ours:
        raise SystemExit("mixed state: edits applied but %s is %s" % (NEW, "not ours" if new_there else "missing"))
    if state == "clean" and new_there:
        raise SystemExit("mixed state: edits not applied but %s is there" % NEW)

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            for anchor, before, after in eds:
                cur = cur.replace(anchor, before + anchor + after)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            text_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, 1 new file; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        for path, eds, raw, eol, cur, _ in plan:
            full = os.path.join(ROOT, path)
            tmp = full + ".r103tmp"
            open(tmp, "wb").write(texts[path].replace("\n", eol).encode("utf-8"))
            os.replace(tmp, full)
        open(new_full, "wb").write(header)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        for anchor, before, after in reversed(eds):
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        tmp = full + ".r103tmp"
        open(tmp, "wb").write(out[path])
        os.replace(tmp, full)
    os.remove(new_full)
    print("reverted")


main()
