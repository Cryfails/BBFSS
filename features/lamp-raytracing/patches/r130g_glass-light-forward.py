# r130g_glass-light-forward: FEATURE patch on top of r130c (lane LRT, glass plan stage S1, part 2). Draft:
# FIXED copy (Opus short review 2026-11-16): PrepareDraw tests draw.glass before the steady rule (a draw r121b refused after the
# placed test keeps glass_placed but is no pane). Otherwise the same as r130g_glass-light-forward.py.
# <queue>/LRT/next/r130g_glass-light-forward.draft.md. Three parts, one knob (BB_GLASS_LIGHT, from r130c; no new knob):
#  (A) a lamp ray's glass query aims at the lamp's CENTRE, from the ray's start to 0.02 m short of it (GLASS_LAMP_CLEAR), also where
#      the solid ray is not cast (inside its blind end, which is 0.18 m or more): glass close to a lamp (a lantern's panes) now tints
#      its light. r130c searched only where the solid ray ran, so up to its blind end short of the lamp.
#  (B) a registered forward pane (window, bottle, lantern, cabinet) drawn with a palette the GPU wrote, which r121b refuses, is let
#      through when its instance was drawn on 3 frames in a row (at most 16 a frame; a pane found moving is not carried), and is
#      carried into the next frame's scene (r86 carry) with its glass record, with BB_GLASS_LIGHT on only.
#  (C) a counter of what the lamp rays did with glass: rays asked, met glass, tinted, met inside the old blind end, the entries met,
#      one lamp's view position and its nearest pane's distance from the lamp's centre. In the half resolution passes that are
#      counted (one in 8), half_counts words 16 to 24 (the buffer is 9 words longer with BB_GLASS_LIGHT on). Printed in the log in
#      every run with BB_GLASS_LIGHT on: a "first look" line and every 600 frames.
#
# Off guarantee: BB_GLASS_LIGHT unset (or off for a reason): glass_light_mode stays 0; GlassPlacedAllowed is false at its first test,
# so r121b's "placed palette" refusal works exactly as before; the carry conditions read as before; no GLASS build is selected; the
# half counter buffer keeps its 16 words (half_words); every shader edit is under #ifdef GLASS (the 16 non-GLASS point_shadow_ray
# SPIR-V builds are byte-identical, compared by the verifying run).
#
# Differences from the draft (so that r130c's own check still says "applied" after this patch: its texts and its new files are not
# edited, only added to): the new constants and JudgeSteady live in NEW files (host_shaders/glass_light_forward_layout.h,
# renderer_vulkan/glass_light_forward.h) and their test is a new file (engine/tests/test_glass_light_forward.cpp, built and run
# next to glass-light-test), not edits of glass_light_layout.h, glass_light.h and test_glass_light.cpp; CMakeLists.txt gets the
# include dependency and the test target; r130c's glassCross and its lampVisibility lines stay (glassCrossC is the counting
# copy, called first: r130c's lines are then reached only with the glass flag clear); the counters of part B are a struct of their
# own (glass_fwd) and its once line, 600-frame line and early line are made by functions called from the places r130c does
# not own; README: a new row after r130c's BB_GLASS_LIGHT row (r130c's sentence about 0.18 m stays, the new row replaces it) and a
# sentence in the BB_RT_GLASS_STATIC row. The 600-frame line is not "in" r130c's line but printed right after it, in the same call.
#
# Not verified (no full build of the engine, no game run, no GPU): that the engine links; that the ray query loop runs without a
# validation error; the picture; where the light path really fails (that is what the counter says in the first build); that the
# torch's palette never qualifies as steady; the cost estimates.
#
# Use: python -I -X utf8 r130g_glass-light-forward.py check | apply | revert
# Root: R130G_ROOT, else <tree>; a root without engine/gpu is refused. Needs r130c applied (revert this one FIRST: last in,
# first out). Line ends kept (CRLF or LF per file; a mixed file is refused; new files take CRLF). Each edit refuses unless its
# anchor is found exactly once; a mixed applied/clean state is refused; text checks run on the result before anything is written.
# apply backs the originals up in r130g_backup next to this script and writes through a temp file and a rename; revert takes
# out exactly what apply inserted and removes the new files.
import os, sys

ROOT = os.environ.get("R130G_ROOT") or "<tree>"
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r130g_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"
HS = "engine/gpu/shadps4/video_core/host_shaders/"
SH = HS + "point_shadow_ray.comp"
TH = RV + "vk_rt_shadow.h"
TC = RV + "vk_rt_shadow.cpp"
PH = RV + "vk_point_shadow.h"
PC = RV + "vk_point_shadow.cpp"
RF = RV + "vk_rasterizer_effects.cpp"
CM = "engine/gpu/CMakeLists.txt"
BS = "engine/build.sh"
R = "README.md"
NEED = HS + "glass_light_layout.h"  # r130c's file: present only with r130c applied

# New files: path -> text (LF here; written with CRLF).
NEW = {
HS + "glass_light_forward_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130g_glass-light-forward): what the lamp pass's GLASS builds (point_shadow_ray.comp, GLASS=1) and the engine
// (renderer_vulkan/glass_light_forward.h, which ties these to its constants with static_asserts) share, on top of
// glass_light_layout.h. Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and C++
// includes it as it is.
#ifndef GLASS_LIGHT_FORWARD_LAYOUT_H
#define GLASS_LIGHT_FORWARD_LAYOUT_H

// The glass query of a lamp ray ends this far (m) short of the lamp's centre.
#define GLASS_LAMP_CLEAR 0.02
// The glass counter's words in half_counts (the half resolution passes' counters): the first word and how many. +0 rays asked,
// +1 met a glass record, +2 tinted the light, +3 met one inside the old blind end, +4 the entries met (OR of bits 0-31), +5..+7 the
// view position of a lamp met (float bits, last written), +8 its nearest pane's distance from the lamp's centre (mm, smallest).
#define GLASS_RAY_FIRST 16u
#define GLASS_RAY_SLOTS 9u

#endif
''',
RV + "glass_light_forward.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r130g_glass-light-forward): the pure parts of the forward glass light: the numbers the lamp shader shares
// (host_shaders/glass_light_forward_layout.h) and the "steady" rule that lets a registered pane drawn with a palette the GPU wrote
// into the scene (RtShadow::GlassPlacedSteady). No Vulkan here: tests/test_glass_light_forward.cpp builds this header alone.

#include <cstdint>
#include <iterator>
#include <unordered_map>

#include "../host_shaders/glass_light_forward_layout.h"

namespace Vulkan::GlassLight {

using u32 = std::uint32_t;
using u64 = std::uint64_t;

inline constexpr float LampClear = float(GLASS_LAMP_CLEAR);
inline constexpr u32 RayFirst = GLASS_RAY_FIRST, RaySlots = GLASS_RAY_SLOTS;
/// The frames in a row a placed pane instance must be drawn, and the most the scene takes in a frame.
inline constexpr u32 SteadyFrames = 3, PlacedPerFrame = 16;
/// The judge's table: at this many keys the ones not drawn for SteadyKeep frames go, then all if it is still full.
inline constexpr u32 SteadyKeysMost = 256, SteadyKeep = 6;

// half_counts holds 16 words before the glass counter; the counter follows them.
static_assert(RayFirst >= 16 && RayFirst + RaySlots == 25 && RaySlots == 9 && LampClear > 0.0f && LampClear < 0.1f);

struct Steady {
    u64 frame = 0; // the last frame the instance was drawn
    u32 run = 0;   // the frames in a row up to it
};
using SteadyMap = std::unordered_map<u64, Steady>;

/// A placed pane instance `instance` is drawn on `frame` (any number of times in it): true once it was drawn on SteadyFrames
/// frames in a row (a gap of one frame starts the count again). The held torch's palette sits at two addresses in turn, so each
/// of its instances is drawn every other frame and never gets there.
inline bool JudgeSteady(SteadyMap& map, u64 instance, u64 frame) {
    if (map.size() >= SteadyKeysMost && !map.contains(instance)) {
        for (auto it = map.begin(); it != map.end();) {
            it = it->second.frame + SteadyKeep < frame ? map.erase(it) : std::next(it);
        }
        if (map.size() >= SteadyKeysMost) {
            map.clear();
        }
    }
    Steady& s = map[instance];
    if (s.run == 0) {
        s = {frame, 1};
    } else if (s.frame != frame) {
        s.run = s.frame + 1 == frame ? (s.run < 1000u ? s.run + 1u : s.run) : 1u;
        s.frame = frame;
    }
    return s.run >= SteadyFrames;
}

} // namespace Vulkan::GlassLight
''',
"engine/tests/test_glass_light_forward.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r130g_glass-light-forward): the steady rule for a registered pane drawn with a GPU-placed palette and the numbers the
// lamp shader shares (renderer_vulkan/glass_light_forward.h). Pure: no Vulkan. Built and run by engine/build.sh --test and the
// CMake target glass-light-forward-test.
#undef NDEBUG
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "gpu/shadps4/video_core/renderer_vulkan/glass_light_forward.h"

namespace L = Vulkan::GlassLight;

int main() {
    // a. the shared numbers: the counter follows half_counts' 16 words, 9 of them.
    assert(L::RayFirst >= 16u && L::RayFirst + L::RaySlots == 25u && L::RaySlots == 9u);
    assert(L::LampClear == 0.02f && L::SteadyFrames == 3 && L::PlacedPerFrame == 16);

    // b. A, A, A on three frames in a row: taken on the third, and then on.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 7, 100) && !L::JudgeSteady(m, 7, 101) && L::JudgeSteady(m, 7, 102));
        assert(L::JudgeSteady(m, 7, 102) && L::JudgeSteady(m, 7, 103)); // twice in a frame, and on
    }
    // c. the torch: two palette addresses in turn, each instance every other frame: never.
    {
        L::SteadyMap m;
        for (std::uint64_t f = 1; f <= 200; ++f) {
            assert(!L::JudgeSteady(m, (f & 1u) ? 11 : 12, f));
        }
    }
    // d. a gap starts the count again; the same frame twice counts once.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 5, 1) && !L::JudgeSteady(m, 5, 1) && !L::JudgeSteady(m, 5, 2));
        assert(!L::JudgeSteady(m, 5, 4)); // frame 3 missed
        assert(!L::JudgeSteady(m, 5, 5) && L::JudgeSteady(m, 5, 6));
        assert(!L::JudgeSteady(m, 5, 8)); // and a gap after taken starts it again
    }
    // e. two instances do not share a count.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 1, 10) && !L::JudgeSteady(m, 2, 10) && !L::JudgeSteady(m, 1, 11) && !L::JudgeSteady(m, 2, 11));
        assert(L::JudgeSteady(m, 1, 12) && L::JudgeSteady(m, 2, 12));
    }
    // f. the table stays bounded: full of one frame's keys it is cleared (a new key stays, as a first look); with old keys among
    // the new ones only the old go.
    {
        L::SteadyMap m;
        for (std::uint64_t k = 0; k < L::SteadyKeysMost; ++k) {
            L::JudgeSteady(m, 1000 + k, 1);
        }
        assert(m.size() == L::SteadyKeysMost);
        L::JudgeSteady(m, 5000, 2);
        assert(m.size() == 1 && m.contains(5000));
        L::SteadyMap n;
        for (std::uint64_t k = 0; k < 100; ++k) {
            L::JudgeSteady(n, 1000 + k, 1);
        }
        for (std::uint64_t k = 100; k < L::SteadyKeysMost; ++k) {
            L::JudgeSteady(n, 1000 + k, 9);
        }
        L::JudgeSteady(n, 5000, 10);
        assert(n.size() == L::SteadyKeysMost - 100 + 1 && n.contains(5000) && !n.contains(1000) && n.contains(1100));
        for (std::uint64_t f = 11; f < 2000; ++f) { // a long run of changing keys never grows it past the bound
            L::JudgeSteady(n, 9000 + f, f);
            assert(n.size() <= L::SteadyKeysMost);
        }
    }
    // g. frame 0 is a frame like any other.
    {
        L::SteadyMap m;
        assert(!L::JudgeSteady(m, 3, 0) && !L::JudgeSteady(m, 3, 1) && L::JudgeSteady(m, 3, 2));
    }

    std::puts("glass light forward: ok");
    return 0;
}
''',
}

# ("ins", anchor, before, after): the anchor stays; `before` goes in front of it, `after` behind it.
# ("rep", old, new): old is replaced by new (new never holds old).
BLOCK_A = r'''#ifdef GLASS
// bbport (r130g_glass-light-forward): the glass query of a lamp ray, with a counter. glassCrossC is r130c's glassCross (which stays)
// plus: the glass records the ray meets are counted. g_asked: queries asked. g_met: met a glass record. g_tint: the product it gave
// was below 1 in some channel. g_beyond: met one farther than old_end (the end of the old solid ray: what r130c searched; the
// glass inside its blind end is what r130g adds). g_entries: the registry entries met, a mask of entries 0 to 31. g_near_t: the
// nearest hit of the last query along its ray (-1: none). g_last: the view position of the last lamp whose query met glass and w,
// its nearest pane's distance from the lamp's centre (w < 0: none yet). The half resolution passes add these to half_counts words
// GLASS_RAY_FIRST and on (HalfCount); the other builds keep them and do nothing with them.
#include "glass_light_forward_layout.h"
uint g_asked = 0u, g_met = 0u, g_tint = 0u, g_beyond = 0u, g_entries = 0u;
float g_near_t = -1.0;
vec4 g_last = vec4(0.0, 0.0, 0.0, -1.0);

vec3 glassCrossC(vec3 o, float tmin, vec3 dir, float tmax, float old_end) {
    vec3 product = vec3(1.0);
    uint seen_lo = 0u, seen_hi = 0u, looked = 0u;
    bool hit_any = false, beyond = false;
    g_near_t = -1.0;
    rayQueryEXT glass;
    rayQueryInitializeEXT(glass, scene, gl_RayFlagsNoOpaqueEXT, GLASS_LIGHT_MASK, o, max(tmin, float(GLASS_LIGHT_TMIN)), dir, tmax);
    while (rayQueryProceedEXT(glass)) {
        if (rayQueryGetIntersectionTypeEXT(glass, false) != gl_RayQueryCandidateIntersectionTriangleEXT) {
            continue;
        }
        const uint index = uint(rayQueryGetIntersectionInstanceCustomIndexEXT(glass, false));
        if ((index & GLASS_INDEX_BIT) != 0u) {
            const uint entry = index & GLASS_ENTRY_MASK;
            const float t = rayQueryGetIntersectionTEXT(glass, false);
            g_near_t = g_near_t < 0.0 ? t : min(g_near_t, t);
            hit_any = true;
            beyond = beyond || t > old_end;
            g_entries |= entry < 32u ? 1u << entry : 0u;
            const uint bit = 1u << (entry & 31u);
            const bool seen = ((entry < 32u ? seen_lo : seen_hi) & bit) != 0u;
            if (!seen) {
                seen_lo |= entry < 32u ? bit : 0u;
                seen_hi |= entry < 32u ? 0u : bit;
                const uint w = data.d[g_words + entry];
                product *= vec3(float(w & 255u), float((w >> 8u) & 255u), float((w >> 16u) & 255u)) * (1.0 / 255.0);
            }
        }
        if (++looked >= GLASS_RAY_CAP) {
            rayQueryTerminateEXT(glass);
        }
    }
    ++g_asked;
    g_met += hit_any ? 1u : 0u;
    g_beyond += beyond ? 1u : 0u;
    g_tint += any(lessThan(product, vec3(0.999))) ? 1u : 0u;
    return product;
}
#endif

'''

BLOCK_B = r'''#ifdef GLASS
    // bbport (r130g_glass-light-forward): with the glass flag the lamp's glass query aims at the lamp's CENTRE from the ray's start
    // to GLASS_LAMP_CLEAR short of it, after a free solid ray, and also when the solid ray was not cast (inside its blind end or
    // reach, where it is free): only registered glass records (mask 0x10) are read, so the blind end adds no blocker. The tint is
    // per lamp (its centre), not per point of its disc. r130c's lines below are reached only without the glass flag.
    if (g_glass) {
        if (ray(from, reach, target) >= 0.0) {
            return 0.0;
        }
        const vec3 to_c = L - from;
        const float len_c = length(to_c);
        const float g_lo = max(reach * 0.5, float(GLASS_LIGHT_TMIN));
        const float g_hi = len_c - float(GLASS_LAMP_CLEAR);
        if (g_hi > g_lo) {
            const vec3 through = glassCrossC(from, g_lo, to_c / len_c, g_hi, g_cast ? g_tmax : 0.0);
            if (g_near_t >= 0.0) {
                g_last = vec4(L, len_c - g_near_t);
            }
            const float grey = dot(through, vec3(0.299, 0.587, 0.114));
            ray_hue = grey > 1e-4 ? through / grey : vec3(1.0);
            return min(grey, 1.0);
        }
        return 1.0;
    }
#endif
'''

HC_ADD = r'''#ifdef GLASS
    // bbport (r130g_glass-light-forward): this invocation's glass counters into the workgroup's (the last one flushes them below)
    if (g_asked != 0u) {
        atomicAdd(glass_n[0], g_asked);
        if (g_met != 0u) {
            atomicAdd(glass_n[1], g_met);
        }
        if (g_tint != 0u) {
            atomicAdd(glass_n[2], g_tint);
        }
        if (g_beyond != 0u) {
            atomicAdd(glass_n[3], g_beyond);
        }
        if (g_entries != 0u) {
            atomicOr(glass_n[4], g_entries);
        }
    }
    if (g_last.w >= 0.0) { // the workgroup keeps the lamp whose pane lies nearest its centre (a race may mix it with another's)
        const uint mm = uint(g_last.w * 1000.0);
        if (atomicMin(glass_n[8], mm) > mm) {
            atomicExchange(glass_n[5], floatBitsToUint(g_last.x));
            atomicExchange(glass_n[6], floatBitsToUint(g_last.y));
            atomicExchange(glass_n[7], floatBitsToUint(g_last.z));
        }
    }
#endif
'''

HC_FLUSH = r'''#ifdef GLASS
    // bbport (r130g_glass-light-forward): the workgroup's glass counters into half_counts (words GLASS_RAY_FIRST and on: sums, the
    // entries' OR, then the lamp's position and its pane's distance as the last workgroup wrote them)
    for (uint i = 0u; i < 5u; ++i) {
        const uint v = atomicAdd(glass_n[i], 0u);
        if (v != 0u) {
            if (i == 4u) {
                atomicOr(half_counts.n[GLASS_RAY_FIRST + i], v);
            } else {
                atomicAdd(half_counts.n[GLASS_RAY_FIRST + i], v);
            }
        }
    }
    const uint near_mm = atomicAdd(glass_n[8], 0u);
    if (near_mm != 0xFFFFFFFFu) {
        atomicExchange(half_counts.n[GLASS_RAY_FIRST + 8u], near_mm);
        for (uint i = 5u; i < 8u; ++i) {
            atomicExchange(half_counts.n[GLASS_RAY_FIRST + i], atomicAdd(glass_n[i], 0u));
        }
    }
#endif
'''

EDITS = {
SH: [
("ins", "vec3 colourLoad(ivec2 p, int row) {\n", BLOCK_A, ""),
("ins", "#ifdef GLASS\n    // bbport (r130c_glass-lamp-light): a blocked ray is 0; a free one crossed the glass records on its way (glassCross): the luma\n",
 BLOCK_B, ""),
("ins", "shared uint half_done;\n",
 "",
 "#ifdef GLASS\n"
 "shared uint glass_n[GLASS_RAY_SLOTS]; // bbport (r130g_glass-light-forward): the workgroup's glass counters (see HalfCount)\n"
 "#endif\n"),
("ins", "        half_done = 0u;\n",
 "",
 "#ifdef GLASS\n"
 "        for (uint i = 0u; i < GLASS_RAY_SLOTS; ++i) { // bbport (r130g_glass-light-forward): word 8 is a minimum\n"
 "            glass_n[i] = i == 8u ? 0xFFFFFFFFu : 0u;\n"
 "        }\n"
 "#endif\n"),
("ins", "    if (half_rays != 0u) {\n", HC_ADD, ""),
("ins", "    if (!first && atomicAdd(half_n[4], 0u) + atomicAdd(half_n[5], 0u) + atomicAdd(half_n[7], 0u) != 0u) {\n", HC_FLUSH, ""),
],
TH: [
("ins", '#include "video_core/renderer_vulkan/rt_glass_static.h" // bbport (r121b_glass-pane-hang)\n',
 "",
 '#include "video_core/renderer_vulkan/glass_light_forward.h" // bbport (r130g_glass-light-forward)\n'),
("ins", "        u8 glass_entry = 0;\n",
 "",
 "        // bbport (r130g_glass-light-forward): a registered pane let through r121b's placed palette refusal (set by the rasterizer\n"
 "        // from RtShadow::GlassPlacedAllowed; PrepareDraw then asks GlassPlacedSteady). Always false while BB_GLASS_LIGHT is off.\n"
 "        bool glass_placed = false;\n"),
("ins", "    void GlassLightNote(Entry& entry, const Draw& draw);\n",
 "",
 "    // bbport (r130g_glass-light-forward): the forward panes and the glass counter. glass_fwd: the 600-frame line's counts.\n"
 "    // glass_rays_now/last: the lamp pass's glass counter words (PointShadow::OnFrameEnd, GlassRaysSeen): [0] counted passes, then\n"
 "    // half_counts words GLASS_RAY_FIRST and on (asked, met, tinted, met beyond the old end, entries, view x y z bits, pane mm).\n"
 "    struct GlassFwdCounts {\n"
 "        u64 window_start = 0, placed_taken = 0, placed_unsteady = 0, placed_cap = 0, moving_left = 0, carried = 0;\n"
 "    };\n"
 "    GlassFwdCounts glass_fwd;\n"
 "    std::array<u32, 10> glass_rays_now{}, glass_rays_last{};\n"
 "    bool glass_rays_early = false;\n"
 "    GlassLight::SteadyMap glass_steady;\n"
 "    u32 glass_placed_frame_n = 0;\n"
 "    u64 glass_placed_frame = 0;\n"
 "    void GlassForwardStart();\n"
 "    void GlassForwardFrame();\n"
 "    void GlassRaysText(char* out, std::size_t size, const std::array<u32, 10>& now, const std::array<u32, 10>& last) const;\n"
 "    bool GlassPlacedSteady(u64 instance);\n"),
("ins", "    [[nodiscard]] bool SunWanted() const;\n",
 "    // bbport (r130g_glass-light-forward): the rasterizer asks (before r121b's placed palette refusal) whether a pane draw whose\n"
 "    // registry hit is `hit` (Draw::glass_entry, index + 1) may be taken with a palette the GPU wrote; the lamp pass hands in the\n"
 "    // glass counter it read back. False at its first test while BB_GLASS_LIGHT is off.\n"
 "    [[nodiscard]] bool GlassPlacedAllowed(u8 hit) const;\n"
 "    void GlassRaysSeen(const std::array<u32, 10>& words) noexcept {\n"
 "        glass_rays_now = words;\n"
 "    }\n",
 ""),
],
TC: [
("ins", "    GlassLightStart(); // bbport (r130c_glass-lamp-light): reads BB_GLASS_LIGHT once; unset: nothing\n",
 "",
 "    GlassForwardStart(); // bbport (r130g_glass-light-forward): its once line, only with BB_GLASS_LIGHT on\n"),
("ins", "// bbport (r83_glass-water-stage1): BB_RT_GLASS: a window pane's draw reached its entry\n",
 r'''// bbport (r130g_glass-light-forward): the once line (BB_GLASS_LIGHT on only).
void RtShadow::GlassForwardStart() {
    if (glass_light_mode == 0) {
        return;
    }
    glass_fwd.window_start = frame;
    std::printf("Glass light (r130g): forward panes %s (BB_RT_GLASS %s): a registered pane drawn with a GPU-placed palette is "
                "taken when drawn %u frames in a row (at most %u a frame) and carried into the next frame's scene; the glass "
                "query reaches %.2f m short of the lamp's centre (before: the solid ray's blind end, 0.18 m or more); counted in "
                "half-resolution passes (one in 8; full resolution counts nothing)\n",
                RtGlassOn() ? "possible" : "none", RtGlassOn() ? "on" : "off", GlassLight::SteadyFrames,
                GlassLight::PlacedPerFrame, double(GlassLight::LampClear));
}

// bbport (r130g_glass-light-forward): the glass counter as text: `now` less `last` (the words of GlassRaysSeen), for the first
// look and the 600-frame line.
void RtShadow::GlassRaysText(char* out, std::size_t size, const std::array<u32, 10>& now, const std::array<u32, 10>& last) const {
    const u32 counted = now[0] - last[0];
    if (counted == 0) {
        std::snprintf(out, size, "lamp rays: no counted pass (full resolution, or no half resolution pass was counted yet)");
        return;
    }
    char lamp[160] = "no lamp met";
    if (now[9] != 0) {
        float v[3];
        for (u32 i = 0; i < 3; ++i) {
            const u32 bits = now[6 + i];
            std::memcpy(&v[i], &bits, sizeof(float));
        }
        std::snprintf(lamp, sizeof(lamp), "a lamp met at %.2f m from the camera (view %.2f %.2f %.2f), its pane %.3f m from the "
                      "lamp's centre", std::sqrt(double(v[0]) * v[0] + double(v[1]) * v[1] + double(v[2]) * v[2]), double(v[0]),
                      double(v[1]), double(v[2]), double(now[9]) * 0.001);
    }
    std::snprintf(out, size, "lamp rays in %u counted passes: asked %u, met glass %u, tinted %u, met inside the old blind end %u; "
                  "entries met 0x%x; %s", counted, now[1] - last[1], now[2] - last[2], now[3] - last[3], now[4] - last[4], now[5],
                  lamp);
}

// bbport (r130g_glass-light-forward): called each scene while the mode is made, right after r130c's GlassLightFrame: the first look
// at the glass counter (once, when four passes were counted) and, every 600 frames, the forward panes and the counter.
void RtShadow::GlassForwardFrame() {
    char text[480];
    if (!glass_rays_early && glass_rays_now[0] >= 4u) {
        glass_rays_early = true;
        GlassRaysText(text, sizeof(text), glass_rays_now, std::array<u32, 10>{});
        std::printf("Glass light (r130g): first look, since start: %s\n", text);
    }
    if (frame - glass_fwd.window_start < 600) {
        return;
    }
    GlassRaysText(text, sizeof(text), glass_rays_now, glass_rays_last);
    std::printf("Glass light (r130g): frames %llu-%llu: placed panes taken %llu, not steady %llu, over the cap %llu, moving left "
                "out %llu; glass records carried %llu; %s\n",
                static_cast<unsigned long long>(glass_fwd.window_start + 1), static_cast<unsigned long long>(frame),
                static_cast<unsigned long long>(glass_fwd.placed_taken), static_cast<unsigned long long>(glass_fwd.placed_unsteady),
                static_cast<unsigned long long>(glass_fwd.placed_cap), static_cast<unsigned long long>(glass_fwd.moving_left),
                static_cast<unsigned long long>(glass_fwd.carried), text);
    glass_rays_last = glass_rays_now;
    glass_fwd = {};
    glass_fwd.window_start = frame;
}

// bbport (r130g_glass-light-forward): may a pane draw with a palette the GPU wrote be taken? Only with BB_GLASS_LIGHT on and a
// registry hit (Draw::glass_entry, index + 1) of a kind that lets light through. Off: false at the first test.
bool RtShadow::GlassPlacedAllowed(u8 hit) const {
    if (glass_light_mode == 0 || hit == 0) {
        return false;
    }
    const auto& table = GlassRegistryRules::Load();
    return hit <= table.count && GlassLight::Transmits(table.entries[hit - 1u].kind);
}

// bbport (r130g_glass-light-forward): the steady rule for such a pane instance (GlassLight::JudgeSteady: drawn on 3 frames in a
// row), and at most PlacedPerFrame of them a frame. False: the draw is left out (PrepareDraw returns 0, as for r121b's verdicts).
bool RtShadow::GlassPlacedSteady(u64 instance) {
    if (!GlassLight::JudgeSteady(glass_steady, instance, frame)) {
        ++glass_fwd.placed_unsteady;
        return false;
    }
    if (glass_placed_frame != frame) {
        glass_placed_frame = frame;
        glass_placed_frame_n = 0;
    }
    if (glass_placed_frame_n >= GlassLight::PlacedPerFrame) {
        ++glass_fwd.placed_cap;
        return false;
    }
    ++glass_placed_frame_n;
    ++glass_fwd.placed_taken;
    return true;
}

''',
 ""),
("ins", "    const bool glass_rec_on = glass_light_mode != 0 && GlassLightFrame(card_lamps);\n",
 "",
 "    if (glass_light_mode != 0) {\n"
 "        GlassForwardFrame(); // bbport (r130g_glass-light-forward): its lines come right after r130c's\n"
 "    }\n"),
("ins", "    // bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC: a pane is a still thing. The judge (rt_glass_static.h)\n",
 "    // bbport (r130g_glass-light-forward): a registered pane let through with a GPU-placed palette must be steady (3 frames in a\n"
 "    // row, at most 16 a frame); the torch's palette alternates two addresses and never is. r121b's judge below runs as before.\n"
 "    // (draw.glass too: a draw a later r121b test refused keeps glass_placed but is no pane, and goes on as before.)\n"
 "    if (draw.glass && draw.glass_placed && !GlassPlacedSteady(draw.palette != 0 ? InstanceKey(key, draw.palette) : key)) {\n"
 "        return 0;\n"
 "    }\n",
 ""),
("rep", "        if (RtGlassCarryOn()) { // bbport (r86_glass-light-stage2a, r86b): carried into the next frame\n",
 "        if (draw.glass_placed && entry.dynamic) { // bbport (r130g_glass-light-forward): a moving placed pane is not carried\n"
 "            ++glass_fwd.moving_left;\n"
 "        } else if (RtGlassCarryOn() || (glass_light_mode != 0 && entry.glass_light != 0)) { // bbport (r86, r86b, r130g): carried\n"),
("rep", "    if (RtGlassCarryOn() && need_scene && // bbport (r86b_glass-visible): or BB_GLASS_GLINT on\n",
 "    if ((RtGlassCarryOn() || (glass_light_mode != 0 && !glass_drawn.empty())) && need_scene && // bbport (r86b, r130g): or\n"),
("rep", "    if (RtGlassCarryOn()) { // bbport (r86b_glass-visible): or BB_GLASS_GLINT on\n",
 "    if (RtGlassCarryOn() || glass_light_mode != 0) { // bbport (r86b_glass-visible; r130g_glass-light-forward): or BB_GLASS_GLINT on\n"),
("ins", "        out[built++] = record;\n",
 "",
 "        glass_fwd.carried += glass_rec && kept ? 1u : 0u; // bbport (r130g_glass-light-forward): a glass record of a carried pane\n"),
],
PH: [
("ins", "    std::array<u32, 64> glass_words{};\n",
 "",
 "    // bbport (r130g_glass-light-forward): the words of the half resolution counters buffer: 16, and with glass_mode the glass\n"
 "    // counter's GlassLight::RaySlots after them (set in Ready, before HalfReady makes the buffers)\n"
 "    u32 half_words = 16;\n"),
],
PC: [
("ins", '#include "video_core/renderer_vulkan/glass_light.h"\n',
 "",
 '#include "video_core/renderer_vulkan/glass_light_forward.h" // bbport (r130g_glass-light-forward)\n'),
("ins", "    if (tune.colour) {\n",
 "    half_words = HalfSlots + (glass_mode ? GlassLight::RaySlots : 0u); // bbport (r130g_glass-light-forward): the glass counter\n",
 ""),
("rep", "            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::DeviceLocal,\n",
 "            instance, 0, half_words * sizeof(u32), VideoCore::MemoryType::DeviceLocal, // bbport (r130g): half_words\n"),
("rep", "            instance, 0, HalfSlots * sizeof(u32), VideoCore::MemoryType::HostCached,\n",
 "            instance, 0, half_words * sizeof(u32), VideoCore::MemoryType::HostCached, // bbport (r130g): half_words\n"),
("rep", "        if (half_readback->mapped_data.size() >= HalfSlots * sizeof(u32)) {\n",
 "        if (half_readback->mapped_data.size() >= half_words * sizeof(u32)) { // bbport (r130g): half_words\n"),
("rep", "            std::memset(half_readback->mapped_data.data(), 0, HalfSlots * sizeof(u32));\n",
 "            std::memset(half_readback->mapped_data.data(), 0, half_words * sizeof(u32)); // bbport (r130g): half_words\n"),
("rep", "         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{}, half_lay_out,\n",
 "         half_read_buffer = use_half ? half_readback->Handle() : vk::Buffer{},\n"
 "         half_bytes = half_words * sizeof(u32), // bbport (r130g_glass-light-forward): the counters copy's size\n"
 "         half_lay_out,\n"),
("rep", "                    const vk::BufferCopy region{0, 0, HalfSlots * sizeof(u32)};\n",
 "                    const vk::BufferCopy region{0, 0, half_bytes}; // bbport (r130g_glass-light-forward): half_words * 4\n"),
("ins", "    if (half_made && half_asked && half_readback && ++half_frames >= 600) {\n",
 "    // bbport (r130g_glass-light-forward): with BB_GLASS_LIGHT on the glass counter (half_counts words 16 to 24, written by the half\n"
 "    // resolution passes that are counted) goes to RtShadow every frame, 40 bytes: its own lines print it. The copy to the host\n"
 "    // lands in one pass of 8, late; the words are cumulative (u32 differences survive the wrap).\n"
 "    if (glass_mode && half_made && half_readback && half_readback->mapped_data.size() >= half_words * sizeof(u32)) {\n"
 "        half_readback->Invalidate(0, half_words * sizeof(u32));\n"
 "        std::array<u32, GlassLight::RayFirst + GlassLight::RaySlots> all{};\n"
 "        std::memcpy(all.data(), half_readback->mapped_data.data(), std::min(sizeof(all), half_words * sizeof(u32)));\n"
 "        std::array<u32, 10> words{};\n"
 "        words[0] = all[0];\n"
 "        for (u32 i = 0; i < GlassLight::RaySlots; ++i) {\n"
 "            words[1 + i] = all[GlassLight::RayFirst + i];\n"
 "        }\n"
 "        rt_shadow.GlassRaysSeen(words);\n"
 "    }\n",
 ""),
],
RF: [
("rep", "            if (draw.palette_placed) {\n",
 "            if (draw.palette_placed && // bbport (r130g_glass-light-forward): a registered pane may keep a placed palette\n"
 "                !(draw.glass_placed = rt_shadow->GlassPlacedAllowed(draw.glass_entry))) {\n"),
],
CM: [
("ins", "    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)\n",
 "    # bbport (r130g_glass-light-forward): and the glass counter's numbers (glass_light_forward.h)\n"
 '    if (FILENAME MATCHES "^point_shadow_ray")\n'
 "        list(APPEND INCLUDES ${SHADER_SRC}/glass_light_forward_layout.h)\n"
 "    endif()\n",
 ""),
("ins", "add_executable(glass-registry-test EXCLUDE_FROM_ALL ../tests/test_glass_registry.cpp)\n"
        "target_compile_options(glass-registry-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
        "target_include_directories(glass-registry-test PRIVATE ..)\n",
 "# bbport (r130g_glass-light-forward): the forward glass light's steady rule and shared numbers (glass_light_forward.h); also\n"
 "# built and run by engine/build.sh --test.\n"
 "add_executable(glass-light-forward-test EXCLUDE_FROM_ALL ../tests/test_glass_light_forward.cpp)\n"
 "target_compile_options(glass-light-forward-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
 "target_include_directories(glass-light-forward-test PRIVATE ..)\n",
 ""),
],
BS: [
("ins", "    out/glass-registry-test\n",
 "    # bbport (r130g_glass-light-forward): the forward glass light's steady rule and shared numbers\n"
 '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_glass_light_forward.cpp -o out/glass-light-forward-test\n'
 "    out/glass-light-forward-test\n",
 ""),
],
}

ROW_FWD = (
    "| `BB_GLASS_LIGHT` (r130g) | r130g_glass-light-forward, on top of r130c, no new knob (all of it only with `BB_GLASS_LIGHT` on). "
    "(1) A lamp ray's glass query now aims at the lamp's centre, from the ray's start to 0.02 m short of it, also where the solid "
    "ray is not cast (inside its blind end of 0.18 m or more, or its reach), so glass close to a lamp (a lantern's panes) tints its "
    "light; this replaces r130c's limit above that glass within 0.18 m of a lamp neither blocks nor tints (the tint is per lamp, from "
    "its centre, not per point of its disc). (2) A registered pane (`BB_GLASS_TABLE`: window, bottle, lantern or cabinet) that the "
    "game draws forward with a palette the GPU wrote, which `BB_RT_GLASS_STATIC` refused, is taken once its instance was drawn on "
    "3 frames in a row (at most 16 placed panes a frame; one found moving is not carried) and is carried into the next frame's scene "
    "with its glass record, also without `BB_RT_GLASS_LIGHT`; the held torch's palette alternates two addresses and never qualifies. "
    "(3) A counter in the half resolution passes that are counted (one in 8; a full resolution build counts nothing): lamp rays "
    "asked, met glass, tinted, met inside the old blind end, the entries met, one lamp's view position and its nearest pane's "
    "distance from the lamp's centre; the half counters buffer is 9 words longer. Log lines `Glass light (r130g): ...`: a once line, "
    "a first look at the counter and, every 600 frames, the panes and the counter. Cost, an estimate (not measured): off 0; on under "
    "0.03 ms (the longer glass query, a few shared atomics in counted passes); with panes one frame-end build of their captures, "
    "0.02 to 0.05 ms; memory 36 bytes on the device and 36 on the host | off |")
STATIC_SENTENCE = ("With `BB_GLASS_LIGHT` on (r130g): a registered pane of a kind that lets light through, drawn with a palette the "
                   "GPU wrote, is let through when its instance was drawn on 3 frames in a row (at most 16 a frame). ")


def readme_edits(text):
    rows = [l for l in text.split("\n") if l.startswith("| `BB_GLASS_LIGHT` |")]
    if len(rows) != 1:
        raise SystemExit("README.md: the BB_GLASS_LIGHT row is there %d times, wanted 1 (r130c applied?)" % len(rows))
    return [
        ("ins", rows[0] + "\n", "", ROW_FWD + "\n"),
        ("ins", "Cost: one hash lookup a pane draw;", STATIC_SENTENCE, ""),
    ]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def edits_for(path, text):
    return readme_edits(text) if path == R else EDITS[path]


def new_state(path):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    raw = open(full, "rb").read()
    if raw == NEW[path].replace("\n", "\r\n").encode("utf-8"):
        return "applied"
    raise SystemExit("REFUSED %s: the file exists and is not the one this patch writes" % path)


def new_lines_check(label, text):
    for n, line in enumerate(text.split("\n"), 1):
        if "\t" in line:
            raise SystemExit("text check: %s line %d holds a tab" % (label, n))
        if len(line) > 150:
            raise SystemExit("text check: %s line %d is %d columns (150 at most)" % (label, n, len(line)))


def edit_texts(eds):
    for e in eds:
        yield from (e[2] + e[3],) if e[0] == "ins" else (e[2],)


def texts_check(texts, news):
    for path, text in news.items():
        new_lines_check(path, text)
        if "\u2014" in text:
            raise SystemExit("text check: %s holds an em dash" % path)
    for path, eds in EDITS.items():
        if path in (CM, BS):
            continue
        for t in edit_texts(eds):
            new_lines_check(path + " (edited)", t)
    # log lines: every printf this patch adds starts "Glass light (r130g)"
    for path in (TC, PC):
        for t in edit_texts(EDITS[path]):
            for line in t.split("\n"):
                if "std::printf(" in line:
                    rest = line.split("std::printf(", 1)[1]
                    if not rest.lstrip().startswith('"Glass light (r130g)'):
                        raise SystemExit("text check: a log line does not start with Glass light (r130g): %s" % line.strip())
    allp = "".join(t for p in (TC, PC) for t in edit_texts(EDITS[p]))
    if allp.count("Glass light (r130g)") < 3:
        raise SystemExit("text check: too few Glass light (r130g) log lines")
    # the shared numbers C++ ties to
    lay = news[HS + "glass_light_forward_layout.h"]
    for want in ("GLASS_LAMP_CLEAR 0.02", "GLASS_RAY_FIRST 16u", "GLASS_RAY_SLOTS 9u"):
        if lay.count("#define " + want + "\n") != 1:
            raise SystemExit("text check: glass_light_forward_layout.h: %s" % want)
    # the shader: every edit is inside #ifdef GLASS (an inserted block); the counter is there
    for e in EDITS[SH]:
        body = "".join(edit_texts([e]))
        if e[0] != "ins" or not body.lstrip().startswith("#ifdef GLASS") or not body.rstrip().endswith("#endif"):
            raise SystemExit("text check: a shader edit is not a #ifdef GLASS block: %r" % e[1][:60])
    sh = "".join(edit_texts(EDITS[SH]))
    for want in ("glassCrossC(from, g_lo, to_c / len_c, g_hi, g_cast ? g_tmax : 0.0)", "atomicAdd(glass_n[0], g_asked)",
                 "atomicMin(glass_n[8], mm)", "half_counts.n[GLASS_RAY_FIRST + i]", "rayQueryGetIntersectionTEXT(glass, false)"):
        if sh.count(want) < 1 or (want != "half_counts.n[GLASS_RAY_FIRST + i]" and sh.count(want) != 1):
            raise SystemExit("text check: shader edit missing: %r" % want)
    cm = texts[CM]
    if cm.count("add_executable(glass-light-forward-test EXCLUDE_FROM_ALL ../tests/test_glass_light_forward.cpp)") != 1 or \
            cm.count("${SHADER_SRC}/glass_light_forward_layout.h") != 1:
        raise SystemExit("text check: CMakeLists.txt: the forward test or the layout include")
    if texts[BS].count("tests/test_glass_light_forward.cpp -o out/glass-light-forward-test") != 1 or \
            texts[BS].count("out/glass-light-forward-test\n") != 2:
        raise SystemExit("text check: build.sh does not build and run the forward test once")
    # off: the placed refusal changes only through GlassPlacedAllowed, whose first test is the mode; buffers keep their size
    tc, pc, rf, ph = texts[TC], texts[PC], texts[RF], texts[PH]
    if "if (glass_light_mode == 0 || hit == 0) {\n        return false;" not in tc:
        raise SystemExit("text check: GlassPlacedAllowed does not test the mode first")
    if rf.count("rt_shadow->GlassPlacedAllowed(draw.glass_entry)") != 1 or rf.count("draw.palette_placed &&") != 1:
        raise SystemExit("text check: the rasterizer's placed palette refusal")
    if pc.count("half_words = HalfSlots + (glass_mode ? GlassLight::RaySlots : 0u);") != 1 or "HalfSlots * sizeof(u32)" in pc:
        raise SystemExit("text check: vk_point_shadow.cpp still sizes a half counter buffer by HalfSlots")
    if ph.count("u32 half_words = 16;") != 1:
        raise SystemExit("text check: vk_point_shadow.h: half_words")
    if "GlassCode(glass_mode," in "".join(edit_texts(EDITS[PC])):
        raise SystemExit("text check: r130g must not touch r130c's GlassCode selection")
    # PrepareDraw: the steady test comes before r121b's judge; the carry conditions name the mode
    if tc.find("GlassPlacedSteady(draw.palette") < 0 or tc.find("GlassPlacedSteady(draw.palette") > tc.find("RtGlassStatic::Judge("):
        raise SystemExit("text check: the steady test comes after r121b's judge")
    for want in ("(glass_light_mode != 0 && entry.glass_light != 0)", "(glass_light_mode != 0 && !glass_drawn.empty())",
                 "RtGlassCarryOn() || glass_light_mode != 0"):
        if tc.count(want) != 1:
            raise SystemExit("text check: vk_rt_shadow.cpp: %r is there %d times" % (want, tc.count(want)))
    # README
    rows = [l for l in texts[R].split("\n") if l.startswith("| `BB_GLASS_LIGHT` (r130g) |")]
    if len(rows) != 1 or not rows[0].endswith("| off |"):
        raise SystemExit("text check: README row of r130g")
    # not these files
    for path in list(EDITS) + list(NEW):
        if "caustics" in path or "rt_cards" in path or "rt_glass_static" in path or "glass_light_layout" in path \
                or path.endswith("test_glass_light.cpp") or path.endswith("/glass_light.h"):
            raise SystemExit("text check: %s must not be touched by this patch" % path)


def state_of(cur, eds, path):
    done = todo = 0
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            parts = [t for t in (before, after) if t]
            na, counts = cur.count(anchor), [cur.count(t) for t in parts]
            if na == 1 and all(k == 1 for k in counts):
                done += 1
            elif na == 1 and all(k == 0 for k in counts):
                todo += 1
            else:
                raise SystemExit("REFUSED %s: anchor found %d times (wanted once), inserted texts %s times: %r"
                                 % (path, na, counts, anchor[:80]))
        else:
            _, old, new = e
            no, nn = cur.count(old), cur.count(new)
            if no == 1 and nn == 0:
                todo += 1
            elif no == 0 and nn == 1:
                done += 1
            else:
                raise SystemExit("REFUSED %s: old text found %d times, new text %d times (wanted 1/0 or 0/1): %r"
                                 % (path, no, nn, old[:80]))
    if done == len(eds):
        return "applied"
    if todo == len(eds):
        return "clean"
    raise SystemExit("%s: %d of %d edits applied" % (path, done, len(eds)))


def apply_text(cur, eds):
    for e in eds:
        if e[0] == "ins":
            _, anchor, before, after = e
            cur = cur.replace(anchor, before + anchor + after)
        else:
            cur = cur.replace(e[1], e[2])
    return cur


def revert_text(cur, eds):
    for e in reversed(eds):
        if e[0] == "ins":
            _, anchor, before, after = e
            for part in (after, before):
                if part:
                    cur = cur.replace(part, "", 1)
        else:
            cur = cur.replace(e[2], e[1])
    return cur


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R130G_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, NEED)):
        raise SystemExit("%s is missing: r130c_glass-lamp-light must be applied first" % NEED)
    plan = []
    for path in (SH, TH, TC, PH, PC, RF, CM, BS, R):
        raw, eol, cur = load(path)
        eds = edits_for(path, cur)
        plan.append((path, eds, raw, eol, cur, state_of(cur, eds, path)))
    new_plan = [(path, new_state(path)) for path in NEW]
    states = {p[5] for p in plan} | {s for _, s in new_plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan) + ", " +
                         ", ".join("%s %s" % p for p in new_plan))
    state = states.pop()

    def applied_texts():
        out = {}
        for path, eds, raw, eol, cur, _ in plan:
            cur = apply_text(cur, eds)
            if state_of(cur, eds, path) != "applied":
                raise SystemExit("%s: the result does not read as applied" % path)
            out[path] = cur
        return out

    def all_checks(texts):
        texts_check(texts, NEW)

    if cmd == "check":
        if state == "applied":
            all_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            all_checks(applied_texts())
            print("not applied; would apply (%d files edited, %d edits, %d new files; text checks on the result pass)"
                  % (len(plan), sum(len(p[1]) for p in plan), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied"); return
        texts = applied_texts()
        all_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, eds, raw, eol, cur, _ in plan:
            open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        writes = [(os.path.join(ROOT, path), texts[path].replace("\n", eol).encode("utf-8")) for path, eds, raw, eol, cur, _ in plan]
        writes += [(os.path.join(ROOT, path), text.replace("\n", "\r\n").encode("utf-8")) for path, text in NEW.items()]
        for full, data in writes:
            open(full + ".r130gtmp", "wb").write(data)
        for full, data in writes:
            os.replace(full + ".r130gtmp", full)
        print("applied"); return
    if state != "applied":
        print("nothing to revert"); return
    out = {}
    for path, eds, raw, eol, cur, _ in plan:
        cur = revert_text(cur, eds)
        if state_of(cur, eds, path) != "clean":
            raise SystemExit("%s: the revert does not read as clean; nothing written" % path)
        out[path] = cur.replace("\n", eol).encode("utf-8")
    for path, eds, raw, eol, cur, _ in plan:
        full = os.path.join(ROOT, path)
        open(full + ".r130gtmp", "wb").write(out[path])
        os.replace(full + ".r130gtmp", full)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
