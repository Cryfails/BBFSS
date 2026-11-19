// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// bbport (t125_exposure-lock): TOOL (branch dev/test-tools; never a feature branch). BB_TEST_EXPOSURE_LOCK=1
// (live knob, r84) holds the exposure of the tone mapping at the value of the moment the knob went to 1,
// until it is not 1 again: the tone setter's argument (engine/auto_exposure.cpp) and the interior lift
// factor (vk_pipeline_common.cpp). Anything else: every function returns its input.
#include <atomic>
#include <cmath>
#include <cstdio>
#include "bbport_live_knobs.h"

namespace BbTestExposureLock {

inline bool ParseOn(const char* text) noexcept {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}

/// The knob now (one atomic load while the file does not change).
inline bool On() noexcept {
    static BbLiveKnobs::Knob<bool> knob{"BB_TEST_EXPOSURE_LOCK", ParseOn};
    return knob.Get();
}

struct State {
    std::atomic<float> tone{0.0f};  ///< held tone argument; 0: not held
    std::atomic<float> scale{0.0f}; ///< held interior lift factor; 0: not held
    std::atomic<unsigned long long> calls{0};
    std::atomic<bool> engaged{false};
};
inline State& Get() noexcept {
    static State state;
    return state;
}

/// Not "1": forget the held numbers, say so once.
inline void Release() noexcept {
    State& s = Get();
    if (!s.engaged.load(std::memory_order_relaxed) || !s.engaged.exchange(false)) {
        return;
    }
    s.tone.store(0.0f, std::memory_order_relaxed);
    s.scale.store(0.0f, std::memory_order_relaxed);
    std::printf("Test exposure lock (t125): released after %llu held tone calls; the exposure is live again\n",
                s.calls.exchange(0, std::memory_order_relaxed));
}

inline float Hold(std::atomic<float>& slot, float now, const char* what) noexcept {
    float held = slot.load(std::memory_order_relaxed);
    if (!(held > 0.0f)) {
        if (!(now > 0.0f) || !std::isfinite(now)) {
            return now; // nothing sensible to hold yet: stay live
        }
        slot.store(now, std::memory_order_relaxed);
        Get().engaged.store(true, std::memory_order_relaxed);
        std::printf("Test exposure lock (t125, BB_TEST_EXPOSURE_LOCK=1): %s held at %.4f\n", what, now);
        held = now;
    }
    return held;
}

/// The tone setter argument. Call after the hook's own work, on the game's call only.
inline float HoldTone(float now) noexcept {
    if (!On()) {
        Release();
        return now;
    }
    State& s = Get();
    const unsigned long long n = s.calls.fetch_add(1, std::memory_order_relaxed) + 1;
    if (n % 600 == 0) {
        std::printf("Test exposure lock (t125): %llu tone calls held (tone %.4f, interior lift %.4f; 0: not held)\n", n,
                    s.tone.load(std::memory_order_relaxed), s.scale.load(std::memory_order_relaxed));
    }
    return Hold(s.tone, now, "tone exposure");
}

/// The interior lift factor, as BbInteriorExposure::Scale() gives it.
inline float HoldScale(float now) noexcept {
    if (!On()) {
        Release();
        return now;
    }
    return Hold(Get().scale, now, "interior lift factor");
}

} // namespace BbTestExposureLock
