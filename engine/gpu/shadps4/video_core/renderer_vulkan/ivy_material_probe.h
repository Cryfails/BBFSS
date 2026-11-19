// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <span>
#include <string>
#include <vector>

namespace Vulkan::IvyMaterialProbe {

inline constexpr uint64_t Vertex = 0xc6cdba2b, Fragment = 0x6720ae0d;
inline constexpr uint32_t First = 2207976, Count = 14868;
inline constexpr size_t ImageCount = 9, MaxSamplers = 9, MaxBuffers = 9;
inline constexpr size_t ConstantCap = 4096, ModuleCap = 128 * 1024, ModuleCount = 4;
inline constexpr unsigned AttemptLimit = 2;

inline bool Wanted() {
    static const bool on = [] {
        const char* knob = std::getenv("BB_IVY_MATERIAL_PROBE");
        return knob && std::strcmp(knob, "1") == 0;
    }();
    return on;
}

constexpr bool Matches(uint64_t vs, uint64_t ps, uint32_t first, uint32_t count, bool indexed) {
    return indexed && vs == Vertex && ps == Fragment && first == First && count == Count;
}

using Bytes = std::span<const uint8_t>;

template <typename T> Bytes ObjectBytes(const T& value) {
    return {reinterpret_cast<const uint8_t*>(&value), sizeof(T)};
}

inline Bytes Words(std::span<const uint32_t> words) {
    return {reinterpret_cast<const uint8_t*>(words.data()), words.size_bytes()};
}

inline unsigned long long Print64(uint64_t value) {
    return static_cast<unsigned long long>(value);
}

inline uint64_t Digest(Bytes bytes) {
    uint64_t hash = 14695981039346656037ULL;
    for (const auto byte : bytes) hash = (hash ^ byte) * 1099511628211ULL;
    return hash;
}

struct Module {
    uint64_t stage{}, handle{}, raw_hash{}, effective_hash{};
    const char* route{};
    const char* emitter{};
    std::vector<uint8_t> raw, effective, profile, runtime;
};

class ModuleBank {
public:
    void Remember(uint64_t stage, uint64_t handle, const char* route, const char* emitter,
                  Bytes raw, Bytes effective, Bytes profile, Bytes runtime) {
        if (!stage || !handle || raw.empty() || effective.empty()) return;
        const std::lock_guard lock(mutex);
        if (finished) return;
        for (const auto& item : modules) {
            if (item && item->stage == stage && item->handle == handle) return;
        }
        if (used == ModuleCount || raw.size() > ModuleCap || effective.size() > ModuleCap ||
            profile.size() > 256 || runtime.size() > 512) {
            if (dropped != std::numeric_limits<unsigned>::max()) ++dropped;
            return;
        }
        auto item = std::make_shared<Module>();
        item->stage = stage;
        item->handle = handle;
        item->route = route;
        item->emitter = emitter;
        item->raw_hash = Digest(raw);
        item->effective_hash = Digest(effective);
        item->effective.assign(effective.begin(), effective.end());
        if (!std::ranges::equal(raw, effective)) {
            item->raw.assign(raw.begin(), raw.end());
        }
        item->profile.assign(profile.begin(), profile.end());
        item->runtime.assign(runtime.begin(), runtime.end());
        modules[used++] = std::move(item);
    }

    struct Selection {
        std::shared_ptr<const Module> module;
        unsigned retained{}, dropped{};
    };

    std::shared_ptr<const Module> Find(uint64_t stage, uint64_t handle) {
        const std::lock_guard lock(mutex);
        for (const auto& item : modules) {
            if (item && item->stage == stage && item->handle == handle) return item;
        }
        return {};
    }

    Selection Take(uint64_t stage, uint64_t handle) {
        const std::lock_guard lock(mutex);
        if (finished) return {};
        finished = true;
        Selection selection{.retained = used, .dropped = dropped};
        for (auto& item : modules) {
            if (item && item->stage == stage && item->handle == handle) {
                selection.module = std::move(item);
            }
            item.reset();
        }
        return selection;
    }

private:
    std::mutex mutex;
    std::array<std::shared_ptr<const Module>, ModuleCount> modules{};
    unsigned used{}, dropped{};
    bool finished{};
};

inline ModuleBank& Modules() {
    static ModuleBank bank;
    return bank;
}

struct Constants {
    uint64_t guest{}, descriptor_offset{}, descriptor_range{}, handle{};
    uint32_t binding{}, shader_offset{}, size{};
    const char* source = "unknown";
    bool seen{};
    std::array<uint8_t, ConstantCap> bytes{};

    const char* Coverage() const {
        if (!size) return "absent";
        return descriptor_range - shader_offset == size ? "full" : "prefix";
    }

    size_t Retainable(uint64_t available) const {
        if (descriptor_range < shader_offset) return 0;
        return std::min({available, descriptor_range - shader_offset, uint64_t(bytes.size())});
    }

    void Copy(Bytes input, const char* label) {
        size = uint32_t(Retainable(input.size()));
        if (!size) return;
        std::memcpy(bytes.data(), input.data(), size);
        source = label;
    }
};

struct Sampler {
    std::array<uint32_t, 4> raw{}, effective{};
    uint64_t handle{};
    uint32_t binding{};
    float lod_bias{};
    bool depth{}, seen{};
};

struct Snapshot {
    uint64_t serial{};
    uint32_t frame{}, ordinal{}, buffers{}, images{}, samplers{}, first_image_binding{};
    std::array<Constants, MaxBuffers> constants{};
    std::array<Sampler, MaxSamplers> sampler{};
    std::array<std::array<uint32_t, 8>, ImageCount> tsharps{};
    std::array<uint8_t, 128> push{};
    size_t push_size{};
    bool tsharps_complete{};
};
static_assert(sizeof(Snapshot) < 40 * 1024);

inline void PrintBlob(const char* kind, uint32_t binding, Bytes bytes,
                      const char* identity = "") {
    constexpr char alphabet[] = "0123456789abcdef";
    constexpr size_t Chunk = 256;
    for (size_t at = 0; at < bytes.size(); at += Chunk) {
        const auto length = std::min(Chunk, bytes.size() - at);
        std::array<char, Chunk * 2 + 1> text{};
        for (size_t i = 0; i < length; ++i) {
            text[i * 2] = alphabet[bytes[at + i] >> 4];
            text[i * 2 + 1] = alphabet[bytes[at + i] & 15];
        }
        std::printf("Ivy material (t133h): blob=%s binding=%u offset=%zu bytes=%zu hex=%s%s\n",
                    kind, binding, at, length, text.data(), identity);
    }
}

} // namespace Vulkan::IvyMaterialProbe
