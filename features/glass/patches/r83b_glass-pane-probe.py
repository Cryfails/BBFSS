# r83b_glass-pane-probe: TOOL patch (diagnosis of r83; branch dev/test-tools, never in a pull
# request; revert it once r83's fault is known, before r83 is reverted or changed).
#
# Why: with r83 (BB_RT_GLASS=1, or a list) applied and built, the game tests at church-candles,
# graveyard-blood, dark-alley, lamp-test-spot and dream-house (2026-11-15 18:43) printed r83's
# "BB_RT_GLASS on" line but never "first window pane draw": no draw of a named pair reached its
# entry in the ray traced scene. Several conditions stand between "a draw of the pair happens"
# and RtShadow::NoteGlassDraw; reading the code cannot tell which one stops the panes (they
# depend on what the game binds: the colour targets of the forward pass, and the size and stride
# of the pane vertex shader's buffers). This counts each of them.
#
# What (only with BB_RT_GLASS on; rt_glass_probe.h): one line every 300 frames
# (RtShadow::OnFrameEnd), all counts since the start:
#   "Ray tracing glass (r83b): stages: key pair A fit B depth C | hook D nogeo E static F skin G
#    pal H const I entry J note K | f FRAME" and then either
#   "| targets T vs bufs N: size/stride ..." (once a named pair was seen) or
#   "| no pair; top fwd blend: vs:ps draws[+z] x3" (never seen).
# key pair/fit/depth: pipeline key refreshes (PipelineCache::RefreshGraphicsKey, also on the draw
# preparation threads) of a draw without a pass capture whose vs:ps pair the knob names; of them
# with 1 or 2 written colour buffers; of them with a depth target, one sample, clipping on and the
# plain VS stage (these get the capture variant, as in r83). A key refresh is not a draw: a
# pipeline found again through a prepared draw or a GX record refreshes no key.
# hook: draws of a named pair that entered Rasterizer::EffectsCaptureDraw (their pipeline has the
# capture variant); nogeo: of them, stopped there (no ray traced scene wanted, or no vertex
# streams hashed: motion_geometry 0). static: passed r83's test there (no skeleton-size buffer, no
# bone palette); skin, pal: how many had a stride-16 buffer of 640 to 16384 bytes (other than 864),
# or of 96 to 639 bytes in steps of 48 (Motion::ClassifyBuffer), each counted. const: in
# RtShadow::PrepareDraw, had the 864-byte camera constants. entry: passed the projection and the
# triangle, index and instance tests. note: reached RtShadow::NoteGlassDraw (r83's line).
# targets: the written colour buffers of the last named pair's key; vs bufs: the count of the
# last named pair's vertex shader buffers and size/stride of the first 6, as EffectsCaptureDraw
# reads them (864 = camera constants). top fwd blend: the 3 shader pairs drawn most often by
# forward blended draws (colour target 0 blended, 1 or 2 targets, a depth target, neither the
# G-buffer nor a sun shadow pass, counted in Rasterizer::DrawRecord), "+z" when one of their draws
# writes depth. Depth-writing draws are listed too, against the brief: the surface probe of
# 2026-11-15 found the panes blended AND writing depth, so a "writes no depth" filter would hide
# them.
#
# Reading (2026-11-15, not proven in game): the pane vertex shader c6cdba2b (cache permutations
# _0 to _3) reads its world matrix from a buffer of 48-byte 3x4 matrices indexed by a per-vertex
# index plus dword 20 of another buffer, and the camera from a buffer with the 864-byte layout
# (dwords 183/187/191 and 200-215). If that matrix buffer (or the 24-dword one) is bound with
# stride 16 and 96 to 639 bytes, every pane draw has draw.palette != 0 and r83's test at
# vk_rasterizer_effects.cpp "!draw.skinned && draw.palette == 0" drops it ("pal" counts, "static"
# stays 0); 640 to 16384 bytes gives "skin". The line settles it; no fix is in this patch.
#
# Cost: off: three tests of a function-static bool (EffectsCaptureDraw, DrawRecord, OnFrameEnd)
# and the r83 key test written in steps (same result, only reached with the knob on); no GPU
# work. On (a probe): a few relaxed atomic adds per named-pair key refresh and draw, one mutex and
# a scan of at most 64 pairs per forward blended draw, one line every 300 frames.
#
# Files: renderer_vulkan/rt_glass_probe.h (new), vk_pipeline_cache.cpp (r83's key test in
# steps), vk_rasterizer_effects.cpp, vk_rt_shadow.cpp, vk_rasterizer.cpp. Needs r83
# (r83_glass-water-stage1.fixed.py) applied: its anchors are r83's text. While r83b is applied,
# r83's own check/apply/revert see a mixed state and stop (exit 1); revert r83b first.
#
# Use: python -I -X utf8 r83b_glass-pane-probe.py check | apply | revert (root from R83B_ROOT,
# else the current directory). check is read only. Files keep their line ends (CRLF in the
# tree); the new file is written CRLF. Originals are kept in r83b_backup/ next to this script.
# Exit: 0 done (or nothing to do), 1 the tree is in neither state or a check failed, 2 usage.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r83b_backup")
ROOT = os.environ.get("R83B_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"

NEW = {
    R + "rt_glass_probe.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r83b_glass-pane-probe): TOOL, diagnosis of r83 (BB_RT_GLASS). With the knob on, no
// window pane draw reached its entry in the ray traced scene in the game tests of 2026-11-15.
// This counts, with the knob on only, the pipeline keys and draws of a named pair that pass each
// of r83's conditions in order, and RtShadow::OnFrameEnd prints one line every EveryFrames
// frames, "Ray tracing glass (r83b): stages: ..." (all counts since the start):
//   key pair   a pipeline key refresh (PipelineCache::RefreshGraphicsKey) of a draw without a
//              pass capture whose vs:ps pair the knob names (a refresh, not a draw: a pipeline
//              found again through a prepared draw or a GX record refreshes no key)
//   fit        of them, 1 or 2 written colour buffers (r83's count)
//   depth      of them, a depth target, one sample, clipping on, the plain VS stage: the key
//              gets the capture variant
//   hook       draws of a named pair that entered Rasterizer::EffectsCaptureDraw
//   nogeo      of them, stopped there (no ray traced scene wanted, or motion_geometry 0)
//   static     passed r83's test there: no skeleton-size buffer and no bone palette; skin and
//              pal count the draws that had one (each counted)
//   const      in RtShadow::PrepareDraw, had the 864-byte camera constants
//   entry      passed the projection and the triangle, index and instance tests
//   note       reached RtShadow::NoteGlassDraw
// Once a named pair was seen the line ends with the written colour buffers of its last key and
// its vertex shader's buffers (count, then size/stride of the first BuffersMost); otherwise with
// the TopPairs shader pairs drawn most often by forward blended draws ("+z": one of their draws
// writes depth; the panes of the 2026-11-15 probe do).

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <mutex>

#include "video_core/renderer_vulkan/rt_glass.h"

namespace Vulkan::RtGlassProbe {

enum Stage : std::uint32_t {
    KeyPair,
    KeyFit,
    KeyDepth,
    Hook,
    NoGeometry,
    Static,
    Skinned,
    Palette,
    Constants,
    ToEntry,
    Note,
    Stages
};

inline constexpr std::uint64_t EveryFrames = 300;
inline constexpr std::size_t PairsMost = 64;  ///< forward blended pairs kept
inline constexpr std::size_t TopPairs = 3;    ///< of them in the line
inline constexpr std::size_t BuffersMost = 6; ///< vertex shader buffers in the line
inline constexpr std::size_t LineMost = 279;  ///< characters of the line, its newline apart

struct ForwardPair {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint64_t draws = 0;
    bool zwrite = false;
};

struct State {
    std::array<std::atomic<std::uint32_t>, Stages> counts{};
    std::atomic<std::uint32_t> key_targets{0};
    std::mutex lock; ///< guards the members below
    std::array<ForwardPair, PairsMost> pairs{};
    std::size_t used = 0;
    std::array<std::uint32_t, BuffersMost * 2> buffers{}; ///< size, stride
    std::uint32_t buffers_kept = 0;
    std::uint32_t buffers_all = 0;
};

inline State& Get() {
    static State state;
    return state;
}

inline void Add(Stage stage) {
    Get().counts[stage].fetch_add(1, std::memory_order_relaxed);
}

/// A key refresh of a draw without a pass capture (the r83 test, in its steps).
inline void NoteKey(bool pair, bool fit, bool depth, std::uint32_t targets) {
    if (!pair) {
        return;
    }
    Add(KeyPair);
    if (fit) {
        Add(KeyFit);
    }
    if (depth) {
        Add(KeyDepth);
    }
    Get().key_targets.store(targets, std::memory_order_relaxed);
}

/// A named pair's draw at r83's static test (EffectsCaptureDraw).
inline void NoteStatic(bool skinned, bool palette) {
    if (skinned) {
        Add(Skinned);
    }
    if (palette) {
        Add(Palette);
    }
    if (!skinned && !palette) {
        Add(Static);
    }
}

/// That draw's vertex shader buffers: size, stride of the first `kept`, and how many it has.
inline void NoteBuffers(const std::uint32_t* size_stride, std::uint32_t kept, std::uint32_t all) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    s.buffers = {};
    s.buffers_kept = 0;
    for (std::uint32_t i = 0; i < kept && i < BuffersMost; ++i) {
        s.buffers[i * 2] = size_stride[i * 2];
        s.buffers[i * 2 + 1] = size_stride[i * 2 + 1];
        ++s.buffers_kept;
    }
    s.buffers_all = all;
}

/// A forward blended draw's shader pair (Rasterizer::DrawRecord). When PairsMost are kept, the
/// least drawn one gives its place and its count goes on (a kept count is never too low).
inline void NoteForward(std::uint64_t vs, std::uint64_t ps, bool zwrite) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    for (std::size_t i = 0; i < s.used; ++i) {
        ForwardPair& pair = s.pairs[i];
        if (pair.vs == vs && pair.ps == ps) {
            ++pair.draws;
            pair.zwrite = pair.zwrite || zwrite;
            return;
        }
    }
    if (s.used < PairsMost) {
        s.pairs[s.used++] = {vs, ps, 1, zwrite};
        return;
    }
    ForwardPair& least = *std::min_element(
        s.pairs.begin(), s.pairs.end(),
        [](const ForwardPair& a, const ForwardPair& b) { return a.draws < b.draws; });
    least = {vs, ps, least.draws + 1, zwrite};
}

/// The line (RtShadow::OnFrameEnd, every EveryFrames frames with the knob on).
inline void Line(std::uint64_t frame) {
    State& s = Get();
    std::array<std::uint32_t, Stages> c{};
    for (std::size_t i = 0; i < c.size(); ++i) {
        c[i] = s.counts[i].load(std::memory_order_relaxed);
    }
    char line[LineMost + 1] = {};
    std::size_t at = 0;
    const auto put = [&at](int n) {
        if (n > 0) {
            at = std::min(LineMost, at + std::size_t(n));
        }
    };
    put(std::snprintf(line, sizeof(line),
                      "Ray tracing glass (r83b): stages: key pair %u fit %u depth %u | hook %u "
                      "nogeo %u static %u skin %u pal %u const %u entry %u note %u | f %llu",
                      c[KeyPair], c[KeyFit], c[KeyDepth], c[Hook], c[NoGeometry], c[Static],
                      c[Skinned], c[Palette], c[Constants], c[ToEntry], c[Note],
                      static_cast<unsigned long long>(frame)));
    {
        std::scoped_lock guard{s.lock};
        if (c[KeyPair] != 0 || c[Hook] != 0) {
            put(std::snprintf(line + at, sizeof(line) - at, " | targets %u vs bufs %u:",
                              s.key_targets.load(std::memory_order_relaxed), s.buffers_all));
            for (std::uint32_t i = 0; i < s.buffers_kept; ++i) {
                put(std::snprintf(line + at, sizeof(line) - at, " %u/%u", s.buffers[i * 2],
                                  s.buffers[i * 2 + 1]));
            }
        } else {
            std::array<ForwardPair, TopPairs> top{};
            const auto end = s.pairs.begin() + static_cast<std::ptrdiff_t>(s.used);
            const auto last = std::partial_sort_copy(
                s.pairs.begin(), end, top.begin(), top.end(),
                [](const ForwardPair& a, const ForwardPair& b) { return a.draws > b.draws; });
            put(std::snprintf(line + at, sizeof(line) - at, " | no pair; top fwd blend:%s",
                              last == top.begin() ? " none" : ""));
            for (auto it = top.begin(); it != last; ++it) {
                put(std::snprintf(line + at, sizeof(line) - at, " %llx:%llx %llu%s",
                                  static_cast<unsigned long long>(it->vs),
                                  static_cast<unsigned long long>(it->ps),
                                  static_cast<unsigned long long>(it->draws),
                                  it->zwrite ? "+z" : ""));
            }
        }
    }
    std::printf("%s\n", line);
}

} // namespace Vulkan::RtGlassProbe
''',
}

EDITS = {
    R + "vk_pipeline_cache.cpp": [
        (r'''#include "video_core/renderer_vulkan/rt_glass.h" // bbport (r83_glass-water-stage1)
''', r'''#include "video_core/renderer_vulkan/rt_glass.h" // bbport (r83_glass-water-stage1)
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
'''),
        (r'''        const auto* glass_vs = sel.infos[static_cast<u32>(Shader::SwStage::Vertex)];
        const auto* glass_fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
        if (RtGlassTargetsFit(bound) && regs.depth_buffer.DepthValid() &&
            regs.depth_buffer.NumSamples() == 1 && !regs.IsClipDisabled() &&
            regs.stage_enable.raw == AmdGpu::ShaderStageEnable::VgtStages::Vs && glass_vs &&
            glass_fs && RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash)) {
            sel.capture = true;
''', r'''        const auto* glass_vs = sel.infos[static_cast<u32>(Shader::SwStage::Vertex)];
        const auto* glass_fs = sel.infos[static_cast<u32>(Shader::SwStage::Fragment)];
        // bbport (r83b_glass-pane-probe): r83's test in its steps, each counted for the r83b line
        // (rt_glass_probe.h): the pair, its targets, then depth, one sample, clipping and the VS
        // stage. The result is r83's.
        const bool glass_pair =
            glass_vs && glass_fs && RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash);
        const bool glass_fit = glass_pair && RtGlassTargetsFit(bound);
        const bool glass_depth = glass_fit && regs.depth_buffer.DepthValid() &&
                                 regs.depth_buffer.NumSamples() == 1 && !regs.IsClipDisabled() &&
                                 regs.stage_enable.raw == AmdGpu::ShaderStageEnable::VgtStages::Vs;
        RtGlassProbe::NoteKey(glass_pair, glass_fit, glass_depth, bound);
        if (glass_depth) {
            sel.capture = true;
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''#include "video_core/renderer_vulkan/volumetric_occlusion.h"
''', r'''#include "video_core/renderer_vulkan/volumetric_occlusion.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
'''),
        (r'''    if (!rt_shadow->Wanted() || !dc.motion_geometry) {
        return;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
''', r'''    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: a capture draw of a named pair reached this
    // hook, and whether it stops just below (rt_glass_probe.h). Off: one test of a static bool.
    static const bool glass_probe = RtGlass().on;
    const auto* glass_ps =
        glass_probe ? pipeline->GetStages()[u32(Shader::SwStage::Fragment)] : nullptr;
    const bool glass_hook =
        glass_ps && RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                 glass_ps->pgm_hash);
    if (glass_hook) {
        RtGlassProbe::Add(RtGlassProbe::Hook);
    }
    if (!rt_shadow->Wanted() || !dc.motion_geometry) {
        if (glass_hook) { // bbport (r83b_glass-pane-probe)
            RtGlassProbe::Add(RtGlassProbe::NoGeometry);
        }
        return;
    }
    const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);
'''),
        (r'''    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {
        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned && draw.palette == 0) {
''', r'''    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {
        // bbport (r83b_glass-pane-probe): the named pair's draw at the test below (a skeleton,
        // a bone palette, or neither) and its vertex shader's buffers as the loop above read them
        // (size and stride; 864 = the camera constants), for the r83b line
        if (glass_hook) {
            RtGlassProbe::NoteStatic(draw.skinned, draw.palette != 0);
            std::array<u32, RtGlassProbe::BuffersMost * 2> glass_buffers{};
            u32 glass_kept = 0, glass_all = 0;
            for (const auto& resource : vs.buffers) {
                if (resource.IsSpecial()) {
                    continue;
                }
                ++glass_all;
                if (glass_kept < RtGlassProbe::BuffersMost) {
                    const auto buffer = resource.GetSharp(vs);
                    glass_buffers[glass_kept * 2] = buffer.GetSize();
                    glass_buffers[glass_kept * 2 + 1] = buffer.GetStride();
                    ++glass_kept;
                }
            }
            RtGlassProbe::NoteBuffers(glass_buffers.data(), glass_kept, glass_all);
        }
        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned && draw.palette == 0) {
'''),
    ],
    R + "vk_rt_shadow.cpp": [
        (r'''#include "video_core/renderer_vulkan/vk_sun_vsm.h"
''', r'''#include "video_core/renderer_vulkan/vk_sun_vsm.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
'''),
        (r'''void RtShadow::NoteGlassDraw(const Entry& entry) {
    const int say = RtGlassNote(glass_stats, frame, entry.triangles);
''', r'''void RtShadow::NoteGlassDraw(const Entry& entry) {
    RtGlassProbe::Add(RtGlassProbe::Note); // bbport (r83b_glass-pane-probe)
    const int say = RtGlassNote(glass_stats, frame, entry.triangles);
'''),
        (r'''    if (!draw.constants) {
        ++stats.no_camera;
        return 0;
    }
''', r'''    if (!draw.constants) {
        ++stats.no_camera;
        return 0;
    }
    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw had the camera constants
        RtGlassProbe::Add(RtGlassProbe::Constants);
    }
'''),
        (r'''        draw.instances > MaxInstancesPerDraw ? ++stats.instanced : ++stats.unsupported;
        return 0;
    }
    stats.strips += draw.strip ? 1 : 0;
''', r'''        draw.instances > MaxInstancesPerDraw ? ++stats.instanced : ++stats.unsupported;
        return 0;
    }
    if (draw.glass) { // bbport (r83b_glass-pane-probe): a pane draw goes on to its entry
        RtGlassProbe::Add(RtGlassProbe::ToEntry);
    }
    stats.strips += draw.strip ? 1 : 0;
'''),
        (r'''    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    ++frame;
''', r'''    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    ++frame;
    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: the r83b line every
    // RtGlassProbe::EveryFrames frames (rt_glass_probe.h). Off: one test of a static bool.
    if (RtGlassOn() && frame % RtGlassProbe::EveryFrames == 0) {
        RtGlassProbe::Line(frame);
    }
'''),
    ],
    R + "vk_rasterizer.cpp": [
        (r'''#include "video_core/renderer_vulkan/vk_rasterizer.h"
''', r'''#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)
'''),
        (r'''    if (dc.capture_draw) {
        BB_SECTION(RtCapture);
        EffectsCaptureDraw(regs, pipeline, is_indexed, index_offset);
    }
''', r'''    if (dc.capture_draw) {
        BB_SECTION(RtCapture);
        EffectsCaptureDraw(regs, pipeline, is_indexed, index_offset);
    }
    // bbport (r83b_glass-pane-probe): BB_RT_GLASS on: the shader pairs of forward blended draws
    // (colour target 0 blended, 1 or 2 targets, a depth target, neither the G-buffer nor a sun
    // shadow pass), for the r83b line when no named pair is seen (rt_glass_probe.h). Off: one
    // test of a static bool.
    static const bool glass_probe_forward = RtGlass().on;
    if (glass_probe_forward && !gbuffer_draw && regs.depth_buffer.DepthValid() &&
        regs.blend_control[0].enable &&
        !(regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&
          regs.depth_buffer.Height() >= 1024)) {
        const auto targets = std::popcount(pipeline->GetGraphicsKey().mrt_mask);
        const auto* glass_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
        if (glass_ps && targets >= 1 && targets <= 2) {
            RtGlassProbe::NoteForward(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,
                                      glass_ps->pgm_hash,
                                      regs.depth_control.depth_write_enable != 0);
        }
    }
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    R + "vk_pipeline_cache.cpp": [('#include "video_core/renderer_vulkan/rt_glass_probe.h"', 1),
                                  ("RtGlassProbe::NoteKey(glass_pair, glass_fit, glass_depth, bound);", 1),
                                  ("if (glass_depth) {", 1), ("sel.capture = true;", 1),
                                  ("RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash)", 1),
                                  ("RtGlassOn()", 1)],
    R + "vk_rasterizer_effects.cpp": [('#include "video_core/renderer_vulkan/rt_glass_probe.h"', 1),
                                      ("RtGlassProbe::Add(RtGlassProbe::Hook);", 1),
                                      ("RtGlassProbe::Add(RtGlassProbe::NoGeometry);", 1),
                                      ("RtGlassProbe::NoteStatic(draw.skinned, draw.palette != 0);", 1),
                                      ("RtGlassProbe::NoteBuffers(glass_buffers.data(), glass_kept, glass_all);", 1),
                                      ("draw.glass = true;", 1)],
    R + "vk_rt_shadow.cpp": [('#include "video_core/renderer_vulkan/rt_glass_probe.h"', 1),
                             ("RtGlassProbe::Add(RtGlassProbe::Note);", 1),
                             ("RtGlassProbe::Add(RtGlassProbe::Constants);", 1),
                             ("RtGlassProbe::Add(RtGlassProbe::ToEntry);", 1),
                             ("RtGlassProbe::Line(frame);", 1), ("NoteGlassDraw(entry);", 1)],
    R + "vk_rasterizer.cpp": [('#include "video_core/renderer_vulkan/rt_glass_probe.h"', 1),
                              ("RtGlassProbe::NoteForward(", 1)],
    R + "rt_glass_probe.h": [('#include "video_core/renderer_vulkan/rt_glass.h"', 1),
                             ('"Ray tracing glass (r83b): stages: key pair %u', 1)],
}

# Order checks on the patched result: each string after the one before it (first occurrence).
ORDER = {
    R + "vk_pipeline_cache.cpp": ["    if (!RefreshGraphicsStages(sel)) {", "RtGlassOn()", "glass_pair =",
                                  "RtGlassProbe::NoteKey(", "if (glass_depth) {", "sel.capture = true;",
                                  "    if (motion_possible) {"],
    R + "vk_rasterizer_effects.cpp": ["void Rasterizer::EffectsCaptureDraw(", "static const bool glass_probe =",
                                      "RtGlassProbe::Add(RtGlassProbe::Hook);",
                                      "if (!rt_shadow->Wanted() || !dc.motion_geometry) {",
                                      "RtGlassProbe::Add(RtGlassProbe::NoGeometry);",
                                      "const auto& vs = pipeline->GetStage(Shader::SwStage::Vertex);",
                                      "draw.palette = XXH3_64bits_withSeed(",
                                      "RtGlassProbe::NoteStatic(", "draw.glass = true;",
                                      "const u32 param = rt_shadow->PrepareDraw(draw);"],
    R + "vk_rt_shadow.cpp": ["void RtShadow::NoteGlassDraw(", "RtGlassProbe::Add(RtGlassProbe::Note);",
                             "u32 RtShadow::PrepareDraw(const Draw& draw) {", "++stats.no_camera;",
                             "RtGlassProbe::Add(RtGlassProbe::Constants);", "R17ToWorld(draw.constants",
                             "++stats.unsupported;", "RtGlassProbe::Add(RtGlassProbe::ToEntry);",
                             "NoteGlassDraw(entry);", "void RtShadow::OnFrameEnd() {", "    ++frame;\n",
                             "RtGlassProbe::Line(frame);"],
    R + "vk_rasterizer.cpp": ["void Rasterizer::DrawRecord(", "EffectsCaptureDraw(regs, pipeline, is_indexed, index_offset);",
                              "RtGlassProbe::NoteForward(", "SurfaceProbeDraw(pipeline, false);"],
}

TMP = ".r83btmp"


def fail(message):
    print(message)
    sys.exit(1)


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        fail("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                fail("text check: %s holds %r %d times, wanted %d" % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                fail("order check: %s: %r not after the one before" % (path, s))
            at = i
    # What this patch writes is ASCII.
    for path, text in list(NEW.items()) + [(p, n) for p, pairs in EDITS.items() for _, n in pairs]:
        if any(ord(ch) > 126 or (ord(ch) < 32 and ch not in "\n") for ch in text):
            fail("text check: %s: what this patch writes is not plain ASCII" % path)
    # The C escapes kept their backslash on the way into this script.
    h = texts[R + "rt_glass_probe.h"]
    if 'std::printf("%s\\n", line);' not in h:
        fail("text check: rt_glass_probe.h: a C escape lost its backslash")
    # The line's fixed text with every count at 6 digits and the frame at 9 stays inside LineMost
    # with room for the tail (the snprintf calls cut it there in any case).
    fixed = ("Ray tracing glass (r83b): stages: key pair %u fit %u depth %u | hook %u nogeo %u static %u "
             "skin %u pal %u const %u entry %u note %u | f %llu")
    if len(fixed.replace("%llu", "9" * 9).replace("%u", "9" * 6)) + 70 > 279:
        fail("text check: the r83b line's fixed part leaves no room for its tail")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        print("use check | apply | revert")
        sys.exit(2)
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        fail("%s is not a source tree root (set R83B_ROOT)" % ROOT)
    if not os.path.exists(os.path.join(ROOT, R + "rt_glass.h")):
        fail("r83 (r83_glass-water-stage1) is not applied in %s: r83b needs it" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: fail("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.isdir(os.path.dirname(full)):
            fail("no such folder: %s" % os.path.dirname(path))
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == text.replace("\n", "\r\n").encode("utf-8"):
            state = "applied"
        else:
            fail("%s is there but not as this script writes it" % path)
        plan.append((path, None, None, "\r\n", None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        fail("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
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
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
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
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        if edits is None:
            os.remove(os.path.join(ROOT, path))
            continue
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    print("reverted")


main()
