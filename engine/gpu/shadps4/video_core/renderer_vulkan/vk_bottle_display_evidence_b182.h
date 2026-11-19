// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
#include <array>
#include <span>
#include <xxhash.h>

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan::BottleDisplay182 {
inline constexpr u64 Vertex = 0x89cda9e4, Fragment = 0x38d65b32;
inline constexpr size_t ModuleLimit = 16, MaxModuleBytes = 128 * 1024;

struct Module {
    vk::ShaderModule handle{};
    u64 guest{}, permutation{}, digest{};
    u32 bytes{};
    const char* route{};
    explicit operator bool() const { return handle && digest && bytes && route; }
};

inline Module Effective(vk::ShaderModule module, u64 guest, u64 permutation,
                        std::span<const u32> code, const char* route) {
    if (!module || code.size() < 5 || code[0] != 0x07230203 || code.size_bytes() > MaxModuleBytes) return {};
    return {module, guest, permutation, XXH3_64bits(code.data(), code.size_bytes()),
            u32(code.size_bytes()), route};
}

struct Program {
    std::array<Module, 4> stages{};
};

class Modules {
public:
    void Remember(Module actual) {
        if (!actual) return;
        for (size_t i = 0; i < used; ++i) {
            if (entries[i].handle == actual.handle) {
                if (entries[i].guest != actual.guest || entries[i].permutation != actual.permutation ||
                    entries[i].digest != actual.digest || entries[i].bytes != actual.bytes)
                    valid = false;
                return;
            }
        }
        if (used == entries.size()) {
            valid = false;
            return;
        }
        entries[used++] = actual;
    }

    Module Find(vk::ShaderModule handle, u64 guest, u64 permutation) const {
        if (!valid || !handle) return {};
        for (size_t i = 0; i < used; ++i) {
            if (entries[i].handle == handle && entries[i].guest == guest && entries[i].permutation == permutation)
                return entries[i];
        }
        return {};
    }
private:
    std::array<Module, ModuleLimit> entries{};
    size_t used{};
    bool valid{true};
};
struct Read {
    vk::Image image{};
    vk::ImageView view{};
    vk::ImageLayout layout{};
    vk::Format format{};
    u64 uid{}, allocator{}, allocation{}, memory{}, offset{}, bytes{}, write_hint{};
    u32 id{}, type{}, width{}, levels{}, layers{}, base_level{}, base_layer{}, view_levels{}, view_layers{};
    bool known{};
};

struct Sampler {
    vk::Sampler handle{};
    std::array<u32, 4> words{};
    u32 binding{};
    float lod_bias{};
    bool known{};
};

struct Draw {
    Read lut{};
    vk::ImageView ui_redirect{};
    Sampler sampler{};
    Program program{};
    std::array<float, 4> viewport_push{};
    u64 vs{}, vs_permutation{}, ps_permutation{};
    u32 scene_size{}, primitive{}, elements{}, instances{}, first_vertex{}, first_instance{};
    vk::Buffer index{};
    u64 index_offset{};
    vk::IndexType index_type{};
    u32 vertex_buffers{}, attributes{}, cull{}, front_face{}, polygon{}, samples{};
    bool depth_clip{}, depth_clamp{};
    bool indexed{}, restart{}, slot1_matches{}, sampler_matches{}, binder_shape{};
};

inline bool Disjoint(const Read& read, vk::Image other, u64 allocator, u64 allocation,
                     u64 memory, u64 offset, u64 bytes) {
    if (!read.known || !read.image || !other || !allocator || read.allocator != allocator ||
        !allocation || !memory || !bytes || !read.allocation || !read.memory || !read.bytes ||
        read.offset > UINT64_MAX - read.bytes || offset > UINT64_MAX - bytes) return false;
    return read.image != other && read.allocation != allocation &&
           (read.memory != memory || read.offset >= offset + bytes || offset >= read.offset + read.bytes);
}

inline bool RawMutableView(vk::Image backing, vk::Format format, vk::ImageCreateFlags flags,
                           vk::ImageView actual_view, const vk::ImageViewCreateInfo& create) {
    constexpr vk::ComponentMapping channels{vk::ComponentSwizzle::eIdentity, vk::ComponentSwizzle::eIdentity,
                                             vk::ComponentSwizzle::eIdentity, vk::ComponentSwizzle::eOne};
    constexpr vk::ImageSubresourceRange range{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
    return backing && backing == create.image && actual_view && !create.pNext &&
           (flags & vk::ImageCreateFlagBits::eMutableFormat) && format == vk::Format::eR8G8B8A8Srgb &&
           create.format == vk::Format::eB8G8R8A8Srgb && create.viewType == vk::ImageViewType::e2D &&
           create.components == channels && create.subresourceRange == range;
}

} // namespace Vulkan::BottleDisplay182
#endif
