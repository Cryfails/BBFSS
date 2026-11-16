# r121b_glass-pane-hang (FEATURE fix of a crash; part of the window pane hook r83/r83b/r83c). Not a TOOL.
# Knob BB_RT_GLASS_STATIC: default 1 when BB_RT_GLASS is set (0 = the pane hook of before, byte for
# byte in behaviour); without BB_RT_GLASS nothing of this runs (glass stays OFF by default).
#
# THE CRASH (owner 2026-11-16, build 69 + r112t): GPU hang, device lost, breadcrumb STUCK at the TLAS
# build "Ray tracing scene" (vk_rt_shadow.cpp, the vkCmdBuildAccelerationStructuresKHR of PrepareScene,
# line ~4186), only with the hunter's torch OUT. Bisect (build 70, one game at a time, graveyard-blood,
# torch out): all features hang; all but glass: no hang; GLASS ONLY (BB_RT_GLASS=...;...;... and
# BB_GLASS_GLINT=1): hang in 60 s. The r83b log at the graveyard (no leaded windows there): "key pair
# 6415 fit 6415 depth 6415 | hook 6415 nogeo 0 static 0 skin 0 pal 6415 const 6415 entry 6415": EVERY matched
# draw carries a bone palette; the shader pair draws the glass of the held torch / lantern too.
#
# HOW THE HOOK CAN MAKE THE TLAS BUILD HANG (code lines of the tree, build 70 = <tree>):
#  1. vk_rasterizer_effects.cpp EffectsCaptureDraw, the pane test (after "r83c_glass-pane-palette"):
#     `!draw.skinned` is the only static test. r83c took the palette draws in (the leaded panes of the
#     dream house have a 96 byte world matrix table that Motion::ClassifyBuffer counts as a small
#     palette). The held torch's palette is a SmallSkeleton too. So the torch glass passes as a "pane".
#  2. In the loop above it (`for (const auto& resource : vs.buffers)`) a small palette in memory the GPU wrote
#     is NOT hashed by its bytes but by where it lies (draw.palette_placed, r47b): the torch's palette sits
#     "at two addresses in turn" (the comment of PrepareScene, r47b held_pose): its hash is the same on
#     every frame while the matrices change under it, and the matrices are not written yet when the CPU
#     side reads them. PrepareDraw (vk_rt_shadow.cpp ~2476 palette_draw, InstanceKey, promote) then
#     makes an instance entry of it; entry.palette != draw.palette sets entry.dynamic (~2840): a pane
#     BLAS REFIT every frame (needs_data), whose world positions the capture vertex shader computes
#     from a palette the GPU has not finished (not written, or NaN / huge): non-finite vertices in a
#     BLAS refit that the TLAS then refits again (r17 upkeep eUpdate with the same_refs rule). A
#     degenerate BLAS on a refit chain is the classic TLAS-stage hang, and it is what only the torch
#     can make (the dream house panes are static: a palette from CPU memory, the same bytes each frame).
#  3. The carry (r86b, BB_GLASS_GLINT on: RtGlassCarryOn, CollectHeld in vk_rt_shadow.cpp ~1523) puts
#     every pane drawn last frame into this frame's TLAS as a held entry. A pane that moves is carried
#     one frame behind its own refit, and the TLAS records change every frame (a fresh pane set), so the
#     r17 refit rule keeps seeing a changed record list ("same_refs" false) and the build path of
#     the 2nd TLAS write of a frame (r121: the ring slot of the first write is overwritten before the GPU
#     read it) is hit all the time: with glint on, the torch makes this a per-frame event.
#  Not proven by a game run (no running allowed in this task): 2 is the cause the code supports most, 3
#  makes it likely to bite; the fix removes both at the root (the torch glass is never a pane) and adds
#  checks that make the path safe whatever draws.
#
# THE FIX (BB_RT_GLASS_STATIC, default 1 with BB_RT_GLASS):
#  (1) A pane is taken only from STATIC world geometry. A draw is refused (counted by reason):
#      skinned (a skeleton buffer), palette_placed (a palette the GPU wrote: held by address, bytes not
#      known), gpustream (the vertex stream's memory is GPU modified and not in place), nonfinite (a
#      small palette's floats are not finite or past 1e6: the CPU can read them here), fresh (a pane
#      INSTANCE, the key mixed with the palette hash by InstanceKey as PrepareDraw keys a palette draw's
#      entry, is taken only once drawn on StableFrames = 3 frames: a moving object has new palette bytes
#      each frame, and a transient stream address is never a pane). Reviewer fix: the draft judged the
#      mesh key alone with a "moved" verdict; windows sharing one mesh with different matrix tables
#      would then read as moving whenever the first-drawn window changed with the view. Dream house panes: CPU written table, the
#      same bytes each frame, stable after 3 frames: taken as before (3 frames later at the very first).
#  (2) Safety of the path: a refused draw returns before an entry is made, so no BLAS is built or refit and
#      the key is never carried (glass_drawn). A pane that moves after it was taken is no longer drawn into
#      the scene, and its entry is not carried again. The BLAS lifetime was read and is safe already
#      (RtShadow::Destroy frees through DeferOperation, after the ticks of the builds that used it); a
#      TLAS refit only happens when every record but the transform is byte equal (same_refs, PrepareScene),
#      so a changed pane set is always a full build: nothing to add. r121 (ring slot per TLAS write) is
#      compatible: this patch touches neither the ring nor PrepareScene.
#
# Files: renderer_vulkan/rt_glass_static.h (new: knob, reasons, counters, the judge, pure code),
# vk_rt_shadow.h (one include, one map member), vk_rt_shadow.cpp (include; PrepareDraw judge after the pane
# key; OnFrameEnd: the 600 frame line and the once-line), vk_rasterizer_effects.cpp (include; the pane
# test's refusals), README.md (one row).
# Off (BB_RT_GLASS unset, or BB_RT_GLASS_STATIC=0): RtGlassStatic::On() is a static bool, false; every added
# test is `if (RtGlassStatic::On() ...)` evaluated only inside the glass branches (which need BB_RT_GLASS),
# so the knob-off path is the old expression: `... && !draw.skinned`. No allocation, no state.
# Cost: ON: one hash lookup (open addressing unordered_map, <= 4096 keys, 32 bytes each = 128 KB worst) per pane
# draw; the palette finite scan 24 floats per palette pane draw; no GPU cost. Fewer panes in the scene than
# before (the torch's), so a little less BLAS work.
#
# Use: python -I -X utf8 r121b_glass-pane-hang.py check | apply | revert
# Root: R121B_ROOT, else <tree>. Backups: r121b_backup next to this script. Each edit's anchor must be
# found exactly once; the new file is removed by revert. Line ends are kept (CRLF in the tree).
import os, sys, io

ROOT = os.environ.get("R121B_ROOT") or "<tree>"
BK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "r121b_backup")
RV = "engine/gpu/shadps4/video_core/renderer_vulkan/"

NEW_H = RV + "rt_glass_static.h"
HEADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC, the window pane hook takes static world geometry only.
// No Vulkan here: the code is pure and the engine's tests may build this header alone.
//
// The crash: the glass of the hunter's held torch (a shader pair of the pane list, drawn with a bone palette
// the GPU wrote, at two addresses in turn) was taken as a window pane: an entry whose BLAS is refit every
// frame from vertices that a palette not yet written (or not finite) places, carried into the next frame
// (BB_GLASS_GLINT) and built into the TLAS: the TLAS build hangs ("Ray tracing scene" STUCK). A pane is a
// still thing: the leaded windows of the dream house have a CPU written 96 byte matrix table with the same
// bytes on every frame.

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <array>
#include <atomic>
#include <unordered_map>

#include "video_core/renderer_vulkan/rt_glass.h"

namespace Vulkan::RtGlassStatic {

/// The draws with the same palette bytes in a row before a pane key is taken.
inline constexpr std::uint32_t StableFrames = 3;
/// The keys the judge remembers (the map is cleared at the cap: panes are then judged afresh, 3 frames late).
inline constexpr std::size_t SeenMost = 4096;
/// A palette float at or beyond this is not a pose.
inline constexpr float PoseLimit = 1.0e6f;

enum Reason : std::uint32_t {
    Skinned,       ///< a skeleton buffer: a character's or a held item's glass
    PlacedPalette, ///< a palette the GPU wrote (known by its address, bytes unknown at the draw)
    GpuStream,     ///< the vertex stream lies in memory the GPU modified (not in place)
    NonFinite,     ///< a small palette whose floats are not finite or are beyond PoseLimit
    Fresh,         ///< the pane instance (mesh key and palette) not yet drawn on StableFrames frames
    Taken,         ///< a draw the judge let through
    Reasons,
};

inline const char* ReasonName(std::uint32_t r) {
    static constexpr const char* names[Reasons] = {"skinned", "placed", "gpustream", "nonfinite",
                                                   "fresh",   "taken"};
    return r < Reasons ? names[r] : "?";
}

/// BB_RT_GLASS_STATIC (read once): on unless BB_RT_GLASS is off or the text is `0`. The once-line is said at the
/// first call with BB_RT_GLASS on.
inline bool On() {
    static const bool on = [] {
        if (!RtGlassOn()) {
            return false;
        }
        const char* text = std::getenv("BB_RT_GLASS_STATIC");
        const bool value = text == nullptr || std::strcmp(text, "0") != 0;
        std::printf("Ray tracing glass static (r121b): BB_RT_GLASS_STATIC %s: a window pane is taken from static world "
                    "geometry only: a skinned draw, a bone palette the GPU wrote, a vertex stream in GPU modified "
                    "memory, a palette that is not finite, and a pane instance (mesh and palette bytes) not yet "
                    "drawn on %u frames (new, or moving) are refused, counted by reason\n",
                    value ? "on" : "off (0: the hook of before)", unsigned(StableFrames));
        return value;
    }();
    return on;
}

struct Counters {
    std::array<std::atomic<std::uint64_t>, Reasons> n{};
};
inline Counters& Count() {
    static Counters counters;
    return counters;
}
inline void Add(Reason r) {
    Count().n[r].fetch_add(1, std::memory_order_relaxed);
}

/// A small palette's floats: all finite and under PoseLimit.
inline bool Finite(const float* values, std::uint32_t count) {
    for (std::uint32_t i = 0; i < count; ++i) {
        if (!(std::fabs(values[i]) < PoseLimit)) { // false for NaN and inf too
            return false;
        }
    }
    return true;
}

/// What the judge remembers of a pane instance.
struct Seen {
    std::uint64_t frame = 0; ///< the frame of its last draw (0: never)
    std::uint32_t run = 0;   ///< the frames it was drawn on
};
using SeenMap = std::unordered_map<std::uint64_t, Seen>;

/// The verdict of a pane draw at `frame`. `instance` is the pane's instance key: its glass key, mixed with the palette
/// hash when it has one (InstanceKey, as PrepareDraw keys a palette draw's entry). Windows that share one mesh and
/// differ by their matrix table are several instances, judged apart (a mesh key judged alone would see the palette of
/// whichever window the game drew first, which changes with the view). A moving object's palette bytes are new on
/// every frame: a new instance each frame, never StableFrames old. Take: build or refresh its entry. Fresh: leave it out.
inline Reason Judge(SeenMap& map, std::uint64_t instance, std::uint64_t frame) {
    if (map.size() >= SeenMost && !map.contains(instance)) {
        // a moving glass object leaves one instance a frame: forget the ones not drawn lately, then all
        std::erase_if(map, [frame](const auto& item) { return item.second.frame + 2 * StableFrames < frame; });
        if (map.size() >= SeenMost) {
            map.clear();
        }
    }
    Seen& s = map[instance];
    if (s.frame != frame) { // the first draw of the instance in this frame
        s.frame = frame;
        ++s.run;
    }
    return s.run >= StableFrames ? Taken : Fresh;
}

/// The 600 frame line, said at the end of every frame with BB_RT_GLASS_STATIC on (a counter changed).
inline void FrameEnd(std::uint64_t frame) {
    if (!On() || frame % 600 != 0) {
        return;
    }
    const Counters& c = Count();
    std::uint64_t total = 0;
    char text[256];
    int used = 0;
    for (std::uint32_t r = 0; r < Reasons; ++r) {
        const std::uint64_t v = c.n[r].load(std::memory_order_relaxed);
        total += v;
        used += std::snprintf(text + used, sizeof(text) - used, " %s %llu", ReasonName(r),
                              static_cast<unsigned long long>(v));
    }
    if (total != 0) {
        std::printf("Ray tracing glass static (r121b): pane draws by verdict (all since the start):%s\n", text);
    }
}

} // namespace Vulkan::RtGlassStatic
'''

E = {
    RV + "vk_rt_shadow.h": [
        ('#include "video_core/renderer_vulkan/rt_glass_light.h" // bbport (r86_glass-light-stage2a)\n',
         '#include "video_core/renderer_vulkan/rt_glass_light.h" // bbport (r86_glass-light-stage2a)\n'
         '#include "video_core/renderer_vulkan/rt_glass_static.h" // bbport (r121b_glass-pane-hang)\n'),
        ('    std::vector<u64> glass_drawn, glass_carry;\n',
         '    std::vector<u64> glass_drawn, glass_carry;\n'
         '    RtGlassStatic::SeenMap glass_seen; // bbport (r121b_glass-pane-hang): what the pane judge knows of each pane key\n'),
    ],
    RV + "vk_rt_shadow.cpp": [
        ('    if (draw.glass) { // bbport (r83_glass-water-stage1): apart from a pass\'s entry of the mesh\n'
         '        key = RtGlassKey(key);\n'
         '    }\n',
         '    if (draw.glass) { // bbport (r83_glass-water-stage1): apart from a pass\'s entry of the mesh\n'
         '        key = RtGlassKey(key);\n'
         '    }\n'
         '    // bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC: a pane is a still thing. The judge (rt_glass_static.h)\n'
         '    // lets a pane instance (the key, mixed with the palette hash as InstanceKey keys a palette draw\'s entry)\n'
         '    // through once it was drawn on RtGlassStatic::StableFrames frames; a new one (a held torch or a swinging\n'
         '    // lantern has new palette bytes each frame) is left out before any entry, BLAS, refit or carry of it\n'
         '    // exists: not in frame_entries and, glass_drawn not given its key, not carried into the next frame.\n'
         '    if (draw.glass && RtGlassStatic::On()) {\n'
         '        const RtGlassStatic::Reason verdict = RtGlassStatic::Judge(\n'
         '            glass_seen, draw.palette != 0 ? InstanceKey(key, draw.palette) : key, frame);\n'
         '        RtGlassStatic::Add(verdict);\n'
         '        if (verdict != RtGlassStatic::Taken) {\n'
         '            return 0;\n'
         '        }\n'
         '    }\n'),
        ('    // bbport (r86f_glass-static-panes): the vote ends with the frame, its candidate too (a vote\n',
         '    RtGlassStatic::FrameEnd(frame); // bbport (r121b_glass-pane-hang): the verdict counters, every 600 frames\n'
         '    // bbport (r86f_glass-static-panes): the vote ends with the frame, its candidate too (a vote\n'),
    ],
    RV + "vk_rasterizer_effects.cpp": [
        ('#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n',
         '#include "video_core/renderer_vulkan/rt_glass_find.h" // bbport (r86g_glint-find-bottles)\n'
         '#include "video_core/renderer_vulkan/rt_glass_static.h" // bbport (r121b_glass-pane-hang)\n'),
        ('        // bbport (r83c_glass-pane-palette): a pane with a small palette (its world matrix comes from\n',
         '        // bbport (r121b_glass-pane-hang): BB_RT_GLASS_STATIC (default on with BB_RT_GLASS): only static world\n'
         '        // geometry is a pane. Refused (counted by reason): a skeleton, a palette the GPU wrote (known by its\n'
         '        // address: the held torch\'s), a vertex stream in GPU modified memory, a small palette that is not\n'
         '        // finite. A pane instance that moves or is new is judged in PrepareDraw (RtGlassStatic::Judge). Evaluated only\n'
         '        // for a draw that matched the pane tests; the knob off: the old test `!draw.skinned` alone.\n'
         '        const auto glass_refused = [&]() -> bool {\n'
         '            if (draw.skinned) {\n'
         '                RtGlassStatic::Add(RtGlassStatic::Skinned);\n'
         '                return true;\n'
         '            }\n'
         '            if (draw.palette_placed) {\n'
         '                RtGlassStatic::Add(RtGlassStatic::PlacedPalette);\n'
         '                return true;\n'
         '            }\n'
         '            if (draw.positions != 0 && draw.positions_size != 0 &&\n'
         '                buffer_cache.IsRegionGpuModified(draw.positions, draw.positions_size) &&\n'
         '                !buffer_cache.IsInPlace(draw.positions, draw.positions_size)) {\n'
         '                RtGlassStatic::Add(RtGlassStatic::GpuStream);\n'
         '                return true;\n'
         '            }\n'
         '            if (draw.palette != 0) {\n'
         '                for (const auto& resource : vs.buffers) {\n'
         '                    if (resource.IsSpecial()) {\n'
         '                        continue;\n'
         '                    }\n'
         '                    const auto buffer = resource.GetSharp(vs);\n'
         '                    const u32 size = buffer.GetSize();\n'
         '                    if (!buffer.Valid() || buffer.GetStride() != 16 ||\n'
         '                        !memory->IsValidGpuMapping(buffer.base_address, 0) ||\n'
         '                        memory->ClampRangeSize(buffer.base_address, size) != size ||\n'
         '                        Motion::ClassifyBuffer(size) != Motion::BufferRole::SmallSkeleton) {\n'
         '                        continue;\n'
         '                    }\n'
         '                    if (!RtGlassStatic::Finite(reinterpret_cast<const float*>(buffer.base_address), size / 4u)) {\n'
         '                        RtGlassStatic::Add(RtGlassStatic::NonFinite);\n'
         '                        return true;\n'
         '                    }\n'
         '                }\n'
         '            }\n'
         '            return false;\n'
         '        };\n'
         '        // bbport (r83c_glass-pane-palette): a pane with a small palette (its world matrix comes from\n'),
        ('        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane || box_cand) && !draw.skinned) {\n',
         '        if (ps && (RtGlassMatch(vs.pgm_hash, ps->pgm_hash) || glass_auto || box_pane || box_cand) &&\n'
         '            (RtGlassStatic::On() ? !glass_refused() : !draw.skinned)) { // bbport (r121b_glass-pane-hang)\n'),
    ],
    "README.md": [
        ('| `BB_RT_GLASS=auto` | (r86g) Glass by state',
         '| `BB_RT_GLASS_STATIC` | Only with `BB_RT_GLASS` on (r121b, a crash fix). Default `1`: a window pane is taken from static world geometry only. Refused, and counted by reason: a draw with a skeleton buffer (`skinned`); a bone palette the GPU wrote (`placed`: the held torch\'s, known by its address); a vertex stream in GPU modified memory that is not in place (`gpustream`); a small palette whose floats are not finite or are beyond 1e6 (`nonfinite`); a pane instance (its mesh with its palette bytes) not yet drawn on 3 frames (`fresh`: an object that moves has new palette bytes every frame, and a stream address that changes every frame is never a pane; a still pane is taken 3 frames after its first draw). It stops the glass of the hunter\'s held torch or lantern from becoming a pane that is refit and carried every frame (with the torch out, a TLAS build "Ray tracing scene" hung the GPU with `BB_RT_GLASS` and `BB_GLASS_GLINT` on). `0`: the pane hook of before. Read once. Log: a once line `Ray tracing glass static (r121b)` and, every 600 frames, the draws by verdict (`taken` is the number that went on to an entry). Cost: one hash lookup a pane draw; nothing without `BB_RT_GLASS` | on with `BB_RT_GLASS` |\n'
         '| `BB_RT_GLASS=auto` | (r86g) Glass by state'),
    ],
}


def rd(p):
    return io.open(p, encoding="utf-8", newline="").read()


def wr(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


mode = sys.argv[1] if len(sys.argv) > 1 else "check"
if mode == "revert":
    for f in E:
        b = os.path.join(BK, f.replace("/", "__"))
        if os.path.exists(b):
            wr(os.path.join(ROOT, f), rd(b))
            print("restored", f)
    p = os.path.join(ROOT, NEW_H)
    if os.path.exists(p):
        os.remove(p)
        print("removed", NEW_H)
    sys.exit(0)

out = {}
for f, eds in E.items():
    s = rd(os.path.join(ROOT, f))
    crlf = "\r\n" in s
    t = s.replace("\r\n", "\n")
    for a, b in eds:
        if b in t:  # already applied (the new text holds the old: found once as the new text)
            if t.count(b) != 1:
                print("REFUSED (new text count)", f, a[:60]); sys.exit(1)
            continue
        if t.count(a) != 1:
            print("REFUSED", f, "anchor count", t.count(a), repr(a[:80])); sys.exit(1)
        t = t.replace(a, b)
    out[f] = (s, t.replace("\n", "\r\n") if crlf else t)
new_path = os.path.join(ROOT, NEW_H)
new_text = HEADER.replace("\n", "\r\n")
new_state = os.path.exists(new_path) and rd(new_path) == new_text
if mode == "check":
    print("applied" if new_state and all(a == b for a, b in out.values()) else "would apply")
    sys.exit(0)
os.makedirs(BK, exist_ok=True)
for f, (s, t) in out.items():
    if s != t:
        b = os.path.join(BK, f.replace("/", "__"))
        if not os.path.exists(b):
            wr(b, s)
        wr(os.path.join(ROOT, f), t)
wr(new_path, new_text)
print("applied")
