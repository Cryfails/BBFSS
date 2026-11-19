// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>

#include "video_core/renderer_vulkan/foliage_mask.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h>

namespace Vulkan {
class Instance;
class Scheduler;
struct RenderState;

// Owned by the ordered renderer. An epoch starts only at a complete receiver boundary.
class FoliageMask {
public:
    static bool Requested();
    static bool Supported(const Instance& instance);

    FoliageMask(const Instance& instance, Scheduler& scheduler);
    ~FoliageMask();
    FoliageMask(const FoliageMask&) = delete;
    FoliageMask& operator=(const FoliageMask&) = delete;

    using Key = FoliageMaskRules::EpochKey;
    using Refusal = FoliageMaskRules::Refusal;

    bool BeginEpoch(const Key& key);
    bool Attach(const Key& key, RenderState& state);
    bool ResumeAttachment(const Key& key, RenderState& state) const;
    void NoteClass(bool tagged);
    void Invalidate(Refusal reason);
    // Only the diagnostic reader can consume tags in this increment.
    vk::ImageView ReadableMask(const Key& key);
    void OnFrameEnd();

    FoliageMaskRules::Diagnostic& Selection() { return diagnostic; }
    Refusal Reason() const { return epoch.Reason(); }

private:
    struct Target {
        vk::Image image{};
        vk::ImageView view{};
        VmaAllocation allocation{};
        vk::Extent2D extent{};
        vk::ImageLayout layout{vk::ImageLayout::eUndefined};
        uint64_t last_tick{};
    };

    bool Allocate(Target& target, vk::Extent2D extent);
    void Destroy(Target& target);
    void Transition(Target& target, vk::ImageLayout layout, bool clear);

    const Instance& instance;
    Scheduler& scheduler;
    std::array<Target, 3> targets{};
    Target* active{};
    FoliageMaskRules::Epoch epoch;
    FoliageMaskRules::Diagnostic diagnostic;
    bool needs_clear{};
};

} // namespace Vulkan
