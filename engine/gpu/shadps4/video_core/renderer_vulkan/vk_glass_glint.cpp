// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r86b_glass-visible): the lamps' glints on the glass BB_RT_GLASS puts into the ray traced
// scene (vk_glass_glint.h; the knobs and the rules in glass_glint.h, the passes in
// host_shaders/glass_glint.comp).

#include "video_core/renderer_vulkan/vk_glass_glint.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "bbport_toggles.h"
// bbport (r86j_glint-same-game): the test tools' live knobs (branch dev/test-tools) when the build has them
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h"
#define BB_GLINT_LIVE 1
#else
#define BB_GLINT_LIVE 0
#endif
#include "video_core/host_shaders/glass_glint_coarse_comp.h"
#include "video_core/host_shaders/glass_glint_shade_comp.h"
#include "video_core/renderer_vulkan/rt_glass_light.h"
#include "video_core/renderer_vulkan/rt_glass_tri.h" // bbport (r86n_glint-aim-panes, TOOL)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
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
namespace BG = ::BbGlassGlint;
/// bbport (r86j_glint-same-game): the glint's strength now, negative for the test view; 0: off. With the live
/// knobs BB_GLASS_GLINT is asked again (a job's set:BB_GLASS_GLINT=0|1|show); the pipelines exist only when the
/// start value was above 0. Without them: the start value.
float LiveStrength([[maybe_unused]] const BG::Knobs& start) {
#if BB_GLINT_LIVE
    static BbLiveKnobs::Knob<float> knob{"BB_GLASS_GLINT", [](const char* text) { return BG::ParseLive(text); }};
    return knob.Get();
#else
    return start.show ? -start.strength : start.strength;
#endif
}
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u64 ProfileRow = 86; ///< EffectPass::Mark: the row "Lighting: glass glint"
constexpr vk::DeviceSize SlotBytes = BG::SlotWords * sizeof(u32);
/// The counters, then a data block a slot (glass_glint_layout.h).
constexpr vk::DeviceSize BufferBytes =
    BG::Slots * SlotBytes + BG::Slots * BG::DataWords * sizeof(u32) +
    BG::Slots * BG::DbgWords * sizeof(u32); // bbport (r86e_glint-hit-distance): the raw-value area
static_assert(BufferBytes == 27648); // 16 x 24 + 16 x 84 + 16 x 324 words (r86e)

/// bbport (r86e_glint-hit-distance): the raw-value records of a slot (log lines "(r86e)"): the pane
/// draw and the camera the pass had, the pane-pixel records, and with `grid` the 12 fixed blocks.
void PrintSlot(const u32* words, u32 slot, bool grid) {
    const u32* data = words + BG::Slots * BG::SlotWords + slot * BG::DataWords;
    const u32* dbg =
        words + BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords + slot * BG::DbgWords;
    const auto flt = [](u32 w) { return std::bit_cast<float>(w); };
    float v[12];
    std::memcpy(v, data + BG::DataView, sizeof(v));
    // world = R^T (view - t), the pass camera's view matrix being world to view (3x4, rows)
    const auto world = [&v](float x, float y, float z, float* out) {
        for (int c = 0; c < 3; ++c) {
            out[c] = v[c] * (x - v[3]) + v[4 + c] * (y - v[7]) + v[8 + c] * (z - v[11]);
        }
    };
    float cam[3];
    world(0.0f, 0.0f, 0.0f, cam);
    const u64 vs = u64(data[BG::DataDraw]) | (u64(data[BG::DataDraw + 1]) << 32);
    const u64 ps = u64(data[BG::DataDraw + 2]) | (u64(data[BG::DataDraw + 3]) << 32);
    BbReport::Printf("Ray tracing glass glint (r86e): a pass (slot %u): pane draw %llx:%llx, %u indices, %u "
                     "instances; camera in the world (%.2f %.2f %.2f); pane pixels sampled %u (every 211th "
                     "pixel on a pane, the first %u shown); depth 'raw' is the depth buffer's value (sky 1)\n",
                     slot, static_cast<unsigned long long>(vs), static_cast<unsigned long long>(ps),
                     data[BG::DataDraw + 4], data[BG::DataDraw + 5], double(cam[0]), double(cam[1]),
                     double(cam[2]), dbg[0], BG::DbgPaneMax);
    const u32 records = BG::DbgPaneMax + (grid ? BG::DbgGridMax : 0u);
    for (u32 i = 0; i < records; ++i) {
        const u32* r = dbg + BG::DbgFirst + i * BG::DbgRecord;
        if (r[0] == 0) {
            continue;
        }
        float hit[3], lamp[3];
        world(flt(r[8]), flt(r[9]), flt(r[10]), hit);
        world(flt(r[11]), flt(r[12]), flt(r[13]), lamp);
        BbReport::Printf(
            "Ray tracing glass glint (r86e):   %s px (%u,%u): raw depth %.7f, depth distance %.2f m at view "
            "(%.2f %.2f %.2f); pane t %.2f m (-1: none) at view (%.2f %.2f %.2f) world (%.2f %.2f %.2f); "
            "nearest lamp %.2f m away (-1: none), reach %.1f, view (%.2f %.2f %.2f) world (%.2f %.2f %.2f)\n",
            r[0] == 1 ? "pane pixel" : "grid block", r[1] & 0xFFFFu, r[1] >> 16, double(flt(r[2])),
            double(flt(r[3])), double(flt(r[4])), double(flt(r[5])), double(flt(r[6])), double(flt(r[7])),
            double(flt(r[8])), double(flt(r[9])), double(flt(r[10])), double(hit[0]), double(hit[1]),
            double(hit[2]), double(flt(r[14])), double(flt(r[15])), double(flt(r[11])), double(flt(r[12])),
            double(flt(r[13])), double(lamp[0]), double(lamp[1]), double(lamp[2]));
    }
}

/// The records of the slots that are long done: up to two passes that sampled pane pixels (else the
/// first with grid blocks), the grid shown with the first. Only the 4 oldest slots (15 to 12 passes,
/// at MaxPasses 2 a frame 6 frames or more ago), so no slot still in flight on the GPU is read.
void PrintSamples(const u32* words, u64 passes) {
    if (words == nullptr || passes < BG::Slots) {
        return;
    }
    u32 chosen[2] = {0, 0};
    u32 count = 0, grid_slot = BG::Slots;
    for (u32 k = 1; k <= 4; ++k) {
        const u32 slot = u32((passes + k) % BG::Slots);
        const u32* dbg =
            words + BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords + slot * BG::DbgWords;
        if (dbg[0] != 0 && count < 2) {
            chosen[count++] = slot;
        }
        if (grid_slot == BG::Slots && dbg[BG::DbgFirst + BG::DbgPaneMax * BG::DbgRecord] != 0) {
            grid_slot = slot;
        }
    }
    if (count == 0 && grid_slot != BG::Slots) {
        chosen[count++] = grid_slot;
    }
    for (u32 i = 0; i < count; ++i) {
        PrintSlot(words, chosen[i], i == 0);
    }
}
} // namespace

bool GlassGlint::Wanted() {
    static const bool wanted = [] {
        const BG::Knobs& k = BG::Load();
        const char* text = std::getenv("BB_GLASS_GLINT");
        if (k.unreadable) {
            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s is neither a number "
                        "nor show: off\n",
                        text);
        } else if (text != nullptr && text[0] != 0 && !(k.strength > 0.0f)) {
            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: off\n", text);
        } else if (k.strength > 0.0f && !RtGlassOn()) {
            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: off, needs "
                        "BB_RT_GLASS (off)\n",
                        text);
        }
        if (k.sharp_unreadable) {
            std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT_SHARP=%.16s is not a whole "
                        "number: %u\n",
                        std::getenv("BB_GLASS_GLINT_SHARP"), k.sharp);
        }
        return BG::On();
    }();
    return wanted;
}

GlassGlint::GlassGlint(const Instance& instance_, Scheduler& scheduler_,
                       VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                       SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                       RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, rt_shadow{rt_shadow_},
      knobs{BG::Load()} {
    using enum vk::DescriptorType;
    // The pipelines and the counters are made here, at the start (no compile in play).
    made = instance.IsRayQuerySupported() &&
           EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, coarse.set_layout, coarse.layout, coarse.pipeline,
                              {eAccelerationStructureKHR, eSampledImage, eStorageImage,
                               eStorageBuffer, eStorageBuffer},
                              sizeof(BG::Push), GLASS_GLINT_COARSE_COMP, "Glass glint coarse") &&
           EffectPass::Create(instance, shade.set_layout, shade.layout, shade.pipeline,
                              {eAccelerationStructureKHR, eSampledImage, eStorageImage,
                               eStorageBuffer, eStorageBuffer},
                              sizeof(BG::Push), GLASS_GLINT_SHADE_COMP, "Glass glint shade");
    if (made) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = BufferBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo alloc_ci{};
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer raw{};
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw,
                            &counters.allocation, &info) == VK_SUCCESS) {
            counters.buffer = raw;
            counters.mapped = info.pMappedData;
        }
        made = counters.mapped != nullptr;
        if (made) {
            std::memset(counters.mapped, 0, BufferBytes);
        }
    }
    const char* text = std::getenv("BB_GLASS_GLINT");
    std::printf("Ray tracing glass glint (r86b): BB_GLASS_GLINT=%.16s: %s, strength %.2f, sharp %u, "
                "lamps up to %u, carry %s, needs BB_RT_GLASS (%s)\n",
                text ? text : "", made ? (knobs.show ? "on, test view" : "on")
                                       : "off - the passes could not be made",
                double(knobs.strength), knobs.sharp, BG::MaxLamps,
                RtGlassCarryOn() ? "on" : "off", RtGlassOn() ? "on" : "off");
    // bbport (r86j_glint-same-game): the line the slot runner keeps
    std::printf("GLINT-PROOF glint made: %s, start strength %.2f, live setting BB_GLASS_GLINT %s\n",
                made ? "yes" : "no (the passes could not be made)", double(knobs.strength),
                BB_GLINT_LIVE ? "read again every frame (the test tools' live knobs)" : "read once");
}

GlassGlint::~GlassGlint() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
    if (work.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), work.buffer, work.allocation);
    }
}

void GlassGlint::AddLights(const u32* records, u32 count) {
    lights.Add(records, count);
}

void GlassGlint::ClearLights() {
    lights.Clear();
}

vk::ImageView GlassGlint::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid &&
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
        .aspect = aspect,
        .view = Check<"create glass glint view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool GlassGlint::EnsureWork(vk::DeviceSize bytes) {
    if (work.buffer && work_bytes >= bytes) {
        return true;
    }
    if (work.buffer) {
        scheduler.DeferOperation([allocator = instance.GetAllocator(), buffer = work.buffer,
                                  allocation = work.allocation] {
            vmaDestroyBuffer(allocator, buffer, allocation);
        });
        work = {};
        work_bytes = 0;
    }
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = bytes,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{};
    alloc_ci.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
    VkBuffer raw{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &work.allocation,
                        nullptr) != VK_SUCCESS) {
        work = {};
        return false;
    }
    work.buffer = raw;
    work_bytes = bytes;
    return true;
}

void GlassGlint::Count(BG::Skip skip) {
    switch (skip) {
    case BG::Skip::NoPane:
        ++stats.no_pane;
        break;
    case BG::Skip::OtherCamera:
        ++stats.other_camera;
        break;
    case BG::Skip::NoLamps:
        ++stats.no_lamps;
        break;
    case BG::Skip::LampsOpen:
        ++stats.lamps_open;
        break;
    case BG::Skip::Shape:
        ++stats.shape;
        break;
    case BG::Skip::Cap:
        ++stats.cap;
        break;
    case BG::Skip::None:
        break;
    }
}

void GlassGlint::AfterGlassDraw(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                                std::array<float, 2> jitter, bool lamps_open,
                                const BG::PaneDraw& pane) {
    // bbport (r86j_glint-same-game): the live switch first; off: a counter and nothing else
    const float live = LiveStrength(knobs);
    if (!(live != 0.0f)) {
        ++stats.gate_off;
        return;
    }
    ++stats.glass_draws;
    // bbport (r86c_glass-glint-visible): the cap first, before the camera, the lamps or any image
    // lookup: a draw it leaves out costs a few compares (Decide asks it first too).
    const bool depth_done = std::find(frame_depths.begin(), frame_depths.begin() + frame_passes,
                                      depth_id) != frame_depths.begin() + frame_passes;
    if (BG::Capped(frame_passes, depth_done)) {
        ++stats.cap;
        return;
    }
    // The gate, in glass_glint.h's order (Decide names the first reason that holds).
    const RtShadow::GlassSceneView glass = rt_shadow.GlassScene();
    const vk::AccelerationStructureKHR tlas = rt_shadow.Scene();
    const auto camera = camera_motion.PassMatrices();
    BG::Gate gate{};
    gate.panes = made && glass.instances > 0 && bool(tlas);
    gate.this_frame = glass.this_frame;
    // A menu's preview frame (several G-buffer passes, not the world) counts as another camera.
    gate.same_camera = camera.valid && !camera_motion.PreviewFrame() &&
                       BG::SameCamera(glass.view, camera.view);
    BG::Picked picked{};
    if (gate.panes && gate.this_frame && gate.same_camera) {
        picked = BG::PickLamps(lights.Lights());
        gate.lamps = picked.count > 0;
    }
    gate.lamps_open = lamps_open;
    VideoCore::Image* color = nullptr;
    VideoCore::Image* depth = nullptr;
    u32 width = 0, height = 0;
    if (gate.lamps && !lamps_open && color_id && depth_id) {
        color = &texture_cache.GetImage(color_id);
        depth = &texture_cache.GetImage(depth_id);
        width = color->info.size.width;
        height = color->info.size.height;
        // The game's render size (its targets may be allocated larger).
        if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
            width = std::min(width, render[0]);
            height = std::min(height, render[1]);
        }
        gate.shape = color->info.pixel_format == vk::Format::eR16G16B16A16Sfloat &&
                     bool(color->usage_flags & vk::ImageUsageFlagBits::eStorage) &&
                     color->info.size.width == depth->info.size.width &&
                     color->info.size.height == depth->info.size.height &&
                     !(scene_targets.Reduced() && scene_targets.EligibleScene(*color)) &&
                     width >= 16 && height >= 16;
    }
    gate.passes = frame_passes;
    gate.depth_done = depth_done; // false here: a capped draw returned above
    const BG::Skip skip = BG::Decide(gate);
    const u32 blocks_x = BG::BlocksOf(width), blocks_y = BG::BlocksOf(height);
    const vk::DeviceSize work_size = vk::DeviceSize(blocks_x) * blocks_y * sizeof(u32);
    if (skip != BG::Skip::None || !EnsureWork(work_size)) {
        Count(skip != BG::Skip::None ? skip : BG::Skip::Shape);
        return;
    }
    // The pass reads the camera depth: with a lamps-apart batch open it was skipped above
    // (lamps open), so no batch is ended here.
    const SceneUseScope scene_use{"glass glint"};
    scheduler.EndRendering();
    const vk::ImageView color_view = CachedView(*color, vk::ImageAspectFlagBits::eColor);
    const vk::ImageView depth_view = CachedView(*depth, vk::ImageAspectFlagBits::eDepth);
    runtime.Transit(color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
    runtime.Transit(depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
    runtime.FlushBarriers();
    scheduler.EndRendering();

    const u32 slot = u32(passes % BG::Slots);
    u32* const words = static_cast<u32*>(counters.mapped);
    // The counts of the pass Slots - 1 before this one (its work is long done; the slot is
    // cleared on the GPU before its next use, the next pass).
    if (passes + 1 >= BG::Slots) {
        const u32* done = words + ((passes + 1) % BG::Slots) * BG::SlotWords;
        for (u32 i = 0; i < BG::CounterWords; ++i) {
            if (i == GLASS_GLINT_W_MAX_ADD) {
                stats.max_add = std::max(stats.max_add, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_BEST_MAX) { // bbport (r86c_glass-glint-visible)
                stats.best_max = std::max(stats.best_max, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_NH_MAX) {
                stats.nh_max = std::max(stats.nh_max, std::bit_cast<float>(done[i]));
            } else if (i == GLASS_GLINT_W_DIST_MIN) {
                stats.dist_stored = std::max(stats.dist_stored, done[i]);
            } else {
                stats.words[i] += done[i];
            }
        }
        ++stats.read;
    }
    // This slot's lamps (the slot's last reader, Slots passes ago, is long done).
    u32* const data = words + BG::Slots * BG::SlotWords + slot * BG::DataWords;
    std::memset(data, 0, BG::DataWords * sizeof(u32));
    data[BG::DataCount] = picked.count;
    // bbport (r86e_glint-hit-distance): the pane draw and the camera of this pass, for the log
    data[BG::DataDraw] = u32(pane.vs);
    data[BG::DataDraw + 1] = u32(pane.vs >> 32);
    data[BG::DataDraw + 2] = u32(pane.ps);
    data[BG::DataDraw + 3] = u32(pane.ps >> 32);
    data[BG::DataDraw + 4] = pane.indices;
    data[BG::DataDraw + 5] = pane.instances;
    std::memcpy(&data[BG::DataView], camera.view.data(), sizeof(camera.view));
    for (u32 k = 0; k < picked.count; ++k) {
        const auto lamp = BG::Words(picked.lamps[k]);
        std::memcpy(&data[BG::DataLamps + k * BG::LampWords], lamp.data(), sizeof(lamp));
    }
    BG::Push push{};
    push.proj = camera.proj;
    push.frame = {float(width), float(height), jitter[0], jitter[1]};
    push.info = {blocks_x, blocks_y, slot, live < 0.0f ? BG::FlagShow : 0u}; // bbport (r86j): the live value
    push.params = {live < 0.0f ? -live : live, float(knobs.sharp), BG::Normalisation(float(knobs.sharp)), 0.0f};

    frame_depths[frame_passes++] = depth_id;
    ++passes;
    ++stats.passes;
    stats.lamps += picked.count;
    if (RtGlassTri::LampLinesPending()) { // bbport (r86n_glint-aim-panes, TOOL): N.H and the term of every lamp for the pane just cut
        std::array<RtGlassTri::LampIn, ::BbGlassGlint::MaxLamps> in{};
        for (u32 k = 0; k < picked.count; ++k) {
            const BG::Lamp& lamp = picked.lamps[k];
            in[k] = {lamp.view[0], lamp.view[1], lamp.view[2], lamp.reach,
                     std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]})};
        }
        RtGlassTri::NoteLampTerms(camera.view, in.data(), picked.count, float(knobs.sharp), live < 0.0f ? -live : live,
                                  [](float d, float reach, float nl, float nh, float vh, float n) {
                                      return BG::Term(d, reach, nl, nh, vh, n);
                                  });
    }
    for (u32 k = 0; k < picked.count; ++k) { // bbport (r86c_glass-glint-visible): the lamps as pushed
        const BG::Lamp& lamp = picked.lamps[k];
        stats.lamp_colour_max =
            std::max(stats.lamp_colour_max, std::max({lamp.colour[0], lamp.colour[1], lamp.colour[2]}));
        stats.reach_min = stats.reach_min > 0.0f ? std::min(stats.reach_min, lamp.reach) : lamp.reach;
        stats.reach_max = std::max(stats.reach_max, lamp.reach);
    }
    if (first_pass_frame == 0) {
        first_pass_frame = u64(BbStats::frame_number.load(std::memory_order_relaxed)) + 1;
    }
    if (!told_first) {
        told_first = true;
        std::printf("Ray tracing glass glint (r86b): first pass: %u pane records, %u lamps, scene "
                    "%ux%u, %ux%u blocks\n",
                    glass.instances, picked.count, width, height, blocks_x, blocks_y);
    }
    // Pinned: a row this cheap falls under BB_GPU_PROFILE_ROWS' cut (30 rows) and the cost run
    // would not show it.
    EffectPass::Mark(ProfileRow, "glass glint", true);
    scheduler.RecordCrumb(
        {.name = "glass glint"},
        [push, width, height, blocks_x, blocks_y, tlas, color_view, depth_view, work_size,
         counter_buffer = counters.buffer, work_buffer = work.buffer,
         coarse_pipeline = *coarse.pipeline, coarse_layout = *coarse.layout,
         shade_pipeline = *shade.pipeline, shade_layout = *shade.layout](vk::CommandBuffer cmdbuf) {
            using enum vk::DescriptorType;
            cmdbuf.fillBuffer(counter_buffer, push.info[2] * SlotBytes, SlotBytes, 0);
            // bbport (r86e_glint-hit-distance): the slot's raw-value records, cleared with its counters
            cmdbuf.fillBuffer(counter_buffer,
                              (BG::Slots * BG::SlotWords + BG::Slots * BG::DataWords +
                               push.info[2] * BG::DbgWords) * sizeof(u32),
                              BG::DbgWords * sizeof(u32), 0);
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
            const vk::DescriptorImageInfo depth_info{{}, depth_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo color_info{{}, color_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo work_info{work_buffer, 0, work_size};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, BufferBytes};
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = eSampledImage, .pImageInfo = &depth_info},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = eStorageImage, .pImageInfo = &color_info},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer, .pBufferInfo = &work_info},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1,
                                       .descriptorType = eStorageBuffer,
                                       .pBufferInfo = &counter_info},
            };
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout, u32 x, u32 y) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch(x, y, 1);
            };
            // COARSE a thread a block; SHADE a group an 8x8 pixel tile (in the quad mode the
            // groups past the 16x16 tiles return at once).
            run(coarse_pipeline, coarse_layout, BG::GroupsOf(blocks_x), BG::GroupsOf(blocks_y));
            EffectPass::ComputeBarrier(cmdbuf);
            run(shade_pipeline, shade_layout, BG::GroupsOf(width), BG::GroupsOf(height));
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands | Host, MemoryAll | vk::AccessFlagBits2::eHostRead);
        });
}

void GlassGlint::OnFrameEnd() {
    // bbport (r86j_glint-same-game): a change of the live setting: what the old setting did, then the new one
    if (const float live = LiveStrength(knobs); live != gate_last) {
        if (gate_last != -2.0f && stats.frames > 0) {
            Report();
        }
        std::printf("GLINT-PROOF gate: BB_GLASS_GLINT now %s (strength %.2f) at frame %llu\n",
                    live < 0.0f ? "show" : live > 0.0f ? "on" : "off", double(live < 0.0f ? -live : live),
                    static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)));
        gate_last = live;
    }
    frame_passes = 0;
    frame_depths = {};
    lights.Clear();
    if (++stats.frames >= LineFrames) {
        Report();
    }
}

void GlassGlint::Report() {
    const double reads = std::max(1.0, double(stats.read));
    const auto per = [&](u32 word) { return double(stats.words[word]) / reads; };
    char first[24] = "-";
    if (first_pass_frame != 0) {
        std::snprintf(first, sizeof(first), "%llu", (unsigned long long)(first_pass_frame - 1));
    }
    BbReport::Printf(
        "Ray tracing glass glint (r86b): %u frames, %u draws, %u passes (first at %s); skipped "
        "%u no pane, %u camera, %u no lamps, %u lamps open, %u shape, %u cap; a pass: blocks "
        "%.0f/%.0f, glass px %.0f, depth-rejected %.0f, glint px %.0f, shadowed %.0f/%.0f, max add "
        "%.2f, lamps %.1f\n",
        stats.frames, stats.glass_draws, stats.passes, first, stats.no_pane, stats.other_camera,
        stats.no_lamps, stats.lamps_open, stats.shape, stats.cap, per(GLASS_GLINT_W_FLAGGED),
        per(GLASS_GLINT_W_BLOCKS), per(GLASS_GLINT_W_GLASS), per(GLASS_GLINT_W_REJECTED),
        per(GLASS_GLINT_W_GLINT), per(GLASS_GLINT_W_SHADOWED), per(GLASS_GLINT_W_SHADOW_RAYS),
        double(stats.max_add), double(stats.lamps) / std::max(1.0, double(stats.passes)));
    // bbport (r86c_glass-glint-visible): the second line: what the glass is and how far the lamps are
    const double units = std::max(1.0, double(stats.words[GLASS_GLINT_W_UNITS]));
    const double pairs = std::max(1.0, double(stats.words[GLASS_GLINT_W_PAIRS]));
    char nearest[16] = "-";
    if (const float metres = BG::DistMinMetres(stats.dist_stored); metres >= 0.0f) {
        std::snprintf(nearest, sizeof(nearest), "%.2f", double(metres));
    }
    BbReport::Printf(
        "Ray tracing glass glint (r86c): a pass: pane points %.0f (%.2f m away, %.0f without a "
        "normal, %.0f curved); lamp pairs in reach %.0f, facing %.0f, lamp-to-pane distance min %s m "
        "mean %.2f m, highest N.H %.3f, brightest term %.4f (before the strength and the 1/255 "
        "shadow test); lamps as pushed: colour up to %.2f, reach %.1f to %.1f m\n",
        per(GLASS_GLINT_W_UNITS), double(stats.words[GLASS_GLINT_W_T_SUM]) / units * 0.01,
        per(GLASS_GLINT_W_NO_NORMAL), per(GLASS_GLINT_W_CURVED), per(GLASS_GLINT_W_PAIRS),
        per(GLASS_GLINT_W_FACING), nearest,
        double(stats.words[GLASS_GLINT_W_DIST_SUM]) / pairs * 0.01, double(stats.nh_max),
        double(stats.best_max), double(stats.lamp_colour_max), double(stats.reach_min),
        double(stats.reach_max));
    // bbport (r86d_glint-pane-depth): the third line: what the depth says under the pane points
    BbReport::Printf("Ray tracing glass glint (r86d): a pass: pane points %.0f, %.1f m away on average "
                     "(each put into 1000 m), %.0f of them where the depth is the sky, %.0f "
                     "nearer than 50 m\n",
                     per(GLASS_GLINT_W_UNITS), double(stats.words[GLASS_GLINT_W_FAR_SUM]) / units,
                     per(GLASS_GLINT_W_SKY), per(GLASS_GLINT_W_NEAR));
    // bbport (r86e_glint-hit-distance): the raw values of the oldest passes still held
    // bbport (r86j_glint-same-game): the line the slot runner keeps, the chain's last link in one place
    std::printf("GLINT-PROOF glint: %u frames, %u pane draws asked, %u of them while the setting was off, %u passes (skipped %u no pane, %u other camera, %u no lamps, %u lamps open, %u shape, %u cap); a pass: pane points %.0f (%.2f m away), glass px %.0f, lamp pairs in reach %.0f, facing %.0f, glint px %.0f, max add %.2f, lamps %.1f\n",
                stats.frames, stats.glass_draws, stats.gate_off, stats.passes, stats.no_pane, stats.other_camera,
                stats.no_lamps, stats.lamps_open, stats.shape, stats.cap, per(GLASS_GLINT_W_UNITS),
                double(stats.words[GLASS_GLINT_W_T_SUM]) / units * 0.01, per(GLASS_GLINT_W_GLASS),
                per(GLASS_GLINT_W_PAIRS), per(GLASS_GLINT_W_FACING), per(GLASS_GLINT_W_GLINT), double(stats.max_add),
                double(stats.lamps) / std::max(1.0, double(stats.passes)));
    PrintSamples(static_cast<const u32*>(counters.mapped), passes);
    stats = {};
}

} // namespace Vulkan
