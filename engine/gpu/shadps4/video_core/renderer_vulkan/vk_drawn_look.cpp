// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_drawn_look.h"

#include <algorithm>
#include <bit>
#include <cstdio>
#include <cstdlib>

#include "bbport_drawn_look_texts.h" // bbport (r55_drawn-look-lines)
#include "bbport_settings.h"
#include "bbport_toggles.h"
#include "video_core/host_shaders/paint_ink_comp.h"
#include "video_core/host_shaders/paint_key_comp.h"
#include "video_core/host_shaders/paint_key_last_comp.h"
#include "video_core/host_shaders/paint_lock_comp.h"
#include "video_core/host_shaders/paint_lock_down_comp.h"
#include "video_core/host_shaders/paint_lock_first_comp.h"
#include "video_core/host_shaders/paint_mips_comp.h"
#include "video_core/host_shaders/paint_prep_comp.h"
#include "video_core/host_shaders/paint_stats_comp.h"
#include "video_core/host_shaders/paint_strokes_comp.h"
#include "video_core/renderer_vulkan/drawn_look_params.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"

namespace Vulkan {
namespace {
constexpr vk::ImageSubresourceRange AllLevels{vk::ImageAspectFlagBits::eColor, 0,
                                              VK_REMAINING_MIP_LEVELS, 0, 1};
/// More levels than any scene has (a level a halving, down to one texel).
constexpr u32 MaxLevels = 16;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto SampledImage = vk::DescriptorType::eSampledImage;
constexpr auto StorageImage = vk::DescriptorType::eStorageImage;
constexpr auto Sampled = vk::DescriptorType::eCombinedImageSampler;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
// The knobs' defaults are written twice: for the renderer (DrawnLookParams::Knobs) and for the
// ini (bbport_settings.h).
static_assert(DrawnLookParams::Knobs{}.strength == BbSettings::DrawnLookStrengthDefault &&
              DrawnLookParams::Knobs{}.stroke_size == BbSettings::DrawnLookStrokeSizeDefault &&
              DrawnLookParams::Knobs{}.texture == BbSettings::DrawnLookTextureDefault &&
              DrawnLookParams::Knobs{}.outlines == BbSettings::DrawnLookOutlinesDefault &&
              DrawnLookParams::Knobs{}.ink_world == BbSettings::DrawnLookInkWorldDefault &&
              DrawnLookParams::Knobs{}.characters == BbSettings::DrawnLookCharactersDefault);

vk::DescriptorImageInfo Info(vk::ImageView view, vk::Sampler sampler = {}) {
    return {.sampler = sampler, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

/// The levels of an image this wide and high, down to one texel.
u32 LevelsOf(u32 width, u32 height) {
    return std::min(u32(std::bit_width(std::max(width, height))), MaxLevels);
}

vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                             const vk::DescriptorImageInfo* image) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type,
            .pImageInfo = image};
}
}

DrawnLook::DrawnLook(const Instance& instance_, Scheduler& scheduler_,
                     VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                     SceneTargets& scene_targets_, CameraMotion& camera_motion_,
                     ObjectMotion& object_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_},
      object_motion{object_motion_} {
    // Not a key of its own in the ini: a test view that a menu change saved there would stay on.
    if (const char* env = std::getenv("BB_DRAWN_LOOK_VIEW")) {
        env_view = std::clamp(std::atoi(env), int(DrawnLookParams::ViewOff),
                              int(DrawnLookParams::ViewMax));
    }
    env_line = DrawnLookParams::LineScaleOf(std::getenv("BB_DRAWN_LOOK_LINE"));
}

DrawnLook::~DrawnLook() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
}

bool DrawnLook::Wanted() {
    const auto& s = BbSettings::Get();
    return DrawnLookParams::Wanted(s.graphics_drawn_look.load(std::memory_order_relaxed),
                                   s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
                                   s.graphics_drawn_look_ink_world.load(std::memory_order_relaxed));
}

void DrawnLook::NoSceneHooks() {
    BbSettings::Get().drawn_look_problem = BbSettings::DrawnLookTexts::NoUpscaler.english;
}

void DrawnLook::Fail(const char* why) {
    failed = true;
    BbSettings::Get().drawn_look_problem = why;
    std::printf("Drawn look: off - %s\n", why);
    // Nothing is painted any more: what was made for it goes now, not when the switch does.
    ReleaseAll();
}

void DrawnLook::ReleaseAll() {
    ReleaseImage(prep_copy);
    ReleaseImage(marks);
    ReleaseImage(lock_means);
    ReleaseViews();
}

bool DrawnLook::SceneDepth(VideoCore::ImageId depth) const {
    return !scene_depths[0] ||
           std::find(scene_depths.begin(), scene_depths.end(), depth) != scene_depths.end();
}

bool DrawnLook::CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                           std::span<const u32> code, const char* name) {
    return EffectPass::Create(instance, pass.set_layout, pass.layout, pass.pipeline, types,
                              sizeof(DrawnLookParams::Params), code, name);
}

bool DrawnLook::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    // The strokes read their colours between the levels of the copy: a sampler of this class's
    // own (EffectPass::CreateSampler's reads one level).
    auto levels_sampler = instance.GetDevice().createSamplerUnique({
        .magFilter = vk::Filter::eLinear,
        .minFilter = vk::Filter::eLinear,
        .mipmapMode = vk::SamplerMipmapMode::eLinear,
        .addressModeU = vk::SamplerAddressMode::eClampToEdge,
        .addressModeV = vk::SamplerAddressMode::eClampToEdge,
        .addressModeW = vk::SamplerAddressMode::eClampToEdge,
        .maxLod = VK_LOD_CLAMP_NONE,
    });
    const bool made =
        levels_sampler.result == vk::Result::eSuccess &&
        EffectPass::StorageFormat(instance, vk::Format::eR16G16B16A16Sfloat) &&
        CreatePass(prep, {SampledImage, SampledImage, StorageImage}, PAINT_PREP_COMP,
                   "Drawn look prep") &&
        CreatePass(stats, {SampledImage, StorageImage, StorageImage}, PAINT_STATS_COMP,
                   "Drawn look stats") &&
        CreatePass(mips, {Sampled, Sampled, StorageImage, StorageImage}, PAINT_MIPS_COMP,
                   "Drawn look mips") &&
        CreatePass(key_sums, {SampledImage, StorageImage}, PAINT_KEY_COMP,
                   "Drawn look key sums") &&
        CreatePass(key_last, {SampledImage, StorageImage}, PAINT_KEY_LAST_COMP,
                   "Drawn look key") &&
        CreatePass(strokes,
                   {Sampled, SampledImage, SampledImage, SampledImage, StorageImage, Sampled},
                   PAINT_STROKES_COMP, "Drawn look strokes") &&
        CreatePass(lock_first, {SampledImage, StorageImage}, PAINT_LOCK_FIRST_COMP,
                   "Drawn look lock means") &&
        CreatePass(lock_down, {Sampled, StorageImage}, PAINT_LOCK_DOWN_COMP,
                   "Drawn look lock levels") &&
        CreatePass(lock, {Sampled, SampledImage, SampledImage, StorageImage, Sampled},
                   PAINT_LOCK_COMP, "Drawn look lock") &&
        CreatePass(ink, {Sampled, SampledImage, StorageImage}, PAINT_INK_COMP, "Drawn look ink");
    if (!made) {
        Fail(BbSettings::DrawnLookTexts::NoPasses.english);
        return false;
    }
    sampler = std::move(levels_sampler.value);
    return true;
}

void DrawnLook::ReleaseImage(OwnImage& own) {
    if (own.image) {
        scheduler.DeferOperation([image = std::move(own.image), view = std::move(own.view),
                                  levels = std::move(own.levels)]() mutable {
            levels.clear();
            view.reset();
            image.Destroy();
        });
    }
    own.levels.clear();
    own.width = 0;
    own.height = 0;
}

bool DrawnLook::EnsureImage(OwnImage& own, u32 width, u32 height, vk::Format format,
                            const char* name) {
    if (own.image && own.width == width && own.height == height) {
        return false;
    }
    ReleaseImage(own);
    const auto device = instance.GetDevice();
    const u32 levels = LevelsOf(width, height);
    own.image = VideoCore::UniqueImage(device, instance.GetAllocator());
    own.image.Create(vk::ImageCreateInfo{
        .imageType = vk::ImageType::e2D,
        .format = format,
        .extent = {width, height, 1},
        .mipLevels = levels,
        .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    SetObjectName(device, vk::Image(own.image), "Drawn look {}", name);
    own.view = Check<"create drawn look image view">(device.createImageViewUnique({
        .image = vk::Image(own.image),
        .viewType = vk::ImageViewType::e2D,
        .format = format,
        .subresourceRange = AllLevels,
    }));
    for (u32 level = 0; level < levels; ++level) {
        own.levels.push_back(Check<"create drawn look level view">(device.createImageViewUnique({
            .image = vk::Image(own.image),
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {vk::ImageAspectFlagBits::eColor, level, 1, 0, 1},
        })));
    }
    own.width = width;
    own.height = height;
    return true;
}

vk::ImageView DrawnLook::CachedView(const VideoCore::Image& image, vk::Format format,
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
        .view = Check<"create drawn look view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void DrawnLook::ReleaseViews() {
    const auto device = instance.GetDevice();
    for (auto& entry : view_cache) {
        if (entry.view) {
            scheduler.DeferOperation(
                [device, view = entry.view] { device.destroyImageView(view); });
        }
        entry = {};
    }
}

void DrawnLook::OnGBufferDraw(VideoCore::ImageId depth, VideoCore::ImageId normal) {
    gbuffer_depth = depth;
    gbuffer_normal = normal;
}

void DrawnLook::OnSmallTransparent(u64 hash, u32 indices) {
    small_hash = hash;
    small_indices = indices;
    small_pending = true;
}

void DrawnLook::OnBlendedScene(VideoCore::ImageId color, VideoCore::ImageId depth,
                               std::array<float, 2> jitter) {
    const bool small = small_pending;
    small_pending = false;
    if (!SceneDepth(depth)) {
        return;
    }
    // The frame's first transparent draw is a small one: its state told it from a full-screen
    // pass (DrawnLookParams::SmallTransparent). Each shader that does this is named once, so a
    // lighting pass taken for a particle (the strokes would go in before the light is
    // complete) shows in the log.
    if (small && !blended_this_frame && frame_result == NotReached &&
        std::find(small_seen.begin(), small_seen.begin() + small_seen_count, small_hash) ==
            small_seen.begin() + small_seen_count) {
        if (small_seen_count < small_seen.size()) {
            small_seen[small_seen_count++] = small_hash;
            std::printf("Drawn look: a frame's first transparent draw is a small one (%u indices, "
                        "ps %016llx): blended, no depth written, depth tested; the strokes are "
                        "painted before it\n",
                        small_indices, static_cast<unsigned long long>(small_hash));
        }
    }
    blended_this_frame = true;
    Paint(AtBlended, color, depth, jitter);
}

void DrawnLook::OnSceneComposite(u64 hash, VideoCore::ImageId color, VideoCore::ImageId depth,
                                 std::array<float, 2> jitter) {
    // The passes of another view of the world (a reflection) are not the scene's: not counted.
    if (!SceneDepth(depth)) {
        return;
    }
    // Which of this shader's full-screen passes of the frame this one is. A frame with more
    // shaders than there is room for does not tell the later ones apart: they match nothing.
    u32 nth = ~0u;
    const auto seen = std::find_if(frame_passes.begin(), frame_passes.begin() + frame_pass_count,
                                   [hash](const FullScreenPass& pass) { return pass.hash == hash; });
    if (seen != frame_passes.begin() + frame_pass_count) {
        nth = seen->nth++;
    } else if (frame_pass_count < frame_passes.size()) {
        frame_passes[frame_pass_count++] = {hash, 1};
        nth = 0;
    }
    if (blended_this_frame) {
        // The first pass after the first transparents. On a frame that was painted before the
        // remembered pass (it had no transparents by then) this one comes after that pass: it
        // tells nothing.
        if (!composite_this_frame && frame_result != AtComposite) {
            composite_this_frame = true;
            if (composite.hash == hash && composite.nth == nth) {
                candidate_frames = 0;
            } else {
                if (candidate.hash != hash || candidate.nth != nth) {
                    candidate = {hash, nth};
                    candidate_frames = 0;
                }
                if (composite.hash == 0 || ++candidate_frames >= CompositeFrames) {
                    composite = candidate;
                    candidate_frames = 0;
                    // Areas differ in it; a game that changed it often would fill the log.
                    if (composite_changes < 8) {
                        ++composite_changes;
                        std::printf("Drawn look: the full-screen pass after the first "
                                    "transparents is ps %016llx (number %u of it in the "
                                    "frame): a frame without transparents is painted before "
                                    "that pass\n",
                                    static_cast<unsigned long long>(hash), nth + 1);
                    }
                }
            }
        }
        return;
    }
    if (composite.hash != 0 && composite.hash == hash && composite.nth == nth) {
        Paint(AtComposite, color, depth, jitter);
    }
}

void DrawnLook::OnBeforeUpscaler(VideoCore::ImageId color, VideoCore::ImageId depth,
                                 std::array<float, 2> jitter) {
    Paint(AtBeforeUpscaler, color, depth, jitter);
}

void DrawnLook::OnFrameEnd(bool wanted) {
    if (was_wanted) {
        ++results[frame_result];
        if (++frames >= 600) {
            BbReport::Printf("Drawn look: of %u frames, painted before the transparents on %u, "
                             "before the fog composite (no transparents) on %u, before the "
                             "upscaler (neither: fog and particles painted too, no ink) on %u; "
                             "not painted: %u menu previews, %u without a camera, %u for want of "
                             "video memory, %u without a scene, %u with ink lines alone right "
                             "before the upscaler; ink lines on %u; what moves by itself told "
                             "against the camera of the frame before on %u\n",
                             frames, results[AtBlended], results[AtComposite],
                             results[AtBeforeUpscaler], results[Preview], results[NoCamera],
                             results[NoRoom], results[NotReached], results[LinesOnlyLate],
                             ink_frames, previous_frames);
            results = {};
            frames = 0;
            ink_frames = 0;
            previous_frames = 0;
        }
        // The camera the frame was painted with is the next frame's "frame before"; a frame
        // that was not painted leaves none.
        last_camera_valid = frame_result <= AtBeforeUpscaler && last_camera_set;
        // The scene's depth is the last G-buffer pass's (as CameraMotion and the upscaler take
        // it): remembered, so that an earlier pass of a frame is known not to be the scene.
        if (gbuffer_depth && std::find(scene_depths.begin(), scene_depths.end(), gbuffer_depth) ==
                                 scene_depths.end()) {
            scene_depths[scene_depth_next++ % scene_depths.size()] = gbuffer_depth;
        }
        if (!wanted) {
            // Switched off (or the strength and the ink lines set to 0): the images go, the
            // pipelines are kept.
            ReleaseAll();
            last_view = last_inputs = ~0u;
            input_lines = 0;
            scene_depths = {};
            scene_depth_next = 0;
            // Switched on again, the memory is asked for again.
            if (refused_width != 0) {
                refused_width = refused_height = 0;
                BbSettings::Get().drawn_look_problem = nullptr;
            }
        }
    }
    if (!was_wanted) {
        last_camera_valid = false;
    }
    last_camera_set = false;
    small_pending = false;
    was_wanted = wanted;
    frame_result = NotReached;
    blended_this_frame = false;
    composite_this_frame = false;
    frame_pass_count = 0;
    gbuffer_depth = {};
    gbuffer_normal = {};
    // (r55_drawn-look-lines) The next frame has no ink lines until it records them.
    if (ink_published) {
        BbSettings::Get().drawn_look_ink_drawn.store(0.0f, std::memory_order_relaxed);
        ink_published = false;
    }
}

void DrawnLook::Paint(Result place, VideoCore::ImageId color_id, VideoCore::ImageId depth_id,
                      std::array<float, 2> jitter) {
    if (frame_result <= AtBeforeUpscaler || failed || !color_id || !depth_id) {
        return;
    }
    // A frame with several G-buffer passes is a menu's 3D preview (character creation), which
    // the upscaler leaves alone too: its "scene" is one of the previews.
    if (camera_motion.PreviewFrame()) {
        frame_result = Preview;
        return;
    }
    const auto camera = camera_motion.PassMatrices();
    if (!camera.valid) {
        frame_result = NoCamera;
        return;
    }
    const auto& s = BbSettings::Get();
    const DrawnLookParams::Knobs knobs{
        .strength = s.graphics_drawn_look_strength.load(std::memory_order_relaxed),
        .stroke_size = s.graphics_drawn_look_stroke_size.load(std::memory_order_relaxed),
        .texture = s.graphics_drawn_look_texture.load(std::memory_order_relaxed),
        .outlines = s.graphics_drawn_look_outlines.load(std::memory_order_relaxed),
        .ink_world = s.graphics_drawn_look_ink_world.load(std::memory_order_relaxed),
        .characters = s.graphics_drawn_look_characters.load(std::memory_order_relaxed),
        .line_scale = env_line,
        .view = env_view >= 0 ? env_view : int(DrawnLookParams::ViewOff),
    };
    // (r55_drawn-look-lines) Ink lines alone have nothing to draw right before the upscaler:
    // nothing is recorded, not even the copy.
    const auto passes = DrawnLookParams::PassesFor(knobs, place == AtBeforeUpscaler);
    if (!passes.strokes && !passes.ink) {
        frame_result = LinesOnlyLate;
        return;
    }
    if (!Ready()) {
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    auto& depth = texture_cache.GetImage(depth_id);
    if (color.info.pixel_format != vk::Format::eR16G16B16A16Sfloat) {
        Fail(BbSettings::DrawnLookTexts::NotHalfFloat.english);
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
    // Too small to be the scene; the marks are made from 4x4 pixels of it.
    if (width < 16 || height < 16) {
        return;
    }
    // The marks are half as wide and high, the painted scene's means a quarter.
    const u32 half_width = width / 2, half_height = height / 2;
    // Eight bytes a texel; an image's smaller levels add a third; the marks have a quarter of
    // the scene's texels, the means a sixteenth.
    if (!prep_copy.image || prep_copy.width != width || prep_copy.height != height) {
        if (width == refused_width && height == refused_height) {
            frame_result = NoRoom;
            return;
        }
        if (!EffectPass::HasRoom(instance, 14ull * width * height)) {
            // Not for good: a smaller scene (another render scale or preset) may fit. The
            // images of the size before are of no use meanwhile.
            refused_width = width;
            refused_height = height;
            frame_result = NoRoom;
            BbSettings::Get().drawn_look_problem = BbSettings::DrawnLookTexts::NoRoom.english;
            std::printf("Drawn look: off - not enough video memory for a scene of %ux%u; asked "
                        "again when the scene's size changes or the look is switched off and "
                        "on\n", width, height);
            ReleaseAll();
            return;
        }
        if (refused_width != 0) {
            refused_width = refused_height = 0;
            BbSettings::Get().drawn_look_problem = nullptr;
        }
    }
    // The G-buffer's normals are the scene's while its lighting and transparents are drawn.
    // Right before the upscaler the game may have reused that target: the normal then comes
    // from the depth.
    VideoCore::Image* normal = nullptr;
    if (place != AtBeforeUpscaler && gbuffer_normal && gbuffer_depth == depth_id) {
        normal = &texture_cache.GetImage(gbuffer_normal);
        if (normal->info.pixel_format != vk::Format::eR8G8B8A8Unorm) {
            normal = nullptr;
        }
    }
    const SceneUseScope scene_use{"drawn look"};
    scheduler.EndRendering();
    vk::ImageView color_view{}, depth_view{}, normal_view{};
    if (reduced) {
        VideoCore::ImageViewInfo color_info, depth_info;
        color_info.format = color.info.pixel_format;
        depth_info.format = depth.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, color_info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            Fail(BbSettings::DrawnLookTexts::ReducedNotStorage.english);
            return;
        }
        color_view = proxy.view;
        depth_view = scene_targets.ReadNext(depth_id, depth_info).view;
        if (normal && scene_targets.EligibleScene(*normal)) {
            VideoCore::ImageViewInfo normal_info;
            normal_info.format = normal->info.pixel_format;
            normal_view = scene_targets.ReadNext(gbuffer_normal, normal_info).view;
        }
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            Fail(BbSettings::DrawnLookTexts::NotStorage.english);
            return;
        }
        color_view = CachedView(color, color.info.pixel_format, vk::ImageAspectFlagBits::eColor);
        depth_view = CachedView(depth, depth.info.pixel_format, vk::ImageAspectFlagBits::eDepth);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.Transit(&depth, vk::ImageLayout::eGeneral, Compute,
                        vk::AccessFlagBits2::eShaderRead);
        if (normal && normal->info.size.width >= width && normal->info.size.height >= height) {
            normal_view = CachedView(*normal, normal->info.pixel_format,
                                     vk::ImageAspectFlagBits::eColor);
            runtime.Transit(normal, vk::ImageLayout::eGeneral, Compute,
                            vk::AccessFlagBits2::eShaderRead);
        }
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();
    // This frame's object motion, where the G-buffer pass wrote it at the scene's size (asked
    // first: PrepareRead would make an image where there is none).
    vk::ImageView motion_view{};
    bool has_motion = false;
    if (object_motion.Enabled() && object_motion.Image(width, height)) {
        motion_view = object_motion.PrepareRead(width, height, has_motion);
    }
    const bool has_normal = normal_view != vk::ImageView{};
    EnsureImage(prep_copy, width, height, vk::Format::eR16G16B16A16Sfloat, "scene copy");
    EnsureImage(marks, half_width, half_height, vk::Format::eR16G16B16A16Sfloat, "marks");
    EnsureImage(lock_means, width / 4, height / 4, vk::Format::eR16G16B16A16Sfloat, "means");
    frame_result = place;

    // (r45b_drawn-look-fixes) The camera of the frame before, when that frame was painted: the
    // object motion's vectors are told from the camera's own move with it.
    const auto params = DrawnLookParams::Make(knobs, camera.inv_view, camera.proj, width, height,
                                              jitter, has_normal, has_motion,
                                              last_camera_valid ? &last_camera : nullptr);
    last_camera = {camera.view, camera.proj};
    last_camera_set = true;
    previous_frames += (params.flags & DrawnLookParams::FlagPrevious) != 0;
    const u32 view = DrawnLookParams::ViewOf(params.flags);
    // A test view shows the strokes' places in colours of its own: no colours to lock.
    const bool locked = passes.lock;
    // (r55_drawn-look-lines) The ink pass's words: the frame's, three of its floats given the
    // ink's meanings (DrawnLookParams::MakeInk).
    const auto ink_params =
        DrawnLookParams::MakeInk(params, knobs.ink_world, knobs.outlines, knobs.line_scale);
    // The inputs may come and go from frame to frame (a frame painted right before the upscaler
    // has no G-buffer normals): their line is printed a few times, not on every change. So may
    // the passes (r55_drawn-look-lines: no ink right before the upscaler).
    const u32 inputs =
        (params.flags & (DrawnLookParams::FlagNormals | DrawnLookParams::FlagMotion)) |
        u32(passes.strokes) << 8 | u32(passes.ink) << 9;
    const bool resized = width != last_width || height != last_height || view != last_view;
    if (resized || (inputs != last_inputs && input_lines < 8)) {
        input_lines += !resized;
        last_width = width;
        last_height = height;
        last_view = view;
        last_inputs = inputs;
        char ink_text[64];
        if (passes.ink) {
            std::snprintf(ink_text, sizeof(ink_text), "ink lines %.2f (line scale %.2f)",
                          ink_params.strength, knobs.line_scale);
        } else {
            std::snprintf(ink_text, sizeof(ink_text), "%s",
                          knobs.ink_world > 0.0f ? "no ink lines here (right before the upscaler)"
                                                 : "no ink lines");
        }
        std::printf("Drawn look: on at %ux%u (%s), %sstroke cells %.1f and %.1f pixels, normals "
                    "from %s, object motion %s, %s, %s\n",
                    width, height, reduced ? "reduced scene" : "the game's scene",
                    passes.strokes ? "" : "no strokes, ", params.cell_bold, params.cell_fine,
                    has_normal ? "the G-buffer" : "the depth", has_motion ? "read" : "not there",
                    view == DrawnLookParams::ViewStrokes  ? "test view 1 (strokes, sizes as mixed)"
                    : view == DrawnLookParams::ViewFine   ? "test view 2 (strokes, all fine)"
                    : view == DrawnLookParams::ViewInk    ? "test view 3 (the ink page)"
                    : view == DrawnLookParams::ViewBold   ? "test view 4 (strokes, all bold)"
                                                          : "no test view",
                    ink_text);
    }

    // Each level's view, for the closures below.
    struct {
        std::array<vk::ImageView, MaxLevels> prep{}, marks{}, lock{};
        u32 count = 0; ///< the copy's levels; the marks have one fewer, the means two
    } levels;
    levels.count = u32(prep_copy.levels.size());
    for (u32 level = 0; level < levels.count; ++level) {
        levels.prep[level] = *prep_copy.levels[level];
    }
    for (u32 level = 0; level < marks.levels.size(); ++level) {
        levels.marks[level] = *marks.levels[level];
    }
    for (u32 level = 0; level < lock_means.levels.size(); ++level) {
        levels.lock[level] = *lock_means.levels[level];
    }
    // The key is told from the copy's level that is 64 texels or fewer on its longer side.
    u32 key_level = 0;
    while ((std::max(width, height) >> key_level) > 64) {
        ++key_level;
    }
    // Two rows in BB_GPU_PROFILE's table: what the strokes are made from, and the strokes
    // with the colour lock after them.
    EffectPass::Mark(18, "drawn look copy and masks");
    scheduler.RecordCrumb(
        {.name = "drawn look masks"},
        [params, width, height, half_width, half_height, levels, key_level, color_view,
         depth_view, sampler = *sampler, prep_image = vk::Image(prep_copy.image),
         marks_image = vk::Image(marks.image), lock_image = vk::Image(lock_means.image),
         prep_pipeline = *prep.pipeline, prep_layout = *prep.layout,
         stats_pipeline = *stats.pipeline, stats_layout = *stats.layout,
         mips_pipeline = *mips.pipeline, mips_layout = *mips.layout,
         sums_pipeline = *key_sums.pipeline, sums_layout = *key_sums.layout,
         key_pipeline = *key_last.pipeline,
         key_layout = *key_last.layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute, ReadWrite);
            // The three images are written anew every frame, every level of them; what the
            // frame before read of them is done.
            std::array<vk::ImageMemoryBarrier2, 3> to_general;
            to_general.fill({
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .subresourceRange = AllLevels,
            });
            to_general[0].image = prep_image;
            to_general[1].image = marks_image;
            to_general[2].image = lock_image;
            cmdbuf.pipelineBarrier2({.imageMemoryBarrierCount = u32(to_general.size()),
                                     .pImageMemoryBarriers = to_general.data()});
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout,
                                 std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(params), &params);
                cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
                EffectPass::ComputeBarrier(cmdbuf);
            };
            {
                const std::array infos{Info(color_view), Info(depth_view), Info(levels.prep[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2])};
                run(prep_pipeline, prep_layout, writes, width, height);
            }
            {
                const std::array infos{Info(levels.prep[0]), Info(levels.prep[1]),
                                       Info(levels.marks[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1]),
                                        Write(2, StorageImage, &infos[2])};
                run(stats_pipeline, stats_layout, writes, half_width, half_height);
            }
            // Level n of the copy and n - 1 of the marks are as large: each gives the next.
            for (u32 n = 1; n + 1 < levels.count; ++n) {
                const std::array infos{Info(levels.prep[n], sampler),
                                       Info(levels.marks[n - 1], sampler),
                                       Info(levels.prep[n + 1]), Info(levels.marks[n])};
                const std::array writes{Write(0, Sampled, &infos[0]), Write(1, Sampled, &infos[1]),
                                        Write(2, StorageImage, &infos[2]),
                                        Write(3, StorageImage, &infos[3])};
                run(mips_pipeline, mips_layout, writes, std::max(half_width >> n, 1u),
                    std::max(half_height >> n, 1u));
            }
            // The frame's key, over the copy's last level (one texel). Its sums wait in the
            // first texels of the means' image, which nothing else uses before the strokes.
            {
                const std::array infos{Info(levels.prep[key_level]), Info(levels.lock[0])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1])};
                run(sums_pipeline, sums_layout, writes, 8, 8);
            }
            {
                const std::array infos{Info(levels.lock[0]), Info(levels.prep[levels.count - 1])};
                const std::array writes{Write(0, SampledImage, &infos[0]),
                                        Write(1, StorageImage, &infos[1])};
                run(key_pipeline, key_layout, writes, 8, 8);
            }
        });
    // (r55_drawn-look-lines) The strokes and the lock when the frame has strokes, then the ink
    // lines in a row of their own.
    auto stroke_pass =
        [params, width, height, locked, levels, color_view, depth_view, sampler = *sampler,
         // A pass without normals or motion binds the copy in their place; its flags tell the
         // shader not to read them.
         normal_view = has_normal ? normal_view : *prep_copy.view,
         motion_view = has_motion ? motion_view : *prep_copy.view, prep_view = *prep_copy.view,
         marks_view = *marks.view, lock_view = *lock_means.view,
         strokes_pipeline = *strokes.pipeline,
         strokes_layout = *strokes.layout, first_pipeline = *lock_first.pipeline,
         first_layout = *lock_first.layout, down_pipeline = *lock_down.pipeline,
         down_layout = *lock_down.layout, lock_pipeline = *lock.pipeline,
         lock_layout = *lock.layout](vk::CommandBuffer cmdbuf) {
            const auto run = [&](vk::Pipeline pipeline, vk::PipelineLayout layout,
                                 std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmdbuf.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(params), &params);
                cmdbuf.dispatch((w + 7) / 8, (h + 7) / 8, 1);
            };
            {
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(normal_view),        Info(motion_view),
                                       Info(color_view),         Info(marks_view, sampler)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        Write(3, SampledImage, &infos[3]),
                                        Write(4, StorageImage, &infos[4]),
                                        Write(5, Sampled, &infos[5])};
                run(strokes_pipeline, strokes_layout, writes, width, height);
            }
            if (locked) {
                // The means' image: every level is written anew here (the key's sums in it
                // are done with).
                EffectPass::ComputeBarrier(cmdbuf);
                {
                    const std::array infos{Info(color_view), Info(levels.lock[0])};
                    const std::array writes{Write(0, SampledImage, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(first_pipeline, first_layout, writes, width / 4, height / 4);
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                for (u32 n = 0; n + 3 < levels.count; ++n) {
                    const std::array infos{Info(levels.lock[n], sampler),
                                           Info(levels.lock[n + 1])};
                    const std::array writes{Write(0, Sampled, &infos[0]),
                                            Write(1, StorageImage, &infos[1])};
                    run(down_pipeline, down_layout, writes, std::max(width >> (n + 3), 1u),
                        std::max(height >> (n + 3), 1u));
                    EffectPass::ComputeBarrier(cmdbuf);
                }
                const std::array infos{Info(prep_view, sampler), Info(depth_view),
                                       Info(motion_view), Info(color_view),
                                       Info(lock_view, sampler)};
                const std::array writes{Write(0, Sampled, &infos[0]),
                                        Write(1, SampledImage, &infos[1]),
                                        Write(2, SampledImage, &infos[2]),
                                        Write(3, StorageImage, &infos[3]),
                                        Write(4, Sampled, &infos[4])};
                run(lock_pipeline, lock_layout, writes, width, height);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        };
    if (passes.strokes) {
        EffectPass::Mark(12, "drawn look strokes and colour lock");
        scheduler.RecordCrumb({.name = "drawn look"}, std::move(stroke_pass));
    }
    if (!passes.ink) {
        return;
    }
    ++ink_frames;
    // The upscaler's extra sharpening on this frame (DrawnLookParams::InkSharpen).
    BbSettings::Get().drawn_look_ink_drawn.store(ink_params.strength, std::memory_order_relaxed);
    ink_published = true;
    EffectPass::Mark(13, "drawn look ink");
    scheduler.RecordCrumb(
        {.name = "drawn look ink"},
        [ink_params, width, height, color_view, depth_view, sampler = *sampler,
         prep_view = *prep_copy.view, ink_pipeline = *ink.pipeline,
         ink_layout = *ink.layout](vk::CommandBuffer cmdbuf) {
            // The scene colour (the strokes' crumb) and the key (the masks') are written.
            EffectPass::ComputeBarrier(cmdbuf);
            const std::array infos{Info(prep_view, sampler), Info(depth_view), Info(color_view)};
            const std::array writes{Write(0, Sampled, &infos[0]), Write(1, SampledImage, &infos[1]),
                                    Write(2, StorageImage, &infos[2])};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, ink_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, ink_layout, 0, writes);
            cmdbuf.pushConstants(ink_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                 sizeof(ink_params), &ink_params);
            cmdbuf.dispatch((width + 7) / 8, (height + 7) / 8, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                      AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

}
