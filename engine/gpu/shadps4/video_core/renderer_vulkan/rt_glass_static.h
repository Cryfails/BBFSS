// SPDX-License-Identifier: GPL-3.0-or-later
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
