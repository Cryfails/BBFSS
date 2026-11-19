// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <memory>

#include "video_core/renderer_vulkan/ivy_material_probe.h"
#include "video_core/renderer_vulkan/vk_platform.h"

VK_DEFINE_HANDLE(VmaAllocator)
VK_DEFINE_HANDLE(VmaAllocation)

namespace Vulkan {
class Instance;
class Scheduler;
struct RenderState;

namespace IvySampleWitness {
inline constexpr u32 Width = 1920, Height = 1080;
inline constexpr u32 DescriptorSet = 2, Binding = 0;
inline constexpr u32 RoiCount = 16, PerCoordinate = 8, RecordWords = 30;
inline constexpr u32 CountBase = 2 + 2 * RoiCount;
inline constexpr u32 RecordBase = CountBase + RoiCount;
inline constexpr u32 NormalViewRecordWords = 36;
constexpr u32 BufferWordCount(u32 record_words) {
    return RecordBase + RoiCount * PerCoordinate * record_words;
}
constexpr size_t BufferByteCount(u32 record_words) {
    return BufferWordCount(record_words) * sizeof(u32);
}
inline constexpr std::array<vk::Offset2D, RoiCount> Coordinates{{
    {982, 322}, {989, 322}, {995, 322}, {1002, 322},
    {982, 329}, {989, 329}, {995, 329}, {1002, 329},
    {982, 335}, {989, 335}, {995, 335}, {1002, 335},
    {982, 342}, {989, 342}, {995, 342}, {1002, 342},
}};
static_assert(BufferByteCount(RecordWords) == 15560);
static_assert(BufferByteCount(NormalViewRecordWords) == 18632);

struct Variant {
    vk::UniqueDescriptorSetLayout empty_set_one;
    vk::UniqueDescriptorSetLayout sample_set;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    u32 record_words = RecordWords;
};

struct Sample {
    ~Sample();

    std::shared_ptr<const Variant> variant;
    vk::UniqueDescriptorPool pool;
    vk::DescriptorSet descriptor;
    VmaAllocator allocator{};
    VkBuffer buffer{};
    VmaAllocation allocation{};
    const u32* mapped{};
    std::array<float, 2> draw_jitter{};
};

bool MatchesEffective(const IvyMaterialProbe::Module& active);
std::unique_ptr<Sample> Prepare(const Instance& instance, std::shared_ptr<const Variant> variant);
void Retire(Scheduler& scheduler, const RenderState& state, std::unique_ptr<Sample> sample,
            const IvyMaterialProbe::Snapshot& draw, u64 stage, u64 module);
} // namespace IvySampleWitness
} // namespace Vulkan
