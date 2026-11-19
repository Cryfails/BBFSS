// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>
#include <limits>

#include "video_core/renderer_vulkan/bottle_caustic_topology.h"

namespace Vulkan::BottleCaustic {

struct ColdSpan {
    std::uint32_t first;
    std::uint32_t count;
    std::uint32_t store;
};

// Ordered indices of the native single-span accessory draw, inclusive endpoints.
inline constexpr std::array<ColdSpan, 3> ColdSpans{{
    {4997, 5192 - 4997 + 1, 0},
    {31206, 31336 - 31206 + 1, 196},
    {63783, 63807 - 63783 + 1, 327},
}};
inline constexpr std::uint32_t ColdVertices = 352;
inline constexpr std::uint32_t ColdSlotBits = 9;
inline constexpr std::uint32_t ColdSlotMask = (1u << ColdSlotBits) - 1;
static_assert(ColdSpans.back().store + ColdSpans.back().count == ColdVertices);
static_assert(ColdVertices <= ColdSlotMask && IndexCount / 3 < (1u << (32 - ColdSlotBits)));

using ColdCornerMap = std::array<std::uint32_t, BottleCorners>;

inline bool MakeColdCornerMap(const ColdCornerMap& corners, std::uint32_t vertex_count,
                              std::int32_t base_vertex, ColdCornerMap& packed) {
    for (const auto& span : ColdSpans) {
        if (span.first + span.count > vertex_count ||
            std::int64_t(base_vertex) + span.first < 0 ||
            std::int64_t(base_vertex) + span.first + span.count - 1 >
                std::numeric_limits<std::int32_t>::max()) {
            return false;
        }
    }
    std::size_t at = 0;
    for (const auto [first, last] : PrimitiveRanges) {
        for (std::uint32_t prim = first; prim <= last; ++prim) {
            for (std::uint32_t corner = 0; corner < 3; ++corner, ++at) {
                bool matched = false;
                for (const auto& span : ColdSpans) {
                    if (corners[at] - span.first < span.count) {
                        const auto slot = span.store + corners[at] - span.first;
                        packed[at] = slot | (corner == 0 ? prim << ColdSlotBits : 0u);
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    return false;
                }
            }
        }
    }
    return at == packed.size();
}

} // namespace Vulkan::BottleCaustic
