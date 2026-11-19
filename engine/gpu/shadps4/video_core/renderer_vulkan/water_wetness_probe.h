// SPDX-License-Identifier: GPL-3.0-or-later
// t133f: private water observation wire format and nonblocking slot ownership.
#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <limits>
#include <optional>

#include "common/types.h"
#include "video_core/renderer_vulkan/caustics_params.h"

namespace BbCaustics::WetnessProbe {
using Clock = std::chrono::steady_clock;
using Time = Clock::time_point;
using namespace std::chrono_literals;
constexpr auto Interval = 250ms;
constexpr auto Duration = 20s;
constexpr u32 MaxAttempts = Duration / Interval;
constexpr u32 SlotCount = 3;
constexpr float Radius = 0.20f;
constexpr float Tolerance = 0.05f;
constexpr u32 ProductionFlags = CAUSTICS_FLAG_SHOW | CAUSTICS_FLAG_PLANE | CAUSTICS_FLAG_MATERIAL |
                                CAUSTICS_FLAG_LAMPS | CAUSTICS_FLAG_RECORDS | CAUSTICS_FLAG_ALBEDO |
                                CAUSTICS_FLAG_PUDDLE | CAUSTICS_FLAG_PUDDLE_PLANE |
                                CAUSTICS_FLAG_WORLD | CAUSTICS_FLAG_MOTION |
                                CAUSTICS_FLAG_WARP_COPY | CAUSTICS_FLAG_WARP | CAUSTICS_FLAG_AMBIENT;
static_assert((ProductionFlags & CAUSTICS_FLAG_WETNESS_PROBE) == 0);
static_assert(offsetof(Push, proj) == 0 && offsetof(Push, frame) == 16 &&
              offsetof(Push, inv_view) == 32 && offsetof(Push, sun) == 80 &&
              offsetof(Push, drift) == 96 && offsetof(Push, gain) == 112 &&
              offsetof(Push, evolve) == 116 && offsetof(Push, flags) == 120 &&
              offsetof(Push, slot) == 124);

struct Point {
    u32 sequence, index, status, reason;
    u32 x, y, depth, expected_z, observed_z;
    std::array<u32, 3> world;
    u32 normal_y, plane_residual, xz_residual, z_residual;
};

struct Result {
    std::array<u32, CAUSTICS_PROBE_HEADER_WORDS> header;
    std::array<Point, CAUSTICS_PROBE_POINTS> points;
};
static_assert(sizeof(Point) == CAUSTICS_PROBE_POINT_WORDS * sizeof(u32));
static_assert(offsetof(Point, x) == 16 && offsetof(Point, world) == 36 &&
              offsetof(Point, normal_y) == 48 && offsetof(Point, z_residual) == 60);
static_assert(offsetof(Result, points) == 64 && sizeof(Result) == 320);

constexpr u64 SliceStride(u64 descriptor_alignment, u64 invalidate_alignment) {
    const u64 alignment = std::max(descriptor_alignment, invalidate_alignment);
    return (sizeof(Result) + alignment - 1) / alignment * alignment;
}

// Every field is captured at issue, including the original view matrix (the shader
// uses the inverse). Vulkan handle values identify the exact references in the crumb.
struct Source {
    u64 image_uid, image, view, proxy_generation;
    u32 frame, pass, depth_id, width, height;
    bool reduced;
    std::array<float, 12> view_matrix;
};

struct Request {
    Source source;
    Push push;
    Time root_time, capture;
    double previous_root_m, previous_root_ms;
};

struct Slot {
    Request request{};
    std::optional<u64> tick;
};

template <typename Range>
bool Finite(const Range& values) {
    return std::ranges::all_of(values, [](float v) { return std::isfinite(v); });
}

inline bool ProjectionValid(const Push& push, const std::array<float, 12>& view) {
    return Finite(push.proj) && Finite(push.frame) && Finite(push.inv_view) && Finite(view) &&
           push.proj[0] != 0.0f && push.proj[1] != 0.0f && push.proj[2] > 0.0f &&
           push.proj[3] < 0.0f && push.frame[0] >= 3.0f && push.frame[1] >= 3.0f;
}

inline bool ExtentMatches(u32 width, u32 height, u32 sampled_width, u32 sampled_height, u32 samples) {
    return width >= 3 && height >= 3 && width == sampled_width && height == sampled_height &&
           samples == 1;
}

inline Push ProbePush(Push push, const Source& source, const std::array<float, 3>& root,
                      float plane, u32 sequence) {
    push.sun = {root[0], root[1], root[2], plane};
    push.drift = {std::bit_cast<float>(source.frame), std::bit_cast<float>(source.pass), Radius,
                  Tolerance};
    push.gain = 0.0f;
    push.evolve = 0.0f;
    push.flags = CAUSTICS_FLAG_WETNESS_PROBE;
    push.slot = sequence;
    return push;
}

inline std::array<u32, CAUSTICS_PROBE_HEADER_WORDS> Header(const Request& req) {
    const auto& push = req.push;
    return {CAUSTICS_PROBE_MAGIC, CAUSTICS_PROBE_VERSION, push.slot, req.source.frame,
            req.source.pass, CAUSTICS_PROBE_POINTS, CAUSTICS_PROBE_POINT_WORDS, 0u,
            std::bit_cast<u32>(push.sun[0]), std::bit_cast<u32>(push.sun[1]),
            std::bit_cast<u32>(push.sun[2]), std::bit_cast<u32>(push.sun[3]),
            std::bit_cast<u32>(Radius), std::bit_cast<u32>(Tolerance), 0u, 0u};
}

enum class Verdict { Water, Rejected, Unknown, Corrupt, Stale };

inline Verdict Validate(const Request& request, const Result& result, Time now) {
    if (result.header != Header(request)) {
        return Verdict::Corrupt;
    }
    bool rejected = false, unknown = false;
    for (u32 i = 0; i < result.points.size(); ++i) {
        const auto& p = result.points[i];
        if (p.sequence != request.push.slot || p.index != i) {
            return Verdict::Corrupt;
        }
        if (p.status == CAUSTICS_PROBE_UNKNOWN) {
            if (p.reason < CAUSTICS_PROBE_PROJECTION || p.reason > CAUSTICS_PROBE_NORMAL ||
                p.world != std::array{CAUSTICS_PROBE_INVALID_FLOAT, CAUSTICS_PROBE_INVALID_FLOAT,
                                      CAUSTICS_PROBE_INVALID_FLOAT} ||
                p.normal_y != CAUSTICS_PROBE_INVALID_FLOAT) {
                return Verdict::Corrupt;
            }
            unknown = true;
            continue;
        }
        if (!((p.status == CAUSTICS_PROBE_WATER && p.reason == CAUSTICS_PROBE_OK) ||
              (p.status == CAUSTICS_PROBE_REJECTED && p.reason == CAUSTICS_PROBE_PREDICATE))) {
            return Verdict::Corrupt;
        }
        if (p.x == 0 || p.y == 0 || p.x >= request.source.width - 1 ||
            p.y >= request.source.height - 1 || !std::isfinite(std::bit_cast<float>(p.normal_y)) ||
            !std::ranges::all_of(p.world, [](u32 word) { return std::isfinite(std::bit_cast<float>(word)); })) {
            return Verdict::Corrupt;
        }
        rejected |= p.status == CAUSTICS_PROBE_REJECTED;
    }
    if (now - request.capture > Interval) {
        return Verdict::Stale;
    }
    return unknown ? Verdict::Unknown : rejected ? Verdict::Rejected : Verdict::Water;
}

struct Session {
    std::array<Slot, SlotCount> slots{};
    std::optional<Time> started;
    std::optional<u32> last_attempt_frame, last_poll_frame;
    Time next_attempt{};
    u32 attempts = 0, sequence = 0;
    bool closed = false;

    bool WindowOpen(Time now) const {
        return started && !closed && now - *started < Duration;
    }
    bool Due(Time now, u32 frame) const {
        return WindowOpen(now) && attempts < MaxAttempts &&
               sequence != std::numeric_limits<u32>::max() &&
               now >= next_attempt && last_attempt_frame != frame;
    }
    void Attempt(Time now, u32 frame) {
        next_attempt = now + Interval;
        last_attempt_frame = frame;
        ++attempts;
    }
    std::optional<u32> FreeSlot() const {
        for (u32 i = 0; i < slots.size(); ++i) {
            if (!slots[i].tick) return i;
        }
        return std::nullopt;
    }
    u32 Pending() const {
        return u32(std::ranges::count_if(slots, [](const Slot& slot) { return slot.tick.has_value(); }));
    }
    template <typename IsFree, typename Read>
    void Poll(u32 frame, IsFree is_free, Read read) {
        if (last_poll_frame == frame) return;
        last_poll_frame = frame;
        for (u32 i = 0; i < slots.size(); ++i) {
            auto& slot = slots[i];
            if (slot.tick && is_free(*slot.tick)) {
                read(i, slot);
                slot.tick.reset();
            }
        }
    }
};
} // namespace BbCaustics::WetnessProbe
