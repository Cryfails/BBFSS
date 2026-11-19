// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_glass_clear.h"
#include "video_core/renderer_vulkan/vk_workflow_consumer.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_toggles.h"
#include "video_core/host_shaders/glass_clear_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r131c_cabinet-glass-clear): the live knobs of the test tools (r84_live-test-knobs): in a build with the header,
// BB_GLASS_CLEAR and BB_GLASS_CLEAR_FILM are switched while the game runs.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define GLASS_CLEAR_LIVE 1
#endif

namespace Vulkan {
namespace {
namespace R = GlassRegistryRules;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr vk::DeviceSize CounterBytes = GLASS_CLEAR_WORDS * sizeof(u32);
// EffectPass::Mark's key (the row "Lighting: glass clear"): the rows are keys, 0x4C490000 | key; in use: 6, 10-18, 51, 61-64,
// 80, 81, 86, 95, 97, 99, 100, 105, 107, 111, 117, 119, 129, 130; 132 is free
constexpr u64 ProfileRow = 132;

/// Colour formats a sampled view reads as float (the G-buffer's normal and albedo targets).
bool FloatColour(vk::Format format) {
    return format == vk::Format::eR8G8B8A8Unorm || format == vk::Format::eR8G8B8A8Srgb ||
           format == vk::Format::eR16G16B16A16Sfloat || format == vk::Format::eA2B10G10R10UnormPack32 ||
           format == vk::Format::eB10G11R11UfloatPack32;
}

/// The colour format the draw's pipeline was made with for target `slot` (as GraphicsPipeline's PipelineRenderingCreateInfo has
/// it), undefined past its targets: a view bound there must be of this format (VUID 08910).
vk::Format SlotFormat(const Instance& instance, const GraphicsPipelineKey& key, u32 slot) {
    if (slot >= key.num_color_attachments || slot >= key.color_buffers.size()) {
        return vk::Format::eUndefined;
    }
    const auto& cb = key.color_buffers[slot];
    return instance.GetSupportedFormat(LiverpoolToVK::SurfaceFormat(cb.data_format, cb.num_format),
                                       vk::FormatFeatureFlagBits2::eColorAttachment);
}

/// BB_GLASS_CLEAR now: live in a build with the live knobs header, else read once. 1 only: the pane is cleared.
bool ClearNow() {
#ifdef GLASS_CLEAR_LIVE
    static BbLiveKnobs::Knob<u8> knob{"BB_GLASS_CLEAR", R::ParseClear};
    return knob.Get() == 1;
#else
    static const bool fixed = R::ParseClear(std::getenv("BB_GLASS_CLEAR")) == 1;
    return fixed;
#endif
}

/// BB_GLASS_CLEAR_FILM now (live where the header is): 0..ClearFilmMax, default ClearFilmDefault.
float FilmNow() {
#ifdef GLASS_CLEAR_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_GLASS_CLEAR_FILM", R::ParseClearFilm};
    return knob.Get();
#else
    static const float fixed = R::ParseClearFilm(std::getenv("BB_GLASS_CLEAR_FILM"));
    return fixed;
#endif
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

/// What the pass's commands begin with: the game's writes before it (the pane's attachment writes included) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
}

/// What it ends with: later passes and the host (the counters) see its writes.
void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands | Host,
                              MemoryAll | vk::AccessFlagBits2::eHostRead);
}

/// A new side image goes from undefined to the General layout it stays in (attachment, sampled, clear target).
vk::ImageMemoryBarrier2 ToGeneral(vk::Image image, vk::ImageAspectFlags aspect) {
    return {.srcStageMask = vk::PipelineStageFlagBits2::eTopOfPipe,
            .dstStageMask = AllCommands,
            .dstAccessMask = MemoryAll,
            .oldLayout = vk::ImageLayout::eUndefined,
            .newLayout = vk::ImageLayout::eGeneral,
            .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
            .image = image,
            .subresourceRange = {aspect, 0, 1, 0, 1}};
}
} // namespace

bool GlassClear::Wanted() {
#ifdef GLASS_CLEAR_LIVE
    if (std::getenv("BB_LIVE_KNOBS_FILE") != nullptr) {
        return true;
    }
#endif
    return R::ParseClear(std::getenv("BB_GLASS_CLEAR")) == 1;
}

GlassClear::GlassClear(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                       Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_}, table{R::Load()} {
    on = ClearNow();
    const char* text = std::getenv("BB_GLASS_CLEAR");
    u32 clearing = 0;
    for (u32 i = 0; i < table.count; ++i) {
        clearing += R::Clears(table.entries[i].kind) ? 1u : 0u;
    }
    BbReport::Printf("Glass clear (r131c): BB_GLASS_CLEAR=%.16s: knob %s, film %.2f (BB_GLASS_CLEAR_FILM, 0 to %.2f), %u clearing "
                     "entries (the cabinet kind; the mirror stays opaque)%s\n",
                     text ? text : "", on ? "on" : "off", double(FilmNow()), double(R::ClearFilmMax), clearing,
                     clearing == 0 ? " - NO cabinet entry in BB_GLASS_TABLE: nothing to clear" : "");
    if (R::ParseClear(text) == 2) {
        BbReport::Printf("Glass clear (r131c): BB_GLASS_CLEAR=%.16s is neither 0 nor 1: knob off\n", text);
    }
}

GlassClear::~GlassClear() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}

bool GlassClear::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made = EffectPass::StorageFormat(instance, SceneFormat) &&
                      EffectPass::Create(instance, set_layout, layout, pipeline,
                                         {eStorageImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                                          eStorageBuffer},
                                         sizeof(Push), GLASS_CLEAR_COMP, "Glass clear");
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = CounterBytes,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{};
    alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
    alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &counters.allocation, &info) == VK_SUCCESS) {
        counters.buffer = raw;
        counters.mapped = info.pMappedData;
    }
    if (counters.mapped == nullptr) {
        Fail("the counters buffer could not be made");
        return false;
    }
    std::memset(counters.mapped, 0, CounterBytes);
    return true;
}

void GlassClear::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Glass clear (r131c): off - %s\n", why);
    ReleaseImages();
}

void GlassClear::ReleaseImages() {
    if (normal_image || albedo_image || depth_image || normal_view || albedo_view || depth_attach_view || depth_sample_view) {
        // views first, then their images, in one deferred operation (the GPU may still use them)
        scheduler.DeferOperation([a = std::move(normal_image), b = std::move(albedo_image), c = std::move(depth_image),
                                  va = std::move(normal_view), vb = std::move(albedo_view), vc = std::move(depth_attach_view),
                                  vd = std::move(depth_sample_view)]() mutable {
            va.reset();
            vb.reset();
            vc.reset();
            vd.reset();
            for (auto* image : {&a, &b, &c}) {
                if (*image) {
                    image->Destroy();
                }
            }
        });
    }
    for (u32 i = 0; i < sink_images.size(); ++i) {
        if (sink_images[i]) {
            scheduler.DeferOperation([image = std::move(sink_images[i]), view = std::move(sink_views[i])]() mutable {
                view.reset();
                image.Destroy();
            });
        }
        sink_views[i].reset();
        sink_formats[i] = vk::Format::eUndefined;
    }
    normal_view.reset();
    albedo_view.reset();
    depth_attach_view.reset();
    depth_sample_view.reset();
    normal_format = albedo_format = depth_format = vk::Format::eUndefined;
    side_width = side_height = 0;
    clear_due = true;
}

bool GlassClear::EnsureSize(u32 width, u32 height) {
    if (side_width == width && side_height == height) {
        return true;
    }
    ReleaseImages();
    side_width = width;
    side_height = height;
    return true;
}

bool GlassClear::EnsureDepth(vk::Format format, bool stencil) {
    if (depth_image && depth_format == format && depth_stencil == stencil) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 6ull * side_width * side_height)) {
        return false;
    }
    if (depth_image) {
        scheduler.DeferOperation([moved = std::move(depth_image), a = std::move(depth_attach_view),
                                  b = std::move(depth_sample_view)]() mutable {
            a.reset();
            b.reset();
            moved.Destroy();
        });
        depth_attach_view.reset();
        depth_sample_view.reset();
    }
    const auto device = instance.GetDevice();
    const vk::ImageAspectFlags aspect =
        stencil ? vk::ImageAspectFlagBits::eDepth | vk::ImageAspectFlagBits::eStencil : vk::ImageAspectFlagBits::eDepth;
    depth_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    depth_image.Create({
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {side_width, side_height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eDepthStencilAttachment | vk::ImageUsageFlagBits::eSampled |
                 vk::ImageUsageFlagBits::eTransferDst,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(depth_image), "Glass clear side depth");
    depth_attach_view = Check<"create glass clear depth view">(device.createImageViewUnique({
        .image = vk::Image(depth_image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {aspect, 0, 1, 0, 1},
    }));
    depth_sample_view = Check<"create glass clear depth sample view">(device.createImageViewUnique({
        .image = vk::Image(depth_image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {vk::ImageAspectFlagBits::eDepth, 0, 1, 0, 1},
    }));
    depth_format = format;
    depth_stencil = stencil;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear depth layout"},
                          [image = vk::Image(depth_image), aspect](vk::CommandBuffer cmd) {
                              const auto barrier = ToGeneral(image, aspect);
                              cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
                          });
    clear_due = true;
    return true;
}

bool GlassClear::EnsureColour(vk::Format normal_format_, vk::Format albedo_format_) {
    if (normal_image && normal_format == normal_format_ && albedo_format == albedo_format_) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 8ull * side_width * side_height)) {
        return false;
    }
    if (normal_image) {
        scheduler.DeferOperation([a = std::move(normal_image), b = std::move(albedo_image), va = std::move(normal_view),
                                  vb = std::move(albedo_view)]() mutable {
            va.reset();
            vb.reset();
            a.Destroy();
            b.Destroy();
        });
        normal_view.reset();
        albedo_view.reset();
    }
    const auto device = instance.GetDevice();
    const auto make = [&](VideoCore::UniqueImage& image, vk::UniqueImageView& view, vk::Format format, const char* name) {
        image = VideoCore::UniqueImage(device, instance.GetAllocator());
        image.Create({
            .imageType = vk::ImageType::e2D,
            .format = format,
            .extent = {side_width, side_height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eColorAttachment | vk::ImageUsageFlagBits::eSampled,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        SetObjectName(device, vk::Image(image), name);
        view = Check<"create glass clear colour view">(device.createImageViewUnique({
            .image = vk::Image(image),
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
        }));
    };
    make(normal_image, normal_view, normal_format_, "Glass clear side normal");
    make(albedo_image, albedo_view, albedo_format_, "Glass clear side albedo");
    normal_format = normal_format_;
    albedo_format = albedo_format_;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear colour layout"},
                          [a = vk::Image(normal_image), b = vk::Image(albedo_image)](vk::CommandBuffer cmd) {
                              const std::array barriers{ToGeneral(a, vk::ImageAspectFlagBits::eColor),
                                                        ToGeneral(b, vk::ImageAspectFlagBits::eColor)};
                              cmd.pipelineBarrier2({.imageMemoryBarrierCount = 2, .pImageMemoryBarriers = barriers.data()});
                          });
    return true;
}

bool GlassClear::EnsureSink(u32 slot, vk::Format format) {
    if (sink_images[slot] && sink_formats[slot] == format) {
        return true;
    }
    if (!EffectPass::HasRoom(instance, 16ull * side_width * side_height)) {
        return false;
    }
    if (sink_images[slot]) {
        scheduler.DeferOperation([image = std::move(sink_images[slot]), view = std::move(sink_views[slot])]() mutable {
            view.reset();
            image.Destroy();
        });
        sink_views[slot].reset();
    }
    const auto device = instance.GetDevice();
    sink_images[slot] = VideoCore::UniqueImage(device, instance.GetAllocator());
    sink_images[slot].Create({
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {side_width, side_height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eColorAttachment,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(sink_images[slot]), "Glass clear sink");
    sink_views[slot] = Check<"create glass clear sink view">(device.createImageViewUnique({
        .image = vk::Image(sink_images[slot]),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    }));
    sink_formats[slot] = format;
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "glass clear sink layout"}, [image = vk::Image(sink_images[slot])](vk::CommandBuffer cmd) {
        const auto barrier = ToGeneral(image, vk::ImageAspectFlagBits::eColor);
        cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
    });
    return true;
}

bool GlassClear::Wants(u8 hit, bool shape_ok, bool preview, bool same_camera) {
    if (!on || failed || hit == 0 || hit > table.count) {
        return false;
    }
    const auto& entry = table.entries[hit - 1u];
    if (!R::Clears(entry.kind) || !shape_ok) {
        return false; // a forward draw of the entry (1 to 4 colour targets) stays as it is
    }
    if (preview) {
        ++stats.kept_preview;
        return false;
    }
    if (!same_camera) {
        ++stats.kept_camera;
        return false;
    }
    f0 = entry.f0;
    return true;
}

bool GlassClear::Redirect(RenderState& state, VideoCore::ImageId normal, VideoCore::ImageId albedo, VideoCore::ImageId depth,
                          u32 depth_mode, bool stencil_func, const GraphicsPipelineKey& key) {
    if (failed) {
        return false;
    }
    const bool depth_only = key.mrt_mask == 0;
    const auto& db = state.depth_stencil_attachment;
    bool cleared = db.depth_clear || db.stencil_clear;
    for (u32 i = 0; i < state.num_color_attachments; ++i) {
        cleared = cleared || state.color_attachments[i].is_clear != 0;
    }
    if (cleared) {
        ++stats.kept_clear; // a pass that clears is not moved to side images
        return false;
    }
    if (stencil_func) {
        ++stats.kept_stencil; // the side stencil holds 0: a stencil test with a func would reject the pane
        return false;
    }
    if (depth_mode > 1 || !depth || !db.has_depth || !db.image_view || (redirected_frame && reverse_z != (depth_mode == 1))) {
        ++stats.kept_other;
        return false;
    }
    if (!depth_only && (!normal || !albedo || state.num_color_attachments < 3 || !state.color_attachments[0].image_view ||
                        !state.color_attachments[2].image_view)) {
        ++stats.kept_other;
        return false;
    }
    if (state.width < 16 || state.height < 16) {
        ++stats.kept_other;
        return false;
    }
    const auto& depth_source = texture_cache.GetImage(depth);
    // fixed (r131c review): every format is the pipeline's own (a view of another format is VUID 08910), and each colour target
    // other than 0 and 2 that has a view gets a sink of that format (a null view where the pipeline has a format is VUID 08912)
    std::array<vk::Format, 8> formats{};
    vk::Format normal_wanted = vk::Format::eUndefined, albedo_wanted = vk::Format::eUndefined;
    if (!depth_only) {
        for (u32 i = 0; i < state.num_color_attachments && i < formats.size(); ++i) {
            formats[i] = state.color_attachments[i].image_view ? SlotFormat(instance, key, i) : vk::Format::eUndefined;
            if (state.color_attachments[i].image_view && formats[i] == vk::Format::eUndefined) {
                ++stats.kept_other;
                return false;
            }
        }
        normal_wanted = formats[0];
        albedo_wanted = formats[2];
        if (state.num_color_attachments > formats.size() || !FloatColour(normal_wanted) || !FloatColour(albedo_wanted)) {
            ++stats.kept_other;
            return false;
        }
    }
    if (!Ready()) {
        return false;
    }
    // the side depth has every aspect of its format (fixed (r131c review): a depth view of a depth-stencil image without its
    // stencil aspect is not what the game's own view is)
    if (!EnsureSize(state.width, state.height) ||
        !EnsureDepth(depth_source.info.pixel_format, bool(depth_source.aspect_mask & vk::ImageAspectFlagBits::eStencil)) ||
        (!depth_only && !EnsureColour(normal_wanted, albedo_wanted))) {
        ++stats.kept_other;
        return false;
    }
    for (u32 i = 0; !depth_only && i < state.num_color_attachments; ++i) {
        if (i != 0 && i != 2 && state.color_attachments[i].image_view && !EnsureSink(i, formats[i])) {
            ++stats.kept_other;
            return false;
        }
    }
    reverse_z = depth_mode == 1;
    redirected_frame = true;
    if (clear_due) {
        // the side depth goes to "far" (and stencil 0) once before the first pane draw of the frame; a command of its own, not a
        // load op, so that every pane draw of a pass has the same render state and the pass is not broken between them
        clear_due = false;
        scheduler.EndRendering();
        scheduler.RecordCrumb({.name = "glass clear depth"},
                              [image = vk::Image(depth_image), far_value = reverse_z ? 0.0f : 1.0f,
                               aspect = depth_stencil ? vk::ImageAspectFlagBits::eDepth | vk::ImageAspectFlagBits::eStencil
                                                      : vk::ImageAspectFlagBits::eDepth](vk::CommandBuffer cmd) {
                                  EffectPass::MemoryBarrier(cmd, AllCommands, MemoryAll, Transfer,
                                                            vk::AccessFlagBits2::eTransferWrite);
                                  const vk::ClearDepthStencilValue value{far_value, 0};
                                  const vk::ImageSubresourceRange range{aspect, 0, 1, 0, 1};
                                  cmd.clearDepthStencilImage(image, vk::ImageLayout::eGeneral, value, range);
                                  EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, AllCommands,
                                                            MemoryAll);
                              });
    }
    // the swap: normal and albedo to the side images, every other colour target that has a view to its sink (a null view stays
    // null, as the game's draw has it), the depth to the side depth
    if (!depth_only) {
        for (u32 i = 0; i < state.num_color_attachments; ++i) {
            auto& attachment = state.color_attachments[i];
            if (i == 0 || i == 2) {
                attachment.image_view = i == 0 ? *normal_view : *albedo_view;
                attachment.image_layout = vk::ImageLayout::eGeneral;
            } else if (attachment.image_view) {
                attachment.image_view = *sink_views[i];
                attachment.image_layout = vk::ImageLayout::eGeneral;
            }
        }
    }
    state.depth_stencil_attachment.image_view = *depth_attach_view;
    state.depth_stencil_attachment.image_layout = vk::ImageLayout::eGeneral;
    pending_composite = true;
    ++stats.redirected;
    stats.depth_only += depth_only ? 1u : 0u;
    return true;
}

vk::ImageView GlassClear::CachedView(const VideoCore::Image& image, vk::Format format, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create glass clear image view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool GlassClear::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
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

vk::ImageView GlassClear::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write) {
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

void GlassClear::Composite(VideoCore::ImageId scene, VideoCore::ImageId depth, std::array<float, 2> jitter,
                           bool lamps_pending) {
    if (!pending_composite || failed || !scene || !depth || lamps_pending || !depth_sample_view || !normal_view ||
        !albedo_view) {
        return; // (with lamps open it waits: the side images stay until the next redirect of a frame)
    }
    if (depth != camera_motion.Depth()) {
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    const auto proj = camera_motion.PassProjection();
    if (!camera.valid || proj[0] == 0.0f || proj[1] == 0.0f) {
        return;
    }
    pending_composite = false;
    const auto& scene_image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (scene_image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) || width != side_width ||
        height != side_height) {
        ++stats.skip_shape;
        if (!told_shape) {
            told_shape = true;
            BbReport::Printf("Glass clear (r131c): composite left out (first time): the lit scene is format %u, %ux%u, the "
                             "side images %ux%u\n",
                             u32(scene_image.info.pixel_format), width, height, side_width, side_height);
        }
        return;
    }
    const SceneUseScope scene_use{"glass clear"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = ViewOf(scene, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView depth_view = ViewOf(depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view || !depth_view) {
        ++stats.skip_shape;
        return;
    }
    Push push{};
    push.proj = proj;
    push.view = camera.view;
    push.size = {float(width), float(height)};
    push.jitter = jitter;
    push.film = FilmNow();
    push.f0 = f0;
    push.hole_metres = R::ClearHoleMetres;
    push.flags = reverse_z ? u32(GLASS_CLEAR_FLAG_REVERSE) : 0u;
    ++stats.composites;
    if (WorkflowProbe::TrackConsumers) ++WorkflowProbe::GlassComposites;
    EffectPass::Mark(ProfileRow, "glass clear", true);
    scheduler.RecordCrumb(
        {.name = "glass clear"},
        [push, width, height, scene_view, depth_view, side_depth = *depth_sample_view, side_albedo = *albedo_view,
         side_normal = *normal_view, counter_buffer = vk::Buffer(counters.buffer), pipeline_handle = *pipeline,
         layout_handle = *layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            using enum vk::DescriptorType;
            const std::array infos{Info(scene_view), Info(depth_view), Info(side_depth), Info(side_albedo), Info(side_normal)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, CounterBytes};
            const std::array writes{
                ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                ImageWrite(2, eSampledImage, &infos[2]), ImageWrite(3, eSampledImage, &infos[3]),
                ImageWrite(4, eSampledImage, &infos[4]),
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1, .descriptorType = eStorageBuffer,
                                       .pBufferInfo = &counter_info},
            };
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline_handle);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout_handle, 0, writes);
            cmd.pushConstants(layout_handle, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + GLASS_CLEAR_GROUP - 1) / GLASS_CLEAR_GROUP, (height + GLASS_CLEAR_GROUP - 1) / GLASS_CLEAR_GROUP,
                         1);
            EndBarrier(cmd);
        });
}

void GlassClear::Line(const char* why) {
    const u64 rt_now = rt_shadow.GlassClearRecords();
    stats.rt_records = rt_now - rt_records_last;
    rt_records_last = rt_now;
    const bool opaque = on && stats.redirected != 0 && stats.rt_records == 0 && !rt_shadow.GlassLightWanted();
    BbReport::Printf("Glass clear (r131c): %sframes %llu-%llu: knob %s, panes redirected %u (depth-only %u), composited %u "
                     "passes, pixels %llu, holes %llu, kept: clear %u, stencil %u, other %u, other camera %u, preview %u, "
                     "composite left out %u; rt: glass records %llu%s%s\n",
                     why, static_cast<unsigned long long>(window_start + 1), static_cast<unsigned long long>(frame),
                     on ? "on" : "off", stats.redirected, stats.depth_only, stats.composites,
                     static_cast<unsigned long long>(stats.visible), static_cast<unsigned long long>(stats.holes),
                     stats.kept_clear, stats.kept_stencil, stats.kept_other, stats.kept_camera, stats.kept_preview,
                     stats.skip_shape, static_cast<unsigned long long>(stats.rt_records),
                     opaque ? " (opaque: needs BB_GLASS_LIGHT=1)" : "", failed ? " (off after a failure)" : "");
    stats = {};
    window_start = frame;
}

void GlassClear::OnFrameEnd() {
    // the frame's redirects are over: the next frame's first one clears the side depth again; nothing carries across frames
    pending_composite = false;
    redirected_frame = false;
    clear_due = true;
    if (counters.mapped != nullptr) { // the pass's cumulative counters (u32 differences survive the wrap)
        const u32* words = static_cast<const u32*>(counters.mapped);
        stats.visible += u32(words[GLASS_CLEAR_W_VISIBLE] - counted_last[0]);
        stats.holes += u32(words[GLASS_CLEAR_W_HOLE] - counted_last[1]);
        counted_last = {words[GLASS_CLEAR_W_VISIBLE], words[GLASS_CLEAR_W_HOLE]};
    }
    const bool now = ClearNow();
    ++frame;
    if (now != on || !told) {
        if (told) {
            Line("before the change, "); // the window up to the flip
        }
        on = now;
        told = true;
        BbReport::Printf("Glass clear (r131c): knob %s at frame %llu\n", now ? "on" : "off", static_cast<unsigned long long>(frame));
        stats.frames = 0;
        return;
    }
    if (++stats.frames < LineFrames) {
        return;
    }
    Line("");
}

} // namespace Vulkan
