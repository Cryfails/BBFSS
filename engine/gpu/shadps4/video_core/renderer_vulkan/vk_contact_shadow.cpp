// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_contact_shadow.h"

#include <array>
#include <cstdio>
#include <cstdlib>

#include "bbport_settings.h"
#include "engine/graphics.h"
#include "common/assert.h"
#include "video_core/host_shaders/contact_shadow_comp.h"
#include "video_core/renderer_vulkan/vk_bend_sss.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)
#include "video_core/renderer_vulkan/vk_sun_term_view.h" // bbport (t129c_sun-term-view)
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
struct Push {
    u32 buf_off;
    u32 frame_index;
    std::array<float, 2> size;
    std::array<float, 4> light_coordinate;
    std::array<s32, 2> wave_offset;
    float surface_thickness;
    float bilinear_threshold;
    float strength;
    float shadow_contrast;
    u32 debug;
    u32 contact_on;
    u32 pcss_on;
    float light_tan;
    float max_penumbra_m;
    float min_penumbra_m;
    float bias_m;
    u32 filter_on;
    float cascade_blend;
    float bend_distance_scale; // 0: no uniforms bound, so no distance fade
};
static_assert(sizeof(Push) == 96);

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;

}

ContactShadow::ContactShadow(const Instance& instance_, Scheduler& scheduler_,
                             VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                             SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                             RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_},
      rt_shadow{rt_shadow_} {
}

bool ContactShadow::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest,
                                  vk::SamplerAddressMode::eClampToBorder,
                                  vk::BorderColor::eFloatOpaqueWhite) &&
        EffectPass::Create(instance, set_layout, layout, pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                            eCombinedImageSampler, eStorageBuffer},
                           sizeof(Push), CONTACT_SHADOW_COMP, "Contact shadows");
    if (!made) {
        failed = true;
        std::printf("Contact shadows: off - this GPU cannot run the pass\n");
    }
    return made;
}

ContactShadow::~ContactShadow() = default;

void ContactShadow::OnShadowDraw(VideoCore::ImageId target, const Inputs& inputs) {
    if (failed || !target || !inputs.constants) {
        return;
    }
    const auto& settings = BbSettings::Get();
    use_contact = settings.effects[BbSettings::EffectContactShadows].load(std::memory_order_relaxed);
    use_pcss = inputs.uniforms && inputs.shadow_map &&
               settings.effects[BbSettings::EffectPcss].load(std::memory_order_relaxed);
    use_rt = inputs.uniforms && rt_shadow.Complete() && rt_shadow.SunWanted();
    if (use_rt) {
        use_contact = false;
        use_pcss = false;
    }
    use_filter = use_pcss;
    if ((!use_contact && !use_filter && !use_rt && !rt_shadow.Wanted()) || !Ready()) {
        return;
    }
    pending = target;
    pending_inputs = inputs;
}

void ContactShadow::OnBlurDraw(VideoCore::ImageId target, VAddr source) {
    if (!pending || !target) return;
    if (texture_cache.GetImage(pending).info.guest_address != source) {
        std::printf("Directional shadows: unexpected blur resource chain; retaining native result\n");
        pending = {};
        return;
    }
    pending = target;
}

void ContactShadow::Flush(bool native_blur) {
    if (!pending || native_blur) {
        return;
    }
    const auto target_id = pending;
    pending = {};
    const auto depth_id = camera_motion.Depth();
    if (!depth_id) {
        return;
    }
    auto& target = texture_cache.GetImage(target_id);
    auto& depth = texture_cache.GetImage(depth_id);
    const bool reduced = scene_targets.Reduced() && scene_targets.Eligible(target) &&
                         scene_targets.Eligible(depth);
    if (target.info.pixel_format != vk::Format::eR8G8B8A8Unorm ||
        (!reduced && !(target.usage_flags & vk::ImageUsageFlagBits::eStorage))) {
        failed = true;
        std::printf("Contact shadows: the shadow target is not an RGBA8 storage image; off\n");
        return;
    }
    scheduler.EndRendering();
    if (!use_contact && !use_filter && !use_rt) {
        rt_shadow.RecordBuilds();
        return;
    }
    const auto device = instance.GetDevice();
    vk::ImageView target_view{}, depth_view{};
    u32 width = target.info.size.width, height = target.info.size.height;
    if (reduced) {
        VideoCore::ImageViewInfo target_info, depth_info;
        target_info.format = target.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(target_id, target_info, Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            failed = true;
            std::printf("Contact shadows: the reduced shadow target is not a storage image; off\n");
            return;
        }
        target_view = proxy.view;
        // bbport (r22_barriers): right after the target's barrier (its Read, compute stage)
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        const auto size = scene_targets.ProxySize(target);
        width = size.width;
        height = size.height;
    } else {
        target_view = Check<"create contact shadow target view">(device.createImageView({
            .image = target.GetImage(),
            .viewType = vk::ImageViewType::e2D,
            .format = vk::Format::eR8G8B8A8Unorm,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        }));
        depth_view = Check<"create contact shadow depth view">(device.createImageView({
            .image = depth.GetImage(),
            .viewType = vk::ImageViewType::e2D,
            .format = depth.info.pixel_format,
            .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
        }));
        scheduler.DeferOperation([device, target_view, depth_view] {
            device.destroyImageView(target_view);
            device.destroyImageView(depth_view);
        });
        runtime.Transit(&target, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }

    // Bend's wavefront layout is only needed for the contact shadows; the shadow-map filter on
    // its own runs one thread per pixel, in rows of 64.
    BendSss::DispatchList dispatches;
    bool bend = use_contact;
    if (bend) {
        if (pending_inputs.has_constants_cpu) {
            dispatches = BendSss::BuildDirectionalDispatchList(
                pending_inputs.constants_cpu.data(), int(width), int(height), flip);
        }
        if (dispatches.dispatch_count == 0) {
            bend = false;
            static bool warned = false;
            if (!warned) {
                warned = true;
                std::printf("Contact shadows: sun projection unavailable; skipped\n");
            }
            if (!use_filter) {
                rt_shadow.RecordBuilds();
                return;
            }
        }
    }
    static bool printed = false;
    if (!printed) {
        printed = true;
        std::printf("Contact shadows: Bend Studio compute, %ux%u, 60 samples, %d dispatches, "
                    "strength %.2f\n",
                    width, height, dispatches.dispatch_count, strength);
        std::printf("Directional shadows: %s after native blur, cascade blend %.0f%%\n",
                    use_filter ? (use_pcss ? "atlas-safe PCSS" : "atlas-safe PCF") : "native filter",
                    100.0f * BbEngine::Graphics::DirectionalShadowBlend());
    }
    const Push push{
        .buf_off = pending_inputs.constants_offset_word,
        .frame_index = pending_inputs.frame_index,
        .size = {float(width), float(height)},
        .light_coordinate = dispatches.light_coordinate,
        .wave_offset = {},
        .surface_thickness = surface_thickness,
        .bilinear_threshold = bilinear_threshold,
        .strength = strength,
        .shadow_contrast = shadow_contrast,
        .debug = debug,
        .contact_on = bend ? 1u : 0u,
        .pcss_on = use_pcss ? 1u : 0u,
        .light_tan = light_tan,
        .max_penumbra_m = max_penumbra_m,
        .min_penumbra_m = min_penumbra_m,
        .bias_m = bias_m,
        .filter_on = use_filter ? 1u : 0u,
        .cascade_blend = BbEngine::Graphics::DirectionalShadowBlend(),
        .bend_distance_scale = pending_inputs.uniforms ? bend_distance_scale : 0.0f,
    };
    const auto in = pending_inputs;
    const bool filter_on = use_filter;
    if (!use_contact && !use_filter) {
        sun_replaced = rt_shadow.Record({.constants = in.constants,
                          .constants_offset = in.constants_offset,
                          .constants_range = in.constants_range,
                          .uniforms = in.uniforms,
                          .uniforms_offset = in.uniforms_offset,
                          .uniforms_range = in.uniforms_range,
                          .depth = depth_view,
                          .target = target_view,
                          .constants_offset_word = in.constants_offset_word,
                          .frame_index = in.frame_index,
                          .width = width,
                          .height = height});
        // bbport (t129c_sun-term-view, TOOL): BB_RT_SUN_TERM_VIEW on only: the sun's visibility copied out before the clouds change it
        if (auto* term_view = SunTermView::Active(); term_view && sun_replaced) {
            term_view->Capture(target_view, width, height);
        }
        // bbport (r105_cloud-shadows): the clouds into the alpha the ray traced sun (or the
        // VSM) just wrote, before the game's directional light reads it (null when off)
        if (auto* clouds = CloudShadow::Active(); clouds && sun_replaced) {
            clouds->Ground(in, depth_view, target_view, width, height);
        }
        return;
    }
    EffectPass::Mark(4, "contact shadows and PCSS");
    scheduler.RecordCrumb(
        {.name = "Contact shadows"},
        [push, dispatches, bend, width, height, target_view, depth_view, sampler = *sampler, in, filter_on,
         constants = pending_inputs.constants, constants_offset = pending_inputs.constants_offset,
         constants_range = pending_inputs.constants_range, pipeline = *pipeline,
         layout = *layout](vk::CommandBuffer cmdbuf) {
            const vk::MemoryBarrier2 before{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderRead |
                                 vk::AccessFlagBits2::eShaderWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            const vk::DescriptorBufferInfo buffer_info{constants, constants_offset,
                                                       constants_range};
            const vk::DescriptorImageInfo depth_info{sampler, depth_view,
                                                     vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo target_info{{}, target_view, vk::ImageLayout::eGeneral};
            // The uniforms also carry the sun-shadow distance fade the Bend shadows use.
            const vk::DescriptorBufferInfo ubo_info =
                in.uniforms ? vk::DescriptorBufferInfo{in.uniforms, in.uniforms_offset,
                                                   in.uniforms_range}
                        : buffer_info;
            const vk::DescriptorImageInfo map_info =
                filter_on ? vk::DescriptorImageInfo{sampler, in.shadow_map, in.shadow_layout}
                        : depth_info;
            const std::array<vk::WriteDescriptorSet, 5> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer,
                 .pBufferInfo = &buffer_info},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage,
                 .pImageInfo = &target_info},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &map_info},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer,
                 .pBufferInfo = &ubo_info},
            }};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            if (!bend) {
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(Push),
                                     &push);
                cmdbuf.dispatch((width + 63) / 64, height, 1);
            }
            for (int i = 0; bend && i < dispatches.dispatch_count; ++i) {
                Push dispatch_push = push;
                dispatch_push.wave_offset = dispatches.dispatches[i].wave_offset;
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(Push), &dispatch_push);
                const auto& count = dispatches.dispatches[i].wave_count;
                cmdbuf.dispatch(count[0], count[1], count[2]);
            }
            const vk::MemoryBarrier2 after{
                .srcStageMask = Compute,
                .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .dstAccessMask = vk::AccessFlagBits2::eMemoryRead |
                                 vk::AccessFlagBits2::eMemoryWrite};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        });
    if (use_rt) {
        rt_shadow.Record({.constants = in.constants,
                          .constants_offset = in.constants_offset,
                          .constants_range = in.constants_range,
                          .uniforms = in.uniforms,
                          .uniforms_offset = in.uniforms_offset,
                          .uniforms_range = in.uniforms_range,
                          .depth = depth_view,
                          .target = target_view,
                          .constants_offset_word = in.constants_offset_word,
                          .frame_index = in.frame_index,
                          .width = width,
                          .height = height});
    } else {
        rt_shadow.RecordBuilds();
    }
}

}
