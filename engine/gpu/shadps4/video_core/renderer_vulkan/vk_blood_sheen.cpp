// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_blood_sheen.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>

#include "bbport_toggles.h"
#include "bbport_settings.h" // bbport (r128d_lrt-sheen-interior)
#include "video_core/amdgpu/regs.h"
#include "video_core/host_shaders/blood_sheen_edit_comp.h"
#include "video_core/host_shaders/blood_sheen_mark_comp.h"
#include "video_core/host_shaders/blood_sheen_show_comp.h"
#include "video_core/host_shaders/blood_sheen_snapshot_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_graphics_pipeline.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_runtime.h"
#include "video_core/renderer_vulkan/vk_scene_resolution.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/texture_cache/texture_cache.h"
// bbport (r100e_blood-sheen-visible): the same-view A/B of the owner's pair (r84_live-test-knobs, a
// test tool): a build with the live knobs header lets one running game pause the film.
#if __has_include("../../../shim/bbport_live_knobs.h")
#include "../../../shim/bbport_live_knobs.h"
#define BLOOD_SHEEN_LIVE_PAUSE 1
#endif

namespace Vulkan {
namespace {
namespace R = BloodSheenRules;
// bbport (r128d_lrt-sheen-interior): the setting's range is the sheen's strength range, its default is off.
static_assert(BbSettings::BloodSheenMax == R::MaxStrength && BbSettings::BloodSheenMin == 0.0f &&
              BbSettings::BloodSheenDefault == 0.0f);
// bbport (r131b_lrt-settings): the colour setting's numbers are the film's three views (grey test, red, clear), red the default.
static_assert(BbSettings::BloodSheenTintMin == 0 && BbSettings::BloodSheenTintMax == 2 &&
              BbSettings::BloodSheenTintDefault == 1 && R::TintOf(-1, BbSettings::BloodSheenTintDefault) == 1);
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ShaderRead = vk::AccessFlagBits2::eShaderRead;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto SceneFormat = vk::Format::eR16G16B16A16Sfloat;
constexpr auto GbufferFormat = vk::Format::eR8G8B8A8Unorm;
constexpr auto TagFormat = vk::Format::eR32Uint;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::DeviceSize SlotBytes = R::SlotWords * 4;
// bbport (r129b_sheen-no-glow): SHOW's dry-scene reference words (2 slots of RefSlotWords) follow the counters' slots.
constexpr vk::DeviceSize RefOffset = R::Slots * SlotBytes, RefSlotBytes = R::RefSlotWords * 4;
constexpr vk::DeviceSize RefBytes = R::Slots * RefSlotBytes;
static_assert(R::RefBase * 4 == RefOffset);
constexpr u64 ProfileRow = 100; ///< EffectPass::Mark: the row "Lighting: blood sheen"

#ifdef BLOOD_SHEEN_LIVE_PAUSE
bool PauseParse(const char* text) {
    return text != nullptr && text[0] != '\0' && text[0] != '0';
}
#endif

/// BB_BLOOD_SHEEN_PAUSE (live, a test knob): 1 stops the film and the dimming at once, 0 (or unset)
/// runs them; always false in a build without the live knobs header. Said in the log at each change.
bool Paused() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<bool> knob{"BB_BLOOD_SHEEN_PAUSE", PauseParse};
    static bool last = false;
    const bool now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf("Blood sheen (r100e): %s (BB_BLOOD_SHEEN_PAUSE, a test knob)\n",
                         now ? "paused: no film, no dimming" : "running again");
    }
    return now;
#else
    return false;
#endif
}

/// BB_BLOOD_SHEEN_RIM_FULL (r129b_sheen-no-glow, live, a test knob): 1: the rim (gap-fill) pixels level their normal by the
/// fill weight as r100h-r100k did; 0 (or unset): by their specular weight. Always false in a build without the live
/// knobs header. Said in the log at each change.
bool RimFull() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<bool> knob{"BB_BLOOD_SHEEN_RIM_FULL", PauseParse};
    static bool last = false;
    const bool now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf(
            "Blood sheen (r129b): the rim levels its normal by %s (BB_BLOOD_SHEEN_RIM_FULL, a test knob)\n",
            now ? "the fill weight (as r100h-r100k)" : "its specular weight");
    }
    return now;
#else
    return false;
#endif
}

/// Film colour controls. TINT and LEVEL also read startup overrides without the live knobs header.
int TintMode() {
    // bbport (r131b_lrt-settings): the variable (set and not empty: it decides) or else the setting graphics_blood_sheen_tint, read at
    // every call (a relaxed load). Without the live knobs header the variable is read once (it was ignored there before).
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<int> knob{"BB_BLOOD_SHEEN_TINT", R::ReadTintEnv};
    const int env = knob.Get();
#else
    static const int env = R::ReadTintEnv(std::getenv("BB_BLOOD_SHEEN_TINT"));
#endif
    const int now = R::TintOf(env, BbSettings::Get().graphics_blood_sheen_tint.load(std::memory_order_relaxed));
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static int last = 1;
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): tint %s (BB_BLOOD_SHEEN_TINT %d)\n",
            now == 0 ? "off (untinted grey specular)" : (now == 2 ? "clear film (grey, dimming by redness)" : "r100i red"), now);
    }
#endif
    static int told_value = -1, told_from_env = -1; // r131b: the first call and a change of value or source
    const int from_env = env >= 0 ? 1 : 0;
    if (now != told_value || from_env != told_from_env) {
        told_value = now;
        told_from_env = from_env;
        BbReport::Printf( // r131b
            "Blood sheen (r131b): tint %d (%s) from %s\n", now, now == 0 ? "grey test" : (now == 2 ? "clear film" : "red"),
            from_env != 0 ? "the environment (BB_BLOOD_SHEEN_TINT)" : "the setting (graphics_blood_sheen_tint)");
    }
    return now;
}

float GlossShare() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_GLOSS", R::ReadShare};
    static float last = 1.0f;
    const float now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): gloss share %.2f (BB_BLOOD_SHEEN_GLOSS)\n", double(now));
    }
    return now;
#else
    return 1.0f;
#endif
}

float LevelShare(int tint) {
    constexpr auto parse = [](const char* text) { return R::ReadShareOr(text, -1.0f); };
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_LEVEL", parse};
    const float level = knob.Get();
#else
    static const float level = parse(std::getenv("BB_BLOOD_SHEEN_LEVEL"));
#endif
    const float now = R::LevelOf(tint, level);
    const bool overridden = level >= 0.0f;
    static float last = 1.0f;
    static bool last_overridden = false;
    if (now != last || overridden != last_overridden) {
        last = now;
        last_overridden = overridden;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): level share %.2f (BB_BLOOD_SHEEN_LEVEL, %s)\n",
            double(now), overridden ? "override" : "tint default");
    }
    return now;
}

float DarkenNow(const R::Knobs& k) {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_DARKEN", R::ReadDarken};
    static float last = k.darken;
    const float now = knob.Get();
    if (now != last) {
        last = now;
        BbReport::Printf( // r130a
            "Blood sheen (r130a): dimming %.2f (BB_BLOOD_SHEEN_DARKEN, live)\n", double(now));
    }
    return now;
#else
    return k.darken;
#endif
}

/// BB_BLOOD_SHEEN_PEAK (r100k_sheen-no-hot-spot): the lit scene's luminance ceiling for the picked pixels, 0: none.
/// Live in a build with the live knobs header (a test aid: the same view with and without it); said in the log at
/// each change (and once at the first use).
float PeakCap() {
#ifdef BLOOD_SHEEN_LIVE_PAUSE
    static BbLiveKnobs::Knob<float> knob{"BB_BLOOD_SHEEN_PEAK", R::ReadPeak};
    const float now = knob.Get();
#else
    static const float fixed = R::ReadPeak(std::getenv("BB_BLOOD_SHEEN_PEAK"));
    const float now = fixed;
#endif
    static float last = -1.0f;
    if (now != last) {
        last = now;
        if (now > 0.0f) {
            BbReport::Printf(
                "Blood sheen (r129b): highlight ceiling %.2f x the dry scene's reference (geometric mean of the max "
                "channel, one frame late; %.2f before the first), on the max channel of the picked pixels, soft above "
                "half (BB_BLOOD_SHEEN_PEAK)\n",
                double(now), double(R::PeakFallback));
        } else {
            BbReport::Printf(
                "Blood sheen (r129b): no highlight ceiling (BB_BLOOD_SHEEN_PEAK 0)\n");
        }
    }
    return now;
}

vk::DescriptorImageInfo Info(vk::ImageView view) {
    return {.sampler = {}, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}

vk::WriteDescriptorSet ImageWrite(u32 binding, vk::DescriptorType type, const vk::DescriptorImageInfo* info) {
    return {.dstBinding = binding, .descriptorCount = 1, .descriptorType = type, .pImageInfo = info};
}

vk::WriteDescriptorSet BufferWrite(u32 binding, const vk::DescriptorBufferInfo* info) {
    return {.dstBinding = binding,
            .descriptorCount = 1,
            .descriptorType = vk::DescriptorType::eStorageBuffer,
            .pBufferInfo = info};
}

/// The counters' commands of a frame's first pass (BloodSheen::TakeCounterStep), then the barrier
/// that lets the pass add to them.
void CounterCommands(vk::CommandBuffer cmd, vk::Buffer counters, vk::Buffer host, bool clear, bool copy_back,
                     u32 slot) {
    if (!clear) {
        return;
    }
    if (copy_back) {
        // r129b_sheen-no-glow: and SHOW's reference words (both slots) behind the counters, for the log
        const std::array copies{vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes},
                                vk::BufferCopy{RefOffset, SlotBytes, RefBytes}};
        cmd.copyBuffer(counters, host, copies);
    }
    cmd.fillBuffer(counters, slot * SlotBytes, SlotBytes, 0);
    EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                              Compute | vk::PipelineStageFlagBits2::eHost,
                              ReadWrite | vk::AccessFlagBits2::eHostRead);
}

/// What a pass's commands begin with: the game's writes before it (and the last pass's reads of the
/// tag) are done.
void BeginBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute | Transfer,
                              ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                  vk::AccessFlagBits2::eTransferWrite);
}

void EndBarrier(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}

std::string KeyText(const R::Knobs& k) {
    std::string text;
    for (u32 i = 0; i < k.key_count; ++i) {
        char key[56];
        if (k.keys[i].indices != 0) {
            std::snprintf(key, sizeof(key), "%s%08llx:%08llx:%u", i ? ";" : "",
                          static_cast<unsigned long long>(k.keys[i].vs),
                          static_cast<unsigned long long>(k.keys[i].ps), k.keys[i].indices);
        } else {
            std::snprintf(key, sizeof(key), "%s%08llx:%08llx", i ? ";" : "",
                          static_cast<unsigned long long>(k.keys[i].vs),
                          static_cast<unsigned long long>(k.keys[i].ps));
        }
        text += key;
    }
    return text.empty() ? std::string("none") : text;
}
} // namespace

bool BloodSheen::Wanted() {
    // bbport (r128d_lrt-sheen-interior): the setting graphics_blood_sheen is handed to the knobs once, before their
    // first read (this is the first caller: the rasterizer's constructor; BbSettings::Load ran in bbgpu_init).
    static const bool handed = [] {
        R::IniStrength() = BbSettings::Get().graphics_blood_sheen.load(std::memory_order_relaxed);
        return true;
    }();
    (void)handed;
    return R::Load().strength > 0.0f;
}

BloodSheen::BloodSheen(const Instance& instance_, Scheduler& scheduler_, VideoCore::TextureCache& texture_cache_,
                       Runtime& runtime_, SceneTargets& scene_targets_, CameraMotion& camera_motion_)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_}, runtime{runtime_},
      scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const auto& k = R::Load();
    BbReport::Printf("Blood sheen (r100d): on, strength %.2f%s; a wet film (gloss toward %.2f, specular "
                     "root toward %.2f) in the G-buffer before the game's lights, where picked\n",
                     double(k.strength), k.show ? ", show (picked red-magenta, left out by the rule cyan)" : "",
                     double(R::WetGloss),
                     double(std::min(R::WetSpecRoot * std::sqrt(std::max(k.strength, 1.0f)), R::SpecRootMax)));
    char rule[96];
    if (k.rule == R::Rule::Albedo) {
        std::snprintf(rule, sizeof(rule), "albedo (red >= %.3f, >= %.2f x green and blue, luminance <= %.3f)",
                      double(R::RedMin), double(k.ratio), double(k.lum_max));
    } else {
        std::snprintf(rule, sizeof(rule), "draw (every pixel a keyed draw wrote last)");
    }
    BbReport::Printf("Blood sheen (r100d): keyed draws (BB_BLOOD_SHEEN_DRAW) %s%s; rule %s%s%s\n",
                     KeyText(k).c_str(), k.keys_bad != 0 ? " (bad tokens dropped)" : "", rule,
                     k.rule_bad ? " (BB_BLOOD_SHEEN_RULE unreadable: draw)" : "",
                     R::CanPick(k) ? "" : "; NOTHING can be picked: name a draw or use the albedo rule");
    BbReport::Printf("Blood sheen (r100h): the film also levels the normal to world up, per pixel: all the way "
                     "inside the pool, weight %.2f at its rim (largest weight %.2f; gloss %.2f for every wet pixel), "
                     "fills the pool's gaps (a kept ground pixel not dark red itself whose 24 ring taps at 6, 14 and "
                     "28 px (1080p) are 50-80%% dark red: the wet count minus the albedo rule count), and, after the "
                     "lighting, dims and reddens the picked pixels' dark light (BB_BLOOD_SHEEN_DARKEN %.2f, %s)\n",
                     double(R::NormalEdge * std::min(k.strength, 1.0f)),
                     double(R::NormalSmooth * std::min(k.strength, 1.0f)), double(R::WetGloss), double(k.darken),
                     k.darken > 0.0f ? "on" : "off: no dimming pass");
    // bbport (r100i_sheen-blood-tint): the specular root's tint, once.
    {
        const double root = double(std::min(R::WetSpecRoot * std::sqrt(std::max(k.strength, 1.0f)), R::SpecRootMax));
        BbReport::Printf("Blood sheen (r100i): the film's specular is tinted by the blood: root %.3f at this strength "
                         "(cap %.2f) times (%.2f, %.2f, %.2f), so f0 red %.3f, green %.3f, blue %.3f (the red is "
                         "never lowered; green and blue go down to it on wet pixels)\n",
                         root, double(R::SpecRootMax), double(R::TintR), double(R::TintG), double(R::TintB),
                         root * double(R::TintR) * root * double(R::TintR),
                         root * double(R::TintG) * root * double(R::TintG),
                         root * double(R::TintB) * root * double(R::TintB));
    }
    // bbport (r100j_sheen-clean-rim): the rim rule, once.
    BbReport::Printf("Blood sheen (r100j): the pool's rim (gap-fill pixels, not dark red themselves) gets at most %.2f "
                     "of the body's specular tint and gloss, rising smoothly to the body's value where 80-100%% of "
                     "its ring taps are dark red; pixels that pass the albedo rule are as before\n",
                     double(R::FillSpec));
    // bbport (r100k_sheen-no-hot-spot): the rim's weight falls with the square of its fill weight.
    BbReport::Printf("Blood sheen (r100k): a rim pixel's specular weight is its fill weight squared times at most "
                     "%.2f; a near light's highlight on the pool is rolled off by a ceiling on the max channel, as a "
                     "multiple of the dry scene's reference (r129b) "
                     "(default %.2f, BB_BLOOD_SHEEN_PEAK, 0 = none)\n",
                     double(R::FillSpec), double(R::PeakDefault));
    // bbport (r128d_lrt-sheen-interior): where the strength and the picked draws come from, once.
    BbReport::Printf("Blood sheen (r128d): strength %.2f from %s; %s\n", double(k.strength),
                     k.from_ini ? "the setting graphics_blood_sheen" : "the environment (BB_BLOOD_SHEEN)",
                     k.default_pick ? "neither BB_BLOOD_SHEEN_DRAW nor BB_BLOOD_SHEEN_RULE is set: the pool's own "
                                      "draw c829ee58:dbb222eb and the albedo rule are used"
                                    : "the draws and the rule are the ones the environment names");
    // bbport (r129b_sheen-no-glow): the rim's levelling, once.
    BbReport::Printf(
        "Blood sheen (r129b): rim (gap-fill) pixels level their normal by their specular weight (fill^2 x rim share), "
        "not the fill weight (BB_BLOOD_SHEEN_RIM_FULL=1, a test knob: as r100h-r100k)\n");
    // bbport (r130a_sheen-colour): the film colour knobs, once.
    BbReport::Printf( // r130a
        "Blood sheen (r130a): film colour knobs (live, test): BB_BLOOD_SHEEN_TINT 1 = r100i red specular, 0 = untinted f0 0.20 "
        "grey, 2 = clear film (grey f0 0.0225, after-lighting dimming by redness only); BB_BLOOD_SHEEN_GLOSS and "
        "BB_BLOOD_SHEEN_LEVEL shares (1 = as r129b; level defaults to 0.25 for tint 2, 1 otherwise); "
        "BB_BLOOD_SHEEN_DARKEN now live\n");
}

BloodSheen::~BloodSheen() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(counters);
    FreeBuffer(readback);
}

bool BloodSheen::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage) {
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

void BloodSheen::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool BloodSheen::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, TagFormat) && EffectPass::StorageFormat(instance, GbufferFormat) &&
        EffectPass::StorageFormat(instance, SceneFormat) &&
        EffectPass::Create(instance, snapshot_pass.set_layout, snapshot_pass.layout, snapshot_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage}, sizeof(R::Push),
                           BLOOD_SHEEN_SNAPSHOT_COMP, "Blood sheen snapshot") &&
        EffectPass::Create(instance, mark_pass.set_layout, mark_pass.layout, mark_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_MARK_COMP, "Blood sheen mark") &&
        EffectPass::Create(instance, edit_pass.set_layout, edit_pass.layout, edit_pass.pipeline,
                           {eSampledImage, eSampledImage, eStorageImage, eStorageImage, eStorageImage,
                            eStorageImage, eStorageBuffer},
                           sizeof(R::Push), BLOOD_SHEEN_EDIT_COMP, "Blood sheen wet ground") &&
        EffectPass::Create(instance, show_pass.set_layout, show_pass.layout, show_pass.pipeline,
                           {eStorageImage, eStorageImage, eStorageBuffer}, sizeof(R::Push), BLOOD_SHEEN_SHOW_COMP,
                           "Blood sheen show") &&
        MakeBuffer(counters, RefOffset + RefBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer | vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes + RefBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the passes");
        return false;
    }
    std::memset(readback.mapped, 0, SlotBytes + RefBytes);
    return true;
}

void BloodSheen::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Blood sheen (r100d): off - %s\n", why);
    ReleaseImage();
}

void BloodSheen::ReleaseImage() {
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

bool BloodSheen::EnsureImage(u32 width, u32 height) {
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
    SetObjectName(device, vk::Image(tag_image), "Blood sheen tag");
    tag_view = Check<"create blood sheen tag view">(device.createImageViewUnique({
        .image = vk::Image(tag_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    before_image = VideoCore::UniqueImage(device, instance.GetAllocator());
    before_image.Create(image_ci);
    SetObjectName(device, vk::Image(before_image), "Blood sheen prints before");
    before_view = Check<"create blood sheen prints view">(device.createImageViewUnique({
        .image = vk::Image(before_image),
        .viewType = vk::ImageViewType::e2D,
        .format = TagFormat,
        .subresourceRange = ColorLevel,
    }));
    tag_width = width;
    tag_height = height;
    tag_fresh = true;
    return true;
}

vk::ImageView BloodSheen::CachedView(const VideoCore::Image& image, vk::Format format,
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
        .view = Check<"create blood sheen view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = format,
            .subresourceRange = {aspect, 0, 1, 0, 1},
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

bool BloodSheen::SceneSize(VideoCore::ImageId id, u32& width, u32& height, bool& reduced) {
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

vk::ImageView BloodSheen::ViewOf(VideoCore::ImageId id, vk::ImageAspectFlags aspect, bool storage, bool write) {
    auto& image = texture_cache.GetImage(id);
    const auto access = write ? ReadWrite : ShaderRead;
    if (scene_targets.Reduced() && scene_targets.EligibleScene(image)) {
        VideoCore::ImageViewInfo info;
        info.format = image.info.pixel_format;
        const auto proxy = scene_targets.Read(id, info, Compute, access);
        const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
        return (proxy.usage & need) ? proxy.view : vk::ImageView{};
    }
    const auto need = storage ? vk::ImageUsageFlagBits::eStorage : vk::ImageUsageFlagBits::eSampled;
    if (!(image.usage_flags & need)) {
        return {};
    }
    const auto view = CachedView(image, image.info.pixel_format, aspect);
    runtime.Transit(&image, vk::ImageLayout::eGeneral, Compute, access);
    return view;
}

bool BloodSheen::Fits(bool material, u32& width, u32& height, bool& reduced) {
    if (!gbuffer_depth || !gbuffer_albedo || (material && (!gbuffer_material || !gbuffer_specular)) ||
        !SceneSize(gbuffer_depth, width, height, reduced)) {
        ++stats.cannot;
        return false;
    }
    const std::array<VideoCore::ImageId, 3> ids{gbuffer_albedo, gbuffer_material, gbuffer_specular};
    for (u32 i = 0; i < (material ? 3u : 1u); ++i) {
        const auto& image = texture_cache.GetImage(ids[i]);
        const bool fits = (i == 0 || image.info.pixel_format == GbufferFormat) && image.info.num_samples == 1 &&
                          (scene_targets.Reduced() && scene_targets.EligibleScene(image)) == reduced &&
                          image.info.size.width >= (reduced ? 1u : width) &&
                          image.info.size.height >= (reduced ? 1u : height);
        if (!fits) {
            ++stats.cannot;
            if (!told_unfit) {
                told_unfit = true;
                BbReport::Printf("Blood sheen (r100d): left out (first time): G-buffer target %u format %u, "
                                 "%ux%u, %u samples (targets 1 and 3 must be R8G8B8A8_UNORM, 37; the scene is "
                                 "%ux%u)\n",
                                 i == 0 ? 2u : (i == 1 ? 1u : 3u), u32(image.info.pixel_format),
                                 image.info.size.width, image.info.size.height, image.info.num_samples, width,
                                 height);
            }
            return false;
        }
    }
    return true;
}

BloodSheen::CounterStep BloodSheen::TakeCounterStep() {
    CounterStep step{};
    step.slot = u32(frame & 1);
    if (counter_frame != frame + 1) {
        counter_frame = frame + 1;
        step.clear = true;
        // the frame before used the other slot: its counts are complete in the queue before this
        step.copy_back = counter_used == frame && frame != 0;
        if (step.copy_back) { // r129b: which reference slot the copy holds the newest words of, and whether any show ran
            ref_read_slot = ref_slot_last;
            ref_read_valid = show_count != 0;
        }
    }
    counter_used = frame + 1;
    return step;
}

void BloodSheen::BeforeDraw(const AmdGpu::Regs& regs, const GraphicsPipeline& pipeline,
                            const std::array<VideoCore::ImageId, 8>& targets, VideoCore::ImageId depth, Kind kind,
                            bool lamps_pending, std::array<float, 2> /*jitter*/) {
    pending = false; // a SNAPSHOT whose draw was left out (a pipeline still compiling): no MARK
    if (failed || Paused()) {
        return;
    }
    const auto& k = R::Load();
    const u32 mrt = u32(pipeline.GetGraphicsKey().mrt_mask);
    // A G-buffer pass's draw: its depth, gloss (1), albedo (2) and specular (3). A G-buffer draw after
    // a light draw begins the next pass (a planar reflection's pass and the world's each get theirs).
    if (std::popcount(mrt) >= 5 && depth) {
        if (!gbuffer_seen || edit_tried) {
            gbuffer_seen = true;
            edit_tried = false;
            keyed_in_pass = 0;
            show_due = false;
        }
        gbuffer_depth = depth;
        gbuffer_material = (mrt & 2u) ? targets[1] : VideoCore::ImageId{};
        gbuffer_albedo = (mrt & 4u) ? targets[2] : VideoCore::ImageId{};
        gbuffer_specular = (mrt & 8u) ? targets[3] : VideoCore::ImageId{};
        gbuffer_normal = (mrt & 1u) ? targets[0] : VideoCore::ImageId{};
        if (k.key_count == 0) {
            return;
        }
        const auto* ps = pipeline.GetStages()[u32(Shader::SwStage::Fragment)];
        const u64 vs_hash = pipeline.GetStage(Shader::SwStage::Vertex).pgm_hash;
        if (!ps || !R::Matches(k, vs_hash, ps->pgm_hash, u32(regs.num_indices))) {
            return;
        }
        ++stats.keyed;
        ++keyed_this_frame;
        // Lamps apart (vk_point_shadow.h): an open batch must not see the scene depth read.
        if (lamps_pending) {
            ++stats.lamps_pending;
        } else if (keyed_in_pass >= R::MaxKeyedDraws) {
            ++stats.over_cap;
        } else if (camera_motion.PreviewFrame()) {
            ++stats.previews;
        } else {
            Snapshot();
        }
        return;
    }
    // EDIT: at the first light draw after each G-buffer pass (the shadow resolve, the sun or moon,
    // or a lamp of the grid, whichever comes first), before its pass: the game's own lighting then
    // sees the wet ground. Not while a lamps-apart batch is open (its deferred lamps read the
    // G-buffer later: they would light the ground half dry and half wet): counted.
    if ((kind.resolve || kind.sun || kind.lamp) && gbuffer_seen && !edit_tried) {
        edit_tried = true;
        if (!R::CanPick(k)) {
            return;
        }
        if (lamps_pending) {
            ++stats.edit_pending;
        } else if (camera_motion.PreviewFrame()) {
            ++stats.previews;
        } else {
            Edit();
        }
    }
}

void BloodSheen::Snapshot() {
    // Only the scene camera's pass (a planar reflection's pass has another depth, often another size:
    // the tag would be made anew for it every frame).
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth()) {
        ++stats.cannot;
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!Fits(false, width, height, reduced) || !Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView albedo_view = ViewOf(gbuffer_albedo, vk::ImageAspectFlagBits::eColor, false, false);
    const vk::ImageView depth_view = ViewOf(gbuffer_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!albedo_view || !depth_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.size = {float(width), float(height)};
    push.flags = R::Flags(k, step.slot) | (keyed_in_pass == 0 ? R::FlagClear : 0u);
    const bool fresh = std::exchange(tag_fresh, false);
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen snapshot"},
        [push, step, fresh, width, height, albedo_view, depth_view, tag_handle = vk::Image(tag_image),
         before_handle = vk::Image(before_image), tag = *tag_view, before = *before_view,
         counter_buffer = counters.buffer, host = readback.buffer, pipeline = *snapshot_pass.pipeline,
         layout = *snapshot_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
                EffectPass::InitGeneral(cmd, before_handle, ColorLevel);
            }
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(albedo_view), Info(depth_view), Info(before), Info(tag)};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3])};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
    ++keyed_in_pass;
    pending = true;
}

void BloodSheen::AfterDraw() {
    if (std::exchange(pending, false)) {
        Mark();
    }
}

void BloodSheen::Mark() {
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView albedo_view = ViewOf(gbuffer_albedo, vk::ImageAspectFlagBits::eColor, false, false);
    const vk::ImageView depth_view = ViewOf(gbuffer_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!albedo_view || !depth_view) {
        ++stats.cannot;
        return;
    }
    const auto& k = R::Load();
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.size = {float(tag_width), float(tag_height)};
    push.flags = R::Flags(k, step.slot);
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen mark"},
        [push, step, width = tag_width, height = tag_height, albedo_view, depth_view, tag = *tag_view,
         before = *before_view, counter_buffer = counters.buffer, host = readback.buffer,
         pipeline = *mark_pass.pipeline, layout = *mark_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(albedo_view), Info(depth_view), Info(before), Info(tag)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3]),
                                    BufferWrite(4, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
}

void BloodSheen::Edit() {
    const auto& k = R::Load();
    // With a key, only a pass whose keyed draws were marked (the tag holds this pass's pixels).
    if (k.key_count != 0 && keyed_in_pass == 0) {
        ++stats.no_key_draw;
        return;
    }
    if (!gbuffer_depth || gbuffer_depth != camera_motion.Depth()) {
        ++stats.cannot; // not the scene's pass (a planar reflection), or no scene depth known yet
        return;
    }
    u32 width = 0, height = 0;
    bool reduced = false;
    if (!Fits(true, width, height, reduced) || !Ready()) {
        return;
    }
    if (!EnsureImage(width, height)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView albedo_view = ViewOf(gbuffer_albedo, vk::ImageAspectFlagBits::eColor, false, false);
    const vk::ImageView depth_view = ViewOf(gbuffer_depth, vk::ImageAspectFlagBits::eDepth, false, false);
    const vk::ImageView material_view = ViewOf(gbuffer_material, vk::ImageAspectFlagBits::eColor, true, true);
    const vk::ImageView specular_view = ViewOf(gbuffer_specular, vk::ImageAspectFlagBits::eColor, true, true);
    // bbport (r100e_blood-sheen-visible): the normal target (0) is flattened where it is RGBA8 and fits
    // as the others do; else its binding stands on the gloss view and the shader leaves it alone.
    bool normal_ok = false;
    vk::ImageView normal_view = material_view;
    if (gbuffer_normal) {
        const auto& normal_image = texture_cache.GetImage(gbuffer_normal);
        normal_ok = normal_image.info.pixel_format == GbufferFormat && normal_image.info.num_samples == 1 &&
                    (scene_targets.Reduced() && scene_targets.EligibleScene(normal_image)) == reduced &&
                    normal_image.info.size.width >= (reduced ? 1u : width) &&
                    normal_image.info.size.height >= (reduced ? 1u : height);
        if (normal_ok) {
            const vk::ImageView view = ViewOf(gbuffer_normal, vk::ImageAspectFlagBits::eColor, true, true);
            normal_ok = static_cast<bool>(view);
            if (normal_ok) {
                normal_view = view;
            }
        }
    }
    if (!normal_ok && !told_normal) {
        told_normal = true;
        BbReport::Printf("Blood sheen (r100e): the normal target cannot be flattened (first time; it is %s): the "
                         "film leaves the normal as it is\n",
                         gbuffer_normal ? "not RGBA8 of the scene's size or not a storage image" : "not written by the G-buffer draws");
    }
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!albedo_view || !depth_view || !material_view || !specular_view) {
        ++stats.cannot;
        return;
    }
    const CounterStep step = TakeCounterStep();
    R::Push push{};
    push.size = {float(width), float(height)};
    push.strength = k.strength;
    push.ratio = k.ratio;
    push.lum_max = k.lum_max;
    push.red_min = R::RedMin;
    push.flags = R::Flags(k, step.slot) | (normal_ok ? R::FlagNormal : 0u) |
                 (RimFull() ? R::FlagRimFull : 0u) | (k.default_pick ? R::FlagAutoGround : 0u);
    {   // bbport (r130a_sheen-colour): the tint probe flags and the gloss and level shares (the shader's `unused` word)
        const int tint = TintMode();
        push.flags |= (tint == 0 ? R::FlagTintOff : 0u) | (tint == 2 ? R::FlagTintClear : 0u);
        push.darken = std::bit_cast<float>(R::PackScales(GlossShare(), LevelShare(tint)));
    }
    const bool fresh = std::exchange(tag_fresh, false);
    ++stats.edits;
    stats.normals += normal_ok ? 1u : 0u;
    show_due = k.show || DarkenNow(k) > 0.0f || PeakCap() > 0.0f; // the test view, the dimming or the ceiling (r100k, r130a)
    if (!told_first) {
        told_first = true;
        BbReport::Printf("Blood sheen (r100d): first wet-ground pass at frame %llu, %ux%u (%s), %u keyed draws "
                         "marked in the pass\n",
                         static_cast<unsigned long long>(frame), width, height,
                         reduced ? "reduced scene" : "the game's scene", keyed_in_pass);
    }
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen wet ground"},
        [push, step, fresh, width, height, albedo_view, depth_view, material_view, specular_view, normal_view,
         tag_handle = vk::Image(tag_image), before_handle = vk::Image(before_image), tag = *tag_view,
         counter_buffer = counters.buffer, host = readback.buffer, pipeline = *edit_pass.pipeline,
         layout = *edit_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            if (fresh) {
                EffectPass::InitGeneral(cmd, tag_handle, ColorLevel);
                EffectPass::InitGeneral(cmd, before_handle, ColorLevel);
            }
            CounterCommands(cmd, counter_buffer, host, step.clear, step.copy_back, step.slot);
            using enum vk::DescriptorType;
            const std::array infos{Info(albedo_view), Info(depth_view), Info(tag), Info(material_view),
                                   Info(specular_view), Info(normal_view)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, R::Slots * SlotBytes};
            const std::array writes{ImageWrite(0, eSampledImage, &infos[0]), ImageWrite(1, eSampledImage, &infos[1]),
                                    ImageWrite(2, eStorageImage, &infos[2]), ImageWrite(3, eStorageImage, &infos[3]),
                                    ImageWrite(4, eStorageImage, &infos[4]), ImageWrite(5, eStorageImage, &infos[5]),
                                    BufferWrite(6, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
}

void BloodSheen::Show(VideoCore::ImageId scene, bool lamps_pending) {
    if (!std::exchange(show_due, false) || failed || !scene || !tag_image || lamps_pending || Paused()) {
        return;
    }
    const auto& image = texture_cache.GetImage(scene);
    u32 width = 0, height = 0;
    bool reduced = false;
    if (image.info.pixel_format != SceneFormat || !SceneSize(scene, width, height, reduced) ||
        width != tag_width || height != tag_height) {
        if (!told_show) {
            told_show = true;
            BbReport::Printf("Blood sheen (r100d): show left out (first time): the lit scene is format %u, "
                             "%ux%u, the tag %ux%u (RGBA16F, 97, of the tag's size wanted)\n",
                             u32(image.info.pixel_format), width, height, tag_width, tag_height);
        }
        return;
    }
    const SceneUseScope scene_use{"blood sheen"};
    scheduler.EndRendering();
    const vk::ImageView scene_view = ViewOf(scene, vk::ImageAspectFlagBits::eColor, true, true);
    runtime.FlushBarriers();
    scheduler.EndRendering();
    if (!scene_view) {
        return;
    }
    R::Push push{};
    const auto& k = R::Load();
    push.size = {float(width), float(height)};
    push.flags = k.show ? R::FlagShow : 0u; // r100e: not the test view: the dimming (push.darken)
    if (!k.show && TintMode() == 2) {
        push.flags |= R::FlagTintClear; // r130a: the dimming acts by the pixel's redness
    }
    push.darken = k.show ? 0.0f : DarkenNow(k) * std::min(k.strength, 1.0f); // r130a: live
    push.ratio = k.show ? 0.0f : PeakCap(); // r100k: the SHOW pass reads its luminance ceiling from `ratio`
    stats.peak_shows += push.ratio > 0.0f ? 1u : 0u;
    // r129b_sheen-no-glow: this show's reference slot (its parity; the other slot, the last show's, gives the ceiling); the
    // first show clears both slots (the buffer is not initialised), later ones their own.
    const u32 ref_slot = show_count++ & 1u;
    push.flags |= ref_slot != 0 ? R::FlagSlot : 0u;
    const bool ref_clear_all = std::exchange(ref_fresh, false);
    ref_slot_last = ref_slot;
    ++stats.shows;
    EffectPass::Mark(ProfileRow, "blood sheen", true);
    scheduler.RecordCrumb(
        {.name = "blood sheen show"},
        [push, width, height, scene_view, tag = *tag_view, ref_slot, ref_clear_all, counter_buffer = counters.buffer,
         pipeline = *show_pass.pipeline, layout = *show_pass.layout](vk::CommandBuffer cmd) {
            BeginBarrier(cmd);
            // r129b_sheen-no-glow: this show's reference words start at 0 (both slots the first time)
            cmd.fillBuffer(counter_buffer, ref_clear_all ? RefOffset : RefOffset + ref_slot * RefSlotBytes,
                           ref_clear_all ? RefBytes : RefSlotBytes, 0);
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite, Compute, ReadWrite);
            using enum vk::DescriptorType;
            const std::array infos{Info(tag), Info(scene_view)};
            const vk::DescriptorBufferInfo counter_info{counter_buffer, 0, RefOffset + RefBytes};
            const std::array writes{ImageWrite(0, eStorageImage, &infos[0]), ImageWrite(1, eStorageImage, &infos[1]),
                                    BufferWrite(2, &counter_info)};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + R::Group - 1) / R::Group, (height + R::Group - 1) / R::Group, 1);
            EndBarrier(cmd);
        });
}

void BloodSheen::OnFrameEnd() {
    pending = false;
    if (keyed_this_frame != 0) {
        ++stats.keyed_frames;
    }
    keyed_this_frame = 0;
    gbuffer_seen = edit_tried = show_due = false;
    keyed_in_pass = 0;
    gbuffer_depth = gbuffer_material = gbuffer_albedo = gbuffer_specular = gbuffer_normal = {};
    ++frame;
    if (++stats.frames < LineFrames) {
        return;
    }
    // The host copy of the last frame with a pass whose next frame had one too (no fence is waited
    // for: a log line).
    std::array<u32, R::SlotWords> c{};
    if (readback.mapped) {
        std::memcpy(c.data(), readback.mapped, sizeof(c));
    }
    BbReport::Printf("Blood sheen (r100d): %u frames, %u with keyed draws (%u draws, %u over cap %u), %u wet "
                     "passes, %u shows; left out: %u lamps open, %u passes no keyed draw, %u keyed at lamps "
                     "open, %u unfit, %u no room, %u previews%s\n",
                     stats.frames, stats.keyed_frames, stats.keyed, stats.over_cap, R::MaxKeyedDraws, stats.edits,
                     stats.shows, stats.edit_pending, stats.no_key_draw, stats.lamps_pending, stats.cannot,
                     stats.no_room, stats.previews, failed ? " (off after a failure)" : "");
    BbReport::Printf("Blood sheen (r100d): recent frame: keyed draws changed %u px; at the light %u still "
                     "theirs, %u drawn over later; %u passed the albedo rule; %u made wet\n",
                     c[R::WordKeyed], c[R::WordKept], c[R::WordLost], c[R::WordRule], c[R::WordWet]);
    // bbport (r100e_blood-sheen-visible): what the made-wet pixels had before the film (the pool's own
    // gloss and specular root: a film at or below them changes nothing) and the passes that flattened.
    const double wet = std::max(1.0, double(c[R::WordWet]));
    BbReport::Printf("Blood sheen (r100e): before the film, the %u made-wet px had mean gloss %.3f and mean specular "
                     "root %.3f (film %.2f and %.2f at strength 1), %u px (%.0f%%) already at gloss >= %.2f; %u of %u "
                     "wet passes flattened the normal\n",
                     c[R::WordWet], double(c[R::WordGlossSum]) / 255.0 / wet, double(c[R::WordRootSum]) / 255.0 / wet,
                     double(R::WetGloss), double(R::WetSpecRoot), c[R::WordGlossy],
                     100.0 * double(c[R::WordGlossy]) / wet, double(R::WetGloss), stats.normals, stats.edits);
    BbReport::Printf("Blood sheen (r100k): %u of %u shows with the luminance ceiling %.2f (0: none)\n",
                     stats.peak_shows, stats.shows, double(PeakCap()));
    {   // bbport (r129b_sheen-no-glow): the dry-scene reference and the ceiling of the last show copied to the host
        std::array<u32, R::Slots * R::RefSlotWords> ref{};
        if (readback.mapped && ref_read_valid) {
            std::memcpy(ref.data(), static_cast<const char*>(readback.mapped) + SlotBytes, sizeof(ref));
        }
        const u32* words = ref.data() + ref_read_slot * R::RefSlotWords;
        const float rel = PeakCap();
        BbReport::Printf(
            "Blood sheen (r129b): dry-scene reference %.4f over %u samples, ceiling %.4f (%.2f x); %u wet px rolled off in "
            "the last show; rim levels by %s\n",
            double(R::RefMean(words[0], words[1])), words[1], double(R::PeakOf(rel, words[0], words[1])), double(rel),
            words[2], RimFull() ? "the fill weight (BB_BLOOD_SHEEN_RIM_FULL)" : "their specular weight");
    }
    {   // bbport (r130a_sheen-colour): the film colour knobs now
        const int tint = TintMode();
        BbReport::Printf( // r130a
            "Blood sheen (r130a): tint %d, gloss share %.2f, level share %.2f, dimming %.2f%s\n", tint,
            double(GlossShare()), double(LevelShare(tint)), double(DarkenNow(R::Load())), tint == 2 ? ", by redness" : "");
    }
    {   // bbport (r128d_lrt-sheen-interior): the counter that says the default pick draws
        const auto& knobs = R::Load();
        BbReport::Printf("Blood sheen (r128d): %u of %u frames had keyed draws; strength from %s, %s\n",
                         stats.keyed_frames, stats.frames,
                         knobs.from_ini ? "the setting graphics_blood_sheen" : "BB_BLOOD_SHEEN",
                         knobs.default_pick ? "default draw and rule" : "draw and rule from the environment");
    }
    stats = {};
}

} // namespace Vulkan
