// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): see vk_ambient_particles.h.

#include "video_core/renderer_vulkan/vk_ambient_particles.h"

#include <algorithm> // bbport (r98c_particles-visible)
#include <cstdio>
#include <span>
#include <string>

#include "video_core/host_shaders/ambient_particles_frag.h"
#include "video_core/host_shaders/ambient_particles_vert.h"
#include "engine/engine_state.h" // bbport (r98e_moths-at-lamps): the hunter (BbEngine::world_player_position)
#include "video_core/renderer_vulkan/vk_gpu_profiler.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {

namespace {
constexpr u64 ProfileKey = 0x4150'0000'0098ull; ///< the GPU profile row "Ambient particles (r98)"
constexpr auto Stages = vk::ShaderStageFlagBits::eVertex | vk::ShaderStageFlagBits::eFragment;

/// The frame before the UI and the UI image (made in its format) must be RGBA8: the motes are
/// screened through the UI image's R8G8B8A8 UNORM view, which reads other byte orders wrongly.
bool Rgba8(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb;
}
} // namespace

AmbientParticles::AmbientParticles(const Instance& instance_, Scheduler& scheduler_)
    : instance{instance_}, scheduler{scheduler_} {
    const auto& knobs = AmbientMotes::Get();
    if (!CreatePipeline()) {
        pipeline.reset();
        std::printf("Ambient particles (r98): the pipeline could not be made; off\n");
        return;
    }
    std::printf("Ambient particles (r98, BB_PARTICLES=%.2f): a cell of %.2f m holds a mote with "
                "chance %.2f (%u cells around the camera), embers %.2f of them, show %s; drawn "
                "into the output-size frame before the UI, after the upscale: right after "
                "RunScaled's upscale of the game's finished frame (by default at outputs other "
                "than 1920x1080), "
                "or, with the upscale before the game's post (upscale_before_post=1 or "
                "BB_UPSCALE_EARLY=1), into RunUiOnly's output-size copy of the game's finished "
                "frame (at its first UI draw, or at the display pass of a frame without UI); "
                "nothing at a 1920x1080 output; drifting with %s\n",
                double(knobs.density), double(AmbientMotes::Cell),
                double(AmbientMotes::Occupancy(knobs)), AmbientMotes::Instances,
                double(knobs.embers), knobs.show ? "on (BB_PARTICLES_SHOW=1)" : "off",
                "the wind when BB_WIND=1, else a calm drift");
    // bbport (r98c_particles-visible)
    if (lamp_gain > 0.0f) {
        std::printf("Ambient particles (r98c, BB_PARTICLES_LAMPS=%.2f): dust lit by up to %u lamps "
                    "of the frame's lamp pass (forward scattering, a %.1f m halo), embers thrown by "
                    "up to %u burning flames within %.0f m (warm, a channel %.1f or more; %u slots "
                    "each, chance %.2f a life x the flame's share: none at a reach of %.0f m or "
                    "less, all from %.0f m), the lattice's embers only near them; lamps only while "
                    "an engine effect runs\n",
                    double(lamp_gain), u32(AP_MAX_LAMPS), double(AP_LAMP_HALO), u32(AP_MAX_FLAMES),
                    double(AP_SPARK_FAR1), double(AP_SPARK_BRIGHT), u32(AP_FLAME_SLOTS),
                    double(AmbientMotes::SparkBirth(knobs)), double(AP_SPARK_REACH0),
                    double(AP_SPARK_REACH1));
    } else {
        std::printf("Ambient particles (r98c): lamps off (BB_PARTICLES_LAMPS=0): the light of the "
                    "picture behind a mote only, embers anywhere (the r98b look)\n");
    }
    // bbport (r98d_particles-still-indoors)
    const auto& still_knobs = AmbientMotes::StillGet();
    std::printf("Ambient particles (r98d, BB_PARTICLES_STILL=%.2f, BB_PARTICLES_DARK=%.2f): where "
                "the wind shelter field says the camera is sheltered (BB_WIND=1 with "
                "BB_WIND_SHELTER above 0; the open share of air at the camera, followed over %.1f "
                "s) the lattice and the embers drift at the open share of the wind and the rest at "
                "the calm %.2f/%.2f m/s, and dust over a picture darker than luma %.2f fades "
                "(in full from %.2f); in the open nothing changes; without the field the share "
                "stays 1\n",
                double(still_knobs.still), double(still_knobs.dark), double(AmbientMotes::OpenTau),
                double(AmbientMotes::CalmDrift[0]), double(AmbientMotes::CalmDrift[2]),
                double(AP_DARK_LO), double(AP_DARK_HI));
    // bbport (r98e_moths-at-lamps)
    if (moth_level > 0) {
        std::printf("Ambient particles (r98e, BB_PARTICLES_MOTHS=%d): %d to %d moths round each of the %u "
                    "nearest lit lamps (warm or white, luminance %.2f or more, reach %.1f to %.1f m, "
                    "within %.0f m of the camera, none within %.1f m of the hunter's chest), loops of "
                    "%.2f to %.2f m, leaning downwind in the open (at most %.2f m), calmer in shelter; "
                    "seen in full to %.0f m, gone at %.0f m; %u instances more in a frame that shows "
                    "one; needs the lamps (BB_PARTICLES_LAMPS above 0, an engine effect running)%s\n",
                    moth_level, moth_level >= 2 ? 3 : 2, moth_level >= 2 ? 6 : 4, u32(AP_MOTH_LAMPS), double(AmbientMotes::MothMinLuma),
                    double(AmbientMotes::MothReachMin), double(AmbientMotes::MothReachMax),
                    double(AP_MOTH_FAR1), double(AmbientMotes::MothHunterNear),
                    double(AP_MOTH_ORBIT_MIN), double(AP_MOTH_ORBIT_MAX), double(AP_MOTH_LEAN_MAX),
                    double(AP_MOTH_FAR0), double(AP_MOTH_FAR1), u32(AP_MOTH_INSTANCES),
                    lamp_gain > 0.0f ? "" : " (BB_PARTICLES_LAMPS is 0: no moths)");
    }
}

AmbientParticles::~AmbientParticles() {
    if (lamp_buffer) { // bbport (r98c_particles-visible)
        vmaDestroyBuffer(instance.GetAllocator(), lamp_buffer, lamp_allocation);
    }
}

bool AmbientParticles::CreatePipeline() {
    const auto device = instance.GetDevice();
    // bbport (r98c_particles-visible): the lamps' block (binding 2), written in each draw's own
    // commands (vkCmdUpdateBuffer), so it lives on the GPU only.
    const VkBufferCreateInfo lamp_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(AmbientMotes::LampBlock),
        .usage = VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo lamp_alloc{};
    lamp_alloc.usage = VMA_MEMORY_USAGE_AUTO;
    VkBuffer lamp_raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &lamp_ci, &lamp_alloc, &lamp_raw, &lamp_allocation,
                        nullptr) != VK_SUCCESS) {
        return false;
    }
    lamp_buffer = lamp_raw;
    const std::array bindings{
        vk::DescriptorSetLayoutBinding{0, vk::DescriptorType::eSampledImage, 1, Stages},
        vk::DescriptorSetLayoutBinding{1, vk::DescriptorType::eSampledImage, 1,
                                       vk::ShaderStageFlagBits::eVertex},
        vk::DescriptorSetLayoutBinding{2, vk::DescriptorType::eUniformBuffer, 1,
                                       vk::ShaderStageFlagBits::eVertex},
    };
    auto set = device.createDescriptorSetLayoutUnique({
        .flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
        .bindingCount = u32(bindings.size()),
        .pBindings = bindings.data(),
    });
    if (set.result != vk::Result::eSuccess) {
        return false;
    }
    set_layout = std::move(set.value);
    const vk::PushConstantRange range{Stages, 0, u32(sizeof(AmbientMotes::Push))};
    const vk::DescriptorSetLayout set_handle = *set_layout;
    auto made_layout = device.createPipelineLayoutUnique({
        .setLayoutCount = 1,
        .pSetLayouts = &set_handle,
        .pushConstantRangeCount = 1,
        .pPushConstantRanges = &range,
    });
    if (made_layout.result != vk::Result::eSuccess) {
        return false;
    }
    layout = std::move(made_layout.value);
    const std::span<const u32> vert = AMBIENT_PARTICLES_VERT;
    const std::span<const u32> frag = AMBIENT_PARTICLES_FRAG;
    auto vert_module =
        device.createShaderModuleUnique({.codeSize = vert.size_bytes(), .pCode = vert.data()});
    auto frag_module =
        device.createShaderModuleUnique({.codeSize = frag.size_bytes(), .pCode = frag.data()});
    if (vert_module.result != vk::Result::eSuccess || frag_module.result != vk::Result::eSuccess) {
        return false;
    }
    const std::array stages{
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eVertex,
                                          .module = *vert_module.value, .pName = "main"},
        vk::PipelineShaderStageCreateInfo{.stage = vk::ShaderStageFlagBits::eFragment,
                                          .module = *frag_module.value, .pName = "main"},
    };
    const vk::PipelineVertexInputStateCreateInfo vertex_input{};
    const vk::PipelineInputAssemblyStateCreateInfo assembly{
        .topology = vk::PrimitiveTopology::eTriangleList};
    const vk::PipelineViewportStateCreateInfo viewport_state{.viewportCount = 1, .scissorCount = 1};
    const vk::PipelineRasterizationStateCreateInfo raster{
        .polygonMode = vk::PolygonMode::eFill,
        .cullMode = vk::CullModeFlagBits::eNone,
        .lineWidth = 1.0f,
    };
    const vk::PipelineMultisampleStateCreateInfo multisample{
        .rasterizationSamples = vk::SampleCountFlagBits::e1};
    const vk::PipelineDepthStencilStateCreateInfo depth_state{};
    // Screen: colour + frame (1 - colour); the frame's alpha is kept.
    const vk::PipelineColorBlendAttachmentState screen{
        .blendEnable = true,
        .srcColorBlendFactor = vk::BlendFactor::eOneMinusDstColor,
        .dstColorBlendFactor = vk::BlendFactor::eOne,
        .colorBlendOp = vk::BlendOp::eAdd,
        .srcAlphaBlendFactor = vk::BlendFactor::eZero,
        .dstAlphaBlendFactor = vk::BlendFactor::eOne,
        .alphaBlendOp = vk::BlendOp::eAdd,
        .colorWriteMask = vk::ColorComponentFlagBits::eR | vk::ColorComponentFlagBits::eG |
                          vk::ColorComponentFlagBits::eB,
    };
    const vk::PipelineColorBlendStateCreateInfo blend{.attachmentCount = 1, .pAttachments = &screen};
    const std::array dynamic_states{vk::DynamicState::eViewport, vk::DynamicState::eScissor};
    const vk::PipelineDynamicStateCreateInfo dynamic{
        .dynamicStateCount = u32(dynamic_states.size()), .pDynamicStates = dynamic_states.data()};
    const vk::Format target_format = vk::Format::eR8G8B8A8Unorm; // the UI image's UNORM view
    const vk::PipelineRenderingCreateInfo rendering{.colorAttachmentCount = 1,
                                                    .pColorAttachmentFormats = &target_format};
    auto made = device.createGraphicsPipelineUnique(
        {}, vk::GraphicsPipelineCreateInfo{
                .pNext = &rendering,
                .stageCount = u32(stages.size()),
                .pStages = stages.data(),
                .pVertexInputState = &vertex_input,
                .pInputAssemblyState = &assembly,
                .pViewportState = &viewport_state,
                .pRasterizationState = &raster,
                .pMultisampleState = &multisample,
                .pDepthStencilState = &depth_state,
                .pColorBlendState = &blend,
                .pDynamicState = &dynamic,
                .layout = *layout,
            });
    if (made.result != vk::Result::eSuccess) {
        return false;
    }
    pipeline = std::move(made.value);
    SetObjectName(device, *pipeline, "Ambient particles (r98)");
    return true;
}

void AmbientParticles::Draw(const TemporalUpscaler::UpscaledFrame& frame,
                            const CameraMotion::Matrices& camera, bool wind_on,
                            const std::array<float, 3>& wind, float open) {
    const auto now = std::chrono::steady_clock::now();
    const double seconds =
        last == std::chrono::steady_clock::time_point{}
            ? 0.0
            : std::chrono::duration<double>(now - last).count();
    last = now;
    if (window == std::chrono::steady_clock::time_point{}) {
        window = now;
    }
    // bbport (r98d_particles-still-indoors): the camera's open share of air (r117's field; 1
    // without it) reaches the motes: the lattice and the embers drift at that share of the wind
    // and the rest at the calm drift; indoors a dust mote's picture-behind light fades if dark.
    const auto& still = AmbientMotes::StillGet();
    open_follow = AmbientMotes::OpenFollow(open_follow, open, seconds);
    const float air = AmbientMotes::AirShare(open_follow, still.still);
    const float shade = AmbientMotes::IndoorShade(open_follow, still.dark);
    drift.Advance(seconds, wind_on, wind, air);
    still_stats.Add(open_follow, air, shade, drift.speed, seconds);
    // bbport (r98c_particles-visible): the lamps of this frame's lamp pass, taken into the world
    // with this camera (used and dropped here); none with BB_PARTICLES_LAMPS=0.
    AmbientMotes::LampBlock lamp_block{};
    if (lamp_gain > 0.0f && camera.valid) {
        const auto& lamp_knobs = AmbientMotes::Get();
        lamp_block = lamps.Update(camera.inv_view, seconds,
                                  lamp_gain * (lamp_knobs.show ? AmbientMotes::ShowGain : 1.0f),
                                  AmbientMotes::SparkBirth(lamp_knobs),
                                  AmbientMotes::SparkDrift(wind_on, wind, air)); // r98d
        const auto& got = lamps.Last();
        if (got.flames > 0) {
            const bool first = lamp_window.most_flames == 0;
            lamp_window.reach_min = first ? got.reach_min : std::min(lamp_window.reach_min, got.reach_min);
            lamp_window.reach_max = std::max(lamp_window.reach_max, got.reach_max);
            const auto& v = camera.view;
            const auto& p = lamp_block.place[0];
            for (std::size_t r = 0; r < 3; ++r) {
                lamp_window.flame_view[r] =
                    v[4 * r] * p[0] + v[4 * r + 1] * p[1] + v[4 * r + 2] * p[2] + v[4 * r + 3];
            }
        }
        ++lamp_window.frames;
        lamp_window.lit += got.lamps > 0 ? 1 : 0;
        lamp_window.lamps += got.lamps;
        lamp_window.flames += got.flames;
        lamp_window.most_flames = std::max(lamp_window.most_flames, got.flames);
        lamp_window.most_listed = std::max(lamp_window.most_listed, got.listed);
        lamp_window.left_out = std::max(lamp_window.left_out, got.left_out);
    } else {
        lamps.Clear();
    }
    // bbport (r98d_particles-still-indoors): the indoor shade, for the dust's colour (0 in the open).
    lamp_block.wind[3] = shade;
    // bbport (r98e_moths-at-lamps): moths round the lit lamps of the block (BB_PARTICLES_MOTHS above 0); none
    // round a light the hunter carries; calm = 1 - the air share (0 in the open). Their instances follow
    // the flames' in the draw, only in a frame that shows one.
    u32 moth_instances = 0;
    if (moth_level > 0 && lamp_block.info[2] > 0.0f && camera.valid) {
        std::array<float, 3> hunter{};
        const bool hunter_known = BbEngine::world_player_position(hunter.data()) &&
                                  std::isfinite(hunter[0]) && std::isfinite(hunter[1]) &&
                                  std::isfinite(hunter[2]);
        const std::array<float, 3> eye{camera.inv_view[3], camera.inv_view[7], camera.inv_view[11]};
        const AmbientMotes::MothStats got =
            moths.Apply(lamp_block, eye, hunter_known, hunter, moth_level, 1.0f - air, seconds);
        moth_window.Add(got);
        moth_instances = got.shown > 0 ? u32(AP_MOTH_INSTANCES) : 0u;
    }
    // The lattice's instances, then the flames' ember slots while the lamps are on.
    const u32 lamp_instances =
        AmbientMotes::Instances + (lamp_block.info[2] > 0.0f ? AmbientMotes::FlameInstances : 0u) +
        moth_instances; // r98e: the moths' instances after the flames'
    const bool srgb = frame.scene_format == vk::Format::eR8G8B8A8Srgb;
    const bool usable = pipeline && frame.view && frame.depth && frame.scene && camera.valid &&
                        Rgba8(frame.scene_format) &&
                        frame.width > 0 && frame.height > 0 && frame.width <= 0xffffu &&
                        frame.height <= 0xffffu && frame.render_width > 0 &&
                        frame.render_height > 0 && frame.render_width <= 0xffffu &&
                        frame.render_height <= 0xffffu;
    if (!usable) {
        ++skipped;
    } else {
        const auto& knobs = AmbientMotes::Get();
        AmbientMotes::Push push = AmbientMotes::MakePush(
            knobs, drift, camera.view, camera.inv_view, camera.proj, frame.width, frame.height,
            frame.render_width, frame.render_height, frame.jitter, srgb);
        // bbport (r98b_particles-reduced-scene): the frame before the UI has the output size and
        // no jitter (the game's finished frame after an upscale before its post): its light is
        // read at output pixels.
        static_assert((AP_FLAG_SCENE_OUTPUT & AP_FLAG_SCENE_SRGB) == 0, "two flag bits");
        if (frame.scene_at_output) {
            push.frame[3] |= u32(AP_FLAG_SCENE_OUTPUT);
        }
        if (!first_said) {
            first_said = true;
            std::printf("Ambient particles (r98): first draw into %ux%u %s (scene depth %ux%u; "
                        "the frame before the UI at the %s size, read %s)\n",
                        frame.width, frame.height,
                        frame.path && frame.path[0] ? frame.path : "after the upscale",
                        frame.render_width, frame.render_height,
                        frame.scene_at_output ? "output" : "render",
                        srgb ? "through an sRGB view" : "as stored");
        }
        scheduler.EndRendering();
        auto* profiler = GpuProfiler::Get();
        const u64 resume = profiler ? profiler->Current() : 0;
        if (profiler) {
            profiler->Mark(ProfileKey, [] { return std::string{"Ambient particles (r98)"}; });
        }
        const vk::Extent2D extent{frame.width, frame.height};
        scheduler.RecordCrumb(
            {.name = "Ambient particles"},
            [push, extent, target = frame.view, depth = frame.depth, scene = frame.scene,
             bound = *pipeline, bound_layout = *layout, lamp_block, lamp_target = lamp_buffer,
             instances = lamp_instances](vk::CommandBuffer cmd) {
                // bbport (r98c_particles-visible): this frame's lamps' block, after the last
                // frame's draw read it.
                const vk::MemoryBarrier2 to_upload{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryRead,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &to_upload});
                cmd.updateBuffer(lamp_target, 0, sizeof(lamp_block), &lamp_block);
                // The depth and the frame before the UI were written by earlier passes; the
                // output image's last barrier (RunScaled, or RunUiOnly's copy) already ends at
                // colour attachment use.
                const vk::MemoryBarrier2 before{
                    .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eVertexShader |
                                    vk::PipelineStageFlagBits2::eFragmentShader |
                                    vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                    .dstAccessMask = vk::AccessFlagBits2::eShaderSampledRead |
                                     vk::AccessFlagBits2::eUniformRead | // r98c: the lamps' block
                                     vk::AccessFlagBits2::eColorAttachmentRead |
                                     vk::AccessFlagBits2::eColorAttachmentWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
                const vk::RenderingAttachmentInfo attachment{
                    .imageView = target,
                    .imageLayout = vk::ImageLayout::eGeneral,
                    .loadOp = vk::AttachmentLoadOp::eLoad,
                    .storeOp = vk::AttachmentStoreOp::eStore,
                };
                cmd.beginRendering({
                    .renderArea = {{0, 0}, extent},
                    .layerCount = 1,
                    .colorAttachmentCount = 1,
                    .pColorAttachments = &attachment,
                });
                const std::array infos{
                    vk::DescriptorImageInfo{{}, depth, vk::ImageLayout::eGeneral},
                    vk::DescriptorImageInfo{{}, scene, vk::ImageLayout::eGeneral},
                };
                // bbport (r98c_particles-visible): binding 2, the lamps' block.
                const vk::DescriptorBufferInfo lamp_info{lamp_target, 0, sizeof(lamp_block)};
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[0]},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage, .pImageInfo = &infos[1]},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eUniformBuffer, .pBufferInfo = &lamp_info},
                }};
                cmd.bindPipeline(vk::PipelineBindPoint::eGraphics, bound);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eGraphics, bound_layout, 0, writes);
                cmd.pushConstants(bound_layout, Stages, 0, u32(sizeof(push)), &push);
                cmd.setViewport(0, vk::Viewport{0.0f, 0.0f, float(extent.width),
                                                float(extent.height), 0.0f, 1.0f});
                cmd.setScissor(0, vk::Rect2D{{0, 0}, extent});
                cmd.draw(6, instances, 0, 0); // r98c: the lattice's, then the flames' slots
                cmd.endRendering();
                // The UI draws into the same image next; the frame generation and native HDR
                // copies read it later.
                const vk::MemoryBarrier2 after{
                    .srcStageMask = vk::PipelineStageFlagBits2::eColorAttachmentOutput,
                    .srcAccessMask = vk::AccessFlagBits2::eColorAttachmentWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                    .dstAccessMask =
                        vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                };
                cmd.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
            });
        // The guest pipelines' dynamic state must be emitted again after this pipeline.
        scheduler.GetDynamicState().Invalidate();
        if (resume) {
            profiler->Resume(resume);
        }
        ++draws;
    }
    // A line every 10 s while frames reach this point, so a test sees that it acted.
    const double elapsed = std::chrono::duration<double>(now - window).count();
    if (elapsed >= 10.0) {
        std::printf("Ambient particles: %u draws and %u frames skipped in the last %.1f s, drift "
                    "%.2f %.2f %.2f m (%s), time %.1f s\n",
                    draws, skipped, elapsed, drift.offset[0], drift.offset[1], drift.offset[2],
                    wind_on ? "with the wind" : "calm", drift.time);
        // bbport (r98c_particles-visible): the lamps of the same 10 s.
        if (lamp_gain > 0.0f) {
            const double frames = lamp_window.frames > 0 ? double(lamp_window.frames) : 1.0;
            std::printf("Ambient particles (r98c): lamps in %u of %u frames, %.1f lamps and %.1f "
                        "flames a frame, at most %u flames (reach %.1f to %.1f m), at most %u lamps "
                        "listed near the camera, at most %u left out (over %u lamps or %u flames), "
                        "nearest flame at view %.2f %.2f %.2f m\n",
                        lamp_window.lit, lamp_window.frames, double(lamp_window.lamps) / frames,
                        double(lamp_window.flames) / frames, lamp_window.most_flames,
                        double(lamp_window.reach_min), double(lamp_window.reach_max),
                        lamp_window.most_listed, lamp_window.left_out, u32(AP_MAX_LAMPS),
                        u32(AP_MAX_FLAMES), double(lamp_window.flame_view[0]),
                        double(lamp_window.flame_view[1]), double(lamp_window.flame_view[2]));
        }
        // bbport (r98d_particles-still-indoors): the air the motes had in the same 10 s.
        char still_line[320];
        still_stats.Text(still_line, sizeof(still_line), elapsed);
        std::printf("%s\n", still_line);
        // bbport (r98e_moths-at-lamps): the moths of the same 10 s.
        if (moth_level > 0) {
            char moth_line[360];
            moth_window.Text(moth_line, sizeof(moth_line), elapsed);
            std::printf("%s\n", moth_line);
            moth_window = {};
        }
        still_stats = {};
        lamp_window = {};
        window = now;
        draws = 0;
        skipped = 0;
    }
}

} // namespace Vulkan
