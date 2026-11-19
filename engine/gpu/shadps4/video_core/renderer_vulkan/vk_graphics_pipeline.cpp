// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <bit>
#include <chrono>
#include "video_core/renderer_vulkan/vk_workflow_capture_proof.h"
#include <cmath>
#include "shader_recompiler/native/froyok_composite.h"
#include "shader_recompiler/native/tone_curve.h"
#include <condition_variable>
#include <cstdlib>
#include <deque>
#include <functional>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <sstream>
#include <thread>
#include <utility>
#include <boost/container/small_vector.hpp>
#include <boost/container/static_vector.hpp>

#include "bbport_threads.h"
#include "common/thread.h"
#include "common/serdes.h"
#include "common/assert.h"
#include "shader_recompiler/backend/spirv/emit_spirv_discard_frag.h"
#include "shader_recompiler/backend/spirv/emit_spirv_quad_rect.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/pipeline_compile_queue.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_pipeline_cache.h"
#include "video_core/renderer_vulkan/vk_reflection_fragment_discard.h"
#include "video_core/renderer_vulkan/ivy_material_probe.h"
#include "video_core/renderer_vulkan/ivy_sample_witness.h"
#include "video_core/renderer_vulkan/ivy_sample_witness_data.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_shader_util.h"
#include <vk_mem_alloc.h>

namespace Vulkan {

using Shader::Backend::SPIRV::AuxShaderType;

/// bbport: pipelines first created during play go to compile threads (BB_ASYNC_PIPELINES=0:
/// on the GPU command thread, as before). Pipelines loaded from the cache at startup are
/// always created at once.
bool AsyncPipelinesEnabled() {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_ASYNC_PIPELINES");
        return !(env && env[0] == '0');
    }();
    return enabled;
}

namespace {
/// A graphics pipeline's create info with everything it points to owned by the job.
struct PendingPipeline {
    vk::GraphicsPipelineCreateInfo info;
    boost::container::static_vector<vk::PipelineShaderStageCreateInfo, MaxShaderStages> stages;
    vk::PipelineShaderStageRequiredSubgroupSizeCreateInfo subgroup_size;
    VertexInputs<vk::VertexInputBindingDescription> bindings;
    VertexInputs<vk::VertexInputAttributeDescription> attributes;
    VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT> divisors;
    vk::PipelineVertexInputDivisorStateCreateInfo divisor_state;
    vk::PipelineVertexInputStateCreateInfo vertex_input;
    vk::PipelineInputAssemblyStateCreateInfo input_assembly;
    vk::PipelineTessellationStateCreateInfo tessellation;
    vk::PipelineViewportDepthClipControlCreateInfoEXT clip_control;
    vk::PipelineViewportStateCreateInfo viewport;
    vk::PipelineRasterizationStateCreateInfo raster;
    vk::PipelineRasterizationProvokingVertexStateCreateInfoEXT provoking;
    vk::PipelineRasterizationDepthClipStateCreateInfoEXT depth_clip;
    vk::PipelineMultisampleStateCreateInfo multisample;
    vk::PipelineDepthStencilStateCreateInfo depth_stencil;
    std::array<vk::PipelineColorBlendAttachmentState, AmdGpu::NUM_COLOR_BUFFERS> attachments;
    vk::PipelineColorBlendStateCreateInfo color_blend;
    boost::container::static_vector<vk::DynamicState, 32> dynamic_states;
    vk::PipelineDynamicStateCreateInfo dynamic;
    std::array<vk::Format, Shader::IR::NumRenderTargets> color_formats;
    std::array<vk::SampleCountFlagBits, AmdGpu::NUM_COLOR_BUFFERS> color_samples;
    vk::AttachmentSampleCountInfoAMD mixed_samples;
    vk::PipelineRenderingCreateInfo rendering;
};

/// Compile threads (BB_PIPELINE_THREADS, default a third of the hardware threads, 1-4), first
/// in, first out: the draw that needs a pipeline first gets it first. Never stopped: pipelines
/// destroyed at exit wait for their job (Pipeline::WaitReady).
class PipelineCompiler {
public:
    static PipelineCompiler& Get() {
        static auto* compiler = new PipelineCompiler();
        return *compiler;
    }

    PipelineJobQueue queue;
    u32 threads = 0;

private:
    PipelineCompiler() {
        threads = std::clamp<u32>(BbThreads::Available() / 3, 1, 4);
        if (const char* env = std::getenv("BB_PIPELINE_THREADS"); env && env[0]) {
            threads = std::clamp(std::atoi(env), 1, 16);
        }
        for (u32 i = 0; i < threads; ++i) {
            std::thread([this, i] {
                Common::SetCurrentThreadName(("bb:Pipeline" + std::to_string(i)).c_str());
                for (;;) {
                    queue.Pop()();
                }
            }).detach();
        }
    }
};

} // namespace

void SubmitPipelineJob(const void* owner, std::function<void()> job) {
    pipeline_compile_stats.background.fetch_add(1, std::memory_order_relaxed);
    PipelineCompiler::Get().queue.Push(owner, std::move(job));
}

std::function<void()> TakePipelineJob(const void* owner) {
    // bbport: BB_PIPELINE_TAKE=0: a thread that needs a queued pipeline waits for a compile
    // thread to get to it, as before.
    static const bool enabled = [] {
        const char* env = std::getenv("BB_PIPELINE_TAKE");
        return !(env && env[0] == '0');
    }();
    if (!enabled) {
        return {};
    }
    return PipelineCompiler::Get().queue.Take(owner);
}

u32 PipelineCompileThreads() {
    return PipelineCompiler::Get().threads;
}

static constexpr std::array LogicalStageToStageBit = {
    vk::ShaderStageFlagBits::eFragment,
    vk::ShaderStageFlagBits::eTessellationControl,
    vk::ShaderStageFlagBits::eTessellationEvaluation,
    vk::ShaderStageFlagBits::eVertex,
    vk::ShaderStageFlagBits::eGeometry,
    vk::ShaderStageFlagBits::eCompute,
};

namespace IvySampleWitness {

bool MatchesEffective(const IvyMaterialProbe::Module& active) {
    return std::ranges::equal(active.effective, IvyMaterialProbe::Words(OriginalWords));
}

static bool NormalViewWanted() {
    static const bool wanted = [] {
        const char* value = std::getenv("BB_IVY_NORMAL_VIEW_WITNESS");
        return value && std::strcmp(value, "1") == 0;
    }();
    return wanted;
}

static std::shared_ptr<const Variant> CreateVariant(
    const Instance& instance, const vk::GraphicsPipelineCreateInfo& original,
    const std::array<vk::DescriptorSetLayout, 2>& original_sets,
    const vk::PushConstantRange& pushes, const IvyMaterialProbe::Module& active,
    const Shader::Info& fragment, const Shader::Info& vertex) {
    if (!MatchesEffective(active)) return {};

    const bool normal_view = NormalViewWanted();
    const u32 record_words = normal_view ? NormalViewRecordWords : RecordWords;
    const auto physical = instance.GetPhysicalDevice();
    const auto limits = physical.getProperties().limits;
    // Count all existing buffers as storage for a conservative limit check.
    const auto fragment_buffers = fragment.buffers.size();
    if (!physical.getFeatures().fragmentStoresAndAtomics || limits.maxBoundDescriptorSets < 3 ||
        limits.maxStorageBufferRange < BufferByteCount(record_words) ||
        limits.maxPerStageDescriptorStorageBuffers <= fragment_buffers ||
        limits.maxDescriptorSetStorageBuffers <= fragment_buffers + vertex.buffers.size() ||
        limits.maxPerStageResources <=
            fragment_buffers + fragment.images.size() + fragment.samplers.size()) {
        std::printf("Ivy sample (t133h): refused storage features or limits\n");
        return {};
    }
    // One test pipeline attempt across warm/cold creation. It stays outside all pipeline caches.
    static std::atomic<bool> attempted{};
    if (attempted.exchange(true, std::memory_order_relaxed)) return {};

    const auto refused = [&](const char* step, vk::Result result) -> std::shared_ptr<const Variant> {
        std::printf("Ivy sample (t133h): prepare stage=%llx original_module=%llx "
                    "step=%s vk_result=%d\n", IvyMaterialProbe::Print64(active.stage),
                    IvyMaterialProbe::Print64(active.handle), step, int(result));
        return {};
    };
    const auto device = instance.GetDevice();
    auto variant = std::make_shared<Variant>();
    variant->record_words = record_words;
    std::array<vk::DescriptorSetLayout, 3> layouts{original_sets[0], original_sets[1], {}};
    if (!layouts[1]) {
        auto [result, empty] = device.createDescriptorSetLayoutUnique(vk::DescriptorSetLayoutCreateInfo{});
        if (result != vk::Result::eSuccess) return refused("set-one", result);
        variant->empty_set_one = std::move(empty);
        layouts[1] = *variant->empty_set_one;
    }
    // The original set 0 may be a push layout. Set 2 always uses an allocated descriptor set.
    const vk::DescriptorSetLayoutBinding binding{
        .binding = Binding, .descriptorType = vk::DescriptorType::eStorageBuffer,
        .descriptorCount = 1, .stageFlags = vk::ShaderStageFlagBits::eFragment,
    };
    auto [set_result, set] = device.createDescriptorSetLayoutUnique(
        {.bindingCount = 1, .pBindings = &binding});
    if (set_result != vk::Result::eSuccess) return refused("set-two", set_result);
    variant->sample_set = std::move(set);
    layouts[DescriptorSet] = *variant->sample_set;
    auto [layout_result, layout] = device.createPipelineLayoutUnique({
        .setLayoutCount = u32(layouts.size()), .pSetLayouts = layouts.data(),
        .pushConstantRangeCount = 1, .pPushConstantRanges = &pushes,
    });
    if (layout_result != vk::Result::eSuccess) return refused("pipeline-layout", layout_result);
    variant->layout = std::move(layout);

    const std::span<const u32> shader_words =
        normal_view ? std::span<const u32>{NormalViewWords} : std::span<const u32>{SampleWords};
    auto [shader_result, shader] = device.createShaderModuleUnique(
        {.codeSize = shader_words.size_bytes(), .pCode = shader_words.data()});
    if (shader_result != vk::Result::eSuccess) return refused("shader-module", shader_result);
    std::array<vk::PipelineShaderStageCreateInfo, 2> stages{
        original.pStages[0], original.pStages[1],
    };
    stages[1].module = *shader;
    auto create = original;
    create.pStages = stages.data();
    create.layout = *variant->layout;
    const auto started = std::chrono::steady_clock::now();
    auto [pipeline_result, pipeline] = device.createGraphicsPipelineUnique({}, create);
    const auto elapsed = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now() - started).count();
    std::printf("Ivy sample (t133h): prepare stage=%llx original_module=%llx "
                "effective=%016llx witness=%016llx vk_result=%d pipeline_us=%lld\n",
                IvyMaterialProbe::Print64(active.stage), IvyMaterialProbe::Print64(active.handle),
                IvyMaterialProbe::Print64(active.effective_hash),
                IvyMaterialProbe::Print64(IvyMaterialProbe::Digest(IvyMaterialProbe::Words(shader_words))),
                int(pipeline_result), static_cast<long long>(elapsed));
    if (pipeline_result != vk::Result::eSuccess) return {};
    variant->pipeline = std::move(pipeline);
    return variant;
}

Sample::~Sample() {
    pool.reset();
    if (buffer) vmaDestroyBuffer(allocator, buffer, allocation);
}

std::unique_ptr<Sample> Prepare(const Instance& instance, std::shared_ptr<const Variant> variant) {
    auto sample = std::make_unique<Sample>();
    sample->variant = std::move(variant);
    const size_t buffer_bytes = BufferByteCount(sample->variant->record_words);
    sample->allocator = instance.GetAllocator();
    const VkBufferCreateInfo buffer_info{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = buffer_bytes, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    };
    const VmaAllocationCreateInfo memory{
        .flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT,
        .usage = VMA_MEMORY_USAGE_AUTO,
    };
    VmaAllocationInfo allocation_info{};
    if (vmaCreateBuffer(sample->allocator, &buffer_info, &memory, &sample->buffer,
                        &sample->allocation, &allocation_info) != VK_SUCCESS ||
        !allocation_info.pMappedData) {
        return {};
    }
    std::array<u32, BufferWordCount(NormalViewRecordWords)> seed{};
    seed[0] = RoiCount;
    for (u32 i = 0; i < RoiCount; ++i) {
        seed[2 + 2*i] = u32(Coordinates[i].x);
        seed[3 + 2*i] = u32(Coordinates[i].y);
    }
    std::memcpy(allocation_info.pMappedData, seed.data(), buffer_bytes);
    // The write and flush precede queue submission, which publishes the mapped initialization.
    if (vmaFlushAllocation(sample->allocator, sample->allocation, 0, buffer_bytes) != VK_SUCCESS) {
        return {};
    }
    sample->mapped = static_cast<const u32*>(allocation_info.pMappedData);

    const auto device = instance.GetDevice();
    const vk::DescriptorPoolSize size{vk::DescriptorType::eStorageBuffer, 1};
    auto [pool_result, pool] = device.createDescriptorPoolUnique(
        {.maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &size});
    if (pool_result != vk::Result::eSuccess) return {};
    sample->pool = std::move(pool);
    const vk::DescriptorSetLayout layout = *sample->variant->sample_set;
    const vk::DescriptorSetAllocateInfo allocate{
        .descriptorPool = *sample->pool, .descriptorSetCount = 1, .pSetLayouts = &layout,
    };
    if (device.allocateDescriptorSets(&allocate, &sample->descriptor) != vk::Result::eSuccess) {
        return {};
    }
    const vk::DescriptorBufferInfo desc{vk::Buffer{sample->buffer}, 0, buffer_bytes};
    const vk::WriteDescriptorSet write{
        .dstSet = sample->descriptor, .dstBinding = Binding, .descriptorCount = 1,
        .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &desc,
    };
    device.updateDescriptorSets(write, {});
    return sample;
}

// The fragment writer increments the count before storing and marks every slot beyond eight.
static std::optional<u32> ValidatedRecordCount(std::span<const u32> words, u32 record_words) {
    static_assert(RoiCount == 16 && PerCoordinate == 8 &&
                  RecordWords == 30 && NormalViewRecordWords == 36);
    constexpr u32 overflow_mask = (1u << RoiCount) - 1;
    if (words.size_bytes() != BufferByteCount(record_words) || words[0] != RoiCount ||
        (words[1] & ~overflow_mask) != 0) {
        return std::nullopt;
    }

    u32 records = 0;
    for (u32 i = 0; i < RoiCount; ++i) {
        const u32 x = words[2 + 2 * i];
        const u32 y = words[3 + 2 * i];
        const u32 count = words[CountBase + i];
        const bool overflow = (words[1] & (1u << i)) != 0;
        if (x >= Width || y >= Height || x != u32(Coordinates[i].x) || y != u32(Coordinates[i].y) ||
            overflow != (count > PerCoordinate)) {
            return std::nullopt;
        }
        const u32 stored = std::min(count, PerCoordinate);
        const auto fields = words.subspan(RecordBase + i * PerCoordinate * record_words,
                                          stored * record_words);
        for (const u32 bits : fields) {
            if (!std::isfinite(std::bit_cast<float>(bits))) {
                return std::nullopt;
            }
        }
        records += stored;
    }
    return records;
}

void Retire(Scheduler& scheduler, const RenderState& state, std::unique_ptr<Sample> sample,
            const IvyMaterialProbe::Snapshot& draw, u64 stage, u64 module) {
    using Stage = vk::PipelineStageFlagBits2;
    using Access = vk::AccessFlagBits2;
    const u32 record_words = sample->variant->record_words;
    const size_t buffer_bytes = BufferByteCount(record_words);
    const bool visible = scheduler.SuspendRenderingForReadback(state);
    if (visible) {
        // This barrier must be outside rendering. Preserve attachment visibility on STORE/LOAD.
        scheduler.Record([buffer = vk::Buffer{sample->buffer}, buffer_bytes](vk::CommandBuffer cmd) {
            constexpr auto attachment_stages = Stage::eColorAttachmentOutput |
                Stage::eEarlyFragmentTests | Stage::eLateFragmentTests;
            constexpr auto attachment_writes = Access::eColorAttachmentWrite |
                Access::eDepthStencilAttachmentWrite;
            const vk::MemoryBarrier2 attachment{
                .srcStageMask = attachment_stages, .srcAccessMask = attachment_writes,
                .dstStageMask = attachment_stages, .dstAccessMask = attachment_writes |
                    Access::eColorAttachmentRead | Access::eDepthStencilAttachmentRead,
            };
            const vk::BufferMemoryBarrier2 read{
                .srcStageMask = Stage::eFragmentShader, .srcAccessMask = Access::eShaderStorageWrite,
                .dstStageMask = Stage::eHost, .dstAccessMask = Access::eHostRead,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .buffer = buffer, .offset = 0, .size = buffer_bytes,
            };
            cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &attachment,
                                  .bufferMemoryBarrierCount = 1, .pBufferMemoryBarriers = &read});
        });
    }
    const auto tick = scheduler.CurrentTick();
    scheduler.DeferOperation([sample = std::move(sample), visible, record_words, buffer_bytes, serial = draw.serial,
                              frame = draw.frame, ordinal = draw.ordinal, tick, stage, module] {
        using namespace IvyMaterialProbe;
        const auto [jitter_x, jitter_y] = sample->draw_jitter;
        // Give every chunk the captured draw identity. The SSBO itself carries no phase tag.
        char identity[256];
        std::snprintf(identity, sizeof(identity),
                      " serial=%llu frame=%u draw=%u stage=%llx original_module=%llx tick=%llu "
                      "coords=native extent=%ux%u jitter=%.6f,%.6f jitter_bits=%08x,%08x ownership=unjoined",
                      Print64(serial), frame, ordinal, Print64(stage), Print64(module), Print64(tick),
                      Width, Height, double(jitter_x), double(jitter_y),
                      std::bit_cast<u32>(jitter_x), std::bit_cast<u32>(jitter_y));
        if (!visible || vmaInvalidateAllocation(sample->allocator, sample->allocation, 0,
                                                buffer_bytes) != VK_SUCCESS) {
            std::printf("Ivy sample (t133h):%s status=unavailable reason=%s\n", identity,
                        visible ? "invalidate" : "visibility");
            return;
        }
        const std::span<const u32> words{sample->mapped, BufferWordCount(record_words)};
        const auto records = ValidatedRecordCount(words, record_words);
        if (!records) {
            std::printf("Ivy sample (t133h):%s status=unavailable reason=invalid-ssbo\n", identity);
            return;
        }
        const char* status = words[1] ? "overflow" : (*records ? "delivered" : "empty");
        const char* layout = record_words == NormalViewRecordWords ? " layout=t170-normal-view" : "";
        std::printf("Ivy sample (t133h):%s records=%u overflow=%04x bytes=%zu status=%s pipeline=private%s\n",
                    identity, *records, words[1], words.size_bytes(), status, layout);
        PrintBlob("sample-ssbo", 0, Words(words), identity);
    }, "t133h ivy sample", false);
}
} // namespace IvySampleWitness

GraphicsPipeline::GraphicsPipeline(
    const Instance& instance, Scheduler& scheduler, DescriptorHeap& desc_heap,
    const Shader::Profile& profile, const GraphicsPipelineKey& key_,
    vk::PipelineCache pipeline_cache, std::span<const Shader::Info*, MaxShaderStages> infos,
    std::span<const Shader::RuntimeInfo, MaxShaderStages> runtime_infos,
    std::optional<const Shader::Gcn::FetchShaderData> fetch_shader_,
    std::span<const vk::ShaderModule> modules, SerializationSupport& sdata, bool preloading,
    WorkflowCapture::Route capture_proof_, const PipelineCache* module_owner)
    : Pipeline{instance, scheduler, desc_heap, profile, pipeline_cache}, key{key_},
      capture_proof{capture_proof_}, fetch_shader{std::move(fetch_shader_)} {
    const vk::Device device = instance.GetDevice();
    std::ranges::copy(infos, stages.begin());
    BuildDescSetLayout(preloading);
    const auto debug_str = GetDebugString();

    // bbport: a composite with the tone curve extension reads its parameters after the push
    // data (native/tone_curve.h).
    uses_tone_curve = std::ranges::any_of(stages, [](const Shader::Info* info) {
        return info && info->uses_tone_curve;
    });
    uses_froyok_bloom = std::ranges::any_of(stages, [](const Shader::Info* info) {
        return info && info->uses_froyok_bloom;
    });
    ASSERT(!key.foliage_mask || (!uses_tone_curve && !uses_froyok_bloom));
    const vk::PushConstantRange push_constants = {
        .stageFlags = AllGraphicsStageBits,
        .offset = 0,
        .size = u32(uses_froyok_bloom ? Shader::Native::FroyokPushOffset +
                                           sizeof(Shader::Native::FroyokPush)
                                     : uses_tone_curve ? Shader::Native::ToneCurvePushOffset +
                                                             sizeof(Shader::Native::ToneCurvePush)
                                                       : key.foliage_mask ? Shader::FoliageMaskOutput::PushSize
                                                                          : sizeof(Shader::PushData)),
    };

    std::array<vk::DescriptorSetLayout, 2> set_layouts{*desc_layout, {}};
    if (key.motion_vectors) {
        motion_address_layout = ObjectMotion::CreateAddressLayout(device);
        set_layouts[Shader::MotionVectors::DescriptorSet] = *motion_address_layout;
    }
    const vk::PipelineLayoutCreateInfo layout_info = {
        .setLayoutCount = key.motion_vectors ? 2U : 1U,
        .pSetLayouts = set_layouts.data(),
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &push_constants,
    };
    auto [layout_result, layout] = instance.GetDevice().createPipelineLayoutUnique(layout_info);
    ASSERT_MSG(layout_result == vk::Result::eSuccess,
               "Failed to create graphics pipeline layout: {}", vk::to_string(layout_result));
    pipeline_layout = std::move(layout);
    SetObjectName(device, *pipeline_layout, "Graphics PipelineLayout {}", debug_str);

    if (!preloading) {
        VertexInputs<AmdGpu::Buffer> guest_buffers;
        if (!instance.IsVertexInputDynamicState()) {
            const auto& vs_info = runtime_infos[u32(Shader::SwStage::Vertex)].sw.vs;
            GetVertexInputs(sdata.vertex_attributes, sdata.vertex_bindings, sdata.divisors,
                            guest_buffers, vs_info.step_rate_0, vs_info.step_rate_1);
        }
    }

    const vk::PipelineVertexInputDivisorStateCreateInfo divisor_state = {
        .vertexBindingDivisorCount = static_cast<u32>(sdata.divisors.size()),
        .pVertexBindingDivisors = sdata.divisors.data(),
    };

    const vk::PipelineVertexInputStateCreateInfo vertex_input_info = {
        .pNext = sdata.divisors.empty() ? nullptr : &divisor_state,
        .vertexBindingDescriptionCount = static_cast<u32>(sdata.vertex_bindings.size()),
        .pVertexBindingDescriptions = sdata.vertex_bindings.data(),
        .vertexAttributeDescriptionCount = static_cast<u32>(sdata.vertex_attributes.size()),
        .pVertexAttributeDescriptions = sdata.vertex_attributes.data(),
    };

    const auto topology = LiverpoolToVK::PrimitiveType(key.prim_type);
    const vk::PipelineInputAssemblyStateCreateInfo input_assembly = {
        .topology = topology,
    };

    const bool is_rect_list = key.prim_type == AmdGpu::PrimitiveType::RectList;
    const bool is_quad_list = key.prim_type == AmdGpu::PrimitiveType::QuadList;
    const vk::PipelineTessellationStateCreateInfo tessellation_state = {
        .patchControlPoints = is_rect_list ? 3U : (is_quad_list ? 4U : key.patch_control_points),
    };

    vk::StructureChain raster_chain = {
        vk::PipelineRasterizationStateCreateInfo{
            .depthClampEnable = key.depth_clamp_enable &&
                                (!key.depth_clip_enable || instance.IsDepthClipEnableSupported()),
            .rasterizerDiscardEnable = false,
            .polygonMode = LiverpoolToVK::PolygonMode(key.polygon_mode),
            .lineWidth = 1.0f,
        },
        vk::PipelineRasterizationProvokingVertexStateCreateInfoEXT{
            .provokingVertexMode = key.provoking_vtx_last == AmdGpu::ProvokingVtxLast::First
                                       ? vk::ProvokingVertexModeEXT::eFirstVertex
                                       : vk::ProvokingVertexModeEXT::eLastVertex,
        },
        vk::PipelineRasterizationDepthClipStateCreateInfoEXT{
            .depthClipEnable = key.depth_clip_enable,
        },
    };

    if (!instance.IsProvokingVertexSupported()) {
        raster_chain.unlink<vk::PipelineRasterizationProvokingVertexStateCreateInfoEXT>();
    }
    if (!instance.IsDepthClipEnableSupported()) {
        raster_chain.unlink<vk::PipelineRasterizationDepthClipStateCreateInfoEXT>();
    }

    if (!preloading) {
        const auto& fs_info = runtime_infos[u32(Shader::SwStage::Fragment)].hw.fs;
        sdata.multisampling = {
            .rasterizationSamples = LiverpoolToVK::NumSamples(
                key.num_samples, instance.GetColorSampleCounts() & instance.GetDepthSampleCounts()),
            .sampleShadingEnable =
                fs_info.addr_flags.persp_sample_ena || fs_info.addr_flags.linear_sample_ena,
        };
    }

    const vk::PipelineViewportDepthClipControlCreateInfoEXT clip_control = {
        .negativeOneToOne = key.clip_space == AmdGpu::ClipSpace::MinusWToW,
    };

    const vk::PipelineViewportStateCreateInfo viewport_info = {
        .pNext = instance.IsDepthClipControlSupported() ? &clip_control : nullptr,
    };

    boost::container::static_vector<vk::DynamicState, 32> dynamic_states = {
        vk::DynamicState::eViewportWithCount,  vk::DynamicState::eScissorWithCount,
        vk::DynamicState::eBlendConstants,     vk::DynamicState::eDepthTestEnable,
        vk::DynamicState::eDepthWriteEnable,   vk::DynamicState::eDepthCompareOp,
        vk::DynamicState::eDepthBiasEnable,    vk::DynamicState::eDepthBias,
        vk::DynamicState::eStencilTestEnable,  vk::DynamicState::eStencilReference,
        vk::DynamicState::eStencilCompareMask, vk::DynamicState::eStencilWriteMask,
        vk::DynamicState::eStencilOp,          vk::DynamicState::eCullMode,
        vk::DynamicState::eFrontFace,          vk::DynamicState::eRasterizerDiscardEnable,
        vk::DynamicState::eLineWidth,          vk::DynamicState::ePrimitiveRestartEnable,
    };

    if (instance.IsDepthBoundsSupported()) {
        dynamic_states.push_back(vk::DynamicState::eDepthBoundsTestEnable);
        dynamic_states.push_back(vk::DynamicState::eDepthBounds);
    }
    if (instance.IsDynamicColorWriteMaskSupported()) {
        dynamic_states.push_back(vk::DynamicState::eColorWriteMaskEXT);
    }
    if (instance.IsVertexInputDynamicState()) {
        dynamic_states.push_back(vk::DynamicState::eVertexInputEXT);
    } else if (!sdata.vertex_bindings.empty()) {
        dynamic_states.push_back(vk::DynamicState::eVertexInputBindingStride);
    }

    const vk::PipelineDynamicStateCreateInfo dynamic_info = {
        .dynamicStateCount = static_cast<u32>(dynamic_states.size()),
        .pDynamicStates = dynamic_states.data(),
    };

    boost::container::static_vector<vk::PipelineShaderStageCreateInfo, MaxShaderStages>
        shader_stages;
    auto stage = u32(Shader::SwStage::Vertex);
    if (infos[stage]) {
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eVertex,
            .module = modules[stage],
            .pName = "main",
        });
    }
    stage = u32(Shader::SwStage::Geometry);
    if (infos[stage]) {
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eGeometry,
            .module = modules[stage],
            .pName = "main",
        });
    }
    stage = u32(Shader::SwStage::TessellationControl);
    if (infos[stage]) {
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eTessellationControl,
            .module = modules[stage],
            .pName = "main",
        });
    } else if (is_rect_list || is_quad_list) {
        const auto type = is_quad_list ? AuxShaderType::QuadListTCS : AuxShaderType::RectListTCS;
        if (!preloading) {
            const auto& fs_info = runtime_infos[u32(Shader::SwStage::Fragment)].hw.fs;
            sdata.tcs = Shader::Backend::SPIRV::EmitAuxilaryTessShader(type, fs_info);
        }
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eTessellationControl,
            .module = CompileSPV(sdata.tcs, instance.GetDevice()),
            .pName = "main",
        });
    }
    stage = u32(Shader::SwStage::TessellationEval);
    if (infos[stage]) {
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eTessellationEvaluation,
            .module = modules[stage],
            .pName = "main",
        });
    } else if (is_rect_list || is_quad_list) {
        if (!preloading) {
            const auto& fs_info = runtime_infos[u32(Shader::SwStage::Fragment)].hw.fs;
            sdata.tes = Shader::Backend::SPIRV::EmitAuxilaryTessShader(
                AuxShaderType::PassthroughTES, fs_info);
        }
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eTessellationEvaluation,
            .module = CompileSPV(sdata.tes, instance.GetDevice()),
            .pName = "main",
        });
    }
    stage = u32(Shader::SwStage::Fragment);
    if (infos[stage]) {
        if (infos[stage]->pgm_hash == IvyMaterialProbe::Fragment && IvyMaterialProbe::Wanted()) {
            ivy_fragment_module = std::bit_cast<u64>(modules[stage]);
        }
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eFragment,
            .module = modules[stage],
            .pName = "main",
        });
    } else if (runtime_infos[u32(Shader::SwStage::Fragment)].hw.fs.clip_distance_emulation ||
               !sdata.fragment.empty()) {
        if (!preloading) {
            const auto& vs = runtime_infos[static_cast<u32>(Shader::SwStage::Vertex)].hw.vs;

            sdata.fragment = Shader::Backend::SPIRV::EmitDiscardFragmentShader(vs.outputs);
        }
        shader_stages.emplace_back(vk::PipelineShaderStageCreateInfo{
            .stage = vk::ShaderStageFlagBits::eFragment,
            .module = CompileSPV(sdata.fragment, instance.GetDevice()),
            .pName = "main",
        });
    }

#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    constexpr auto bottle_vs = u32(Shader::SwStage::Vertex), bottle_ps = u32(Shader::SwStage::Fragment);
    constexpr auto bottle_tcs = u32(Shader::SwStage::TessellationControl);
    constexpr auto bottle_tes = u32(Shader::SwStage::TessellationEval);
    if (is_rect_list && module_owner && !key.foliage_mask && infos[bottle_vs] && infos[bottle_ps] &&
        infos[bottle_vs]->pgm_hash == BottleDisplay182::Vertex &&
        infos[bottle_ps]->pgm_hash == BottleDisplay182::Fragment &&
        !infos[bottle_tcs] && !infos[bottle_tes] && shader_stages.size() == 4 &&
        shader_stages[0].stage == vk::ShaderStageFlagBits::eVertex &&
        shader_stages[1].stage == vk::ShaderStageFlagBits::eTessellationControl &&
        shader_stages[2].stage == vk::ShaderStageFlagBits::eTessellationEvaluation &&
        shader_stages[3].stage == vk::ShaderStageFlagBits::eFragment &&
        module_owner->BottleDisplayEvidenceEnabled()) {
        using namespace BottleDisplay182;
        bottle_display_program = std::make_unique<const BottleDisplay182::Program>(BottleDisplay182::Program{{
            module_owner->FindBottleDisplayModule(shader_stages[0].module, Vertex, key.stage_hashes[bottle_vs]),
            Effective(shader_stages[1].module, 0, 0, sdata.tcs, preloading ? "warm-rect-tcs" : "cold-rect-tcs"),
            Effective(shader_stages[2].module, 0, 0, sdata.tes, preloading ? "warm-rect-tes" : "cold-rect-tes"),
            module_owner->FindBottleDisplayModule(shader_stages[3].module, Fragment, key.stage_hashes[bottle_ps]),
        }});
    }

#endif

    if (WorkflowCapture::Atomic(capture_proof) &&
        (shader_stages.size() != 2 || shader_stages[0].stage != vk::ShaderStageFlagBits::eVertex ||
         shader_stages[1].stage != vk::ShaderStageFlagBits::eFragment)) {
        capture_proof = WorkflowCapture::Route::Scope;
    }
    const vk::PipelineShaderStageRequiredSubgroupSizeCreateInfo subgroup_size_ci = {
        .requiredSubgroupSize = 64,
    };
    for (auto& stage : shader_stages) {
        stage.pNext = instance.IsSubgroupSize64Supported() ? &subgroup_size_ci : nullptr;
    }

    constexpr u32 discard_vs = u32(Shader::SwStage::Vertex), discard_ps = u32(Shader::SwStage::Fragment);
    const bool original_pair = module_owner && infos[discard_vs] && infos[discard_ps] &&
        !key.foliage_mask && shader_stages.size() == 2 &&
        shader_stages[0].stage == vk::ShaderStageFlagBits::eVertex &&
        shader_stages[1].stage == vk::ShaderStageFlagBits::eFragment && modules[discard_vs] &&
        shader_stages[0].module == modules[discard_vs] && shader_stages[1].module == modules[discard_ps];
    if (original_pair) {
        const auto* role = ReflectionDiscard::StockFragmentForStages(
            key.stage_hashes[discard_vs], key.stage_hashes[discard_ps]);
        if (role && infos[discard_vs]->pgm_hash == role->vertex_guest &&
            infos[discard_ps]->pgm_hash == role->fragment_guest) {
            stock_fragment_verdict = module_owner->ResolveStockFragment(*role, shader_stages[1].module);
            if (stock_fragment_verdict != ReflectionDiscard::Verdict::Unknown) {
                stock_fragment_role = role->role;
                stock_fragment_owner = module_owner;
            }
        }
    }
    if (original_pair && ReflectionDiscard::On() &&
        ReflectionDiscard::GuestRole(infos[discard_ps]->pgm_hash) < ReflectionDiscard::RoleCount) {
        const auto module = ReflectionDiscard::Find(module_owner, infos[discard_ps]->pgm_hash,
            key.stage_hashes[discard_ps], shader_stages[1].module);
        if (module) {
            reflection_discard = std::make_unique<const ReflectionDiscard::Pipeline>(
                ReflectionDiscard::Pipeline{.fragment = *module, .vertex = shader_stages[0].module});
        }
    }

    const auto depth_format =
        instance.GetSupportedFormat(LiverpoolToVK::DepthFormat(key.z_format, key.stencil_format),
                                    vk::FormatFeatureFlagBits2::eDepthStencilAttachment);
    const u32 host_attachment_count = key.HostColorAttachmentCount();
    const auto is_mask = [&](u32 i) {
        return key.foliage_mask && i == Shader::FoliageMaskOutput::Location;
    };
    std::array<vk::Format, Shader::IR::NumRenderTargets> color_formats;
    for (u32 i = 0; i < host_attachment_count; ++i) {
        if (is_mask(i)) {
            color_formats[i] = vk::Format::eR8Unorm;
            continue;
        }
        const auto& col_buf = key.color_buffers[i];
        const auto format = LiverpoolToVK::SurfaceFormat(col_buf.data_format, col_buf.num_format);
        const auto color_format =
            instance.GetSupportedFormat(format, vk::FormatFeatureFlagBits2::eColorAttachment);
        if (!instance.IsFormatSupported(color_format,
                                        vk::FormatFeatureFlagBits2::eColorAttachment)) {
            LOG_WARNING(Render_Vulkan,
                        "color buffer format {} does not support COLOR_ATTACHMENT_BIT",
                        vk::to_string(color_format));
        }
        color_formats[i] = color_format;
    }

    std::array<vk::SampleCountFlagBits, AmdGpu::NUM_COLOR_BUFFERS> color_samples;
    std::ranges::transform(key.color_samples, color_samples.begin(), [&instance](u8 num_samples) {
        return num_samples ? LiverpoolToVK::NumSamples(num_samples, instance.GetColorSampleCounts())
                           : vk::SampleCountFlagBits::e1;
    });
    const vk::AttachmentSampleCountInfoAMD mixed_samples = {
        .colorAttachmentCount = host_attachment_count,
        .pColorAttachmentSamples = color_samples.data(),
        .depthStencilAttachmentSamples =
            LiverpoolToVK::NumSamples(key.depth_samples, instance.GetDepthSampleCounts()),
    };

    const vk::PipelineRenderingCreateInfo pipeline_rendering_ci = {
        .pNext = instance.IsMixedDepthSamplesSupported() ? &mixed_samples : nullptr,
        .colorAttachmentCount = host_attachment_count,
        .pColorAttachmentFormats = color_formats.data(),
        .depthAttachmentFormat = key.z_format != AmdGpu::DepthBuffer::ZFormat::Invalid
                                     ? depth_format
                                     : vk::Format::eUndefined,
        .stencilAttachmentFormat = key.stencil_format != AmdGpu::DepthBuffer::StencilFormat::Invalid
                                       ? depth_format
                                       : vk::Format::eUndefined,
    };

    std::array<vk::PipelineColorBlendAttachmentState, AmdGpu::NUM_COLOR_BUFFERS> attachments;
    for (u32 i = 0; i < host_attachment_count; i++) {
        if (is_mask(i)) {
            attachments[i] = {.colorWriteMask = key.HostWriteMask(i)};
            continue;
        }
        const auto& control = key.blend_controls[i];

        const auto src_color = LiverpoolToVK::BlendFactor(control.color_src_factor);
        const auto dst_color = LiverpoolToVK::BlendFactor(control.color_dst_factor);
        const auto color_blend = LiverpoolToVK::BlendOp(control.color_func);

        const auto src_alpha = control.separate_alpha_blend
                                   ? LiverpoolToVK::BlendFactor(control.alpha_src_factor)
                                   : src_color;
        const auto dst_alpha = control.separate_alpha_blend
                                   ? LiverpoolToVK::BlendFactor(control.alpha_dst_factor)
                                   : dst_color;
        const auto alpha_blend =
            control.separate_alpha_blend ? LiverpoolToVK::BlendOp(control.alpha_func) : color_blend;

        // Vulkan ignores blend factors for min/max, but a factor that zeroes one operand
        // makes the operation collapse to a plain selection: min(s, 0) is 0 and max(s, 0)
        // is s for normalized alpha. Rewrite those to the equivalent add so the result is
        // exact instead of leaving the other operand to survive.
        auto eff_src_alpha = src_alpha;
        auto eff_dst_alpha = dst_alpha;
        auto eff_alpha_blend = alpha_blend;
        if (alpha_blend == vk::BlendOp::eMin || alpha_blend == vk::BlendOp::eMax) {
            const bool takes_max = alpha_blend == vk::BlendOp::eMax;
            if (src_alpha == vk::BlendFactor::eOne && dst_alpha == vk::BlendFactor::eZero) {
                eff_alpha_blend = vk::BlendOp::eAdd;
                eff_src_alpha = takes_max ? vk::BlendFactor::eOne : vk::BlendFactor::eZero;
                eff_dst_alpha = vk::BlendFactor::eZero;
            } else if (src_alpha == vk::BlendFactor::eZero && dst_alpha == vk::BlendFactor::eOne) {
                eff_alpha_blend = vk::BlendOp::eAdd;
                eff_src_alpha = vk::BlendFactor::eZero;
                eff_dst_alpha = takes_max ? vk::BlendFactor::eOne : vk::BlendFactor::eZero;
            }
        }

        const auto color_scaled_min_max =
            (color_blend == vk::BlendOp::eMin || color_blend == vk::BlendOp::eMax) &&
            (src_color != vk::BlendFactor::eOne || dst_color != vk::BlendFactor::eOne) &&
            !key.color_buffers[i].blend_self_scale;
        const auto alpha_scaled_min_max =
            (eff_alpha_blend == vk::BlendOp::eMin || eff_alpha_blend == vk::BlendOp::eMax) &&
            (eff_src_alpha != vk::BlendFactor::eOne || eff_dst_alpha != vk::BlendFactor::eOne);
        if (color_scaled_min_max || alpha_scaled_min_max) {
            LOG_WARNING(
                Render_Vulkan,
                "Unimplemented use of min/max blend op with blend factor not equal to one.");
        }

        attachments[i] = vk::PipelineColorBlendAttachmentState{
            .blendEnable = control.enable,
            .srcColorBlendFactor = src_color,
            .dstColorBlendFactor = dst_color,
            .colorBlendOp = color_blend,
            .srcAlphaBlendFactor = eff_src_alpha,
            .dstAlphaBlendFactor = eff_dst_alpha,
            .alphaBlendOp = eff_alpha_blend,
            .colorWriteMask =
                instance.IsDynamicColorWriteMaskSupported()
                    ? vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                          vk::ColorComponentFlagBits::eB | vk::ColorComponentFlagBits::eA
                    : key.write_masks[i],
        };

        // The shader squares its color output for this attachment (see PsColorBuffer), so the
        // factors must not scale the operands again.
        if (key.color_buffers[i].blend_self_scale) {
            LOG_WARNING(
                Render_Vulkan,
                "Emulating scaled min/max blend with squared shader output on attachment {}", i);
            attachments[i].srcColorBlendFactor = vk::BlendFactor::eOne;
            attachments[i].dstColorBlendFactor = vk::BlendFactor::eOne;
        }

        // On GCN GPU there is an additional mask which allows to control color components exported
        // from a pixel shader. A situation possible, when the game may mask out the alpha channel,
        // while it is still need to be used in blending ops. For such cases, HW will default alpha
        // to 1 and perform the blending, while shader normally outputs 0 in the last component.
        // Unfortunatelly, Vulkan doesn't provide any control on blend inputs, so below we detecting
        // such cases and override alpha value in order to emulate HW behaviour.
        const auto has_alpha_masked_out =
            (key.cb_shader_mask.GetMask(i) & AmdGpu::ColorBufferMask::ComponentA) == 0;
        const auto has_src_alpha_in_src_blend = src_color == vk::BlendFactor::eSrcAlpha ||
                                                src_color == vk::BlendFactor::eOneMinusSrcAlpha;
        const auto has_src_alpha_in_dst_blend = dst_color == vk::BlendFactor::eSrcAlpha ||
                                                dst_color == vk::BlendFactor::eOneMinusSrcAlpha;
        if (has_alpha_masked_out && has_src_alpha_in_src_blend) {
            attachments[i].srcColorBlendFactor = src_color == vk::BlendFactor::eSrcAlpha
                                                     ? vk::BlendFactor::eOne
                                                     : vk::BlendFactor::eZero; // 1-A
        }
        if (has_alpha_masked_out && has_src_alpha_in_dst_blend) {
            attachments[i].dstColorBlendFactor = dst_color == vk::BlendFactor::eSrcAlpha
                                                     ? vk::BlendFactor::eOne
                                                     : vk::BlendFactor::eZero; // 1-A
        }
    }

    const vk::PipelineColorBlendStateCreateInfo color_blending = {
        .logicOpEnable =
            instance.IsLogicOpSupported() && key.logic_op != AmdGpu::ColorControl::LogicOp::Copy,
        .logicOp = LiverpoolToVK::LogicOp(key.logic_op),
        .attachmentCount = host_attachment_count,
        .pAttachments = attachments.data(),
        .blendConstants = std::array{1.0f, 1.0f, 1.0f, 1.0f},
    };

    // Required by spec unless VK_EXT_extended_dynamic_state3 is supported.
    // In practice, we use dynamic state for all of it.
    constexpr vk::PipelineDepthStencilStateCreateInfo depth_stencil_info = {};

    const vk::GraphicsPipelineCreateInfo pipeline_info = {
        .pNext = &pipeline_rendering_ci,
        .stageCount = static_cast<u32>(shader_stages.size()),
        .pStages = shader_stages.data(),
        .pVertexInputState = !instance.IsVertexInputDynamicState() ? &vertex_input_info : nullptr,
        .pInputAssemblyState = &input_assembly,
        .pTessellationState = &tessellation_state,
        .pViewportState = &viewport_info,
        .pRasterizationState = &raster_chain.get(),
        .pMultisampleState = &sdata.multisampling,
        .pDepthStencilState =
            !instance.IsExtendedDynamicState3Supported() ? &depth_stencil_info : nullptr,
        .pColorBlendState = &color_blending,
        .pDynamicState = &dynamic_info,
        .layout = *pipeline_layout,
    };
    constexpr u32 ivy_ps = u32(Shader::SwStage::Fragment);
    constexpr u32 ivy_vs = u32(Shader::SwStage::Vertex);
    if (ivy_fragment_module && infos[ivy_vs] && infos[ivy_vs]->pgm_hash == IvyMaterialProbe::Vertex &&
        !key.foliage_mask && key.prim_type == AmdGpu::PrimitiveType::TriangleList &&
        key.mrt_mask == 1 && key.num_samples == 1 && key.depth_samples == 1 &&
        key.logic_op == AmdGpu::ColorControl::LogicOp::Copy && shader_stages.size() == 2 &&
        sdata.multisampling.rasterizationSamples == vk::SampleCountFlagBits::e1 &&
        !sdata.multisampling.sampleShadingEnable && !sdata.multisampling.alphaToCoverageEnable &&
        pipeline_rendering_ci.depthAttachmentFormat == vk::Format::eD32SfloatS8Uint &&
        host_attachment_count == 1 && color_formats[0] == vk::Format::eR16G16B16A16Sfloat) {
        const auto active = IvyMaterialProbe::Modules().Find(key.stage_hashes[ivy_ps], ivy_fragment_module);
        if (active) {
            ivy_sample_variant = IvySampleWitness::CreateVariant(instance, pipeline_info, set_layouts,
                                                                 push_constants, *active, *infos[ivy_ps],
                                                                 *infos[ivy_vs]);
        }
    }
    if (const char* flag = std::getenv("BB_SPECULAR_CAPTURE");
        flag && flag[0] == '1' && flag[1] == '\0' &&
        infos[u32(Shader::SwStage::Fragment)] &&
        infos[u32(Shader::SwStage::Fragment)]->pgm_hash == DirectionalFragmentShaderHash &&
        infos[u32(Shader::SwStage::Vertex)] &&
        infos[u32(Shader::SwStage::Vertex)]->pgm_hash == PointGridVertexShaderHash) {
        if (const char* directory = std::getenv("BB_CAPTURE_DIR"); directory && directory[0]) {
            std::ostringstream name;
            name << "pipeline-" << std::hex << std::hash<GraphicsPipelineKey>{}(key) << ".txt";
            std::ofstream file(std::filesystem::path(directory) / name.str());
            file << std::setprecision(9) << "version 1\npush_descriptors "
                 << uses_push_descriptors << "\ndynamic_vertex_input "
                 << instance.IsVertexInputDynamicState() << "\nsubgroup_size "
                 << (instance.IsSubgroupSize64Supported() ? 64 : 0) << "\nmultisample "
                 << u32(sdata.multisampling.rasterizationSamples) << ' '
                 << sdata.multisampling.sampleShadingEnable << ' '
                 << sdata.multisampling.minSampleShading << ' '
                 << sdata.multisampling.alphaToCoverageEnable << ' '
                 << sdata.multisampling.alphaToOneEnable << "\nclip "
                 << clip_control.negativeOneToOne << ' ' << key.depth_clip_enable << ' '
                 << raster_chain.get<vk::PipelineRasterizationStateCreateInfo>().depthClampEnable
                 << "\nprovoking_last "
                 << (key.provoking_vtx_last == AmdGpu::ProvokingVtxLast::Last) << '\n';
            for (u32 i = 0; i < key.num_color_attachments; ++i) {
                const auto& blend = attachments[i];
                file << "blend " << i << ' ' << blend.blendEnable << ' '
                     << u32(blend.srcColorBlendFactor) << ' ' << u32(blend.dstColorBlendFactor)
                     << ' ' << u32(blend.colorBlendOp) << ' ' << u32(blend.srcAlphaBlendFactor)
                     << ' ' << u32(blend.dstAlphaBlendFactor) << ' ' << u32(blend.alphaBlendOp)
                     << ' ' << u32(blend.colorWriteMask) << '\n';
            }
            file << "dynamic_states";
            for (auto state : dynamic_states) file << ' ' << u32(state);
            file << '\n';
            file.close();
            if (!file) std::printf("Specular capture: native pipeline state write failed\n");
        } else {
            std::printf("Specular capture: BB_CAPTURE_DIR is required for native pipeline state\n");
        }
    }

    // bbport (BB_ASYNC_PIPELINES): a pipeline first seen during play is created by a compile
    // thread; the draw recording thread waits for it only when it records the bind (Handle).
    // Meanwhile the GPU command thread decodes on and starts the next new pipelines, so a burst
    // of compiles (area loads: 50-90 at once, 0.5-1.3 s on one thread) runs in parallel.
    // bbport: the start's cached pipelines are created in parallel (WarmupJobs).
    WarmupJobs* const warmup = preloading ? warmup_jobs : nullptr;
    if ((!preloading && AsyncPipelinesEnabled()) || warmup) {
        auto job = std::make_shared<PendingPipeline>();
        auto& j = *job;
        bool ok = true;
        j.stages.assign(shader_stages.begin(), shader_stages.end());
        j.subgroup_size = subgroup_size_ci;
        ok &= subgroup_size_ci.pNext == nullptr;
        for (auto& s : j.stages) {
            ok &= s.pNext == nullptr || s.pNext == &subgroup_size_ci;
            s.pNext = s.pNext ? &j.subgroup_size : nullptr;
        }
        j.bindings = sdata.vertex_bindings;
        j.attributes = sdata.vertex_attributes;
        j.divisors = sdata.divisors;
        j.divisor_state = divisor_state;
        ok &= divisor_state.pNext == nullptr &&
              divisor_state.pVertexBindingDivisors == sdata.divisors.data();
        j.divisor_state.pVertexBindingDivisors = j.divisors.data();
        j.vertex_input = vertex_input_info;
        ok &= vertex_input_info.pNext == nullptr || vertex_input_info.pNext == &divisor_state;
        j.vertex_input.pNext = vertex_input_info.pNext ? &j.divisor_state : nullptr;
        j.vertex_input.pVertexBindingDescriptions = j.bindings.data();
        j.vertex_input.pVertexAttributeDescriptions = j.attributes.data();
        j.input_assembly = input_assembly;
        j.tessellation = tessellation_state;
        j.clip_control = clip_control;
        j.viewport = viewport_info;
        ok &= viewport_info.pNext == nullptr || viewport_info.pNext == &clip_control;
        j.viewport.pNext = viewport_info.pNext ? &j.clip_control : nullptr;
        // The rasterization chain, linked again in the same order without unlinked parts.
        j.raster = raster_chain.get<vk::PipelineRasterizationStateCreateInfo>();
        j.provoking = raster_chain.get<vk::PipelineRasterizationProvokingVertexStateCreateInfoEXT>();
        j.depth_clip = raster_chain.get<vk::PipelineRasterizationDepthClipStateCreateInfoEXT>();
        {
            const void** next = &j.raster.pNext;
            if (instance.IsProvokingVertexSupported()) {
                *next = &j.provoking;
                next = &j.provoking.pNext;
            }
            if (instance.IsDepthClipEnableSupported()) {
                *next = &j.depth_clip;
                next = &j.depth_clip.pNext;
            }
            *next = nullptr;
        }
        j.multisample = sdata.multisampling;
        ok &= sdata.multisampling.pNext == nullptr && sdata.multisampling.pSampleMask == nullptr;
        j.depth_stencil = depth_stencil_info;
        j.attachments = attachments;
        j.color_blend = color_blending;
        ok &= color_blending.pNext == nullptr;
        j.color_blend.pAttachments = j.attachments.data();
        j.dynamic_states.assign(dynamic_states.begin(), dynamic_states.end());
        j.dynamic = dynamic_info;
        j.dynamic.pDynamicStates = j.dynamic_states.data();
        j.color_formats = color_formats;
        j.color_samples = color_samples;
        j.mixed_samples = mixed_samples;
        j.mixed_samples.pColorAttachmentSamples = j.color_samples.data();
        j.rendering = pipeline_rendering_ci;
        ok &= pipeline_rendering_ci.pNext == nullptr || pipeline_rendering_ci.pNext == &mixed_samples;
        j.rendering.pNext = pipeline_rendering_ci.pNext ? &j.mixed_samples : nullptr;
        j.rendering.pColorAttachmentFormats = j.color_formats.data();
        j.info = pipeline_info;
        ok &= input_assembly.pNext == nullptr && tessellation_state.pNext == nullptr &&
              clip_control.pNext == nullptr && dynamic_info.pNext == nullptr &&
              mixed_samples.pNext == nullptr && pipeline_info.pRasterizationState == &raster_chain.get() &&
              pipeline_info.pMultisampleState == &sdata.multisampling;
        j.info.pNext = &j.rendering;
        j.info.stageCount = static_cast<u32>(j.stages.size());
        j.info.pStages = j.stages.data();
        j.info.pVertexInputState = pipeline_info.pVertexInputState ? &j.vertex_input : nullptr;
        j.info.pInputAssemblyState = &j.input_assembly;
        j.info.pTessellationState = &j.tessellation;
        j.info.pViewportState = &j.viewport;
        j.info.pRasterizationState = &j.raster;
        j.info.pMultisampleState = &j.multisample;
        j.info.pDepthStencilState = pipeline_info.pDepthStencilState ? &j.depth_stencil : nullptr;
        j.info.pColorBlendState = &j.color_blend;
        j.info.pDynamicState = &j.dynamic;
        // Anything this copy does not know how to own (a chain added later): created here.
        if (ok && warmup) {
            ready.store(false, std::memory_order_relaxed);
            warmup->jobs.push_back([this, job, device, cache = pipeline_cache, name = debug_str] {
                auto [result, created] = device.createGraphicsPipelineUnique(cache, job->info);
                if (result == vk::Result::eSuccess) {
                    pipeline = std::move(created);
                    SetObjectName(device, *pipeline, "Graphics Pipeline {}", name);
                }
                MarkReady();
                return result == vk::Result::eSuccess;
            });
            return;
        }
        if (ok) {
            ready.store(false, std::memory_order_relaxed);
            SubmitPipelineJob(this, [this, job, device, cache = pipeline_cache, name = debug_str] {
                auto [result, created] = device.createGraphicsPipelineUnique(cache, job->info);
                ASSERT_MSG(result == vk::Result::eSuccess,
                           "Failed to create graphics pipeline: {}", vk::to_string(result));
                pipeline = std::move(created);
                SetObjectName(device, *pipeline, "Graphics Pipeline {}", name);
                MarkReady();
            });
            return;
        }
    }

    auto [pipeline_result, pipe] =
        device.createGraphicsPipelineUnique(pipeline_cache, pipeline_info);
    if (preloading && pipeline_result != vk::Result::eSuccess) {
        // bbport: a pipeline from the cache the driver rejects is a damaged cache entry: the
        // cache is rebuilt (PipelineCache::WarmUp) instead of stopping the game at every start.
        throw Serialization::CorruptData{"cached graphics pipeline rejected by the driver: " +
                                         vk::to_string(pipeline_result)};
    }
    ASSERT_MSG(pipeline_result == vk::Result::eSuccess, "Failed to create graphics pipeline: {}",
               vk::to_string(pipeline_result));
    pipeline = std::move(pipe);
    SetObjectName(device, *pipeline, "Graphics Pipeline {}", debug_str);
}

void GraphicsPipeline::PushFoliageClass(vk::CommandBuffer command_buffer, bool tagged) const {
    ASSERT(key.foliage_mask);
    const u32 value = tagged ? 1 : 0;
    command_buffer.pushConstants(GetLayout(), AllGraphicsStageBits,
                                 Shader::FoliageMaskOutput::PushOffset, sizeof(value), &value);
}

ReflectionDiscard::Verdict GraphicsPipeline::GetStockFragmentVerdict(
    const PipelineCache& owner, ReflectionDiscard::StockRole role, vk::Pipeline ready) const {
    return stock_fragment_owner == &owner && stock_fragment_role == role &&
        ready && ready == HandleIfReady() && owner.StockFragmentUsable(role, stock_fragment_verdict)
        ? stock_fragment_verdict : ReflectionDiscard::Verdict::Unknown;
}

void GraphicsPipeline::WaitForStockFragmentCreation() const {
    constexpr u32 vs = u32(Shader::SwStage::Vertex), ps = u32(Shader::SwStage::Fragment);
    if (ReflectionDiscard::StockFragmentForStages(key.stage_hashes[vs], key.stage_hashes[ps])) {
        WaitReady();
    }
}

bool GraphicsPipeline::GetReflectionDiscardProof(const PipelineCache* owner, u64 expected_stage,
                                                ReflectionDiscard::Pipeline& proof) const {
    if (!reflection_discard || reflection_discard->fragment.id.cache != owner ||
        reflection_discard->fragment.id.stage != expected_stage) {
        return false;
    }
    const auto handle = HandleIfReady();
    if (!handle || !ReflectionDiscard::Revalidate(reflection_discard->fragment.id)) return false;
    proof = *reflection_discard;
    proof.handle = handle;
    return true;
}

void GraphicsPipeline::WaitForReflectionDiscardCreation(const PipelineCache* owner,
                                                        vk::ShaderModule module) const {
    if (reflection_discard && reflection_discard->fragment.id.cache == owner &&
        (reflection_discard->vertex == module ||
         reflection_discard->fragment.id.handle == std::bit_cast<u64>(module))) {
        WaitReady();
    }
}

GraphicsPipeline::~GraphicsPipeline() {
    // bbport: the compile thread may still be creating it (its job points at this object).
    WaitReady();
}

template <typename Attribute, typename Binding>
void GraphicsPipeline::GetVertexInputs(
    VertexInputs<Attribute>& attributes, VertexInputs<Binding>& bindings,
    VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT>& divisors,
    VertexInputs<AmdGpu::Buffer>& guest_buffers, u32 step_rate_0, u32 step_rate_1,
    std::span<const AmdGpu::Buffer> sharps) const {
    using InstanceIdType = Shader::Gcn::VertexAttribute::InstanceIdType;
    if (!fetch_shader || fetch_shader->attributes.empty()) {
        return;
    }
    const auto& vs_info = GetStage(Shader::SwStage::Vertex);
    const bool given = sharps.size() == fetch_shader->attributes.size();
    for (u32 index = 0; const auto& attrib : fetch_shader->attributes) {
        const auto step_rate = attrib.GetStepRate();
        const auto buffer = given ? sharps[index] : attrib.GetSharp(vs_info);
        ++index;
        attributes.push_back(Attribute{
            .location = attrib.semantic,
            .binding = attrib.semantic,
            .format = LiverpoolToVK::SurfaceFormat(buffer.GetDataFmt(), buffer.GetNumberFmt()),
            .offset = 0,
        });
        bindings.push_back(Binding{
            .binding = attrib.semantic,
            .stride = buffer.GetStride(),
            .inputRate = step_rate == InstanceIdType::None ? vk::VertexInputRate::eVertex
                                                           : vk::VertexInputRate::eInstance,
        });
        const u32 divisor = step_rate == InstanceIdType::OverStepRate0
                                ? step_rate_0
                                : (step_rate == InstanceIdType::OverStepRate1 ? step_rate_1 : 1);
        if constexpr (std::is_same_v<Binding, vk::VertexInputBindingDescription2EXT>) {
            bindings.back().divisor = divisor;
        } else if (step_rate != InstanceIdType::None) {
            divisors.push_back(vk::VertexInputBindingDivisorDescriptionEXT{
                .binding = attrib.semantic,
                .divisor = divisor,
            });
        }
        guest_buffers.emplace_back(buffer);
    }
}

// Declare templated GetVertexInputs for necessary types.
template void GraphicsPipeline::GetVertexInputs(
    VertexInputs<vk::VertexInputAttributeDescription>& attributes,
    VertexInputs<vk::VertexInputBindingDescription>& bindings,
    VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT>& divisors,
    VertexInputs<AmdGpu::Buffer>& guest_buffers, u32 step_rate_0, u32 step_rate_1,
    std::span<const AmdGpu::Buffer> sharps) const;
template void GraphicsPipeline::GetVertexInputs(
    VertexInputs<vk::VertexInputAttributeDescription2EXT>& attributes,
    VertexInputs<vk::VertexInputBindingDescription2EXT>& bindings,
    VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT>& divisors,
    VertexInputs<AmdGpu::Buffer>& guest_buffers, u32 step_rate_0, u32 step_rate_1,
    std::span<const AmdGpu::Buffer> sharps) const;

void GraphicsPipeline::BuildDescSetLayout(bool preloading) {
    boost::container::small_vector<vk::DescriptorSetLayoutBinding, 32> bindings;
    u32 binding{};

    for (const auto* stage : stages) {
        if (!stage) {
            continue;
        }
        const auto stage_bit = LogicalStageToStageBit[u32(stage->sw_stage)];
        for (const auto& buffer : stage->buffers) {
            const auto sharp =
                preloading ? AmdGpu::Buffer{}
                           : buffer.GetSharp(*stage); // See for the comment in compute PL creation
            bindings.push_back({
                .binding = binding++,
                .descriptorType = buffer.is_uniform ? vk::DescriptorType::eUniformBuffer
                                                    : vk::DescriptorType::eStorageBuffer,
                .descriptorCount = 1,
                .stageFlags = stage_bit,
            });
        }
        for (const auto& image : stage->images) {
            const u32 num_bindings = image.NumBindings(*stage);
            bindings.push_back({
                .binding = binding,
                .descriptorType = image.is_written ? vk::DescriptorType::eStorageImage
                                                   : vk::DescriptorType::eSampledImage,
                .descriptorCount = num_bindings,
                .stageFlags = stage_bit,
            });
            binding += num_bindings;
        }
        for (const auto& sampler : stage->samplers) {
            bindings.push_back({
                .binding = binding++,
                .descriptorType = vk::DescriptorType::eSampler,
                .descriptorCount = 1,
                .stageFlags = stage_bit,
            });
        }
    }
    uses_push_descriptors = binding < instance.MaxPushDescriptors();
    const auto flags = uses_push_descriptors
                           ? vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR
                           : vk::DescriptorSetLayoutCreateFlagBits{};
    const vk::DescriptorSetLayoutCreateInfo desc_layout_ci = {
        .flags = flags,
        .bindingCount = static_cast<u32>(bindings.size()),
        .pBindings = bindings.data(),
    };
    auto [layout_result, layout] =
        instance.GetDevice().createDescriptorSetLayoutUnique(desc_layout_ci);
    ASSERT_MSG(layout_result == vk::Result::eSuccess,
               "Failed to create graphics descriptor set layout: {}", vk::to_string(layout_result));
    desc_layout = std::move(layout);
}

} // namespace Vulkan
