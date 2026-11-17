// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_sun_term_view.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/host_shaders/sun_term_view_copy_comp.h"
#include "video_core/host_shaders/sun_term_view_show_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// the live knobs of the test tools (r84_live-test-knobs): BB_RT_SUN_TERM_VIEW is switched while the game runs
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define SUN_TERM_LIVE 1
#endif

namespace Vulkan {
namespace {
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto TermFormat = vk::Format::eR8Unorm;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr u32 Group = 8; // sun_term_view.comp's workgroup side
// EffectPass::Mark's key (the row "Lighting: sun term view"): in use: 6, 10-18, 51, 61-64, 80, 81, 86, 95, 97, 99, 100, 105, 107, 111,
// 117, 119, 129; 130 is free
constexpr u64 ProfileRow = 130;
SunTermView* active = nullptr;

/// Exactly "1" is on.
bool ParseOn(const char* text) {
    return text != nullptr && text[0] == '1' && text[1] == '\0';
}

/// BB_RT_SUN_TERM_VIEW now: live in a build with the live knobs header, else read once.
bool ViewNow() {
#ifdef SUN_TERM_LIVE
    static BbLiveKnobs::Knob<bool> knob{"BB_RT_SUN_TERM_VIEW", [](const char* text) -> bool { return ParseOn(text); }};
    return knob.Get();
#else
    static const bool fixed = ParseOn(std::getenv("BB_RT_SUN_TERM_VIEW"));
    return fixed;
#endif
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = info};
}
} // namespace

bool SunTermView::Wanted() {
#ifdef SUN_TERM_LIVE
    if (std::getenv("BB_LIVE_KNOBS_FILE") != nullptr) {
        return true;
    }
#endif
    return ParseOn(std::getenv("BB_RT_SUN_TERM_VIEW"));
}

SunTermView* SunTermView::Active() noexcept {
    return active;
}

SunTermView::SunTermView(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                         Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    active = this;
    on = ViewNow();
    if (on) {
        BbReport::Printf("Sun term view (t129c): view on at frame 0 (the ray traced sun/moon shadow term as grey, white lit)\n");
    }
}

SunTermView::~SunTermView() {
    if (active == this) {
        active = nullptr;
    }
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool SunTermView::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TermFormat) && EffectPass::StorageFormat(instance, SceneFormat) &&
        EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
        EffectPass::Create(instance, copy_pass.set_layout, copy_pass.layout, copy_pass.pipeline, {eStorageImage, eStorageImage},
                           sizeof(Push), SUN_TERM_VIEW_COPY_COMP, "Sun term view copy") &&
        EffectPass::Create(instance, show_pass.set_layout, show_pass.layout, show_pass.pipeline, {eStorageImage, eStorageImage},
                           sizeof(Push), SUN_TERM_VIEW_SHOW_COMP, "Sun term view show");
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void SunTermView::Fail(const char* why) {
    failed = true;
    have_term = false;
    BbReport::Printf("Sun term view (t129c): off - %s\n", why);
    ReleaseImage();
}

void SunTermView::ReleaseImage() {
    have_term = false;
    if (term_image) {
        scheduler.DeferOperation([image = std::move(term_image), view = std::move(term_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    term_view.reset();
    term_width = term_height = 0;
}

bool SunTermView::EnsureImage(u32 width, u32 height) {
    if (term_image && term_width == width && term_height == height) {
        return true;
    }
    ReleaseImage();
    if (!EffectPass::HasRoom(instance, 2ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = TermFormat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    term_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    term_image.Create(image_ci);
    SetObjectName(device, vk::Image(term_image), "Sun term view term");
    term_view = Check<"create sun term view term view">(device.createImageViewUnique({
        .image = vk::Image(term_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TermFormat,
        .subresourceRange = ColorLevel,
    }));
    term_width = width;
    term_height = height;
    term_fresh = true;
    return true;
}

bool SunTermView::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
    const auto& image = texture_cache.GetImage(id);
    reduced = scene_targets.Reduced() && scene_targets.EligibleScene(image);
    width = image.info.size.width;
    height = image.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    return width >= 16 && height >= 16;
}

/// The lit scene as a storage image written by the pass: the reduced proxy or the image itself (General layout); null when it cannot.
vk::ImageView SunTermView::SceneView(VideoCore::ImageId id) {
    auto& image = texture_cache.GetImage(id);
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, ReadWrite);
        return (proxy.usage & vk::ImageUsageFlagBits::eStorage) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
        return {};
    }
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == image.info.pixel_format) {
            entry.last_use = ++view_uses;
            runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, ReadWrite);
            return entry.view;
        }
        if (entry.last_use < oldest->last_use) {
            oldest = &entry;
        }
    }
    const auto device = instance.GetDevice();
    if (oldest->view) {
        scheduler.DeferOperation([device, view = oldest->view] { device.destroyImageView(view); });
    }
    *oldest = {
        .image = handle,
        .uid = image.image_uid,
        .format = image.info.pixel_format,
        .view = Check<"create sun term view scene view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = ColorLevel,
        })),
        .last_use = ++view_uses,
    };
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, ReadWrite);
    return oldest->view;
}

void SunTermView::Capture(vk::ImageView target, u32 width, u32 height) {
    if (!on || failed || !target || width < 16 || height < 16 || camera_motion.PreviewFrame()) {
        return;
    }
    if (!Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        Fail("no room for the term image");
        return;
    }
    scheduler.EndRendering();
    Push push{};
    push.size = {float(width), float(height)};
    const bool fresh = std::exchange(term_fresh, false);
    EffectPass::Mark(ProfileRow, "sun term view");
    scheduler.RecordCrumb(
        {.name = "sun term view copy"},
        [push, fresh, width, height, target, handle = vk::Image(term_image), term = *term_view,
         pipeline = *copy_pass.pipeline, layout = *copy_pass.layout](vk::CommandBuffer cmd) {
            EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
            if (fresh) {
                EffectPass::InitGeneral(cmd, handle, ColorLevel);
            }
            const std::array infos{Info(target), Info(term)};
            const std::array writes{ImageWrite(0, &infos[0]), ImageWrite(1, &infos[1])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + Group - 1) / Group, (height + Group - 1) / Group, 1);
            EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
        });
    have_term = true;
    ++stats.captures;
}

void SunTermView::Show(VideoCore::ImageId scene, bool lamps_pending) {
    if (!on || !have_term || failed || !scene || !term_image || lamps_pending || camera_motion.PreviewFrame()) {
        return;
    }
    const auto& image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) || width != term_width ||
        height != term_height) {
        ++stats.skip_shape;
        if (!told_show) {
            told_show = true;
            BbReport::Printf("Sun term view (t129c): show left out (first time): the lit scene is format %u, %ux%u, the term "
                             "%ux%u (RGBA16F, 97, of the term's size wanted)\n",
                             u32(image.info.pixel_format), width, height, term_width, term_height);
        }
        return;
    }
    const SceneUseScope scene_use{"sun term view"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = SceneView(scene);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.size = {float(width), float(height)};
    ++stats.shows;
    EffectPass::Mark(ProfileRow, "sun term view");
    scheduler.RecordCrumb(
        {.name = "sun term view show"},
        [push, width, height, scene_view, term = *term_view, pipeline = *show_pass.pipeline,
         layout = *show_pass.layout](vk::CommandBuffer cmd) {
            EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
            const std::array infos{Info(term), Info(scene_view)};
            const std::array writes{ImageWrite(0, &infos[0]), ImageWrite(1, &infos[1])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + Group - 1) / Group, (height + Group - 1) / Group, 1);
            EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
        });
}

void SunTermView::OnFrameEnd() {
    const bool now = ViewNow();
    have_term = false; // a frame's capture is shown in that frame only
    if (now != on) {
        on = now;
        BbReport::Printf("Sun term view (t129c): view %s at frame %llu%s\n", now ? "on" : "off",
                         static_cast<unsigned long long>(frame),
                         now ? " (the ray traced sun/moon shadow term as grey, white lit, black shadowed)" : "");
        stats = {};
        if (!now) {
            ReleaseImage();
        }
    }
    ++frame;
    if (!on || ++stats.frames < LineFrames) {
        return;
    }
    BbReport::Printf("Sun term view (t129c): view on: %u captures, %u shows, %u shows left out%s\n", stats.captures, stats.shows,
                     stats.skip_shape, failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
