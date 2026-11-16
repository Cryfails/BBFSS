// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r97_heat-haze): the heat haze above flames (vk_heat_haze.h; the numbers in heat_haze.h,
// the pass in host_shaders/heat_haze.comp).

#include "video_core/renderer_vulkan/vk_heat_haze.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring> // bbport (r97b_heat-haze-paths)
#include <utility>
#include <vector>

#include "bbport_toggles.h"
#include "bbport_settings.h" // bbport (r97e_heat-haze-option)
#include "video_core/host_shaders/heat_haze_comp.h"
#include "video_core/host_shaders/heat_haze_find_comp.h" // bbport (r97f_haze-per-flame)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto MemoryAll = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr vk::ImageSubresourceRange ColorRange{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr u32 LineFrames = 600;
constexpr u32 FirstLineFrames = 120; ///< the first line comes sooner, for short test runs
constexpr u64 ProfileRow = 97; ///< EffectPass::Mark: the row "Lighting: heat haze"

/// BB_HEAT_HAZE and BB_HEAT_HAZE_SHOW, read once (the first caller: Wanted, at the rasterizer's
/// start). Set to something that is off, it says so.
const BbHeatHaze::Knobs& ReadKnobs() {
    static const BbHeatHaze::Knobs knobs = [] {
        const char* haze = std::getenv("BB_HEAT_HAZE");
        BbHeatHaze::Knobs read = BbHeatHaze::Parse(haze, std::getenv("BB_HEAT_HAZE_SHOW"));
        // bbport (r97e_heat-haze-option): BB_HEAT_HAZE_SHOW is read as if the strength were above 0; the
        // strength is HeatHaze::Strength()'s (setting or variable), per frame, and nothing runs at 0.
        {
            const BbHeatHaze::Knobs view = BbHeatHaze::Parse("1", std::getenv("BB_HEAT_HAZE_SHOW"));
            read.show = view.show;
            read.outline = view.outline;
        }
        // bbport (r97b_heat-haze-paths): BB_HEAT_HAZE_DEPTH=0, or the test view 2, drops the
        // depth tests
        read.depth = BbHeatHaze::DepthTests(std::getenv("BB_HEAT_HAZE_DEPTH")) && !read.outline;
        // bbport (r97d_heat-haze-real-shimmer): BB_HEAT_HAZE_PROOF=1 (TOOL view): written pixels magenta
        const char* proof = std::getenv("BB_HEAT_HAZE_PROOF");
        read.proof = proof != nullptr && proof[0] == '1' && proof[1] == 0; // r97e: the strength is per frame
        if (read.unreadable) {
            std::printf("Heat haze (r97): BB_HEAT_HAZE=%.16s is not a number: off\n", haze);
        } else if (haze != nullptr && haze[0] != 0 && !(read.strength > 0.0f)) {
            std::printf("Heat haze (r97): BB_HEAT_HAZE=%.16s: off\n", haze);
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

bool Overlap(const std::array<s32, 4>& a, const std::array<s32, 4>& b) {
    return a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
}
} // namespace

// bbport (r97e_heat-haze-option): the setting's numbers are the header's (one default: off).
static_assert(BbSettings::HeatHazeStrengthDefault == BbHeatHaze::DefaultStrength &&
              BbSettings::HeatHazeStrengthMax == BbHeatHaze::MaxStrength &&
              BbSettings::HeatHazeStrengthMin == 0.0f);

bool HeatHaze::Wanted() {
    return Strength().value > 0.0f;
}

StrengthKnob::Value HeatHaze::Strength() {
    // BB_HEAT_HAZE, when set and not empty, decides (its value comes from ReadKnobs: a number clamped
    // to 0..2, text that is not a number 0); else the setting, read every frame.
    static const StrengthKnob::Env env = [] {
        StrengthKnob::Env read;
        const char* text = std::getenv("BB_HEAT_HAZE");
        read.set = text != nullptr && text[0] != '\0';
        read.value = read.set ? ReadKnobs().strength : 0.0f;
        return read;
    }();
    return StrengthKnob::Pick(
        env, BbSettings::Get().graphics_heat_haze_strength.load(std::memory_order_relaxed),
        BbHeatHaze::MaxStrength, BbHeatHaze::DefaultStrength);
}

void HeatHaze::StrengthLine() {
    static StrengthKnob::Line line;
    const StrengthKnob::Value s = Strength();
    if (line.Due(LineFrames, s)) {
        BbReport::Printf("Heat haze (r97e): strength %.2f from the %s (%s)%s\n", double(s.value),
                         StrengthKnob::SourceName(s),
                         s.from_env ? "BB_HEAT_HAZE" : "graphics_heat_haze_strength",
                         s.value > 0.0f ? "" : "; 0: off, nothing is drawn");
    }
}

HeatHaze::HeatHaze(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_}, knobs{ReadKnobs()} {
    // The pipeline is made here, at the start (no compile in play); the atlas at the first
    // frame with a column, at that scene's size.
    made = EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
           EffectPass::Create(instance, set_layout, layout, pipeline,
                              {StorageImage, StorageImage, SampledImage,
                               vk::DescriptorType::eStorageBuffer}, // r97b: the counters
                              sizeof(BbHeatHaze::Push), HEAT_HAZE_COMP, "Heat haze") &&
           // bbport (r97b_heat-haze-paths): the pixel counters, 64 bytes on the GPU and 64 in
           // host memory
           MakeBuffer(counter_buffer, BbHeatHaze::CounterWords * 4, false,
                      vk::BufferUsageFlagBits::eStorageBuffer |
                          vk::BufferUsageFlagBits::eTransferSrc |
                          vk::BufferUsageFlagBits::eTransferDst) &&
           MakeBuffer(counter_host, BbHeatHaze::CounterWords * 4, true,
                      vk::BufferUsageFlagBits::eTransferDst);
    if (made) {
        std::memset(counter_host.mapped, 0, BbHeatHaze::CounterWords * 4);
    }
    std::printf("Heat haze (r97, strength %.2f): %s; a shimmer in a column above each flame "
                "(a warm lamp of the game's lamp pass), at most %u columns a frame, up to %.0f m "
                "away, drawn into the scene colour right before the upscaler (under the HUD); "
                "test view %s\n",
                double(Strength().value), made ? "on" : "off - the pass could not be made",
                BbHeatHaze::MaxColumns, double(BbHeatHaze::FadeEnd),
                knobs.show ? "on (BB_HEAT_HAZE_SHOW=1 or 2: 3 times the shimmer, the columns tinted)"
                           : "off");
    // bbport (r97b_heat-haze-paths)
    std::printf("Heat haze (r97b): depth tests %s; test view 2 (rectangles outlined, no depth test) "
                "%s; the haze pass counts its pixels for the log\n",
                knobs.depth ? "on" : "off (BB_HEAT_HAZE_DEPTH=0 or BB_HEAT_HAZE_SHOW=2)",
                knobs.outline ? "on" : "off");
    // bbport (r97c_heat-haze-visible)
    std::printf("Heat haze (r97c): shimmer up to %.3f m at the flame's distance (at most %.0f pixels per "
                "1080 rows) at strength 1, the noise's root mean square 0.49 of that, the weight 1 - t "
                "above the flame (r97: 0.03 m, 8 pixels, 0.30, (1 - t)^1.5)\n",
                double(BbHeatHaze::AmplitudeM), double(BbHeatHaze::MaxAmplitudePx));
    // bbport (r97d_heat-haze-real-shimmer)
    std::printf("Heat haze (r97d): the log also counts the applied offset of every written pixel; proof "
                "view (BB_HEAT_HAZE_PROOF=1, written pixels 30%% magenta) %s\n",
                knobs.proof ? "on" : "off");
    // bbport (r97f_haze-per-flame): the flame finder, unless BB_HEAT_HAZE_FLAMES=0
    flames = BbHeatHaze::ParseFlames(std::getenv("BB_HEAT_HAZE_FLAMES"));
    blob_min = BbHeatHaze::ParseBlobMin(std::getenv("BB_HEAT_HAZE_FLAME_MIN"));
    if (made && flames != BbHeatHaze::FlameMode::Off) {
        find_made = EffectPass::Create(instance, find_set_layout, find_layout, find_pipeline,
                                       {StorageImage, vk::DescriptorType::eStorageBuffer},
                                       sizeof(BbHeatHaze::FindPush), HEAT_HAZE_FIND_COMP,
                                       "Heat haze flames") &&
                    MakeBuffer(find_buffer, BbHeatHaze::FindBytes, false,
                               vk::BufferUsageFlagBits::eStorageBuffer |
                                   vk::BufferUsageFlagBits::eTransferSrc |
                                   vk::BufferUsageFlagBits::eTransferDst) &&
                    MakeBuffer(find_host, BbHeatHaze::FindBytes, true,
                               vk::BufferUsageFlagBits::eTransferDst);
        if (find_made) {
            std::memset(find_host.mapped, 0, BbHeatHaze::FindBytes);
        }
    }
    if (flames != BbHeatHaze::FlameMode::Off) {
        std::printf("Heat haze (r97f): flames %d (BB_HEAT_HAZE_FLAMES; 0 the columns stand on the lamps' "
                    "lights, 1 on the flames found around each lamp, 2 also on the light of a lamp with "
                    "none found yet): %s; each frame a scan of the %u nearest lamps' surroundings (a "
                    "%.0f m square of the view plane, %ux%u cells) in the scene colour, a flame is a "
                    "cell at least %.2f HDR luma above its surround (BB_HEAT_HAZE_FLAME_MIN), up to %u "
                    "a lamp\n",
                    int(flames), find_made ? "on" : "off - the pass could not be made",
                    BbHeatHaze::MaxScans, double(2.0f * BbHeatHaze::ScanHalfM), HF_GRID, HF_GRID,
                    double(blob_min), BbHeatHaze::MaxAnchors);
    }
}

HeatHaze::~HeatHaze() {
    const auto device = instance.GetDevice();
    FreeBuffer(counter_buffer); // bbport (r97b_heat-haze-paths)
    FreeBuffer(counter_host);
    FreeBuffer(find_buffer); // bbport (r97f_haze-per-flame)
    FreeBuffer(find_host);
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

// bbport (r97b_heat-haze-paths): a buffer of the pixel counters (as Halation::MakeBuffer).
bool HeatHaze::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void HeatHaze::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

// bbport (r97b_heat-haze-paths): what the haze pass did with its pixels since the last line, and the
// nearest column's flame pixel: the numbers that say why a column the CPU drew shows nothing (the
// column's shape, the depth image read before the upscaler, or a write lost after this pass).
void HeatHaze::ReportPixels() {
    if (!counter_host.mapped) {
        return;
    }
    std::array<u32, BbHeatHaze::CounterWords> now{};
    std::memcpy(now.data(), counter_host.mapped, sizeof(now));
    const auto c = BbHeatHaze::CountsBetween(now.data(), counters_seen.data());
    const bool flame_seen = now[HH_WORD_FLAME_SEEN] != counters_seen[HH_WORD_FLAME_SEEN];
    const auto previous = counters_seen; // bbport (r97d)
    counters_seen = now;
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    BbReport::Printf("Heat haze (r97b): of %llu column pixels %llu tested (depth tests %s): %llu "
                     "written, %llu nearer than the flame, %llu taking a nearer pixel; %llu outside "
                     "the column's shape\n",
                     ull(c.rect), ull(c.Tested()), knobs.depth ? "on" : "off, counted only",
                     ull(c.written), ull(c.nearer), ull(c.source), ull(c.shape));
    BbReport::Printf("Heat haze (r97b): the depth puts the tested pixels %llu nowhere, %llu under "
                     "half the flame's view z, %llu short of the test's limit, %llu behind it, "
                     "%llu at the sky\n",
                     ull(c.z_bad), ull(c.z_close), ull(c.z_front), ull(c.z_behind), ull(c.sky));
    BbReport::Printf("Heat haze (r97b): %s\n", BbHeatHaze::Verdict(c));
    if (flame_seen) {
        const auto word = [&](u32 w) { return double(std::bit_cast<float>(now[w])); };
        BbReport::Printf("Heat haze (r97b): nearest flame's pixel: depth %.6f = view z %.2f m; its "
                         "lamp's view z %.2f m would read %.6f; the depth test's limit %.2f m\n",
                         word(HH_WORD_FLAME_DEPTH), word(HH_WORD_FLAME_Z),
                         word(HH_WORD_FLAME_LAMP_Z), word(HH_WORD_FLAME_EXPECT),
                         word(HH_WORD_FLAME_FRONT));
    }
    // bbport (r97d_heat-haze-real-shimmer): the offsets the written pixels really took
    const auto o = BbHeatHaze::OffsetsBetween(now.data(), previous.data());
    const double k = double(out_scale);
    BbReport::Printf("Heat haze (r97d): offset of %llu written pixels, render px: mean %.2f, 95%% under "
                     "%.2f, largest since start %.2f; output px (x%.2f): mean %.2f, 95%% under %.2f, "
                     "largest %.2f; proof view %s\n",
                     ull(o.pixels), o.mean, o.p95_below, o.largest, k, o.mean * k, o.p95_below * k,
                     o.largest * k, knobs.proof ? "on" : "off");
}

void HeatHaze::NoSceneHooks() {
    std::printf("Heat haze (r97): not drawn - the upscaler is not available (BB_UPSCALER=none, or "
                "this GPU cannot run it), and the haze is drawn right before it\n");
}

vk::ImageView HeatHaze::CachedView(const VideoCore::Image& image, vk::ImageAspectFlags aspect) {
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
        .view = Check<"create heat haze view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = image.info.pixel_format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool HeatHaze::EnsureAtlas(u32 width, u32 height) {
    if (atlas_image && atlas_width == width && atlas_height == height) {
        return true;
    }
    if (width == refused_width && height == refused_height) {
        return false;
    }
    const vk::DeviceSize bytes = 8ull * width * height;
    if (!EffectPass::HasRoom(instance, bytes)) {
        refused_width = width;
        refused_height = height;
        std::printf("Heat haze (r97): no room in video memory for its atlas of %ux%u (%llu bytes); "
                    "asked again when the scene's size changes\n",
                    width, height, static_cast<unsigned long long>(bytes));
        return false;
    }
    refused_width = refused_height = 0;
    if (atlas_image) {
        scheduler.DeferOperation(
            [image = std::move(atlas_image), view = std::move(atlas_view)]() mutable {
                view.reset();
                image.Destroy();
            });
    }
    const auto device = instance.GetDevice();
    atlas_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    atlas_image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(atlas_image), "Heat haze atlas");
    atlas_view = Check<"create heat haze atlas view">(device.createImageViewUnique({
        .image = vk::Image(atlas_image),
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR16G16B16A16Sfloat,
        .subresourceRange = ColorRange,
    }));
    atlas_width = width;
    atlas_height = height;
    std::printf("Heat haze (r97): atlas %ux%u RGBA16F (%llu bytes) for a scene of %ux%u\n", width,
                height, static_cast<unsigned long long>(bytes), width * 2, height * 2);
    return true;
}

void HeatHaze::Apply(VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                     std::array<float, 2> jitter, const std::array<float, 3>& wind) {
    ++stats.frames;
    const auto lamps = collector.Lamps();
    stats.records += collector.Records();
    stats.others += collector.Others();
    stats.dropped += collector.Dropped();
    stats.beyond += collector.Beyond();
    stats.flames += lamps.size();
    // The frame's lamps are used once: the next frame gathers its own (a frame that draws no
    // G-buffer pass gathers none).
    // The first line after FirstLineFrames (a short test run sees it), then every LineFrames.
    const auto done = [&] {
        collector.Clear();
        if (stats.frames >= (reported ? LineFrames : FirstLineFrames)) {
            reported = true;
            Report();
        }
    };
    if (!made || lamps.empty() || !color_id || !depth_id) {
        done();
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (camera_motion.PreviewFrame() || !camera.valid) {
        ++stats.no_camera;
        done();
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        ++stats.no_scene;
        done();
        return;
    }
    // The scene's size is the reduced one while a preset renders below the game's own size,
    // else the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    if (width < 16 || height < 16) {
        done();
        return;
    }
    const BbHeatHaze::Camera view{camera.view, camera.inv_view, camera.proj, width, height, jitter};
    const auto atlas = BbHeatHaze::AtlasFor(width, height);
    BbHeatHaze::Counts counts;
    // bbport (r97f_haze-per-flame): with the flame finder, the columns stand on the flames found around
    // each lamp (the table's), this frame's scans are planned, and the answers of earlier ones read
    std::vector<BbHeatHaze::ScanJob> scans;
    std::vector<BbHeatHaze::Lamp> flame_sources;
    std::span<const BbHeatHaze::Lamp> sources = lamps;
    if (find_made) {
        PrepareFlames(view, lamps, scans, flame_sources);
        sources = flame_sources;
    }
    const auto columns =
        BbHeatHaze::Choose(sources, view, Strength().value, knobs.show, wind, atlas, counts); // r97e, r97f
    stats.unseen += counts.unseen;
    stats.over += counts.over;
    stats.no_room += counts.no_room;
    const bool want_scan = find_made && !scans.empty(); // bbport (r97f_haze-per-flame)
    if (columns.empty() && !want_scan) {
        done();
        return;
    }
    if (!columns.empty() && !EnsureAtlas(atlas.width, atlas.height)) {
        ++stats.no_memory;
        done();
        return;
    }
    const SceneUseScope scene_use{"heat haze"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{};
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
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // bbport (r97d_heat-haze-real-shimmer): render pixels -> output pixels, and once which image
    // the pass writes: the one the upscaler is handed (Rasterizer: upscaler->SceneColor()), which
    // TemporalUpscaler::Run reads by the same id (its reduced proxy when the scene is reduced).
    out_scale = float(color.info.size.width) / float(width);
    if (!told_image) {
        told_image = true;
        std::printf("Heat haze (r97d): the pass writes scene colour image id %u (handle %llx, format %d, "
                    "native %ux%u, scene %ux%u, %s): the upscaler's colour input is that same id (%s), "
                    "1 render pixel = %.2f output pixels\n",
                    u32(color_id.index), static_cast<unsigned long long>(reinterpret_cast<std::uintptr_t>(VkImage(color.GetImage()))),
                    int(color.info.pixel_format), color.info.size.width, color.info.size.height, width,
                    height, reduced ? "through the reduced proxy" : "the native image",
                    reduced ? "Run reads scene_targets.Read(scene_color) too" : "Run reads it directly",
                    double(out_scale));
    }
    if (want_scan) { // bbport (r97f_haze-per-flame): the scan, before the haze changes the colour it reads
        RecordFind(scans, color_view);
    }
    if (columns.empty()) {
        done();
        return;
    }
    // Real time (wrapped, for the floats), so the shimmer rises at its speed at any frame rate.
    const float time = float(std::fmod(
        std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count(), 4096.0));
    std::array<BbHeatHaze::Push, BbHeatHaze::MaxColumns> pushes{};
    // barrier[i]: column i's rectangle overlaps one drawn before it; its haze waits for theirs.
    std::array<bool, BbHeatHaze::MaxColumns> barrier{};
    const u32 count = u32(std::min<std::size_t>(columns.size(), BbHeatHaze::MaxColumns));
    for (u32 i = 0; i < count; ++i) {
        pushes[i] = columns[i].push;
        pushes[i].clock[2] = time;
        // bbport (r97b_heat-haze-paths): the test view 2, the depth tests' switch and the nearest
        // column (the last one: they come farthest first) keeping its flame pixel's depth
        pushes[i].atlas[3] |= (knobs.outline ? BbHeatHaze::FlagOutline : 0) |
                              (knobs.depth ? 0 : BbHeatHaze::FlagNoDepth) |
                              (i + 1 == count ? BbHeatHaze::FlagProbe : 0) |
                              (knobs.proof ? BbHeatHaze::FlagProof : 0); // r97d
        for (u32 j = 0; j < i && !barrier[i]; ++j) {
            barrier[i] = Overlap(pushes[i].rect, pushes[j].rect);
        }
        stats.pixels += u64(pushes[i].rect[2]) * u64(pushes[i].rect[3]);
        stats.most_px = std::max(stats.most_px, pushes[i].shape[2]);
        stats.nearest = stats.columns == 0 && i == 0
                            ? columns[i].distance
                            : std::min(stats.nearest, columns[i].distance);
    }
    stats.columns += count;
    ++stats.lit;
    if (!told_size) {
        told_size = true;
        std::printf("Heat haze (r97): first columns drawn, %u at a scene of %ux%u (%s)\n", count,
                    width, height, reduced ? "reduced scene" : "the game's scene");
    }
    // bbport (r97b_heat-haze-paths): the counters start at zero (filled at the first drawing frame)
    const bool zero_counters = !std::exchange(counters_zeroed, true);
    EffectPass::Mark(ProfileRow, "heat haze");
    scheduler.RecordCrumb(
        {.name = "heat haze"},
        [pushes, barrier, count, color_view, depth_view, atlas_handle = vk::Image(atlas_image),
         atlas_handle_view = *atlas_view, pass_pipeline = *pipeline,
         pass_layout = *layout, counters = counter_buffer.buffer, host = counter_host.buffer,
         zero_counters](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (zero_counters) { // bbport (r97b_heat-haze-paths)
                cmdbuf.fillBuffer(counters, 0, VK_WHOLE_SIZE, 0);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            }
            // The atlas is written anew where it is read; what it held before is of no use.
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = ReadWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = atlas_handle,
                .subresourceRange = ColorRange,
            };
            cmdbuf.pipelineBarrier2(
                {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const std::array infos{Info(color_view), Info(atlas_handle_view), Info(depth_view)};
            // bbport (r97b_heat-haze-paths): binding 3, the pixel counters
            const vk::DescriptorBufferInfo counter_info{counters, 0, VK_WHOLE_SIZE};
            const std::array writes{Write(0, StorageImage, &infos[0]),
                                    Write(1, StorageImage, &infos[1]),
                                    Write(2, SampledImage, &infos[2]),
                                    vk::WriteDescriptorSet{.dstBinding = 3, .descriptorCount = 1,
                                                           .descriptorType =
                                                               vk::DescriptorType::eStorageBuffer,
                                                           .pBufferInfo = &counter_info}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            for (const s32 pass : {BbHeatHaze::PassCopy, BbHeatHaze::PassHaze}) {
                for (u32 i = 0; i < count; ++i) {
                    if (pass == BbHeatHaze::PassHaze && barrier[i]) {
                        EffectPass::ComputeBarrier(cmdbuf);
                    }
                    BbHeatHaze::Push push = pushes[i];
                    push.atlas[2] = pass;
                    cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(push), &push);
                    cmdbuf.dispatch((u32(push.rect[2]) + 7) / 8, (u32(push.rect[3]) + 7) / 8, 1);
                }
                if (pass == BbHeatHaze::PassCopy) {
                    EffectPass::ComputeBarrier(cmdbuf);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            // bbport (r97b_heat-haze-paths): the counters' totals into the host copy
            cmdbuf.copyBuffer(counters, host, vk::BufferCopy{0, 0, BbHeatHaze::CounterWords * 4});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    done();
}

// bbport (r97f_haze-per-flame): the answers of the scans a frame or two back into the table, this frame's
// scans, and the places the columns stand on (a found flame each).
void HeatHaze::PrepareFlames(const BbHeatHaze::Camera& view, std::span<const BbHeatHaze::Lamp> lamps,
                             std::vector<BbHeatHaze::ScanJob>& scans,
                             std::vector<BbHeatHaze::Lamp>& sources) {
    ReadFinds(view);
    ++find_frame;
    scans = BbHeatHaze::PlanScans(lamps, flame_table, view, u32(find_frame), find_frame, blob_min);
    BbHeatHaze::FlameCounts counted;
    sources = BbHeatHaze::FlameSources(lamps, flame_table, view, flames, counted);
    flame_stats.scans += scans.size();
    flame_stats.anchored += counted.anchored;
    flame_stats.empty += counted.empty;
    flame_stats.unscanned += counted.unscanned;
    flame_stats.flames += counted.flames;
}

// The finder's host copy (a frame or two old, as the GPU left it): every block with a new tag goes to the
// table. A block the copy was still writing fails its check and is skipped (it is rewritten next frame).
void HeatHaze::ReadFinds(const BbHeatHaze::Camera& view) {
    if (!find_host.mapped) {
        return;
    }
    std::array<u32, BbHeatHaze::FindWords> now{};
    std::memcpy(now.data(), find_host.mapped, sizeof(now));
    for (u32 slot = 0; slot < BbHeatHaze::MaxScans; ++slot) {
        BbHeatHaze::Block block;
        const auto kind = BbHeatHaze::ReadBlock(now.data() + slot * HF_BLOCK_WORDS, block);
        if (kind == BbHeatHaze::ReadKind::Torn) {
            ++flame_stats.torn;
            continue;
        }
        if (kind == BbHeatHaze::ReadKind::Bad) {
            ++flame_stats.bad;
            continue;
        }
        if (kind != BbHeatHaze::ReadKind::Ok) {
            continue;
        }
        const auto result = flame_table.Apply(block, view.inv_view);
        if (result == BbHeatHaze::ApplyResult::Unknown) {
            ++flame_stats.unknown;
            continue;
        }
        if (result == BbHeatHaze::ApplyResult::Same) {
            continue;
        }
        ++flame_stats.answers;
        flame_stats.blob_max = std::max(flame_stats.blob_max, block.best);
        flame_stats.bright_max = std::max(flame_stats.bright_max, block.bright);
        if (result == BbHeatHaze::ApplyResult::Anchors) {
            ++flame_stats.with_flames;
        } else {
            ++flame_stats.none;
        }
    }
}

// The scans of one frame: a workgroup each, reading the scene colour, into the finder's buffer, copied to
// the host copy. Recorded before the haze (it reads the colour the haze is about to change).
void HeatHaze::RecordFind(const std::vector<BbHeatHaze::ScanJob>& scans, vk::ImageView color_view) {
    std::array<BbHeatHaze::FindPush, BbHeatHaze::MaxScans> pushes{};
    const u32 count = u32(std::min<std::size_t>(scans.size(), BbHeatHaze::MaxScans));
    for (u32 i = 0; i < count; ++i) {
        pushes[i] = scans[i].push;
    }
    const bool zero = !std::exchange(find_zeroed, true);
    EffectPass::Mark(ProfileRow, "heat haze");
    scheduler.RecordCrumb(
        {.name = "heat haze flames"},
        [pushes, count, color_view, pass_pipeline = *find_pipeline, pass_layout = *find_layout,
         blocks = find_buffer.buffer, host = find_host.buffer, zero](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            if (zero) {
                cmdbuf.fillBuffer(blocks, 0, VK_WHOLE_SIZE, 0);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            }
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pass_pipeline);
            const vk::DescriptorImageInfo image_info = Info(color_view);
            const vk::DescriptorBufferInfo buffer_info{blocks, 0, VK_WHOLE_SIZE};
            const std::array writes{Write(0, StorageImage, &image_info),
                                    vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                                           .descriptorType =
                                                               vk::DescriptorType::eStorageBuffer,
                                                           .pBufferInfo = &buffer_info}};
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, pass_layout, 0, writes);
            for (u32 i = 0; i < count; ++i) {
                cmdbuf.pushConstants(pass_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(BbHeatHaze::FindPush), &pushes[i]);
                cmdbuf.dispatch(1, 1, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands, MemoryAll);
            cmdbuf.copyBuffer(blocks, host, vk::BufferCopy{0, 0, BbHeatHaze::FindBytes});
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                      vk::AccessFlagBits2::eTransferWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
}

void HeatHaze::ReportFlames() {
    if (!find_made) {
        return;
    }
    const auto ull = [](u64 v) { return static_cast<unsigned long long>(v); };
    const double f = std::max(1.0, double(stats.frames));
    BbReport::Printf("Heat haze (r97f): flames %d: %llu lamps scanned (%.1f a frame), %llu answers read "
                     "(%llu found flames, %llu none), %llu torn, %llu unusable, %llu of a lamp no longer "
                     "kept; lamp frames: %llu on found flames (%llu flames), %llu none found, %llu not "
                     "answered yet\n",
                     int(flames), ull(flame_stats.scans), double(flame_stats.scans) / f,
                     ull(flame_stats.answers), ull(flame_stats.with_flames), ull(flame_stats.none),
                     ull(flame_stats.torn), ull(flame_stats.bad), ull(flame_stats.unknown),
                     ull(flame_stats.anchored), ull(flame_stats.flames), ull(flame_stats.empty),
                     ull(flame_stats.unscanned));
    BbReport::Printf("Heat haze (r97f): strongest blob %.2f and brightest cell %.2f (HDR luma) since the "
                     "last line; a flame needs a blob of %.2f (BB_HEAT_HAZE_FLAME_MIN)\n",
                     double(flame_stats.blob_max), double(flame_stats.bright_max), double(blob_min));
    flame_stats = {};
}

void HeatHaze::Report() {
    const double f = std::max(1.0, double(stats.frames));
    const double drawn = std::max(1.0, double(stats.lit));
    BbReport::Printf(
        "Heat haze (r97): of %u frames before the upscaler %u drew columns, %.2f a frame (%llu in "
        "all); a frame %.1f flames kept among %.1f light records (%.1f records not of a flame, "
        "%.1f flame records behind the camera or beyond %.0f m, %llu flame records over %u); %llu "
        "kept flames without a column (off the screen, too short or too small), %llu columns "
        "beyond %u, %llu without room in the atlas; %u frames without a "
        "camera, %u whose scene colour was not writable, %u without video memory for the atlas; "
        "nearest flame with a column %.1f m, largest shimmer %.1f px, %.0f pixels under the "
        "columns a drawing frame\n",
        stats.frames, stats.lit, double(stats.columns) / f,
        static_cast<unsigned long long>(stats.columns), double(stats.flames) / f,
        double(stats.records) / f, double(stats.others) / f, double(stats.beyond) / f,
        double(BbHeatHaze::FadeEnd), static_cast<unsigned long long>(stats.dropped),
        BbHeatHaze::MaxLamps, static_cast<unsigned long long>(stats.unseen),
        static_cast<unsigned long long>(stats.over), BbHeatHaze::MaxColumns,
        static_cast<unsigned long long>(stats.no_room), stats.no_camera, stats.no_scene,
        stats.no_memory, double(stats.nearest), double(stats.most_px),
        double(stats.pixels) / drawn);
    ReportPixels(); // bbport (r97b_heat-haze-paths)
    ReportFlames(); // bbport (r97f_haze-per-flame)
    stats = {};
}

} // namespace Vulkan
