// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r100c_blood-pool-probe, r100d_blood-pool-draws): TOOL (branch dev/test-tools).
// vk_blood_pool_probe.h says where it hooks in and what it costs; blood_pool_probe.h has the knob.
#include "video_core/renderer_vulkan/vk_blood_pool_probe.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <utility>

#include "bbport_live_knobs.h"
#include "bbport_toggles.h"
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_pool_probe_compare_comp.h"
#include "video_core/host_shaders/blood_pool_probe_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace R = BloodPoolProbeRules;
constexpr const char* KnobName = "BB_BLOOD_POOL_PROBE";
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr vk::DeviceSize CountsBytes = vk::DeviceSize(R::CaptureFrames) * R::MaxDraws * R::RecordWords * 4;
constexpr vk::DeviceSize OwnersBytes = vk::DeviceSize(R::OwnerMaps) * R::MaxSide * R::MaxSide * 4;
/// Role names (DrawInfo::role): 1-8 the G-buffer pass's targets 0-7, then a light draw's and the
/// scene colour (RGBA16F with the scene depth).
constexpr const char* RoleNames[] = {"", "nrm", "mat", "alb", "spc", "g4", "g5", "g6", "g7", "lit", "scn"};
constexpr u8 RoleLight = 9, RoleScene = 10;
constexpr const char* FuncNames[] = {"never", "lt", "eq", "le", "gt", "ne", "ge", "always"};

/// A colour target format the passes sample as floats (an integer format would need another
/// texture type): its short name in the log, else null.
const char* ColourName(vk::Format format) {
    switch (format) {
    case vk::Format::eR8G8B8A8Unorm:
        return "8";
    case vk::Format::eR8G8B8A8Srgb:
        return "8s";
    case vk::Format::eB8G8R8A8Unorm:
        return "b8";
    case vk::Format::eB8G8R8A8Srgb:
        return "b8s";
    case vk::Format::eA2B10G10R10UnormPack32:
        return "10";
    case vk::Format::eB10G11R11UfloatPack32:
        return "11f";
    case vk::Format::eR16G16B16A16Sfloat:
        return "16f";
    case vk::Format::eR16G16Sfloat:
        return "rg16f";
    case vk::Format::eR16Sfloat:
        return "r16f";
    case vk::Format::eR32Sfloat:
        return "32f";
    case vk::Format::eR32G32Sfloat:
        return "rg32f";
    case vk::Format::eR32G32B32A32Sfloat:
        return "128f";
    case vk::Format::eR8Unorm:
        return "r8";
    case vk::Format::eR8G8Unorm:
        return "rg8";
    case vk::Format::eR16G16B16A16Unorm:
        return "16u";
    default:
        return nullptr;
    }
}

const char* DepthName(vk::Format format) {
    switch (format) {
    case vk::Format::eD32SfloatS8Uint:
        return "d32s8";
    case vk::Format::eD32Sfloat:
        return "d32";
    case vk::Format::eD24UnormS8Uint:
        return "d24s8";
    case vk::Format::eD16Unorm:
        return "d16";
    default:
        return "d?";
    }
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// What a pass's commands begin with: the game's writes before it are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
}

/// And end with: the game's next work waits for the pass's reads, the next pass for its writes.
void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, ReadWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

/// Records one pass: the nine targets (unused bindings hold a view of a used one; the mask keeps
/// the shader off them), the prints, and for COMPARE the counters and owner maps.
void RecordPass(vk::CommandBuffer cmd, vk::Pipeline pipeline, vk::PipelineLayout layout,
                const std::array<vk::ImageView, R::Targets>& views, vk::Buffer prints, vk::Buffer counts,
                vk::Buffer owners, const R::Push& push, u32 groups_x, u32 groups_y) {
    BeginBarrier(cmd);
    std::array<vk::DescriptorImageInfo, R::Targets> images{};
    std::array<vk::WriteDescriptorSet, R::Targets + 3> writes{};
    for (u32 t = 0; t < R::Targets; ++t) {
        images[t] = Info(views[t]);
        writes[t] = {.dstBinding = t,
                     .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eSampledImage,
                     .pImageInfo = &images[t]};
    }
    const std::array<vk::DescriptorBufferInfo, 3> buffers{
        vk::DescriptorBufferInfo{prints, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{counts, 0, VK_WHOLE_SIZE},
        vk::DescriptorBufferInfo{owners, 0, VK_WHOLE_SIZE}};
    const u32 buffer_count = counts ? 3u : 1u;
    for (u32 b = 0; b < buffer_count; ++b) {
        writes[R::Targets + b] = {.dstBinding = R::Targets + b,
                                  .descriptorCount = 1,
                                  .descriptorType = vk::DescriptorType::eStorageBuffer,
                                  .pBufferInfo = &buffers[b]};
    }
    cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
    cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                             vk::ArrayProxy<const vk::WriteDescriptorSet>(R::Targets + buffer_count,
                                                                          writes.data()));
    cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
    cmd.dispatch(groups_x, groups_y, 2);
    EndBarrier(cmd);
}
} // namespace

bool BloodPoolProbe::Wanted() {
    static const bool wanted = R::Parse(std::getenv(KnobName)).kind != R::Kind::Off;
    return wanted;
}

BloodPoolProbe::BloodPoolProbe(const Instance& instance_, Scheduler& scheduler_,
                               VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                               SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const char* env = std::getenv(KnobName);
    BbReport::Printf("Blood pool probe (r100d, TOOL): on (%s=%.32s); a box x0:y0:x1:y1 in scene pixels "
                     "(this value or the live knobs file) is probed after %u frames with a G-buffer pass "
                     "(%u after a live change): every draw of %u frames\n",
                     KnobName, env ? env : "", R::ArmFramesStart, R::ArmFramesLive, R::CaptureFrames);
    knob_generation = BbLiveKnobs::Generation();
    TakeKnob(true);
}

BloodPoolProbe::~BloodPoolProbe() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(prints);
    FreeBuffer(counts);
    FreeBuffer(owners);
}

bool BloodPoolProbe::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = static_cast<VkBufferUsageFlags>(usage),
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    if (host) {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation, &info) !=
        VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    return !host || out.mapped;
}

void BloodPoolProbe::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodPoolProbe::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_SNAPSHOT_COMP, "Blood pool probe snapshot") &&
        EffectPass::Create(instance, compare_pass.set_layout, compare_pass.layout, compare_pass.pipeline,
                           {eSampledImage, eSampledImage, eSampledImage, eSampledImage, eSampledImage,
                            eSampledImage, eSampledImage, eSampledImage, eSampledImage, eStorageBuffer,
                            eStorageBuffer, eStorageBuffer},
                           sizeof(R::Push), BLOOD_POOL_PROBE_COMPARE_COMP, "Blood pool probe compare") &&
        MakeBuffer(counts, CountsBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(owners, OwnersBytes, true,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    return true;
}

void BloodPoolProbe::Fail(const char* why) {
    failed = true;
    state = State::Idle;
    pending = {};
    BbReport::Printf("Blood pool probe (r100d): off - %s\n", why);
}

vk::ImageView BloodPoolProbe::CachedView(const VideoCore::Image& image, vk::Format format,
                                         vk::ImageAspectFlags aspect) {
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
        .view = Check<"create blood pool probe view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

vk::ImageView BloodPoolProbe::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect) {
    auto& image = texture_cache.GetImage(id);
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, ShaderRead);
        return (proxy.usage & vk::ImageUsageFlagBits::eSampled) ? proxy.view : vk::ImageView{};
    }
    if (!(image.usage_flags & vk::ImageUsageFlagBits::eSampled)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, ShaderRead);
    return view;
}

void BloodPoolProbe::TakeKnob(bool at_start) {
    const BbLiveKnobs::Text text = BbLiveKnobs::Lookup(KnobName);
    const char* value = text.Get();
    const R::Knob k = R::Parse(value);
    switch (k.kind) {
    case R::Kind::Box:
        if (!at_start && k.SameBox(last_taken)) {
            return; // (another knob of the file changed)
        }
        last_taken = k;
        next = k;
        next_live = text.in_file;
        return;
    case R::Kind::Off:
    case R::Kind::On:
        last_taken = {};
        next = {};
        if (state == State::Armed) {
            state = State::Idle;
            BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u dropped before probing (%s=%.16s)\n",
                             box.x0, box.x1, box.y0, box.y1, KnobName, value ? value : "");
        }
        return;
    case R::Kind::Bad:
        BbReport::Printf("Blood pool probe (r100d): %s=%.40s is no box (x0:y0:x1:y1, decimal, x0<=x1, "
                         "y0<=y1); nothing changed\n",
                         KnobName, value ? value : "");
        return;
    }
}

void BloodPoolProbe::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                                const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth,
                                bool light, bool lamps_pending, bool indirect) {
    if (pending.on) {
        // The draw SNAPSHOT was recorded for was left out (a pipeline still compiling, a cascade
        // nothing samples): no COMPARE for it.
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    note_due = false;
    if (state == State::Idle || state == State::Waiting) {
        return;
    }
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    const bool gbuffer = std::popcount(mrt) >= 5 && bool(depth);
    const u8 phase = gbuffer                ? R::Gbuffer
                     : light                ? R::Light
                     : !frame_gbuffer       ? R::BeforeGbuffer
                     : frame_lit            ? R::AfterLight
                                            : R::BeforeLight;
    if (gbuffer) {
        frame_gbuffer = true;
        frame_lit = false;
        scene_depth = depth;
        const auto& image = texture_cache.GetImage(depth);
        scene_width = image.info.size.width;
        scene_height = image.info.size.height;
    } else if (light) {
        frame_lit = true;
    }
    if (state != State::Capturing) {
        return;
    }
    const u32 n = ordinal++;
    auto& list = infos[capture];
    if (n >= R::MaxDraws || n != list.size()) {
        ++over_cap[capture];
        return;
    }
    DrawInfo& info = list.emplace_back();
    note_due = true;
    note_ordinal = n;
    info.vs = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
    const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
    info.ps = ps ? ps->pgm_hash : 0;
    info.indices = indirect ? 0u : u32(regs.num_indices);
    info.instances = indirect ? 0u : regs.num_instances.NumInstances();
    info.mrt = mrt;
    info.phase = phase;
    info.indirect = indirect;
    info.light = light;
    info.depth_test = regs.depth_control.depth_enable != 0 && bool(depth);
    info.depth_write = info.depth_test && regs.depth_control.depth_write_enable != 0;
    info.depth_func = u8(u32(regs.depth_control.depth_func) & 7u);
    std::array<VideoCore::ImageId, R::Targets> ids{};
    for (u32 cb = 0; cb < 8; ++cb) {
        if (((mrt >> cb) & 1u) == 0 || !targets[cb]) {
            continue;
        }
        ids[cb] = targets[cb];
        const auto& image = texture_cache.GetImage(targets[cb]);
        info.format[cb] = u32(image.info.pixel_format);
        info.write_masks |= (regs.color_target_mask.GetMask(cb) & 15u) << (4 * cb);
        if (regs.blend_control[cb].enable && !regs.color_buffers[cb].info.blend_bypass) {
            info.blend |= u8(1u << cb);
        }
        info.role[cb] = gbuffer ? u8(1 + cb)
                        : light ? RoleLight
                        : (cb == 0 && image.info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
                           depth && depth == scene_depth)
                            ? RoleScene
                            : u8(0);
    }
    if (depth) {
        ids[R::DepthTarget] = depth;
        info.depth_format = u32(texture_cache.GetImage(depth).info.pixel_format);
    }
    if (camera_motion.PreviewFrame()) {
        info.skipped = Preview;
        return;
    }
    // Lamps apart (vk_point_shadow.h): an open batch's lamps go into images of their own, so the
    // light targets do not hold them yet; those draws are left alone (no read while it is open).
    if (lamps_pending) {
        info.skipped = LampsApart;
        return;
    }
    // The targets of the scene's size (the G-buffer pass's depth, or its reduced proxy) that the
    // passes can sample.
    u32 mask = 0;
    bool other_size = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if (!ids[t]) {
            continue;
        }
        const auto& image = texture_cache.GetImage(ids[t]);
        const bool proxy = scene_targets.Reduced() && scene_targets.EligibleScene(image);
        const bool scene_sized = proxy == capture_reduced &&
                                 (proxy || (image.info.size.width == cap_width &&
                                            image.info.size.height == cap_height));
        if (!scene_sized) {
            other_size = true;
            continue;
        }
        if ((t != R::DepthTarget && !ColourName(image.info.pixel_format)) || image.info.num_samples != 1) {
            continue; // (the passes read single-sample float textures)
        }
        mask |= 1u << t;
    }
    if (!mask) {
        info.skipped = other_size ? NotScene : Unreadable;
        return;
    }
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((mask >> t) & 1u) {
            views[t] = ViewOf(ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                          : vk::ImageAspectFlagBits::eColor);
            if (!views[t]) {
                mask &= ~(1u << t);
            }
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!mask) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    // Owners: the G-buffer's albedo (target 2), the scene colour by a draw of more than six indices
    // (full-screen passes left out; an indirect draw's count is unknown: taken), the depth.
    u32 albedo = R::NoTarget, scene = R::NoTarget;
    if (gbuffer && ((mask >> 2) & 1u)) {
        albedo = 2;
    }
    if (info.role[0] == RoleScene && (mask & 1u) && (indirect || info.indices > 6 || info.instances > 1)) {
        scene = 0;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = mask;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    info.read_mask = mask;
    scheduler.RecordCrumb({.name = "blood pool probe snapshot"},
                          [views, push, gx, gy, prints_buffer = prints.buffer,
                           pipeline_handle = *snapshot_pass.pipeline,
                           layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, {}, {}, push,
                                         gx, gy);
                          });
    pending = {.on = true,
               .ordinal = n,
               .mask = mask,
               .ids = ids,
               .owner_targets = albedo | (scene << 8) | ((mask >> R::DepthTarget) & 1u ? R::OwnDepth : 0u)};
}

void BloodPoolProbe::Note(bool indexed, u64 index_address, u32 first_index,
                          const std::array<Texture, R::DrawTextures>& textures, u32 count, u32 all, u32 hash) {
    if (!std::exchange(note_due, false) || state != State::Capturing || note_ordinal >= infos[capture].size()) {
        return;
    }
    DrawInfo& info = infos[capture][note_ordinal];
    info.noted = true;
    info.indexed = indexed;
    info.index_address = index_address;
    info.first_index = first_index;
    info.textures = textures;
    info.texture_count = std::min<u32>(count, R::DrawTextures);
    info.textures_all = all;
    info.texture_hash = hash;
}

void BloodPoolProbe::AfterDraw() {
    if (!pending.on) {
        return;
    }
    const Pending p = pending;
    pending = {};
    DrawInfo& info = infos[capture][p.ordinal];
    const SceneUseScope scene_use{"blood pool probe"};
    scheduler.EndRendering();
    std::array<vk::ImageView, R::Targets> views{};
    bool lost = false;
    for (u32 t = 0; t < R::Targets; ++t) {
        if ((p.mask >> t) & 1u) {
            views[t] = ViewOf(p.ids[t], t == R::DepthTarget ? vk::ImageAspectFlagBits::eDepth
                                                            : vk::ImageAspectFlagBits::eColor);
            lost = lost || !views[t];
        }
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (lost) {
        info.skipped = NoView;
        return;
    }
    const vk::ImageView any = views[std::countr_zero(p.mask)];
    for (auto& view : views) {
        view = view ? view : any;
    }
    R::Push push{};
    push.box[0] = s32(box.x0);
    push.box[1] = s32(box.y0);
    push.box[2] = s32(box.Width());
    push.box[3] = s32(box.Height());
    push.grid[0] = s32(grid_cols);
    push.grid[1] = s32(grid_rows);
    push.grid[2] = s32(R::Stride);
    push.mask = p.mask;
    push.record = (capture * R::MaxDraws + p.ordinal) * R::RecordWords;
    push.owner = R::OwnerValue(capture, p.ordinal);
    push.owner_targets = p.owner_targets;
    const u32 gx = (std::max(box.Width(), grid_cols) + R::Group - 1) / R::Group;
    const u32 gy = (std::max(box.Height(), grid_rows) + R::Group - 1) / R::Group;
    scheduler.RecordCrumb({.name = "blood pool probe compare"},
                          [views, push, gx, gy, prints_buffer = prints.buffer, counts_buffer = counts.buffer,
                           owners_buffer = owners.buffer, pipeline_handle = *compare_pass.pipeline,
                           layout = *compare_pass.layout](vk::CommandBuffer cmd) {
                              RecordPass(cmd, pipeline_handle, layout, views, prints_buffer, counts_buffer,
                                         owners_buffer, push, gx, gy);
                          });
    info.probed = true;
}

bool BloodPoolProbe::StartCapture() {
    if (!scene_depth || scene_width == 0 || scene_height == 0) {
        return false;
    }
    const auto& depth_image = texture_cache.GetImage(scene_depth);
    cap_width = scene_width;
    cap_height = scene_height;
    capture_reduced = scene_targets.Reduced() && scene_targets.EligibleScene(depth_image);
    pixels_width = cap_width;
    pixels_height = cap_height;
    if (capture_reduced) {
        pixels_width = scene_targets.Size().width;
        pixels_height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        pixels_width = std::min(pixels_width, render[0]);
        pixels_height = std::min(pixels_height, render[1]);
    }
    if (box.x1 >= pixels_width || box.y1 >= pixels_height) {
        BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u is not inside the %ux%u scene; "
                         "not probed\n",
                         box.x0, box.x1, box.y0, box.y1, pixels_width, pixels_height);
        state = State::Idle;
        return false;
    }
    if (!Ready()) {
        return false;
    }
    grid_cols = (pixels_width + R::Stride - 1) / R::Stride;
    grid_rows = (pixels_height + R::Stride - 1) / R::Stride;
    const vk::DeviceSize need =
        (vk::DeviceSize(box.Width()) * box.Height() + vk::DeviceSize(grid_cols) * grid_rows) * R::Targets * 4;
    if (need > prints_size) {
        if (prints.buffer) {
            scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = prints.buffer,
                                      allocation = prints.allocation] {
                vmaDestroyBuffer(allocator, buffer, allocation);
            });
            prints = {};
            prints_size = 0;
        }
        if (!EffectPass::HasRoom(instance, need) ||
            !MakeBuffer(prints, need, false, vk::BufferUsageFlagBits::eStorageBuffer)) {
            prints = {};
            Fail("no room for the prints");
            return false;
        }
        prints_size = need;
    }
    for (auto& list : infos) {
        list.clear();
        list.reserve(2048);
    }
    over_cap = {};
    capture = 0;
    pending = {};
    // The counters and owner maps start at 0 (the host reads them once the GPU is past the frames).
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe clear"},
                          [counts_buffer = counts.buffer, owners_buffer = owners.buffer](vk::CommandBuffer cmd) {
                              EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryRead,
                                                        Transfer, vk::AccessFlagBits2::eTransferWrite);
                              cmd.fillBuffer(counts_buffer, 0, VK_WHOLE_SIZE, 0);
                              cmd.fillBuffer(owners_buffer, 0, VK_WHOLE_SIZE, 0);
                              EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                                        Compute, ReadWrite);
                          });
    return true;
}

void BloodPoolProbe::EndCapture() {
    scheduler.EndRendering();
    scheduler.RecordCrumb({.name = "blood pool probe done"}, [](vk::CommandBuffer cmd) {
        EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                  vk::PipelineStageFlagBits2::eHost, vk::AccessFlagBits2::eHostRead);
    });
    done_tick = scheduler.CurrentTick();
}

void BloodPoolProbe::OnFrameEnd() {
    if (pending.on) {
        if (state == State::Capturing && pending.ordinal < infos[capture].size()) {
            infos[capture][pending.ordinal].skipped = LeftOut;
        }
        pending = {};
    }
    if (const u32 generation = BbLiveKnobs::Generation(); generation != knob_generation) {
        knob_generation = generation;
        TakeKnob(false);
    }
    switch (state) {
    case State::Idle:
        if (next.kind == R::Kind::Box && !failed) {
            box = next;
            box_live = next_live;
            next = {};
            arm_need = box_live ? R::ArmFramesLive : R::ArmFramesStart;
            arm_frames = 0;
            state = State::Armed;
            BbReport::Printf("Blood pool probe (r100d): box x %u-%u y %u-%u (%u px)%s armed (%s); probed "
                             "after %u frames in a row with a G-buffer pass\n",
                             box.x0, box.x1, box.y0, box.y1, box.Width() * box.Height(),
                             box.cut ? ", a side cut to 256" : "", box_live ? "live knobs file" : "at start",
                             arm_need);
        }
        break;
    case State::Armed:
        arm_frames = frame_gbuffer && !camera_motion.PreviewFrame() ? arm_frames + 1 : 0;
        if (arm_frames >= arm_need && StartCapture()) {
            state = State::Capturing;
        }
        break;
    case State::Capturing:
        if (++capture >= R::CaptureFrames) {
            capture = R::CaptureFrames - 1;
            EndCapture();
            state = State::Waiting;
            wait_frames = 0;
        }
        break;
    case State::Waiting:
        if (scheduler.IsFree(done_tick) || ++wait_frames >= R::WaitFrames) {
            Log();
            state = State::Idle;
        }
        break;
    }
    frame_gbuffer = frame_lit = false;
    ordinal = 0;
    note_due = false;
}

void BloodPoolProbe::Log() {
    const bool gpu_done = scheduler.IsFree(done_tick);
    const auto* c = static_cast<const u32*>(counts.mapped);
    const auto* o = static_cast<const u32*>(owners.mapped);
    const u32 frames = R::CaptureFrames;
    const u32 box_px = box.Width() * box.Height();
    struct Sum {
        u64 vs = 0, ps = 0;
        u32 draws = 0, probed = 0, box_draws = 0, box_max = 0;
        u64 box = 0, frame = 0;
        std::array<u64, R::Targets> by_target{};
        std::array<u32, R::OwnerMaps> own{};
        u32 idx_min = ~0u, idx_max = 0, inst_max = 0;
        u8 phases = 0;
        bool indirect = false;
        const DrawInfo* rep = nullptr;
        bool rep_changed = false;
        int first = -1, last = -1;
    };
    std::vector<Sum> sums;
    std::map<std::pair<u64, u64>, std::size_t> where;
    std::array<u32, 7> skipped{};
    u32 probed = 0;
    int gb_first = -1, gb_last = -1, light_first = -1;
    const u32 last_frame = frames - 1;
    for (u32 f = 0; f < frames; ++f) {
        for (u32 i = 0; i < infos[f].size(); ++i) {
            const DrawInfo& d = infos[f][i];
            const auto [it, added] = where.try_emplace({d.vs, d.ps}, sums.size());
            if (added) {
                sums.push_back({.vs = d.vs, .ps = d.ps});
            }
            Sum& s = sums[it->second];
            ++s.draws;
            s.phases |= d.phase;
            s.indirect = s.indirect || d.indirect;
            if (!d.indirect) {
                s.idx_min = std::min(s.idx_min, d.indices);
                s.idx_max = std::max(s.idx_max, d.indices);
                s.inst_max = std::max(s.inst_max, d.instances);
            }
            if (f == last_frame) {
                s.first = s.first < 0 ? int(i) : s.first;
                s.last = int(i);
                if (d.phase == R::Gbuffer) {
                    gb_first = gb_first < 0 ? int(i) : gb_first;
                    gb_last = int(i);
                } else if (d.phase == R::Light && light_first < 0) {
                    light_first = int(i);
                }
            }
            u32 changed = 0;
            if (d.probed) {
                ++probed;
                ++s.probed;
                const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
                changed = r[R::WordBox];
                s.box += changed;
                s.frame += r[R::WordFrame];
                s.box_max = std::max(s.box_max, changed);
                s.box_draws += changed != 0 ? 1u : 0u;
                for (u32 t = 0; t < R::Targets; ++t) {
                    s.by_target[t] += r[R::WordTarget0 + t];
                }
            } else if (d.skipped < skipped.size()) {
                ++skipped[d.skipped];
            }
            if (!s.rep || (!s.rep_changed && changed != 0)) {
                s.rep = &d;
                s.rep_changed = changed != 0;
            }
        }
    }
    // The owner maps: the last change of each box pixel over the probed frames.
    std::array<u32, R::OwnerMaps> owned{}, owner_pairs{};
    std::vector<std::array<bool, R::OwnerMaps>> owns(sums.size());
    for (u32 m = 0; m < R::OwnerMaps; ++m) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || f >= frames || n >= infos[f].size()) {
                continue;
            }
            const DrawInfo& d = infos[f][n];
            const std::size_t k = where[{d.vs, d.ps}];
            ++sums[k].own[m];
            ++owned[m];
            if (!owns[k][m]) {
                owns[k][m] = true;
                ++owner_pairs[m];
            }
        }
    }
    std::vector<std::size_t> order;
    for (std::size_t k = 0; k < sums.size(); ++k) {
        const Sum& s = sums[k];
        if (s.box != 0 || s.own[0] != 0 || s.own[1] != 0 || s.own[2] != 0) {
            order.push_back(k);
        }
    }
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        const Sum &x = sums[a], &y = sums[b];
        const u64 ox = u64(x.own[0]) + x.own[1] + x.own[2], oy = u64(y.own[0]) + y.own[1] + y.own[2];
        // owners first: full-screen passes change the whole box but own none of it
        return ox != oy ? ox > oy : x.box != y.box ? x.box > y.box : a < b;
    });
    char line[280];
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): box x %u-%u y %u-%u (%u px)%s of the %ux%u scene%s, %u frames, logged "
                  "%s; last frame: G-buffer draws #%d-%d, light draws from #%d",
                  box.x0, box.x1, box.y0, box.y1, box_px, box.cut ? " (cut)" : "", pixels_width, pixels_height,
                  capture_reduced ? " (reduced)" : "", frames,
                  gpu_done ? "after the GPU" : "BEFORE the GPU was done (counts may be short)", gb_first, gb_last,
                  light_first);
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): %u draws in the last frame (%u over the cap of %u), %u probed in %u "
                  "frames; not probed: %u lamps apart, %u not scene-sized, %u unreadable, %u left out, %u menu "
                  "preview, %u no view; %zu pairs changed the box",
                  u32(infos[last_frame].size()) + over_cap[last_frame], over_cap[last_frame], R::MaxDraws,
                  probed, frames, skipped[LampsApart], skipped[NotScene], skipped[Unreadable], skipped[LeftOut],
                  skipped[Preview], skipped[NoView], order.size());
    BbReport::Printf("%s\n", line);
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): last writer of each box pixel (a G-buffer albedo, s scene colour by "
                  "draws over 6 indices, z depth): a %u px by %u pairs, s %u by %u, z %u by %u; none: a %u, s %u, "
                  "z %u",
                  owned[0], owner_pairs[0], owned[1], owner_pairs[1], owned[2], owner_pairs[2], box_px - owned[0],
                  box_px - owned[1], box_px - owned[2]);
    BbReport::Printf("%s\n", line);
    BbReport::Printf("Blood pool probe (r100d): pair lines by own, then box: box px changed a frame, own = last writer, "
                     "frame~ px changed a frame, n draws a frame, p probed, #first-last draw in the last frame, "
                     "P pre-G-buffer G G-buffer B pre-light L light A after; cb:format/role+b blend=box px\n");
    static constexpr const char* PhaseLetters = "PGBLA";
    const u32 shown = std::min<u32>(u32(order.size()), R::MaxLines);
    u64 rest_px = 0;
    for (u32 rank = 0; rank < order.size(); ++rank) {
        const Sum& s = sums[order[rank]];
        if (rank >= shown) {
            rest_px += s.box;
            continue;
        }
        char phases[8] = {};
        for (u32 b = 0, n = 0; b < 5; ++b) {
            if ((s.phases >> b) & 1u) {
                phases[n++] = PhaseLetters[b];
            }
        }
        char idx[40];
        if (s.idx_max == 0 && s.indirect) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (s.idx_min == s.idx_max) {
            std::snprintf(idx, sizeof(idx), "%u%s", s.idx_max, s.indirect ? "+ind" : "");
        } else {
            std::snprintf(idx, sizeof(idx), "%u-%u%s", s.idx_min, s.idx_max, s.indirect ? "+ind" : "");
        }
        if (s.inst_max > 1) {
            const std::size_t used = std::strlen(idx);
            std::snprintf(idx + used, sizeof(idx) - used, "x%u", s.inst_max);
        }
        // The representative draw's targets: cb:format/role, +b blending, m<mask> a partial write
        // mask, =box pixels a frame where that target changed; then the depth.
        std::string targets;
        const DrawInfo& d = *s.rep;
        for (u32 cb = 0; cb < 8; ++cb) {
            if (((d.mrt >> cb) & 1u) == 0 || d.format[cb] == 0) {
                continue;
            }
            const char* name = ColourName(vk::Format(d.format[cb]));
            const u32 mask = (d.write_masks >> (4 * cb)) & 15u;
            char part[48];
            std::snprintf(part, sizeof(part), " %u:%s%s%s%s", cb, name ? name : "int",
                          d.role[cb] ? "/" : "", RoleNames[d.role[cb]], (d.blend >> cb) & 1u ? "+b" : "");
            targets += part;
            if (mask != 15u) {
                std::snprintf(part, sizeof(part), "m%x", mask);
                targets += part;
            }
            std::snprintf(part, sizeof(part), "=%llu", static_cast<unsigned long long>(s.by_target[cb] / frames));
            targets += part;
        }
        {
            char part[48];
            if (d.depth_test) {
                std::snprintf(part, sizeof(part), " d:%s %s%s=%llu", DepthName(vk::Format(d.depth_format)),
                              FuncNames[d.depth_func], d.depth_write ? " w" : "",
                              static_cast<unsigned long long>(s.by_target[R::DepthTarget] / frames));
            } else {
                std::snprintf(part, sizeof(part), " d:-");
            }
            targets += part;
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): %u/%zu %08llx:%08llx box %llu/f max %u own a%u s%u z%u "
                      "frame~%llu n%u/f p%u%s idx %s #%d-%d %s |%s",
                      rank + 1, order.size(), static_cast<unsigned long long>(s.vs),
                      static_cast<unsigned long long>(s.ps), static_cast<unsigned long long>(s.box / frames),
                      s.box_max, s.own[0], s.own[1], s.own[2],
                      static_cast<unsigned long long>(s.frame * R::Stride * R::Stride / frames), s.draws / frames,
                      s.probed, s.rep_changed ? "" : " (none)", idx, s.first, s.last, phases,
                      targets.c_str());
        BbReport::Printf("%s\n", line);
    }
    if (order.size() > shown) {
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): %zu more pairs changed the box (%llu px a frame together), not "
                      "listed",
                      order.size() - shown, static_cast<unsigned long long>(rest_px / frames));
        BbReport::Printf("%s\n", line);
    }
    // r100d: the self-check of the counts: every compared draw looked at the whole box and the
    // whole sample grid (r100c's b21 run had draws counting more changed box pixels than the box).
    {
        const u32 want_frame = grid_cols * grid_rows;
        u32 checked = 0, wrong_box = 0, wrong_frame = 0, over_box = 0;
        u32 first_box = 0, first_frame = 0, first_changed = 0;
        bool first = false;
        for (u32 f = 0; f < frames; ++f) {
            for (u32 i = 0; i < infos[f].size(); ++i) {
                if (!infos[f][i].probed) {
                    continue;
                }
                const u32* r = c + (std::size_t(f) * R::MaxDraws + i) * R::RecordWords;
                ++checked;
                const bool box_wrong = r[R::WordSeenBox] != box_px;
                const bool frame_wrong = r[R::WordSeenFrame] != want_frame;
                const bool over = r[R::WordBox] > box_px;
                wrong_box += box_wrong ? 1u : 0u;
                wrong_frame += frame_wrong ? 1u : 0u;
                over_box += over ? 1u : 0u;
                if (!first && (box_wrong || frame_wrong || over)) {
                    first = true;
                    first_box = r[R::WordSeenBox];
                    first_frame = r[R::WordSeenFrame];
                    first_changed = r[R::WordBox];
                }
            }
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): self-check, %u compared draws: %u saw other than the %u box px, "
                      "%u other than the %u samples, %u changed more box px than the box; %s (first: saw %u "
                      "box px, %u samples, changed %u)",
                      checked, wrong_box, box_px, wrong_frame, want_frame, over_box,
                      first ? "COUNTS WRONG" : "counts sound", first_box, first_frame, first_changed);
        BbReport::Printf("%s\n", line);
    }
    // r100d: the draws of the pair that owns the most box albedo, each draw on its own line (a decal
    // mesh drawn with the ground's shaders shows as one small draw owning the pool; the ground's
    // texture as the same large draw in the pool box and the control box).
    std::size_t top = sums.size();
    for (std::size_t k = 0; k < sums.size(); ++k) {
        if (sums[k].own[0] != 0 && (top == sums.size() || sums[k].own[0] > sums[top].own[0])) {
            top = k;
        }
    }
    if (top == sums.size()) {
        BbReport::Printf("Blood pool probe (r100d): draw lines: no pair owns box albedo\n");
        return;
    }
    const Sum& top_sum = sums[top];
    std::map<u32, std::array<u32, 2>> by_draw; // owner value: own a, own z
    for (u32 m = 0; m < R::OwnerMaps; m += 2) {
        for (u32 i = 0; i < box_px; ++i) {
            const u32 v = o[std::size_t(m) * box_px + i];
            const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
            if (v == 0 || f >= frames || n >= infos[f].size()) {
                continue;
            }
            const DrawInfo& d = infos[f][n];
            if (d.vs == top_sum.vs && d.ps == top_sum.ps) {
                ++by_draw[v][m == 0 ? 0 : 1];
            }
        }
    }
    std::vector<std::pair<u32, u32>> listed; // own a, owner value
    u32 listed_px = 0, owning = 0;
    for (const auto& [v, own] : by_draw) {
        owning += own[0] != 0 ? 1u : 0u;
        if (own[0] != 0 && u64(own[0]) * R::DrawLineShare >= box_px) {
            listed.emplace_back(own[0], v);
            listed_px += own[0];
        }
    }
    std::sort(listed.begin(), listed.end(), [](const auto& a, const auto& b) {
        return a.first != b.first ? a.first > b.first : a.second < b.second;
    });
    std::snprintf(line, sizeof(line),
                  "Blood pool probe (r100d): draws of %08llx:%08llx (own a%u of %u box px; %u draws a frame): %u "
                  "own albedo, %zu own at least 1/%u of the box (%u px); by own: f frame#draw, idx count, first "
                  "index @index buffer, textures address:WxH:format",
                  static_cast<unsigned long long>(top_sum.vs), static_cast<unsigned long long>(top_sum.ps),
                  top_sum.own[0], box_px, top_sum.draws / frames, owning, listed.size(), R::DrawLineShare, listed_px);
    BbReport::Printf("%s\n", line);
    for (std::size_t rank = 0; rank < listed.size() && rank < R::MaxDrawLines; ++rank) {
        const u32 v = listed[rank].second;
        const u32 f = (v >> R::OwnerFrameShift) - 1u, n = v & ((1u << R::OwnerFrameShift) - 1u);
        const DrawInfo& d = infos[f][n];
        const u32* r = c + (std::size_t(f) * R::MaxDraws + n) * R::RecordWords;
        char idx[64];
        if (d.indirect) {
            std::snprintf(idx, sizeof(idx), "indirect");
        } else if (!d.noted) {
            std::snprintf(idx, sizeof(idx), "%u first ? (no note)", d.indices);
        } else if (!d.indexed) {
            std::snprintf(idx, sizeof(idx), "%u (not indexed)", d.indices);
        } else {
            std::snprintf(idx, sizeof(idx), "%u first %u @%llx", d.indices, d.first_index,
                          static_cast<unsigned long long>(d.index_address));
        }
        if (d.instances > 1) {
            const std::size_t used = std::strlen(idx);
            std::snprintf(idx + used, sizeof(idx) - used, " x%u", d.instances);
        }
        std::string textures;
        for (u32 i = 0; i < d.texture_count; ++i) {
            char part[64];
            std::snprintf(part, sizeof(part), " %llx:%ux%u:%u",
                          static_cast<unsigned long long>(d.textures[i].address), d.textures[i].width,
                          d.textures[i].height, d.textures[i].format);
            textures += part;
        }
        std::snprintf(line, sizeof(line),
                      "Blood pool probe (r100d): draw %c f%u#%u own a%u z%u box %u frame~%llu idx %s tex %u h%08x%s",
                      char('A' + rank), f, n, by_draw[v][0], by_draw[v][1], d.probed ? r[R::WordBox] : 0u,
                      static_cast<unsigned long long>(u64(d.probed ? r[R::WordFrame] : 0u) * R::Stride * R::Stride),
                      idx, d.textures_all, d.texture_hash, textures.c_str());
        BbReport::Printf("%s\n", line);
    }
}

// bbport (r100d_blood-pool-draws, TOOL): once the draw's textures are bound (DrawRecord and
// DrawIndirectRecord, after BindResources and BeginRendering): its index range and textures, for the
// probe's draw lines. dc.bound_images lists the draw's colour targets, then its depth target, then
// every stage's images (as SparkProbeDraw reads it).
void Rasterizer::BloodPoolProbeNote(const GraphicsPipeline* pipeline, bool indirect, bool is_indexed,
                                    u32 index_offset) {
    const auto& dc = Dc();
    const auto& regs = Regs();
    const u32 mrt = u32(pipeline->GetGraphicsKey().mrt_mask);
    u32 own = db_desc.first ? 1u : 0u;
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        own += ((mrt >> cb) & 1u) != 0 && cb_descs[cb].first ? 1u : 0u;
    }
    std::array<BloodPoolProbe::Texture, BloodPoolProbeRules::DrawTextures> textures{};
    u32 count = 0;
    u64 hash = 0xcbf29ce484222325ull;
    for (std::size_t i = own; i < dc.bound_images.size(); ++i) {
        const auto& image = texture_cache.GetImage(dc.bound_images[i]);
        hash = (hash ^ image.info.guest_address) * 0x100000001b3ull;
        if (count < textures.size()) {
            textures[count++] = {.address = image.info.guest_address,
                                 .width = image.info.size.width,
                                 .height = image.info.size.height,
                                 .format = u32(image.info.pixel_format)};
        }
    }
    const bool indexed = is_indexed && !indirect;
    blood_pool_probe->Note(indexed, indexed ? regs.index_base_address.Address<VAddr>() : 0, indexed ? index_offset : 0,
                           textures, count,
                           u32(dc.bound_images.size() > own ? dc.bound_images.size() - own : 0),
                           u32(hash ^ (hash >> 32)));
}

// bbport (r100c_blood-pool-probe, TOOL): the probe's before-draw hook (direct and indirect draws).
void Rasterizer::BloodPoolProbeBefore(const GraphicsPipeline* pipeline, bool indirect, bool light) {
    static_assert(AmdGpu::NUM_COLOR_BUFFERS == 8);
    std::array<VideoCore::ImageId, 8> targets{};
    for (u32 cb = 0; cb < AmdGpu::NUM_COLOR_BUFFERS; ++cb) {
        targets[cb] = cb_descs[cb].first;
    }
    blood_pool_probe->BeforeDraw(Regs(), *pipeline, targets, db_desc.first, light, point_shadow->Pending(),
                                 indirect);
}

} // namespace Vulkan
