// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r128a_lrt-moving-shadows): BB_LAMP_SHADOW_JITTER. The lamp pass answers "is this point in shadow" at the
// pixel's centre while the scene the upscaler is fed was drawn through a viewport shifted by its sub-pixel jitter, so a
// lamp shadow's edge is a fixed staircase of render pixels that the upscaler cannot average out and shows where the
// shadow moves (blocky moving edges, 4K DLSS). With the knob on, a pass that averages its history is told this frame's
// and the last frame's jitter (4 words after its history block's tail, word 0 of the block gets HISTORY_JITTER) and
// builds the surface point where the depth value really lies and looks its history up where the last frame's jittered
// sample lay (point_shadow_ray.comp). 0 or not set (the default): nothing here pushes a word or sets a flag. 1 (any
// whole number but 0): on. The jitter is zero without an upscaler: nothing changes then. No Vulkan here.

#include <array>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "bbport_live_knobs.h"

namespace Vulkan {

inline constexpr std::uint32_t LampJitterWords = 4;        ///< the history block's words 34 to 37
inline constexpr std::uint32_t LampHistoryJitterFlag = 32; ///< point_shadow_ray.comp HISTORY_JITTER

namespace LampJitterDetail {
inline std::uint32_t carried = 0;  ///< passes that carried the words since the last periodic line
inline std::uint32_t shifted = 0;  ///< of them, with a shift that is not 0
inline std::uint32_t no_room = 0;  ///< passes the 4 words did not fit after (the data buffer was full)
inline std::uint32_t lines = 0;    ///< periodic lines printed
inline bool have_frame = false;
inline std::uint32_t frame = 0;    ///< the frame the two shifts below belong to
inline std::array<float, 2> now{}; ///< this frame's jitter, render pixels
inline std::array<float, 2> before{}; ///< the jitter of the frame before the last one that had a pass

inline bool Parse(const char* text) noexcept {
    if (!text || !text[0]) {
        return false;
    }
    char* end = nullptr;
    const long value = std::strtol(text, &end, 10);
    return end != text && *end == '\0' && value != 0;
}
} // namespace LampJitterDetail

/// Startup-only path when the live file is absent.
inline bool LampJitterOn() {
    static const bool on = [] {
        const bool value = LampJitterDetail::Parse(std::getenv("BB_LAMP_SHADOW_JITTER"));
        if (value) {
            std::printf("Ray traced lamps (r128a): sample jitter on (BB_LAMP_SHADOW_JITTER): a lamp pass that "
                        "averages its history builds each pixel's surface point where the upscaler's jittered "
                        "scene depth really lies and looks its history up where the last frame's jittered "
                        "sample lay; nothing changes where the jitter is 0 (no upscaler)\n");
        }
        return value;
    }();
    return on;
}

struct LampJitterHistory {
    std::array<float, 2> shift{};
    bool carried = false;
};

/// Read the live knob on the first nonempty Flush of a frame. The sample
/// itself comes from the first history writer that can fit the jitter words.
class LampJitterFrame {
public:
    void Latch(std::uint32_t frame) {
        if (have_frame && frame == index) {
            return;
        }
        have_frame = true;
        index = frame;
        have_sample = false;
        if (live) {
            static BbLiveKnobs::Knob<bool> knob{"BB_LAMP_SHADOW_JITTER", LampJitterDetail::Parse};
            const bool value = knob.Get();
            if (value != enabled) {
                enabled = value;
                namespace D = LampJitterDetail;
                D::carried = D::shifted = D::no_room = 0;
                std::printf("Ray traced lamps (r128a): sample jitter live=%u frame=%u\n",
                            unsigned(enabled), unsigned(frame));
            }
        }
    }

    [[nodiscard]] bool Live() const noexcept { return live; }
    [[nodiscard]] bool On() const { return live ? enabled : LampJitterOn(); }
    [[nodiscard]] std::uint32_t Index() const noexcept { return index; }

    [[nodiscard]] bool Compatible(bool carries, const LampJitterHistory& previous) const noexcept {
        return !live || carries == previous.carried;
    }

    const std::array<float, 2>& Sample(const std::array<float, 2>& jitter) {
        if (!have_sample) {
            sample = jitter;
            have_sample = true;
        }
        return sample;
    }

private:
    static bool LiveFile() {
        static const bool enabled = [] {
            const char* path = std::getenv("BB_LIVE_KNOBS_FILE");
            return path && *path;
        }();
        return enabled;
    }

    std::array<float, 2> sample{};
    std::uint32_t index = 0;
    bool live = LiveFile();
    bool enabled = false;
    bool have_frame = false;
    bool have_sample = false;
};

inline bool LampJitterRoom(std::size_t used, std::size_t limit) noexcept {
    return used <= limit && limit - used >= LampJitterWords;
}

/// vk_point_shadow.cpp calls this right after it pushed the history block (its word 0 is at `history_at`, the tail words
/// 30 to 33 are the last pushed): with the knob on and `blend` (the pass averages) it adds the four words (this frame's
/// jitter x, y; previous jitter x, y) and sets the flag in word 0. For a live knob, previous jitter comes from
/// the history actually read, or the current sample if that history is unavailable. Return what was packed.
inline LampJitterHistory LampJitterAdd(std::vector<std::uint32_t>& data, std::uint32_t history_at,
                                      std::uint32_t limit_words, bool blend, LampJitterFrame& frame,
                                      const std::array<float, 2>& jitter,
                                      const LampJitterHistory* read) {
    namespace D = LampJitterDetail;
    if (!blend || !frame.On()) {
        return {};
    }
    if (!LampJitterRoom(data.size(), limit_words)) {
        ++D::no_room;
        return {};
    }
    if (frame.Live()) {
        D::now = frame.Sample(jitter);
        D::before = read && read->carried ? read->shift : D::now;
    } else if (!D::have_frame || D::frame != frame.Index()) {
        D::before = D::have_frame ? D::now : jitter; // the very first frame has no earlier one (its history is not read)
        D::now = jitter;
        D::frame = frame.Index();
        D::have_frame = true;
    }
    data.push_back(std::bit_cast<std::uint32_t>(D::now[0]));
    data.push_back(std::bit_cast<std::uint32_t>(D::now[1]));
    data.push_back(std::bit_cast<std::uint32_t>(D::before[0]));
    data.push_back(std::bit_cast<std::uint32_t>(D::before[1]));
    data[history_at] |= LampHistoryJitterFlag;
    ++D::carried;
    if (D::now[0] != 0.0f || D::now[1] != 0.0f) {
        ++D::shifted;
    }
    return {D::now, true};
}

/// PointShadow's periodic lamp lines: a short line of its own, only with the knob on.
inline void LampJitterLine(const LampJitterFrame& frame) {
    namespace D = LampJitterDetail;
    if (!frame.On()) {
        return;
    }
    ++D::lines;
    std::printf("Ray traced lamps (r128a): sample jitter carried by %u lamp passes since the last line, %u of them "
                "with a shift that is not 0 (last shift %.2f, %.2f px; before it %.2f, %.2f), %u without room, "
                "line %u\n",
                unsigned(D::carried), unsigned(D::shifted), double(D::now[0]), double(D::now[1]),
                double(D::before[0]), double(D::before[1]), unsigned(D::no_room), unsigned(D::lines));
    D::carried = D::shifted = D::no_room = 0;
}

} // namespace Vulkan
