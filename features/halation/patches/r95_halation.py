# r95_halation: FEATURE patch (order item 11, "Halation"). Film halation: a soft red-orange glow
# that bleeds from very bright small sources (lamps, candles, the torch flame, bright windows, the
# moon) into the dark around them, tighter and redder than the game's own bloom (which is untouched).
# Off by default behind the environment knob BB_HALATION (strength 0..2; unset or 0: off).
#
# What (new files; the shared files get only hook lines, each insertion a block of its own):
#  1. renderer_vulkan/halation_params.h (new, pure): knobs (BB_HALATION, BB_HALATION_RADIUS,
#     BB_HALATION_THRESHOLD, BB_HALATION_SHOW, read once), the 80-byte push block, the key's fixed
#     point, sizes. tests/test_halation.cpp (new): its checks, built and run by engine/build.sh
#     --test and the CMake target halation-test.
#     host_shaders/halation_layout.h (new, plain #define lines): the pass numbers, the show value,
#     the key slot's words and the workgroup size, which the shader includes (GL_GOOGLE_include_
#     directive) and halation_params.h includes and ties to its enums with static_asserts.
#  2. host_shaders/halation.comp (new, one build, four passes by the push word `mode`): down (4x4
#     scene pixels -> one quarter texel of their soft-capped excess over key * 2^threshold, and the
#     frame's log-luminance sums for the next frame's key), blur x, blur y (Gaussian, bilinear
#     pairs), add (bilinear upsample, tint, added into the scene in place; untouched pixels are not
#     written).
#  3. renderer_vulkan/vk_halation.h/.cpp (new): class Halation: the pass at the upscaler's trigger,
#     the scene's view (reduced proxy or the game's image), two quarter RGBA16F images, the key
#     buffer (2 x 16 bytes) and its 16-byte host copy, the once-lines and the 600-frame line.
#  Hooks in shared files:
#   - vk_rasterizer.h: the include (after r62's vk_card_alpha.h include) and the member (after
#     froyok_bloom).
#   - vk_rasterizer.cpp: made after the upscaler, only when Halation::Wanted().
#   - vk_rasterizer_effects.cpp: EffectsOnFrameEnd (after froyok_bloom->OnFrameEnd()) and
#     EffectsBeforeUpscaler (before r62's card debug view, so after the drawn look and the fog).
#   - engine/gpu/CMakeLists.txt: add_host_shader's dependency on halation_layout.h (after r81's
#     volumetric_area_layout.h block), the shader build (after the froyok upsample build) and the
#     halation-test target (before r51's volumetric-occlusion-test block).
#   - engine/build.sh: halation-test (after wind-test).
#   - engine/tests/test_effect_pipelines.cpp: the include and the pipeline row (after froyok's).
#   - README.md: a "Halation (in development)" section before "## Sponsors".
#
# Off: the rasterizer makes no Halation (unique_ptr stays null); the two hooks test that pointer;
# no pipeline, image, buffer, pass or barrier; the frame is bit-identical. The shader's SPIR-V is in
# the binary only as a header array. Existing shader builds are not touched.
#
# Reviewed 2026-11-15 (this .fixed.py): the test's "too large" key case was wrong (4320 lines fit);
# the shader's numbers moved into halation_layout.h, tied to the C++ enums by static_asserts and a
# CMake dependency; RGBA16F overflow clamps; README log name and exact rules; descriptor writes in
# the form vk_card_alpha.cpp compiles.
# Use: python -I -X utf8 r95_halation.fixed.py check | apply | revert. Root from R95_HALATION_ROOT (or
# R95_ROOT), else <tree>. Files keep their line ends (CRLF in the tree); new files are written
# with CRLF. apply keeps the edited files' originals in r95_backup/ next to this script. revert
# removes exactly this patch's blocks (so patches applied after it in the same files stay) and the
# new files (only when unchanged); it refuses when a block is not found exactly once.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r95_backup")
ROOT = os.environ.get("R95_HALATION_ROOT") or os.environ.get("R95_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    R + "halation_params.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r95_halation): film halation, the soft red-orange glow that bleeds from very bright
// small sources (lamps, candles, the torch flame, bright windows, the moon) into the dark around
// them. Unlike the game's own bloom (wide, the colour of its light, added in the game's final
// composite) it is tight and red-orange, as light that passed the film and came back from its base
// into the red layer. The pass (vk_halation.cpp, host_shaders/halation.comp) runs on the scene
// colour right before the upscaler, at the scene's render size, after the fog. This header holds
// the knobs and the push words; no Vulkan here: tests/test_halation.cpp builds it alone.
//
// Knobs (environment, read once at the first use; Load):
//   BB_HALATION            strength 0..2; unset, empty, 0, a negative or non-numeric text: off
//                          (the rasterizer makes no Halation: no pipeline, image, buffer or pass)
//   BB_HALATION_RADIUS     0.5..3, factor on the glow's width (DefaultRadius 1: a Gaussian blur
//                          of SigmaAt1080 pixels at 1080 lines, the same share at any size)
//   BB_HALATION_THRESHOLD  1..8 stops over the frame's key a pixel must pass to glow (3.5)
//   BB_HALATION_SHOW       test only: 1 the glow ShowGain times as strong and the threshold
//                          ShowThresholdDrop stops lower; 2 as 1, the glow alone on black
// A missing or unreadable radius or threshold takes the default; then the range is applied.
//
// The passes (HalationParams::Mode, one shader build):
//   Down   a quarter of the size: each texel the mean of its 4x4 scene pixels' excess over the
//          threshold T = key * 2^threshold, each pixel's excess e soft-capped as e / (1 + e / C)
//          with C = T * 2^CapStops (so a single spark adds at most C / 16 to its texel, a window or
//          a flame its full excess), in the pixel's own colour. The key is the log-mean luminance
//          of the frame BEFORE (its sums in the key buffer's other slot), this frame's sums go into
//          its slot (fixed point, KeyScale and KeyBias, also in the push words).
//   BlurX, BlurY  a separable Gaussian of sigma Sigma() quarter texels, Taps() texels a side
//          (two texels a bilinear read).
//   Add    every scene pixel: + gain * (luma(g) * tint * (1 - HueKeep) + g * HueKeep), g the
//          blurred texel read bilinearly; a pixel whose glow is below 1e-6 is not written.

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/halation_layout.h"

namespace Vulkan::HalationParams {

inline constexpr float MaxStrength = 2.0f;
inline constexpr float DefaultRadius = 1.0f, MinRadius = 0.5f, MaxRadius = 3.0f;
inline constexpr float DefaultThreshold = 3.5f, MinThreshold = 1.0f, MaxThreshold = 8.0f;
/// The blur's sigma in scene pixels at radius 1 and 1080 lines (about 1.1% of the height).
inline constexpr float SigmaAt1080 = 12.0f;
/// The glow added per unit of the blurred, capped excess at strength 1.
inline constexpr float Gain = 0.06f;
/// The soft cap of a pixel's excess, in stops over the threshold.
inline constexpr float CapStops = 6.0f;
/// The share of the glow that keeps the source's own colour; the rest is the film's tint.
inline constexpr float HueKeep = 0.25f;
/// The film's red-orange (1, 0.36, 0.14), scaled to a Rec. 709 luminance of 1.
inline constexpr float TintLuma = 0.2126f * 1.0f + 0.7152f * 0.36f + 0.0722f * 0.14f;
inline constexpr float TintR = 1.0f / TintLuma, TintG = 0.36f / TintLuma, TintB = 0.14f / TintLuma;
/// BB_HALATION_SHOW 1 and 2.
inline constexpr float ShowGain = 4.0f, ShowThresholdDrop = 1.5f;
/// The blur reads at most this many texels a side.
inline constexpr std::uint32_t MaxTaps = 64;
/// The key's fixed point: (clamp(log2(max(mean, KeyFloor)), -KeyBias, KeyBias) + KeyBias) * KeyScale
/// a quarter texel, summed with 32-bit atomics.
inline constexpr float KeyScale = 64.0f, KeyBias = 16.0f, KeyFloor = 1e-4f;
/// One slot of the key buffer: sum, count, pixels over the threshold, unused (4 words). Two slots:
/// this frame's and the frame before's.
inline constexpr std::uint32_t KeySlotWords = 4, KeySlotBytes = KeySlotWords * 4, KeySlots = 2;

enum Mode : std::uint32_t { Down = 0, BlurX = 1, BlurY = 2, Add = 3, ModeCount = 4 };
enum Show : std::uint32_t { ShowOff = 0, ShowStrong = 1, ShowGlowOnly = 2 };
// The shader's numbers (halation_layout.h) are these, tied here.
static_assert(Down == HALATION_MODE_DOWN && BlurX == HALATION_MODE_BLUR_X &&
              BlurY == HALATION_MODE_BLUR_Y && Add == HALATION_MODE_ADD);
static_assert(ShowGlowOnly == HALATION_SHOW_GLOW_ONLY);
static_assert(KeySlotWords == HALATION_SLOT_WORDS);
/// Pixels or texels a side of one workgroup (the dispatches' rounding).
inline constexpr std::uint32_t Group = HALATION_GROUP;

struct Knobs {
    float strength = 0.0f; ///< 0: off
    float radius = DefaultRadius;
    float threshold = DefaultThreshold;
    std::uint32_t show = ShowOff;
};

/// What halation.comp's push block holds, word for word (20 words).
struct Push {
    std::uint32_t mode, slot, scene_w, scene_h;
    std::uint32_t quarter_w, quarter_h, taps, show;
    float sigma, threshold_stops, cap_stops, gain;
    float tint_r, tint_g, tint_b, hue_keep;
    float key_scale, key_bias, key_floor, pad0;
};
static_assert(sizeof(Push) == 80);

/// A number from the environment's text; `fallback` when unset, empty, unreadable or not finite.
inline float Number(const char* text, float fallback) {
    if (text == nullptr || text[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const float value = std::strtof(text, &end);
    return end != text && std::isfinite(value) ? value : fallback;
}

inline Knobs Read(const char* strength, const char* radius, const char* threshold,
                  const char* show) {
    Knobs k;
    const float s = Number(strength, 0.0f);
    k.strength = s > 0.0f ? std::min(s, MaxStrength) : 0.0f;
    k.radius = std::clamp(Number(radius, DefaultRadius), MinRadius, MaxRadius);
    k.threshold = std::clamp(Number(threshold, DefaultThreshold), MinThreshold, MaxThreshold);
    k.show = show && (show[0] == '1' || show[0] == '2') && show[1] == '\0'
                 ? std::uint32_t(show[0] - '0')
                 : ShowOff;
    return k;
}

/// The knobs, read once.
inline const Knobs& Load() {
    static const Knobs knobs =
        Read(std::getenv("BB_HALATION"), std::getenv("BB_HALATION_RADIUS"),
             std::getenv("BB_HALATION_THRESHOLD"), std::getenv("BB_HALATION_SHOW"));
    return knobs;
}

/// The quarter image's side for a scene side (a texel per 4x4 pixels, the last one partial).
inline constexpr std::uint32_t Quarter(std::uint32_t n) {
    return (n + 3) / 4;
}

/// The blur's sigma in quarter texels for a scene `height` pixels high.
inline float Sigma(const Knobs& k, std::uint32_t height) {
    return SigmaAt1080 / 4.0f * k.radius * float(height) / 1080.0f;
}

/// Texels a side the blur reads: three sigmas, at least 1, at most MaxTaps.
inline std::uint32_t Taps(float sigma) {
    return std::clamp(std::uint32_t(std::ceil(3.0f * sigma)), 1u, MaxTaps);
}

/// The key's sums of a frame stay below 2^32 (every texel at most 2 * KeyBias * KeyScale).
inline constexpr bool KeyFits(std::uint32_t quarter_w, std::uint32_t quarter_h) {
    return double(quarter_w) * double(quarter_h) * double(2.0f * KeyBias * KeyScale) <
           4294967296.0;
}

/// The key (log-mean scene luminance) a slot's sum and count stand for; 0 without texels.
inline double KeyOf(std::uint32_t sum, std::uint32_t count) {
    return count ? std::exp2(double(sum) / double(count) / double(KeyScale) - double(KeyBias))
                 : 0.0;
}

inline float ThresholdStops(const Knobs& k) {
    return k.threshold - (k.show != ShowOff ? ShowThresholdDrop : 0.0f);
}

inline float GainOf(const Knobs& k) {
    return Gain * k.strength * (k.show != ShowOff ? ShowGain : 1.0f);
}

/// The push words of pass `mode` for a scene of width x height; `slot` is this frame's key slot.
inline Push Make(const Knobs& k, std::uint32_t width, std::uint32_t height, std::uint32_t slot,
                 Mode mode) {
    const float sigma = Sigma(k, height);
    return Push{
        .mode = mode,
        .slot = slot & 1u,
        .scene_w = width,
        .scene_h = height,
        .quarter_w = Quarter(width),
        .quarter_h = Quarter(height),
        .taps = Taps(sigma),
        .show = k.show,
        .sigma = sigma,
        .threshold_stops = ThresholdStops(k),
        .cap_stops = CapStops,
        .gain = GainOf(k),
        .tint_r = TintR,
        .tint_g = TintG,
        .tint_b = TintB,
        .hue_keep = HueKeep,
        .key_scale = KeyScale,
        .key_bias = KeyBias,
        .key_floor = KeyFloor,
        .pad0 = 0.0f,
    };
}

} // namespace Vulkan::HalationParams
''',
    R + "vk_halation.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): film halation, a red-orange glow around very bright small sources
// (halation_params.h has the knobs and the passes' rules; host_shaders/halation.comp the passes).
//
// Where: Rasterizer::EffectsBeforeUpscaler, at the upscaler's trigger dispatch, after the drawn
// look and the fog composite, on the scene colour the upscaler is about to take, at the scene's
// render size (the reduced scene while a preset renders below the game's size). So:
//  - the HUD is never touched: the game draws it after its final composite, on the upscaler's
//    output (docs/hdr-scene-path.md, "After the composite"), which this pass never sees;
//  - with DLSS (or FSR, XeSS, the engine's TAA) it runs on the internal frame (1920x1080 for 4K
//    output with DLSS Performance), a quarter of the output's pixels, and the upscaler takes the
//    glow as a smooth part of the scene. Its input is the jittered frame and nothing is
//    un-jittered: the jitter (under a pixel) is small against the blur (a sigma of 12 pixels at
//    1080 lines and radius 1), and the glow is added to the same jittered frame it came from;
//  - the glow is linear light before the game's exposure and tone curve, so it is compressed with
//    the light it comes from, and the game's bloom, added in that composite, stays apart from it;
//  - without the upscaler (BB_UPSCALER=none, or a GPU it cannot run on) the trigger is never
//    reached and nothing is drawn (said once at the start).
// A menu's 3D preview frame (CameraMotion::PreviewFrame) is left alone, as the drawn look does.
//
// Off (BB_HALATION unset or 0): the rasterizer makes no Halation (Wanted), so nothing of this is
// made or run; the frame is as before, bit for bit. On: the pipeline, the sampler and two small
// buffers are made at the first frame it runs; two quarter-size RGBA16F images (2.1 MB at a
// 1920x1080 scene) are made then and anew when the scene's size changes.
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/halation_params.h"
#include "video_core/renderer_vulkan/vk_common.h"

#include <vk_mem_alloc.h> // after vk_common.h: its Vulkan configuration first
#include "video_core/texture_cache/image.h"

namespace VideoCore {
class TextureCache;
}

namespace Vulkan {
class CameraMotion;
class Instance;
class Runtime;
class SceneTargets;
class Scheduler;

class Halation {
public:
    /// BB_HALATION names a strength above 0 (HalationParams::Load, read once).
    [[nodiscard]] static bool Wanted();
    /// Says the knobs once; `upscaler_on`: the upscaler runs, so the pass has its place.
    Halation(const Instance& instance, Scheduler& scheduler, VideoCore::TextureCache& texture_cache,
             Runtime& runtime, SceneTargets& scene_targets, CameraMotion& camera_motion,
             bool upscaler_on);
    ~Halation();
    Halation(const Halation&) = delete;
    Halation& operator=(const Halation&) = delete;

    /// The upscaler's trigger: the glow into the scene colour `color` (once a frame).
    void Apply(VideoCore::ImageId color);
    /// Every frame end: the counters, and every LineFrames frames the "Halation (r95):" line.
    void OnFrameEnd();

private:
    struct Quarter {
        VideoCore::UniqueImage image;
        vk::UniqueImageView view;
    };
    struct Buffer {
        vk::Buffer buffer;
        VmaAllocation allocation{};
        void* mapped = nullptr;
    };
    struct ViewEntry {
        vk::Image image{};
        u64 uid = 0;
        vk::ImageView view{};
        u64 last_use = 0;
    };

    bool Ready();
    bool MakeBuffer(Buffer& out, vk::DeviceSize size, bool host, vk::BufferUsageFlags usage);
    void FreeBuffer(Buffer& buffer);
    bool EnsureImages(u32 width, u32 height);
    void ReleaseImages();
    vk::ImageView CachedView(const VideoCore::Image& image);
    void Fail(const char* why);

    static constexpr u32 LineFrames = 600;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    CameraMotion& camera_motion;

    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::UniqueSampler sampler; ///< linear, clamped to the edge
    /// The two quarter images: A (the down pass, the blur's end) and B (between the blurs).
    std::array<Quarter, 2> quarter;
    u32 quarter_width = 0, quarter_height = 0;
    /// The key's two slots (HalationParams::KeySlotBytes each), device memory, and the host copy
    /// of the frame before's slot (copied by each pass, read by the line).
    Buffer key_buffer, readback;
    std::array<ViewEntry, 4> view_cache{};
    u64 view_uses = 0;
    bool tried = false;
    bool failed = false;
    bool applied = false; ///< this frame's trigger was handled (ran or skipped)
    u64 runs = 0;         ///< passes recorded; the key slot is runs & 1
    u32 last_width = 0, last_height = 0;

    struct Stats {
        u32 frames = 0, ran = 0, previews = 0, small = 0, no_room = 0;
    } stats;
};

} // namespace Vulkan
''',
    R + "vk_halation.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_halation.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "bbport_toggles.h"
#include "video_core/host_shaders/halation_comp.h"
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
namespace HP = HalationParams;
constexpr auto AllCommands = vk::PipelineStageFlagBits2::eAllCommands;
constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto Transfer = vk::PipelineStageFlagBits2::eTransfer;
constexpr auto ReadWrite = vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite;
constexpr auto Format = vk::Format::eR16G16B16A16Sfloat;
constexpr vk::ImageSubresourceRange ColorLevel{vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1};
constexpr vk::DeviceSize SlotBytes = HP::KeySlotBytes;

vk::DescriptorImageInfo Info(vk::ImageView view, vk::Sampler sampler = {}) {
    return {.sampler = sampler, .imageView = view, .imageLayout = vk::ImageLayout::eGeneral};
}
} // namespace

bool Halation::Wanted() {
    return HP::Load().strength > 0.0f;
}

Halation::Halation(const Instance& instance_, Scheduler& scheduler_,
                   VideoCore::TextureCache& texture_cache_, Runtime& runtime_,
                   SceneTargets& scene_targets_, CameraMotion& camera_motion_, bool upscaler_on)
    : instance{instance_}, scheduler{scheduler_}, texture_cache{texture_cache_},
      runtime{runtime_}, scene_targets{scene_targets_}, camera_motion{camera_motion_} {
    const auto& k = HP::Load();
    BbReport::Printf("Halation (r95, BB_HALATION=%.2f): radius %.2f (a blur of sigma %.1f pixels "
                     "at 1080 lines), threshold %.2f stops over the frame's key, glow gain %.3f, "
                     "show %u; on the scene before the upscaler, at its render size\n",
                     double(k.strength), double(k.radius), double(HP::SigmaAt1080 * k.radius),
                     double(HP::ThresholdStops(k)), double(HP::GainOf(k)), k.show);
    if (!upscaler_on) {
        BbReport::Printf("Halation (r95): no place in the frame without the upscaler "
                         "(BB_UPSCALER=none, or this GPU cannot run it); nothing is drawn\n");
    }
}

Halation::~Halation() {
    const auto device = instance.GetDevice();
    for (const auto& entry : view_cache) {
        if (entry.view) {
            device.destroyImageView(entry.view);
        }
    }
    FreeBuffer(key_buffer);
    FreeBuffer(readback);
}

bool Halation::MakeBuffer(Buffer& out, vk::DeviceSize size, bool host,
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

void Halation::FreeBuffer(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

bool Halation::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, Format) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eLinear) &&
        EffectPass::Create(instance, set_layout, layout, pipeline,
                           {eCombinedImageSampler, eStorageImage, eStorageBuffer},
                           sizeof(HP::Push), HALATION_COMP, "Halation") &&
        MakeBuffer(key_buffer, HP::KeySlots * SlotBytes, false,
                   vk::BufferUsageFlagBits::eStorageBuffer |
                       vk::BufferUsageFlagBits::eTransferSrc |
                       vk::BufferUsageFlagBits::eTransferDst) &&
        MakeBuffer(readback, SlotBytes, true, vk::BufferUsageFlagBits::eTransferDst);
    if (!made) {
        Fail("this GPU cannot run the pass");
        return false;
    }
    // No frame before yet: the line reads zeros (no key) until the second pass.
    std::memset(readback.mapped, 0, SlotBytes);
    return true;
}

void Halation::Fail(const char* why) {
    failed = true;
    BbReport::Printf("Halation (r95): off - %s\n", why);
    ReleaseImages();
}

void Halation::ReleaseImages() {
    for (auto& q : quarter) {
        if (q.image) {
            scheduler.DeferOperation(
                [image = std::move(q.image), view = std::move(q.view)]() mutable {
                    view.reset();
                    image.Destroy();
                });
        }
        q.view.reset();
    }
    quarter_width = quarter_height = 0;
}

bool Halation::EnsureImages(u32 width, u32 height) {
    if (quarter[0].image && quarter_width == width && quarter_height == height) {
        return true;
    }
    ReleaseImages();
    // Eight bytes a texel, two images.
    if (!EffectPass::HasRoom(instance, 16ull * width * height)) {
        return false;
    }
    const auto device = instance.GetDevice();
    for (u32 i = 0; i < quarter.size(); ++i) {
        auto& q = quarter[i];
        q.image = VideoCore::UniqueImage(device, instance.GetAllocator());
        q.image.Create(vk::ImageCreateInfo{
            .imageType = vk::ImageType::e2D,
            .format = Format,
            .extent = {width, height, 1},
            .mipLevels = 1,
            .arrayLayers = 1,
            .samples = vk::SampleCountFlagBits::e1,
            .tiling = vk::ImageTiling::eOptimal,
            .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
            .initialLayout = vk::ImageLayout::eUndefined,
        });
        SetObjectName(device, vk::Image(q.image), "Halation quarter {}", i);
        q.view = Check<"create halation image view">(device.createImageViewUnique({
            .image = vk::Image(q.image),
            .viewType = vk::ImageViewType::e2D,
            .format = Format,
            .subresourceRange = ColorLevel,
        }));
    }
    quarter_width = width;
    quarter_height = height;
    return true;
}

vk::ImageView Halation::CachedView(const VideoCore::Image& image) {
    const vk::Image handle = image.GetImage();
    ViewEntry* oldest = &view_cache[0];
    for (auto& entry : view_cache) {
        if (entry.view && entry.image == handle && entry.uid == image.image_uid) {
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
        .view = Check<"create halation scene view">(device.createImageView({
            .image = handle,
            .viewType = vk::ImageViewType::e2D,
            .format = Format,
            .subresourceRange = ColorLevel,
        })),
        .last_use = ++view_uses,
    };
    return oldest->view;
}

void Halation::Apply(VideoCore::ImageId color_id) {
    if (applied || failed || !color_id) {
        return;
    }
    applied = true;
    // A menu's 3D preview: its "scene" is one of the previews (the upscaler leaves it too).
    if (camera_motion.PreviewFrame()) {
        ++stats.previews;
        return;
    }
    if (!Ready()) {
        return;
    }
    auto& color = texture_cache.GetImage(color_id);
    if (color.info.pixel_format != Format) {
        Fail("the scene colour is not RGBA16F");
        return;
    }
    // The scene's size: the reduced one while a preset renders below the game's own size, else
    // the game's render size (its targets may be allocated larger).
    const bool reduced = scene_targets.Reduced() && scene_targets.EligibleScene(color);
    u32 width = color.info.size.width, height = color.info.size.height;
    if (reduced) {
        width = scene_targets.Size().width;
        height = scene_targets.Size().height;
    } else if (const auto render = camera_motion.RenderSize(); render[0] && render[1]) {
        width = std::min(width, render[0]);
        height = std::min(height, render[1]);
    }
    const u32 qw = HP::Quarter(width), qh = HP::Quarter(height);
    if (width < 16 || height < 16 || !HP::KeyFits(qw, qh)) {
        ++stats.small;
        return;
    }
    if (!EnsureImages(qw, qh)) {
        ++stats.no_room;
        return;
    }
    const SceneUseScope scene_use{"halation"};
    scheduler.EndRendering();
    vk::ImageView color_view{};
    if (reduced) {
        VideoCore::ImageViewInfo info;
        info.format = color.info.pixel_format;
        const auto proxy = scene_targets.Read(color_id, info, Compute, ReadWrite);
        if (!(proxy.usage & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the reduced scene colour is not a storage image");
            return;
        }
        color_view = proxy.view;
    } else {
        if (!(color.usage_flags & vk::ImageUsageFlagBits::eStorage)) {
            Fail("the scene colour is not a storage image");
            return;
        }
        color_view = CachedView(color);
        runtime.Transit(&color, vk::ImageLayout::eGeneral, Compute, ReadWrite);
        runtime.FlushBarriers();
    }
    scheduler.EndRendering();

    const auto& k = HP::Load();
    const u32 slot = u32(runs & 1);
    const bool first = runs == 0;
    ++runs;
    ++stats.ran;
    if (width != last_width || height != last_height) {
        last_width = width;
        last_height = height;
        BbReport::Printf("Halation (r95): on at %ux%u (%s), quarter %ux%u, blur sigma %.2f "
                         "quarter texels, %u a side\n",
                         width, height, reduced ? "reduced scene" : "the game's scene", qw, qh,
                         double(HP::Sigma(k, height)), HP::Taps(HP::Sigma(k, height)));
    }
    std::array<HP::Push, HP::ModeCount> push{};
    for (u32 mode = 0; mode < HP::ModeCount; ++mode) {
        push[mode] = HP::Make(k, width, height, slot, HP::Mode(mode));
    }

    EffectPass::Mark(95, "halation");
    scheduler.RecordCrumb(
        {.name = "halation"},
        [push, width, height, qw, qh, slot, first, color_view, sampler = *sampler,
         a_image = vk::Image(quarter[0].image), b_image = vk::Image(quarter[1].image),
         a_view = *quarter[0].view, b_view = *quarter[1].view, key = key_buffer.buffer,
         host = readback.buffer, pipeline = *pipeline,
         layout = *layout](vk::CommandBuffer cmd) {
            // The scene's writes before this, and the frame before's reads of the images and of
            // the key's slots.
            EffectPass::MemoryBarrier(cmd, AllCommands, vk::AccessFlagBits2::eMemoryWrite,
                                      Compute | Transfer,
                                      ReadWrite | vk::AccessFlagBits2::eTransferRead |
                                          vk::AccessFlagBits2::eTransferWrite);
            std::array<vk::ImageMemoryBarrier2, 2> to_general;
            to_general.fill({
                .srcStageMask = AllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eNone,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderStorageWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .subresourceRange = ColorLevel,
            });
            to_general[0].image = a_image;
            to_general[1].image = b_image;
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = u32(to_general.size()),
                                  .pImageMemoryBarriers = to_general.data()});
            // The frame before's slot to the host (the line's numbers); this frame's slot cleared.
            // The first pass has no frame before: both slots cleared.
            if (first) {
                cmd.fillBuffer(key, 0, HP::KeySlots * SlotBytes, 0);
            } else {
                cmd.copyBuffer(key, host, vk::BufferCopy{(1 - slot) * SlotBytes, 0, SlotBytes});
                cmd.fillBuffer(key, slot * SlotBytes, SlotBytes, 0);
            }
            EffectPass::MemoryBarrier(cmd, Transfer, vk::AccessFlagBits2::eTransferWrite,
                                      Compute | vk::PipelineStageFlagBits2::eHost,
                                      ReadWrite | vk::AccessFlagBits2::eHostRead);
            const vk::DescriptorBufferInfo key_info{key, 0, HP::KeySlots * SlotBytes};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            const auto run = [&](const HP::Push& p, vk::ImageView source, vk::ImageView target,
                                 u32 w, u32 h) {
                using enum vk::DescriptorType;
                const std::array infos{Info(source, sampler), Info(target)};
                const std::array writes{
                    vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                           .descriptorType = eCombinedImageSampler,
                                           .pImageInfo = &infos[0]},
                    vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                           .descriptorType = eStorageImage, .pImageInfo = &infos[1]},
                    vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                           .descriptorType = eStorageBuffer,
                                           .pBufferInfo = &key_info},
                };
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
                cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(p), &p);
                cmd.dispatch((w + HP::Group - 1) / HP::Group, (h + HP::Group - 1) / HP::Group, 1);
            };
            run(push[HP::Down], color_view, a_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::BlurX], a_view, b_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::BlurY], b_view, a_view, qw, qh);
            EffectPass::ComputeBarrier(cmd);
            run(push[HP::Add], a_view, color_view, width, height);
            EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite, AllCommands,
                                      vk::AccessFlagBits2::eMemoryRead |
                                          vk::AccessFlagBits2::eMemoryWrite);
        });
}

void Halation::OnFrameEnd() {
    applied = false;
    if (++stats.frames < LineFrames) {
        return;
    }
    // The host copy of a recent frame's key slot (no fence is waited for: a log line).
    std::array<u32, HP::KeySlotWords> words{};
    if (readback.mapped) {
        std::memcpy(words.data(), readback.mapped, sizeof(words));
    }
    const auto& k = HP::Load();
    const double key = HP::KeyOf(words[0], words[1]);
    const double pixels = double(words[1]) * 16.0;
    BbReport::Printf("Halation (r95): of %u frames, the glow drawn on %u at %ux%u; skipped: %u "
                     "menu previews, %u too small or too large, %u for want of video memory; a "
                     "recent frame's key %.4g (log-mean scene luminance), threshold %.4g, %.3f%% "
                     "of its pixels over it%s\n",
                     stats.frames, stats.ran, last_width, last_height, stats.previews, stats.small,
                     stats.no_room, key, key * std::exp2(double(HP::ThresholdStops(k))),
                     pixels > 0.0 ? 100.0 * double(words[2]) / pixels : 0.0,
                     failed ? " (off after a failure)" : "");
    stats = {};
}

} // namespace Vulkan
''',
    H + "halation_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): what the halation's shader (halation.comp) and the engine
// (renderer_vulkan/halation_params.h, which ties these to its enums with static_asserts) share.
// Plain #define lines only: the shader includes this file through GL_GOOGLE_include_directive and
// C++ includes it as it is, so one text holds every number both sides use.
#ifndef HALATION_LAYOUT_H
#define HALATION_LAYOUT_H

// The passes, by the push word `mode` (HalationParams::Mode).
#define HALATION_MODE_DOWN 0u
#define HALATION_MODE_BLUR_X 1u
#define HALATION_MODE_BLUR_Y 2u
#define HALATION_MODE_ADD 3u
// BB_HALATION_SHOW=2: the glow alone on black (HalationParams::ShowGlowOnly).
#define HALATION_SHOW_GLOW_ONLY 2u
// A key slot's words: log-luminance sum, texels, pixels over the threshold, unused
// (HalationParams::KeySlotWords).
#define HALATION_SLOT_WORDS 4u
// Pixels or texels a side of one workgroup (HalationParams::Group).
#define HALATION_GROUP 8u

#endif
''',
    H + "halation.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): film halation on the scene colour before the upscaler (BB_HALATION;
// renderer_vulkan/halation_params.h has the rules, vk_halation.cpp records the passes). One build,
// four passes chosen by the push word `mode`:
//   0 down    source: the scene (texelFetch); target: the quarter image A; the key buffer
//   1 blur x  source: A (bilinear); target: B
//   2 blur y  source: B (bilinear); target: A
//   3 add     source: A (bilinear); target: the scene, read and written in place
#version 450
#extension GL_GOOGLE_include_directive : require

#include "halation_layout.h"

layout(local_size_x = HALATION_GROUP, local_size_y = HALATION_GROUP, local_size_z = 1) in;

layout(binding = 0) uniform sampler2D source;
layout(binding = 1, rgba16f) uniform image2D target;
// Two slots of HalationParams::KeySlotWords words: log-luminance sum, texels, pixels over the
// threshold, unused. `slot` is this frame's (cleared before the down pass), the other the frame
// before's.
layout(binding = 2, std430) buffer KeySums {
    uint key_words[];
};

// HalationParams::Push, word for word.
layout(push_constant) uniform Push {
    uint mode;
    uint slot;
    uint scene_w;
    uint scene_h;
    uint quarter_w;
    uint quarter_h;
    uint taps;
    uint show;
    float sigma;
    float threshold_stops;
    float cap_stops;
    float gain;
    float tint_r;
    float tint_g;
    float tint_b;
    float hue_keep;
    float key_scale;
    float key_bias;
    float key_floor;
    float pad0;
};

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);
// The quarter images are RGBA16F: what is stored in them stays below half its largest finite value,
// so a weighted mean of it stays finite too (an infinity would reach the scene and the upscaler's
// history).
const float QUARTER_MAX = 32768.0;
const float HALF_MAX = 65504.0;

shared uint group_sum;
shared uint group_count;
shared uint group_over;

// A broken texel (NaN, infinite) adds nothing; a negative channel is no light.
vec3 Clean(vec3 c) {
    if (any(isnan(c)) || any(isinf(c))) {
        return vec3(0.0);
    }
    return clamp(c, vec3(0.0), vec3(HALF_MAX));
}

void Down() {
    const ivec2 q = ivec2(gl_GlobalInvocationID.xy);
    const bool inside = q.x < int(quarter_w) && q.y < int(quarter_h);
    if (gl_LocalInvocationIndex == 0u) {
        group_sum = 0u;
        group_count = 0u;
        group_over = 0u;
    }
    memoryBarrierShared();
    barrier();
    // The frame before's key; none yet (its first frame): no glow this frame.
    const uint before = (1u - slot) * HALATION_SLOT_WORDS;
    const uint before_count = key_words[before + 1u];
    const bool keyed = before_count > 0u;
    const float key =
        keyed ? exp2(float(key_words[before]) / float(before_count) / key_scale - key_bias) : 0.0;
    const float threshold = key * exp2(threshold_stops);
    const float cap = threshold * exp2(cap_stops);
    if (inside) {
        const ivec2 last = ivec2(int(scene_w) - 1, int(scene_h) - 1);
        vec3 glow = vec3(0.0);
        float tone = 0.0;
        uint over = 0u;
        for (int y = 0; y < 4; ++y) {
            for (int x = 0; x < 4; ++x) {
                const vec3 c = Clean(texelFetch(source, min(q * 4 + ivec2(x, y), last), 0).rgb);
                const float l = dot(c, LUMA);
                tone += l;
                if (keyed && l > threshold) {
                    const float excess = l - threshold;
                    glow += c * (excess / (1.0 + excess / cap) / l);
                    over += 1u;
                }
            }
        }
        imageStore(target, q, vec4(min(glow * (1.0 / 16.0), vec3(QUARTER_MAX)), 1.0));
        const float stops = clamp(log2(max(tone * (1.0 / 16.0), key_floor)), -key_bias, key_bias);
        atomicAdd(group_sum, uint((stops + key_bias) * key_scale + 0.5));
        atomicAdd(group_count, 1u);
        atomicAdd(group_over, over);
    }
    memoryBarrierShared();
    barrier();
    if (gl_LocalInvocationIndex == 0u && group_count > 0u) {
        const uint at = slot * HALATION_SLOT_WORDS;
        atomicAdd(key_words[at], group_sum);
        atomicAdd(key_words[at + 1u], group_count);
        atomicAdd(key_words[at + 2u], group_over);
    }
}

// A Gaussian of `sigma` texels along `axis`, `taps` texels a side, two texels a bilinear read.
void Blur(vec2 axis) {
    const ivec2 q = ivec2(gl_GlobalInvocationID.xy);
    if (q.x >= int(quarter_w) || q.y >= int(quarter_h)) {
        return;
    }
    const vec2 texel = 1.0 / vec2(quarter_w, quarter_h);
    const vec2 uv = (vec2(q) + 0.5) * texel;
    const float spread = 2.0 * sigma * sigma;
    vec3 sum = textureLod(source, uv, 0.0).rgb;
    float weights = 1.0;
    for (uint i = 1u; i <= taps; i += 2u) {
        const float a = float(i);
        const float b = float(i + 1u);
        const float wa = exp(-a * a / spread);
        const float wb = i + 1u <= taps ? exp(-b * b / spread) : 0.0;
        const float w = wa + wb;
        const vec2 d = axis * ((a * wa + b * wb) / w) * texel;
        sum += (textureLod(source, uv + d, 0.0).rgb + textureLod(source, uv - d, 0.0).rgb) * w;
        weights += 2.0 * w;
    }
    imageStore(target, q, vec4(sum / weights, 1.0));
}

void Add() {
    const ivec2 p = ivec2(gl_GlobalInvocationID.xy);
    if (p.x >= int(scene_w) || p.y >= int(scene_h)) {
        return;
    }
    // The quarter texel centres sit at 4q + 2 pixels.
    const vec2 uv = (vec2(p) + 0.5) * 0.25 / vec2(quarter_w, quarter_h);
    const vec3 g = textureLod(source, uv, 0.0).rgb;
    const float l = dot(g, LUMA);
    // Nothing to add: the pixel is left as it is (no read, no write).
    if (show != HALATION_SHOW_GLOW_ONLY && !(l * gain >= 1e-6)) {
        return;
    }
    const vec3 glow =
        gain * (l * vec3(tint_r, tint_g, tint_b) * (1.0 - hue_keep) + g * hue_keep);
    const vec4 scene = imageLoad(target, p);
    const vec3 sum = show == HALATION_SHOW_GLOW_ONLY ? glow : scene.rgb + glow;
    imageStore(target, p, vec4(min(sum, vec3(HALF_MAX)), scene.a));
}

void main() {
    if (mode == HALATION_MODE_DOWN) {
        Down();
    } else if (mode == HALATION_MODE_BLUR_X) {
        Blur(vec2(1.0, 0.0));
    } else if (mode == HALATION_MODE_BLUR_Y) {
        Blur(vec2(0.0, 1.0));
    } else if (mode == HALATION_MODE_ADD) {
        Add();
    }
}
''',
    "engine/tests/test_halation.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r95_halation): the halation's knobs and push words (halation_params.h). Pure: no Vulkan.
// Built and run by engine/build.sh --test and the CMake target halation-test.
#undef NDEBUG
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "gpu/shadps4/video_core/renderer_vulkan/halation_params.h"

using namespace Vulkan::HalationParams;

namespace {
bool Near(double a, double b, double eps = 1e-5) {
    return std::abs(a - b) <= eps;
}

/// The shader's fixed point for a quarter texel's mean luminance (halation.comp, Down).
std::uint32_t Encode(float mean) {
    const float stops = std::clamp(std::log2(std::max(mean, KeyFloor)), -KeyBias, KeyBias);
    return std::uint32_t((stops + KeyBias) * KeyScale + 0.5f);
}
} // namespace

int main() {
    // a. Off unless a strength above 0 is named; at most MaxStrength.
    assert(Read(nullptr, nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("0", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("-1", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("on", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("nan", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("inf", nullptr, nullptr, nullptr).strength == 0.0f);
    assert(Read("1", nullptr, nullptr, nullptr).strength == 1.0f);
    assert(Read("0.5", nullptr, nullptr, nullptr).strength == 0.5f);
    assert(Read("7", nullptr, nullptr, nullptr).strength == MaxStrength);

    // b. Radius and threshold: defaults for missing or unreadable text, then the ranges.
    const Knobs d = Read("1", nullptr, nullptr, nullptr);
    assert(d.radius == DefaultRadius && d.threshold == DefaultThreshold && d.show == ShowOff);
    assert(Read("1", "x", "y", nullptr).radius == DefaultRadius);
    assert(Read("1", "0.1", nullptr, nullptr).radius == MinRadius);
    assert(Read("1", "9", nullptr, nullptr).radius == MaxRadius);
    assert(Read("1", "2", nullptr, nullptr).radius == 2.0f);
    assert(Read("1", nullptr, "0", nullptr).threshold == MinThreshold);
    assert(Read("1", nullptr, "20", nullptr).threshold == MaxThreshold);
    assert(Read("1", nullptr, "5", nullptr).threshold == 5.0f);

    // c. Show: exactly "1" or "2".
    assert(Read("1", nullptr, nullptr, "1").show == ShowStrong);
    assert(Read("1", nullptr, nullptr, "2").show == ShowGlowOnly);
    assert(Read("1", nullptr, nullptr, "3").show == ShowOff);
    assert(Read("1", nullptr, nullptr, "12").show == ShowOff);
    assert(Read("1", nullptr, nullptr, "").show == ShowOff);

    // d. The quarter size covers every pixel; the blur's width is a share of the height.
    assert(Quarter(1920) == 480 && Quarter(1080) == 270 && Quarter(1078) == 270 &&
           Quarter(1) == 1 && Quarter(5) == 2);
    assert(Near(Sigma(d, 1080), 3.0) && Near(Sigma(d, 2160), 6.0) && Near(Sigma(d, 720), 2.0));
    assert(Taps(3.0f) == 9 && Taps(0.1f) == 1 && Taps(1000.0f) == MaxTaps);
    const Knobs wide = Read("1", "3", nullptr, nullptr);
    assert(Taps(Sigma(wide, 2160)) == 54); // the widest blur at a 2160-line scene still fits

    // e. The push words.
    const Push p = Make(d, 1920, 1080, 3, Add);
    assert(p.mode == Add && p.slot == 1 && p.scene_w == 1920 && p.scene_h == 1080);
    assert(p.quarter_w == 480 && p.quarter_h == 270 && p.taps == 9 && p.show == ShowOff);
    assert(Near(p.sigma, 3.0) && p.threshold_stops == DefaultThreshold && p.cap_stops == CapStops);
    assert(Near(p.gain, Gain) && p.hue_keep == HueKeep);
    assert(p.key_scale == KeyScale && p.key_bias == KeyBias && p.key_floor == KeyFloor);
    const Knobs strong = Read("2", nullptr, nullptr, "1");
    const Push s = Make(strong, 1920, 1080, 0, Down);
    assert(Near(s.gain, Gain * 2.0f * ShowGain) && s.slot == 0);
    assert(Near(s.threshold_stops, DefaultThreshold - ShowThresholdDrop));
    assert(Make(Read("1", nullptr, nullptr, "2"), 64, 64, 0, Add).show == ShowGlowOnly);

    // f. The tint is red-orange with a luminance of 1.
    assert(Near(0.2126 * TintR + 0.7152 * TintG + 0.0722 * TintB, 1.0, 1e-5));
    assert(TintR > TintG && TintG > TintB);

    // g. The key: the shader's fixed point and its decoding agree; sums fit 32 bits.
    for (const float mean : {0.001f, 0.02f, 0.18f, 1.0f, 40.0f}) {
        const double back = KeyOf(Encode(mean) * 1000u, 1000u);
        assert(std::abs(std::log2(back) - std::log2(double(mean))) <= 0.5 / KeyScale + 1e-6);
    }
    assert(Near(KeyOf(Encode(0.0f), 1), KeyFloor, 1e-6)); // black counts as the floor
    assert(KeyOf(0, 0) == 0.0);
    assert(KeyFits(Quarter(3840), Quarter(2160)));  // a 2160-line scene
    assert(KeyFits(Quarter(7680), Quarter(4320)));  // 4320 lines still fit (2048 x 1920 x 1080)
    assert(!KeyFits(Quarter(8192), Quarter(8192))); // too large: skipped, counted
    assert(2.0f * KeyBias * KeyScale * float(Quarter(3840)) * float(Quarter(2160)) < 4294967296.0f);

    std::printf("halation-test: all checks passed\n");
    return 0;
}
''',
}

# (anchor, block, where): the block is inserted right "after" or "before" the anchor, which must be
# found exactly once; revert removes the block, which must be found exactly once.
EDITS = {
    R + "vk_rasterizer.h": [
        ('#include "video_core/renderer_vulkan/vk_card_alpha.h" // bbport (r62_leaf-stage3)\n',
         '#include "video_core/renderer_vulkan/vk_halation.h" // bbport (r95_halation)\n',
         "after"),
        ("    std::unique_ptr<FroyokBloom> froyok_bloom;\n",
         "    /// bbport (r95_halation): made only with BB_HALATION above 0 (Halation::Wanted), else null.\n"
         "    std::unique_ptr<Halation> halation;\n",
         "after"),
    ],
    R + "vk_rasterizer.cpp": [
        ("    upscaler = std::make_unique<TemporalUpscaler>(instance, scheduler, texture_cache, runtime,\n"
         "                                                  *camera_motion, *scene_targets, *hdr_native);\n",
         "    // bbport (r95_halation): BB_HALATION above 0 only (Halation::Wanted, read once); otherwise\n"
         "    // no Halation is made and nothing of it runs. Its pipeline, buffers and images are made at\n"
         "    // the first frame it runs (EffectsBeforeUpscaler); without the upscaler it has no place.\n"
         "    if (Halation::Wanted()) {\n"
         "        halation = std::make_unique<Halation>(instance, scheduler, texture_cache, runtime,\n"
         "                                              *scene_targets, *camera_motion,\n"
         "                                              upscaler->Enabled());\n"
         "    }\n",
         "after"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("    froyok_bloom->OnFrameEnd();\n",
         "    if (halation) { // bbport (r95_halation)\n"
         "        halation->OnFrameEnd();\n"
         "    }\n",
         "after"),
        ("    // bbport (r62_leaf-stage3): BB_RT_CARD_ALPHA_VIEW: the card debug view, last, over all of it.\n",
         "    // bbport (r95_halation): BB_HALATION above 0: the film halation into the scene colour, after\n"
         "    // the drawn look and the fog; the HUD is drawn later, on the upscaler's output.\n"
         "    if (halation && compute_hash == upscaler->TriggerHash()) {\n"
         "        halation->Apply(upscaler->SceneColor());\n"
         "    }\n",
         "before"),
    ],
    "engine/gpu/CMakeLists.txt": [
        ("    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)\n"
         '    if (FILENAME MATCHES "^volumetric_(light|area_gate)")\n'
         "        list(APPEND INCLUDES ${SHADER_SRC}/volumetric_area_layout.h)\n"
         "    endif()\n",
         "    # bbport (r95_halation): the halation's numbers, shared with C++ (halation_params.h)\n"
         '    if (FILENAME MATCHES "^halation")\n'
         "        list(APPEND INCLUDES ${SHADER_SRC}/halation_layout.h)\n"
         "    endif()\n",
         "after"),
        ("add_host_shader(froyok_bloom.comp froyok_bloom_upsample_comp UPSAMPLE=1)\n",
         "# bbport (r95_halation): BB_HALATION above 0 only: the film halation's four passes, one build\n"
         "# (renderer_vulkan/vk_halation.cpp)\n"
         "add_host_shader(halation.comp halation_comp)\n",
         "after"),
        ("# bbport (r51_volumetric-leak): the volumetric march's cascades and knob (volumetric_occlusion.h)\n",
         "# bbport (r95_halation): the halation's knobs and push words (halation_params.h); also built and\n"
         "# run by engine/build.sh --test.\n"
         "add_executable(halation-test EXCLUDE_FROM_ALL ../tests/test_halation.cpp)\n"
         "target_compile_options(halation-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(halation-test PRIVATE ..)\n",
         "before"),
    ],
    "engine/build.sh": [
        ("    out/wind-test\n",
         "    # bbport (r95_halation): the halation's knobs and push words\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_halation.cpp -o out/halation-test\n'
         "    out/halation-test\n",
         "after"),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        ('#include "video_core/host_shaders/froyok_bloom_upsample_comp.h"\n',
         '#include "video_core/host_shaders/halation_comp.h" // bbport (r95_halation)\n',
         "after"),
        ('        {"froyok upsample", FROYOK_BLOOM_UPSAMPLE_COMP,\n'
         "         {eCombinedImageSampler, eCombinedImageSampler, eStorageImage}, 32},\n",
         "        // bbport (r95_halation): as vk_halation.cpp makes it (HalationParams::Push)\n"
         '        {"halation", HALATION_COMP, {eCombinedImageSampler, eStorageImage, eStorageBuffer}, 80},\n',
         "after"),
    ],
    "README.md": [
        ("## Sponsors\n", None, "before"),  # block: README_BLOCK below
    ],
}

README_BLOCK = r'''### Halation (in development)

Film halation: a soft red-orange glow that bleeds from the brightest small sources (lamps, candles, the torch flame, bright windows, the moon) into the dark around them. It is tighter and redder than the game's own bloom, which stays as it is. It is drawn into the scene before the upscaler, after the fog, at the scene's render size (1920x1080 for 4K output with DLSS Performance), so the HUD, which the game draws later on the upscaled picture, is never touched; without the upscaler (`BB_UPSCALER=none`) nothing is drawn. Off unless `BB_HALATION` names a strength above 0; then a few lines of the session log (with the Windows launcher, `last_session.log` in the `logs` folder) start with `Halation (r95`, among them one every 600 frames with the frames it drew on and the share of pixels over the threshold. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing and are part of no look; no ini key yet.

| Variable | What it does | Default |
|---|---|---|
| `BB_HALATION` | Strength, 0 to 2 (`1` the intended look). A pixel brighter than the threshold (see `BB_HALATION_THRESHOLD`) gives its excess e, softly capped near 6 stops over the threshold (e / (1 + e / C), C the threshold times 2^6), in its own colour, to a quarter-size image (the mean of each 4x4 pixels), which is blurred and added back: three quarters in the film's red-orange, a quarter in the source's own colour, 0.06 of the blurred excess at strength 1. The first frame draws no glow (no key yet). Unset, `0`, a negative number or text that is not a number: off, and nothing of it is made. Cost: an estimate of 0.05 to 0.1 ms at 1080p internal, about four times that at 2160p internal, not measured; 2.1 MB of video memory at 1080p internal. It is the `Lighting: halation` row of `BB_GPU_PROFILE=1` | off |
| `BB_HALATION_RADIUS` | Width of the glow, 0.5 to 3: at 1 a Gaussian blur of sigma 12 pixels at 1080 lines, the same share of the picture at every render size | `1` |
| `BB_HALATION_THRESHOLD` | Stops over the frame's key a pixel's luminance must pass to glow, 1 to 8. The key is the log-mean, over the frame before, of the mean luminance of each 4x4 pixels (each mean taken as at least 0.0001) | `3.5` |
| `BB_HALATION_SHOW` | Test only: `1` the glow 4 times as strong and the threshold 1.5 stops lower; `2` as `1`, with the glow alone on black in place of the picture | off |

'''
EDITS["README.md"][0] = ("## Sponsors\n", README_BLOCK, "before")

# README numbers tied to the header's constants (defaults written twice).
TIES = [("DefaultRadius = 1.0f", "| `BB_HALATION_RADIUS` |", "| `1` |"),
        ("MinRadius = 0.5f, MaxRadius = 3.0f", "| `BB_HALATION_RADIUS` |", "0.5 to 3"),
        ("DefaultThreshold = 3.5f", "| `BB_HALATION_THRESHOLD` |", "| `3.5` |"),
        ("MinThreshold = 1.0f, MaxThreshold = 8.0f", "| `BB_HALATION_THRESHOLD` |", "1 to 8"),
        ("MaxStrength = 2.0f", "| `BB_HALATION` |", "0 to 2"),
        ("SigmaAt1080 = 12.0f", "| `BB_HALATION_RADIUS` |", "sigma 12 pixels at 1080 lines"),
        ("Gain = 0.06f", "| `BB_HALATION` |", "0.06 of the blurred excess"),
        ("CapStops = 6.0f", "| `BB_HALATION` |", "6 stops over the threshold"),
        ("HueKeep = 0.25f", "| `BB_HALATION` |", "a quarter in the source's own colour"),
        ("ShowGain = 4.0f, ShowThresholdDrop = 1.5f", "| `BB_HALATION_SHOW` |",
         "4 times as strong and the threshold 1.5 stops lower"),
        ("KeyFloor = 1e-4f", "| `BB_HALATION_THRESHOLD` |", "at least 0.0001"),
        ("CapStops = 6.0f", "| `BB_HALATION` |", "the threshold times 2^6")]

PARAMS = R + "halation_params.h"


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def insert(text, anchor, block, where):
    return text.replace(anchor, anchor + block if where == "after" else block + anchor)


def text_checks(texts):
    for path, edits in EDITS.items():
        for anchor, block, where in edits:
            if texts[path].count(block) != 1 or texts[path].count(anchor) != 1:
                raise SystemExit("text check: %s: block or anchor not found exactly once: %r"
                                 % (path, block[:70]))
    for const, row, value in TIES:
        line = [l for l in texts["README.md"].split("\n") if l.startswith(row)]
        if NEW[PARAMS].count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    for path, text in list(NEW.items()) + [("README block", README_BLOCK)]:
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R95_HALATION_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(block) == 1 for anchor, block, where in edits)
        todo = sum(cur.count(anchor) == 1 and cur.count(block) == 0 for anchor, block, where in edits)
        if done == len(edits):
            state = "applied"
        elif todo == len(edits):
            state = "clean"
        else:
            raise SystemExit("%s: %d of %d blocks in place, %d anchors found once without their block"
                             % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            state = "clean"
        elif open(full, "rb").read() == new_bytes(text):
            state = "applied"
        else:
            raise SystemExit("%s exists and is not this patch's file" % path)
        plan.append((path, None, None, None, None, state))
    states = {p[5] for p in plan}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join("%s %s" % (p[0], p[5]) for p in plan))
    state = states.pop()
    edited = [p for p in plan if p[1] is not None]
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in edited})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in edited:
                for anchor, block, where in edits:
                    cur = insert(cur, anchor, block, where)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied":
            print("already applied")
            return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for anchor, block, where in edits:
                cur = insert(cur, anchor, block, where)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, path.replace("/", "__")), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                full = os.path.join(ROOT, path)
                tmp = full + ".r95tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r95tmp"
                if os.path.exists(tmp):
                    os.remove(tmp)
            for path, raw in written:
                if raw is None:
                    os.remove(os.path.join(ROOT, path))
                else:
                    open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied (%d files edited, %d new)" % (len(edited), len(NEW)))
        return
    if state != "applied":
        print("nothing to revert")
        return
    for path, edits, raw, eol, cur, _ in edited:
        for anchor, block, where in reversed(edits):
            if cur.count(block) != 1:
                raise SystemExit("%s: block not found exactly once: %r" % (path, block[:70]))
            cur = cur.replace(block, "", 1)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(edited), len(NEW)))


main()
