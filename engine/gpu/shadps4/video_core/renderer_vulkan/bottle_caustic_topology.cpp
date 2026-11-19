// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/bottle_caustic_topology.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>

#include "bbport_toggles.h"

#include "../../../../tools/engine/sha256.h"

namespace Vulkan::BottleCaustic {

namespace {
using ProfileClock = std::chrono::steady_clock;
constexpr std::uint32_t ProfileStride = 4;
constexpr std::uint32_t ProfileSamples = 96;

bool SampleTopology(std::uint32_t& calls) {
    // A finite startup-only probe. Use the ordinary live effect knob to bracket on and off.
    static const bool enabled = [] {
        const char* text = std::getenv("BB_BOTTLE_TOPOLOGY_PROFILE");
        return text && std::strcmp(text, "1") == 0;
    }();
    if (!enabled || calls >= ProfileStride * ProfileSamples) {
        return false;
    }
    const auto index = calls++;
    return index % ProfileStride == 0;
}

template <class Verify>
bool MeasureTopology(const char* stage, std::uint32_t call, std::size_t bytes, Verify verify) {
    const auto frame = BbStats::frame_number.load(std::memory_order_relaxed);
    const auto start = ProfileClock::now();
    const bool match = verify();
    const auto end = ProfileClock::now();
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    std::printf("Bottle topology t161 stage=%s call=%u frame=%u input_bytes=%zu match=%u duration_ns=%lld\n",
                stage, call, frame, bytes, unsigned(match), static_cast<long long>(ns));
    return match;
}
} // namespace

bool Topology::Verify(std::span<const std::uint32_t> indices) {
    if (SampleTopology(guest_calls)) {
        return MeasureTopology(verified.empty() ? "guest-first" : "guest-repeat", guest_calls,
                               indices.size_bytes(), [&] { return VerifyGuest(indices); });
    }
    return VerifyGuest(indices);
}

bool Topology::BuiltListMatches(std::span<const std::uint32_t> indices) const {
    if (SampleTopology(resident_calls)) {
        return MeasureTopology("resident", resident_calls, indices.size_bytes(),
                               [&] { return Matches(indices); });
    }
    return Matches(indices);
}

bool Topology::VerifyGuest(std::span<const std::uint32_t> indices) {
    static_assert(std::endian::native == std::endian::little);
    if (indices.size() != IndexCount) {
        return false;
    }
    if (!verified.empty()) {
        return Matches(indices);
    }
    if (sha256_hex(reinterpret_cast<const std::uint8_t*>(indices.data()), indices.size_bytes()) !=
        "888e4a3bfb21bef7513db66489a3295573f302bace6e6533ff6e9166cbaba09c") {
        return false;
    }
    // MakeEntry normalizes by the minimum and skips repeated-index triangles.
    // Both operations must leave the authored index order and ordinals intact.
    if (*std::ranges::min_element(indices) != 0) {
        return false;
    }
    for (std::size_t i = 0; i < indices.size(); i += 3) {
        if (indices[i] == indices[i + 1] || indices[i + 1] == indices[i + 2] ||
            indices[i + 2] == indices[i]) {
            return false;
        }
    }
    verified.assign(indices.begin(), indices.end());
    return true;
}

} // namespace Vulkan::BottleCaustic
