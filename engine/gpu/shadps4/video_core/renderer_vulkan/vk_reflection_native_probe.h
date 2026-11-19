// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <cstdlib>
#include <cstring>
#include <optional>

#include "video_core/amdgpu/resource.h"
#include "video_core/renderer_vulkan/vk_reflection_first_hit.h"

namespace VideoCore {
struct Buffer;
}

namespace Vulkan::ReflectionNativeProbe {

inline constexpr u32 WitnessCount = ReflectionFirstHit::PlacedSourceCount;
inline constexpr u32 NoWitness = ~u32{0};
inline constexpr u32 MaxBindings = 4;
inline constexpr u32 MaxBindingBytes = 624;
inline constexpr u32 ReadbackBytes = MaxBindings * MaxBindingBytes;
inline constexpr std::array labels{"mirror", "fireplace", "wall"};

struct Key {
    u64 vs{}, ps{};
    u32 count{}, first{};
    bool operator==(const Key&) const = default;
};

inline u32 Witness(u32 count) {
    switch (count) {
    case 24: return 0;
    case 18282: return 1;
    case 42441: return 2;
    default: return NoWitness;
    }
}

inline u32 Match(Key key) {
    constexpr std::array keys{
        Key{0x9da6aacb, 0xca7226ec, 24, 2440816},
        Key{0x9da6aacb, 0xbb10e440, 18282, 158744},
        Key{0xc829ee58, 0xdbb222eb, 42441, 12368},
    };
    const auto index = Witness(key.count);
    return index != NoWitness && keys[index] == key ? index : NoWitness;
}

inline bool On() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_NATIVE_PROOF");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on;
}

struct Binding {
    const VideoCore::Buffer* buffer{};
    vk::Buffer handle{};
    u64 guest{}, descriptor_offset{}, descriptor_range{};
    u32 ordinal{}, slot{}, adjust{}, guest_bytes{}, effective_bytes{};
    bool range_known{}, gpu_dirty{}, in_place{}, writable{};
};

// A completed, CPU-owned copy used by the descriptor bound for this direct draw.
enum class ObjectOrigin : u8 { Unseen, ConstantRing, StagedCpuCopy, BufferCache, GpuCopy, UnprovenStream };

struct ObjectBinding {
    AmdGpu::Buffer sharp{};
    u64 address{}, range{};
    u32 slot{}, adjust{};
    ObjectOrigin origin{};
    bool complete{};
};

struct ExactObjects {
    static constexpr u32 Object0Bytes = 416, Object3Bytes = 64, UsedObject0Bytes = 24 * sizeof(u32);
    std::array<u8, Object0Bytes> object0{};
    std::array<u8, Object3Bytes> object3{};
    ObjectBinding binding0{}, binding3{};
    bool placement{}, submitted{};
};

inline bool ExactEquivalenceOn() {
    static const bool on = [] {
        const char* flag = std::getenv("BB_REFLECTION_EXACT_EQUIVALENCE");
        return flag && std::strcmp(flag, "1") == 0;
    }();
    return on && ReflectionFirstHit::PlacedOn();
}

struct StampRetry {
    ReflectionFirstHit::Stamp early{};
    u64 prior_frame{}, prior_pass{}, early_tick{};
    u32 validator_reject{};
    const char* failure = "unreached";
    bool attempted{}, current{}, safe{}, palette{}, handle{}, alpha{}, classified{}, reporting{};
};

static_assert(sizeof(std::optional<StampRetry>) <= 208);

inline bool OneFrameBehind(const ReflectionFirstHit::Stamp& prior, u64 generation, u64 frame) {
    return prior.valid_native && prior.pass && prior.generation == generation &&
        frame && prior.frame == frame - 1;
}

inline const char* RetryStampRefusal(const StampRetry& retry, const ReflectionFirstHit::Stamp& stamp) {
    const auto& early = retry.early;
    if (!stamp.valid_native || !stamp.pass || stamp.pass == retry.prior_pass) return "current-pass";
    if (early.generation != stamp.generation) return "current-generation";
    if (early.frame != stamp.frame) return "current-frame";
    if (early.depth != stamp.depth || early.cb0 != stamp.cb0) return "current-target";
    if (early.depth_uid != stamp.depth_uid || early.cb0_uid != stamp.cb0_uid) return "current-uid";
    if (early.depth_image != stamp.depth_image || early.cb0_image != stamp.cb0_image) return "current-image";
    if (early.view != stamp.view) return "current-view";
    if (early.projection != stamp.projection) return "current-projection";
    if (early.extent != stamp.extent) return "current-extent";
    if (early.jitter != stamp.jitter) return "current-jitter";
    return nullptr;
}

struct Draw {
    Key key{};
    ReflectionFirstHit::Stamp stamp{};
    std::array<Binding, MaxBindings> bindings{};
    std::optional<ExactObjects> exact;
    std::optional<StampRetry> stamp_retry;
    u64 serial{}, allocation{}, revision{}, resident_cookie{}, resident_frame{};
    u32 binding_count{}, capture_param{}, stamp_reject{};
    bool trace{}, overflow{}, stamped{}, placement_safe{}, submission_stamp{}, native_entry{};
    const char* readback_reason = "stamp-unavailable";
};

// Exact slots of the three supported vertex palettes. The effective buffer must be the
// actual read-only binding, with no in-place, unknown-range or offset permutation.
inline const Binding* PlacedDescriptor(const Draw& draw) {
    constexpr std::array slots{21u, 18u, 24u};
    static_assert(slots.size() == WitnessCount);
    const u32 target = Match(draw.key);
    if (target == NoWitness || draw.overflow || draw.binding_count != 1) {
        return nullptr;
    }
    const auto& binding = draw.bindings.front();
    return binding.range_known && binding.gpu_dirty && !binding.in_place && !binding.writable &&
           binding.handle && binding.buffer && binding.ordinal == 1 && binding.slot == slots[target] &&
           binding.adjust == 0 && binding.descriptor_offset % 4 == 0 &&
           binding.guest_bytes == ReflectionFirstHit::PaletteBytes &&
           binding.effective_bytes == ReflectionFirstHit::PaletteBytes &&
           binding.descriptor_range == ReflectionFirstHit::PaletteBytes ? &binding : nullptr;
}

inline const Binding* PlacedBinding(const Draw& draw) {
    return draw.placement_safe ? PlacedDescriptor(draw) : nullptr;
}

} // namespace Vulkan::ReflectionNativeProbe
