// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <atomic>
#include <memory>
#include <mutex>
#include <optional>
#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

VK_DEFINE_HANDLE(VmaAllocation)
VK_DEFINE_HANDLE(VmaAllocator)

namespace Vulkan::PostProxyProof {

struct Key {
    u64 request{}, checkpoint{}, frame{};
    explicit operator bool() const { return request && frame; }
    bool operator==(const Key&) const = default;
};

struct Backing {
    vk::Image image{};
    VmaAllocator allocator{};
    VmaAllocation allocation{};
    vk::DeviceMemory memory{};
    u64 offset{}, bytes{};

    explicit operator bool() const {
        return image && allocator && allocation && memory && bytes && offset <= ~u64{} - bytes;
    }
    bool operator==(const Backing&) const = default;
};

inline bool Distinct(const Backing& a, const Backing& b) {
    return a && b && a.allocator == b.allocator && a.image != b.image && a.allocation != b.allocation &&
        (a.memory != b.memory || a.offset + a.bytes <= b.offset || b.offset + b.bytes <= a.offset);
}

inline constexpr vk::ImageSubresourceRange Color0{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};

struct Binding {
    Key key{};
    u64 owner{}, generation{}, incarnation{}, uid{}, native_serial{};
    Backing proxy{}, native{};
    vk::Image image{};
    vk::ImageView view{};
    vk::ImageLayout layout{};
    vk::Extent2D extent{};
    vk::Format format{};
    vk::SampleCountFlagBits samples{};
    vk::ImageSubresourceRange range{};
    bool valid{}, dirty{};

    bool IsOwned() const {
        return key && owner && incarnation && uid && image == proxy.image &&
            view && Distinct(proxy, native) && layout == vk::ImageLayout::eGeneral &&
            extent.width && extent.height && format == vk::Format::eR16G16B16A16Sfloat &&
            samples == vk::SampleCountFlagBits::e1 && range == Color0;
    }
};

struct BackingCheck {
    bool resident{}, coherence_same{}, native_serial_same{};
};

inline BackingCheck Recheck(const Binding& read, const Binding& now) {
    if (!read.IsOwned() || !now.IsOwned() || read.key != now.key || read.owner != now.owner ||
        read.generation != now.generation || read.incarnation != now.incarnation ||
        read.uid != now.uid || read.proxy != now.proxy || read.native != now.native ||
        read.image != now.image || read.view != now.view || read.layout != now.layout ||
        read.range != now.range || read.extent != now.extent) return {};
    return {true, now.valid == read.valid && now.dirty == read.dirty,
        now.native_serial == read.native_serial};
}

struct Order {
    u64 scheduler{}, queue{}, timeline{}, queued_tick{}, cookie{};
    u32 queue_family{};
};

struct Emitted {
    Order order{};
    vk::CommandBuffer command{};
    vk::ImageMemoryBarrier2 barrier{};
    bool encoder_note{};
};

inline bool ReadScope(const Binding& view, const Emitted& actual) {
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    const auto& b = actual.barrier;
    const auto& at = actual.order;
    return actual.command && at.scheduler && at.queue && at.timeline && at.queued_tick && at.cookie &&
        !b.pNext && b.image == view.image && b.subresourceRange == view.range && b.newLayout == view.layout &&
        b.oldLayout != vk::ImageLayout::eUndefined && b.srcStageMask == Stage::eAllCommands &&
        bool(b.srcAccessMask & Access::eMemoryWrite) &&
        bool(b.dstStageMask & (Stage::eComputeShader | Stage::eAllCommands)) &&
        bool(b.dstAccessMask & (Access::eShaderSampledRead | Access::eShaderRead | Access::eMemoryRead)) &&
        b.srcQueueFamilyIndex == b.dstQueueFamilyIndex &&
        (b.srcQueueFamilyIndex == VK_QUEUE_FAMILY_IGNORED || b.srcQueueFamilyIndex == at.queue_family);
}

class Trace {
public:
    explicit Trace(const Order& order_) : order{order_} {}

    const Order order;

    bool Commit(vk::CommandBuffer cmd, const vk::ImageMemoryBarrier2& actual, bool encoder_note) {
        std::scoped_lock lock{mutex};
        if (!cmd || emitted || conflicted) {
            conflicted = true;
            return false;
        }
        emitted = Emitted{order, cmd, actual, encoder_note};
        return true;
    }

    std::optional<Emitted> Read() const {
        std::scoped_lock lock{mutex};
        return conflicted ? std::nullopt : emitted;
    }

private:
    mutable std::mutex mutex;
    std::optional<Emitted> emitted;
    bool conflicted{};
};

inline u64 NextIncarnation() {
    static std::atomic<u64> sequence{1};
    const auto n = sequence.fetch_add(1, std::memory_order_relaxed);
    return n && n <= 0x0000ffffffffffffULL ? n : 0;
}

inline u64 NextCookie() {
    static std::atomic<u64> sequence{1};
    const auto n = sequence.fetch_add(1, std::memory_order_relaxed);
    return n && n <= 0x0000ffffffffffffULL ? (0xd30a000000000000ULL | n) : 0;
}

struct Lease {
    Binding binding{};
    std::shared_ptr<const Trace> trace;

    std::optional<Emitted> Emission(Key key, vk::Image image, vk::ImageView view) const {
        if (!trace || !binding.IsOwned() || !binding.valid || !binding.dirty ||
            binding.key != key || binding.image != image || binding.view != view) return {};
        const auto actual = trace->Read();
        return actual && ReadScope(binding, *actual) ? actual : std::nullopt;
    }
};

} // namespace Vulkan::PostProxyProof
