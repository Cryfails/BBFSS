// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <cstddef>
#include <cstdlib>
#include <optional>
#include <span>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class PipelineCache;

namespace ReflectionDiscard {

inline constexpr size_t ScanWords = 128 * 1024 / sizeof(u32);
inline constexpr u32 RoleCount = 3;

enum class StockRole : u8 { None, Fireplace, Wall };

struct StockFragment {
    StockRole role;
    u64 vertex_guest, fragment_guest;
    u64 vertex_stage, fragment_stage;
    size_t permutation, effective_bytes;
    u64 effective_digest;
};

inline constexpr StockFragment Fireplace{
    StockRole::Fireplace, 0x9da6aacb, 0xbb10e440, 0x000009db8f183eadull, 0x00000bb1033c63beull,
    1, 26028, 0x486418d6758674dbull};
inline constexpr StockFragment Wall{
    StockRole::Wall, 0xc829ee58, 0xdbb222eb, 0x00000c8381b676c7ull, 0x00000dbb15936903ull,
    1, 32724, 0x8d8801e4e9a19afbull};

// Native draw identity is first checked by ReflectionNativeProbe::Match.
constexpr StockRole StockRoleForWitness(u32 witness) {
    switch (witness) {
    case 1: return StockRole::Fireplace;
    case 2: return StockRole::Wall;
    default: return StockRole::None;
    }
}

constexpr const StockFragment* StockFragmentForCreation(u64 guest, u64 stage, size_t permutation) {
    const auto* fragment = guest == Wall.fragment_guest ? &Wall
                         : guest == Fireplace.fragment_guest ? &Fireplace : nullptr;
    return fragment && stage == fragment->fragment_stage && permutation == fragment->permutation
        ? fragment : nullptr;
}

constexpr const StockFragment* StockFragmentForStages(u64 vertex, u64 fragment) {
    if (vertex == Wall.vertex_stage && fragment == Wall.fragment_stage) return &Wall;
    if (vertex == Fireplace.vertex_stage && fragment == Fireplace.fragment_stage) return &Fireplace;
    return nullptr;
}

enum class Verdict : u8 { Unknown, DiscardPresent, CertifiedClear };

constexpr bool EffectiveAlpha(Verdict verdict, bool shared) {
    switch (verdict) {
    case Verdict::CertifiedClear: return false;
    case Verdict::DiscardPresent: return true;
    default: return shared;
    }
}

constexpr u32 GuestRole(u64 guest) {
    switch (guest) {
    case 0xca7226ec: return 0;
    case 0xbb10e440: return 1;
    case 0xdbb222eb: return 2;
    default: return RoleCount;
    }
}

inline bool On() {
    static const bool on = [] {
        const char* value = std::getenv("BB_REFLECTION_FRAGMENT_DISCARD");
        return value && value[0] == '1' && value[1] == '\0';
    }();
    return on;
}

enum class Route : u8 {
    ColdOriginal, ColdHostPatch, ColdUserPatch, ColdReplacement,
    WarmOriginal, WarmHostPatch, WarmReplacement,
};

struct Opcodes {
    bool valid{};
    u32 kill{}, terminate{}, demote{};
};

constexpr Opcodes Scan(std::span<const u32> words) {
    if (words.size() <= 5 || words.size() > ScanWords || words[0] != 0x07230203u) return {};
    Opcodes result{.valid = true};
    for (size_t p = 5; p < words.size();) {
        const u32 count = words[p] >> 16;
        const u32 opcode = words[p] & 0xffffu;
        if (!count || count > words.size() - p) return {};
        // The installed and engine SPIRV-Headers agree on these instruction encodings.
        switch (opcode) {
        case 252: ++result.kill; break;
        case 4416: ++result.terminate; break;
        case 5380: ++result.demote; break;
        default: p += count; continue;
        }
        if (count != 1) return {};
        ++p;
    }
    return result;
}

constexpr bool StockHostPatch(Route route) {
    return route == Route::ColdHostPatch || route == Route::WarmHostPatch;
}

constexpr Verdict Classify(const StockFragment& fragment, Opcodes opcodes, Route route,
                           size_t bytes, u64 digest) {
    if (!opcodes.valid) return Verdict::Unknown;
    if (opcodes.kill || opcodes.terminate || opcodes.demote) return Verdict::DiscardPresent;
    return StockHostPatch(route) && bytes == fragment.effective_bytes &&
        digest == fragment.effective_digest
        ? Verdict::CertifiedClear : Verdict::Unknown;
}

struct Signature {
    const PipelineCache* cache{};
    u64 guest{}, stage{}, handle{}, generation{};
    constexpr bool operator==(const Signature&) const = default;
};

constexpr bool Live(const Signature& selected, const Signature& current, bool replaced) {
    return !replaced && selected.cache && GuestRole(selected.guest) < RoleCount && selected.stage &&
           selected.handle && selected.generation && selected == current;
}

struct Module {
    Signature id;
    size_t permutation{};
    size_t bytes{};
    u64 effective_xxh3{};
    Opcodes opcodes;
    Route route;
    std::optional<bool> warm_raw_discard;
};

struct Pipeline {
    Module fragment;
    vk::ShaderModule vertex{};
    vk::Pipeline handle{};
};

void Observe(const PipelineCache* cache, u64 guest, u64 stage, size_t permutation,
             vk::ShaderModule handle, Route route, std::span<const u32> code,
             std::optional<bool> warm_raw_discard = {});
std::optional<Module> Find(const PipelineCache* cache, u64 guest, u64 stage, vk::ShaderModule handle);
bool Revalidate(const Signature& signature);
void Clear(const PipelineCache* cache);
void Replaced();
const char* Name(Route route);

} // namespace ReflectionDiscard
} // namespace Vulkan
