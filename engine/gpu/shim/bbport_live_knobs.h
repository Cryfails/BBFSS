// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// bbport (r84_live-test-knobs): TOOL (branch dev/test-tools; never a feature branch or a pull
// request). A test knob that one running game may change between test variants: its reader asks
// this instead of std::getenv. BB_LIVE_KNOBS_FILE and its lines: src/sys/live_knobs.h.
//
// Converting a knob, one at a time (the rule):
//  1. `static const T v = Parse(std::getenv("BB_X")); return v;` becomes
//     `static BbLiveKnobs::Knob<T> v{"BB_X", Parse}; return v.Get();` (T trivially copyable, at
//     most 4 bytes: a number, a mask, a bool; Parse a pure function of the text, nullptr meaning
//     not set). Get() may be called from any thread. Get() parses at
//     its first use and again at the first use after each change of the file, so the value must
//     be asked where it is used (every frame), not copied into a member at construction.
//  2. Find everything the value decides once: members set at construction, resources made at
//     first use with the value of that moment (pipelines, images, buffers), once-lines and their
//     flags. Make what any value needs at its first need, read members again where they are used,
//     and say once-lines again when the value changes (keep the last value seen and compare).
//  3. Leave the knob read once, and say why next to it, when it is read before the watcher starts
//     (static initialization, before runtime_memory_set_gpu_hooks), sizes something that lives
//     for the whole run (pools, device features, the swapchain, threads), or enters a pipeline
//     cache key or anything saved.
//  4. Check it in one slot game: a job action set:BB_X=..., the log line "Live knobs: BB_X=...",
//     then the caller's own line or picture.
// Without BB_LIVE_KNOBS_FILE Generation() stays 0 and Get() parses once, as the static did.
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <type_traits>
#include "../../src/sys/live_knobs.h"

namespace BbLiveKnobs {

/// + 1 at every change of the live knobs file; 0 while none came (or BB_LIVE_KNOBS_FILE not set).
inline std::uint32_t Generation() noexcept {
    return __atomic_load_n(&runtime_live_knobs_generation, __ATOMIC_ACQUIRE);
}

/// A knob's text now: the file's value when the file names the knob (copied), else the
/// environment's.
struct Text {
    bool in_file = false;
    char file[LIVE_KNOB_VALUE_MAX] = {};
    const char* env = nullptr;
    /// As std::getenv gives it: nullptr when neither names the knob; "" for an empty value.
    [[nodiscard]] const char* Get() const noexcept {
        return in_file ? file : env;
    }
};

inline Text Lookup(const char* name) noexcept {
    Text text;
    text.in_file = runtime_live_knob(name, text.file, sizeof(text.file)) != 0;
    if (!text.in_file) {
        text.env = std::getenv(name);
    }
    return text;
}

/// A knob parsed at its first use and again at the first use after each change of the file. The
/// value and the generation it was parsed at are one atomic word, so that threads asking across a
/// change never leave an older value marked with the newer generation (they parse again instead).
template <class T>
class Knob {
    static_assert(std::is_trivially_copyable_v<T> && sizeof(T) <= sizeof(std::uint32_t),
                  "a live knob's value is trivially copyable and at most 4 bytes");

public:
    constexpr Knob(const char* name_, T (*parse_)(const char*)) noexcept
        : name{name_}, parse{parse_} {}
    Knob(const Knob&) = delete;
    Knob& operator=(const Knob&) = delete;

    T Get() noexcept {
        const std::uint32_t now = Generation();
        std::uint64_t state = packed.load(std::memory_order_relaxed);
        if (std::uint32_t(state >> 32) != now) {
            const Text text = Lookup(name);
            const T parsed = parse(text.Get());
            std::uint32_t raw = 0;
            std::memcpy(&raw, &parsed, sizeof(T));
            state = std::uint64_t(now) << 32 | raw;
            packed.store(state, std::memory_order_relaxed);
        }
        const std::uint32_t low = std::uint32_t(state);
        T value{};
        std::memcpy(&value, &low, sizeof(T));
        return value;
    }

private:
    const char* name;
    T (*parse)(const char*);
    /// The generation the value was parsed at (high half; 0xFFFFFFFF: not parsed yet) and the
    /// value's bytes (low half).
    std::atomic<std::uint64_t> packed{0xFFFFFFFF00000000ull};
};

} // namespace BbLiveKnobs
