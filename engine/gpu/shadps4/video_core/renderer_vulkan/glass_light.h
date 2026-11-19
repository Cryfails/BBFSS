// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r130c_glass-lamp-light): lamp light through glass (stage S1 of the glass plan). BB_GLASS_LIGHT=1 (needs the glass
// registry, BB_GLASS_TABLE) makes a lamp's light that crosses a registered glass entry of a transmitting kind (window, bottle,
// lantern, cabinet; not the mirror) tinted by the entry's tint and dimmed by its strength (token sX, 0..1; defaults by kind),
// instead of blocked or passed untouched. No Vulkan here: tests/test_glass_light.cpp builds this header alone and runs the code
// the engine runs. The numbers the shader shares are in host_shaders/glass_light_layout.h.
//
// A tint word (what a lamp ray multiplies by when it crosses the entry): unorm8 R, G, B in bits 0-23 of the linear tint times
// the strength, the entry's kind in bits 24-31 (0: the entry does not transmit). Linear: (c / 255) ^ 2.2.

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

#include "../host_shaders/glass_light_layout.h"
#include "glass_registry.h"
#include "rt_card_uv.h"
#include "rt_glass.h"

namespace Vulkan::GlassLight {

namespace R = GlassRegistryRules;
using u8 = std::uint8_t;
using u32 = std::uint32_t;

inline constexpr u32 IndexBit = GLASS_INDEX_BIT, EntryMask = GLASS_ENTRY_MASK, RayCap = GLASS_RAY_CAP;
inline constexpr u32 WordCount = GLASS_WORDS, FlagActive = GLASS_FLAG_ACTIVE, FlagLampHue = GLASS_FLAG_LAMP_HUE;
inline constexpr u32 RayMask = GLASS_LIGHT_MASK;
inline constexpr float RayTmin = float(GLASS_LIGHT_TMIN);

static_assert(IndexBit == (1u << 23) && IndexBit > CardSlotsMost && CardSlotsMost <= IndexBit,
              "a glass record's custom index never reads as a card slot");
static_assert((IndexBit | EntryMask) < (1u << 24), "instanceCustomIndex has 24 bits");
static_assert(EntryMask + 1 == R::MaxEntries && WordCount == 1 + R::MaxEntries && (IndexBit & EntryMask) == 0);
static_assert(RayMask == RtGlassMask && RayCap >= 1 && FlagActive != FlagLampHue);

/// BB_GLASS_LIGHT's text: 0 off (nullptr, "", "0", "off"), 1 on ("1", "on"), 2 unreadable.
constexpr u8 ParseLight(const char* text) {
    return R::ParseView(text);
}

/// The kinds whose lamp light passes (tinted); the mirror stays opaque.
constexpr bool Transmits(R::Kind kind) {
    return kind == R::Kind::Window || kind == R::Kind::Bottle || kind == R::Kind::Lantern || kind == R::Kind::Cabinet;
}

constexpr float DefaultStrength(R::Kind kind) {
    switch (kind) {
    case R::Kind::Window:
    case R::Kind::Cabinet:
        return 0.90f;
    case R::Kind::Lantern:
        return 0.85f;
    case R::Kind::Bottle:
        return 0.75f;
    default:
        return 0.0f;
    }
}

/// The entry's strength: its s token, else the kind's default.
constexpr float StrengthOf(const R::Entry& entry) {
    return entry.strength >= 0.0f ? entry.strength : DefaultStrength(entry.kind);
}

/// An sRGB hex colour (0xRRGGBB) as linear light: (c / 255) ^ 2.2 each.
inline std::array<float, 3> LinearOf(u32 srgb_hex) {
    const auto one = [](u32 byte) { return std::pow(float(byte & 255u) / 255.0f, 2.2f); };
    return {one(srgb_hex >> 16), one(srgb_hex >> 8), one(srgb_hex)};
}

/// The entry's tint word (see above); 0 for an entry that does not transmit.
inline u32 TintWord(const R::Entry& entry) {
    if (!Transmits(entry.kind)) {
        return 0;
    }
    const std::array<float, 3> lin = LinearOf(entry.tint);
    const float s = StrengthOf(entry);
    u32 word = u32(entry.kind) << 24;
    for (u32 c = 0; c < 3; ++c) {
        const float v = std::clamp(lin[c] * s, 0.0f, 1.0f);
        word |= u32(std::lround(v * 255.0f)) << (8 * c);
    }
    return word;
}

/// The 64 tint words of the table (an unused entry: 0).
inline std::array<u32, R::MaxEntries> Words(const R::Table& table) {
    std::array<u32, R::MaxEntries> words{};
    for (u32 i = 0; i < table.count && i < R::MaxEntries; ++i) {
        words[i] = TintWord(table.entries[i]);
    }
    return words;
}

/// How many entries of the table transmit, and how many stay opaque (the mirror).
constexpr u32 CountTransmitting(const R::Table& table) {
    u32 n = 0;
    for (u32 i = 0; i < table.count; ++i) {
        n += Transmits(table.entries[i].kind) ? 1u : 0u;
    }
    return n;
}

/// A glass record's instanceCustomIndex for the registry entry index `entry` (0 based).
constexpr u32 CustomIndex(u8 entry) {
    return IndexBit | (u32(entry) & EntryMask);
}

constexpr bool IsGlassIndex(u32 custom_index) {
    return (custom_index & IndexBit) != 0;
}

/// The flag word a repair pass pushes after its tuning words.
constexpr u32 Flags(bool active, bool lamp_hue) {
    return (active ? FlagActive : 0u) | (lamp_hue ? FlagLampHue : 0u);
}

static_assert(CustomIndex(5) == 0x800005u && CustomIndex(63) == 0x80003fu && IsGlassIndex(CustomIndex(0)));
static_assert(ParseLight("1") == 1 && ParseLight("") == 0 && ParseLight(nullptr) == 0 && ParseLight("2") == 2);
static_assert(Transmits(R::Kind::Window) && !Transmits(R::Kind::Mirror) && !Transmits(R::Kind::None));
static_assert(Flags(true, true) == 3 && Flags(false, true) == 2 && Flags(false, false) == 0);

} // namespace Vulkan::GlassLight
