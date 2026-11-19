// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r131a_foliage-translucency): the foliage translucency's knobs and the back-lit glow (vk_foliage_glow.h; the rules in
// foliage_translucency.h, the pass in host_shaders/foliage_glow.comp).

#include "video_core/renderer_vulkan/vk_foliage_glow.h"
#include "video_core/renderer_vulkan/vk_foliage_mask.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>
#include <vector>

#include "bbport_settings.h"
#include "bbport_toggles.h"
#if __has_include("bbport_live_knobs.h")
#include "bbport_live_knobs.h" // the test tools' live knobs (r84_live-test-knobs), when the build has them
#define FT_LIVE_KNOBS 1
#endif
#include "shader_recompiler/ir/passes/cutout_analysis.h"
#include "video_core/host_shaders/foliage_glow_comp.h"
#include "video_core/host_shaders/foliage_glow_mask_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/vk_rt_shadow.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/volumetric_area_gate.h"
#include "video_core/texture_cache/texture_cache.h"

// bbport (r131a_foliage-translucency): the setting's numbers are the rules' (0 off, 1 light through leaves, 2 glow, 3 both; off by default).
static_assert(BbSettings::FoliageTranslucencyOff == Vulkan::FoliageTranslucency::SettingOff &&
              BbSettings::FoliageTranslucencyBoth == Vulkan::FoliageTranslucency::SettingBoth &&
              BbSettings::FoliageTranslucencyDefault == Vulkan::FoliageTranslucency::SettingOff);

namespace Vulkan::FoliageTranslucency {
namespace {

struct Config {
    Decision decision;
    bool light = false; ///< the colour layers are made and the visibility rays take them
    bool lamps = false, sun = false, glow = false;
    Tune tune;
};

const char* Env(const char* name) {
    return std::getenv(name);
}

// Read once, by the first caller: the start line.
const Config& State() {
    static const Config config = [] {
        Config c;
        const int setting = BbSettings::Get().startup_foliage_translucency;
        const char* const master = Env("BB_FOLIAGE_TRANSLUCENCY");
        c.decision = Decide(master, Env("BB_FOLIAGE_LIGHT_THROUGH"), Env("BB_FOLIAGE_GLOW"), setting,
                            Shader::Optimization::CardAlphaLevel() == 2);
        c.tune = ReadTune(Env);
        if (!c.decision.master) {
            std::printf("Foliage translucency (r131a): BB_FOLIAGE_TRANSLUCENCY=0: %s (nothing made)\n", c.decision.why);
            return c;
        }
        const char* lamps_why = "off (light through leaves is off)";
        const char* sun_why = lamps_why;
        if (c.decision.light) {
            c.lamps = RtShadow::CardLampsWanted();
            c.sun = RtShadow::CardSunOn();
            lamps_why = c.lamps ? "on" : "off (needs BB_RT_CARD_LAMPS=1)";
            sun_why = c.sun ? "on" : "off (needs BB_RT_CARD_SUN=1)";
        }
        c.glow = c.decision.glow && RtShadow::CardLampsWanted();
        c.light = c.decision.light && (c.lamps || c.sun || c.glow);
        char source[96];
        if (EnvGiven(master)) {
            std::snprintf(source, sizeof source, "BB_FOLIAGE_TRANSLUCENCY=1");
        } else {
            std::snprintf(source, sizeof source, "setting graphics_foliage_translucency=%d", setting);
        }
        std::printf("Foliage translucency (r131a): %s: light-through lamps %s, sun %s, glow %s; T=%.2f tint=%.2f floor=%.3f; "
                    "colour layers %s\n",
                    source, lamps_why, sun_why,
                    c.glow ? "on" : (c.decision.glow ? "off (needs BB_RT_CARD_LAMPS=1)" : "off"), double(c.tune.pass),
                    double(c.tune.tint), double(c.tune.floor),
                    c.light ? "2.0 MiB" : "none");
        if (c.lamps && c.sun == false && c.decision.light) {
            std::printf("Foliage translucency (r131a): the sun and moon stay as before (grey shadows); needs BB_RT_CARD_SUN=1\n");
        }
        if (c.sun && !c.glow) {
            std::printf("Foliage translucency (r131a): sun: grey (no tint without the glow pass)\n");
        }
        if (c.lamps) {
            std::printf("Foliage translucency (r131a): lamps: only the strongest two lamps of a pixel take the leaf's hue, the rest stay grey; "
                        "with BB_GLASS_LIGHT on a frame with leaves runs the foliage build (no glass tint)\n");
        }
        return c;
    }();
    return config;
}

} // namespace

bool On() {
    return State().decision.master;
}
bool LightThrough() {
    return State().light;
}
bool LampThrough() {
    return State().lamps;
}
bool SunThrough() {
    return State().sun;
}
bool Glow() {
    return State().glow;
}
const Tune& Tuning() {
    return State().tune;
}

namespace {
// -1: unset or empty in the live knobs file (the start value stands), else exactly "1" is on and anything else off.
int LiveReading(const char* text) {
    return text == nullptr || text[0] == '\0' ? -1 : ExactOne(text) ? 1 : 0;
}
// A part as it is now: the start value, and where the build has the live knobs the knob's value (said when it changes).
bool Now(bool start, [[maybe_unused]] const char* name, [[maybe_unused]] bool& told) {
    if (!start) {
        return false;
    }
#ifdef FT_LIVE_KNOBS
    static BbLiveKnobs::Knob<int> light{"BB_FOLIAGE_LIGHT_THROUGH", [](const char* text) -> int { return LiveReading(text); }};
    static BbLiveKnobs::Knob<int> glow{"BB_FOLIAGE_GLOW", [](const char* text) -> int { return LiveReading(text); }};
    const int v = name[11] == 'L' ? light.Get() : glow.Get(); // "BB_FOLIAGE_L..." or "BB_FOLIAGE_G..." (index 11; review fix: 12 swapped the two knobs)
    const bool on = v < 0 || v == 1;
    if (on != told) {
        told = on;
        std::printf("Foliage translucency (r131a): %s now %s (live)\n", name, on ? "on" : "off");
    }
    return on;
#else
    return true;
#endif
}
} // namespace

bool LightNow() {
    static bool told = true;
    return Now(State().light, "BB_FOLIAGE_LIGHT_THROUGH", told);
}
bool GlowNow() {
    static bool told = true;
    return Now(State().glow, "BB_FOLIAGE_GLOW", told);
}

} // namespace Vulkan::FoliageTranslucency

namespace Vulkan {
namespace {
namespace FT = FoliageTranslucency;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Host = vk::PipelineStageFlagBits2::eHost;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr u64 ProfileRow = 133; ///< EffectPass::Mark: the row "Lighting: foliage glow"
constexpr vk::DeviceSize BufferBytes = vk::DeviceSize(FG_COUNTER_WORDS + FG_SLOTS * FG_DATA_WORDS) * sizeof(u32);

struct Push {
    std::array<float, 4> proj;
    std::array<float, 4> rot0, rot1, rot2;
    std::array<float, 2> jitter;
    std::array<u32, 2> size;
    u32 flags, slot;
    float strength, wrap, pass_share, pass_tint, pass_floor, unused;
};
static_assert(sizeof(Push) == FG_PUSH_BYTES);

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// Four 8-bit channels (the G-buffer's normal target).
bool FourBytes(const VideoCore::Image& image) {
    const auto f = image.info.pixel_format;
    return f == vk::Format::eR8G8B8A8Unorm || f == vk::Format::eB8G8R8A8Unorm || f == vk::Format::eA8B8G8R8UnormPack32;
}

bool Finite3(const std::array<float, 3>& v) {
    return std::isfinite(v[0]) && std::isfinite(v[1]) && std::isfinite(v[2]);
}
} // namespace

bool FoliageGlow::Wanted() {
    return FT::Glow();
}

FoliageGlow::FoliageGlow(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                         Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                         PointShadow& point_shadow_, RtShadow& rt_shadow_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, point_shadow{point_shadow_}, rt_shadow{rt_shadow_} {
    using enum vk::DescriptorType;
    mask_mode = FoliageMask::Requested();
    if (EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat)) {
        if (mask_mode && FoliageMask::Supported(instance)) {
            mask_shader = EffectPass::Create(
                instance, set_layout, layout, pipeline,
                {eAccelerationStructureKHR, eSampledImage, eStorageImage, eSampledImage, eSampledImage,
                 eStorageBuffer, eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                 eCombinedImageSampler, eStorageBuffer, eSampledImage, eSampledImage},
                FG_PUSH_BYTES, FOLIAGE_GLOW_MASK_COMP, "Foliage glow mask");
        }
        // A device without the mask path can still use the legacy layout for hue, with
        // FG_FLAG_GLOW clear so its camera query is unreachable.
        made = mask_shader || EffectPass::Create(
            instance, set_layout, layout, pipeline,
            {eAccelerationStructureKHR, eSampledImage, eStorageImage, eSampledImage, eSampledImage,
             eStorageBuffer, eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
             eCombinedImageSampler, eStorageBuffer, eSampledImage},
            FG_PUSH_BYTES, FOLIAGE_GLOW_COMP, "Foliage glow");
    }
    if (made) {
        const VkBufferCreateInfo buffer_ci{
            .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
            .size = BufferBytes,
            .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
        };
        VmaAllocationCreateInfo alloc_ci{};
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO;
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
        VkBuffer raw{};
        VmaAllocationInfo info{};
        if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &data.allocation, &info) == VK_SUCCESS) {
            data.buffer = raw;
            data.mapped = info.pMappedData;
        }
        made = data.mapped != nullptr;
        if (made) {
            std::memset(data.mapped, 0, BufferBytes);
        }
    }
    const auto& tune = FT::Tuning();
    std::printf("Foliage glow (r131a): %s; leaves and grass lit from behind (the sun, the moon and the two strongest lamps) gain light colour x "
                "leaf albedo x %.2f (strength) x %.2f (T) x back-lit factor (wrap %.2f) x visibility; the sun's constant k %.3f%s; thin-leaf "
                "diffuse transmission on the front leaf in screen space, not volumetric subsurface scattering; the sun's colour is the "
                "brightest light set's, one for the frame\n",
                made ? "on" : "off - the pass could not be made", double(tune.strength), double(tune.pass), double(tune.wrap),
                double(tune.sun_k), tune.glow_view ? "; test view on (the term x8 over a dim scene)" : "");
}

FoliageGlow::~FoliageGlow() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    if (data.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), data.buffer, data.allocation);
    }
}

void FoliageGlow::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal, VideoCore::ImageId albedo) {
    gbuffer_depth = depth;
    gbuffer_normal = normal;
    gbuffer_albedo = albedo;
    lamps.Clear(); // the lamps of this pass only (they are in its view space)
    armed = armed || depth != applied_depth || BbStats::frame_number.load(std::memory_order_relaxed) != applied_frame;
}

void FoliageGlow::AddLights(const u32* records, u32 count) {
    lamps.Add(records, count);
}

void FoliageGlow::OnSun(const std::array<float, 3>& toward, bool valid) {
    const float length = std::sqrt(toward[0] * toward[0] + toward[1] * toward[1] + toward[2] * toward[2]);
    sun_valid = valid && Finite3(toward) && length > 1e-6f;
    if (sun_valid) {
        sun_world = {toward[0] / length, toward[1] / length, toward[2] / length};
    }
}

// The brightest set's light 0 (not the fallback): the sun's or the moon's colour for this frame.
void FoliageGlow::OnLightSets(const float* table, u32 floats) {
    namespace AG = VolumetricAreaGate;
    const u32 count = std::min(floats / AG::RecordFloats, AG::Records);
    float best = 0.0f;
    const float* pick = nullptr;
    for (u32 i = 0; i < count; ++i) {
        const float* set = table + i * AG::RecordFloats;
        if (AG::IsFallback(set)) {
            continue;
        }
        const float lum = AG::RawLuminance(set + AG::RecordColour);
        if (lum > best) {
            best = lum;
            pick = set;
        }
    }
    sun_colour_valid = pick != nullptr;
    if (pick != nullptr) {
        sun_colour = {pick[AG::RecordColour], pick[AG::RecordColour + 1], pick[AG::RecordColour + 2]};
        sun_colour_valid = Finite3(sun_colour);
    }
}

vk::ImageView FoliageGlow::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid && entry.aspect == aspect) {
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
        .view = Check<"create foliage glow view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void FoliageGlow::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                        std::array<float, 2> jitter, vk::ImageView receiver_mask,
                        vk::ImageView diagnostic_mask, vk::Extent2D mask_extent) {
    // Once after each G-buffer pass: the rasterizer calls at every blended draw of the scene.
    if (!armed) {
        return;
    }
    armed = false;
    applied_depth = gbuffer_depth;
    applied_frame = BbStats::frame_number.load(std::memory_order_relaxed);
    ++stats.calls;
    if (!FT::GlowNow()) { // switched off live (the test tools' knobs file): nothing runs
        ++stats.switched_off;
        return;
    }
    if (!made || !color_id || !depth_id || camera_motion.PreviewFrame()) {
        ++stats.no_scene;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid) {
        ++stats.no_scene;
        return;
    }
    if (gbuffer_depth != depth_id || !gbuffer_normal || !gbuffer_albedo) {
        ++stats.no_gbuffer; // not the pass the lights and targets were noted for
        return;
    }
    const auto& tune = FT::Tuning();
    const bool diagnostic = mask_shader && diagnostic_mask && tune.strength == 0.0f;
    bool leaf_glow = !mask_mode || (mask_shader && receiver_mask && tune.strength > 0.0f);
    if (!leaf_glow && !diagnostic && !(sun_valid && sun_colour_valid && FT::SunThrough() && FT::LightNow())) {
        return;
    }
    // The cards take CARD_LAMP_MASK only while a reader of them exists (as the lamp pass tells the scene).
    rt_shadow.NoteCardLampUser();
    if (!rt_shadow.PrepareScene()) {
        ++stats.no_scene;
        return;
    }
    const auto readers = rt_shadow.CardLampReadersNow();
    const vk::AccelerationStructureKHR tlas = rt_shadow.Scene();
    if (readers.instances == 0 || !readers.rows || !readers.pool || !readers.info || !readers.layers || !readers.sampler || !tlas) {
        ++stats.no_cards; // no card with data in the scene yet
        return;
    }
    const bool has_sun = sun_valid && sun_colour_valid;
    const auto& seen = lamps.Lights();
    const u32 lamp_count = u32(std::min<std::size_t>(seen.size(), FG_MAX_LAMPS));
    if (!has_sun && lamp_count == 0 && !diagnostic) {
        ++stats.no_light;
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    auto& normal = texture_cache.GetImage(gbuffer_normal);
    auto& albedo = texture_cache.GetImage(gbuffer_albedo);
    const auto albedo_format = albedo.info.pixel_format;
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat || !FourBytes(normal) ||
        (!FourBytes(albedo) && albedo_format != vk::Format::eR8G8B8A8Srgb && albedo_format != vk::Format::eB8G8R8A8Srgb)) {
        ++stats.no_gbuffer;
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size, else the game's render size.
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
        if (!scene_targets.EligibleScene(normal) || !scene_targets.EligibleScene(albedo)) {
            ++stats.no_gbuffer;
            return;
        }
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        ++stats.no_scene;
        return;
    }
    // The sun trace's hue image (the light through leaves: its tint), when it was written this frame at this size.
    const auto hue = rt_shadow.SunHueNow();
    const bool use_hue = has_sun && hue.view && hue.width == width && hue.height == height && FT::SunThrough() && FT::LightNow();
    stats.no_hue += has_sun && FT::SunThrough() && !use_hue ? 1 : 0;
    const bool mask_matches = mask_extent == vk::Extent2D{width, height};
    const bool use_diagnostic = diagnostic && mask_matches;
    leaf_glow &= !mask_mode || mask_matches;
    if (!leaf_glow && !use_hue && !use_diagnostic) {
        return;
    }
    // The pass reads the camera depth and the lit scene: a lamps-apart batch still open ends first.
    if (point_shadow.Apart()) {
        point_shadow.EndApart(jitter[0] != 0.0f || jitter[1] != 0.0f);
    }
    const SceneUseScope scene_use{"foliage glow"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, normal_view{}, albedo_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        VideoCore::ImageViewInfo normal_info, albedo_info;
        normal_info.format = normal.info.pixel_format;
        albedo_info.format = albedo.info.pixel_format;
        normal_view = scene_targets.ReadNext(gbuffer_normal, normal_info).view;
        albedo_view = scene_targets.ReadNext(gbuffer_albedo, albedo_info).view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            ++stats.no_scene;
            return;
        }
        color_view = CachedView(color, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, vk::ImageAspectFlagBits::eDepth);
        normal_view = CachedView(normal, vk::ImageAspectFlagBits::eColor);
        albedo_view = CachedView(albedo, vk::ImageAspectFlagBits::eColor);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.Transit(&normal, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.Transit(&albedo, vk::ImageLayout::eGeneral, Compute, vk::AccessFlagBits2::eShaderRead);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    // This dispatch's data block (its last reader, FG_SLOTS dispatches ago, is long done): the sun, then the lamps nearest the camera.
    const u32 slot = dispatches % FG_SLOTS;
    u32* block = static_cast<u32*>(data.mapped) + FG_COUNTER_WORDS + slot * FG_DATA_WORDS;
    std::memset(block, 0, FG_DATA_WORDS * sizeof(u32));
    const auto put = [&](u32 at, float v) { std::memcpy(&block[at], &v, sizeof(float)); };
    if (has_sun) {
        for (u32 r = 0; r < 3; ++r) {
            put(FG_DATA_SUN + r, camera.view[r * 4] * sun_world[0] + camera.view[r * 4 + 1] * sun_world[1] +
                                     camera.view[r * 4 + 2] * sun_world[2]);
            put(FG_DATA_SUN_COLOUR + r, sun_colour[r]);
        }
        put(FG_DATA_SUN_K, tune.sun_k);
    }
    u32 kept = 0;
    {
        // the nearest to the camera when the pass has more than the shader takes
        std::vector<std::pair<float, u32>> by_distance;
        by_distance.reserve(seen.size());
        for (u32 i = 0; i < u32(seen.size()); ++i) {
            const auto word = [&](u32 w) { return std::bit_cast<float>(seen[i][w]); };
            by_distance.emplace_back(word(0) * word(0) + word(1) * word(1) + word(2) * word(2), i);
        }
        const std::size_t take = std::min<std::size_t>(by_distance.size(), FG_MAX_LAMPS);
        std::partial_sort(by_distance.begin(), by_distance.begin() + take, by_distance.end());
        for (std::size_t k = 0; k < take; ++k) {
            const auto& light = seen[by_distance[k].second];
            if (!LampFog::Readable(light)) {
                continue;
            }
            const u32 at = FG_DATA_LAMPS + kept * 8u;
            for (u32 w = 0; w < 7; ++w) {
                block[at + w] = light[w]; // x y z, inverse radius squared, colour r g b: the light grid's own words
            }
            ++kept;
        }
    }
    block[FG_DATA_LAMP_COUNT] = kept;
    stats.lamps += kept;
    ++stats.passes;
    ++dispatches;
    if (!told_first) {
        told_first = true;
        std::printf("Foliage glow (r131a): first pass at frame %llu: scene %ux%u (%s), %u lamps, sun %s, hue image %s, light through leaves %s\n",
                    static_cast<unsigned long long>(BbStats::frame_number.load(std::memory_order_relaxed)), width, height,
                    reduced ? "reduced scene" : "the game's scene", kept, has_sun ? "yes" : "no", use_hue ? "yes" : "no",
                    FT::LightNow() && readers.colour ? "on" : "off");
    }
    Push push{};
    push.proj = camera.proj;
    push.rot0 = {camera.view[0], camera.view[1], camera.view[2], camera.view[3]};
    push.rot1 = {camera.view[4], camera.view[5], camera.view[6], camera.view[7]};
    push.rot2 = {camera.view[8], camera.view[9], camera.view[10], camera.view[11]};
    push.jitter = jitter;
    push.size = {width, height};
    push.flags = (leaf_glow ? FG_FLAG_GLOW : 0u) | (has_sun ? FG_FLAG_SUN : 0u) | (FT::LightNow() && readers.colour ? FG_FLAG_TRANSMIT : 0u) |
                 (use_hue ? FG_FLAG_HUE : 0u) | (tune.glow_view ? FG_FLAG_VIEW : 0u);
    if (use_diagnostic) {
        static const bool show_mask = [] {
            const char* value = std::getenv("BB_FOLIAGE_MASK_VIEW");
            return value && std::strcmp(value, "1") == 0;
        }();
        push.flags |= FG_FLAG_MASK_DIAG | (show_mask ? FG_FLAG_MASK_VIEW : 0u);
    }
    push.slot = slot;
    push.strength = tune.strength;
    push.wrap = tune.wrap;
    push.pass_share = tune.pass;
    push.pass_tint = tune.tint;
    push.pass_floor = tune.floor;
    // Unbound inputs take the depth's view (the shader reads them only under their flag).
    const vk::ImageView hue_view = use_hue ? hue.view : depth_view;
    const vk::ImageView mask_view = use_diagnostic ? diagnostic_mask
                                   : leaf_glow && receiver_mask ? receiver_mask : depth_view;
    const vk::ImageView colour_view = readers.colour ? readers.colour : readers.layers;
    EffectPass::Mark(ProfileRow, "foliage glow");
    scheduler.RecordCrumb(
        {.name = "foliage glow"},
        [push, width, height, tlas, color_view, depth_view, normal_view, albedo_view, hue_view, colour_view, readers,
         mask_view, use_mask_layout = mask_shader, buffer = data.buffer,
         pass_pipeline = *pipeline, pass_layout = *layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute, ReadWrite);
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const vk::WriteDescriptorSetAccelerationStructureKHR as_info{.accelerationStructureCount = 1,
                                                                         .pAccelerationStructures = &tlas};
            const std::array infos{Info(color_view), Info(depth_view), Info(normal_view),
                                   Info(albedo_view), Info(hue_view), Info(mask_view)};
            const vk::DescriptorBufferInfo rows_info{readers.rows, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo pool_info{readers.pool, 0, VK_WHOLE_SIZE};
            const vk::DescriptorBufferInfo layer_info{readers.info, 0, VK_WHOLE_SIZE};
            const vk::DescriptorImageInfo alpha_info{readers.sampler, readers.layers, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo colour_info{readers.sampler, colour_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo data_info{buffer, 0, BufferBytes};
            using enum vk::DescriptorType;
            const std::array writes{
                vk::WriteDescriptorSet{.pNext = &as_info, .dstBinding = 0, .descriptorCount = 1, .descriptorType = eAccelerationStructureKHR},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[1]},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1, .descriptorType = eStorageImage, .pImageInfo = &infos[0]},
                vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[2]},
                vk::WriteDescriptorSet{.dstBinding = 4, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[3]},
                vk::WriteDescriptorSet{.dstBinding = 5, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &rows_info},
                vk::WriteDescriptorSet{.dstBinding = 6, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &pool_info},
                vk::WriteDescriptorSet{.dstBinding = 7, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &layer_info},
                vk::WriteDescriptorSet{.dstBinding = 8, .descriptorCount = 1, .descriptorType = eCombinedImageSampler, .pImageInfo = &alpha_info},
                vk::WriteDescriptorSet{.dstBinding = 9, .descriptorCount = 1, .descriptorType = eCombinedImageSampler, .pImageInfo = &colour_info},
                vk::WriteDescriptorSet{.dstBinding = 10, .descriptorCount = 1, .descriptorType = eStorageBuffer, .pBufferInfo = &data_info},
                vk::WriteDescriptorSet{.dstBinding = 11, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[4]},
                vk::WriteDescriptorSet{.dstBinding = 12, .descriptorCount = 1, .descriptorType = eSampledImage, .pImageInfo = &infos[5]}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0,
                                       std::span{writes}.first(use_mask_layout ? writes.size() : writes.size() - 1));
            cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmdbuf.dispatch((width + FG_GROUP - 1) / FG_GROUP, (height + FG_GROUP - 1) / FG_GROUP, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands | Host,
                                      MemoryAll | vk::AccessFlagBits2::eHostRead);
        });
}

void FoliageGlow::OnFrameEnd() {
    if (!made || ++frames < LineFrames) {
        return;
    }
    frames = 0;
    Report();
}

// The counters are cumulative u32 sums of the GPU (differences survive the wrap), read without waiting for it: a line may miss the last pass.
void FoliageGlow::Report() {
    std::array<u32, FG_COUNTER_WORDS> now{};
    std::memcpy(now.data(), data.mapped, sizeof(now));
    std::array<double, FG_COUNTER_WORDS> d{};
    for (u32 i = 0; i < FG_COUNTER_WORDS; ++i) {
        d[i] = double(u32(now[i] - last[i]));
    }
    last = now;
    const double back = d[FG_C_BACKLIT];
    if (mask_mode) {
        std::printf("Foliage mask (r132a): sampled tags %.0f, camera ID rays %.0f\n",
                    d[FG_C_FOLIAGE], d[FG_C_ID_RAYS]);
    }
    std::printf("Foliage glow (r131a): passes %u, pixels %.0f, foliage %.0f, back-lit %.0f, lamp rays %.0f, sun rays %.0f, added luma mean %.4f, hue pixels %.0f; "
                "calls %u, skipped: %u switched off, %u no scene, %u no G-buffer, %u no cards, %u no light, sun hue missing %u; %u lamps a pass\n",
                stats.passes, d[FG_C_PIXELS], d[FG_C_FOLIAGE], back, d[FG_C_LAMP_RAYS], d[FG_C_SUN_RAYS],
                back > 0.0 ? d[FG_C_ADDED] * 0.001 / back : 0.0, d[FG_C_HUE], stats.calls, stats.switched_off, stats.no_scene, stats.no_gbuffer,
                stats.no_cards, stats.no_light, stats.no_hue, stats.passes != 0 ? u32(stats.lamps / stats.passes) : 0u);
    stats = {};
}

} // namespace Vulkan
