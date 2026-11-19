// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <chrono>
#include <cstdint>

namespace Vulkan::WindowPathProbe {

// Launch-only state of the cold test. Acquisition resources are created by
// the draw hook only after it consumes an exact indexed camera draw.
struct ColdPaneWatch {
    using Clock = std::chrono::steady_clock;
    using U32 = std::uint32_t;

    struct Pixels {
        U32 id = 0, width = 0, height = 0, x = 0, y = 0;
    };

    Pixels pixels{};
    Clock::time_point deadline{};

    bool Active() const { return pixels.id != 0; }
    void Arm(Pixels request, Clock::time_point now) {
        pixels = request;
        deadline = now + std::chrono::seconds(120);
    }
    bool Expired(Clock::time_point now) const { return Active() && now >= deadline; }
    Pixels Take(bool exact_indexed_camera, Clock::time_point now) {
        if (!Active() || !exact_indexed_camera || Expired(now)) {
            return {};
        }
        const auto request = pixels;
        pixels = {};
        return request;
    }
};

} // namespace Vulkan::WindowPathProbe

