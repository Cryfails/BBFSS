// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <atomic>
#include <memory>

#include <boost/container/static_vector.hpp>
#include <xxhash.h>

#include "shader_recompiler/frontend/fetch_shader.h"
#include "video_core/amdgpu/regs_color.h"
#include "video_core/amdgpu/regs_depth.h"
#include "video_core/amdgpu/regs_primitive.h"
#include "video_core/renderer_vulkan/vk_pipeline_common.h"
#include "video_core/renderer_vulkan/vk_bottle_display_evidence_b182.h"

namespace VideoCore {
class BufferCache;
class TextureCache;
} // namespace VideoCore

namespace WorkflowCapture {
enum class Route : u8;
}

namespace Vulkan {

static constexpr u32 MaxShaderStages = static_cast<u32>(Shader::SwStage::NumLogicalStages);
static constexpr u32 MaxVertexBufferCount = 32;

class Instance;
class Scheduler;
class DescriptorHeap;
class PipelineCache;
namespace ReflectionDiscard {
enum class StockRole : u8;
enum class Verdict : u8;
struct Pipeline;
}
namespace IvySampleWitness {
struct Variant;
}

template <typename T>
using VertexInputs = boost::container::static_vector<T, MaxVertexBufferCount>;

struct GraphicsPipelineKey {
    std::array<size_t, MaxShaderStages> stage_hashes;
    std::array<vk::Format, MaxVertexBufferCount> vertex_buffer_formats;
    u32 patch_control_points;
    u32 num_color_attachments;
    std::array<Shader::PsColorBuffer, AmdGpu::NUM_COLOR_BUFFERS> color_buffers;
    std::array<AmdGpu::BlendControl, AmdGpu::NUM_COLOR_BUFFERS> blend_controls;
    std::array<vk::ColorComponentFlags, AmdGpu::NUM_COLOR_BUFFERS> write_masks;
    AmdGpu::ColorBufferMask cb_shader_mask;
    AmdGpu::ColorControl::LogicOp logic_op;
    u8 num_samples;
    u8 depth_samples;
    std::array<u8, AmdGpu::NUM_COLOR_BUFFERS> color_samples;
    u32 mrt_mask;
    u32 motion_vectors = 0;
    struct {
        AmdGpu::DepthBuffer::ZFormat z_format : 2;
        AmdGpu::DepthBuffer::StencilFormat stencil_format : 1;
        u32 depth_clamp_enable : 1;
        u32 foliage_mask : 1;
    };
    struct {
        AmdGpu::PrimitiveType prim_type : 5;
        AmdGpu::PolygonMode polygon_mode : 2;
        AmdGpu::ClipSpace clip_space : 1;
        AmdGpu::ProvokingVtxLast provoking_vtx_last : 1;
        u32 depth_clip_enable : 1;
    };

    GraphicsPipelineKey() {
        std::memset(this, 0, sizeof(*this));
    }

    bool operator==(const GraphicsPipelineKey& key) const noexcept {
        return std::memcmp(this, &key, sizeof(key)) == 0;
    }

    // These describe host attachments. mrt_mask and num_color_attachments retain their
    // original meaning for guest target lookup and pass classification.
    u32 HostColorAttachmentCount() const {
        constexpr u32 count = Shader::FoliageMaskOutput::Location + 1;
        return foliage_mask && num_color_attachments < count ? count : num_color_attachments;
    }

    vk::ColorComponentFlags HostWriteMask(u32 location) const {
        return foliage_mask && location == Shader::FoliageMaskOutput::Location
                   ? vk::ColorComponentFlagBits::eR : write_masks[location];
    }

    void Serialize(Serialization::Archive& ar) const;
    bool Deserialize(Serialization::Archive& ar);
};

class GraphicsPipeline : public Pipeline {
public:
    struct SerializationSupport {
        VertexInputs<vk::VertexInputAttributeDescription> vertex_attributes{};
        VertexInputs<vk::VertexInputBindingDescription> vertex_bindings{};
        VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT> divisors{};
        vk::PipelineMultisampleStateCreateInfo multisampling{};
        std::vector<u32> tcs{};
        std::vector<u32> tes{};
        std::vector<u32> fragment{};

        void Serialize(Serialization::Archive& ar) const;
        bool Deserialize(Serialization::Archive& ar, bool legacy);
    };

    GraphicsPipeline(const Instance& instance, Scheduler& scheduler, DescriptorHeap& desc_heap,
                     const Shader::Profile& profile, const GraphicsPipelineKey& key,
                     vk::PipelineCache pipeline_cache,
                     std::span<const Shader::Info*, MaxShaderStages> stages,
                     std::span<const Shader::RuntimeInfo, MaxShaderStages> runtime_infos,
                     std::optional<const Shader::Gcn::FetchShaderData> fetch_shader,
                     std::span<const vk::ShaderModule> modules, SerializationSupport& sdata,
                     bool preloading, WorkflowCapture::Route capture_proof = {},
                     const PipelineCache* module_owner = nullptr);
    ~GraphicsPipeline();

    const std::optional<const Shader::Gcn::FetchShaderData>& GetFetchShader() const noexcept {
        return fetch_shader;
    }

    // Ordered draw hook calls this after BindResources for every masked draw, including zero.
    void PushFoliageClass(vk::CommandBuffer command_buffer, bool tagged) const;

    const GraphicsPipeline* FoliageVariant() const {
        return foliage_variant.load(std::memory_order_acquire);
    }
    void SetFoliageVariant(const GraphicsPipeline* variant) const {
        foliage_variant.store(variant, std::memory_order_release);
    }

    u64 IvyFragmentModule() const { return ivy_fragment_module; }
    std::shared_ptr<const IvySampleWitness::Variant> IvySampleVariant() const {
        return ivy_sample_variant;
    }

    const GraphicsPipelineKey& GetGraphicsKey() const {
        return key;
    }
    WorkflowCapture::Route WorkflowCaptureProof() const { return capture_proof; }
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    const BottleDisplay182::Program* BottleDisplayProgram() const { return bottle_display_program.get(); }
#endif

    ReflectionDiscard::Verdict GetStockFragmentVerdict(const PipelineCache& owner,
        ReflectionDiscard::StockRole role, vk::Pipeline ready) const;
    void WaitForStockFragmentCreation() const;

    bool GetReflectionDiscardProof(const PipelineCache* owner, u64 expected_stage,
                                   ReflectionDiscard::Pipeline& proof) const;
    void WaitForReflectionDiscardCreation(const PipelineCache* owner, vk::ShaderModule module) const;

    /// Gets the attributes and bindings for vertex inputs.
    /// bbport: `sharps`, when given, are the V#s of the fetch shader's attributes as the GPU
    /// command thread read them (in the draw packet): the V# tables they come from may have been
    /// rewritten by a later constant engine dump by the time the recording thread gets here.
    template <typename Attribute, typename Binding>
    void GetVertexInputs(VertexInputs<Attribute>& attributes, VertexInputs<Binding>& bindings,
                         VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT>& divisors,
                         VertexInputs<AmdGpu::Buffer>& guest_buffers, u32 step_rate_0,
                         u32 step_rate_1, std::span<const AmdGpu::Buffer> sharps = {}) const;

private:
    mutable std::atomic<const GraphicsPipeline*> foliage_variant{};
    void BuildDescSetLayout(bool preloading);

private:
    GraphicsPipelineKey key;
    WorkflowCapture::Route capture_proof;
#if defined(BB_TEST_BOTTLE_CUT_SOURCE) && defined(BB_TEST_SHARED_POST_GRAPH) && defined(BB_TEST_POST_PRESENT_RESOURCES)
    std::unique_ptr<const BottleDisplay182::Program> bottle_display_program;
#endif
    ReflectionDiscard::Verdict stock_fragment_verdict{};
    ReflectionDiscard::StockRole stock_fragment_role{};
    u64 ivy_fragment_module{};
    std::shared_ptr<const IvySampleWitness::Variant> ivy_sample_variant;
    const PipelineCache* stock_fragment_owner{};
    std::unique_ptr<const ReflectionDiscard::Pipeline> reflection_discard;
    vk::UniqueDescriptorSetLayout motion_address_layout;
    std::optional<const Shader::Gcn::FetchShaderData> fetch_shader{};
};

struct ClipDistanceShaderKey {
    std::array<std::tuple<u8, u8>, 8> clip_locations;

    bool operator==(const ClipDistanceShaderKey& key) const noexcept {
        return std::memcmp(this, &key, sizeof(key)) == 0;
    }
};

} // namespace Vulkan

template <>
struct std::hash<Vulkan::GraphicsPipelineKey> {
    std::size_t operator()(const Vulkan::GraphicsPipelineKey& key) const noexcept {
        return XXH3_64bits(&key, sizeof(key));
    }
};

template <>
struct std::hash<Vulkan::ClipDistanceShaderKey> {
    std::size_t operator()(const Vulkan::ClipDistanceShaderKey& key) const noexcept {
        return XXH3_64bits(&key, sizeof(key));
    }
};
