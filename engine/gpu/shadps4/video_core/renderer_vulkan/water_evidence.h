// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <chrono>
#include <cstdint>

namespace BbWaterEvidence {

using Clock = std::chrono::steady_clock;

/// The budget belongs to one serial. Repeated calls at the same time cannot add samples.
struct Window {
    static constexpr unsigned MaxSamples = 200, MaxEvents = 32;
    static constexpr auto Duration = std::chrono::seconds(20);
    static constexpr auto Interval = std::chrono::milliseconds(100);

    Clock::time_point started{}, next_sample{};
    unsigned samples = 0, events = 0, dropped_events = 0;
    unsigned calls = 0, same_frame_calls = 0, pass = 0;
    std::uint32_t frame = 0;

    bool Open(Clock::time_point now) const { return now - started < Duration; }

    bool Observe(Clock::time_point now, std::uint32_t observed_frame) {
        if (!Open(now)) return false;
        if (calls == 0 || frame != observed_frame) {
            frame = observed_frame;
            pass = 0;
        } else {
            ++same_frame_calls;
        }
        ++calls;
        ++pass;
        if (samples == MaxSamples || now < next_sample) return false;
        ++samples;
        next_sample = now + Interval;
        return true;
    }

    bool Event(Clock::time_point now) {
        if (!Open(now)) return false;
        if (events == MaxEvents) {
            ++dropped_events;
            return false;
        }
        ++events;
        return true;
    }
};

} // namespace BbWaterEvidence
