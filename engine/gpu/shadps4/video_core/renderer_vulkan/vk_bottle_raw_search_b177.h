// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#ifdef BB_TEST_BOTTLE_CUT_SOURCE
#include <charconv>
#include <span>
#include <string_view>
#include "video_core/renderer_vulkan/vk_bottle_cold_source_b177.h"
#include "video_core/renderer_vulkan/vk_bottle_cut_present.h"

namespace Vulkan::BottleRawSearch177 {
namespace Present = BottleCutPresent;
namespace Cold = BottleColdSource177;

struct Options {
    u32 request{}, span{};
    Present::Mode mode{};
};

inline std::optional<Options> Parse(std::string_view text, u32 request) {
    const auto first = text.find('/');
    const auto last = text.rfind('/');
    if (!request || first == text.npos || first == last) return {};
    const auto read = [](std::string_view field, u32& value) {
        const auto end = field.data() + field.size();
        const auto [ptr, code] = std::from_chars(field.data(), end, value);
        return code == std::errc{} && ptr == end && value;
    };
    const auto mode = text.substr(first + 1, last - first - 1);
    Options options;
    if (!read(text.substr(0, first), options.request) || options.request != request ||
        !read(text.substr(last + 1), options.span)) return {};
    if (mode == "cut" && options.span <= Present::Capacity) {
        options.mode = Present::Mode::Cut;
    } else if (mode == "off" && options.span <= Present::MaxOff) {
        options.mode = Present::Mode::AllOff;
    } else {
        return {};
    }
    return options;
}

inline std::optional<Present::RawSearch> Project(
    const Cold::Closed& current, const Options& options,
    std::span<const std::array<float, 3>> world_search) {
    using Present::State;
    const auto& frame = current.frame;
    const auto& source = current.source;
    const bool on = current.raw_state == Cold::State::On;
    if (!current.before_display || current.raw_refusal || !current.ordinary_read ||
        (!on && current.raw_state != Cold::State::Off) ||
        !frame || frame.request != options.request || !options.span ||
        (options.mode != Present::Mode::Cut && options.mode != Present::Mode::AllOff) || !current.camera ||
        !current.camera->Valid() || !current.depth.Distinct(current.color) || !source.closed ||
        !source.last_sequence || !source.last_order ||
        source.last_sequence != current.ordinary_read->opportunity ||
        source.last_order.timeline != frame.timeline || source.key.request != frame.request ||
        source.key.load != frame.load || source.key.target_generation != frame.targets ||
        source.key.rt_frame != frame.rt_frame || source.key.object_frame != frame.object_frame ||
        (on && options.mode == Present::Mode::AllOff) ||
        world_search.empty() || world_search.size() > Present::MaxPatches) return {};

    Present::RawSearch result{
        .scene = {source.key, frame.draw_frame, on ? State::On : State::Off,
                  current.first_epoch, current.last_epoch},
        .native_timeline = frame.timeline, .native_tick = source.last_order.tick,
        .native_application = source.last_phase2, .color_uid = current.color.uid,
        .depth_uid = current.depth.uid, .color_parent = current.color.handle, .depth_parent = current.depth.handle,
        .color_allocation = reinterpret_cast<u64>(current.color.allocation),
        .depth_allocation = reinterpret_cast<u64>(current.depth.allocation),
        .ordinary_read_tick = current.ordinary_read->tick,
        .read_color = current.ordinary_read->color.image, .read_depth = current.ordinary_read->depth.image,
        .read_color_view = current.ordinary_read->color.view, .read_depth_view = current.ordinary_read->depth.view,
        .read_color_incarnation = current.ordinary_read->color.incarnation,
        .read_depth_incarnation = current.ordinary_read->depth.incarnation,
        .camera = *current.camera};
    const auto& camera = result.camera;
    for (const auto& world : world_search) {
        std::array<double, 3> p{};
        for (u32 i = 0; i < p.size(); ++i) {
            const auto* row = camera.view.data() + i * 4;
            p[i] = double(row[0]) * world[0] + double(row[1]) * world[1] +
                   double(row[2]) * world[2] + row[3];
        }
        if (!(p[2] > .1) || !std::isfinite(p[2])) return {};
        // The prepared output uses the current unjittered camera. The native receipt
        // retains its separate actual jitter for later depth and application joins.
        const double x = (p[0] * camera.projection[0] / p[2] * .5 + .5) * Present::Extent.width;
        const double y = (p[1] * camera.projection[1] / p[2] * .5 + .5) * Present::Extent.height;
        if (!(x >= 0 && x < Present::Extent.width && y >= 0 && y < Present::Extent.height))
            return {};
        result.centres[result.count++] = vk::Offset2D{s32(x), s32(y)};
    }
    return result.Valid() ? std::optional{result} : std::nullopt;
}
} // namespace Vulkan::BottleRawSearch177
#endif
