// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_footprints.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <utility>

#include "bbport_toggles.h"
#include "engine/engine_state.h"
#include "video_core/host_shaders/footprints_comp.h"
#include "video_core/host_shaders/footprints_flat_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = FootprintRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto GbufferFormat = vk::Format::eR8G8B8A8Unorm;
/// G-buffer target 2 (albedo) as the game makes it (vk_ssgi.cpp reads it only in this format).
constexpr auto AlbedoSrgbFormat = vk::Format::eR8G8B8A8Srgb;
constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;
constexpr vk::DeviceSize PrintBytes = R::PrintFloats * 4;
constexpr vk::DeviceSize FlatBytes = R::FlatWords * 4; ///< (r111e) the draw over the picture's counters
constexpr u64 ProfileRow = 111; ///< EffectPass::Mark: the row "Lighting: footprints"
/// The hunter's box for the sense (and the test view's ring): across and up or down of him.
constexpr float SenseBoxAcrossM = float(FOOTPRINTS_SENSE_RADIUS_M) + 0.05f;
constexpr float SenseBoxUpM = float(FOOTPRINTS_SENSE_HEIGHT_M) + 0.05f;

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type,
                                  const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .pBufferInfo = info};
}

/// The counters' commands of a frame's first pass (Footprints::TakeCounterStep), then the barrier
/// that lets the pass add to them.
void CounterCommands(vk::CommandBuffer cmd, vk::Buffer counter_buffer, vk::Buffer host, bool clear,
                     bool copy_back, u32 slot) {
    if (!clear) {
        return;
    }
    if (copy_back) {
        cmd.copyBuffer(counter_buffer, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
    }
    cmd.fillBuffer(counter_buffer, slot * SlotBytes, SlotBytes, 0);
    EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                              Compute | vk::PipelineStageFlagBits2::eHost,
                              ReadWrite | vk::AccessFlagBits2::eHostRead);
}

/// What the pass's commands begin with: the game's writes before it (and the reads of the prints by
/// an earlier pass of the frame) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                              Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

bool Finite3(const float v[3]) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}
} // namespace

bool Footprints::Wanted() {
    return R::Load().on;
}

Footprints::Footprints(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_},
      start{std::chrono::steady_clock::now()} {
    const auto& k = R::Load();
    BbReport::Printf("Footprints (r111): on%s; a print each %.2f m of the hunter's path, %.2f m to "
                     "the left or right of it in turn, fading over %.0f s; coat %s%s\n",
                     k.show ? ", show (test colours, ring)" : "",
                     double(R::StrideM), double(R::GaitHalfM), double(R::LifeS),
                     k.coat_forced ? R::KindName(k.coat)
                                   : "from the ground (wet: water, puddles; blood: dark red)",
                     k.coat_forced ? " (BB_FOOTPRINTS_COAT, a test: never dries)"
                                   : (k.coat_bad ? " (BB_FOOTPRINTS_COAT names no kind: wet, mud or blood)"
                                                 : ""));
    BbReport::Printf("Footprints (r111c): print strength gain %.2f%s; sole %.2f x %.2f m; a blood print's red "
                     "is %.2f times the stone's (%.3f to %.3f), cover %.0f%%; a wet print darkens by up to %.0f%%\n",
                     double(k.gain),
                     k.gain_bad ? " (BB_FOOTPRINTS_GAIN is no number from 0 to 4: 1 used)"
                                : (k.gain != 1.0f ? " (BB_FOOTPRINTS_GAIN)" : ""),
                     double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                            FOOTPRINTS_SOLE_SCALE),
                     double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE),
                     double(FOOTPRINTS_BLOOD_RED_KEEP), double(FOOTPRINTS_BLOOD_RED_MIN),
                     double(FOOTPRINTS_BLOOD_RED_MAX), double(FOOTPRINTS_BLOOD_COVER) * 100.0,
                     double(FOOTPRINTS_WET_DARKEN) * 100.0);
    BbReport::Printf("Footprints (r111d): boot sole %.2f x %.2f m (heel, waist, ball); a blood coat leaves %u full "
                     "prints then keeps %.2f a step (%u prints), a wet coat %u then %.2f (%u prints); prints "
                     "fade over %.0f s; gain 0 draws none\n",
                     double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU - (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) *
                            FOOTPRINTS_SOLE_SCALE),
                     double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE), R::BloodFullPrints,
                     double(R::BloodKeep), R::CoatPrints(R::Kind::Blood), R::WetFullPrints,
                     double(R::DryPerStep), R::CoatPrints(R::Kind::Wet), double(R::LifeS));
    BbReport::Printf("Footprints (r111e): after the lighting, on the scene colour: post stamp %.2f "
                     "(BB_FOOTPRINTS_POST: blood prints recoloured dark red at the lit pixel's luminance, wet "
                     "and mud %.0f%% darker still; 0 off); test view %s (BB_FOOTPRINTS_SHOW=1: flat red "
                     "quads, no depth, no light)\n",
                     double(R::Post()), double(FOOTPRINTS_POST_WET_DARKEN) * 100.0,
                     R::ShowFlat() ? "on" : "off");
    { // (r111f) one copy of each new line with zeros, so the kinds come early in the log (the slot runner
      // keeps the first 30 feature lines by first appearance, the first and last of each kind)
        FlatSnap none{};
        none.count = 1;
        LogProbe(none, std::array<u32, R::FlatWords>{});
        LogFlat();
        LogStamp(0, 0, 0, std::array<float, 3>{}); // (r111g)
        LogTotals();                               // (r111h) a zero copy
        LogLuma();                                 // (r111i) a zero copy
        LogView(0, FlatSnap{}, 0u, 0.0, 0.0, 0u);  // (r111j) a zero copy
        LogSheen();                                // (r111j) a zero copy
        LogTrail();                                // (r111k) a zero copy
    }
    BbReport::Printf("Footprints (r111h): blood prints dark red at %.2f of the lit luminance, strongest first (%u full, "
                     "keep %.2f); wet darkens %.0f%% with edge %.2f; a pixel nearer than %.0f%% of its print's view z "
                     "is skipped; facing read over %d px\n",
                     double(FOOTPRINTS_POST_BLOOD_LUM), R::BloodFullPrints, double(R::BloodKeep),
                     double(FOOTPRINTS_POST_WET_DARKEN) * 100.0, double(FOOTPRINTS_POST_WET_EDGE),
                     double(FOOTPRINTS_POST_NEAR_FRAC) * 100.0, int(FOOTPRINTS_POST_NORMAL_PX));
    BbReport::Printf("Footprints (r111i): wet and mud weights rounded 1 - (1 - w)^2, wet edge from %.2f of the radius; a "
                     "pixel next to a surface more than %.2f m + %.0f%% of its depth nearer (%.1f%% of the picture "
                     "height away) is left out\n",
                     double(FOOTPRINTS_POST_WET_EDGE), double(FOOTPRINTS_POST_SILHOUETTE_M),
                     double(FOOTPRINTS_POST_SILHOUETTE_REL) * 100.0, double(FOOTPRINTS_POST_SILHOUETTE_FRAC) * 100.0);
    BbReport::Printf("Footprints (r111g): look: blood prints dark red at %.2f of the lit luminance (tint %.2f %.2f %.2f, "
                     "cover %.0f%%, weight 1 - (1 - w)^2); wet prints darken the stone %.0f%% (G-buffer) and %.0f%% "
                     "(post), no gloss or specular added\n",
                     double(FOOTPRINTS_POST_BLOOD_LUM), double(FOOTPRINTS_POST_BLOOD_TINT_R),
                     double(FOOTPRINTS_POST_BLOOD_TINT_G), double(FOOTPRINTS_POST_BLOOD_TINT_B),
                     double(FOOTPRINTS_POST_BLOOD_COVER) * 100.0, double(FOOTPRINTS_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_POST_WET_DARKEN) * 100.0);
    BbReport::Printf("Footprints (r111j): a view line when the verdict, the prints in the picture, the gain or the sheen "
                     "changes, or every %u passes, at most %u; verdict 0 no print in the picture, 1 in it but no pixel "
                     "stamped, 2 stamped where the lit luminance is under %.3f (near black), 3 on lit ground\n",
                     ViewEvery, ViewMax, double(FOOTPRINTS_VIEW_READABLE_LUM));
    BbReport::Printf("Footprints (r111j): sheen %.2f (BB_FOOTPRINTS_SHEEN, 0 to %.0f, default 0, blood prints only): a "
                     "blood print's luminance is lifted to at least %.4f times it (ceiling %.3f, knee %.2f of it)\n",
                     double(R::Sheen()), double(R::SheenMax), double(FOOTPRINTS_SHEEN_SKY),
                     double(FOOTPRINTS_SHEEN_PEAK), double(FOOTPRINTS_SHEEN_KNEE));
    BbReport::Printf("Footprints (r111k): trail %u (BB_FOOTPRINTS_TRAIL, 0 = r111j's rules): %u full prints, then a taper "
                     "to dry over %u (blood) or %u (wet); blood from %u%% of the pickup disc, held to %u%%, a puddle held "
                     "to %u%%; blood strength = share over %.2f; a print fades in over %.2f s\n",
                     R::Trail() ? 1u : 0u, R::TrailFull, R::TrailBloodPrints, R::TrailWetPrints, R::BloodEnterPercent,
                     R::BloodStayPercent, R::PuddleStayPercent, double(R::BloodFullShareTrail), double(R::FadeInS));
    BbReport::Printf("Footprints (r111k): look %u (BB_FOOTPRINTS_LOOK, 0 = r111j's): wet darkens %.0f%% (G-buffer) and "
                     "%.0f%% (post), was %.0f%% and %.0f%%; gloss to %.2f; cool grey floor %.3f; blood keeps its dark red, "
                     "sheen floor %.2f times %.3f\n",
                     R::Look() ? 1u : 0u, double(FOOTPRINTS_K_WET_DARKEN) * 100.0, double(FOOTPRINTS_K_POST_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_WET_DARKEN) * 100.0, double(FOOTPRINTS_POST_WET_DARKEN) * 100.0,
                     double(FOOTPRINTS_K_WET_GLOSS), double(FOOTPRINTS_K_WET_SHEEN), double(FOOTPRINTS_K_BLOOD_SHEEN),
                     double(FOOTPRINTS_SHEEN_SKY));
    if (!camera_motion.Enabled()) {
        Fail("it needs the upscaler's camera (BB_UPSCALER=none)");
    }
}

Footprints::~Footprints() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(prints_buffer);
    FreeBuffer(counters);
    FreeBuffer(readback);
    FreeBuffer(flat_prints);
    FreeBuffer(flat_counts);
    FreeBuffer(flat_host);
}

bool Footprints::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
                            vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags =
            VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void Footprints::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool Footprints::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, GbufferFormat) &&
        EffectPass::Create(instance, edit_set_layout, edit_layout, edit_pipeline,
                           {eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), FOOTPRINTS_COMP, "Footprints", true) &&
        MakeBuffer(prints_buffer, R::MaxPrints * PrintBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(counters, R::Slots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void Footprints::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Footprints (r111): off - %s\n", why);
}

vk::ImageView Footprints::CachedView(const VideoCore::Image& image, vk::Format format,
                                     vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
            entry.format == format && entry.aspect == aspect) {
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
        .view = Check<"create footprints view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool Footprints::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
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

vk::ImageView Footprints::ViewOf(VideoCore::ImageId id, vk::Format format,
                                 vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    // (Game images and their reduced proxies are made with eMutableFormat and eExtendedUsage
    // (texture_cache/image.cpp; a proxy copies the image's create info): an R8G8B8A8_SRGB target
    // can be viewed as R8G8B8A8_UNORM storage.)
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

Footprints::CounterStep Footprints::TakeCounterStep() {
    CounterStep step{};
    step.slot = u32(frame & 1);
    if (counter_frame != frame + 1) {
        counter_frame = frame + 1;
        step.clear = true;
        // the frame before used the other slot: its counts are complete in the queue before this
        step.copy_back = counter_used == frame && frame != 0;
    }
    counter_used = frame + 1;
    return step;
}

void Footprints::BeforeDraw(const GraphicsPipeline& draw_pipeline,
                            const std::array<VideoCore::ImageId, 8>& targets,
                            VideoCore::ImageId depth, bool light_draw, bool lamps_pending,
                            std::array<float, 2> jitter) {
    if (failed) {
        return;
    }
    const u32 mrt = u32(draw_pipeline.GetGraphicsKey().mrt_mask);
    // The G-buffer pass: its depth, gloss (target 1), albedo (target 2), specular colour (target 3).
    if (std::popcount(mrt) >= 5 && depth) {
        // Each G-buffer pass's lighting comes after it (a planar reflection's pass and the world's
        // each get their own pass).
        edit_tried = false;
        gbuffer_seen = true;
        gbuffer_depth = depth;
        gbuffer_material = (mrt & 2u) ? targets[1] : VideoCore::ImageId{};
        gbuffer_albedo = (mrt & 4u) ? targets[2] : VideoCore::ImageId{};
        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        return;
    }
    if (!light_draw || !gbuffer_seen || edit_tried) {
        return;
    }
    edit_tried = true;
    // The water plane of this frame's passes so far (the world's pass comes after its mirror image).
    if (float y = 0.0f; camera_motion.MirrorPlane(y)) {
        plane_seen = true;
        plane_y = y;
    }
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    // Lamps apart (vk_point_shadow.h): the open batch's lamps read the G-buffer later; prints laid
    // now would be lit by half of the lamps.
    if (lamps_pending) {
        ++stats.lamps_open;
        return;
    }
    Edit(jitter);
}

void Footprints::Edit(std::array<float, 2> jitter) {
    if (placed_count == 0 && !hunter_known) {
        ++stats.off_screen;
        return; // nothing to lay and no one to sense
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid || camera.proj[0] == 0.0f || camera.proj[1] == 0.0f) {
        ++stats.no_camera;
        return;
    }
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth() || !gbuffer_material ||
        !gbuffer_albedo || !gbuffer_specular) {
        ++stats.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(gbuffer_depth, width, height, reduced)) {
        ++stats.cannot;
        return;
    }
    // Targets 1, 2 and 3 must be RGBA8 (the shader's rgba8 images: 1 and 3 UNORM, 2 UNORM or SRGB,
    // the game's) and stand where the depth does.
    const bool albedo_srgb = texture_cache.GetImage(gbuffer_albedo).info.pixel_format == AlbedoSrgbFormat;
    for (const auto id : {gbuffer_material, gbuffer_albedo, gbuffer_specular}) {
        const auto& image = texture_cache.GetImage(id);
        const bool fits = (image.info.pixel_format == GbufferFormat ||
                           (id == gbuffer_albedo && albedo_srgb)) &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == reduced &&
                          image.info.size.width >= (reduced ? 1u : width) &&
                          image.info.size.height >= (reduced ? 1u : height);
        if (!fits) {
            ++stats.cannot;
            if (!told_unfit) {
                told_unfit = true;
                BbReport::Printf("Footprints (r111): left out (first time): G-buffer target 1 format "
                                 "%u, target 2 format %u, target 3 format %u, %ux%u (the pass writes "
                                 "R8G8B8A8_UNORM, 37, target 2 also _SRGB, 43, on a %ux%u scene)\n",
                                 u32(texture_cache.GetImage(gbuffer_material).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_albedo).info.pixel_format),
                                 u32(texture_cache.GetImage(gbuffer_specular).info.pixel_format),
                                 image.info.size.width, image.info.size.height, width, height);
            }
            return;
        }
    }
    // The prints on this pass's screen (their boxes), and the hunter's box for the sense.
    const float fw = float(width), fh = float(height);
    const float cam_x = camera.inv_view[3], cam_y = camera.inv_view[7], cam_z = camera.inv_view[11];
    std::array<float, R::MaxPrints * R::PrintFloats> packed{};
    u32 count = 0;
    R::Rect rect{};
    float near_print = 0.0f, far_print = 0.0f; // (r111c) camera to the prints sent
    int box_w = 0, box_h = 0;                  // (r111c) the largest print box, px
    for (u32 i = 0; i < placed_count; ++i) {
        const Placed& p = placed[i];
        const float dx = p.x - cam_x, dy = p.y - cam_y, dz = p.z - cam_z;
        if (p.now <= 0.0f || dx * dx + dy * dy + dz * dz > R::MaxDistanceM * R::MaxDistanceM) {
            continue;
        }
        const float lo[3] = {p.x - R::PrintBoxAcrossM, p.y - R::PrintBoxUpM, p.z - R::PrintBoxAcrossM};
        const float hi[3] = {p.x + R::PrintBoxAcrossM, p.y + R::PrintBoxUpM, p.z + R::PrintBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        if (r.Empty()) {
            continue;
        }
        rect = R::Union(rect, r);
        { // (r111c) how far and how big the prints on this pass's screen are
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            near_print = count != 0 ? std::min(near_print, d) : d;
            far_print = count != 0 ? std::max(far_print, d) : d;
            box_w = std::max(box_w, int(r.x1 - r.x0));
            box_h = std::max(box_h, int(r.y1 - r.y0));
        }
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
                packed.data() + std::size_t(count) * R::PrintFloats);
        ++count;
    }
    if (count != 0) {
        ++stats.print_passes;
        stats.sent_prints += count;
        stats.print_near_m = stats.print_passes > 1 ? std::min(stats.print_near_m, near_print) : near_print;
        stats.print_far_m = stats.print_passes > 1 ? std::max(stats.print_far_m, far_print) : far_print;
        stats.box_w = std::max(stats.box_w, box_w);
        stats.box_h = std::max(stats.box_h, box_h);
        if (!told_onscreen) {
            told_onscreen = true;
            BbReport::Printf("Footprints (r111c): first prints on a pass's screen at frame %llu: %u of %u "
                             "placed, %.2f to %.2f m from the camera, the largest print box %d x %d px (a "
                             "print is %.2f x %.2f m)\n",
                             static_cast<unsigned long long>(frame), count, placed_count,
                             double(near_print), double(far_print), box_w, box_h,
                             double((FOOTPRINTS_FORE_U + FOOTPRINTS_FORE_RU -
                                     (FOOTPRINTS_HEEL_U - FOOTPRINTS_HEEL_RU)) * FOOTPRINTS_SOLE_SCALE),
                             double(2.0 * FOOTPRINTS_FORE_RV * FOOTPRINTS_SOLE_SCALE));
        }
    }
    bool sensing = false;
    if (hunter_known) {
        const float lo[3] = {hunter[0] - SenseBoxAcrossM, hunter[1] - SenseBoxUpM, hunter[2] - SenseBoxAcrossM};
        const float hi[3] = {hunter[0] + SenseBoxAcrossM, hunter[1] + SenseBoxUpM, hunter[2] + SenseBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        sensing = !r.Empty();
        rect = R::Union(rect, r);
    }
    if (rect.Empty()) {
        ++stats.off_screen;
        return;
    }
    if (!Ready()) {
        return;
    }
    const SceneUseScope scene_use{"footprints"};
    scheduler.EndRendering();
    constexpr auto Color = vk::ImageAspectFlagBits::eColor;
    const vk::ImageView depth_view =
        ViewOf(gbuffer_depth, texture_cache.GetImage(gbuffer_depth).info.pixel_format,
               vk::ImageAspectFlagBits::eDepth, false, false);
    const vk::ImageView material_view = ViewOf(gbuffer_material, GbufferFormat, Color, true, true);
    // (an SRGB albedo through a UNORM view: the shader decodes and encodes, FOOTPRINTS_FLAG_SRGB)
    const vk::ImageView albedo_view = ViewOf(gbuffer_albedo, GbufferFormat, Color, true, true);
    const vk::ImageView specular_view = ViewOf(gbuffer_specular, GbufferFormat, Color, true, true);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!depth_view || !material_view || !albedo_view || !specular_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.inv_view = camera.inv_view;
    push.proj = camera.proj;
    push.size = {fw, fh};
    push.jitter = jitter;
    push.hunter = {hunter[0], hunter[1], hunter[2], R::Look() ? 1.0f : 0.0f}; // (r111k) .w: the look
    push.count = count;
    push.flags = R::Flags(k, sensing, step.slot, albedo_srgb);
    push.stamp = u32(frame + 1);
    push.gain = R::Gain();
    if (push.gain != told_gain) { // (r111d) the first pass, and each change of the live gain
        told_gain = push.gain;
        BbReport::Printf("Footprints (r111d): print strength gain now %.2f%s\n", double(push.gain),
                         push.gain == 0.0f ? " (no print is drawn)" : "");
    }
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
    const u32 gx1 = (u32(rect.x1) + R::Group - 1) / R::Group;
    const u32 gy1 = (u32(rect.y1) + R::Group - 1) / R::Group;
    ++stats.passes;
    stats.pass_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
    EffectPass::Mark(ProfileRow, "footprints", true);
    scheduler.RecordCrumb(
        {.name = "footprints"},
        [push, step, packed, count, gx0, gy0, gx1, gy1, depth_view, material_view, albedo_view,
         specular_view, prints = prints_buffer.buffer, counter_buffer = counters.buffer,
         host = readback.buffer, pass_pipeline = *edit_pipeline,
         pass_layout = *edit_layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            if (count != 0) {
                cmd.updateBuffer(prints, 0, vk::DeviceSize(count) * PrintBytes, packed.data());
                EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                          Compute, ShaderRead);
            }
            using enum vk::DescriptorType;
            const std::array infos{Info(depth_view), Info(material_view), Info(albedo_view),
                                   Info(specular_view)};
            const vk::DescriptorBufferInfo prints_info{prints, 0, R::MaxPrints * PrintBytes};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]),
                                    ImageWrite(1, eStorageImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]),
                                    ImageWrite(3, eStorageImage, &infos[3]),
                                    BufferWrite(4, &prints_info), BufferWrite(5, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmd.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            EndBarrier(cmd);
        });
}

bool Footprints::FlatReady() {
    if (flat_tried) {
        return !flat_failed;
    }
    flat_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
        EffectPass::Create(instance, flat_set_layout, flat_layout, flat_pipeline,
                           {eStorageImage, eSampledImage, eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), FOOTPRINTS_FLAT_COMP, "Footprints flat", true) &&
        MakeBuffer(flat_prints, R::MaxPrints * PrintBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(flat_counts, FlatBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(flat_host, FlatBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        flat_failed = true;
        BbReport::Printf("Footprints (r111e): the draw over the picture is off - this GPU cannot run its pass\n");
        return false;
    }
    std::memset(flat_host.mapped, 0, FlatBytes);
    return true;
}

/// (r111f) The probes are told from this pass of a mode on and every FlatProbeEvery passes after it, at most
/// FlatProbeMax times.
constexpr u32 FlatProbeFirst = 6, FlatProbeEvery = 120, FlatProbeMax = 20;

void Footprints::LogFlat() const {
    BbReport::Printf("Footprints (r111f): over the picture: %u frames, %u passes (view %u), %u read back, %u all "
                     "run, %u prints, %.0f px a pass; last %u red px (max %u), %u stamped (max %u); skipped "
                     "%u off, %u no camera, %u cannot; post %.2f\n",
                     flat.frames, flat.passes, R::ShowFlat() ? 1u : 0u, flat.read_back, flat.groups_ok,
                     flat.sent, flat.passes ? double(flat.rect_px) / double(flat.passes) : 0.0, flat.red_last,
                     flat.red_max, flat.post_last, flat.post_max, flat.off_screen, flat.no_camera, flat.cannot,
                     double(R::Post()));
}

void Footprints::LogProbe(const FlatSnap& snap, const std::array<u32, R::FlatWords>& counts) const {
    BbReport::Printf("Footprints (r111f): pass %u of view %u (1 flat red, 0 stamp): camera %.1f %.1f %.1f, %u "
                     "prints, rect %d x %d, groups run %u of %u, red px %u, stamped px %u\n",
                     snap.mode_pass, snap.show, double(snap.camera[0]), double(snap.camera[1]),
                     double(snap.camera[2]), snap.count, int(snap.rect_w), int(snap.rect_h),
                     counts[R::WordFlatGroups], snap.groups, counts[R::WordFlatRedPx],
                     counts[R::WordFlatPostPx]);
    const u32 n = std::min(snap.count, R::FlatProbes);
    for (u32 i = 0; i < n; ++i) { // oldest first: the line the runner keeps last is the last print's
        const u32* w = counts.data() + R::WordFlatProbe + std::size_t(i) * R::FlatProbeWords;
        float depth = 0.0f, view_z = 0.0f;
        std::memcpy(&depth, &w[2], sizeof(depth));
        std::memcpy(&view_z, &w[3], sizeof(view_z));
        const auto& pt = snap.points[i];
        BbReport::Printf("Footprints (r111f): print %u of %u at %.1f %.1f %.1f: pixel %.0f %.0f state %d (1 in, "
                         "0 out, 2 behind; GPU %d %d), view z %.2f, scene z %.2f, depth %.4f\n",
                         i, n, double(pt.x), double(pt.y), double(pt.z), double(pt.screen.x),
                         double(pt.screen.y), int(pt.screen.state), w[0] != 0u ? int(w[0]) - 1 : -1,
                         w[0] != 0u ? int(w[1]) : -1, double(pt.screen.z), double(view_z), double(depth));
    }
}

/// (r111g) Told once, when the first post stamp's pixels are read back (a zero copy at construction).
void Footprints::LogStamp(u64 at_frame, u32 px, u32 prints, const std::array<float, 3>& cam) const {
    BbReport::Printf("Footprints (r111g): first post stamp read back at frame %llu: %u stamped px, %u prints on "
                     "the pass, camera %.1f %.1f %.1f\n",
                     static_cast<unsigned long long>(at_frame), px, prints, double(cam[0]), double(cam[1]),
                     double(cam[2]));
}

/// (r111h) Totals, numbers first: at construction (zeros), at frame 240 and every LineFrames frames, so a place
/// where nothing is placed says 0 prints, 0 passes, 0 px explicitly.
void Footprints::LogTotals() const {
    BbReport::Printf("Footprints (r111h): totals at frame %u: %u prints placed (%u blood, %u wet, %u mud), %u live, %u "
                     "post passes, %llu px stamped in %u read-backs (most %u), %u G-buffer passes\n",
                     stats.frames, stats.by_kind[0] + stats.by_kind[1] + stats.by_kind[2], stats.by_kind[2],
                     stats.by_kind[0], stats.by_kind[1], placed_count, flat.passes,
                     static_cast<unsigned long long>(stats.stamp_px_sum), flat.read_back, flat.post_max,
                     stats.passes);
}

/// (r111i) What the post stamp did to the pixels it wrote: the mean lit luminance before and after, by kind
/// (summed over the read-backs; fixed point, FOOTPRINTS_FLAT_LUM_SCALE). A place where nothing is stamped says 0 px.
void Footprints::LogLuma() const {
    const auto mean = [](u64 sum, u64 px) {
        return px != 0u ? double(sum) / (double(px) * FOOTPRINTS_FLAT_LUM_SCALE) : 0.0;
    };
    const auto ratio = [](u64 before, u64 after) {
        return before != 0u ? double(after) / double(before) : 0.0;
    };
    BbReport::Printf("Footprints (r111i): lit luminance under the post stamp: wet or mud %llu px, mean %.4f before, "
                     "%.4f after (x%.2f); blood %llu px, mean %.4f before, %.4f after (x%.2f)\n",
                     static_cast<unsigned long long>(stats.lum_px[0]), mean(stats.lum_before[0], stats.lum_px[0]),
                     mean(stats.lum_after[0], stats.lum_px[0]), ratio(stats.lum_before[0], stats.lum_after[0]),
                     static_cast<unsigned long long>(stats.lum_px[1]), mean(stats.lum_before[1], stats.lum_px[1]),
                     mean(stats.lum_after[1], stats.lum_px[1]), ratio(stats.lum_before[1], stats.lum_after[1]));
}

/// (r111j) One line about a view: the prints in the picture, the pixels the stamp wrote there and their lit luminance
/// before and after, the gain and the sheen, and the verdict (see the once-line): so a picture without prints is told
/// from a stamp that wrote nothing and from prints on near-black ground. Told by ViewRead.
void Footprints::LogView(u64 at_frame, const FlatSnap& snap, u32 px, double lum_before, double lum_after,
                         u32 verdict) const {
    BbReport::Printf("Footprints (r111j): view at frame %llu, camera %.1f %.1f %.1f: %u prints sent, %u in the picture, "
                     "%u behind the camera, %u px stamped, lit luminance %.4f before %.4f after, gain %.2f sheen %.2f, "
                     "verdict %u\n",
                     static_cast<unsigned long long>(at_frame), double(snap.camera[0]), double(snap.camera[1]),
                     double(snap.camera[2]), snap.count, snap.in_frame, snap.behind, px, lum_before, lum_after,
                     double(snap.gain), double(snap.sheen), verdict);
}

/// (r111j) The sheen's counter: blood pixels it lifted, over the read-backs.
void Footprints::LogSheen() const {
    BbReport::Printf("Footprints (r111j): sheen %.2f: %llu blood pixels lifted in %u read-backs; view lines told %u of %u\n",
                     double(R::Sheen()), static_cast<unsigned long long>(stats.sheen_px), flat.read_back,
                     view_told.lines, ViewMax);
}

/// (r111k) Numbers first: the prints placed by the trail rules, how many of them in the taper (under TailStrength of a coat),
/// the frames a pickup was held by the lower stay share, and where the coat stands in its trail. Told at construction (zeros),
/// and with the periodic lines.
void Footprints::LogTrail() const {
    BbReport::Printf("Footprints (r111k): trail %u look %u: %u prints placed by the trail rules, %u of them in the taper "
                     "(under %.2f of a coat), %u frames a pickup was held by the lower stay share; the coat is %u prints "
                     "into a trail of %u\n",
                     R::Trail() ? 1u : 0u, R::Look() ? 1u : 0u, stats.trail_prints, stats.tail_prints,
                     double(R::TailStrength), stats.trail_holds, coat.step_n, R::TrailPrints(coat.kind));
}

/// (r111j) A stamp pass's read-back as a view: told when it differs from the last line told, and every ViewEvery passes.
void Footprints::ViewRead(const FlatSnap& snap, const std::array<u32, R::FlatWords>& counts) {
    u64 px = 0, before = 0, after = 0; // wet or mud, and blood, together
    for (u32 k = 0; k < 2; ++k) {
        const u32* lw = counts.data() + R::WordFlatLum + k * 3u;
        px += lw[0];
        before += lw[1];
        after += lw[2];
    }
    const double scale = px != 0u ? double(px) * FOOTPRINTS_FLAT_LUM_SCALE : 1.0;
    const double lum_before = double(before) / scale, lum_after = double(after) / scale;
    const u32 px32 = u32(std::min<u64>(px, 0xFFFFFFFFull));
    const u32 verdict = R::ViewVerdict(snap.in_frame, px32, lum_before);
    ViewTold& t = view_told;
    ++t.since;
    const bool changed = verdict != t.verdict || snap.in_frame != t.in_frame || snap.gain != t.gain ||
                         snap.sheen != t.sheen;
    if (t.lines >= ViewMax || !(changed || t.since >= ViewEvery)) {
        return;
    }
    ++t.lines;
    t.since = 0;
    t.verdict = verdict;
    t.in_frame = snap.in_frame;
    t.gain = snap.gain;
    t.sheen = snap.sheen;
    LogView(frame, snap, px32, lum_before, lum_after, verdict);
}

void Footprints::FlatProbeRead(const std::array<u32, R::FlatWords>& counts) {
    const u32 stamp = counts[R::WordFlatStamp];
    if (stamp == 0u || stamp == flat_probe.last_stamp) {
        return;
    }
    const FlatSnap& snap = flat_snaps[stamp % flat_snaps.size()];
    if (snap.stamp != stamp) {
        return; // the snapshot was taken over by a later pass
    }
    flat_probe.last_stamp = stamp;
    ++flat.read_back;
    flat.groups_ok += counts[R::WordFlatGroups] == snap.groups ? 1u : 0u;
    { // (r111g) the post stamp's pixels are print pixels too (the r111c counter had the G-buffer band only)
        const u32 px = counts[R::WordFlatPostPx];
        stats.print_px_frames += px != 0u ? 1u : 0u;
        stats.print_px_max = std::max(stats.print_px_max, px);
        stats.stamp_px_sum += px; // (r111h)
        for (u32 k = 0; k < 2; ++k) { // (r111i) wet or mud, then blood: pixels, luminance before, after
            const u32* lw = counts.data() + R::WordFlatLum + k * 3u;
            stats.lum_px[k] += lw[0];
            stats.lum_before[k] += lw[1];
            stats.lum_after[k] += lw[2];
        }
        stats.sheen_px += counts[R::WordFlatSheen]; // (r111j)
        if (!snap.show) {
            ViewRead(snap, counts); // (r111j) one line per view
        }
        if (px != 0u && !flat_probe.told_stamp) {
            flat_probe.told_stamp = true;
            LogStamp(frame, px, snap.count, snap.camera);
        }
    }
    if (snap.episode != flat_probe.episode || snap.mode_pass < flat_probe.next_pass ||
        flat_probe.told >= FlatProbeMax) {
        return;
    }
    flat_probe.next_pass = snap.mode_pass + FlatProbeEvery;
    ++flat_probe.told;
    LogProbe(snap, counts);
}

void Footprints::DrawOver(VideoCore::ImageId color_id, std::array<float, 2> jitter) {
    if (failed || flat_failed) {
        return;
    }
    const bool show = R::ShowFlat();
    const float strength = R::Gain() * R::Post();
    if (!show && !(strength > 0.0f)) {
        return;
    }
    ++flat.frames;
    if (flat_host.mapped) { // the last pass's counts (a frame or two old; the host copy needs no fence)
        std::array<u32, R::FlatWords> c{};
        std::memcpy(c.data(), flat_host.mapped, sizeof(c));
        flat.red_last = c[R::WordFlatRedPx];
        flat.post_last = c[R::WordFlatPostPx];
        flat.red_max = std::max(flat.red_max, flat.red_last);
        flat.post_max = std::max(flat.post_max, flat.post_last);
        FlatProbeRead(c); // (r111f)
    }
    if (placed_count == 0 || !color_id) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid || camera.proj[0] == 0.0f || camera.proj[1] == 0.0f) {
        ++flat.no_camera;
        return;
    }
    const VideoCore::ImageId depth_id = camera_motion.Depth();
    if (!depth_id || texture_cache.GetImage(color_id).info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++flat.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!SceneSize(color_id, width, height, reduced)) {
        ++flat.cannot;
        return;
    }
    { // the depth must stand where the colour does (reduced alike, and covering the scene), as Edit asks
        const auto& depth_image = texture_cache.GetImage(depth_id);
        if ((scene_targets.Reduced() && scene_targets.EligibleScene(depth_image)) != reduced ||
            (!reduced && (depth_image.info.size.width < width || depth_image.info.size.height < height))) {
            ++flat.cannot;
            return;
        }
    }
    // The prints on screen (their boxes) as Edit takes them.
    const float fw = float(width), fh = float(height);
    const float cam_x = camera.inv_view[3], cam_y = camera.inv_view[7], cam_z = camera.inv_view[11];
    std::array<float, R::MaxPrints * R::PrintFloats> packed{};
    u32 count = 0;
    R::Rect rect{};
    for (u32 i = 0; i < placed_count; ++i) {
        const Placed& p = placed[i];
        const float dx = p.x - cam_x, dy = p.y - cam_y, dz = p.z - cam_z;
        if (p.now <= 0.0f || dx * dx + dy * dy + dz * dz > R::MaxDistanceM * R::MaxDistanceM) {
            continue;
        }
        const float lo[3] = {p.x - R::PrintBoxAcrossM, p.y - R::PrintBoxUpM, p.z - R::PrintBoxAcrossM};
        const float hi[3] = {p.x + R::PrintBoxAcrossM, p.y + R::PrintBoxUpM, p.z + R::PrintBoxAcrossM};
        const R::Rect r = R::Project(camera.view, camera.proj, fw, fh, jitter, lo, hi);
        if (r.Empty() && !show) { // (r111f) the test view sends every print, on the screen or not
            continue;
        }
        rect = R::Union(rect, r);
        R::Pack(p.x, p.y, p.z, p.now, p.dir_x, p.dir_z, p.side, p.kind,
                packed.data() + std::size_t(count) * R::PrintFloats);
        ++count;
    }
    if (show && count != 0) { // (r111f) the test view covers the whole picture (markers, corner beacon)
        rect = R::Rect{0, 0, std::int32_t(width), std::int32_t(height)};
    }
    if (count == 0 || rect.Empty()) {
        ++flat.off_screen;
        return;
    }
    if (!FlatReady()) {
        return;
    }
    const SceneUseScope scene_use{"footprints"};
    scheduler.EndRendering();
    const vk::ImageView color_view =
        ViewOf(color_id, vk::Format::eR16G16B16A16Sfloat, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view =
        ViewOf(depth_id, texture_cache.GetImage(depth_id).info.pixel_format,
               vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!color_view || !depth_view) {
        ++flat.cannot;
        return;
    }
    R::Push push{};
    push.inv_view = camera.inv_view;
    push.proj = camera.proj;
    push.size = {fw, fh};
    push.jitter = jitter;
    push.count = count;
    push.flags = show ? R::FlagShow : 0u;
    push.stamp = u32(frame + 1);
    push.gain = strength;
    push.hunter = {R::Sheen(), R::Look() ? 1.0f : 0.0f, 0.0f, 0.0f}; // (r111j) .x: BB_FOOTPRINTS_SHEEN; (r111k) .y: the look
    const u32 gx0 = u32(rect.x0) / R::Group, gy0 = u32(rect.y0) / R::Group;
    const u32 gx1 = (u32(rect.x1) + R::Group - 1) / R::Group;
    const u32 gy1 = (u32(rect.y1) + R::Group - 1) / R::Group;
    ++flat.passes;
    flat.sent += count;
    flat.rect_px += u64(rect.x1 - rect.x0) * u64(rect.y1 - rect.y0);
    { // (r111f) the snapshot of this pass for the probe: the CPU's numbers, matched to the GPU's by the stamp
        if (flat_probe.episode == 0 || flat_probe.show != show) {
            flat_probe.show = show;
            flat_probe.mode_passes = 0;
            flat_probe.next_pass = FlatProbeFirst;
            ++flat_probe.episode;
        }
        ++flat_probe.mode_passes;
        FlatSnap& snap = flat_snaps[push.stamp % flat_snaps.size()];
        snap = {};
        snap.stamp = push.stamp;
        snap.show = show ? 1u : 0u;
        snap.count = count;
        snap.groups = (gx1 - gx0) * (gy1 - gy0);
        snap.mode_pass = flat_probe.mode_passes;
        snap.episode = flat_probe.episode;
        snap.rect_w = rect.x1 - rect.x0;
        snap.rect_h = rect.y1 - rect.y0;
        snap.camera = {cam_x, cam_y, cam_z};
        for (u32 i = 0; i < count; ++i) { // (r111j) where every print sent lands (the view line's count)
            const float* q = packed.data() + std::size_t(i) * R::PrintFloats;
            const R::ScreenPoint where = R::ProjectPoint(camera.view, camera.proj, fw, fh, jitter, q[0], q[1], q[2]);
            snap.in_frame += where.state == 1 ? 1u : 0u;
            snap.behind += where.state == 2 ? 1u : 0u;
        }
        snap.gain = push.gain;
        snap.sheen = push.hunter[0];
        for (u32 i = 0; i < std::min(count, R::FlatProbes); ++i) {
            const float* q = packed.data() + std::size_t(i) * R::PrintFloats;
            snap.points[i].x = q[0];
            snap.points[i].y = q[1];
            snap.points[i].z = q[2];
            snap.points[i].screen = R::ProjectPoint(camera.view, camera.proj, fw, fh, jitter, q[0], q[1], q[2]);
        }
    }
    if (!told_flat) {
        told_flat = true;
        BbReport::Printf("Footprints (r111e): first pass over the picture at frame %llu: %s, %u prints, "
                         "rectangle %d x %d px of a %ux%u scene%s\n",
                         static_cast<unsigned long long>(frame),
                         show ? "flat red test view" : "post stamp", count, int(rect.x1 - rect.x0),
                         int(rect.y1 - rect.y0), width, height, reduced ? " (reduced)" : "");
    }
    EffectPass::Mark(ProfileRow, "footprints", true);
    scheduler.RecordCrumb(
        {.name = "footprints over"},
        [push, packed, count, gx0, gy0, gx1, gy1, color_view, depth_view,
         prints = flat_prints.buffer, counts = flat_counts.buffer, host = flat_host.buffer,
         pass_pipeline = *flat_pipeline, pass_layout = *flat_layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            cmd.fillBuffer(counts, 0, FlatBytes, 0);
            cmd.updateBuffer(prints, 0, vk::DeviceSize(count) * PrintBytes, packed.data());
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute,
                                      ReadWrite);
            using enum vk::DescriptorType;
            const std::array infos{Info(color_view), Info(depth_view)};
            const vk::DescriptorBufferInfo prints_info{prints, 0, R::MaxPrints * PrintBytes};
            const vk::DescriptorBufferInfo counts_info{counts, 0, FlatBytes};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]),
                                    ImageWrite(1, eSampledImage, &infos[1]),
                                    BufferWrite(2, &prints_info), BufferWrite(3, &counts_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmd.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatchBase(gx0, gy0, 0, gx1 - gx0, gy1 - gy0, 1);
            EndBarrier(cmd);
            cmd.copyBuffer(counts, host, vk::BufferCopy{0, 0, FlatBytes});
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

void Footprints::Place(const R::Step& s, R::Kind kind, float strength, double now) {
    if (placed_count == placed.size()) {
        // full: the oldest goes
        std::move(placed.begin() + 1, placed.end(), placed.begin());
        --placed_count;
    }
    placed[placed_count++] = {.x = s.x,
                              .y = s.y,
                              .z = s.z,
                              .dir_x = s.dir_x,
                              .dir_z = s.dir_z,
                              .side = s.side,
                              .kind = kind,
                              .strength = strength,
                              .now = strength,
                              .born = now};
    ++stats.by_kind[std::min<u32>(u32(kind), 2u)];
    if (!told_print) {
        told_print = true;
        BbReport::Printf("Footprints (r111): first print at frame %llu: %s, strength %.2f, at %.2f %.2f "
                         "%.2f, heading %.2f %.2f, %s foot\n",
                         static_cast<unsigned long long>(frame), R::KindName(kind), double(strength),
                         double(s.x), double(s.y), double(s.z), double(s.dir_x), double(s.dir_z),
                         s.side > 0.0f ? "one" : "the other");
    }
}

void Footprints::OnFrameEnd() {
    gbuffer_seen = edit_tried = false;
    gbuffer_depth = gbuffer_material = gbuffer_albedo = gbuffer_specular = {};
    const bool plane = std::exchange(plane_seen, false);
    ++frame;
    if (failed) {
        return;
    }
    R::Knobs k = R::Load();
    k.trail = R::Trail(); // (r111k) the trail rules, live with the test tools' knobs
    const double now =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    ++stats.frames;
    stats.planes += plane ? 1 : 0;
    if (stats.frames == 240 || stats.frames % LineFrames == 0) {
        LogTotals(); // (r111h)
        LogLuma();   // (r111i)
        LogSheen();  // (r111j)
    }
    // The sense of a recent frame (the host copy; no fence is waited for: it may be a few frames old,
    // its stamp says how old).
    std::array<u32, R::SlotWords> c{};
    if (readback.mapped) {
        std::memcpy(c.data(), readback.mapped, sizeof(c));
    }
    const bool fresh = c[R::WordStamp] != 0 && u64(c[R::WordStamp]) + R::SenseFreshFrames >= frame;
    if (fresh) {
        sense = c;
        sense_fresh = true;
        ++stats.sense_fresh;
        ++stats.readbacks; // (r111c) the pass's own count of print pixels in this read-back
        stats.print_px_frames += c[R::WordPrintPx] != 0u ? 1u : 0u;
        stats.print_px_max = std::max(stats.print_px_max, c[R::WordPrintPx]);
    }
    const bool glossy = fresh && R::GlossyGround(c[R::WordGroundN], c[R::WordWetN]);
    const bool glossy_stay = fresh && R::GlossyGroundStay(c[R::WordGroundN], c[R::WordWetN]); // (r111k)
    // (r111b) the pickup disc under his feet: its up-facing ground pixels, and the blood ones.
    const u32 pick_px = fresh ? c[R::WordPickN] : 0u, blood_px = fresh ? c[R::WordBloodN] : 0u;
    // The hunter.
    float pos[3] = {};
    hunter_known = BbEngine::world_player_position(pos) && Finite3(pos);
    if (!hunter_known) {
        ++stats.unread;
        if (!told_unread && stats.unread == 120) {
            told_unread = true;
            BbReport::Printf("Footprints (r111): the hunter's position cannot be read (the engine "
                             "features are off, or not in a level yet): no prints\n");
        }
    } else {
        ++stats.read;
        hunter = {pos[0], pos[1], pos[2]};
        const auto cam = camera_motion.CameraMatrices();
        if (cam.valid) {
            const float dx = cam.inv_view[3] - pos[0], dy = cam.inv_view[7] - pos[1];
            const float dz = cam.inv_view[11] - pos[2];
            const float d = std::sqrt(dx * dx + dy * dy + dz * dz);
            stats.near_m = stats.camera_n ? std::min(stats.near_m, d) : d;
            stats.far_m = stats.camera_n ? std::max(stats.far_m, d) : d;
            stats.low_m = stats.camera_n ? std::min(stats.low_m, dy) : dy;
            stats.high_m = stats.camera_n ? std::max(stats.high_m, dy) : dy;
            ++stats.camera_n;
            if (!told_position) {
                told_position = true;
                BbReport::Printf("Footprints (r111): first hunter position %.2f %.2f %.2f, camera at %.2f "
                                 "%.2f %.2f: %.2f m away, %.2f m above his position (the same space "
                                 "when about 1.5 to 6 m away and 0.5 to 3 m above)\n",
                                 double(pos[0]), double(pos[1]), double(pos[2]), double(cam.inv_view[3]),
                                 double(cam.inv_view[7]), double(cam.inv_view[11]), double(d), double(dy));
            }
        }
        if (cam.valid && told_position && !told_camera) {
            // (r111c) the first line's camera may still hold its start values (0 4 -8 at the load)
            const float cx = cam.inv_view[3] - pos[0], cy = cam.inv_view[7] - pos[1];
            const float cz = cam.inv_view[11] - pos[2];
            const float cd = std::sqrt(cx * cx + cy * cy + cz * cz);
            if (cd <= 12.0f) {
                told_camera = true;
                BbReport::Printf("Footprints (r111c): hunter at %.2f %.2f %.2f, the camera %.2f m away and "
                                 "%.2f m above his position, the first time it is within 12 m: %s\n",
                                 double(pos[0]), double(pos[1]), double(pos[2]), double(cd), double(cy),
                                 (cd >= 1.5f && cd <= 6.0f && cy >= 0.5f && cy <= 3.0f)
                                     ? "the game's position and the picture agree"
                                     : "outside the 1.5 to 6 m, 0.5 to 3 m above window: look at the ring");
            }
        }
        const bool in_water = R::InWater(plane, plane_y, pos[1]);
        stats.in_water += in_water ? 1 : 0;
        stats.glossy += glossy ? 1 : 0;
        // (a stale sense reads as nothing under the feet: keep the coat's source, so one pool is one pickup)
        if ((fresh || in_water || k.coat_forced) &&
            R::Soak(coat, k, in_water, glossy, pick_px, blood_px, glossy_stay)) {
            const u32 share = pick_px ? u32(u64(blood_px) * 100u / pick_px) : 0u;
            const u32 kind_at = std::min<u32>(u32(coat.kind), 2u);
            ++stats.pickups[kind_at];
            if (coat.source == R::Source::Blood) {
                stats.share_last = share;
                stats.share_max = std::max(stats.share_max, share);
                stats.share_sum += share;
                ++stats.share_n;
            }
            if (!told_pickup[kind_at]) {
                told_pickup[kind_at] = true;
                BbReport::Printf("Footprints (r111): first pickup at frame %llu: a %s coat from %s, "
                                 "strength %.2f; pickup disc %u px, %u blood (%u%%); ground band %u "
                                 "px, %u glossy\n",
                                 static_cast<unsigned long long>(frame), R::KindName(coat.kind),
                                 R::SourceName(coat.source), double(coat.amount), pick_px, blood_px,
                                 share, c[R::WordGroundN], c[R::WordWetN]);
            }
        }
        if (k.trail && fresh) { // (r111k) frames a source is held by the lower stay share and not by the pickup rule
            stats.trail_holds += ((coat.source == R::Source::Blood && !R::InBloodTrail(pick_px, blood_px, false)) ||
                                  (coat.source == R::Source::Puddle && !glossy))
                                     ? 1u
                                     : 0u;
        }
        const R::Step s = R::Walk(walker, pos);
        if (s.step) {
            ++stats.steps;
            ++stats.steps_in[std::min<u32>(u32(coat.source), 3u)];
            R::Kind kind = R::Kind::Wet;
            const float strength = R::TakeStep(coat, k, in_water, kind);
            if (strength > 0.0f) {
                Place(s, kind, strength, now);
                stats.trail_prints += k.trail ? 1u : 0u; // (r111k)
                stats.tail_prints += (k.trail && strength < R::TailStrength) ? 1u : 0u;
            } else {
                ++stats.dry_steps;
            }
        }
    }
    stats.jumps = walker.jumps;
    // Fading: a print whose strength is gone is dropped (the oldest come first).
    u32 kept = 0;
    for (u32 i = 0; i < placed_count; ++i) {
        Placed p = placed[i];
        const double age = now - p.born;
        p.now = p.strength * R::Fade(age) * (k.trail ? R::FadeIn(age) : 1.0f); // (r111k) a new print fades in
        if (p.now > 1.0f / 64.0f || (k.trail && age < double(R::FadeInS))) {
            placed[kept++] = p;
        }
    }
    placed_count = kept;
    if (stats.frames < LineFrames) {
        return;
    }
    // (Five lines, each under 300 characters: the slot runner keeps 300 of a log line.)
    BbReport::Printf("Footprints (r111): %u frames, hunter read in %u (at %.2f %.2f %.2f; camera %.2f to "
                     "%.2f m away, %.2f to %.2f m above his position); %u steps: %u prints placed "
                     "(%u wet, %u mud, %u blood), %u dry\n",
                     stats.frames, stats.read, double(hunter[0]), double(hunter[1]), double(hunter[2]),
                     double(stats.near_m), double(stats.far_m), double(stats.low_m), double(stats.high_m),
                     stats.steps, stats.by_kind[0] + stats.by_kind[1] + stats.by_kind[2],
                     stats.by_kind[0], stats.by_kind[1], stats.by_kind[2], stats.dry_steps);
    BbReport::Printf("Footprints (r111): frames %u in water, %u on glossy ground, %u with a water "
                     "plane; %u path restarts; %u live; coat %s %.2f; %u passes (%.0f px each)\n",
                     stats.in_water, stats.glossy, stats.planes, stats.jumps, placed_count,
                     R::KindName(coat.kind), double(coat.amount), stats.passes,
                     stats.passes ? double(stats.pass_px) / double(stats.passes) : 0.0);
    BbReport::Printf("Footprints (r111): skipped %u off screen, %u no camera, %u unfit, %u lamps "
                     "open, %u previews\n",
                     stats.off_screen, stats.no_camera, stats.cannot, stats.lamps_open, stats.previews);
    const auto& s = sense;
    const u32 ground = s[R::WordGroundN];
    const double g = ground ? 1.0 / (255.0 * double(ground)) : 0.0;
    char water[48] = "none";
    if (plane_y != 0.0f) {
        std::snprintf(water, sizeof(water), "y %.2f (last seen)", double(plane_y));
    }
    BbReport::Printf("Footprints (r111): recent frame (%s, %u fresh): %u print pixels of %u looked at; "
                     "around the feet %u up-facing px, mean height %+.3f m (under -0.25 m %u, -0.25 "
                     "to -0.08 %u, band %u, 0.08 to 0.25 %u, above %u)\n",
                     sense_fresh ? "read back" : "none yet", stats.sense_fresh, s[R::WordPrintPx],
                     s[R::WordSeenPx], s[R::WordSenseN],
                     s[R::WordSenseN] ? double(s[R::WordSenseDyMm]) / (1000.0 * double(s[R::WordSenseN])) -
                                            double(FOOTPRINTS_SENSE_HEIGHT_M)
                                      : 0.0,
                     s[R::WordBinLow], s[R::WordBinBelow], ground, s[R::WordBinAbove],
                     s[R::WordBinHigh]);
    BbReport::Printf("Footprints (r111): ground band gloss mean %.3f, %u at 0.88 or more (%u needed of "
                     "%u); linear albedo mean %.3f %.3f %.3f; ring %u px; water plane %s\n",
                     double(s[R::WordGlossSum]) * g, s[R::WordWetN],
                     (ground * R::WetSharePercent + 99u) / 100u, ground,
                     double(s[R::WordAlbedoR]) * g, double(s[R::WordAlbedoG]) * g,
                     double(s[R::WordAlbedoB]) * g, s[R::WordRingPx], water);
    BbReport::Printf("Footprints (r111): pickup: coat %s %.2f, %u prints at full strength left; picked "
                     "up %u wet, %u blood, %u mud (mud is not read); steps in blood %u, in water %u, "
                     "on a puddle %u, elsewhere %u\n",
                     R::KindName(coat.kind), double(coat.amount), coat.full, stats.pickups[0],
                     stats.pickups[2], stats.pickups[1], stats.steps_in[3], stats.steps_in[1],
                     stats.steps_in[2], stats.steps_in[0]);
    BbReport::Printf("Footprints (r111): blood pickups %u: share of the pickup disc in blood last %u%%, "
                     "max %u%%, mean %u%%; disc now %u px, %u blood; the rule: linear "
                     "red %.2f to %.2f, at least %.1f times green and %.1f times blue, from %u%% of "
                     "the disc\n",
                     stats.pickups[2], stats.share_last, stats.share_max,
                     stats.share_n ? stats.share_sum / stats.share_n : 0u, s[R::WordPickN],
                     s[R::WordBloodN], double(BLOOD_ALBEDO_R_MIN), double(BLOOD_ALBEDO_R_MAX),
                     double(BLOOD_ALBEDO_RED_OVER_GREEN), double(BLOOD_ALBEDO_RED_OVER_BLUE),
                     R::BloodSharePercent);
    BbReport::Printf("Footprints (r111c): prints on a pass's screen: %u passes, %u prints sent, %.2f to %.2f m "
                     "from the camera, the largest box %d x %d px; read-backs %u, %u frames with print pixels (G-buffer "
                     "band or post stamp), the most %u px; gain %.2f\n",
                     stats.print_passes, stats.sent_prints, double(stats.print_near_m),
                     double(stats.print_far_m), stats.box_w, stats.box_h, stats.readbacks,
                     stats.print_px_frames, stats.print_px_max, double(R::Gain()));
    LogFlat(); // (r111f) the line of r111e, in numbers only, with the read-back count
    LogTrail(); // (r111k)
    flat = {};
    stats = {};
}

} // namespace Vulkan
