// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <chrono>
#include <cstdint>

namespace Vulkan::WindowPathProbe {

struct NaturalPanePair {
    using Clock = std::chrono::steady_clock;
    using U64 = std::uint64_t;
    using U32 = std::uint32_t;

    struct Build {
        U64 object_frame = 0, rt_frame = 0, entry = 0, base = 0;
        U32 param = 0, ordinal = 0;
        bool new_entry = false;
    };

    U64 request = 0, arm_frame = 0;
    Clock::time_point deadline{};
    Build build{};
    bool sampled = false;

    void Arm(U64 id, U64 frame, Clock::time_point now) {
        request = id;
        arm_frame = frame;
        deadline = now + std::chrono::seconds(20);
    }
    bool Active() const { return request != 0; }
    bool Latched() const { return build.ordinal != 0; }

    bool Expired(U64 object_frame, U32 frame_budget, Clock::time_point now) const {
        return now >= deadline || object_frame < arm_frame || object_frame - arm_frame >= frame_budget;
    }
    bool Latch(Build candidate) {
        if (!Active() || Latched() || !candidate.object_frame || !candidate.rt_frame ||
            !candidate.param || !candidate.ordinal || !candidate.entry || !candidate.base) {
            return false;
        }
        build = candidate;
        return true;
    }
    bool CanSample(U64 id, U64 object_frame, U64 rt_frame) const {
        return Latched() && !sampled && request == id &&
               build.object_frame == object_frame && build.rt_frame == rt_frame;
    }
    bool MatchBuild(U64 rt_frame, U32 param, U32 ordinal, U64 base) const {
        return Latched() && build.rt_frame == rt_frame && build.param == param &&
               build.ordinal == ordinal && build.base == base;
    }
    bool Closed(U64 rt_frame) const { return Latched() && rt_frame > build.rt_frame; }
};

} // namespace Vulkan::WindowPathProbe

