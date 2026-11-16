// SPDX-License-Identifier: GPL-3.0-or-later
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
