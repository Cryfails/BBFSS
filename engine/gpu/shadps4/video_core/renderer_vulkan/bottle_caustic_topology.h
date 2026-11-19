// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <bit>
#include <cstdint>
#include <cstring>
#include <span>
#include <utility>
#include <vector>

namespace Vulkan::BottleCaustic {

inline constexpr std::uint64_t VertexShader = 0x9da6aacb;
inline constexpr std::uint64_t PixelShader = 0xca7226ec;
inline constexpr std::uint32_t FirstIndex = 523344;
inline constexpr std::uint32_t IndexCount = 162096;
inline constexpr std::array<std::pair<std::uint32_t, std::uint32_t>, 5> PrimitiveRanges{{
    {9932, 9983}, {10240, 10347}, {37872, 37879}, {41856, 41887}, {48759, 48824},
}};
inline constexpr std::uint32_t BottleTriangles = [] {
    std::uint32_t count = 0;
    for (const auto [first, last] : PrimitiveRanges) {
        count += last - first + 1;
    }
    return count;
}();
inline constexpr std::uint32_t BottleCorners = BottleTriangles * 3;
static_assert(BottleTriangles == 266);

constexpr bool ExactDraw(std::uint64_t vs, std::uint64_t ps, std::uint32_t first, std::uint32_t count) {
    return vs == VertexShader && ps == PixelShader && first == FirstIndex && count == IndexCount;
}

class Topology {
public:
    // The first match is certified by SHA-256. Subsequent matches use the entire
    // saved ordered byte range, including triangles outside the bottle.
    bool Verify(std::span<const std::uint32_t> indices);

    bool BuiltListMatches(std::span<const std::uint32_t> indices) const;

    std::array<std::uint32_t, BottleCorners> Corners() const {
        std::array<std::uint32_t, BottleCorners> corners{};
        std::size_t at = 0;
        for (const auto [first, last] : PrimitiveRanges) {
            for (std::uint32_t i = first * 3; i < (last + 1) * 3; ++i) {
                corners[at++] = verified[i];
            }
        }
        return corners;
    }

private:
    bool VerifyGuest(std::span<const std::uint32_t> indices);

    bool Matches(std::span<const std::uint32_t> indices) const {
        return !verified.empty() && indices.size() == verified.size() &&
               std::memcmp(indices.data(), verified.data(), indices.size_bytes()) == 0;
    }

    std::vector<std::uint32_t> verified;
    std::uint32_t guest_calls = 0;
    mutable std::uint32_t resident_calls = 0;
};

} // namespace Vulkan::BottleCaustic
