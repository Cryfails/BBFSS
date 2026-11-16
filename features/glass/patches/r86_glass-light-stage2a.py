# r86_glass-light-stage2a (fixed, reviewed 2026-11-15 evening): FEATURE patch (glass, water and
# caustics, branch visual/glass-water), the EXPERIMENT part of stage 2a. The ray traced sun's ray,
# where it reaches the sun, asks the window panes (r83's instance mask 0x10) along the sun's
# direction, counts what it meets, and can show the shape of the light a window lets through. NO
# COLOUR YET: carrying a colour into the game's sun light and reading the pane texture at a ray hit
# each need a patch of their own and a choice by the owner (see bbfss-ctx-glass-water-caustics.md,
# sections of 2026-11-15 r86). Off by default.
#
# Why this first: the owner wants window-shaped coloured light on floors from the sun and lamps
# (2026-11-15). Reading the tree for it found (1) the sun's answer is one 8-bit visibility per pixel
# that the filter writes into the alpha of the game's screen shadow target, which the game's sun
# shader (d92266b9) reads per channel as a*u + (1-u); (2) panes have no UV records, no card slot
# and no colour layer (cards have alpha layers only); (3) the panes are drawn FORWARD, after the
# sun's trace and the lamp pass. RtShadow builds a frame's captures only when a reader of the scene
# asks (PrepareScene, the contact shadow hook); OnFrameEnd drops the captures still waiting (the
# entry is captured again at its next draw) and forgets the frame's entries. So a pane captured
# after the last reader never gets a BLAS (Entry::blas stays false), and no traced scene of any
# frame holds it: with r83 alone the panes are in no ray's scene. This patch makes the one part
# every later choice needs: the panes built and in the sun's scene (carried from the frame before)
# and the bounded second ray; its counts and view decide what the colour stage must do.
#
# What (BB_RT_GLASS_LIGHT, environment only, read once; renderer_vulkan/rt_glass_light.h; needs
# BB_RT_GLASS on, else off):
# 1. unset, empty, "0" or other text: off. Nothing changes: no new pipeline, the trace pipelines
#    are made from the builds of before (their SPIR-V byte for byte as before), the counters, the
#    captures and the records as before, no carry, no build at the frame end.
# 2. "1": the sun trace pipelines (full and half resolution) are made from the GLASS_LIGHT builds
#    of rt_shadow.comp. At the frame end, while a pane's capture waits (and the scene is wanted),
#    RtShadow builds the frame's waiting captures (RecordBuilds, as a late reader's PrepareScene
#    does with BB_LAMP_FOG_SHAFTS), keeps the keys of the pane entries drawn in the frame
#    (PrepareDraw), and CollectHeld adds those drawn last frame and not yet this frame that have a
#    BLAS to the scene (a record under RtGlassMask alone, never the sun's held mask). While the TLAS
#    last written holds a pane record (glass_instances), r25_flags carries RT_GLASS_LIGHT_PANES and
#    a pixel whose ray(s) reached the sun traces one more ray along the sun's direction at mask 0x10
#    alone, every pane triangle a candidate (gl_RayFlagsNoOpaqueEXT), at most RT_GLASS_LIGHT_CAP (4)
#    candidates, then the query ends. A half-resolution second-pass pixel that takes the first
#    pass's answer asks nothing (it takes that answer). The picture is as before; on the counted
#    sun traces (one in 8, as r25's) it counts.
# 3. "view": as 1, and such a pixel keeps half its sun per pane candidate (visibility * 2^-n, a
#    pane drawn with both faces counts twice): the window's shape of light shows as a darker patch
#    in the sunlight. A debug look, not the feature.
# 4. "probe": as 1, and on the counted sun traces a pixel whose ray was blocked also asks whether a
#    pane lies where its nearest sun caster is (2 cm + 0.2 %): the pane's own copy in the sun's
#    scene (a sun shadow pass draw of the same mesh, as e30b0480's meshes at the dream house) would
#    stop all light through that window.
# 5. Log: once, at the ray tracing start, when the variable is set: "Ray tracing glass light
#    (r86): ...". Every 600 sun traces with r25's line, a short line (the slot runs keep 300
#    characters of a line; "^Ray tracing glass" is in their evidence pattern): the pane records in
#    the scene last written (and of them the carried ones), the frames whose captures were built at
#    the frame end since the last line, then per counted sun trace: sun-lit pixels asked, crossing
#    a pane, pane candidates, stopped at the cap, blocked pixels tested, blocked at a pane. README row.
#
# Cost: off: one test of a function-static bool per pane draw and one at the frame end, an empty
# loop per CollectHeld, the r25 flags OR'd with 0, one mask test per TLAS record; no GPU work.
# On (NOT MEASURED): one ray query per sun-lit pixel while panes are in the scene, against the few
# pane instances only (mask 0x10), at most 4 candidates; inside the existing GPU profile row
# "Lighting: ray traced sun" (EffectPass::Mark 14): cost = that row with "1" minus that row with
# the knob off in one normal run each. The frame-end build costs a pane's BLAS build when its entry
# is captured (its first draw, then when it is rebuilt), as the other captures' builds; it lands
# in the profile row of the pass recorded before it. "probe" adds two short queries per shadowed
# pixel on counted sun traces (not a cost figure). Counters: 6 words more (88 bytes instead of 64).
#
# Not changed here: the game's sun shader, the filter, the screen shadow target's R, G, B, the lamp
# rays (point_shadow_ray.comp), the bounce (its GLASS_SCENE build already leaves 0x10 out), r83's
# pane capture. The carried panes are traced by every ray of the frame that traces 0x10: only this.
#
# Review of the draft (2026-11-15 evening), fixed here:
# A. The draft carried pane entries by key but their captures were never built (OnFrameEnd drops
#    captures no reader took, so Entry::blas stayed false and CollectHeld skipped every pane): the
#    experiment would have printed "panes in the scene 0" at the dream house and been read as "the
#    sun's rays cross no pane". Fix: the frame-end build above (RtShadow::OnFrameEnd).
# B. The log lines began "Ray traced sun glass light", which the slot workers' evidence pattern does
#    not catch, and the periodic line put its numbers past the 300 characters the slots keep. Now
#    "Ray tracing glass light (r86): ..." and a short line.
# C. The CMakeLists.txt include rule was anchored after r81's volumetric rule (another feature's
#    neighbourhood, between r81 and r95/r94); it is now anchored on r83's own glass include line.
# D. Root default: <tree> (was the current directory). README row states the exact rule
#    (triangles as candidates, half resolution, the frame-end build).
#
# Files: renderer_vulkan/rt_glass_light.h (new), host_shaders/rt_glass_light_layout.h (new),
# host_shaders/rt_shadow.comp, renderer_vulkan/vk_rt_shadow.cpp, vk_rt_shadow.h,
# engine/gpu/CMakeLists.txt, README.md. Needs r83 (+ r83b, r83c) in the tree.
#
# Use: python -I -X utf8 r86_glass-light-stage2a.fixed.py check | apply | revert (root from
# R86_ROOT, else <tree>). Files keep their line ends (CRLF in the tree); new files are written
# CRLF. Originals are kept in r86_backup/ next to this script with their sha256 and the patched
# files' sha256 (manifest.txt); revert takes the edits back out and says per file whether the
# result is the original byte for byte (sha256); new files are removed only when they are as this
# script writes them. Exit 0 done or nothing to do, 1 refused (mixed state, anchors), 2 usage.
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r86_backup")
ROOT = os.environ.get("R86_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    H + "rt_glass_light_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT's numbers, shared by rt_shadow.comp's
// GLASS_LIGHT builds and renderer_vulkan/rt_glass_light.h. Plain #define lines only, as
// rt_glass_layout.h: GLSL includes this file and C++ includes it as it is.
#ifndef RT_GLASS_LIGHT_LAYOUT_H
#define RT_GLASS_LIGHT_LAYOUT_H

// r25_flags bits of the sun trace, above r25's own (1, 2, 4, 8).
#define RT_GLASS_LIGHT_PANES 16u // panes are in the scene: sun-lit pixels ask them
#define RT_GLASS_LIGHT_VIEW 32u  // such a pixel keeps half its sun per pane candidate
#define RT_GLASS_LIGHT_PROBE 64u // counted frames: is a shadowed pixel's blocker a pane?
// Pane candidates (triangles) a ray takes at most.
#define RT_GLASS_LIGHT_CAP 4u
// The counters: words 16 to 21 of the sun trace's counters (r25_buf).
#define RT_GLASS_LIGHT_FIRST_WORD 16u
#define RT_GLASS_LIGHT_WORDS 6u

#endif
''',
    R + "rt_glass_light.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86_glass-light-stage2a): sunlight through window panes, its first part
// (BB_RT_GLASS_LIGHT). No Vulkan here.
//
// r83 (BB_RT_GLASS) put the game's forward window pane draws into the ray traced scene under
// RtGlassMask (0x10) alone, which no ray traced. The game draws them after the sun's trace and the
// lamp pass; RtShadow builds captures only for a reader of the scene and forgets a frame's entries
// at its end. So with this knob on RtShadow builds the waiting captures at the frame end while a
// pane's is among them, and carries the panes drawn in a frame into the next frame's scene
// (CollectHeld). Where the sun's ray reaches the sun, a second ray asks the panes (rt_shadow.comp,
// GLASS_LIGHT builds): every pane triangle a candidate, at most RtGlassLightCap. No colour yet:
// "1" counts, "view" shows the window's shape of light (half the sun per candidate), "probe" also
// asks whether a shadowed pixel's blocker is a pane's own copy in the sun's scene.

#include <cstddef>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/rt_glass_light_layout.h"
#include "rt_glass.h"

namespace Vulkan {

enum class RtGlassLightMode : std::uint32_t { Off = 0, Count = 1, View = 2, Probe = 3 };

constexpr bool RtGlassLightSame(const char* a, const char* b) {
    std::size_t i = 0;
    while (a[i] != '\0' && a[i] == b[i]) {
        ++i;
    }
    return a[i] == b[i];
}

/// BB_RT_GLASS_LIGHT's text: "1" Count, "view" View, "probe" Probe; anything else (unset, empty,
/// "0") Off.
constexpr RtGlassLightMode ParseRtGlassLight(const char* text) {
    return !text                             ? RtGlassLightMode::Off
           : RtGlassLightSame(text, "1")     ? RtGlassLightMode::Count
           : RtGlassLightSame(text, "view")  ? RtGlassLightMode::View
           : RtGlassLightSame(text, "probe") ? RtGlassLightMode::Probe
                                             : RtGlassLightMode::Off;
}
static_assert(ParseRtGlassLight("1") == RtGlassLightMode::Count);
static_assert(ParseRtGlassLight("view") == RtGlassLightMode::View);
static_assert(ParseRtGlassLight("probe") == RtGlassLightMode::Probe);
static_assert(ParseRtGlassLight("0") == RtGlassLightMode::Off && ParseRtGlassLight("") == RtGlassLightMode::Off);
static_assert(ParseRtGlassLight("2") == RtGlassLightMode::Off && ParseRtGlassLight("views") == RtGlassLightMode::Off);
static_assert(ParseRtGlassLight(nullptr) == RtGlassLightMode::Off);

/// The sun trace's r25_flags bits (rt_glass_light_layout.h), above r25's 1, 2, 4 and 8.
inline constexpr std::uint32_t RtGlassLightPanes = RT_GLASS_LIGHT_PANES;
inline constexpr std::uint32_t RtGlassLightView = RT_GLASS_LIGHT_VIEW;
inline constexpr std::uint32_t RtGlassLightProbe = RT_GLASS_LIGHT_PROBE;
static_assert(((RtGlassLightPanes | RtGlassLightView | RtGlassLightProbe) & 15u) == 0);
inline constexpr std::uint32_t RtGlassLightCap = RT_GLASS_LIGHT_CAP;
inline constexpr std::uint32_t RtGlassLightFirstWord = RT_GLASS_LIGHT_FIRST_WORD;
inline constexpr std::uint32_t RtGlassLightWords = RT_GLASS_LIGHT_WORDS;
/// The sun trace's counters with the knob on (r25's 16 words, then these).
inline constexpr std::uint32_t RtGlassLightCounterWords = RtGlassLightFirstWord + RtGlassLightWords;

/// A sun trace's r25_flags bits: none when off or when no pane is in the scene.
constexpr std::uint32_t RtGlassLightFlags(RtGlassLightMode mode, bool panes) {
    return mode == RtGlassLightMode::Off || !panes
               ? 0u
               : RtGlassLightPanes | (mode == RtGlassLightMode::View ? RtGlassLightView : 0u) |
                     (mode == RtGlassLightMode::Probe ? RtGlassLightProbe : 0u);
}
static_assert(RtGlassLightFlags(RtGlassLightMode::Off, true) == 0);
static_assert(RtGlassLightFlags(RtGlassLightMode::View, false) == 0);
static_assert(RtGlassLightFlags(RtGlassLightMode::Count, true) == RtGlassLightPanes);
static_assert(RtGlassLightFlags(RtGlassLightMode::View, true) == (RtGlassLightPanes | RtGlassLightView));
static_assert(RtGlassLightFlags(RtGlassLightMode::Probe, true) == (RtGlassLightPanes | RtGlassLightProbe));

constexpr const char* RtGlassLightName(RtGlassLightMode mode) {
    return mode == RtGlassLightMode::Count  ? "1"
           : mode == RtGlassLightMode::View  ? "view"
           : mode == RtGlassLightMode::Probe ? "probe"
                                             : "off";
}

/// The knob, read once; off while BB_RT_GLASS is off (no pane is in the scene then).
inline RtGlassLightMode RtGlassLight() {
    static const RtGlassLightMode mode =
        RtGlassOn() ? ParseRtGlassLight(std::getenv("BB_RT_GLASS_LIGHT")) : RtGlassLightMode::Off;
    return mode;
}

inline bool RtGlassLightOn() {
    return RtGlassLight() != RtGlassLightMode::Off;
}

} // namespace Vulkan
''',
}

EDITS = {
    H + "rt_shadow.comp": [
        (r'''#extension GL_EXT_ray_query : require

layout(local_size_x = 8, local_size_y = 8) in;
''', r'''#extension GL_EXT_ray_query : require
#ifdef GLASS_LIGHT
// bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT (renderer_vulkan/rt_glass_light.h): the
// builds whose sun-lit pixels also ask the window panes (r83's instance mask RT_GLASS_MASK).
#extension GL_GOOGLE_include_directive : require
#include "rt_glass_layout.h"
#include "rt_glass_light_layout.h"
#ifndef COVERAGE_SKIP
#error "GLASS_LIGHT needs COVERAGE_SKIP (its r25_flags and counters)"
#endif
#endif

layout(local_size_x = 8, local_size_y = 8) in;
'''),
        (r'''           CLS_FILL_RAY = 5u, CLS_FILL_TAKEN = 6u, CLS_FIRST_PASS = 7u;
''', r'''           CLS_FILL_RAY = 5u, CLS_FILL_TAKEN = 6u, CLS_FIRST_PASS = 7u;

#ifdef GLASS_LIGHT
// bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT, with BB_RT_GLASS's panes in the scene
// (r83: RT_GLASS_MASK alone). r25_flags bits (rt_glass_light_layout.h): RT_GLASS_LIGHT_PANES,
// panes are in this frame's scene, so a pixel whose ray(s) reached the sun asks them along the
// sun's direction (one more ray query, only there); RT_GLASS_LIGHT_VIEW, such a pixel keeps half
// its sun per pane candidate (a debug look of the patch of light a window lets through: shape
// only, no colour yet); RT_GLASS_LIGHT_PROBE, on the counted frames a pixel whose ray was blocked
// asks whether a pane lies where its nearest blocker is (the pane's own copy in the sun's scene).
// Counters (counted frames only, r25_buf words RT_GLASS_LIGHT_FIRST_WORD + 0 to 5): sun-lit pixels
// asked, of them crossing a pane, pane candidates, rays stopped at the cap, blocked pixels tested,
// of them blocked at a pane.
shared uint r86_n[RT_GLASS_LIGHT_WORDS];

// The pane candidates along a ray, at most RT_GLASS_LIGHT_CAP (then the query ends). Not sorted:
// transmissions multiply, so the order does not count below the cap. The panes' BLAS are built
// opaque; the ray flag makes each triangle a candidate, none is confirmed.
uint r86Panes(vec3 origin, float tmin, vec3 dir, float tmax) {
    rayQueryEXT query;
    rayQueryInitializeEXT(query, scene, gl_RayFlagsNoOpaqueEXT, RT_GLASS_MASK, origin, tmin, dir, tmax);
    uint n = 0u;
    while (rayQueryProceedEXT(query)) {
        if (rayQueryGetIntersectionTypeEXT(query, false) == gl_RayQueryCandidateIntersectionTriangleEXT &&
            ++n >= RT_GLASS_LIGHT_CAP) {
            rayQueryTerminateEXT(query);
        }
    }
    return n;
}

// RT_GLASS_LIGHT_PROBE: whether a pane lies where the nearest sun caster (mask 0x01) on the way
// is, within 2 cm plus 0.2 % of its distance.
bool r86BlockedAtPane(vec3 origin, float tmin, vec3 dir, float tmax) {
    rayQueryEXT query;
    rayQueryInitializeEXT(query, scene, gl_RayFlagsOpaqueEXT, 0x01u, origin, tmin, dir, tmax);
    rayQueryProceedEXT(query);
    if (rayQueryGetIntersectionTypeEXT(query, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
        return false;
    }
    const float t = rayQueryGetIntersectionTEXT(query, true);
    const float eps = 0.02 + 0.002 * t;
    return r86Panes(origin, max(tmin, t - eps), dir, t + eps) != 0u;
}
#endif
'''),
        (r'''    imageStore(raw_img, pixel, vec4(float(lit) * radius_scale));
    return fill ? CLS_FILL_RAY : CLS_RAY;
''', r'''#ifdef GLASS_LIGHT
    // bbport (r86_glass-light-stage2a): the panes along the sun's direction, where it was reached
    float vis = float(lit) * radius_scale;
    if ((r25_flags & RT_GLASS_LIGHT_PANES) != 0u) {
        const bool counted = (r25_flags & R25_COUNT) != 0u;
        if (lit != 0u) {
            const uint panes = r86Panes(origin, reach * 0.5, dir, max_distance);
            if (counted) {
                atomicAdd(r86_n[0], 1u);
                if (panes != 0u) {
                    atomicAdd(r86_n[1], 1u);
                    atomicAdd(r86_n[2], panes);
                }
                if (panes >= RT_GLASS_LIGHT_CAP) {
                    atomicAdd(r86_n[3], 1u);
                }
            }
            if ((r25_flags & RT_GLASS_LIGHT_VIEW) != 0u) {
                vis *= exp2(-float(panes));
            }
        } else if (counted && (r25_flags & RT_GLASS_LIGHT_PROBE) != 0u) {
            atomicAdd(r86_n[4], 1u);
            if (r86BlockedAtPane(origin, reach * 0.5, dir, max_distance)) {
                atomicAdd(r86_n[5], 1u);
            }
        }
    }
    imageStore(raw_img, pixel, vec4(vis));
#else
    imageStore(raw_img, pixel, vec4(float(lit) * radius_scale));
#endif
    return fill ? CLS_FILL_RAY : CLS_RAY;
'''),
        (r'''    if (count && gl_LocalInvocationIndex < 7u) {
        r25_n[gl_LocalInvocationIndex] = 0u;
    }
    barrier();
''', r'''    if (count && gl_LocalInvocationIndex < 7u) {
        r25_n[gl_LocalInvocationIndex] = 0u;
    }
#ifdef GLASS_LIGHT
    if (count && gl_LocalInvocationIndex < RT_GLASS_LIGHT_WORDS) { // bbport (r86_glass-light-stage2a)
        r86_n[gl_LocalInvocationIndex] = 0u;
    }
#endif
    barrier();
'''),
        (r'''    if (count) {
        R25Count(cls);
    }
}
#else
''', r'''    if (count) {
        R25Count(cls);
#ifdef GLASS_LIGHT
        // bbport (r86_glass-light-stage2a): R25Count's barrier made the group's counts whole
        if (gl_LocalInvocationIndex < RT_GLASS_LIGHT_WORDS && r86_n[gl_LocalInvocationIndex] != 0u) {
            atomicAdd(r25_buf.n[RT_GLASS_LIGHT_FIRST_WORD + gl_LocalInvocationIndex],
                      r86_n[gl_LocalInvocationIndex]);
        }
#endif
    }
}
#else
'''),
    ],
    R + "vk_rt_shadow.h": [
        (r'''#include "video_core/renderer_vulkan/rt_glass.h"       // bbport (r83_glass-water-stage1)
''', r'''#include "video_core/renderer_vulkan/rt_glass.h"       // bbport (r83_glass-water-stage1)
#include "video_core/renderer_vulkan/rt_glass_light.h" // bbport (r86_glass-light-stage2a)
'''),
        (r'''    static constexpr u32 R25Slots = 16;
''', r'''    static constexpr u32 R25Slots = 16;
    // bbport (r86_glass-light-stage2a): with BB_RT_GLASS_LIGHT on the counters hold
    // RtGlassLightWords words more, from RtGlassLightFirstWord (rt_shadow.comp's GLASS_LIGHT
    // builds)
    static_assert(RtGlassLightFirstWord >= R25Slots);
    static u32 R25Words() {
        return RtGlassLightOn() ? RtGlassLightCounterWords : R25Slots;
    }
'''),
        (r'''    u32 card_lamp_instances = 0, card_lamp_plants = 0, card_lamp_moving = 0;
''', r'''    u32 card_lamp_instances = 0, card_lamp_plants = 0, card_lamp_moving = 0;
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT: the window pane records in the TLAS last
    // written (and of them those carried from the frame before), the frames whose waiting captures
    // OnFrameEnd built for a pane since the last line, the keys (of `entries`) of the pane entries
    // drawn this frame and of those drawn last frame (CollectHeld carries them into the scene), and
    // the counters' values at Record's last line
    u32 glass_instances = 0, glass_carried = 0, glass_late = 0;
    std::vector<u64> glass_drawn, glass_carry;
    std::array<u32, RtGlassLightWords> r86_last{};
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
''', r'''#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_glass_comp.h"      // bbport (r86_glass-light-stage2a)
#include "video_core/host_shaders/rt_shadow_half_glass_comp.h" // bbport (r86_glass-light-stage2a)
'''),
        (r'''                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));
        }
''', r'''                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));
        }
        // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT's state (rt_glass_light.h), said once
        // when the variable is set
        if (const char* text = std::getenv("BB_RT_GLASS_LIGHT");
            text && text[0] && !(text[0] == '0' && text[1] == '\0')) {
            const RtGlassLightMode light = RtGlassLight();
            if (light != RtGlassLightMode::Off) {
                std::printf("Ray tracing glass light (r86): BB_RT_GLASS_LIGHT=%s: %s; where a "
                            "pixel's sun ray reaches the sun, one more ray asks the window panes "
                            "(instance mask 0x%x alone, at most %u triangles), only while panes are "
                            "in the scene; a frame's pane captures are built at its end and its "
                            "panes are carried into the next frame's scene\n",
                            RtGlassLightName(light),
                            light == RtGlassLightMode::View
                                ? "the view, half the sun per pane triangle crossed (a debug "
                                  "look, no colour)"
                            : light == RtGlassLightMode::Probe
                                ? "the picture is as before; counted frames also ask whether a "
                                  "shadowed pixel's blocker is a pane's own copy in the sun's scene"
                                : "the picture is as before (counted only)",
                            unsigned(RtGlassMask), unsigned(RtGlassLightCap));
            } else {
                std::printf("Ray tracing glass light (r86): BB_RT_GLASS_LIGHT=%.40s off (%s)\n",
                            text,
                            ParseRtGlassLight(text) == RtGlassLightMode::Off
                                ? "not understood: 1, view or probe"
                                : "it needs BB_RT_GLASS on");
            }
        }
'''),
        (r'''                               sizeof(TracePush), RT_SHADOW_HALF_COMP,
''', r'''                               // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the
                               // build that also asks the panes (same bindings and push constants)
                               sizeof(TracePush),
                               RtGlassLightOn() ? std::span<const u32>{RT_SHADOW_HALF_GLASS_COMP}
                                                : std::span<const u32>{RT_SHADOW_HALF_COMP},
'''),
        (r'''                            sizeof(TracePush), RT_SHADOW_COVERAGE_COMP, "Ray traced shadows") ||
''', r'''                            // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the build
                            // that also asks the panes (same bindings and push constants)
                            sizeof(TracePush),
                            RtGlassLightOn() ? std::span<const u32>{RT_SHADOW_GLASS_COMP}
                                             : std::span<const u32>{RT_SHADOW_COVERAGE_COMP},
                            "Ray traced shadows") ||
'''),
        (r'''    if (!Make(r25_counts, R25Slots * sizeof(u32), false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                  VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(r25_readback, R25Slots * sizeof(u32), true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !r25_readback.mapped) {
        return false;
    }
    std::memset(r25_readback.mapped, 0, R25Slots * sizeof(u32));
''', r'''    // bbport (r86_glass-light-stage2a): R25Words: R25Slots, or more with BB_RT_GLASS_LIGHT on
    if (!Make(r25_counts, R25Words() * sizeof(u32), false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                  VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(r25_readback, R25Words() * sizeof(u32), true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !r25_readback.mapped) {
        return false;
    }
    std::memset(r25_readback.mapped, 0, R25Words() * sizeof(u32));
'''),
        (r'''void RtShadow::CollectHeld() {
    held_now.clear();
    for (Entry* entry : held) {
        if (entry->seen_frame != frame && Holds(*entry)) {
            held_now.push_back(entry);
        }
    }
}
''', r'''void RtShadow::CollectHeld() {
    held_now.clear();
    for (Entry* entry : held) {
        if (entry->seen_frame != frame && Holds(*entry)) {
            held_now.push_back(entry);
        }
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the window panes drawn last frame and
    // not yet this frame, with a BLAS (built at that frame's end, OnFrameEnd). The game draws them
    // forward, after the sun's trace and the lamp pass, and the frame's entries are forgotten at
    // its end: without this no traced scene holds a pane. Their records keep RtGlassMask alone
    // (PrepareScene). Off: glass_carry stays empty.
    for (const u64 key : glass_carry) {
        const auto it = entries.find(key);
        if (it != entries.end() && it->second && it->second->blas &&
            it->second->seen_frame != frame && RtGlassEntry(it->second->mask)) {
            held_now.push_back(it->second.get());
        }
    }
}
'''),
        (r'''    if (draw.glass) { // bbport (r83_glass-water-stage1): for the log
        NoteGlassDraw(entry);
    }
''', r'''    if (draw.glass) { // bbport (r83_glass-water-stage1): for the log
        NoteGlassDraw(entry);
        if (RtGlassLightOn()) { // bbport (r86_glass-light-stage2a): carried into the next frame
            glass_drawn.push_back(entry_key);
        }
    }
'''),
        (r'''    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
''', r'''    u32 lamp_cards = 0, lamp_plants = 0, lamp_moving = 0, lamp_flips = 0;
    u32 glass_records = 0, glass_records_carried = 0; // bbport (r86_glass-light-stage2a)
'''),
        (r'''        const u8 mask =
            kept ? ShadowMask
                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
''', r'''        // bbport (r86_glass-light-stage2a): a window pane carried from the frame before
        // (CollectHeld, BB_RT_GLASS_LIGHT) is not held for the sun: its own mask, RtGlassMask
        const u8 mask =
            kept && !RtGlassEntry(entry->mask)
                ? ShadowMask
                : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
'''),
        (r'''        out[built++] = record;
''', r'''        out[built++] = record;
        // bbport (r86_glass-light-stage2a): the pane records (Record asks them only while one is
        // in)
        if (RtGlassEntry(static_cast<u8>(record.mask))) {
            ++glass_records;
            glass_records_carried += kept ? 1 : 0;
        }
'''),
        (r'''    card_lamp_instances = lamp_cards;
''', r'''    card_lamp_instances = lamp_cards;
    glass_instances = glass_records; // bbport (r86_glass-light-stage2a)
    glass_carried = glass_records_carried;
'''),
        (r'''                    d[13]);
        r25_frames = 0;
''', r'''                    d[13]);
        // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: its counters, means per counted
        // frame as r25's (u32 differences survive the wrap); a short line, the slot runs keep 300
        // characters of a line
        if (RtGlassLightOn()) {
            std::array<u32, RtGlassLightWords> got{};
            std::memcpy(got.data(),
                        static_cast<const u32*>(r25_readback.mapped) + RtGlassLightFirstWord,
                        sizeof(got));
            std::array<double, RtGlassLightWords> m{};
            for (u32 i = 0; i < RtGlassLightWords && counted != 0; ++i) {
                m[i] = double(u32(got[i] - r86_last[i])) / double(counted);
            }
            r86_last = got;
            std::printf("Ray tracing glass light (r86): %s; panes in the scene %u (carried %u), "
                        "built at a frame end in %u frames; a counted frame (%u): sun-lit asked "
                        "%.0f, crossing a pane %.0f, pane hits %.0f, at the cap %.0f; shadowed "
                        "tested %.0f, blocked at a pane %.0f\n",
                        RtGlassLightName(RtGlassLight()), glass_instances, glass_carried,
                        glass_late, counted, m[0], m[1], m[2], m[3], m[4], m[5]);
            glass_late = 0;
        }
        r25_frames = 0;
'''),
        (r'''    const u32 r25_flags =
        (r25_exact ? R25Exact : 0u) | ((r25_recorded++ & 7) == 0 ? R25Count : 0u);
''', r'''    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on and a pane in the TLAS: its bits
    // (rt_glass_light.h); off, or no pane: 0, the flags of before
    const u32 r25_flags =
        (r25_exact ? R25Exact : 0u) | ((r25_recorded++ & 7) == 0 ? R25Count : 0u) |
        RtGlassLightFlags(RtGlassLight(), glass_instances != 0);
'''),
        (r'''                const vk::BufferCopy region{0, 0, R25Slots * sizeof(u32)};
''', r'''                const vk::BufferCopy region{0, 0, R25Words() * sizeof(u32)}; // (r86)
'''),
        (r'''void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
    }
''', r'''void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
    }
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the game draws the window panes after
    // the frame's last reader of the scene (forward, after the sun's trace and the lamp pass), so
    // their captures would be dropped below (an entry is captured again at its next draw) and no
    // pane ever got a BLAS. While a pane's capture waits and the scene is wanted, the frame's
    // waiting captures are built here, as a later reader's PrepareScene builds them (with
    // BB_LAMP_FOG_SHAFTS), and CollectHeld carries the panes into the next frame's scene. Off:
    // nothing here.
    if (RtGlassLightOn() && need_scene &&
        std::ranges::any_of(builds, [](const Build& b) {
            return !b.probe && !b.left_out && b.entry && RtGlassEntry(b.entry->mask);
        })) {
        scheduler.EndRendering();
        RecordBuilds();
        ++glass_late;
    }
'''),
        (r'''    tlas_count = 0;
    frame_entries.clear();
''', r'''    tlas_count = 0;
    frame_entries.clear();
    // bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: this frame's pane keys, each once,
    // for the next frame's scene (CollectHeld). Off: both lists stay empty.
    if (RtGlassLightOn()) {
        glass_carry.swap(glass_drawn);
        glass_drawn.clear();
        std::ranges::sort(glass_carry);
        const auto twice = std::ranges::unique(glass_carry);
        glass_carry.erase(twice.begin(), twice.end());
    }
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''        # bbport (r83_glass-water-stage1): the gather's GLASS_SCENE build includes the panes' mask
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h)
    endif()
''', r'''        # bbport (r83_glass-water-stage1): the gather's GLASS_SCENE build includes the panes' mask
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h)
    endif()
    # bbport (r86_glass-light-stage2a): the sun trace's GLASS_LIGHT builds include the panes' mask
    if (FILENAME MATCHES "^rt_shadow\\.comp$")
        list(APPEND INCLUDES ${SHADER_SRC}/rt_glass_layout.h ${SHADER_SRC}/rt_glass_light_layout.h)
    endif()
'''),
        (r'''add_host_shader(rt_shadow.comp rt_shadow_half_comp COVERAGE_SKIP=1 HALF=1)
''', r'''add_host_shader(rt_shadow.comp rt_shadow_half_comp COVERAGE_SKIP=1 HALF=1)
# bbport (r86_glass-light-stage2a): BB_RT_GLASS_LIGHT on: the sun trace's builds that also ask the
# window panes (rt_glass_light.h); the builds above are unchanged.
add_host_shader(rt_shadow.comp rt_shadow_glass_comp COVERAGE_SKIP=1 GLASS_LIGHT=1)
add_host_shader(rt_shadow.comp rt_shadow_half_glass_comp COVERAGE_SKIP=1 HALF=1 GLASS_LIGHT=1)
'''),
    ],
    "README.md": [
        (r'''it can be missing for a moment while that pipeline compiles. Any other text is off | off |
''', r'''it can be missing for a moment while that pipeline compiles. Any other text is off | off |
| `BB_RT_GLASS_LIGHT` | Needs `BB_RT_GLASS` on and the ray traced sun (full or half resolution). The first part of sunlight through window panes: the panes' captures of a frame are built at its end and the panes are kept in the next frame's ray traced scene (the game draws them after the sun's trace); while a pane is in that scene, a pixel whose sun ray reaches the sun sends one more ray along the sun's direction that meets only pane triangles, at most 4 of them (a half-resolution pixel that takes the first pass's answer sends none). `1` counts only: the picture stays the same; every 600 sun traces a log line gives the pane records in the scene and, for the sun traces that count (one in 8), the pixels asked, crossing a pane and the triangles met. `view` also gives such a pixel half its sun per pane triangle met: the shape of the light a window lets through shows darker (a debug look, no colour yet). `probe` is `1`, and in the counted sun traces a pixel in the sun's shadow also asks whether a pane lies within 2 cm + 0.2 % of its nearest sun caster (a pane's own copy in the sun's scene). Any other text is off | off |
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "rt_shadow.comp": [("#ifdef GLASS_LIGHT", 5), ("uint r86Panes(", 1), ("bool r86BlockedAtPane(", 1),
                           ("imageStore(raw_img, pixel, vec4(float(lit) * radius_scale));", 2),
                           ("imageStore(raw_img, pixel, vec4(vis));", 1),
                           ("gl_RayFlagsNoOpaqueEXT, RT_GLASS_MASK", 1)],
    R + "vk_rt_shadow.h": [('#include "video_core/renderer_vulkan/rt_glass_light.h"', 1),
                           ("static u32 R25Words() {", 1),
                           ("u32 glass_instances = 0, glass_carried = 0, glass_late = 0;", 1),
                           ("std::vector<u64> glass_drawn, glass_carry;", 1)],
    R + "vk_rt_shadow.cpp": [("std::span<const u32>{RT_SHADOW_GLASS_COMP}", 1),
                             ("std::span<const u32>{RT_SHADOW_HALF_GLASS_COMP}", 1),
                             ('#include "video_core/host_shaders/rt_shadow_glass_comp.h"', 1),
                             ('#include "video_core/host_shaders/rt_shadow_half_glass_comp.h"', 1),
                             ("R25Slots * sizeof(u32)", 0), ("R25Words() * sizeof(u32)", 4),
                             ("for (const u64 key : glass_carry) {", 1), ("glass_drawn.push_back(entry_key);", 1),
                             ("kept && !RtGlassEntry(entry->mask)", 1), ("++glass_records;", 1),
                             ("glass_instances = glass_records;", 1),
                             ("RtGlassLightFlags(RtGlassLight(), glass_instances != 0);", 1),
                             ("glass_carry.swap(glass_drawn);", 1), ('std::getenv("BB_RT_GLASS_LIGHT")', 1),
                             ("RecordBuilds();\n        ++glass_late;", 1), ("glass_late = 0;", 1),
                             ("Ray traced sun glass light", 0), ("Ray tracing glass light (r86): ", 3)],
    "engine/gpu/CMakeLists.txt": [("rt_shadow_glass_comp COVERAGE_SKIP=1 GLASS_LIGHT=1", 1),
                                  ("rt_shadow_half_glass_comp COVERAGE_SKIP=1 HALF=1 GLASS_LIGHT=1", 1),
                                  ("${SHADER_SRC}/rt_glass_light_layout.h", 1)],
    "README.md": [("| `BB_RT_GLASS_LIGHT` |", 1)],
    H + "rt_glass_light_layout.h": [("#define RT_GLASS_LIGHT_PANES 16u", 1)],
    R + "rt_glass_light.h": [('std::getenv("BB_RT_GLASS_LIGHT")', 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    H + "rt_shadow.comp": ["#extension GL_EXT_ray_query : require", '#include "rt_glass_layout.h"',
                           "layout(local_size_x = 8", "CLS_FIRST_PASS = 7u;", "uint r86Panes(",
                           "uint Shade(", "imageStore(raw_img, pixel, vec4(vis));",
                           "r86_n[gl_LocalInvocationIndex] = 0u;", "R25Count(cls);",
                           "atomicAdd(r25_buf.n[RT_GLASS_LIGHT_FIRST_WORD"],
    R + "vk_rt_shadow.cpp": ["void RtShadow::CollectHeld() {", "for (const u64 key : glass_carry) {",
                             "u32 RtShadow::PrepareDraw(const Draw& draw) {", "glass_drawn.push_back(entry_key);",
                             "bool RtShadow::PrepareScene() {", "kept && !RtGlassEntry(entry->mask)",
                             "++glass_records;", "glass_instances = glass_records;",
                             "bool RtShadow::Record(const Inputs& in) {", "Ray tracing glass light (r86): %s; panes",
                             "RtGlassLightFlags(RtGlassLight(), glass_instances != 0);",
                             "void RtShadow::OnFrameEnd() {", "RecordBuilds();\n        ++glass_late;",
                             "for (const Build& build : builds) {",
                             "frame_entries.clear();\n    // bbport (r86"],
    "engine/gpu/CMakeLists.txt": ["function(add_host_shader", "${SHADER_SRC}/rt_glass_light_layout.h",
                                  "add_custom_command(OUTPUT", "rt_shadow_half_comp COVERAGE_SKIP=1 HALF=1",
                                  "rt_shadow_glass_comp COVERAGE_SKIP=1 GLASS_LIGHT=1"],
}

TMP = ".r86tmp"
MANIFEST = os.path.join(BACKUP, "manifest.txt")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def refuse(msg):
    print("REFUSED: " + msg)
    sys.exit(1)


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                refuse("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                refuse("order check: %s: %r not after the one before" % (path, s))
            at = i
    for path, text in list(NEW.items()) + [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n") for ch in text):
            refuse("text check: %s: what this patch writes is not plain ASCII" % path)
    rt = texts[R + "vk_rt_shadow.cpp"]
    if ("(counted only)\",\n" not in rt or "or probe\"\n" not in rt
            or "%.0f\\n\",\n                        RtGlassLightName(RtGlassLight())" not in rt
            or "next frame's scene\\n\",\n" not in rt):
        refuse("text check: vk_rt_shadow.cpp: a C escape lost its backslash")
    if '"^rt_shadow\\\\.comp$"' not in texts["engine/gpu/CMakeLists.txt"]:
        refuse("text check: CMakeLists.txt: the regex lost its backslashes")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("check", "apply", "revert"):
        print("use check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        refuse("%s is not a source tree root (set R86_ROOT)" % ROOT)
    for need in (R + "rt_glass.h", H + "rt_glass_layout.h"):
        if not os.path.exists(os.path.join(ROOT, need)):
            refuse("%s is missing: r86 needs r83 in the tree" % need)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: refuse("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.isdir(os.path.dirname(full)):
            refuse("no such folder: %s" % os.path.dirname(path))
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == text.replace("\n", "\r\n").encode("utf-8"):
            state = "applied"
        else:
            refuse("%s is there but not as this script writes it" % path)
        plan.append((path, None, None, "\r\n", None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        refuse("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()

    def patched():
        texts = {}
        for path, edits, raw, eol, cur, _ in plan:
            if edits is None:
                texts[path] = NEW[path]
                continue
            if state == "clean":
                for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
        return texts

    if cmd == "check":
        text_checks(patched())
        if state == "applied":
            print("applied (text checks pass)")
        else:
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(EDITS), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts = patched()
        text_checks(texts)
        outs = []
        for path, edits, raw, eol, cur, _ in plan:
            outs.append((path, texts[path].replace("\n", eol).encode("utf-8"), raw))
        os.makedirs(BACKUP, exist_ok=True)
        lines = []
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
                lines.append("%s %s %s" % (sha(raw), sha(data), path))
            else:
                lines.append("new %s %s" % (sha(data), path))
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        open(MANIFEST, "w", newline="\n").write("\n".join(lines) + "\n")
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    known = {}
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST).read().splitlines():
            a, b, p = line.split(" ", 2)
            known[p] = (a, b)
    # Everything is worked out and checked before a file is written.
    outs, notes = [], []
    for path, edits, raw, eol, cur, _ in plan:
        if edits is None:
            outs.append((path, None))
            notes.append("removed %s" % path)
            continue
        for old, new in reversed(edits): cur = cur.replace(new, old)
        data = cur.replace("\n", eol).encode("utf-8")
        if path in known:
            orig, applied = known[path]
            if sha(data) == orig:
                notes.append("restored %s: sha256 %s, as before the apply" % (path, orig[:16]))
            elif sha(raw) != applied:
                notes.append("restored %s: edits taken out; the file was changed after the apply, "
                             "so it differs from the backup (r86_backup)" % path)
            else:
                refuse("%s: taken out, but not to the original's sha256; nothing written; the "
                       "backup is in r86_backup" % path)
        else:
            notes.append("restored %s: edits taken out (no manifest to compare)" % path)
        outs.append((path, data))
    for path, data in outs:
        if data is None:
            os.remove(os.path.join(ROOT, path))
        else:
            open(os.path.join(ROOT, path), "wb").write(data)
    for note in notes:
        print(note)
    print("reverted")


main()
