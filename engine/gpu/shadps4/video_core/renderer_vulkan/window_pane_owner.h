// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstdint>

namespace Vulkan::WindowPathProbe {

enum class PaneOwnerResult { Proven, Contradicted, Ambiguous };

struct OwnerTexel {
    std::uint32_t albedo = 0, depth = 0;
    bool operator==(const OwnerTexel&) const = default;
};

constexpr PaneOwnerResult ClassifyPaneOwner(bool joined, bool primitive, OwnerTexel before,
                                           OwnerTexel after, OwnerTexel final, bool later_writer,
                                           bool coverage_gap) {
    if (!joined) return PaneOwnerResult::Ambiguous;
    if (after != final) return PaneOwnerResult::Contradicted;
    if (!primitive || later_writer || coverage_gap || before.albedo == after.albedo || before.depth == after.depth) {
        return PaneOwnerResult::Ambiguous;
    }
    return PaneOwnerResult::Proven;
}

constexpr const char* OwnerName(PaneOwnerResult result) {
    switch (result) {
    case PaneOwnerResult::Proven: return "proven";
    case PaneOwnerResult::Contradicted: return "contradicted";
    default: return "ambiguous";
    }
}

} // namespace Vulkan::WindowPathProbe

