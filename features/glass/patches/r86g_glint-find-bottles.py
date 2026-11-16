# r86g_glint-find-bottles: FEATURE fix (glass, r83 chain; on top of r86f, r86e, r86d, r86c, r86b, r83c, r83b, r83).
#
# Why: builds 35 and 40: the glass glint never draws at the Hunter's Dream house. r86f gave the static
# pane draws the frame camera's constants ("const 39717" in the r83b stage line) but "entry" stayed at the
# palette draws (282) and the only pane record is still the sky dome e30b0480:8a6c7657 (89676 indices, 900 m
# away): the listed pairs probably do not name the bottles at all, and for the draws they do name nobody
# knows which PrepareDraw test stops them (the stage line counts const and entry, not what lies between).
#
# What this does:
#  1. FIND (BB_GLASS_FIND=1, log only): every forward draw (neither G-buffer nor sun shadow pass) that is
#     alpha blended on colour target 0 or listed in BB_RT_GLASS is counted by its vs:ps pair: draws a frame,
#     index counts, instances, depth write/test, discard, textured, capture pipeline, the union of the
#     scissors (screen box), and for every draw that reaches the glass hook its VERDICT (RtShadow::GlassVerdict:
#     the PrepareDraw tests in their order: pane, dropped, unwanted, no scene, no camera, bad camera, not
#     tris, no indices, 0 inst, many inst; no capture; skinned) with one failing draw as a sample (index
#     count, instances, whether the camera constants were its own or the voted ones, the projection words).
#     Lines "Ray tracing glass find (r86g): ..." at frames 300, 600 ... 1800 then every 1800 (rt_glass_find.h).
#     It works without BB_RT_GLASS too (then it lists the game's blended pairs only).
#  2. AUTO (BB_RT_GLASS=auto): glass found by state, not by a pair list. The pipeline key (the capture
#     variant) and the effects hook take a forward draw (1 or 2 colour targets, no G-buffer, no shadow pass)
#     that is alpha blended on target 0 with depth write on and 1..BB_GLASS_AUTO_INDICES indices (default
#     12000: the 89676-index sky dome is out) as a window pane; a skinned one is left out as before. Every
#     later stage (static pane camera of r86f, entries, TLAS records, carry, glint) is unchanged. The glass
#     of the game's own windows, bottles, jars, cabinet panes, lantern glass all fit the rule the r83 header
#     states for panes (forward, blended, depth write on); particles and smoke blend without depth write and
#     stay out. NOT proven on the game: see the log lines to see what the rule takes.
# Off: BB_RT_GLASS unset/0/list: auto is one test of a static bool-based inline (RtGlassAuto) in code that
# already runs only with BB_RT_GLASS on; BB_GLASS_FIND unset: one test of a static bool per forward draw
# (rasterizer) and per pane draw (effects hook); nothing is allocated, no lock is taken.
# Files: renderer_vulkan/rt_glass.h, rt_glass_find.h (NEW), vk_pipeline_cache.cpp, vk_rasterizer.cpp,
# vk_rasterizer_effects.cpp, vk_rt_shadow.h, vk_rt_shadow.cpp, README.md (3 rows), tests/test_rt_glass.cpp.
# Use: python -I -X utf8 r86g_glint-find-bottles.py check | apply | revert
# Root: R86G_ROOT else <tree>. Line ends kept per file. Backups in r86g_backup next to this script.
import os, sys, io

ROOT = os.environ.get("R86G_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r86g_backup")
V = "engine/gpu/shadps4/video_core/renderer_vulkan/"

NEW = {
 V + "rt_glass_find.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1, a diagnosis of the glass glint's missing glass
// (the Hunter's Dream house bottles, jars and cabinet glass never became pane records in the game
// tests of 2026-11-16: b35, b40). With the knob on, every forward draw (neither the G-buffer nor a
// sun shadow pass) that is alpha blended on colour target 0, or whose shader pair BB_RT_GLASS names,
// is counted by its vertex and pixel shader pair, and every draw that reaches the glass hook says
// what became of it. Every 300 frames up to frame 1800, then every 1800, RtShadow::OnFrameEnd
// calls Report: one summary line and one line for each of the busiest pairs (glass-like first):
//   "Ray tracing glass find (r86g): vs:ps listed|unlisted auto-yes|auto-no: N draws a frame,
//    indices a-b, instances n | verdicts ... | flags box e.g. <one failing draw>"
// glass-like (auto-yes): blend and depth write seen and at most BB_GLASS_AUTO_INDICES indices,
// which is what BB_RT_GLASS=auto takes for a pane. Verdicts (draws a frame since the last report):
//   pane          the draw became a pane record (NoteGlassDraw)
//   dropped       it passed every test of PrepareDraw but no record came (entry budget, MakeEntry)
//   unwanted, no scene, no camera, bad camera, not tris, no indices, 0 inst, many inst: the test of
//                 RtShadow::PrepareDraw it fails first (RtShadow::GlassVerdict, in its order)
//   no capture    the pipeline has no capture variant (no motion geometry): not given by the
//                 pipeline key, or no ray traced scene wanted
//   skinned       a pane draw with a skeleton buffer, left out by r83
// Pairs that were never listed or glass-like show no verdict. Off: one test of a static bool per
// forward draw in the rasterizer and per pane draw in the effects hook; nothing else.
// No Vulkan here: tests/test_rt_glass.cpp runs this header's code.

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <vector>

#include "rt_glass.h"

namespace Vulkan::RtGlassFind {

enum Verdict : std::uint32_t {
    Pane,
    Dropped,
    NotWanted,
    NoScene,
    NoCamera,
    NoWorld,
    NotTriangles,
    NoIndices,
    NoInstances,
    ManyInstances,
    NoGeometry,
    Skinned,
    Verdicts
};

inline constexpr std::array<const char*, Verdicts> VerdictName{{"pane", "dropped", "unwanted", "no scene",
                                                                "no camera", "bad camera", "not tris",
                                                                "no indices", "0 inst", "many inst",
                                                                "no capture", "skinned"}};

/// What a draw of a pair had, ored together over the draws.
inline constexpr std::uint32_t FlagZWrite = 1;    ///< depth write on
inline constexpr std::uint32_t FlagNoZWrite = 2;  ///< depth write off
inline constexpr std::uint32_t FlagZTest = 4;     ///< depth test on
inline constexpr std::uint32_t FlagDiscard = 8;   ///< the pixel shader discards
inline constexpr std::uint32_t FlagTextured = 16; ///< the pixel shader reads an image
inline constexpr std::uint32_t FlagListed = 32;   ///< BB_RT_GLASS names the pair
inline constexpr std::uint32_t FlagCapture = 64;  ///< the draw had a capture pipeline
inline constexpr std::uint32_t FlagGeometry = 128; ///< ... and its motion geometry

inline constexpr std::size_t PairsMost = 48;
inline constexpr std::size_t SampleMost = 88;
inline constexpr std::size_t LinePairs = 10;

struct Pair {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint64_t draws = 0; ///< since the last report
    std::uint32_t idx_min = 0xffffffffu;
    std::uint32_t idx_max = 0;
    std::uint32_t inst_max = 0;
    std::uint32_t flags = 0;
    std::uint32_t targets = 0;
    std::int32_t box[4] = {0x7fffffff, 0x7fffffff, -0x7fffffff, -0x7fffffff}; ///< union of the scissors
    std::array<std::uint64_t, Verdicts> verdict{};                             ///< since the last report
    char sample[SampleMost] = {};
};

struct DrawNote {
    std::uint64_t vs = 0;
    std::uint64_t ps = 0;
    std::uint32_t index_count = 0;
    std::uint32_t instances = 0;
    std::uint32_t flags = 0;
    std::uint32_t targets = 0;
    std::int32_t x0 = 0, y0 = 0, x1 = 0, y1 = 0; ///< the draw's scissor, in render target pixels
};

struct State {
    std::mutex lock;
    std::array<Pair, PairsMost> pairs{};
    std::size_t used = 0;
    std::uint64_t overflow = 0;   ///< draws of pairs past PairsMost
    std::uint64_t last_frame = 0; ///< of the last report
};

inline State& Get() {
    static State state;
    return state;
}

/// BB_GLASS_FIND=1, read once.
inline bool On() {
    static const bool on = [] {
        const char* text = std::getenv("BB_GLASS_FIND");
        return text && text[0] == '1' && text[1] == '\0';
    }();
    return on;
}

/// The row of a pair, made when new (lock held); null when the table is full.
inline Pair* Find(State& s, std::uint64_t vs, std::uint64_t ps) {
    for (std::size_t i = 0; i < s.used; ++i) {
        if (s.pairs[i].vs == vs && s.pairs[i].ps == ps) {
            return &s.pairs[i];
        }
    }
    if (s.used == PairsMost) {
        ++s.overflow;
        return nullptr;
    }
    Pair& p = s.pairs[s.used++];
    p.vs = vs;
    p.ps = ps;
    return &p;
}

inline void NoteDraw(const DrawNote& d) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    Pair* p = Find(s, d.vs, d.ps);
    if (!p) {
        return;
    }
    ++p->draws;
    p->idx_min = std::min(p->idx_min, d.index_count);
    p->idx_max = std::max(p->idx_max, d.index_count);
    p->inst_max = std::max(p->inst_max, d.instances);
    p->flags |= d.flags;
    p->targets = d.targets;
    if (d.x1 > d.x0 && d.y1 > d.y0) {
        p->box[0] = std::min(p->box[0], d.x0);
        p->box[1] = std::min(p->box[1], d.y0);
        p->box[2] = std::max(p->box[2], d.x1);
        p->box[3] = std::max(p->box[3], d.y1);
    }
}

/// What became of a draw at the glass hook; `sample` (may be null) is kept for the first draw of the
/// pair since the last report that did not become a pane.
inline void NoteVerdict(std::uint64_t vs, std::uint64_t ps, Verdict v, const char* sample) {
    State& s = Get();
    std::scoped_lock guard{s.lock};
    Pair* p = Find(s, vs, ps);
    if (!p) {
        return;
    }
    ++p->verdict[v];
    if (sample && v != Pane && p->sample[0] == '\0') {
        std::strncpy(p->sample, sample, SampleMost - 1);
        p->sample[SampleMost - 1] = '\0';
    }
}

/// Whether a row is glass-like: blend and depth write seen (the draws were blended, or listed) and
/// at most `auto_most` indices.
inline bool GlassLike(const Pair& p, std::uint32_t auto_most) {
    return (p.flags & FlagZWrite) != 0 && p.draws + p.idx_max != 0 && p.idx_max <= auto_most;
}

/// The reports' frames: 300, 600, ... 1800, then every 1800.
constexpr bool ReportFrame(std::uint64_t frame) {
    return frame >= 300 && frame % 300 == 0 && (frame <= 1800 || frame % 1800 == 0);
}

inline void Report(std::uint64_t frame, std::uint32_t auto_most) {
    if (!ReportFrame(frame)) {
        return;
    }
    State& s = Get();
    std::vector<Pair> rows;
    std::uint64_t from = 0, overflow = 0;
    {
        std::scoped_lock guard{s.lock};
        if (frame == s.last_frame) {
            return;
        }
        from = s.last_frame;
        s.last_frame = frame;
        overflow = s.overflow;
        rows.assign(s.pairs.begin(), s.pairs.begin() + static_cast<std::ptrdiff_t>(s.used));
        for (std::size_t i = 0; i < s.used; ++i) {
            s.pairs[i].draws = 0;
            s.pairs[i].verdict = {};
            s.pairs[i].sample[0] = '\0';
        }
    }
    const double frames = double(frame - from > 0 ? frame - from : 1);
    std::erase_if(rows, [](const Pair& p) {
        return p.draws == 0 &&
               std::all_of(p.verdict.begin(), p.verdict.end(), [](std::uint64_t n) { return n == 0; });
    });
    const auto rank = [&](const Pair& p) { return GlassLike(p, auto_most) ? 2 : (p.flags & FlagListed) ? 1 : 0; };
    std::stable_sort(rows.begin(), rows.end(), [&](const Pair& a, const Pair& b) {
        return rank(a) != rank(b) ? rank(a) > rank(b) : a.draws > b.draws;
    });
    std::size_t like = 0, listed = 0;
    for (const Pair& p : rows) {
        like += GlassLike(p, auto_most) ? 1 : 0;
        listed += (p.flags & FlagListed) ? 1 : 0;
    }
    std::printf("Ray tracing glass find (r86g): frames %llu-%llu: %zu forward blended or listed pairs drawn, "
                "%zu glass-like (blend + depth write, at most %u indices: BB_RT_GLASS=auto takes them), "
                "%zu listed, %llu draws of pairs past the table; the busiest below, glass-like first\n",
                static_cast<unsigned long long>(from), static_cast<unsigned long long>(frame), rows.size(),
                like, auto_most, listed, static_cast<unsigned long long>(overflow));
    for (std::size_t n = 0; n < rows.size() && n < LinePairs; ++n) {
        const Pair& p = rows[n];
        char line[512];
        std::size_t at = 0;
        const auto put = [&](int written) {
            if (written > 0) {
                at = std::min(sizeof(line) - 1, at + std::size_t(written));
            }
        };
        put(std::snprintf(line, sizeof(line),
                          "Ray tracing glass find (r86g): %llx:%llx %s %s: %.1f draws a frame, indices %u-%u, "
                          "instances %u",
                          static_cast<unsigned long long>(p.vs), static_cast<unsigned long long>(p.ps),
                          (p.flags & FlagListed) ? "listed" : "unlisted",
                          GlassLike(p, auto_most) ? "auto-yes" : "auto-no", double(p.draws) / frames,
                          p.idx_min == 0xffffffffu ? 0u : p.idx_min, p.idx_max, p.inst_max));
        bool any = false;
        for (std::size_t v = 0; v < Verdicts; ++v) {
            if (p.verdict[v] != 0) {
                put(std::snprintf(line + at, sizeof(line) - at, "%s %s %.1f", any ? "," : " | verdicts",
                                  VerdictName[v], double(p.verdict[v]) / frames));
                any = true;
            }
        }
        if (!any) {
            put(std::snprintf(line + at, sizeof(line) - at, " | no pane test"));
        }
        put(std::snprintf(line + at, sizeof(line) - at, " |%s%s%s%s%s%s%s targets %u",
                          (p.flags & FlagZWrite) ? " zwrite" : "", (p.flags & FlagNoZWrite) ? " nozwrite" : "",
                          (p.flags & FlagDiscard) ? " discard" : "", (p.flags & FlagTextured) ? " textured" : "",
                          (p.flags & FlagCapture) ? " capture" : "", (p.flags & FlagGeometry) ? " geometry" : "",
                          (p.flags & FlagZTest) ? " ztest" : "", p.targets));
        if (p.box[2] > p.box[0] && p.box[3] > p.box[1]) {
            put(std::snprintf(line + at, sizeof(line) - at, ", scissors %d,%d-%d,%d", p.box[0], p.box[1],
                              p.box[2], p.box[3]));
        }
        std::printf("%s\n", line);
        // review fix: the sample on a line of its own; the pair line can pass 300 characters
        // (16-digit hashes, several verdicts, flags, scissors) and the sample must not be cut off
        if (p.sample[0] != '\0') {
            std::printf("Ray tracing glass find (r86g): %llx:%llx sample %s\n",
                        static_cast<unsigned long long>(p.vs), static_cast<unsigned long long>(p.ps),
                        p.sample);
        }
    }
}

} // namespace Vulkan::RtGlassFind
''',
}

E = {
 V + "rt_glass.h": [
  ("    bool listed = false; ///< the pairs are the text's, not RtGlassBuiltIn\n",
   "    bool listed = false; ///< the pairs are the text's, not RtGlassBuiltIn\n"
   "    bool automatic = false; ///< \"auto\" (r86g_glint-find-bottles): no pairs, the draw's state decides\n"),
  ("    RtGlassKnob listed{};\n    listed.listed = true;\n",
   "    // bbport (r86g_glint-find-bottles): \"auto\": glass by state (RtGlassAutoDraw), no pair list\n"
   "    if (text[0] == 'a' && text[1] == 'u' && text[2] == 't' && text[3] == 'o' && text[4] == '\\0') {\n"
   "        RtGlassKnob automatic{};\n"
   "        automatic.on = true;\n"
   "        automatic.automatic = true;\n"
   "        return automatic;\n"
   "    }\n"
   "    RtGlassKnob listed{};\n    listed.listed = true;\n"),
  ("inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {\n    return RtGlassMatches(RtGlass(), vs, ps);\n}\n",
   "inline bool RtGlassMatch(std::uint64_t vs, std::uint64_t ps) {\n    return RtGlassMatches(RtGlass(), vs, ps);\n}\n"
   "\n"
   "// bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto: a forward draw is a pane when it is alpha blended\n"
   "// on colour target 0 with depth write on (the r83 header's description of the game's panes) and has\n"
   "// 1 to BB_GLASS_AUTO_INDICES indices (default 12000: the sky dome's 89676 is out, bottles and window\n"
   "// panes are a few hundred to a few thousand). The pipeline key knows the state only (RtGlassAutoKey),\n"
   "// the draw also its index count (RtGlassAutoDraw).\n"
   "inline constexpr std::uint32_t RtGlassAutoIndicesDefault = 12000;\n"
   "\n"
   "constexpr bool RtGlassAutoKey(bool blend, bool depth_write) {\n"
   "    return blend && depth_write;\n"
   "}\n"
   "\n"
   "constexpr bool RtGlassAutoDraw(bool blend, bool depth_write, std::uint32_t index_count, std::uint32_t most) {\n"
   "    return RtGlassAutoKey(blend, depth_write) && index_count != 0 && index_count <= most;\n"
   "}\n"
   "\n"
   "/// BB_GLASS_AUTO_INDICES's text: 3 to 1000000 (digits only, at most 8 of them), else the default.\n"
   "constexpr std::uint32_t RtGlassParseAutoIndices(const char* text) {\n"
   "    if (!text || text[0] == '\\0') {\n"
   "        return RtGlassAutoIndicesDefault;\n"
   "    }\n"
   "    std::uint64_t value = 0;\n"
   "    for (std::size_t i = 0; text[i] != '\\0'; ++i) {\n"
   "        if (text[i] < '0' || text[i] > '9' || i >= 8) {\n"
   "            return RtGlassAutoIndicesDefault;\n"
   "        }\n"
   "        value = value * 10 + std::uint64_t(text[i] - '0');\n"
   "    }\n"
   "    return value >= 3 && value <= 1000000 ? std::uint32_t(value) : RtGlassAutoIndicesDefault;\n"
   "}\n"
   "\n"
   "/// BB_RT_GLASS=auto, read once (with the knob).\n"
   "inline bool RtGlassAuto() {\n"
   "    return RtGlass().on && RtGlass().automatic;\n"
   "}\n"
   "\n"
   "inline std::uint32_t RtGlassAutoIndices() {\n"
   "    static const std::uint32_t most = RtGlassParseAutoIndices(std::getenv(\"BB_GLASS_AUTO_INDICES\"));\n"
   "    return most;\n"
   "}\n"),
 ],
 V + "vk_pipeline_cache.cpp": [
  ("        const bool glass_pair =\n"
   "            glass_vs && glass_fs && RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash);\n",
   "        const bool glass_pair =\n"
   "            glass_vs && glass_fs &&\n"
   "            (RtGlassMatch(glass_vs->pgm_hash, glass_fs->pgm_hash) ||\n"
   "             // bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto: blended with depth write (the fit\n"
   "             // test below keeps the G-buffer and the shadow pass out)\n"
   "             (RtGlassAuto() && RtGlassAutoKey(regs.blend_control[0].enable != 0,\n"
   "                                              regs.depth_control.depth_write_enable != 0)));\n"),
 ],
 V + "vk_rasterizer.cpp": [
  ('#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n',
   '#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n'
   '#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'),
  ("            RtGlassProbe::NoteForward(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                      glass_ps->pgm_hash,\n"
   "                                      regs.depth_control.depth_write_enable != 0);\n"
   "        }\n"
   "    }\n",
   "            RtGlassProbe::NoteForward(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                      glass_ps->pgm_hash,\n"
   "                                      regs.depth_control.depth_write_enable != 0);\n"
   "        }\n"
   "    }\n"
   "    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1 (rt_glass_find.h): every forward draw (not the\n"
   "    // G-buffer, not a sun shadow pass) that is blended on colour target 0 or in the BB_RT_GLASS list,\n"
   "    // counted by its shader pair, for the log. Off: one test of a static bool.\n"
   "    static const bool glass_find = RtGlassFind::On();\n"
   "    if (glass_find && !gbuffer_draw &&\n"
   "        !(regs.depth_buffer.DepthValid() && regs.depth_buffer.Pitch() == regs.depth_buffer.Height() &&\n"
   "          regs.depth_buffer.Height() >= 1024)) {\n"
   "        const auto* find_ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];\n"
   "        const u64 find_vs = pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash;\n"
   "        const bool find_listed = find_ps && RtGlassMatch(find_vs, find_ps->pgm_hash);\n"
   "        if (find_ps && (regs.blend_control[0].enable || find_listed)) {\n"
   "            const vk::Rect2D find_box = DrawScissor(0);\n"
   "            RtGlassFind::DrawNote note;\n"
   "            note.vs = find_vs;\n"
   "            note.ps = find_ps->pgm_hash;\n"
   "            note.index_count = regs.num_indices;\n"
   "            note.instances = regs.num_instances.NumInstances();\n"
   "            note.targets = u32(std::popcount(pipeline->GetGraphicsKey().mrt_mask));\n"
   "            note.flags = (regs.depth_control.depth_write_enable != 0 ? RtGlassFind::FlagZWrite\n"
   "                                                                      : RtGlassFind::FlagNoZWrite) |\n"
   "                         (regs.depth_control.depth_enable != 0 ? RtGlassFind::FlagZTest : 0u) |\n"
   "                         (find_ps->has_discard ? RtGlassFind::FlagDiscard : 0u) |\n"
   "                         (!find_ps->images.empty() ? RtGlassFind::FlagTextured : 0u) |\n"
   "                         (find_listed ? RtGlassFind::FlagListed : 0u) |\n"
   "                         (dc.capture_draw ? RtGlassFind::FlagCapture : 0u) |\n"
   "                         (dc.motion_geometry != 0 ? RtGlassFind::FlagGeometry : 0u);\n"
   "            note.x0 = find_box.offset.x;\n"
   "            note.y0 = find_box.offset.y;\n"
   "            note.x1 = find_box.offset.x + s32(find_box.extent.width);\n"
   "            note.y1 = find_box.offset.y + s32(find_box.extent.height);\n"
   "            RtGlassFind::NoteDraw(note);\n"
   "        }\n"
   "    }\n"),
 ],
 V + "vk_rasterizer_effects.cpp": [
  ('#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n',
   '#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n'
   '#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'),
  ("    const bool glass_hook =\n"
   "        glass_ps && RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                 glass_ps->pgm_hash);\n",
   "    // bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto: a forward draw blended with depth write and\n"
   "    // a modest index count is a pane (rt_glass.h), whatever its shader pair\n"
   "    const bool glass_auto =\n"
   "        glass_ps && !gbuffer_draw && RtGlassAuto() &&\n"
   "        RtGlassAutoDraw(regs.blend_control[0].enable != 0, regs.depth_control.depth_write_enable != 0,\n"
   "                        regs.num_indices, RtGlassAutoIndices());\n"
   "    const bool glass_hook =\n"
   "        glass_ps && (RtGlassMatch(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                  glass_ps->pgm_hash) ||\n"
   "                     glass_auto);\n"),
  ("        if (glass_hook) { // bbport (r83b_glass-pane-probe)\n"
   "            RtGlassProbe::Add(RtGlassProbe::NoGeometry);\n"
   "        }\n"
   "        return;\n",
   "        if (glass_hook) { // bbport (r83b_glass-pane-probe)\n"
   "            RtGlassProbe::Add(RtGlassProbe::NoGeometry);\n"
   "            if (RtGlassFind::On()) { // bbport (r86g_glint-find-bottles)\n"
   "                RtGlassFind::NoteVerdict(pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash,\n"
   "                                         glass_ps->pgm_hash, RtGlassFind::NoGeometry, nullptr);\n"
   "            }\n"
   "        }\n"
   "        return;\n"),
  ("    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {\n",
   "    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: what the pane test of PrepareDraw says of\n"
   "    // this pane draw (RtShadow::GlassVerdict, before the call) and the pane records counted before it\n"
   "    // (an unset sample is never read: find_verdict stays RtGlassFind::Verdicts without the knob)\n"
   "    static const bool glass_find = RtGlassFind::On();\n"
   "    u32 find_verdict = RtGlassFind::Verdicts;\n"
   "    u32 find_notes = 0;\n"
   "    char find_sample[RtGlassFind::SampleMost];\n"
   "    find_sample[0] = '\\0';\n"
   "    if (!draw.camera_pass && !draw.shadow_pass && RtGlassOn()) {\n"),
  ("        if (ps && RtGlassMatch(vs.pgm_hash, ps->pgm_hash) && !draw.skinned) {\n",
   "        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto) && !draw.skinned) {\n"),
  ("            if (!draw.constants) {\n"
   "                draw.constants = rt_shadow->GlassCamera();\n"
   "            }\n"
   "            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n"
   "        }\n"
   "    }\n"
   "    BbSections::Scope prepare_scope{BbSections::RtPrepare};\n"
   "    const u32 param = rt_shadow->PrepareDraw(draw);\n"
   "    prepare_scope.End();\n",
   "            const bool find_own = draw.constants != nullptr; // bbport (r86g_glint-find-bottles)\n"
   "            if (!draw.constants) {\n"
   "                draw.constants = rt_shadow->GlassCamera();\n"
   "            }\n"
   "            glint_pending = glass_glint ? pipeline : nullptr; // bbport (r86b_glass-visible)\n"
   "            if (glass_find) { // bbport (r86g_glint-find-bottles)\n"
   "                find_verdict =\n"
   "                    rt_shadow->GlassVerdict(draw, find_own, find_sample, sizeof(find_sample));\n"
   "                find_notes = RtGlassProbe::Get().counts[RtGlassProbe::Note].load(\n"
   "                    std::memory_order_relaxed);\n"
   "            }\n"
   "        } else if (glass_find && glass_hook) { // a pane draw with a skeleton buffer: left out by r83\n"
   "            RtGlassFind::NoteVerdict(vs.pgm_hash, ps->pgm_hash, RtGlassFind::Skinned, nullptr);\n"
   "        }\n"
   "    }\n"
   "    BbSections::Scope prepare_scope{BbSections::RtPrepare};\n"
   "    const u32 param = rt_shadow->PrepareDraw(draw);\n"
   "    prepare_scope.End();\n"
   "    if (find_verdict != RtGlassFind::Verdicts && ps) { // bbport (r86g_glint-find-bottles)\n"
   "        u32 found = find_verdict;\n"
   "        if (found == RtGlassFind::Pane &&\n"
   "            RtGlassProbe::Get().counts[RtGlassProbe::Note].load(std::memory_order_relaxed) ==\n"
   "                find_notes) {\n"
   "            found = RtGlassFind::Dropped; // passed the tests, no record came (budget, MakeEntry)\n"
   "        }\n"
   "        RtGlassFind::NoteVerdict(vs.pgm_hash, ps->pgm_hash, RtGlassFind::Verdict(found), find_sample);\n"
   "    }\n"),
 ],
 V + "vk_rt_shadow.h": [
  ("    [[nodiscard]] const float* GlassCamera();\n",
   "    [[nodiscard]] const float* GlassCamera();\n"
   "    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: which PrepareDraw test a pane draw (as the\n"
   "    // effects hook built it, camera constants given) would fail first, as an RtGlassFind::Verdict\n"
   "    // (0 = passes all); no side effect. `sample` (size bytes, may be null) gets one line of the draw's\n"
   "    // numbers: index count, instances, triangles, indices, whose constants, the projection's words 12-15.\n"
   "    [[nodiscard]] u32 GlassVerdict(const Draw& draw, bool own_constants, char* sample,\n"
   "                                   std::size_t size) const;\n"),
 ],
 V + "vk_rt_shadow.cpp": [
  ('#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n',
   '#include "video_core/renderer_vulkan/rt_glass_probe.h" // bbport (r83b_glass-pane-probe)\n'
   '#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'),
  ('                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));\n'
   "        }\n",
   '                        glass.listed ? "the listed" : "the built-in", list, unsigned(RtGlassMask));\n'
   "        }\n"
   "        // bbport (r86g_glint-find-bottles): BB_RT_GLASS=auto and BB_GLASS_FIND, said once\n"
   "        if (glass.on && glass.automatic) {\n"
   '            std::printf("Ray tracing glass (r86g): BB_RT_GLASS=auto: a forward draw alpha blended on '
   'colour target 0 with depth write on and 1 to %u indices (BB_GLASS_AUTO_INDICES) is a window pane '
   '(a skinned one is left out); no shader pair list\\n",\n'
   "                        RtGlassAutoIndices());\n"
   "        }\n"
   "        if (RtGlassFind::On()) {\n"
   '            std::printf("Ray tracing glass find (r86g): BB_GLASS_FIND=1: forward blended and listed '
   'shader pairs and what became of their pane draws are logged at frames 300, 600 ... 1800, then every '
   '1800\\n");\n'
   "        }\n"),
  ("    return r86f_camera;\n}\n\nu32 RtShadow::PrepareDraw(const Draw& draw) {\n",
   "    return r86f_camera;\n}\n"
   "\n"
   "// bbport (r86g_glint-find-bottles): the tests PrepareDraw makes of a pane draw after the glass hook,\n"
   "// in its order, without their side effects (see the header). 0 (RtGlassFind::Pane): passes them all.\n"
   "u32 RtShadow::GlassVerdict(const Draw& draw, bool own_constants, char* sample, std::size_t size) const {\n"
   "    std::array<float, 12> world{};\n"
   "    const bool camera = draw.constants != nullptr && ToWorld(draw.constants, draw.camera_pass, world);\n"
   "    if (sample != nullptr && size != 0) {\n"
   "        const float* p = draw.constants != nullptr ? draw.constants + 52 : nullptr;\n"
   '        std::snprintf(sample, size, "e.g. idx %u inst %u tri %d ind %d cam %s %s p12-15 %.3g %.3g %.3g %.3g",\n'
   "                      draw.index_count, draw.instances, draw.triangles ? 1 : 0, draw.indices != 0 ? 1 : 0,\n"
   '                      draw.constants == nullptr ? "none" : own_constants ? "own" : "voted",\n'
   '                      camera ? "ok" : "bad", p ? p[12] : 0.0f, p ? p[13] : 0.0f, p ? p[14] : 0.0f,\n'
   "                      p ? p[15] : 0.0f);\n"
   "    }\n"
   "    if (!Wanted()) {\n"
   "        return RtGlassFind::NotWanted;\n"
   "    }\n"
   "    if (draw.camera_pass && !need_scene) {\n"
   "        return RtGlassFind::NoScene;\n"
   "    }\n"
   "    if (draw.constants == nullptr) {\n"
   "        return RtGlassFind::NoCamera;\n"
   "    }\n"
   "    if (!camera) {\n"
   "        return RtGlassFind::NoWorld;\n"
   "    }\n"
   "    if (!draw.triangles) {\n"
   "        return RtGlassFind::NotTriangles;\n"
   "    }\n"
   "    if (draw.indices == 0) {\n"
   "        return RtGlassFind::NoIndices;\n"
   "    }\n"
   "    if (draw.instances == 0) {\n"
   "        return RtGlassFind::NoInstances;\n"
   "    }\n"
   "    if (draw.instances > MaxInstancesPerDraw) {\n"
   "        return RtGlassFind::ManyInstances;\n"
   "    }\n"
   "    return RtGlassFind::Pane;\n"
   "}\n"
   "\n"
   "u32 RtShadow::PrepareDraw(const Draw& draw) {\n"),
  ("        RtGlassProbe::Line(frame);\n    }\n",
   "        RtGlassProbe::Line(frame);\n    }\n"
   "    // bbport (r86g_glint-find-bottles): BB_GLASS_FIND=1: the find lines (rt_glass_find.h). Off: one test.\n"
   "    if (RtGlassFind::On()) {\n"
   "        RtGlassFind::Report(frame, RtGlassAutoIndices());\n"
   "    }\n"),
 ],
 "README.md": [
  ("| `BB_GLASS_GLINT_SHARP` | Only with `BB_GLASS_GLINT` on:",
   "| `BB_RT_GLASS=auto` | (r86g) Glass by state instead of a list of shader pairs: with the text `auto`, every forward draw (not the G-buffer, not a sun shadow pass; 1 or 2 colour targets, a depth target) that is alpha blended on colour target 0 with depth write on and has 1 to `BB_GLASS_AUTO_INDICES` indices is a window pane in the ray traced scene (a skinned one is left out). Meant for the Hunter's Dream house bottles, jars and cabinet glass, whose pairs the lists never named; the sky dome (89676 indices) is out. Everything after that (the static panes' camera of r86f, records, carry, glint) is as with a list. Off by default like `BB_RT_GLASS`. Log: `Ray tracing glass (r86g):` once. |\n"
   "| `BB_GLASS_AUTO_INDICES` | Only with `BB_RT_GLASS=auto` (r86g). The most indices a draw may have to count as a pane: 3 to 1000000, default 12000 (digits only, anything else is the default). |\n"
   "| `BB_GLASS_FIND` | `1` (r86g, a diagnosis, log only): every forward draw that is alpha blended on colour target 0 or whose pair `BB_RT_GLASS` names is counted by its vertex and pixel shader pair, and every pane draw says what became of it. At frames 300, 600 ... 1800 then every 1800: a summary line and one line for each of the ten busiest pairs (glass-like first): draws a frame, indices, instances, `auto-yes` (the `auto` rule would take it), verdicts (pane, dropped, unwanted, no scene, no camera, bad camera, not tris, no indices, 0 inst, many inst, no capture, skinned), depth write/test, discard, textured, capture pipeline, the union of the draw scissors, and one failing draw's numbers. Works without `BB_RT_GLASS`. Log: `Ray tracing glass find (r86g):`. |\n"
   "| `BB_GLASS_GLINT_SHARP` | Only with `BB_GLASS_GLINT` on:"),
 ],
 "engine/tests/test_rt_glass.cpp": [
  ('#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass.h"\n',
   '#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass.h"\n'
   '#include "gpu/shadps4/video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'),
  ('    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n",\n',
   "    // bbport (r86g_glint-find-bottles): \"auto\", the state rule, the index limit's text\n"
   "    {\n"
   '        constexpr RtGlassKnob automatic = ParseRtGlass("auto");\n'
   "        static_assert(automatic.on && automatic.automatic && !automatic.listed && automatic.count == 0);\n"
   '        static_assert(!ParseRtGlass("1").automatic && !ParseRtGlass("c6cdba2b:c31bd920").automatic);\n'
   '        static_assert(!ParseRtGlass("autos").on && !ParseRtGlass("Auto").on && !ParseRtGlass("aut").on);\n'
   "        static_assert(!RtGlassMatches(automatic, 0xc6cdba2b, 0xc31bd920)); // no pair is named\n"
   "        static_assert(RtGlassAutoDraw(true, true, 400, 12000) && !RtGlassAutoDraw(false, true, 400, 12000));\n"
   "        static_assert(!RtGlassAutoDraw(true, false, 400, 12000) && !RtGlassAutoDraw(true, true, 0, 12000));\n"
   "        static_assert(!RtGlassAutoDraw(true, true, 89676, 12000) && RtGlassAutoDraw(true, true, 12000, 12000));\n"
   "        static_assert(RtGlassAutoKey(true, true) && !RtGlassAutoKey(true, false) && !RtGlassAutoKey(false, true));\n"
   "        static_assert(RtGlassParseAutoIndices(nullptr) == 12000 && RtGlassParseAutoIndices(\"\") == 12000);\n"
   '        static_assert(RtGlassParseAutoIndices("5000") == 5000 && RtGlassParseAutoIndices("3") == 3);\n'
   '        static_assert(RtGlassParseAutoIndices("2") == 12000 && RtGlassParseAutoIndices("x") == 12000);\n'
   '        static_assert(RtGlassParseAutoIndices("5000x") == 12000 && RtGlassParseAutoIndices("1000001") == 12000);\n'
   '        static_assert(RtGlassParseAutoIndices("1000000") == 1000000);\n'
   "    }\n"
   "    // The find table: draws and verdicts of a pair, a report resets the window, frames that report\n"
   "    {\n"
   "        static_assert(!RtGlassFind::ReportFrame(0) && !RtGlassFind::ReportFrame(299) && RtGlassFind::ReportFrame(300));\n"
   "        static_assert(RtGlassFind::ReportFrame(1800) && !RtGlassFind::ReportFrame(2100) && RtGlassFind::ReportFrame(3600));\n"
   "        RtGlassFind::State& table = RtGlassFind::Get();\n"
   "        RtGlassFind::DrawNote note;\n"
   "        note.vs = 0xe94b5b06;\n"
   "        note.ps = 0x5e4596f4;\n"
   "        note.index_count = 360;\n"
   "        note.instances = 1;\n"
   "        note.flags = RtGlassFind::FlagZWrite | RtGlassFind::FlagListed;\n"
   "        note.targets = 1;\n"
   "        note.x1 = 100;\n"
   "        note.y1 = 50;\n"
   "        RtGlassFind::NoteDraw(note);\n"
   "        note.index_count = 90;\n"
   "        RtGlassFind::NoteDraw(note);\n"
   "        RtGlassFind::NoteVerdict(0xe94b5b06, 0x5e4596f4, RtGlassFind::NoCamera, \"e.g. idx 360\");\n"
   "        RtGlassFind::NoteVerdict(0xe94b5b06, 0x5e4596f4, RtGlassFind::Pane, nullptr);\n"
   "        RtGlassFind::NoteVerdict(0xe30b0480, 0x8a6c7657, RtGlassFind::NoGeometry, nullptr); // a new pair\n"
   "        assert(table.used == 2 && table.pairs[0].draws == 2 && table.pairs[0].idx_min == 90);\n"
   "        assert(table.pairs[0].idx_max == 360 && table.pairs[0].box[2] == 100 && table.pairs[0].box[3] == 50);\n"
   "        assert(table.pairs[0].verdict[RtGlassFind::NoCamera] == 1 && table.pairs[0].verdict[RtGlassFind::Pane] == 1);\n"
   "        assert(table.pairs[1].draws == 0 && table.pairs[1].verdict[RtGlassFind::NoGeometry] == 1);\n"
   "        assert(RtGlassFind::GlassLike(table.pairs[0], 12000) && !RtGlassFind::GlassLike(table.pairs[0], 200));\n"
   "        RtGlassFind::Report(299, 12000); // not a report frame: nothing changes\n"
   "        assert(table.pairs[0].draws == 2);\n"
   "        RtGlassFind::Report(300, 12000); // prints the lines, starts a new window\n"
   "        assert(table.pairs[0].draws == 0 && table.pairs[0].sample[0] == '\\0' && table.last_frame == 300);\n"
   "        assert(table.pairs[0].verdict[RtGlassFind::NoCamera] == 0 && table.pairs[0].idx_max == 360);\n"
   "    }\n"
   '    std::printf("rt glass: ok (mask 0x%x, bounce mask 0x%x, %zu built-in pairs, at most %zu listed)\\n",\n'),
 ],
}

def rd(p): return io.open(p, encoding="utf-8", newline="").read()
def wr(p, s): io.open(p, "w", encoding="utf-8", newline="").write(s)

def plan():
    out, state = {}, []
    for f, eds in E.items():
        s = rd(os.path.join(ROOT, f)); crlf = "\r\n" in s; t = s.replace("\r\n", "\n")
        for a, b in eds:
            if t.count(b) == 1 and b != a:
                state.append("done"); continue
            if t.count(a) != 1:
                print("REFUSED", f, "anchor count", t.count(a), repr(a[:70])); sys.exit(1)
            t = t.replace(a, b); state.append("todo")
        out[f] = (s, t.replace("\n", "\r\n") if crlf else t)
    if "done" in state and "todo" in state:
        print("REFUSED: mixed state (%d done, %d todo)" % (state.count("done"), state.count("todo"))); sys.exit(1)
    for f in NEW:
        p = os.path.join(ROOT, f)
        state.append("done" if os.path.exists(p) else "todo")
    if "done" in state and "todo" in state:
        print("REFUSED: mixed state (new files)"); sys.exit(1)
    return out, state

mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "revert":
    for f in E:
        b = os.path.join(BK, f.replace("/", "__"))
        if os.path.exists(b):
            wr(os.path.join(ROOT, f), rd(b)); os.remove(b); print("restored", f)
    for f in NEW:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            os.remove(p); print("removed", f)
    sys.exit(0)
if mode not in ("check", "apply"):
    print("usage: check | apply | revert"); sys.exit(2)
out, state = plan()
if mode == "check":
    print("applied" if "todo" not in state else "not applied; would apply (%d edits, %d new files)" % (len(state) - len(NEW), len(NEW))); sys.exit(0)
if "todo" not in state:
    print("already applied"); sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace("/", "__"))
        if not os.path.exists(b): wr(b, s)
        wr(os.path.join(ROOT, f), t)
for f, text in NEW.items():
    wr(os.path.join(ROOT, f), text.replace("\n", "\r\n") if os.environ.get("R86G_CRLF") else text)
print("applied")
