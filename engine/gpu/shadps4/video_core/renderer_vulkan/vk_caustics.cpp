// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r107_caustics): water caustics from the sun or moon (vk_caustics.h; the knob and the
// numbers in caustics_params.h, the pass in host_shaders/caustics.comp).

#include "video_core/renderer_vulkan/vk_caustics.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

#include "bbport_settings.h" // bbport (r107c_caustics-lamp-gain): the game's lamp curve
#include "bbport_toggles.h"
#include "video_core/host_shaders/caustics_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_local_falloff.h" // r107c
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/volumetric_area_gate.h" // bbport (r107b_caustics-visible)
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
namespace BC = ::BbCaustics;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageBuffer = vk::DescriptorType::eStorageBuffer;
constexpr u32 LineCalls = 600;
constexpr u32 FirstLineCalls = 120; ///< the first line comes sooner, for short test runs
constexpr u64 ProfileRow = 107;     ///< EffectPass::Mark: the row "Lighting: water caustics"
constexpr vk::DeviceSize SlotBytes = BC::SlotWords * sizeof(u32);
constexpr vk::DeviceSize CounterBytes = BC::Slots * SlotBytes;
/// bbport (r107b_caustics-visible): the counters, then a data block a slot (caustics_layout.h).
constexpr vk::DeviceSize BufferBytes = CounterBytes + BC::Slots * BC::DataWords * sizeof(u32);
/// bbport (r107f_caustics-world-anchored): the world map (caustics_layout.h): one word a cell.
constexpr vk::DeviceSize WorldBytes = BC::MapWords * sizeof(u32);

/// BB_CAUSTICS and BB_CAUSTICS_LAMPS, read once (the first caller: Wanted, at the rasterizer's
/// start). Set to something that is off, it says so.
const BC::Knobs& ReadKnobs() {
    static const BC::Knobs knobs = [] {
        const char* value = std::getenv("BB_CAUSTICS");
        BC::Knobs read = BC::Parse(value, std::getenv("BB_CAUSTICS_LAMPS"));
        read.world = BC::WorldOf(std::getenv("BB_CAUSTICS_WORLD")); // r107f
        if (read.unreadable) {
            std::printf("Water caustics (r107): BB_CAUSTICS=%.16s is neither a number nor show: off\n",
                        value);
        } else if (value != nullptr && value[0] != 0 && !(read.strength > 0.0f)) {
            std::printf("Water caustics (r107): BB_CAUSTICS=%.16s: off\n", value);
        }
        const char* lamps = std::getenv("BB_CAUSTICS_LAMPS");
        if (read.lamps_unreadable) {
            std::printf("Water caustics (r107b): BB_CAUSTICS_LAMPS=%.16s is neither a number nor "
                        "show: off\n",
                        lamps);
        } else if (lamps != nullptr && lamps[0] != 0 && !(read.lamp_strength > 0.0f)) {
            std::printf("Water caustics (r107b): BB_CAUSTICS_LAMPS=%.16s: off\n", lamps);
        }
        return read;
    }();
    return knobs;
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}

/// Four 8-bit channels (the game's screen shadow target, the G-buffer's material target).
bool FourBytes(const VideoCore::Image& image) {
    const auto f = image.info.pixel_format;
    return f == vk::Format::eR8G8B8A8Unorm || f == vk::Format::eB8G8R8A8Unorm ||
           f == vk::Format::eA8B8G8R8UnormPack32;
}
} // namespace

bool Caustics::Wanted() {
    return ReadKnobs().strength > 0.0f || ReadKnobs().lamp_strength > 0.0f;
}

Caustics::Caustics(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                   PointShadow& point_shadow_, bool upscaler_on)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, point_shadow{point_shadow_},
      knobs{ReadKnobs()} {
    // The pipeline and the counters are made here, at the start (no compile in play).
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, set_layout, layout, pipeline,
                              {StorageImage, SampledImage, SampledImage, SampledImage, StorageBuffer,
                               SampledImage, SampledImage, StorageBuffer},
                              sizeof(BC::Push), CAUSTICS_COMP, "Water caustics");
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
    if (made && knobs.world > 0.0f && knobs.lamp_strength > 0.0f) {
        // bbport (r107f_caustics-world-anchored): the world map, device local; the first dispatch
        // that uses it clears it. Without it the knob does nothing (the log says so).
        const VkBufferCreateInfo map_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = WorldBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT,
        };
        VmaAllocationCreateInfo map_alloc{};
        map_alloc.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
        VkBuffer map_raw{};
        if (vmaCreateBuffer(instance.GetAllocator(), &map_ci, &map_alloc, &map_raw,
                            &world_map.allocation, nullptr) == VK_SUCCESS) {
            world_map.buffer = map_raw;
        }
    }
    std::printf("Water caustics (r107b, BB_CAUSTICS=%s%.2f, LAMPS=%.2f): %s; gain %.2f, lamps %.2f, "
                "test view %s; the light of the sun or moon (where the light set has it) and of up "
                "to %u lamps a water plane reflects (the game's mirrored passes), as a moving net\n",
                knobs.show ? "show, " : "", double(knobs.strength), double(knobs.lamp_strength),
                made ? "on" : "off - the pass could not be made", double(BC::GainOf(knobs)),
                double(BC::LampGainOf(knobs)), knobs.show ? "on" : "off", BC::MaxLamps);
    if (knobs.world > 0.0f) {
        std::printf("Water caustics (r107f, BB_CAUSTICS_WORLD=%.2f): %s; a world map of what the water is "
                    "(%u x %u cells of %.2f m, %u KB), the lamps kept from pass to pass, the lamps' light "
                    "on the bed under a mirrored plane's water, puddles that ripple\n",
                    double(knobs.world),
                    world_map.buffer ? "on"
                                     : "off - it needs BB_CAUSTICS_LAMPS and the pass made, and the map did not fit",
                    unsigned(CAUSTICS_MAP_SIZE), unsigned(CAUSTICS_MAP_SIZE), 1.0 / CAUSTICS_MAP_CELLS_PER_M,
                    unsigned(WorldBytes / 1024));
    }
    if (!upscaler_on) {
        std::printf("Water caustics (r107): not drawn - the upscaler is not available (BB_UPSCALER=none, "
                    "or this GPU cannot run it), and the pass runs at its first blended draw\n");
    }
}

Caustics::~Caustics() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (world_map.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), world_map.buffer, world_map.allocation); // r107f
    }
    if (counters.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), counters.buffer, counters.allocation);
    }
}

void Caustics::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId material,
                             VideoCore::ImageId albedo, VideoCore::ImageId records) {
    gbuffer_depth = depth;
    gbuffer_material = material;
    gbuffer_albedo = albedo;
    gbuffer_records = records;
    lamps.Clear(); // r107b: the lamps of this pass only (they are in its view space)
    armed = armed || depth != applied_depth ||
            BbStats::frame_number.load(std::memory_order_relaxed) != applied_frame;
}

void Caustics::OnShadowResolve(VideoCore::ImageId target, const std::array<float, 3>& toward,
                               bool valid) {
    std::array<float, 3> unit{};
    const bool above = valid && BC::SunUsable(toward, unit);
    if (valid) {
        last_sun_y = unit[1];
    }
    shadow_target = target;
    sun = unit;
    sun_valid = above;
    resolved = true;
}

// bbport (r107b_caustics-visible)
void Caustics::AddLights(const u32* records, u32 count) {
    if (knobs.lamp_strength > 0.0f) {
        lamps.Add(records, count);
    }
}

// bbport (r107b_caustics-visible): the r81 area gate's rule (volumetric_area_gate.h): a set has the
// sun when its light 0 is at least half as bright (weight 0.5 or more) as the brightest set's;
// the white fallback set counts as without sun (fail closed: no sun indoors).
void Caustics::OnLightSets(const float* table, u32 floats, VAddr texture0) {
    namespace AG = VolumetricAreaGate;
    const u32 count = std::min(floats / AG::RecordFloats, AG::Records);
    float best = 0.0f, best_raw = 0.0f;
    for (u32 i = 0; i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (!AG::IsFallback(set)) {
            best = std::max(best, AG::SunLuminance(set + AG::RecordColour));
            best_raw = std::max(best_raw, AG::RawLuminance(set + AG::RecordColour));
        }
    }
    sun_mask = {};
    sets_sunny = 0;
    for (u32 i = 0; best > 0.0f && i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (!AG::IsFallback(set) &&
            AG::SunWeight(AG::SunLuminance(set + AG::RecordColour), best) >= 0.5f) {
            sun_mask[i >> 5] |= 1u << (i & 31u);
            ++sets_sunny;
        }
    }
    sets_count = count;
    sets_best = best_raw;
    sets_address = texture0;
    sets_fresh = true;
}

vk::ImageView Caustics::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create water caustics view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void Caustics::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter, const std::array<float, 3>& wind) {
    // Once after each G-buffer pass: the rasterizer calls at every blended draw of the scene.
    if (!armed) {
        return;
    }
    armed = false;
    applied_depth = gbuffer_depth;
    applied_frame = BbStats::frame_number.load(std::memory_order_relaxed);
    ++stats.calls;
    // Real time (clamped steps), so the pattern drifts at its speed at any frame rate.
    const auto now = std::chrono::steady_clock::now();
    drift.Advance(std::chrono::duration<double>(now - last_time).count(), wind);
    last_time = now;
    const auto done = [&] {
        if (stats.calls >= (reported ? LineCalls : FirstLineCalls)) {
            reported = true;
            Report();
        }
    };
    if (!made || !color_id || !depth_id) {
        done();
        return;
    }
    float plane_y = 0.0f;
    const bool plane = camera_motion.MirrorPlane(plane_y) && std::isfinite(plane_y);
    const auto camera = camera_motion.PassMatrices();
    // r107b: `draw` is the sun's caustics (BB_CAUSTICS), `lamp_draw` the lamps' (BB_CAUSTICS_LAMPS).
    bool draw = plane && knobs.strength > 0.0f;
    bool lamp_draw = plane && knobs.lamp_strength > 0.0f;
    bool sets_ok = false;
    std::array<BC::Lamp, BC::MaxLamps> chosen{};
    u32 chosen_count = 0;
    // r107e: puddles stand in for the water plane in frames without a mirrored water pass.
    calls_since_mirror = plane ? 0u : calls_since_mirror + 1u;
    const bool puddle = !plane && knobs.lamp_strength > 0.0f && camera.valid &&
                        calls_since_mirror > BC::PuddleQuietCalls;
    if (!plane) {
        // The first pass of a mirrored frame (the mirror image) comes here too: it leaves the
        // shadow resolve's news for the pass the plane is found in.
        ++stats.no_plane;
        if (puddle && puddle_found) {
            plane_y = puddle_y;
            if (puddle_checked) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
                lamp_draw = chosen_count > 0;
            } else {
                ++stats.puddle_floor;
            }
        } else if (puddle) {
            ++stats.puddle_none;
        }
    } else {
        // The sun and its shadow target are this frame's only when a resolve came since the last
        // call that found a plane; so are the light sets (r107b).
        const bool fresh = resolved;
        resolved = false;
        sets_ok = std::exchange(sets_fresh, false);
        if (camera.valid && camera.inv_view[7] < plane_y) {
            // The camera is below the water: this pass is the mirror image, not the world.
            ++stats.mirror;
            draw = lamp_draw = false;
        } else {
            if (draw && (!fresh || !sun_valid)) {
                ++stats.no_sun;
                draw = false;
            }
            if (lamp_draw && camera.valid) {
                const auto& seen = lamps.Lights();
                chosen_count = BC::ChooseLamps(seen.empty() ? nullptr : seen.front().data(),
                                               seen.size(), camera.inv_view, plane_y, chosen,
                                               knobs.world > 0.0f ? &last_lamps : nullptr, last_lamp_count);
            }
            if (lamp_draw && chosen_count == 0) {
                ++stats.no_lamps;
                lamp_draw = false;
            }
        }
    }
    if (knobs.world > 0.0f && chosen_count > 0) {
        last_lamps = chosen; // r107f: the lamps of this pass count more in the next one
        last_lamp_count = chosen_count;
    }
    if (!draw && !lamp_draw && !knobs.show && !puddle) { // r107e: puddles measure every pass
        done();
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (!camera.valid || color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.no_scene;
        done();
        return;
    }
    VideoCore::Image* shadow = nullptr;
    if (draw && shadow_target) {
        shadow = &texture_cache.GetImage(shadow_target);
        if (!FourBytes(*shadow)) {
            shadow = nullptr;
        }
    }
    VideoCore::Image* material = nullptr;
    if ((knobs.show || puddle) && gbuffer_material && gbuffer_depth == depth_id) { // r107e
        material = &texture_cache.GetImage(gbuffer_material);
        if (!FourBytes(*material)) {
            material = nullptr;
        }
    }
    // r107b: the sun only where the light set at the water point has it: the sets of this frame's
    // directional draw, whose texture 0 must be the G-buffer's specular target.
    VideoCore::Image* records = nullptr;
    if (draw && sets_ok && gbuffer_records && gbuffer_depth == depth_id) {
        records = &texture_cache.GetImage(gbuffer_records);
        if (!FourBytes(*records) || records->info.guest_address != sets_address) {
            records = nullptr;
        }
    }
    if (draw && !records) {
        ++stats.no_sets;
        draw = false;
    }
    VideoCore::Image* albedo = nullptr;
    if (lamp_draw && gbuffer_albedo && gbuffer_depth == depth_id) {
        albedo = &texture_cache.GetImage(gbuffer_albedo);
        const auto f = albedo->info.pixel_format;
        if (!FourBytes(*albedo) && f != vk::Format::eR8G8B8A8Srgb && f != vk::Format::eB8G8R8A8Srgb) {
            albedo = nullptr;
        }
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
        // Only scene-sized images have a reduced proxy: the others are left out.
        if (shadow && !scene_targets.EligibleScene(*shadow)) {
            shadow = nullptr;
        }
        if (material && !scene_targets.EligibleScene(*material)) {
            material = nullptr;
        }
        if (records && !scene_targets.EligibleScene(*records)) {
            records = nullptr; // r107b
        }
        if (albedo && !scene_targets.EligibleScene(*albedo)) {
            albedo = nullptr; // r107b
        }
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (draw && !shadow) {
        ++stats.no_shadow;
        draw = false;
    }
    if (draw && !records) {
        ++stats.no_sets; // r107b
        draw = false;
    }
    if ((!draw && !lamp_draw && !material) || width < 16 || height < 16) {
        done();
        return;
    }
    // The pass reads the camera depth: a lamps-apart batch still open ends first (only here,
    // right before a dispatch, so it is never split for nothing).
    if (point_shadow.Apart()) {
        point_shadow.EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
        ++stats.lamp_ends;
    }
    const SceneUseScope scene_use{"water caustics"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, shadow_view{}, material_view{};
    vk::ImageView records_view{}, albedo_view{}; // r107b
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        if (shadow) {
            VideoCore::ImageViewInfo info;
            info.format = shadow->info.pixel_format;
            shadow_view = scene_targets.ReadNext(shadow_target, info).view;
        }
        if (material) {
            VideoCore::ImageViewInfo info;
            info.format = material->info.pixel_format;
            material_view = scene_targets.ReadNext(gbuffer_material, info).view;
        }
        if (draw && records) { // r107b
            VideoCore::ImageViewInfo info;
            info.format = records->info.pixel_format;
            records_view = scene_targets.ReadNext(gbuffer_records, info).view;
        }
        if (lamp_draw && albedo) { // r107b
            VideoCore::ImageViewInfo info;
            info.format = albedo->info.pixel_format;
            albedo_view = scene_targets.ReadNext(gbuffer_albedo, info).view;
        }
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            done();
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        if (shadow) {
            shadow_view = CachedView(*shadow, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(shadow, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (material) {
            material_view = CachedView(*material, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(material, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (draw && records) { // r107b
            records_view = CachedView(*records, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(records, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        if (lamp_draw && albedo) { // r107b
            albedo_view = CachedView(*albedo, vk::ImageAspectFlagBits::eColor);
            runtime.Transit(albedo, vk::ImageLayout::eGeneral, Compute, ShaderRead);
        }
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    if (draw && !shadow_view) {
        ++stats.no_shadow;
        draw = false;
    }
    if (draw && !records_view) {
        ++stats.no_sets; // r107b
        draw = false;
    }
    if (puddle && !material_view) {
        lamp_draw = false; // r107e: lamps over puddles need the gloss (a crossing must be a candidate)
    }
    if (!draw && !lamp_draw && !material_view) {
        done();
        return;
    }
    BC::Push push{};
    push.proj = camera.proj;
    push.frame = {float(width), float(height), jitter[0], jitter[1]};
    push.inv_view = camera.inv_view;
    push.sun = {sun[0], sun[1], sun[2], plane_y};
    push.drift = drift.Offsets();
    push.gain = BC::GainOf(knobs);
    push.evolve = drift.EvolveCells();
    push.flags = (knobs.show ? BC::FlagShow : 0u) | (draw ? BC::FlagPlane | BC::FlagRecords : 0u) |
                 (material_view ? BC::FlagMaterial : 0u) | (lamp_draw ? BC::FlagLamps : 0u) |
                 (lamp_draw && albedo_view ? BC::FlagAlbedo : 0u);
    // r107f: the world map is used with the lamps' caustics; a plane more than WorldKeep m from the
    // last one starts a new generation (the old cells read as unknown); the first use clears it.
    const bool world_on = knobs.world > 0.0f && lamp_draw && world_map.buffer;
    bool clear_map = false;
    if (world_on) {
        if (world_gen == 0 || std::fabs(plane_y - world_plane) > BC::WorldKeep) {
            ++world_gen;
            world_plane = plane_y;
            ++stats.world_changes;
        }
        push.flags |= BC::FlagWorld;
        ++stats.world_draws;
        clear_map = !world_cleared;
        world_cleared = true;
    }
    push.slot = dispatches % BC::Slots;
    // r107e: puddles: measured with the G-buffer's gloss; the plane found goes in sun.w.
    const bool puddle_pass = puddle && material_view;
    if (puddle_pass) {
        push.flags |= BC::FlagPuddle | (puddle_found ? BC::FlagPuddlePlane : 0u);
        ++stats.puddle_measured;
        stats.puddle_lamps += lamp_draw ? 1 : 0;
    }
    slot_camera_y[push.slot] = camera.inv_view[7];
    slot_puddle_y[push.slot] = plane_y;
    slot_puddle[push.slot] = puddle_pass ? (puddle_found ? 2 : 1) : 0;
    // r107b: the slot's data block (the slot's last reader, Slots dispatches ago, is long done):
    // the light sets' sun mask, the lamps and their gain.
    {
        u32* data = static_cast<u32*>(counters.mapped) + BC::Slots * BC::SlotWords +
                    push.slot * BC::DataWords;
        std::memset(data, 0, BC::DataWords * sizeof(u32));
        std::memcpy(data, sun_mask.data(), sizeof(sun_mask));
        const u32 lamp_count = lamp_draw ? chosen_count : 0u;
        data[CAUSTICS_DATA_COUNT] = lamp_count;
        const float lamp_gain = BC::LampGainOf(knobs);
        std::memcpy(&data[CAUSTICS_DATA_GAIN], &lamp_gain, sizeof(float));
        // r107c: the game's lamp curve, as LocalFalloff::Patch makes it (read at the start).
        const auto& settings = BbSettings::Get();
        const float core = std::isfinite(settings.startup_local_light_core) &&
                                   settings.startup_local_light_core > 0.0f
                               ? settings.startup_local_light_core
                               : 0.0f;
        const bool inverse_square = settings.startup_local_inverse_square;
        const float core2 = inverse_square ? core * core : -1.0f;
        const float energy = inverse_square ? settings.startup_local_light_intensity *
                                                  LocalFalloff::EnergyScale(core)
                                            : 1.0f;
        std::memcpy(&data[CAUSTICS_DATA_CORE2], &core2, sizeof(float));
        std::memcpy(&data[CAUSTICS_DATA_ENERGY], &energy, sizeof(float));
        const float look = lamp_count > 0 ? BC::LookOf(knobs) : 0.0f; // r107d
        std::memcpy(&data[CAUSTICS_DATA_LOOK], &look, sizeof(float));
        // r107f: the world map's generation and the bed's strength (0 and 0 without BB_CAUSTICS_WORLD)
        data[CAUSTICS_DATA_WORLD_GEN] = world_on ? world_gen : 0u;
        const float bed_strength = world_on ? knobs.world : 0.0f;
        std::memcpy(&data[CAUSTICS_DATA_BED], &bed_strength, sizeof(float));
        for (u32 k = 0; k < lamp_count; ++k) {
            const auto& lamp = chosen[k];
            const std::array<float, BC::LampWords> words{lamp.world[0],  lamp.world[1],
                                                        lamp.world[2],  lamp.reach,
                                                        lamp.colour[0], lamp.colour[1],
                                                        lamp.colour[2], 0.0f};
            std::memcpy(&data[CAUSTICS_DATA_LAMPS + k * BC::LampWords], words.data(), sizeof(words));
            stats.colour_top = std::max({stats.colour_top, lamp.colour[0], lamp.colour[1], lamp.colour[2]});
        }
        stats.lamp_draws += lamp_draw ? 1 : 0;
        stats.lamps_used += lamp_count;
    }
    // The shader's counts of the dispatch Slots - 1 before this one (its work is long done; the
    // slot is cleared on the GPU before its next use, which is the next dispatch).
    if (dispatches + 1 >= BC::Slots) {
        const auto* words = static_cast<const u32*>(counters.mapped) +
                            ((dispatches + 1) % BC::Slots) * BC::SlotWords;
        for (u32 i = 0; i < BC::SlotWords; ++i) {
            stats.pixels[i] += words[i];
        }
        ++stats.read;
        // r107e: that dispatch's puddle candidates give the plane; its counts on the plane it was
        // given check it (only the same plane, within PuddleKeep).
        const u32 slot = (dispatches + 1) % BC::Slots;
        if (slot_puddle[slot] != 0) {
            const auto e = BC::EstimatePuddle(words + CAUSTICS_W_HEIGHTS, slot_camera_y[slot], width * height);
            if (!e.found) {
                puddle_found = puddle_checked = false;
            } else if (!puddle_found || std::fabs(e.height - puddle_y) > BC::PuddleKeep) {
                puddle_found = true;
                puddle_checked = false;
                puddle_y = e.height;
            }
            if (puddle_found && slot_puddle[slot] == 2 &&
                std::fabs(slot_puddle_y[slot] - puddle_y) <= BC::PuddleKeep) {
                const u32 ground = words[CAUSTICS_W_PUDDLE_GROUND], wet = words[CAUSTICS_W_PUDDLE_WET];
                puddle_checked = BC::PuddlesNotFloor(ground, wet);
                stats.puddle_ground = ground;
                stats.puddle_wet = wet;
            }
        }
    }
    ++dispatches;
    stats.drawn += draw || lamp_draw ? 1 : 0;
    stats.shown += draw || lamp_draw || puddle_pass ? 0 : 1; // r107e: a puddle pass is no test view
    last_plane = plane || puddle_found ? plane_y : last_plane;
    if (!told_first && (draw || lamp_draw)) {
        told_first = true;
        std::printf("Water caustics (r107b): first caustics drawn: water plane at y %.2f, sun or moon "
                    "%.2f up (%s), %u lamps, scene %ux%u (%s)\n",
                    double(plane_y), double(sun[1]), draw ? "drawn" : "not drawn",
                    lamp_draw ? chosen_count : 0u, width, height,
                    reduced ? "reduced scene" : "the game's scene");
    }
    // Unbound inputs take the depth's view (the shader reads them only under their flag).
    const vk::ImageView bound_shadow = shadow_view ? shadow_view : depth_view;
    const vk::ImageView bound_material = material_view ? material_view : depth_view;
    const vk::ImageView bound_albedo = albedo_view ? albedo_view : depth_view;   // r107b
    const vk::ImageView bound_records = records_view ? records_view : depth_view; // r107b
    EffectPass::Mark(ProfileRow, "water caustics");
    scheduler.RecordCrumb(
        {.name = "water caustics"},
        [push, width, height, color_view, depth_view, bound_shadow, bound_material, bound_albedo,
         bound_records,
         counter_buffer = counters.buffer,
         world_buffer = world_map.buffer ? world_map.buffer : counters.buffer, clear_map, // r107f
         pass_pipeline = *pipeline,
         pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            if (clear_map) {
                cmdbuf.fillBuffer(world_buffer, 0, WorldBytes, 0); // r107f: the first use
            }
            cmdbuf.fillBuffer(counter_buffer, push.slot * SlotBytes, SlotBytes, 0);
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array infos{Info(color_view),     Info(depth_view),   Info(bound_shadow),
                                   Info(bound_material), Info(bound_albedo), Info(bound_records)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, BufferBytes};
            const vk::DescriptorBufferInfo world_info{world_buffer, 0, VK_WHOLE_SIZE}; // r107f
            const std::array writes{Write(0, StorageImage, &infos[0]),
                                    Write(1, SampledImage, &infos[1]),
                                    Write(2, SampledImage, &infos[2]),
                                    Write(3, SampledImage, &infos[3]),
                                    vk::WriteDescriptorSet{.dstBinding = 4,
                                                           .descriptorCount = 1,
                                                           .descriptorType = StorageBuffer,
                                                           .pBufferInfo = &counter_info},
                                    Write(5, SampledImage, &infos[4]),
                                    Write(6, SampledImage, &infos[5]),
                                    vk::WriteDescriptorSet{.dstBinding = 7,
                                                           .descriptorCount = 1,
                                                           .descriptorType = StorageBuffer,
                                                           .pBufferInfo = &world_info}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                 &push);
            cmdbuf.dispatch((width + BC::Group - 1) / BC::Group, (height + BC::Group - 1) / BC::Group,
                            1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands | Host, MemoryAll | vk::AccessFlagBits2::eHostRead);
        });
    done();
}

void Caustics::Report() {
    const double reads = std::max(1.0, double(stats.read));
    BbReport::Printf(
        "Water caustics (r107): %u calls, %u drew, %u test view only; skipped: %u no water plane, %u "
        "mirror image, %u no sun, %u no shadow target, %u no scene; plane y %.2f, sun %.2f up; a "
        "dispatch: %.0f px facing, %.0f on water, %.0f drawn, %.0f puddle cand.; %u lamp batch ends\n",
        stats.calls, stats.drawn, stats.shown, stats.no_plane, stats.mirror, stats.no_sun,
        stats.no_shadow, stats.no_scene, double(last_plane), double(last_sun_y),
        double(stats.pixels[0]) / reads,
        double(stats.pixels[1]) / reads, double(stats.pixels[2]) / reads,
        double(stats.pixels[3]) / reads, stats.lamp_ends);
    // r107b: why water points are not water, what the depth holds at those that are, the light
    // sets, the lamps (a dispatch, as above)
    const auto px = [&](int word) { return double(stats.pixels[word]) / reads; };
    BbReport::Printf(
        "Water caustics (r107b): a dispatch: sun water pt %.0f off scr, %.0f hidden, %.0f dry, %.0f "
        "on plane, %.0f below it, %.0f sunless set; skipped %u no sets; sets %u, %u sunny, best "
        "%.2f\n",
        px(CAUSTICS_W_OFF), px(CAUSTICS_W_HIDDEN), px(CAUSTICS_W_DRY), px(CAUSTICS_W_ON_PLANE),
        px(CAUSTICS_W_BELOW), px(CAUSTICS_W_NO_SUN_SET), stats.no_sets, sets_count, sets_sunny,
        double(sets_best));
    // r107c: the lamps (a dispatch with lamps; the light added and the lamps' own direct light as
    // the pass models it, each over the pixel's own, means over the lit pixels)
    const double lit = std::max(1.0, double(stats.pixels[CAUSTICS_W_LAMP_LIT]));
    BbReport::Printf(
        "Water caustics (r107c): a dispatch: lamps %.2f (colour up to %.1f, %s curve), %.0f px tried, "
        "%.0f lit (+%.1f%% of their own, lamp model %.2f of it), crossings %.0f dry, %.0f unseen; "
        "skipped %u no lamps\n",
        double(stats.lamps_used) / std::max(1.0, double(stats.lamp_draws)), double(stats.colour_top),
        BbSettings::Get().startup_local_inverse_square ? "inverse-square" : "(1-d/r)^2",
        px(CAUSTICS_W_LAMP_TRIED), px(CAUSTICS_W_LAMP_LIT),
        100.0 * double(stats.pixels[CAUSTICS_W_LAMP_RATIO]) / CAUSTICS_RATIO_SCALE / lit,
        double(stats.pixels[CAUSTICS_W_LAMP_MODEL]) / CAUSTICS_MODEL_SCALE / lit, px(CAUSTICS_W_LAMP_DRY),
        px(CAUSTICS_W_LAMP_UNSEEN), stats.no_lamps);
    // r107d: the modelled lamp light over the pixel's own, by bins of that light (2 stops a bin),
    // and over the brightest tenth of those pixels (whole bins from the top, at least a tenth).
    char bins[BC::Bins * 24] = {};
    size_t used = 0;
    double all = 0.0, top_n = 0.0, top_sum = 0.0;
    for (u32 b = 0; b < BC::Bins; ++b) {
        all += double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);
    }
    for (u32 b = 0; b < BC::Bins; ++b) {
        const double n = double(stats.pixels[CAUSTICS_W_BIN_COUNT + b]);
        const double ratio = double(stats.pixels[CAUSTICS_W_BIN_RATIO + b]) / CAUSTICS_MODEL_SCALE / std::max(1.0, n);
        used += size_t(std::max(0, std::snprintf(bins + used, sizeof(bins) - used, "%s%.0f %.2f",
                                                 b ? ", " : "", n / reads, ratio)));
        used = std::min(used, sizeof(bins) - 1);
        const u32 from_top = BC::Bins - 1 - b;
        if (top_n < 0.1 * all) {
            top_n += double(stats.pixels[CAUSTICS_W_BIN_COUNT + from_top]);
            top_sum += double(stats.pixels[CAUSTICS_W_BIN_RATIO + from_top]) / CAUSTICS_MODEL_SCALE;
        }
    }
    BbReport::Printf("Water caustics (r107d): a dispatch: lamp model over own by modelled light (px ratio, "
                     "<2^-10, 2 stops a bin, >=1): %s; brightest tenth (%.0f px) %.2f; look %.2f, %.0f px\n",
                     bins, top_n / reads, top_sum / std::max(1.0, top_n), double(BC::LookOf(knobs)),
                     px(CAUSTICS_W_LOOK));
    // r107e: the puddles (a dispatch: means over every dispatch read)
    double candidates = 0.0;
    for (u32 i = 0; i < BC::HeightBins; ++i) {
        candidates += double(stats.pixels[CAUSTICS_W_HEIGHTS + i]);
    }
    BbReport::Printf("Water caustics (r107e): puddles: %u passes measured, %u with lamps; %.0f candidates "
                     "a dispatch; plane %s y %.2f; guard: %llu up-facing on it, %llu wet (%.2f, refused "
                     "above %.2f); %u calls no plane, %u unchecked or refused\n",
                     stats.puddle_measured, stats.puddle_lamps, candidates / reads,
                     puddle_found ? (puddle_checked ? "checked" : "unchecked") : "none", double(puddle_y),
                     static_cast<unsigned long long>(stats.puddle_ground),
                     static_cast<unsigned long long>(stats.puddle_wet),
                     double(stats.puddle_wet) / std::max(1.0, double(stats.puddle_ground)),
                     double(BC::PuddleMaxWet), stats.puddle_none, stats.puddle_floor);
    if (knobs.world > 0.0f) {
        // r107f: the world map and the light under the water (a dispatch: means over every dispatch read)
        BbReport::Printf("Water caustics (r107f): world map (bed %.2f): %u dispatches with it, %u new plane "
                         "generations (now %u, plane y %.2f); a dispatch: %.0f cells written as water, %.0f "
                         "as dry; lamp crossings the screen cannot see taken from the map: %.0f as water, "
                         "%.0f as dry; light through the water %.0f px (mirrored plane), ripple on %.0f px "
                         "(puddles)\n",
                         double(knobs.world), stats.world_draws, stats.world_changes, world_gen,
                         double(world_plane), px(CAUSTICS_W_MAP_WATER), px(CAUSTICS_W_MAP_DRY),
                         px(CAUSTICS_W_MAP_RESCUED_WATER), px(CAUSTICS_W_MAP_RESCUED_DRY), px(CAUSTICS_W_BED),
                         px(CAUSTICS_W_BED_PUDDLE));
    }
    stats = {};
}

} // namespace Vulkan
