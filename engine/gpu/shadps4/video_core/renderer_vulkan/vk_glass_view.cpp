// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_glass_view.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/glass_view_mark_comp.h"
#include "video_core/host_shaders/glass_view_paint_comp.h"
#include "video_core/host_shaders/glass_view_show_comp.h"
#include "video_core/host_shaders/glass_view_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r129a_glass-registry): the live knobs of the test tools (r84_live-test-knobs): in a build with the header,
// BB_GLASS_VIEW is switched while the game runs.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define GLASS_VIEW_LIVE 1
#endif

namespace Vulkan {
namespace {
namespace R = GlassRegistryRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto TagFormat = vk::Format::eR32Uint;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
// EffectPass::Mark's key (the row "Lighting: glass view"): the rows are keys, 0x4C490000 | key; in use: 6, 10-18, 51, 61-64,
// 80, 81, 86, 95, 97, 99, 100, 105, 107, 111, 117, 119; 129 is free
constexpr u64 ProfileRow = 129;

/// Target 0 formats a sampled view reads as float (a G-buffer draw's normal target, a forward draw's scene colour).
bool FloatColour(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb ||
           format == vk::Format::eR16G16B16A16Sfloat || format == vk::Format::eA2B10G10R10UnormPack32 ||
           format == vk::Format::eB10G11R11UfloatPack32;
}

/// BB_GLASS_VIEW now: live in a build with the live knobs header, else read once. 1 only: the view is on.
bool ViewNow() {
#ifdef GLASS_VIEW_LIVE
    static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_VIEW", R::ParseView};
    return knob.Get() == 1;
#else
    static const bool fixed = R::ParseView(std::getenv("BB_GLASS_VIEW")) == 1;
    return fixed;
#endif
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

/// What a pass's commands begin with: the game's writes before it (and the last pass's reads of the tag) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead | vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// "any" or the number.
std::string Wild(u32 value, u32 any) {
    return value == any ? std::string("any") : std::to_string(value);
}
} // namespace

// ---- the registry ----

GlassRegistry::GlassRegistry() : table{R::Load()} {
    const char* text = std::getenv("BB_GLASS_TABLE");
    const char* view_text = std::getenv("BB_GLASS_VIEW");
    const u8 view = R::ParseView(view_text);
    BbReport::Printf("Glass registry (r129a): BB_GLASS_TABLE=%.200s: %u entries (%u built-in), %u errors; view %s\n",
                     text ? text : "", table.count, table.builtins, table.errors,
                     !GlassView::Wanted() ? "off" : (view == 1 ? "on" : "off (live: BB_GLASS_VIEW)"));
    for (u32 i = 0; i < table.count; ++i) {
        const auto& e = table.entries[i];
        BbReport::Printf("Glass registry (r129a): entry %u %s %08llx:%08llx idx %s first %s tint %06x f0 %.2f%s%s\n", i + 1,
                         R::KindName(e.kind), static_cast<unsigned long long>(e.vs), static_cast<unsigned long long>(e.ps),
                         Wild(e.index_count, R::AnyCount).c_str(), Wild(e.first_index, R::AnyFirst).c_str(), e.tint,
                         double(e.f0), e.builtin ? " (built-in)" : "",
                         e.kind == R::Kind::Lantern ? " (whole draw: the panes need a triangle class, a later stage)" : "");
    }
    for (u32 i = 0; i < std::min<u32>(table.errors, u32(table.first_errors.size())); ++i) {
        BbReport::Printf("Glass registry (r129a): error in entry %u: %s, skipped\n", u32(table.first_errors[i].ordinal),
                         R::ReasonName(table.first_errors[i].reason));
    }
    if (table.errors > table.first_errors.size()) {
        BbReport::Printf("Glass registry (r129a): %u more errors not listed\n",
                         table.errors - u32(table.first_errors.size()));
    }
    if (view == 2) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s is neither 0 nor 1: view off\n", view_text);
    }
}

void GlassRegistry::SayOff() {
    const char* text = std::getenv("BB_GLASS_TABLE");
    if (text != nullptr && text[0] != '\0' && std::strcmp(text, "0") != 0 && std::strcmp(text, "off") != 0) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_TABLE=%.40s: no valid entry, registry off\n", text);
        const auto& table = R::Load();
        for (u32 i = 0; i < std::min<u32>(table.errors, u32(table.first_errors.size())); ++i) {
            BbReport::Printf("Glass registry (r129a): error in entry %u: %s, skipped\n",
                             u32(table.first_errors[i].ordinal), R::ReasonName(table.first_errors[i].reason));
        }
    }
    const char* view_text = std::getenv("BB_GLASS_VIEW");
    const u8 view = R::ParseView(view_text);
    if (view == 1) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s needs BB_GLASS_TABLE; view off\n", view_text);
    } else if (view == 2) {
        BbReport::Printf("Glass registry (r129a): BB_GLASS_VIEW=%.16s is neither 0 nor 1: view off\n", view_text);
    }
}

void GlassRegistry::OnFrameEnd() {
    last_frame_mask = frame_mask.exchange(0, std::memory_order_relaxed);
    for (u32 i = 0; i < table.count; ++i) {
        const u32 draws = frame_draws[i].exchange(0, std::memory_order_relaxed);
        last_frame_draws[i] = draws;
        if (draws != 0) {
            window_draws[i] += draws;
            ++window_frames[i];
        }
    }
    ++frames;
    if (frames - window_start < LineFrames) {
        return;
    }
    u32 hit = 0, total = 0;
    for (u32 i = 0; i < table.count; ++i) {
        hit += window_draws[i] != 0 ? 1u : 0u;
        total += window_draws[i];
    }
    BbReport::Printf("Glass registry (r129a): frames %llu-%llu: %u of %u entries hit, %u draws\n",
                     static_cast<unsigned long long>(window_start + 1), static_cast<unsigned long long>(frames), hit,
                     table.count, total);
    for (u32 i = 0; i < table.count; ++i) {
        const auto& e = table.entries[i];
        BbReport::Printf("Glass registry (r129a): entry %u %s %08llx:%08llx: %u draws in %u/%u frames\n", i + 1,
                         R::KindName(e.kind), static_cast<unsigned long long>(e.vs), static_cast<unsigned long long>(e.ps),
                         window_draws[i], window_frames[i], u32(frames - window_start));
    }
    window_draws = {};
    window_frames = {};
    window_start = frames;
}

// ---- the draw hook ----

void Rasterizer::GlassRegistryDraw(const GraphicsPipeline* pipeline, bool is_indexed, u32 index_offset) {
    auto& dc = Dc();
    if (glass_view) {
        glass_view->FlushMark(); // the draw before a hit has finished: its MARK goes in front of this draw
    }
    dc.glass_hit = 0;
    dc.clear_draw = false; // bbport (r131c_cabinet-glass-clear)
    const auto* ps = pipeline->GetStages()[u32(Shader::SwStage::Fragment)];
    if (!ps) {
        return;
    }
    const u8 hit = R::Lookup(glass_registry->Rules(), pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash, ps->pgm_hash,
                             u32(Regs().num_indices), is_indexed ? index_offset : R::AnyFirst);
    if (hit == 0) {
        return;
    }
    dc.glass_hit = hit;
    glass_registry->Hit(u8(hit - 1));
    // bbport (r131c_cabinet-glass-clear): a hit of a clearing kind (the cabinet's pane) is recorded into side images when the knob is
    // on (vk_glass_clear.h): a G-buffer draw or a draw with no colour target, in the scene camera's pass. No GlassClear: stays false.
    dc.clear_draw = glass_clear && glass_clear->Wants(hit, gbuffer_draw || pipeline->GetGraphicsKey().mrt_mask == 0,
                                                      camera_motion->PreviewFrame(),
                                                      db_desc.first && db_desc.first == camera_motion->Depth());
    if (glass_view && glass_view->On()) {
        const u32 mrt = u32(pipeline->GetGraphicsKey().mrt_mask);
        // PrepareRenderState has run: cb_descs and db_desc are this draw's
        glass_view->Snapshot(cb_descs[0].first, db_desc.first, std::popcount(mrt) >= 5,
                             glass_registry->Rules().entries[hit - 1].kind, point_shadow->Pending());
    }
}

// ---- the view ----

bool GlassView::Wanted() {
#ifdef GLASS_VIEW_LIVE
    if (std::getenv("BB_LIVE_KNOBS_FILE") != nullptr) {
        return true;
    }
#endif
    return R::ParseView(std::getenv("BB_GLASS_VIEW")) == 1;
}

GlassView::GlassView(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                     Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    on = ViewNow();
}

GlassView::~GlassView() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool GlassView::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TagFormat) && EffectPass::StorageFormat(instance, SceneFormat) &&
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage}, sizeof(Push),
                           GLASS_VIEW_SNAPSHOT_COMP, "Glass view snapshot") &&
        EffectPass::Create(instance, mark_pass.set_layout, mark_pass.layout, mark_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage}, sizeof(Push),
                           GLASS_VIEW_MARK_COMP, "Glass view mark") &&
        EffectPass::Create(instance, paint_pass.set_layout, paint_pass.layout, paint_pass.pipeline,
                           {eSampledImage, eStorageImage, eStorageImage}, sizeof(Push), GLASS_VIEW_PAINT_COMP,
                           "Glass view paint") &&
        EffectPass::Create(instance, show_pass.set_layout, show_pass.layout, show_pass.pipeline,
                           {eStorageImage, eSampledImage, eStorageImage}, sizeof(Push), GLASS_VIEW_SHOW_COMP,
                           "Glass view show");
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void GlassView::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Glass view (r129a): off - %s\n", why);
    ReleaseImage();
}

void GlassView::ReleaseImage() {
    if (tag_image) {
        scheduler.DeferOperation([image = std::move(tag_image), view = std::move(tag_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    if (before_image) {
        scheduler.DeferOperation([image = std::move(before_image), view = std::move(before_view)]() mutable {
            view.reset();
            image.Destroy();
        });
    }
    tag_view.reset();
    before_view.reset();
    tag_width = tag_height = 0;
}

bool GlassView::EnsureImage(u32 width, u32 height) {
    if (tag_image && tag_width == width && tag_height == height) {
        return true;
    }
    ReleaseImage();
    if (!EffectPass::HasRoom(instance, 8ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    const vk::ImageCreateInfo image_ci{
        .imageType = vk::ImageType::e2D,
        .format = TagFormat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    };
    tag_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    tag_image.Create(image_ci);
    SetObjectName(device, vk::Image(tag_image), "Glass view tag");
    tag_view = Check<"create glass view tag view">(device.createImageViewUnique({
        .image = vk::Image(tag_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    before_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    before_image.Create(image_ci);
    SetObjectName(device, vk::Image(before_image), "Glass view prints before");
    before_view = Check<"create glass view prints view">(device.createImageViewUnique({
        .image = vk::Image(before_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    tag_width = width;
    tag_height = height;
    tag_fresh = true;
    clear_due = true;
    tag_dirty = false;
    return true;
}

vk::ImageView GlassView::CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.format == format &&
            entry.aspect == aspect) {
            entry.last_use = ++view_uses;
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
        .format = format,
        .aspect = aspect,
        .view = Check<"create glass view image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool GlassView::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
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

vk::ImageView GlassView::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

void GlassView::Snapshot(VideoCore::ImageId target0, VideoCore::ImageId depth, bool gbuffer, R::Kind kind,
                         bool lamps_pending) {
    if (failed) {
        return;
    }
    // Lamps apart (vk_point_shadow.h): an open batch must not see the scene depth read.
    if (lamps_pending) {
        ++stats.skip_lamps;
        return;
    }
    if (snapshots_this_frame >= MaxSnapshots) {
        ++stats.skip_cap;
        return;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.skip_preview;
        return;
    }
    // Only the scene camera's pass (a planar reflection's pass has another depth, often another size).
    if (!depth || depth != camera_motion.Depth()) {
        ++stats.skip_camera;
        return;
    }
    u32 width = 0, height = 0, width0 = 0, height0 = 0;
    bool reduced = false, reduced0 = false;
    if (!target0 || !SceneSize(depth, width, height, reduced) || !SceneSize(target0, width0, height0, reduced0)) {
        ++stats.skip_shape;
        return;
    }
    const auto& image = texture_cache.GetImage(target0);
    const bool format_fits = gbuffer ? FloatColour(image.info.pixel_format) : image.info.pixel_format == SceneFormat;
    if (!format_fits || image.info.num_samples != 1 || width0 != width || height0 != height || reduced0 != reduced) {
        ++stats.skip_shape;
        return;
    }
    if (!Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.skip_shape;
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    const vk::ImageView colour_view = ViewOf(target0, vk::ImageAspectFlagBits::eColor, false, false);
    const vk::ImageView depth_view = ViewOf(depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!colour_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.size = {float(width), float(height)};
    push.flags = clear_due ? u32(GLASS_VIEW_FLAG_CLEAR) : 0u;
    clear_due = false;
    const bool fresh = std::exchange(tag_fresh, false);
    EffectPass::Mark(ProfileRow, "glass view", true);
    scheduler.RecordCrumb(
        {.name = "glass view snapshot"},
        [push, fresh, width, height, colour_view, depth_view, tag_handle = vk::Image(tag_image),
         before_handle = vk::Image(before_image), tag = *tag_view, before = *before_view,
         pipeline = *snapshot_pass.pipeline, layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
                EffectPass::InitGeneral(cmd, before_handle, ColorLevel);
            }
            using enum vk::DescriptorType;
            const std::array infos{Info(colour_view), Info(depth_view), Info(before), Info(tag)};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
    ++snapshots_this_frame;
    ++stats.snapshots;
    pending = {.active = true, .gbuffer = gbuffer, .kind = kind, .target0 = target0, .depth = depth,
               .target0_uid = image.image_uid, .depth_uid = texture_cache.GetImage(depth).image_uid};
}

void GlassView::FlushMark() {
    if (pending.active) {
        Mark();
    }
}

void GlassView::Mark() {
    const Pending draw = std::exchange(pending, Pending{});
    if (!draw.active || failed || !tag_image) {
        return;
    }
    // the MARK runs at the next draw's hook: that draw's PrepareRenderState may have freed (or reused the slot of) the hit
    // draw's target 0 or depth; GetImage on a freed id is not safe, so both are looked up by id and uid first
    if (!texture_cache.TryGetImage(draw.target0, draw.target0_uid) || !texture_cache.TryGetImage(draw.depth, draw.depth_uid)) {
        ++stats.skip_shape;
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    // a G-buffer draw: target 0 is read (its print, as the SNAPSHOT's); a forward draw paints target 0 itself
    const vk::ImageView colour_view =
        draw.gbuffer ? ViewOf(draw.target0, vk::ImageAspectFlagBits::eColor, false, false)
                     : ViewOf(draw.target0, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(draw.depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!colour_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.size = {float(tag_width), float(tag_height)};
    push.kind = u32(draw.kind);
    const auto colour = R::ViewColour(draw.kind);
    push.colour = {colour[0], colour[1], colour[2], 1.0f};
    EffectPass::Mark(ProfileRow, "glass view", true);
    const auto& pass = draw.gbuffer ? mark_pass : paint_pass;
    scheduler.RecordCrumb(
        {.name = draw.gbuffer ? "glass view mark" : "glass view paint"},
        [push, gbuffer = draw.gbuffer, width = tag_width, height = tag_height, colour_view, depth_view, tag = *tag_view,
         before = *before_view, pipeline = *pass.pipeline, layout = *pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            if (gbuffer) {
                const std::array infos{Info(colour_view), Info(depth_view), Info(before), Info(tag)};
                const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                        ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3])};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            } else {
                const std::array infos{Info(depth_view), Info(before), Info(colour_view)};
                const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eStorageImage, &infos[1]),
                                        ImageWrite(2, eStorageImage, &infos[2])};
                cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            }
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
    if (draw.gbuffer) {
        tag_dirty = true;
        tag_depth = draw.depth;
        tag_depth_uid = draw.depth_uid;
        ++stats.marks;
    } else {
        ++stats.paints;
    }
}

void GlassView::Show(VideoCore::ImageId scene, bool lamps_pending) {
    FlushMark();
    if (!tag_dirty || failed || !scene || !tag_depth || !tag_image || lamps_pending ||
        !texture_cache.TryGetImage(tag_depth, tag_depth_uid)) { // the tags' depth freed since: the frame end clears them
        return;
    }
    const auto& image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) || width != tag_width ||
        height != tag_height) {
        if (!told_show) {
            told_show = true;
            BbReport::Printf("Glass view (r129a): show left out (first time): the lit scene is format %u, %ux%u, the tag "
                             "%ux%u (RGBA16F, 97, of the tag's size wanted)\n",
                             u32(image.info.pixel_format), width, height, tag_width, tag_height);
        }
        return;
    }
    const SceneUseScope scene_use{"glass view"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = ViewOf(scene, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(tag_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view || !depth_view) {
        return;
    }
    Push push{};
    push.size = {float(width), float(height)};
    tag_dirty = false; // SHOW clears every tag it reads
    ++stats.shows;
    EffectPass::Mark(ProfileRow, "glass view", true);
    scheduler.RecordCrumb(
        {.name = "glass view show"},
        [push, width, height, scene_view, depth_view, tag = *tag_view, pipeline = *show_pass.pipeline,
         layout = *show_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            const std::array infos{Info(tag), Info(depth_view), Info(scene_view)};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::ViewGroup - 1) / R::ViewGroup, (height + R::ViewGroup - 1) / R::ViewGroup, 1);
            EndBarrier(cmd);
        });
}

void GlassView::OnFrameEnd() {
    // a MARK still pending (the hit draw was the frame's last direct draw) is dropped, not recorded at the frame end
    pending = {};
    const bool now = ViewNow();
    if (now != on || now != told_on) {
        on = now;
        told_on = now;
        BbReport::Printf("Glass view (r129a): view %s at frame %llu\n", now ? "on" : "off",
                         static_cast<unsigned long long>(frame));
    }
    if (tag_dirty) { // tags no SHOW took (the scene did not fit): the next hit draw's SNAPSHOT clears them
        clear_due = true;
        tag_dirty = false;
    }
    snapshots_this_frame = 0;
    tag_depth = {};
    ++frame;
    if (++stats.frames < LineFrames) {
        return;
    }
    BbReport::Printf("Glass view (r129a): view %s: snapshots %u marks %u paints %u shows %u; skipped cap %u preview %u "
                     "lamps open %u camera %u shape %u%s\n",
                     on ? "on" : "off", stats.snapshots, stats.marks, stats.paints, stats.shows, stats.skip_cap,
                     stats.skip_preview, stats.skip_lamps, stats.skip_camera, stats.skip_shape,
                     failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
