// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r45_drawn-look): the drawn look's passes (paint_prep.comp, paint_stats.comp,
// paint_mips.comp, paint_key.comp, paint_strokes.comp, paint_lock.comp) on a synthetic scene,
// with the words the renderer gives them (DrawnLookParams::Make) and recorded as the renderer
// records them. Checked here:
//  - a stroke belongs to a place in the world: the test view, which paints every stroke in a flat
//    colour of its own, gives the same picture, moved, when the jitter or the camera moves, and
//    so does what the look itself changes in the picture;
//  - the look keeps the picture's colours: the mean colour of every surface stays, the sky and
//    the alpha are not touched, a brighter or darker scene (another exposure) gets the same look;
//  - it flattens fine grit, leaves what moves by itself without strokes, and a colour that is no
//    number does not spread;
//  - (r45b_drawn-look-fixes) what moves by itself is told against the camera's own move: a wall
//    with a vector in the object motion image gets its strokes whatever the camera does, a ball
//    that lies still does too, one that moves does not; and which small draws count as
//    transparents (DrawnLookParams::SmallTransparent).
//
// drawn-look-test [picture.bmp]: with a path, four views of the scene are also written.
// drawn-look-test --picture in.bmp out [2]: the look on a picture (24-bit BMP, sRGB), laid on a
// floor and a wall for want of its depth; writes out_before.bmp, out_after.bmp, out_full.bmp
// (strength 1) and out_sizes.bmp (test view 1), prints what the look does to the picture's
// colours and what the passes cost on this GPU. "2": at half the picture's size; a number of
// lines (1440): at that height.
#include <algorithm>
#include <array>
#include <bit>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <span>
#include <string>
#include <vector>
#define VULKAN_HPP_NO_CONSTRUCTORS
#define VULKAN_HPP_NO_EXCEPTIONS
#define VULKAN_HPP_DISPATCH_LOADER_DYNAMIC 1
#include <vulkan/vulkan.hpp>
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

VULKAN_HPP_DEFAULT_DISPATCH_LOADER_DYNAMIC_STORAGE

namespace {
using u8 = uint8_t;
using u16 = uint16_t;
using u32 = uint32_t;
using Vec3 = std::array<double, 3>;
using Half4 = std::array<u16, 4>;
using Rgb = std::array<float, 3>;
namespace Look = Vulkan::DrawnLookParams;

constexpr vk::ImageSubresourceRange Range{vk::ImageAspectFlagBits::eColor, 0,
                                          VK_REMAINING_MIP_LEVELS, 0, 1};
constexpr double Near = 0.1;

template <class T>
T Check(vk::ResultValue<T> result) {
    if (result.result != vk::Result::eSuccess) {
        std::fprintf(stderr, "Vulkan call failed: %s\n", vk::to_string(result.result).c_str());
        std::abort();
    }
    return std::move(result.value);
}

u16 ToHalf(float value) {
    u32 bits;
    std::memcpy(&bits, &value, 4);
    const u32 sign = (bits >> 16) & 0x8000u;
    const int exponent = int((bits >> 23) & 0xff) - 127 + 15;
    u32 mantissa = bits & 0x7fffffu;
    if (exponent <= 0) {
        if (exponent < -10) {
            return u16(sign);
        }
        mantissa = (mantissa | 0x800000u) >> (1 - exponent);
        return u16(sign | ((mantissa + 0x1000u) >> 13));
    }
    if (exponent >= 31) {
        return u16(sign | 0x7c00u);
    }
    return u16((sign | (u32(exponent) << 10) | (mantissa >> 13)) + ((mantissa >> 12) & 1u));
}

float FromHalf(u16 half) {
    const int exponent = (half >> 10) & 31;
    const float mantissa = float(half & 1023u) / 1024.0f;
    if (exponent == 31) {
        return mantissa != 0.0f ? NAN : (half & 0x8000u) ? -INFINITY : INFINITY;
    }
    const float value = exponent == 0 ? std::ldexp(mantissa, -14)
                                      : std::ldexp(1.0f + mantissa, exponent - 15);
    return (half & 0x8000u) ? -value : value;
}

Vec3 Add(const Vec3& a, const Vec3& b, double s = 1.0) {
    return {a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s};
}
double Dot(const Vec3& a, const Vec3& b) {
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

/// View axes: x right, y down, z forward. The world is y-up, as the game's.
struct Camera {
    Vec3 pos{};
    double yaw = 0.0, pitch = 0.0; ///< radians; yaw 0 looks along world z
    std::array<float, 2> jitter{};

    Vec3 Forward() const {
        return {std::sin(yaw) * std::cos(pitch), std::sin(pitch), std::cos(yaw) * std::cos(pitch)};
    }
    Vec3 Right() const {
        return {std::cos(yaw), 0.0, -std::sin(yaw)};
    }
    Vec3 Down() const {
        const Vec3 f = Forward(), r = Right();
        return {-(f[1] * r[2] - f[2] * r[1]), -(f[2] * r[0] - f[0] * r[2]),
                -(f[0] * r[1] - f[1] * r[0])};
    }
    std::array<float, 12> InvView() const {
        const Vec3 r = Right(), d = Down(), f = Forward();
        std::array<float, 12> rows;
        for (int i = 0; i < 3; ++i) {
            rows[i * 4 + 0] = float(r[i]);
            rows[i * 4 + 1] = float(d[i]);
            rows[i * 4 + 2] = float(f[i]);
            rows[i * 4 + 3] = float(pos[i]);
        }
        return rows;
    }
    /// World to view, 3x4 rows.
    std::array<float, 12> View() const {
        const std::array<Vec3, 3> axes{Right(), Down(), Forward()};
        std::array<float, 12> rows;
        for (int i = 0; i < 3; ++i) {
            for (int k = 0; k < 3; ++k) {
                rows[i * 4 + k] = float(axes[i][k]);
            }
            rows[i * 4 + 3] = float(-Dot(axes[i], pos));
        }
        return rows;
    }
};

/// The projection's scales for a screen of this shape: 50 degrees from top to bottom.
struct Lens {
    u32 width, height;
    double ys = 1.0 / std::tan(25.0 * 3.14159265358979 / 180.0);
    double xs = ys * double(height) / double(width);
    std::array<float, 4> Proj() const {
        return {float(xs), float(ys), 1.0f, float(-Near)};
    }
};

enum Surface : u8 { Sky, Floor, BackWall, SideWall, Column, Ball };

struct Hit {
    Surface surface = Sky;
    double t = 1e30; ///< the view depth: the ray's direction has view z 1
    Vec3 normal{0, 1, 0};
};

Hit Cast(const Vec3& o, const Vec3& d) {
    Hit hit;
    const auto take = [&](Surface surface, double t, const Vec3& normal) {
        if (t > Near && t < hit.t) {
            hit = {surface, t, normal};
        }
    };
    if (d[1] < 0.0) {
        const double t = -o[1] / d[1];
        const Vec3 p = Add(o, d, t);
        if (p[0] > -3.5 && p[0] < 12.0 && p[2] > -5.0 && p[2] < 9.0) {
            take(Floor, t, {0, 1, 0});
        }
    }
    if (d[2] > 0.0) {
        const double t = (9.0 - o[2]) / d[2];
        const Vec3 p = Add(o, d, t);
        if (p[1] > 0.0 && p[1] < 4.2 && p[0] > -3.5 && p[0] < 6.0) {
            take(BackWall, t, {0, 0, -1});
        }
    }
    if (d[0] < 0.0) {
        const double t = (-3.5 - o[0]) / d[0];
        const Vec3 p = Add(o, d, t);
        if (p[1] > 0.0 && p[1] < 4.2 && p[2] > -5.0 && p[2] < 9.0) {
            take(SideWall, t, {1, 0, 0});
        }
    }
    {
        // A round column: its normals turn from one stroke plane to the other.
        const double cx = 1.6, cz = 5.5, radius = 0.45;
        const double a = d[0] * d[0] + d[2] * d[2];
        const double b = (o[0] - cx) * d[0] + (o[2] - cz) * d[2];
        const double c = (o[0] - cx) * (o[0] - cx) + (o[2] - cz) * (o[2] - cz) - radius * radius;
        const double disc = b * b - a * c;
        if (a > 1e-12 && disc > 0.0) {
            const double t = (-b - std::sqrt(disc)) / a;
            const Vec3 p = Add(o, d, t);
            if (p[1] > 0.0 && p[1] < 3.4) {
                take(Column, t, {(p[0] - cx) / radius, 0.0, (p[2] - cz) / radius});
            }
        }
    }
    {
        // A ball that stands for a character: the motion image says it moves by itself.
        const Vec3 centre{-0.9, 0.95, 4.2};
        const double radius = 0.55;
        const Vec3 oc = Add(o, centre, -1.0);
        const double a = Dot(d, d), b = Dot(oc, d), c = Dot(oc, oc) - radius * radius;
        const double disc = b * b - a * c;
        if (disc > 0.0) {
            const double t = (-b - std::sqrt(disc)) / a;
            const Vec3 p = Add(o, d, t);
            take(Ball, t, {(p[0] - centre[0]) / radius, (p[1] - centre[1]) / radius,
                           (p[2] - centre[2]) / radius});
        }
    }
    return hit;
}

struct Scene {
    u32 width = 0, height = 0;
    std::vector<Half4> colour;                ///< RGBA16F: linear, alpha a pattern of its own
    std::vector<float> depth;                 ///< 1 - Near / view depth; 1: sky
    std::vector<std::array<u8, 4>> normal;    ///< world normal * 0.5 + 0.5
    std::vector<std::array<float, 4>> motion; ///< b 1 and a the depth on the ball
    std::vector<Surface> surface;
    std::vector<Vec3> world;

    Scene(u32 w, u32 h)
        : width{w}, height{h}, colour(size_t(w) * h), depth(size_t(w) * h), normal(size_t(w) * h),
          motion(size_t(w) * h) {}
};

u32 Hash(u32 v) {
    v = v * 747796405u + 2891336453u;
    const u32 w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

/// What a scene's surfaces look like. Plain: one flat colour a surface (there a stroke's colour
/// in the test view depends on nothing but which stroke it is). Lit: a lamp's light on them.
/// Grit: on top of the light, a fine pattern fixed to the world, 2.5 cm a speck, as a stone
/// texture has: what the look is there to flatten.
/// Patches: on top of the light, light and dark patches fixed to the world, 12 cm a patch, apart
/// by a share that rises and falls along the surfaces: somewhere on each of them the picture is
/// just rough enough to count as detail, and the look goes from bold strokes to fine ones.
enum class Paint { Plain, Lit, Grit, Patches };

/// What the object motion image holds for a scene. Without `before`: as the scenes of r45, the
/// ball alone has a vector, and it is zero. With `before` (the camera of the frame before and
/// its lens): the ball's vector is what the camera's own move makes of a still point there
/// plus `ball` pixels of its own, and with `world` every surface has a vector too, the
/// camera's: what the game's walls and floors drawn through a bone buffer have.
struct Vectors {
    const Camera* before = nullptr;
    const Lens* lens_before = nullptr;
    bool world = false;
    std::array<float, 2> ball{};
};

/// Where a world point lies on a camera's screen in pixels, without the jitter.
std::array<double, 2> Place(const Lens& lens, const Camera& camera, const Vec3& world) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    const double z = Dot(rel, camera.Forward());
    return {(Dot(rel, camera.Right()) * lens.xs / z * 0.5 + 0.5) * lens.width,
            (Dot(rel, camera.Down()) * lens.ys / z * 0.5 + 0.5) * lens.height};
}

Scene MakeScene(const Lens& lens, const Camera& camera, Paint paint, float exposure = 1.0f,
                const Vectors& vectors = {}) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    scene.surface.resize(size_t(w) * h);
    scene.world.resize(size_t(w) * h);
    const Vec3 r = camera.Right(), dn = camera.Down(), f = camera.Forward();
    static constexpr Rgb Colours[] = {{0.05f, 0.07f, 0.12f}, {0.16f, 0.14f, 0.12f},
                                      {0.30f, 0.27f, 0.22f}, {0.22f, 0.20f, 0.19f},
                                      {0.34f, 0.33f, 0.30f}, {0.25f, 0.08f, 0.07f}};
    for (u32 y = 0; y < h; ++y) {
        for (u32 x = 0; x < w; ++x) {
            const double nx = (x + 0.5 - camera.jitter[0]) / w * 2.0 - 1.0;
            const double ny = (y + 0.5 - camera.jitter[1]) / h * 2.0 - 1.0;
            const Vec3 dir = Add(Add(f, r, nx / lens.xs), dn, ny / lens.ys);
            const Hit hit = Cast(camera.pos, dir);
            const u32 i = y * w + x;
            const Vec3 p = Add(camera.pos, dir, hit.t);
            Rgb c = Colours[hit.surface];
            float light = exposure;
            if (paint != Paint::Plain && hit.surface != Sky) {
                const Vec3 to_lamp = Add(Vec3{0.5, 2.6, 3.0}, p, -1.0);
                const double distance2 = Dot(to_lamp, to_lamp);
                const double facing = std::max(Dot(hit.normal, to_lamp) / std::sqrt(distance2), 0.0);
                light *= float(0.25 + 6.0 * facing / (1.0 + distance2));
            }
            if (paint == Paint::Grit && hit.surface != Sky) {
                const auto cell = [&](int k) { return u32(int(std::floor(p[k] * 40.0)) + 4096); };
                light *= 0.8f + 0.4f * float(Hash(cell(0) + Hash(cell(1) + Hash(cell(2)))) >> 8) /
                                    16777216.0f;
            }
            if (paint == Paint::Patches && hit.surface != Sky) {
                // (Not on a whole number where a surface lies: the walls and the floor do.)
                const auto cell = [&](int k) {
                    return u32(int(std::floor(p[k] * 8.0 + 0.37)) + 4096);
                };
                const double wave = std::fmod((p[0] + p[2] + 100.0) / 6.0, 1.0);
                const double apart = 0.2 + 0.5 * (1.0 - std::abs(2.0 * wave - 1.0));
                const bool up = Hash(cell(0) + Hash(cell(1) + Hash(cell(2)))) & 0x100u;
                light *= float(up ? 1.0 + apart : 1.0 - apart);
            }
            for (float& channel : c) {
                channel *= light;
            }
            scene.colour[i] = {ToHalf(c[0]), ToHalf(c[1]), ToHalf(c[2]),
                               ToHalf(float((x * 7 + y * 13) % 32) / 64.0f)};
            scene.surface[i] = hit.surface;
            scene.depth[i] = hit.surface == Sky ? 1.0f : float(1.0 - Near / hit.t);
            scene.world[i] = p;
            for (int k = 0; k < 3; ++k) {
                scene.normal[i][k] = u8(std::lround((hit.normal[k] * 0.5 + 0.5) * 255.0));
            }
            scene.normal[i][3] = 255;
            if (hit.surface == Ball && !vectors.before) {
                scene.motion[i] = {0.0f, 0.0f, 1.0f, scene.depth[i]};
            } else if (vectors.before && hit.surface != Sky &&
                       (vectors.world || hit.surface == Ball)) {
                // Previous - current, pixels, as the game's vertex positions give it.
                const auto now = Place(lens, camera, p);
                const auto then = Place(*vectors.lens_before, *vectors.before, p);
                const bool ball = hit.surface == Ball;
                scene.motion[i] = {float(then[0] - now[0]) + (ball ? vectors.ball[0] : 0.0f),
                                   float(then[1] - now[1]) + (ball ? vectors.ball[1] : 0.0f),
                                   1.0f, scene.depth[i]};
            }
        }
    }
    return scene;
}

/// An image with all its levels down to one texel, as vk_drawn_look.cpp makes its three.
struct Image {
    vk::UniqueImage image;
    vk::UniqueDeviceMemory memory;
    vk::UniqueImageView view;                ///< all levels
    std::vector<vk::UniqueImageView> levels; ///< each level alone
};

/// What the passes take on the GPU, in milliseconds.
struct Times {
    double masks = 0.0;   ///< the copy, the marks and their levels
    double strokes = 0.0; ///< the stroke pass
    double lock = 0.0;    ///< the colour lock: the painted scene's means, and the scaling
};

class Gpu {
public:
    Gpu() {
        static vk::detail::DynamicLoader loader;
        VULKAN_HPP_DEFAULT_DISPATCHER.init(
            loader.getProcAddress<PFN_vkGetInstanceProcAddr>("vkGetInstanceProcAddr"));
        const vk::ApplicationInfo app{.pApplicationName = "drawn-look-test",
                                      .apiVersion = VK_API_VERSION_1_3};
        instance = Check(vk::createInstanceUnique({.pApplicationInfo = &app}));
        VULKAN_HPP_DEFAULT_DISPATCHER.init(*instance);
        const auto gpus = Check(instance->enumeratePhysicalDevices());
        assert(!gpus.empty());
        physical = gpus[0];
        std::printf("device: %s\n", physical.getProperties().deviceName.data());
        period_ns = physical.getProperties().limits.timestampPeriod;
        const auto families = physical.getQueueFamilyProperties();
        u32 family = 0;
        while (family < families.size() &&
               !(families[family].queueFlags & vk::QueueFlagBits::eCompute)) {
            ++family;
        }
        assert(family < families.size());
        timed = families[family].timestampValidBits == 64;
        const float priority = 1;
        const vk::DeviceQueueCreateInfo queue_info{.queueFamilyIndex = family,
                                                   .queueCount = 1,
                                                   .pQueuePriorities = &priority};
        const char* extension = VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME;
        device = Check(physical.createDeviceUnique({.queueCreateInfoCount = 1,
                                                    .pQueueCreateInfos = &queue_info,
                                                    .enabledExtensionCount = 1,
                                                    .ppEnabledExtensionNames = &extension}));
        VULKAN_HPP_DEFAULT_DISPATCHER.init(*device);
        queue = device->getQueue(family, 0);
        pool = Check(device->createCommandPoolUnique(
            {.flags = vk::CommandPoolCreateFlagBits::eResetCommandBuffer,
             .queueFamilyIndex = family}));
        command = Check(device->allocateCommandBuffers(
            {.commandPool = *pool,
             .level = vk::CommandBufferLevel::ePrimary,
             .commandBufferCount = 1}))[0];
        queries = Check(device->createQueryPoolUnique(
            {.queryType = vk::QueryType::eTimestamp, .queryCount = 4}));
        // As vk_drawn_look.cpp makes them.
        using enum vk::DescriptorType;
        prep = MakePass({eSampledImage, eSampledImage, eStorageImage}, PAINT_PREP_COMP);
        stats = MakePass({eSampledImage, eStorageImage, eStorageImage}, PAINT_STATS_COMP);
        mips = MakePass({eCombinedImageSampler, eCombinedImageSampler, eStorageImage, eStorageImage},
                        PAINT_MIPS_COMP);
        key_sums = MakePass({eSampledImage, eStorageImage}, PAINT_KEY_COMP);
        key_last = MakePass({eSampledImage, eStorageImage}, PAINT_KEY_LAST_COMP);
        strokes = MakePass({eCombinedImageSampler, eSampledImage, eSampledImage, eSampledImage,
                            eStorageImage, eCombinedImageSampler},
                           PAINT_STROKES_COMP);
        lock_first = MakePass({eSampledImage, eStorageImage}, PAINT_LOCK_FIRST_COMP);
        lock_down = MakePass({eCombinedImageSampler, eStorageImage}, PAINT_LOCK_DOWN_COMP);
        lock = MakePass({eCombinedImageSampler, eSampledImage, eSampledImage, eStorageImage,
                         eCombinedImageSampler},
                        PAINT_LOCK_COMP);
        sampler = Check(device->createSamplerUnique(
            {.magFilter = vk::Filter::eLinear,
             .minFilter = vk::Filter::eLinear,
             .mipmapMode = vk::SamplerMipmapMode::eLinear,
             .addressModeU = vk::SamplerAddressMode::eClampToEdge,
             .addressModeV = vk::SamplerAddressMode::eClampToEdge,
             .addressModeW = vk::SamplerAddressMode::eClampToEdge,
             .maxLod = VK_LOD_CLAMP_NONE}));
    }

    /// The scene colour after the passes.
    std::vector<Half4> Run(const Scene& scene, const Look::Params& params) {
        Load(scene);
        Begin();
        RecordMasks(params);
        RecordStrokes(params);
        if (ShowsLook(params)) {
            RecordLock(params);
        }
        const vk::BufferImageCopy region{
            .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .imageExtent = {width, height, 1}};
        command.copyImageToBuffer(*colour.image, vk::ImageLayout::eGeneral, *staging, region);
        Barrier();
        Submit();
        std::vector<Half4> out(size_t(width) * height);
        std::memcpy(out.data(), mapped, out.size() * sizeof(Half4));
        return out;
    }

    /// What the passes take on this GPU. An idle GPU runs its clock slow and speeds it up only
    /// under work, so a single run between two uploads tells nothing: each part is recorded
    /// `repeats` times in a row in one submission, after as many unmeasured rounds of all of
    /// them, and the best of three such submissions counts.
    Times Measure(const Scene& scene, const Look::Params& params, u32 repeats) {
        Load(scene);
        Times best{1e9, 1e9, 1e9};
        for (int round = 0; round < 3; ++round) {
            Begin();
            command.resetQueryPool(*queries, 0, 4);
            const auto stamp = [&](u32 query) {
                command.writeTimestamp(vk::PipelineStageFlagBits::eBottomOfPipe, *queries, query);
            };
            for (u32 i = 0; i < repeats; ++i) {
                RecordMasks(params);
                RecordStrokes(params);
                RecordLock(params);
            }
            stamp(0);
            for (u32 i = 0; i < repeats; ++i) {
                RecordMasks(params);
            }
            stamp(1);
            for (u32 i = 0; i < repeats; ++i) {
                RecordStrokes(params);
            }
            stamp(2);
            for (u32 i = 0; i < repeats; ++i) {
                RecordLock(params);
            }
            stamp(3);
            Submit();
            std::array<uint64_t, 4> stamps{};
            const auto read = device->getQueryPoolResults(
                *queries, 0, 4, sizeof(stamps), stamps.data(), sizeof(uint64_t),
                vk::QueryResultFlagBits::e64 | vk::QueryResultFlagBits::eWait);
            assert(read == vk::Result::eSuccess);
            const double ms = period_ns / 1e6 / repeats;
            best.masks = std::min(best.masks, double(stamps[1] - stamps[0]) * ms);
            best.strokes = std::min(best.strokes, double(stamps[2] - stamps[1]) * ms);
            best.lock = std::min(best.lock, double(stamps[3] - stamps[2]) * ms);
        }
        return best;
    }

    bool Timed() const {
        return timed;
    }

private:
    struct Pass {
        vk::UniqueDescriptorSetLayout set;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };

    /// The colour lock runs with the look; a test view has no colours to lock.
    static bool ShowsLook(const Look::Params& params) {
        const u32 view = Look::ViewOf(params.flags);
        return view == Look::ViewOff || view == Look::ViewInk;
    }

    void Load(const Scene& scene) {
        Resize(scene.width, scene.height);
        Upload(colour, scene.colour.data(), scene.colour.size() * sizeof(Half4));
        Upload(depth, scene.depth.data(), scene.depth.size() * sizeof(float));
        Upload(normal, scene.normal.data(), scene.normal.size() * 4);
        Upload(motion, scene.motion.data(), scene.motion.size() * 16);
    }

    void Dispatch(const Pass& pass, const Look::Params& params,
                  std::span<const vk::WriteDescriptorSet> writes, u32 w, u32 h) {
        command.bindPipeline(vk::PipelineBindPoint::eCompute, *pass.pipeline);
        command.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, *pass.layout, 0, writes);
        command.pushConstants(*pass.layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
        command.dispatch((w + 7) / 8, (h + 7) / 8, 1);
        Barrier();
    }

    vk::DescriptorImageInfo Info(const vk::UniqueImageView& view, bool sampled = false) const {
        return {.sampler = sampled ? *sampler : vk::Sampler{},
                .imageView = *view,
                .imageLayout = vk::ImageLayout::eGeneral};
    }

    static vk::WriteDescriptorSet Write(u32 binding, vk::DescriptorType type,
                                        const vk::DescriptorImageInfo* image) {
        return {.dstBinding = binding,
                .descriptorCount = 1,
                .descriptorType = type,
                .pImageInfo = image};
    }

    // The three parts below: as vk_drawn_look.cpp records them.
    void RecordMasks(const Look::Params& params) {
        using enum vk::DescriptorType;
        const u32 half_width = width / 2, half_height = height / 2;
        {
            const std::array infos{Info(colour.view), Info(depth.view), Info(copy.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eSampledImage, &infos[1]),
                                    Write(2, eStorageImage, &infos[2])};
            Dispatch(prep, params, writes, width, height);
        }
        {
            const std::array infos{Info(copy.levels[0]), Info(copy.levels[1]),
                                   Info(marks.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1]),
                                    Write(2, eStorageImage, &infos[2])};
            Dispatch(stats, params, writes, half_width, half_height);
        }
        for (u32 n = 1; n + 1 < copy.levels.size(); ++n) {
            const std::array infos{Info(copy.levels[n], true), Info(marks.levels[n - 1], true),
                                   Info(copy.levels[n + 1]), Info(marks.levels[n])};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eCombinedImageSampler, &infos[1]),
                                    Write(2, eStorageImage, &infos[2]),
                                    Write(3, eStorageImage, &infos[3])};
            Dispatch(mips, params, writes, std::max(half_width >> n, 1u),
                     std::max(half_height >> n, 1u));
        }
        u32 key_level = 0;
        while ((std::max(width, height) >> key_level) > 64) {
            ++key_level;
        }
        {
            const std::array infos{Info(copy.levels[key_level]), Info(means.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(key_sums, params, writes, 8, 8);
        }
        {
            const std::array infos{Info(means.levels[0]), Info(copy.levels.back())};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(key_last, params, writes, 8, 8);
        }
    }

    void RecordStrokes(const Look::Params& params) {
        using enum vk::DescriptorType;
        // A pass without normals or motion gets the copy in their place, as in the renderer.
        const bool normals = params.flags & Look::FlagNormals;
        const bool moving = params.flags & Look::FlagMotion;
        const std::array infos{Info(copy.view, true),
                               Info(depth.view),
                               Info(normals ? normal.view : copy.view),
                               Info(moving ? motion.view : copy.view),
                               Info(colour.view),
                               Info(marks.view, true)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eSampledImage, &infos[2]),
                                Write(3, eSampledImage, &infos[3]),
                                Write(4, eStorageImage, &infos[4]),
                                Write(5, eCombinedImageSampler, &infos[5])};
        Dispatch(strokes, params, writes, width, height);
    }

    void RecordLock(const Look::Params& params) {
        using enum vk::DescriptorType;
        {
            const std::array infos{Info(colour.view), Info(means.levels[0])};
            const std::array writes{Write(0, eSampledImage, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(lock_first, params, writes, width / 4, height / 4);
        }
        for (u32 n = 0; n + 1 < means.levels.size(); ++n) {
            const std::array infos{Info(means.levels[n], true), Info(means.levels[n + 1])};
            const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                    Write(1, eStorageImage, &infos[1])};
            Dispatch(lock_down, params, writes, std::max(width >> (n + 3), 1u),
                     std::max(height >> (n + 3), 1u));
        }
        const bool moving = params.flags & Look::FlagMotion;
        const std::array infos{Info(copy.view, true), Info(depth.view),
                               Info(moving ? motion.view : copy.view), Info(colour.view),
                               Info(means.view, true)};
        const std::array writes{Write(0, eCombinedImageSampler, &infos[0]),
                                Write(1, eSampledImage, &infos[1]),
                                Write(2, eSampledImage, &infos[2]),
                                Write(3, eStorageImage, &infos[3]),
                                Write(4, eCombinedImageSampler, &infos[4])};
        Dispatch(lock, params, writes, width, height);
    }

    Pass MakePass(std::initializer_list<vk::DescriptorType> types, std::span<const u32> code) {
        Pass pass;
        std::vector<vk::DescriptorSetLayoutBinding> bindings;
        for (const auto type : types) {
            bindings.push_back({.binding = u32(bindings.size()),
                                .descriptorType = type,
                                .descriptorCount = 1,
                                .stageFlags = vk::ShaderStageFlagBits::eCompute});
        }
        pass.set = Check(device->createDescriptorSetLayoutUnique(
            {.flags = vk::DescriptorSetLayoutCreateFlagBits::ePushDescriptorKHR,
             .bindingCount = u32(bindings.size()),
             .pBindings = bindings.data()}));
        const vk::PushConstantRange push{.stageFlags = vk::ShaderStageFlagBits::eCompute,
                                         .offset = 0,
                                         .size = sizeof(Look::Params)};
        pass.layout = Check(device->createPipelineLayoutUnique({.setLayoutCount = 1,
                                                                .pSetLayouts = &*pass.set,
                                                                .pushConstantRangeCount = 1,
                                                                .pPushConstantRanges = &push}));
        const auto module = Check(device->createShaderModuleUnique(
            {.codeSize = code.size_bytes(), .pCode = code.data()}));
        pass.pipeline = Check(device->createComputePipelineUnique(
            {}, vk::ComputePipelineCreateInfo{.stage = {.stage = vk::ShaderStageFlagBits::eCompute,
                                                        .module = *module,
                                                        .pName = "main"},
                                              .layout = *pass.layout}));
        return pass;
    }

    u32 MemoryType(u32 bits, vk::MemoryPropertyFlags flags) const {
        const auto properties = physical.getMemoryProperties();
        for (u32 i = 0; i < properties.memoryTypeCount; ++i) {
            if ((bits & (1u << i)) && (properties.memoryTypes[i].propertyFlags & flags) == flags) {
                return i;
            }
        }
        std::abort();
    }

    /// `all_levels`: with every level down to one texel, else the one.
    Image MakeImage(vk::Format format, vk::ImageUsageFlags usage, u32 w, u32 h, bool all_levels) {
        Image made;
        const u32 levels = all_levels ? u32(std::bit_width(std::max(w, h))) : 1;
        made.image = Check(device->createImageUnique(
            {.imageType = vk::ImageType::e2D,
             .format = format,
             .extent = {w, h, 1},
             .mipLevels = levels,
             .arrayLayers = 1,
             .samples = vk::SampleCountFlagBits::e1,
             .tiling = vk::ImageTiling::eOptimal,
             .usage = usage | vk::ImageUsageFlagBits::eSampled |
                      vk::ImageUsageFlagBits::eTransferDst}));
        const auto needs = device->getImageMemoryRequirements(*made.image);
        made.memory = Check(device->allocateMemoryUnique(
            {.allocationSize = needs.size,
             .memoryTypeIndex =
                 MemoryType(needs.memoryTypeBits, vk::MemoryPropertyFlagBits::eDeviceLocal)}));
        const auto bound = device->bindImageMemory(*made.image, *made.memory, 0);
        assert(bound == vk::Result::eSuccess);
        made.view = Check(device->createImageViewUnique({.image = *made.image,
                                                         .viewType = vk::ImageViewType::e2D,
                                                         .format = format,
                                                         .subresourceRange = Range}));
        for (u32 level = 0; level < levels; ++level) {
            made.levels.push_back(Check(device->createImageViewUnique(
                {.image = *made.image,
                 .viewType = vk::ImageViewType::e2D,
                 .format = format,
                 .subresourceRange = {vk::ImageAspectFlagBits::eColor, level, 1, 0, 1}})));
        }
        return made;
    }

    void Resize(u32 w, u32 h) {
        if (w == width && h == height) {
            return;
        }
        width = w;
        height = h;
        const auto storage = vk::ImageUsageFlagBits::eStorage;
        const auto half = vk::Format::eR16G16B16A16Sfloat;
        colour = MakeImage(half, storage | vk::ImageUsageFlagBits::eTransferSrc, w, h, false);
        copy = MakeImage(half, storage, w, h, true);
        marks = MakeImage(half, storage, w / 2, h / 2, true);
        means = MakeImage(half, storage, w / 4, h / 4, true);
        depth = MakeImage(vk::Format::eR32Sfloat, {}, w, h, false);
        normal = MakeImage(vk::Format::eR8G8B8A8Unorm, {}, w, h, false);
        motion = MakeImage(vk::Format::eR32G32B32A32Sfloat, {}, w, h, false);
        if (mapped) {
            device->unmapMemory(*staging_memory);
        }
        staging = Check(device->createBufferUnique(
            {.size = vk::DeviceSize(width) * height * 16,
             .usage = vk::BufferUsageFlagBits::eTransferSrc |
                      vk::BufferUsageFlagBits::eTransferDst}));
        const auto needs = device->getBufferMemoryRequirements(*staging);
        staging_memory = Check(device->allocateMemoryUnique(
            {.allocationSize = needs.size,
             .memoryTypeIndex =
                 MemoryType(needs.memoryTypeBits, vk::MemoryPropertyFlagBits::eHostVisible |
                                                      vk::MemoryPropertyFlagBits::eHostCoherent)}));
        const auto bound = device->bindBufferMemory(*staging, *staging_memory, 0);
        assert(bound == vk::Result::eSuccess);
        mapped = Check(device->mapMemory(*staging_memory, 0, VK_WHOLE_SIZE));
        Begin();
        std::array<vk::ImageMemoryBarrier, 7> to_general;
        const std::array<const Image*, 7> images{&colour, &copy,   &marks, &means,
                                                 &depth,  &normal, &motion};
        for (u32 i = 0; i < images.size(); ++i) {
            to_general[i] = {.dstAccessMask = vk::AccessFlagBits::eMemoryRead |
                                              vk::AccessFlagBits::eMemoryWrite,
                             .oldLayout = vk::ImageLayout::eUndefined,
                             .newLayout = vk::ImageLayout::eGeneral,
                             .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                             .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                             .image = *images[i]->image,
                             .subresourceRange = Range};
        }
        command.pipelineBarrier(vk::PipelineStageFlagBits::eTopOfPipe,
                                vk::PipelineStageFlagBits::eAllCommands, {}, {}, {}, to_general);
        Submit();
    }

    void Upload(const Image& image, const void* data, size_t bytes) {
        std::memcpy(mapped, data, bytes);
        Begin();
        const vk::BufferImageCopy region{
            .imageSubresource = {vk::ImageAspectFlagBits::eColor, 0, 0, 1},
            .imageExtent = {width, height, 1}};
        command.copyBufferToImage(*staging, *image.image, vk::ImageLayout::eGeneral, region);
        Barrier();
        Submit();
    }

    void Begin() {
        const auto begun = command.begin(vk::CommandBufferBeginInfo{});
        assert(begun == vk::Result::eSuccess);
    }

    /// Everything before is done before anything after starts.
    void Barrier() {
        const auto all = vk::AccessFlagBits::eMemoryRead | vk::AccessFlagBits::eMemoryWrite;
        const vk::MemoryBarrier barrier{.srcAccessMask = all, .dstAccessMask = all};
        command.pipelineBarrier(vk::PipelineStageFlagBits::eAllCommands,
                                vk::PipelineStageFlagBits::eAllCommands, {}, barrier, {}, {});
    }

    void Submit() {
        const auto ended = command.end();
        assert(ended == vk::Result::eSuccess);
        const auto submitted = queue.submit(
            vk::SubmitInfo{.commandBufferCount = 1, .pCommandBuffers = &command});
        assert(submitted == vk::Result::eSuccess);
        const auto idle = queue.waitIdle();
        assert(idle == vk::Result::eSuccess);
    }

    vk::UniqueInstance instance;
    vk::PhysicalDevice physical;
    vk::UniqueDevice device;
    vk::Queue queue;
    vk::UniqueCommandPool pool;
    vk::CommandBuffer command;
    vk::UniqueQueryPool queries;
    double period_ns = 1.0;
    bool timed = false;
    Pass prep, stats, mips, key_sums, key_last, strokes, lock_first, lock_down, lock;
    vk::UniqueSampler sampler;
    u32 width = 0, height = 0;
    Image colour, copy, marks, means, depth, normal, motion;
    vk::UniqueBuffer staging;
    vk::UniqueDeviceMemory staging_memory;
    void* mapped = nullptr;
};

Rgb Colour(const Half4& pixel) {
    return {FromHalf(pixel[0]), FromHalf(pixel[1]), FromHalf(pixel[2])};
}

float Luminance(const Half4& pixel) {
    const Rgb c = Colour(pixel);
    return 0.2126f * c[0] + 0.7152f * c[1] + 0.0722f * c[2];
}

bool Same(const Half4& a, const Half4& b) {
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2];
}

/// Two pixels show the same stroke: every channel within a tenth of the larger.
bool Alike(const Half4& a, const Half4& b) {
    const Rgb x = Colour(a), y = Colour(b);
    for (int c = 0; c < 3; ++c) {
        if (std::abs(x[c] - y[c]) > 0.1f * std::max(x[c], y[c]) + 1e-4f) {
            return false;
        }
    }
    return true;
}

bool failed = false;

void Expect(bool ok, const char* what) {
    std::printf("%s: %s\n", ok ? "ok" : "FAILED", what);
    failed |= !ok;
}

/// `before`, `lens_before`: the camera of the frame before and its lens (none: this frame's), or
/// no camera of the frame before.
Look::Params Words(const Lens& lens, const Camera& camera, int view, bool normals = true,
                   bool motion = false, float strength = 0.6f, float characters = 0.5f,
                   const Camera* before = nullptr, const Lens* lens_before = nullptr) {
    Look::Knobs knobs;
    knobs.strength = strength;
    knobs.characters = characters;
    knobs.view = view;
    Look::Previous previous{};
    if (before) {
        previous = {before->View(), (lens_before ? lens_before : &lens)->Proj()};
    }
    return Look::Make(knobs, camera.InvView(), lens.Proj(), lens.width, lens.height,
                      camera.jitter, normals, motion, before ? &previous : nullptr);
}

/// Where a world point lies on the camera's screen (the pixel it falls in) and how deep.
bool Project(const Lens& lens, const Camera& camera, const Vec3& world, int& x, int& y,
             double& z) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    z = Dot(rel, camera.Forward());
    if (z <= Near) {
        return false;
    }
    const double px = (Dot(rel, camera.Right()) * lens.xs / z * 0.5 + 0.5) * lens.width +
                      camera.jitter[0];
    const double py = (Dot(rel, camera.Down()) * lens.ys / z * 0.5 + 0.5) * lens.height +
                      camera.jitter[1];
    x = int(std::floor(px));
    y = int(std::floor(py));
    return x >= 0 && y >= 0 && x < int(lens.width) && y < int(lens.height);
}

struct Share {
    u32 alike = 0, of = 0;
    double Part() const {
        return of ? double(alike) / of : 0.0;
    }
};

/// As strokeOctaves of paint_common.glsl: the smaller of the two stroke sizes a point takes,
/// and the share of the larger one; a point that takes only the larger one counts as taking the
/// next size alone.
struct Sizes {
    int octave;
    double upper_share;
    bool operator==(const Sizes& other) const {
        return octave == other.octave && std::abs(upper_share - other.upper_share) < 1e-3;
    }
};

/// `normal`: the surface's; its largest part names the plane the strokes lie in (strokePlanes).
Sizes SizesAt(const Lens& lens, const Vec3& world, const std::array<u8, 4>& normal,
              const Camera& camera, double cell_px) {
    const Vec3 rel = Add(world, camera.pos, -1.0);
    const double distance = std::sqrt(Dot(rel, rel));
    int plane = 0;
    for (int k = 1; k < 3; ++k) {
        if (std::abs(int(normal[k]) - 128) > std::abs(int(normal[plane]) - 128)) {
            plane = k;
        }
    }
    const double lean = std::max(std::abs(rel[plane]) / distance, 0.04);
    const double level =
        std::log2(cell_px / std::sqrt(lean) * 2.0 * distance / (lens.ys * lens.height));
    const double part = std::clamp((level - std::floor(level) - 0.25) / 0.5, 0.0, 1.0);
    const double share = part * part * (3.0 - 2.0 * part);
    return share >= 1.0 ? Sizes{int(std::floor(level)) + 1, 0.0}
                        : Sizes{int(std::floor(level)), share};
}

struct Shares {
    Share all;   ///< every pixel a stroke painted
    Share inner; ///< those with the same stroke on all eight pixels around them
    std::array<Share, 6> inner_of{}; ///< `inner` by Surface
};

/// Of the pixels of `a` that a stroke painted and that `b` sees too (the same surface at the
/// same depth), the share that shows the same stroke in `b` where the point lies there
/// (`follow`), or at the same place of the screen (not `follow`: what strokes stuck to the
/// screen would give). A point of `a` falls between the pixels of `b`, so at a stroke's edge
/// the nearest pixel of `b` may show the stroke beside it: the pixels inside a stroke tell
/// whether the strokes moved with their surfaces. A point the camera came nearer to, or went
/// away from, far enough to mix its two sizes of stroke otherwise is left out: there the look
/// crosses over from one size to the next, which is meant. `cell_px`: the frames' stroke cell.
Shares Compare(const Lens& lens, const Scene& a, const std::vector<Half4>& out_a,
               const Camera& camera_a, const Camera& camera_b, const Scene& b,
               const std::vector<Half4>& out_b, double cell_px, bool follow) {
    Shares shares;
    for (u32 y = 1; y + 1 < lens.height; ++y) {
        for (u32 x = 1; x + 1 < lens.width; ++x) {
            const u32 i = y * lens.width + x;
            if (a.surface[i] == Sky || Same(out_a[i], a.colour[i])) {
                continue;
            }
            int bx = int(x), by = int(y);
            double z = 0.0;
            if (follow && !Project(lens, camera_b, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * lens.width + u32(bx);
            if (b.surface[j] != a.surface[i]) {
                continue;
            }
            if (follow && std::abs(Near / (1.0 - double(b.depth[j])) - z) > 0.02 * z) {
                continue;
            }
            if (SizesAt(lens, a.world[i], a.normal[i], camera_a, cell_px) !=
                SizesAt(lens, a.world[i], a.normal[i], camera_b, cell_px)) {
                continue;
            }
            bool inner = true;
            for (int k = 0; k < 9; ++k) {
                inner &= Alike(out_a[i], out_a[i + (k / 3 - 1) * int(lens.width) + k % 3 - 1]);
            }
            const bool alike = Alike(out_a[i], out_b[j]);
            ++shares.all.of;
            shares.all.alike += alike;
            shares.inner.of += inner;
            shares.inner.alike += inner && alike;
            shares.inner_of[a.surface[i]].of += inner;
            shares.inner_of[a.surface[i]].alike += inner && alike;
        }
    }
    return shares;
}

/// How two lists of numbers go together, -1..1.
struct Together {
    double sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    u32 n = 0;
    void Add(double x, double y) {
        sx += x, sy += y, sxx += x * x, syy += y * y, sxy += x * y;
        ++n;
    }
    double Value() const {
        const double vx = sxx - sx * sx / n, vy = syy - sy * sy / n;
        return vx > 0 && vy > 0 ? (sxy - sx * sy / n) / std::sqrt(vx * vy) : 0.0;
    }
};

/// What the look did to a pixel's brightness, as a ratio less 1.
double Change(const Scene& scene, const std::vector<Half4>& out, u32 i) {
    return double(Luminance(out[i])) / std::max(double(Luminance(scene.colour[i])), 1e-9) - 1.0;
}

/// Whether what the look changed in frame `a` is found again in frame `b`: where each point of
/// `a` lies in `b` (`follow`), and at the same place of the screen (`stuck`). Strokes that stay
/// on their surfaces give a high first number and a low second one. Without the ball: it gets no
/// strokes.
void LookTogether(const Lens& lens, const Scene& a, const std::vector<Half4>& out_a,
                  const Camera& camera_b, const Scene& b, const std::vector<Half4>& out_b,
                  Together& follow, Together& stuck) {
    for (u32 y = 0; y < lens.height; ++y) {
        for (u32 x = 0; x < lens.width; ++x) {
            const u32 i = y * lens.width + x;
            if (a.surface[i] == Sky || a.surface[i] == Ball) {
                continue;
            }
            int bx = 0, by = 0;
            double z = 0.0;
            if (!Project(lens, camera_b, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * lens.width + u32(bx);
            if (b.surface[j] != a.surface[i] || b.surface[i] != a.surface[i] ||
                std::abs(Near / (1.0 - double(b.depth[j])) - z) > 0.02 * z) {
                continue;
            }
            const double change = Change(a, out_a, i);
            follow.Add(change, Change(b, out_b, j));
            stuck.Add(change, Change(b, out_b, i));
        }
    }
}

u8 Display(float linear) {
    return u8(std::lround(std::pow(std::clamp(linear * 1.6f, 0.0f, 1.0f), 1.0f / 2.2f) * 255.0f));
}

/// Rows of 24-bit pixels (blue, green, red), top row first, as a BMP.
bool WriteBmp(const std::string& path, u32 width, u32 height, const std::vector<u8>& rows) {
    const u32 stride = (width * 3 + 3) & ~3u;
    u8 header[54] = {'B', 'M'};
    const auto put = [&](int at, u32 value) { std::memcpy(header + at, &value, 4); };
    put(2, u32(sizeof(header)) + stride * height);
    put(10, sizeof(header));
    put(14, 40);
    put(18, width);
    put(22, height);
    put(26, 1 | 24 << 16);
    put(34, stride * height);
    std::ofstream file(path, std::ios::binary);
    file.write(reinterpret_cast<const char*>(header), sizeof(header));
    std::vector<u8> line(stride);
    for (u32 y = height; y-- > 0;) {
        std::memcpy(line.data(), &rows[size_t(y) * width * 3], size_t(width) * 3);
        file.write(reinterpret_cast<const char*>(line.data()), stride);
    }
    return file.good();
}

/// Four pictures of one size as one BMP, two beside two.
void WritePicture(const char* path, u32 w, u32 h,
                  const std::array<const std::vector<Half4>*, 4>& parts) {
    const u32 width = w * 2, height = h * 2;
    std::vector<u8> rows(size_t(width) * height * 3);
    for (u32 y = 0; y < height; ++y) {
        for (u32 x = 0; x < width; ++x) {
            const auto& part = *parts[(y / h) * 2 + x / w];
            const Rgb c = Colour(part[(y % h) * w + x % w]);
            u8* out = &rows[(size_t(y) * width + x) * 3];
            out[0] = Display(c[2]);
            out[1] = Display(c[1]);
            out[2] = Display(c[0]);
        }
    }
    Expect(WriteBmp(path, width, height, rows), "the picture is written");
}

// --- the look on a picture ---

float FromSrgb(u8 value) {
    const float v = value / 255.0f;
    return v <= 0.04045f ? v / 12.92f : std::pow((v + 0.055f) / 1.055f, 2.4f);
}

u8 ToSrgb(float linear) {
    const float v = std::clamp(linear, 0.0f, 1.0f);
    return u8(std::lround((v <= 0.0031308f ? v * 12.92f : 1.055f * std::pow(v, 1 / 2.4f) - 0.055f) *
                          255.0f));
}

/// Linear sRGB as Oklab (L, a, b).
std::array<double, 3> Oklab(const Rgb& c) {
    const double l = std::cbrt(0.4122214708 * c[0] + 0.5363325363 * c[1] + 0.0514459929 * c[2]);
    const double m = std::cbrt(0.2119034982 * c[0] + 0.6806995451 * c[1] + 0.1073969566 * c[2]);
    const double s = std::cbrt(0.0883024619 * c[0] + 0.2817188376 * c[1] + 0.6299787005 * c[2]);
    return {0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s};
}

/// A 24-bit BMP's pixels as linear colours, top row first; empty if it is not one.
std::vector<Rgb> ReadBmp(const char* path, u32& width, u32& height) {
    std::ifstream file(path, std::ios::binary);
    u8 header[54];
    file.read(reinterpret_cast<char*>(header), sizeof(header));
    u32 offset, w, h;
    u16 bits;
    std::memcpy(&offset, header + 10, 4);
    std::memcpy(&w, header + 18, 4);
    std::memcpy(&h, header + 22, 4);
    std::memcpy(&bits, header + 28, 2);
    if (!file.good() || header[0] != 'B' || header[1] != 'M' || bits != 24 || int(h) <= 0) {
        return {};
    }
    width = w;
    height = h;
    const u32 stride = (w * 3 + 3) & ~3u;
    std::vector<u8> line(stride);
    std::vector<Rgb> pixels(size_t(w) * h);
    file.seekg(offset);
    for (u32 y = h; y-- > 0;) {
        file.read(reinterpret_cast<char*>(line.data()), stride);
        for (u32 x = 0; x < w; ++x) {
            pixels[size_t(y) * w + x] = {FromSrgb(line[x * 3 + 2]), FromSrgb(line[x * 3 + 1]),
                                         FromSrgb(line[x * 3])};
        }
    }
    return file.good() ? pixels : std::vector<Rgb>{};
}

/// The picture as a scene: a camera 1.6 m above a floor looks a little down at a wall 9 m
/// away, and the picture lies on both. `exposure`: the scene is that much brighter than the
/// picture, as a game's scene before its exposure is some factor away from what is shown.
/// The parts of the picture that the game draws after the strokes (the HUD: `hud`, rectangles
/// in shares of the picture) count as sky, which is not painted.
Scene PictureScene(const Lens& lens, const Camera& camera, const std::vector<Rgb>& picture,
                   float exposure, std::span<const std::array<float, 4>> hud) {
    const u32 w = lens.width, h = lens.height;
    Scene scene{w, h};
    const Vec3 r = camera.Right(), dn = camera.Down(), f = camera.Forward();
    for (u32 y = 0; y < h; ++y) {
        for (u32 x = 0; x < w; ++x) {
            const u32 i = y * w + x;
            const double nx = (x + 0.5) / w * 2.0 - 1.0, ny = (y + 0.5) / h * 2.0 - 1.0;
            const Vec3 dir = Add(Add(f, r, nx / lens.xs), dn, ny / lens.ys);
            const double wall = (9.0 - camera.pos[2]) / dir[2];
            const double floor = dir[1] < 0.0 ? -camera.pos[1] / dir[1] : 1e30;
            const bool on_floor = floor < wall;
            bool in_hud = false;
            for (const auto& box : hud) {
                in_hud |= (x + 0.5f) / w >= box[0] && (x + 0.5f) / w < box[2] &&
                          (y + 0.5f) / h >= box[1] && (y + 0.5f) / h < box[3];
            }
            const Rgb& c = picture[i];
            scene.colour[i] = {ToHalf(c[0] * exposure), ToHalf(c[1] * exposure),
                               ToHalf(c[2] * exposure), ToHalf(1.0f)};
            scene.depth[i] = in_hud ? 1.0f : float(1.0 - Near / std::min(floor, wall));
            scene.normal[i] = on_floor ? std::array<u8, 4>{128, 255, 128, 255}
                                       : std::array<u8, 4>{128, 128, 0, 255};
        }
    }
    return scene;
}

/// Each 2x2 pixels of a picture as one, the mean of the linear colours.
std::vector<Rgb> Halved(const std::vector<Rgb>& picture, u32 width, u32 height) {
    std::vector<Rgb> half(size_t(width / 2) * (height / 2));
    for (u32 y = 0; y < height / 2; ++y) {
        for (u32 x = 0; x < width / 2; ++x) {
            Rgb sum{};
            for (int k = 0; k < 4; ++k) {
                const Rgb& c = picture[size_t(y * 2 + k / 2) * width + x * 2 + k % 2];
                for (int ch = 0; ch < 3; ++ch) {
                    sum[ch] += c[ch] * 0.25f;
                }
            }
            half[size_t(y) * (width / 2) + x] = sum;
        }
    }
    return half;
}

/// A picture at another height (the width goes with it): every new pixel the mean of the part
/// of the picture it covers.
std::vector<Rgb> Resized(const std::vector<Rgb>& picture, u32 width, u32 height, u32 new_width,
                         u32 new_height) {
    std::vector<Rgb> out(size_t(new_width) * new_height);
    const double sx = double(width) / new_width, sy = double(height) / new_height;
    for (u32 y = 0; y < new_height; ++y) {
        for (u32 x = 0; x < new_width; ++x) {
            const double x0 = x * sx, x1 = (x + 1) * sx, y0 = y * sy, y1 = (y + 1) * sy;
            std::array<double, 3> sum{};
            double weight = 0.0;
            for (u32 v = u32(y0); v < std::min(u32(std::ceil(y1)), height); ++v) {
                const double wy = std::min(y1, v + 1.0) - std::max(y0, double(v));
                for (u32 u = u32(x0); u < std::min(u32(std::ceil(x1)), width); ++u) {
                    const double w = wy * (std::min(x1, u + 1.0) - std::max(x0, double(u)));
                    const Rgb& c = picture[size_t(v) * width + u];
                    for (int ch = 0; ch < 3; ++ch) {
                        sum[ch] += c[ch] * w;
                    }
                    weight += w;
                }
            }
            out[size_t(y) * new_width + x] = {float(sum[0] / weight), float(sum[1] / weight),
                                              float(sum[2] / weight)};
        }
    }
    return out;
}

bool WriteScene(const std::string& path, const Lens& lens, const std::vector<Half4>& pixels,
                float exposure) {
    std::vector<u8> rows(size_t(lens.width) * lens.height * 3);
    for (size_t i = 0; i < pixels.size(); ++i) {
        const Rgb c = Colour(pixels[i]);
        rows[i * 3 + 0] = ToSrgb(c[2] / exposure);
        rows[i * 3 + 1] = ToSrgb(c[1] / exposure);
        rows[i * 3 + 2] = ToSrgb(c[0] / exposure);
    }
    return WriteBmp(path, lens.width, lens.height, rows);
}

/// What the look did to the picture's colours: the whole frame's mean, and every block of
/// `block` pixels (64 at 2160 lines, the design's check) that is not near black.
void ReportColours(const char* name, const Lens& lens, const Scene& scene,
                   const std::vector<Half4>& out, float exposure) {
    const u32 block = std::max(lens.height * 64 / 2160, 8u);
    std::array<double, 3> before{}, after{}, lab_before{}, lab_after{};
    u32 changed = 0, painted = 0;
    std::vector<double> light, lightness;
    double frame_luminance = 0.0;
    for (const Half4& pixel : scene.colour) {
        frame_luminance += Luminance(pixel) / exposure;
    }
    frame_luminance /= double(scene.colour.size());
    for (u32 by = 0; by + block <= lens.height; by += block) {
        for (u32 bx = 0; bx + block <= lens.width; bx += block) {
            std::array<double, 3> a{}, b{};
            double la = 0.0, lb = 0.0;
            for (u32 y = by; y < by + block; ++y) {
                for (u32 x = bx; x < bx + block; ++x) {
                    const u32 i = y * lens.width + x;
                    Rgb ca = Colour(scene.colour[i]), cb = Colour(out[i]);
                    for (int ch = 0; ch < 3; ++ch) {
                        ca[ch] /= exposure;
                        cb[ch] /= exposure;
                        a[ch] += ca[ch];
                        b[ch] += cb[ch];
                    }
                    const auto oa = Oklab(ca), ob = Oklab(cb);
                    la += oa[0];
                    lb += ob[0];
                    for (int ch = 0; ch < 3; ++ch) {
                        lab_before[ch] += oa[ch];
                        lab_after[ch] += ob[ch];
                    }
                    painted += scene.depth[i] < 1.0f;
                    changed += std::abs(Luminance(out[i]) - Luminance(scene.colour[i])) >
                               0.01f * Luminance(scene.colour[i]);
                }
            }
            for (int ch = 0; ch < 3; ++ch) {
                before[ch] += a[ch];
                after[ch] += b[ch];
            }
            const double n = double(block) * block;
            const double ya = (0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]) / n;
            const double yb = (0.2126 * b[0] + 0.7152 * b[1] + 0.0722 * b[2]) / n;
            // A block darker than a tenth of the frame's mean: a change there is a large
            // share of nearly nothing.
            if (ya > 0.1 * frame_luminance) {
                light.push_back(std::abs(yb / ya - 1.0) * 100.0);
                lightness.push_back(std::abs(lb / la - 1.0) * 100.0);
            }
        }
    }
    const auto spread = [](std::vector<double>& values, double& mean, double& p95, double& top) {
        std::sort(values.begin(), values.end());
        mean = 0.0;
        for (const double v : values) {
            mean += v;
        }
        mean /= double(values.size());
        p95 = values[values.size() * 95 / 100];
        top = values.back();
    };
    double m1, p1, t1, m2, p2, t2;
    spread(light, m1, p1, t1);
    spread(lightness, m2, p2, t2);
    const double all = double(scene.colour.size());
    std::printf("%s: frame mean linear R %+.2f%% G %+.2f%% B %+.2f%%; mean Oklab L %+.4f a "
                "%+.4f b %+.4f; %.1f%% of the %u painted pixels changed by more than 1%%\n",
                name, (after[0] / before[0] - 1.0) * 100.0, (after[1] / before[1] - 1.0) * 100.0,
                (after[2] / before[2] - 1.0) * 100.0, (lab_after[0] - lab_before[0]) / all,
                (lab_after[1] - lab_before[1]) / all, (lab_after[2] - lab_before[2]) / all,
                100.0 * changed / std::max(painted, 1u), painted);
    std::printf("%s: %zu blocks of %ux%u (those under a tenth of the frame's mean brightness "
                "left out): mean luminance changed by mean %.2f%% p95 %.2f%% max %.2f%%; mean "
                "Oklab L by mean %.2f%% p95 %.2f%% max %.2f%%\n",
                name, light.size(), block, block, m1, p1, t1, m2, p2, t2);
}

int PictureMain(int argc, char** argv) {
    u32 width = 0, height = 0;
    std::vector<Rgb> picture = ReadBmp(argv[2], width, height);
    if (picture.empty() || argc < 4) {
        std::puts("usage: drawn-look-test --picture in.bmp out [2 | lines]   (in.bmp: 24 bits a "
                  "pixel; 2: at half the size; lines: at that height, 1440 for one)");
        return 2;
    }
    if (argc > 4 && std::strcmp(argv[4], "2") == 0) {
        picture = Halved(picture, width, height);
        width /= 2;
        height /= 2;
    } else if (argc > 4 && std::atoi(argv[4]) >= 64) {
        const u32 new_height = u32(std::atoi(argv[4]));
        const u32 new_width = u32(std::lround(double(width) * new_height / height / 2.0)) * 2;
        picture = Resized(picture, width, height, new_width, new_height);
        width = new_width;
        height = new_height;
    }
    const std::string out = argv[3];
    Gpu gpu;
    const Lens lens{width, height};
    const Camera camera{.pos = {0.0, 1.6, 0.0}, .pitch = -0.035};
    // The game's HUD in the design's screenshot, as shares of the picture.
    static constexpr std::array<float, 4> Hud[] = {{0.052f, 0.050f, 0.232f, 0.208f},
                                                   {0.820f, 0.055f, 0.955f, 0.155f},
                                                   {0.872f, 0.012f, 0.995f, 0.034f}};
    const float exposure = 4.0f;
    const Scene scene = PictureScene(lens, camera, picture, exposure, Hud);
    const auto words = [&](float strength, int view) {
        return Words(lens, camera, view, true, false, strength);
    };
    std::printf("picture %ux%u, stroke cells %.1f and %.1f pixels\n", width, height,
                words(0.6f, 0).cell_bold, words(0.6f, 0).cell_fine);
    const auto after = gpu.Run(scene, words(0.6f, Look::ViewOff));
    const auto full = gpu.Run(scene, words(1.0f, Look::ViewOff));
    const auto sizes = gpu.Run(scene, words(0.6f, Look::ViewStrokes));
    ReportColours("strength 0.6", lens, scene, after, exposure);
    ReportColours("strength 1.0", lens, scene, full, exposure);
    for (const float times : {16.0f, 1.5f}) {
        // The same picture brighter, by a whole number of stops and by a part of one: the same
        // look.
        const Scene bright = PictureScene(lens, camera, picture, exposure * times, Hud);
        const auto again = gpu.Run(bright, words(0.6f, Look::ViewOff));
        u32 off = 0;
        for (size_t i = 0; i < after.size(); ++i) {
            off += std::abs(Luminance(again[i]) / times - Luminance(after[i])) >
                   0.02f * Luminance(after[i]) + 1e-4f;
        }
        std::printf("%.1f times as bright: %u of %zu pixels differ by more than 2%% from the "
                    "look on the picture as it is\n", times, off, after.size());
    }
    if (gpu.Timed()) {
        const u32 repeats = width * height > 3000000 ? 50 : 150;
        const Times look = gpu.Measure(scene, words(0.6f, Look::ViewOff), repeats);
        const Times full_look = gpu.Measure(scene, words(1.0f, Look::ViewOff), repeats);
        const Times test_view = gpu.Measure(scene, words(0.6f, Look::ViewBold), repeats);
        std::printf("GPU time at %ux%u (each part %u times in a row, best of 3): copy, marks "
                    "and levels %.3f ms, strokes %.3f ms (at strength 1: %.3f ms; the test "
                    "view's: %.3f ms), colour lock %.3f ms; the look together %.3f ms\n",
                    width, height, repeats, look.masks, look.strokes, full_look.strokes,
                    test_view.strokes, look.lock, look.masks + look.strokes + look.lock);
    }
    const bool written = WriteScene(out + "_before.bmp", lens, scene.colour, exposure) &&
                         WriteScene(out + "_after.bmp", lens, after, exposure) &&
                         WriteScene(out + "_full.bmp", lens, full, exposure) &&
                         WriteScene(out + "_sizes.bmp", lens, sizes, exposure);
    std::puts(written ? "pictures written" : "FAILED to write the pictures");
    return written ? 0 : 1;
}
} // namespace

int main(int argc, char** argv) {
    if (argc > 2 && std::strcmp(argv[1], "--picture") == 0) {
        return PictureMain(argc, argv);
    }
    Gpu gpu;
    const Lens lens{960, 540};
    const u32 n = lens.width * lens.height;
    // Looks straight at the back wall, ten metres away: every pixel of that wall is as deep.
    const Camera straight{.pos = {0.3, 1.6, -1.0}};
    const Scene scene = MakeScene(lens, straight, Paint::Plain);
    const auto bold = gpu.Run(scene, Words(lens, straight, Look::ViewBold));

    for (const int view : {int(Look::ViewOff), int(Look::ViewStrokes), int(Look::ViewFine),
                           int(Look::ViewBold)}) {
        const auto out = gpu.Run(scene, Words(lens, straight, view));
        u32 sky = 0, sky_changed = 0, alpha_changed = 0, surface = 0, painted = 0;
        for (u32 i = 0; i < n; ++i) {
            alpha_changed += out[i][3] != scene.colour[i][3];
            if (scene.surface[i] == Sky) {
                ++sky;
                sky_changed += !Same(out[i], scene.colour[i]);
            } else {
                ++surface;
                painted += !Same(out[i], scene.colour[i]);
            }
        }
        std::printf("%s %d: %u sky pixels, %u changed; %u alphas changed; %.1f%% of the %u "
                    "surface pixels changed\n",
                    view ? "test view" : "the look, view", view, sky, sky_changed, alpha_changed,
                    100.0 * painted / surface, surface);
        Expect(sky > n / 20 && sky_changed == 0, "the sky is not painted");
        Expect(alpha_changed == 0, "the alpha is kept");
        Expect(painted > surface * 0.6, "strokes cover most of the surfaces");
        if (view == Look::ViewOff) {
            // The view kept for the ink lines shows the look, as no view does.
            Expect(gpu.Run(scene, Words(lens, straight, Look::ViewInk)) == out,
                   "view 3 (kept for the ink lines) shows the look");
        }
    }
    {
        // The jitter moved by whole pixels: the same picture, moved by as much.
        Camera moved = straight;
        moved.jitter = {3.0f, -2.0f};
        const Scene scene_b = MakeScene(lens, moved, Paint::Plain);
        const auto out = gpu.Run(scene_b, Words(lens, moved, Look::ViewBold));
        u32 compared = 0, same = 0;
        for (u32 y = 2; y < lens.height; ++y) {
            for (u32 x = 0; x + 3 < lens.width; ++x) {
                const u32 i = y * lens.width + x, j = (y - 2) * lens.width + x + 3;
                if (scene.surface[i] != Sky && scene.surface[j] == scene.surface[i]) {
                    ++compared;
                    same += Alike(bold[i], out[j]);
                }
            }
        }
        std::printf("jitter (3, -2): %u of %u pixels show the same stroke 3 right and 2 up "
                    "(%.3f%%)\n", same, compared, 100.0 * same / compared);
        Expect(same > compared * 0.995, "a jitter of whole pixels moves the strokes with the scene");
    }
    {
        // The camera steps sideways, then up, by what moves the back wall a whole number of
        // pixels: the wall's strokes must move with the wall, pixel for pixel.
        const double z = 9.0 - straight.pos[2];
        const double cell_px = Words(lens, straight, Look::ViewBold).cell_bold;
        for (int axis = 0; axis < 2; ++axis) {
            const int pixels = axis == 0 ? 16 : 9;
            Camera moved = straight;
            moved.pos[axis] += axis == 0 ? pixels * 2.0 * z / (lens.xs * lens.width)
                                         : pixels * 2.0 * z / (lens.ys * lens.height);
            const Scene scene_b = MakeScene(lens, moved, Paint::Plain);
            const auto out = gpu.Run(scene_b, Words(lens, moved, Look::ViewBold));
            u32 compared = 0, same = 0, stuck = 0;
            for (u32 y = 0; y + (axis == 1 ? pixels : 0) < lens.height; ++y) {
                for (u32 x = axis == 0 ? pixels : 0; x < lens.width; ++x) {
                    const u32 i = y * lens.width + x;
                    const u32 j = axis == 0 ? i - pixels : i + pixels * lens.width;
                    // A point whose two sizes of stroke mix otherwise from the moved camera
                    // (the wall is seen a little less squarely from there) is left out.
                    if (scene.surface[i] == BackWall && scene_b.surface[j] == BackWall &&
                        scene_b.surface[i] == BackWall && !Same(bold[i], scene.colour[i]) &&
                        SizesAt(lens, scene.world[i], scene.normal[i], straight, cell_px) ==
                            SizesAt(lens, scene.world[i], scene.normal[i], moved, cell_px)) {
                        ++compared;
                        same += Alike(bold[i], out[j]);
                        stuck += Alike(bold[i], out[i]);
                    }
                }
            }
            std::printf("camera %.4f m %s: the back wall moved %d pixels; of %u painted pixels "
                        "%.3f%% show the same stroke there, %.1f%% at the same place of the "
                        "screen\n",
                        std::abs(moved.pos[axis] - straight.pos[axis]),
                        axis == 0 ? "to the right" : "up", pixels, compared,
                        100.0 * same / compared, 100.0 * stuck / compared);
            Expect(compared > 20000 && same > compared * 0.995 && stuck < compared * 0.3,
                   "the wall's strokes move with the wall");
        }
    }
    {
        // The normal from the depth (a frame painted right before the upscaler) picks the
        // same strokes on flat surfaces as the G-buffer's normal.
        const auto out = gpu.Run(scene, Words(lens, straight, Look::ViewBold, false));
        u32 compared = 0, same = 0;
        for (u32 i = 0; i < n; ++i) {
            if (scene.surface[i] == Floor || scene.surface[i] == BackWall ||
                scene.surface[i] == SideWall) {
                ++compared;
                same += Alike(bold[i], out[i]);
            }
        }
        std::printf("normals from the depth: %.2f%% of %u flat pixels as with the G-buffer's\n",
                    100.0 * same / compared, compared);
        Expect(same > compared * 0.97, "the depth's normal gives the same strokes on flat surfaces");
    }
    {
        // What moves by itself is marked: its strokes are grey in the test view. (A pixel
        // that one of its planes has no stroke for keeps a part of the ball's own colour.)
        const auto out = gpu.Run(scene, Words(lens, straight, Look::ViewBold, true, true));
        const auto colourful = [](const Half4& pixel) {
            const Rgb c = Colour(pixel);
            return std::max({c[0], c[1], c[2]}) - std::min({c[0], c[1], c[2]});
        };
        u32 ball = 0, grey = 0, grey_before = 0, tinted = 0, elsewhere = 0;
        for (u32 i = 0; i < n; ++i) {
            if (scene.surface[i] != Ball) {
                elsewhere += !Same(out[i], bold[i]);
            } else if (!Same(out[i], scene.colour[i])) {
                ++ball;
                grey += out[i][0] == out[i][1] && out[i][1] == out[i][2];
                grey_before += bold[i][0] == bold[i][1] && bold[i][1] == bold[i][2];
                tinted += colourful(out[i]) > colourful(scene.colour[i]) + 1e-3f;
            }
        }
        std::printf("object motion: %u painted pixels on the ball, %u grey (%u without the "
                    "motion image), %u more colourful than the ball; %u pixels changed "
                    "elsewhere\n", ball, grey, grey_before, tinted, elsewhere);
        Expect(ball > 1000 && grey > ball * 0.9 && tinted == 0 && grey_before < ball / 10 &&
                   elsewhere == 0,
               "surfaces that move by themselves are told apart");
    }
    // A camera that turns and tilts, then one that walks too, with jitters under a pixel: no
    // pixel falls on a pixel, so strokes are compared where each point of the first frame lies
    // in the second. Turning changes nothing about a point's strokes. A walking camera comes
    // nearer to some points: where that changes how a point mixes its two sizes of stroke
    // the point is not compared.
    const Lens large{1920, 1080};
    const Camera first{.pos = {0.3, 1.6, -1.0}, .yaw = 0.10, .pitch = -0.06, .jitter = {0.21f, -0.37f}};
    const Camera turned{.pos = first.pos, .yaw = 0.02, .pitch = -0.10, .jitter = {-0.42f, 0.13f}};
    const Camera walked{.pos = {0.75, 1.68, -0.55}, .yaw = 0.02, .pitch = -0.10,
                        .jitter = {-0.42f, 0.13f}};
    for (const int view : {int(Look::ViewBold), int(Look::ViewFine)}) {
        const Scene a = MakeScene(large, first, Paint::Plain);
        const auto words = Words(large, first, view);
        const double cell_px = view == Look::ViewFine ? words.cell_fine : words.cell_bold;
        const auto out_a = gpu.Run(a, words);
        for (const Camera* second : {&turned, &walked}) {
            const Scene b = MakeScene(large, *second, Paint::Plain);
            const auto out_b = gpu.Run(b, Words(large, *second, view));
            const Shares follow = Compare(large, a, out_a, first, *second, b, out_b, cell_px, true);
            const Shares stuck = Compare(large, a, out_a, first, *second, b, out_b, cell_px, false);
            const bool walks = second == &walked;
            std::printf("camera turned%s, test view %d at 1920x1080: where the point lies in "
                        "the second frame %.1f%% of %u pixels inside a stroke show the same "
                        "stroke (%.1f%% of all %u painted pixels); at the same place of the "
                        "screen %.1f%% (%.1f%%)\n",
                        walks ? " and walked" : "", view, 100.0 * follow.inner.Part(),
                        follow.inner.of, 100.0 * follow.all.Part(), follow.all.of,
                        100.0 * stuck.inner.Part(), 100.0 * stuck.all.Part());
            std::printf("  inside a stroke, by surface: floor %.1f%% of %u, back wall %.1f%% of "
                        "%u, side wall %.1f%% of %u, column %.1f%% of %u, ball %.1f%% of %u\n",
                        100.0 * follow.inner_of[Floor].Part(), follow.inner_of[Floor].of,
                        100.0 * follow.inner_of[BackWall].Part(), follow.inner_of[BackWall].of,
                        100.0 * follow.inner_of[SideWall].Part(), follow.inner_of[SideWall].of,
                        100.0 * follow.inner_of[Column].Part(), follow.inner_of[Column].of,
                        100.0 * follow.inner_of[Ball].Part(), follow.inner_of[Ball].of);
            Expect(follow.inner.of > 20000 && follow.inner.Part() > 0.99 &&
                       stuck.inner.Part() < 0.1,
                   "the strokes stay on their surfaces while the camera moves");
        }
    }
    {
        // Another render size (another upscaler mode): the strokes keep their share of the
        // picture, so a pixel of the small frame shows the stroke of the large frame's pixel
        // at the same place.
        const Scene big = MakeScene(large, straight, Paint::Plain);
        const auto out = gpu.Run(big, Words(large, straight, Look::ViewBold));
        u32 compared = 0, same = 0;
        for (u32 y = 0; y < lens.height; ++y) {
            for (u32 x = 0; x < lens.width; ++x) {
                const u32 i = y * lens.width + x, j = y * 2 * large.width + x * 2;
                if (scene.surface[i] != Sky && big.surface[j] == scene.surface[i] &&
                    !Same(bold[i], scene.colour[i])) {
                    ++compared;
                    same += Alike(bold[i], out[j]);
                }
            }
        }
        std::printf("960x540 against 1920x1080: %.1f%% of %u painted pixels show the same "
                    "stroke\n", 100.0 * same / compared, compared);
        Expect(same > compared * 0.7, "the strokes are the same at another render size");
    }

    // --- the look itself (no test view), on the lit scene with grit ---
    const Scene grit = MakeScene(large, first, Paint::Grit);
    const u32 pixels = large.width * large.height;
    for (const float strength : {0.6f, 1.0f}) {
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff, true, false, strength));
        // Every surface keeps its mean colour; the grit between neighbouring pixels of a
        // surface (how far their brightness is apart, in stops) gets less.
        std::array<std::array<double, 3>, 6> before{}, after{};
        std::array<double, 6> rough_before{}, rough_after{};
        std::array<u32, 6> count{}, pairs{};
        u32 unchanged_sky = 0, sky = 0, alpha_changed = 0;
        for (u32 i = 0; i < pixels; ++i) {
            const Surface s = grit.surface[i];
            alpha_changed += out[i][3] != grit.colour[i][3];
            if (s == Sky) {
                ++sky;
                unchanged_sky += Same(out[i], grit.colour[i]);
                continue;
            }
            const Rgb a = Colour(grit.colour[i]), b = Colour(out[i]);
            for (int ch = 0; ch < 3; ++ch) {
                before[s][ch] += a[ch];
                after[s][ch] += b[ch];
            }
            ++count[s];
            if (i % large.width + 1 < large.width && grit.surface[i + 1] == s) {
                rough_before[s] += std::abs(std::log2(Luminance(grit.colour[i]) /
                                                      Luminance(grit.colour[i + 1])));
                rough_after[s] += std::abs(std::log2(Luminance(out[i]) / Luminance(out[i + 1])));
                ++pairs[s];
            }
        }
        double worst = 0.0, least_calmed = 1.0;
        static constexpr const char* Names[] = {"sky", "floor", "back wall", "side wall", "column",
                                                "ball"};
        std::printf("the look at strength %.1f on the lit scene with grit, 1920x1080:\n", strength);
        for (int s = Floor; s <= Ball; ++s) {
            double off = 0.0;
            for (int ch = 0; ch < 3; ++ch) {
                off = std::max(off, std::abs(after[s][ch] / before[s][ch] - 1.0));
            }
            worst = std::max(worst, off);
            const double calmed = rough_after[s] / rough_before[s];
            least_calmed = std::min(least_calmed, 1.0 - calmed);
            std::printf("  %s: %u pixels, mean colour R %+.2f%% G %+.2f%% B %+.2f%%; grit "
                        "between neighbours %.3f -> %.3f stops (%.0f%% less)\n",
                        Names[s], count[s], (after[s][0] / before[s][0] - 1.0) * 100.0,
                        (after[s][1] / before[s][1] - 1.0) * 100.0,
                        (after[s][2] / before[s][2] - 1.0) * 100.0, rough_before[s] / pairs[s],
                        rough_after[s] / pairs[s], (1.0 - calmed) * 100.0);
        }
        Expect(worst < 0.01, "every surface keeps its mean colour within 1%");
        Expect(least_calmed > 0.25 * strength, "the grit is flattened on every surface");
        Expect(sky > 0 && unchanged_sky == sky && alpha_changed == 0,
               "the look leaves the sky and the alpha alone");
    }
    {
        // What the look changes stays on the surfaces while the camera turns and walks. On
        // the scene without grit: a speck of grit is smaller than a pixel far away, the two
        // frames see other specks in a pixel, and what the look takes away would differ by that.
        const auto words = [&](const Camera& camera) {
            return Words(large, camera, Look::ViewOff, true, false, 1.0f);
        };
        const Scene lit = MakeScene(large, first, Paint::Lit);
        const auto out_a = gpu.Run(lit, words(first));
        for (const Camera* second : {&turned, &walked}) {
            const Scene b = MakeScene(large, *second, Paint::Lit);
            const auto out_b = gpu.Run(b, words(*second));
            Together follow, stuck;
            LookTogether(large, lit, out_a, *second, b, out_b, follow, stuck);
            std::printf("the look, camera turned%s: what it changed in a pixel's brightness "
                        "goes together with the change where the point lies in the second "
                        "frame by %.3f, with the change at the same place of the screen by "
                        "%.3f (%u points; 1: the same, 0: unrelated)\n",
                        second == &walked ? " and walked" : "", follow.Value(), stuck.Value(),
                        follow.n);
            Expect(follow.n > 200000 && follow.Value() > 0.8 && stuck.Value() < 0.3,
                   "what the look changes stays on the surfaces while the camera moves");
        }
    }
    for (const float times : {8.0f, 1.5f}) {
        // Another exposure: the scene eight times as bright gets the same look, and so does
        // one brighter by a part of a stop (no step of the look lies at a brightness of its own).
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff));
        const Scene bright = MakeScene(large, first, Paint::Grit, times);
        const auto out_bright = gpu.Run(bright, Words(large, first, Look::ViewOff));
        u32 off = 0;
        for (u32 i = 0; i < pixels; ++i) {
            off += std::abs(Luminance(out_bright[i]) / times - Luminance(out[i])) >
                   0.01f * Luminance(out[i]);
        }
        std::printf("%.1f times as bright: %u of %u pixels differ by more than 1%%\n", times, off,
                    pixels);
        Expect(off < pixels / 1000, "the look does not depend on how bright the scene is");
    }
    {
        // What counts as black, and what as glowing, is told from the surfaces: not from the
        // sky, however bright, and not from a pixel or two that are off the scale.
        const auto out = gpu.Run(grit, Words(large, first, Look::ViewOff));
        Scene bright_sky = grit;
        for (u32 i = 0; i < pixels; ++i) {
            if (bright_sky.surface[i] == Sky) {
                bright_sky.colour[i] = {ToHalf(40.0f), ToHalf(50.0f), ToHalf(60.0f),
                                        bright_sky.colour[i][3]};
            }
        }
        Scene spark = grit;
        const u32 at = (large.height * 3 / 4) * large.width + large.width / 2;
        spark.colour[at] = {ToHalf(60000.0f), ToHalf(60000.0f), ToHalf(60000.0f),
                            spark.colour[at][3]};
        const auto out_sky = gpu.Run(bright_sky, Words(large, first, Look::ViewOff));
        const auto out_spark = gpu.Run(spark, Words(large, first, Look::ViewOff));
        // Next to the sky and to the spark the picture differs, and so may the look: the
        // surfaces 150 pixels and more away from either are compared.
        std::vector<u8> near_sky(pixels, 0);
        const int reach = 150;
        for (u32 y = 0; y < large.height; y += 10) {
            for (u32 x = 0; x < large.width; x += 10) {
                if (grit.surface[y * large.width + x] != Sky) {
                    continue;
                }
                for (int v = std::max(int(y) - reach, 0);
                     v < std::min(int(y) + reach, int(large.height)); ++v) {
                    std::memset(&near_sky[size_t(v) * large.width + std::max(int(x) - reach, 0)], 1,
                                size_t(std::min(int(x) + reach, int(large.width)) -
                                       std::max(int(x) - reach, 0)));
                }
            }
        }
        u32 compared = 0, off_sky = 0, far = 0, off_spark = 0;
        for (u32 i = 0; i < pixels; ++i) {
            if (grit.surface[i] == Sky) {
                continue;
            }
            const float was = Luminance(out[i]);
            if (!near_sky[i]) {
                ++compared;
                off_sky += std::abs(Luminance(out_sky[i]) - was) > 0.01f * was;
            }
            const int dx = int(i % large.width) - int(at % large.width);
            const int dy = int(i / large.width) - int(at / large.width);
            if (std::abs(dx) > reach || std::abs(dy) > reach) {
                ++far;
                off_spark += std::abs(Luminance(out_spark[i]) - was) > 0.01f * was;
            }
        }
        std::printf("a sky some 500 times as bright: %u of %u surface pixels away from it differ "
                    "by more than 1%%; one pixel at 60000: %u of %u pixels away from it differ\n",
                    off_sky, compared, off_spark, far);
        Expect(compared > pixels / 4 && off_sky < compared / 1000,
               "a bright sky does not change the look on the surfaces");
        Expect(off_spark < far / 1000, "a pixel off the scale does not change the look elsewhere");
    }
    {
        // Bold or fine is settled for a whole stroke, and stays settled: the same camera with
        // another jitter under a pixel (the next frame of a still camera) takes the same size
        // of stroke at nearly every point, also where the picture is on the line between plain
        // and detailed. Which size a pixel shows is told from the test views: view 1 (the sizes
        // the look mixes) is there as view 4 (all bold), as view 2 (all fine), or between.
        Camera again = first;
        again.jitter = {-0.42f, 0.13f};
        const Scene a = MakeScene(large, first, Paint::Patches);
        const Scene b = MakeScene(large, again, Paint::Patches);
        enum : u8 { None, Bold, Fine, Between };
        const auto sizes = [&](const Scene& s, const Camera& camera) {
            const auto mixed = gpu.Run(s, Words(large, camera, Look::ViewStrokes));
            const auto all_bold = gpu.Run(s, Words(large, camera, Look::ViewBold));
            const auto all_fine = gpu.Run(s, Words(large, camera, Look::ViewFine));
            std::vector<u8> size(pixels, None);
            for (u32 i = 0; i < pixels; ++i) {
                if (s.surface[i] == Sky || Same(mixed[i], s.colour[i])) {
                    continue;
                }
                // A pixel that the bold and the fine view paint alike tells nothing.
                const bool as_bold = Alike(mixed[i], all_bold[i]);
                const bool as_fine = Alike(mixed[i], all_fine[i]);
                size[i] = as_bold && as_fine ? None : as_bold ? Bold : as_fine ? Fine : Between;
            }
            return size;
        };
        const auto size_a = sizes(a, first), size_b = sizes(b, again);
        std::array<u32, 4> count{};
        u32 compared = 0, same = 0, flipped = 0;
        for (u32 i = 0; i < pixels; ++i) {
            ++count[size_a[i]];
            int bx = 0, by = 0;
            double z = 0.0;
            if (size_a[i] == None || !Project(large, again, a.world[i], bx, by, z)) {
                continue;
            }
            const u32 j = u32(by) * large.width + u32(bx);
            if (b.surface[j] != a.surface[i] || size_b[j] == None) {
                continue;
            }
            ++compared;
            same += size_a[i] == size_b[j];
            flipped += (size_a[i] == Bold && size_b[j] == Fine) ||
                       (size_a[i] == Fine && size_b[j] == Bold);
        }
        const u32 told = count[Bold] + count[Fine] + count[Between];
        std::printf("patches (the picture goes from plain to detailed and back): of %u pixels "
                    "%.1f%% take bold strokes, %.1f%% fine ones, %.1f%% something between. "
                    "Another jitter: %.2f%% of %u points take the same size, %.2f%% went from "
                    "bold to fine or back\n",
                    told, 100.0 * count[Bold] / told, 100.0 * count[Fine] / told,
                    100.0 * count[Between] / told, 100.0 * same / compared, compared,
                    100.0 * flipped / compared);
        Expect(count[Bold] > told / 10 && count[Fine] > told / 10,
               "the patches take bold strokes in places and fine ones in others");
        Expect(same > compared * 0.9 && flipped < compared / 50,
               "bold or fine stays settled from one jitter to the next");
    }
    {
        // A floor with bumps in its normals (a normal map: cobbles), leaning as far as 50
        // degrees: the floor itself is flat, and its strokes stay the floor's.
        Scene bumps = scene;
        u32 floor = 0, leaning = 0;
        for (u32 i = 0; i < n; ++i) {
            if (bumps.surface[i] != Floor) {
                continue;
            }
            ++floor;
            const Vec3& p = bumps.world[i];
            const u32 cell = Hash(u32(int(std::floor(p[0] * 20.0)) + 4096) +
                                  Hash(u32(int(std::floor(p[2] * 20.0)) + 4096)));
            if (cell & 0x100u) {
                ++leaning;
                const double angle = 50.0 * 3.14159265358979 / 180.0;
                const bool along_x = cell & 0x200u;
                const Vec3 normal{along_x ? std::sin(angle) : 0.0, std::cos(angle),
                                  along_x ? 0.0 : std::sin(angle)};
                for (int k = 0; k < 3; ++k) {
                    bumps.normal[i][k] = u8(std::lround((normal[k] * 0.5 + 0.5) * 255.0));
                }
            }
        }
        const auto out = gpu.Run(bumps, Words(lens, straight, Look::ViewBold));
        u32 same = 0;
        for (u32 i = 0; i < n; ++i) {
            same += bumps.surface[i] == Floor && Alike(bold[i], out[i]);
        }
        std::printf("a flat floor with bumps in its normals (%.0f%% of it leaning 50 degrees): "
                    "%.2f%% of %u floor pixels show the stroke they show without the bumps\n",
                    100.0 * leaning / floor, 100.0 * same / floor, floor);
        Expect(same > floor * 0.97, "bumps in the normals do not move a flat surface's strokes");
    }
    {
        // What moves by itself gets no strokes: smoothed by its own share of the strength,
        // and left alone at 0. The ball is plain here: smoothing a flat colour changes nothing
        // but at its rim, where a little of what lies behind it gets in (the small levels of
        // the copy know no silhouettes; the depth test keeps out all but a few per cent).
        const Scene plain = MakeScene(large, first, Paint::Plain);
        const auto with = gpu.Run(plain, Words(large, first, Look::ViewOff, true, true, 1.0f, 1.0f));
        const auto none = gpu.Run(plain, Words(large, first, Look::ViewOff, true, true, 1.0f, 0.0f));
        const auto fixed = gpu.Run(plain, Words(large, first, Look::ViewOff, true, false, 1.0f));
        u32 ball = 0, marked = 0, untouched = 0, stroked = 0;
        double most = 0.0;
        for (u32 i = 0; i < pixels; ++i) {
            if (plain.surface[i] == Ball) {
                ++ball;
                const double change = std::abs(Change(plain, with, i));
                most = std::max(most, change);
                marked += change > 0.02;
                untouched += Same(none[i], plain.colour[i]);
                stroked += std::abs(Change(plain, fixed, i)) > 0.02;
            }
        }
        std::printf("a ball that moves by itself: of %u pixels %u change their brightness by "
                    "more than 2%% (%u when it is not marked as moving), the most %.1f%%; with "
                    "graphics_drawn_look_characters 0, %u are untouched\n",
                    ball, marked, stroked, most * 100.0, untouched);
        Expect(ball > 5000 && marked < ball / 20 && most < 0.1 && stroked > ball / 4 &&
                   untouched == ball,
               "what moves by itself is smoothed, not stroked");
    }
    {
        // (r45b_drawn-look-fixes) Having a vector in the object motion image is not moving: in
        // the game most of the world has one (walls and floors drawn through a bone buffer),
        // and it says what the camera did. Every surface has such a vector here. The camera
        // stood still since the frame before, or turned and walked, or turned and zoomed: the
        // surfaces get the strokes they get without the image, pixel for pixel; a ball that
        // lies still gets them too; a ball that moves three pixels a frame is smoothed. Without
        // the camera of the frame before nothing tells still from moving, and all of it is
        // smoothed (what r45 did on every frame).
        const Lens longer{large.width, large.height, large.ys * 1.07};
        struct Case {
            const char* name;
            const Camera* before;
            const Lens* lens_before;
        };
        const Case cases[] = {{"the camera stood still", &first, &large},
                              {"the camera turned and walked", &walked, &large},
                              {"the camera turned and zoomed", &turned, &longer}};
        const Scene plain = MakeScene(large, first, Paint::Plain);
        const auto fixed = gpu.Run(plain, Words(large, first, Look::ViewOff, true, false, 1.0f));
        u32 world = 0, ball = 0, world_stroked = 0;
        for (u32 i = 0; i < pixels; ++i) {
            world += plain.surface[i] != Sky && plain.surface[i] != Ball;
            ball += plain.surface[i] == Ball;
            world_stroked += plain.surface[i] != Sky && plain.surface[i] != Ball &&
                             std::abs(Change(plain, fixed, i)) > 0.02;
        }
        bool ok = world > pixels / 2 && ball > 5000 && world_stroked > world / 4;
        for (const Case& c : cases) {
            const Vectors still{c.before, c.lens_before, true, {}};
            const Vectors rolls{c.before, c.lens_before, true, {3.0f, 0.0f}};
            const Scene at_rest = MakeScene(large, first, Paint::Plain, 1.0f, still);
            const Scene rolling = MakeScene(large, first, Paint::Plain, 1.0f, rolls);
            const auto words = Words(large, first, Look::ViewOff, true, true, 1.0f, 1.0f,
                                     c.before, c.lens_before);
            ok &= (words.flags & Look::FlagPrevious) != 0;
            const auto rest = gpu.Run(at_rest, words);
            const auto roll = gpu.Run(rolling, words);
            u32 world_off = 0, world_beside = 0, ball_off = 0, ball_marked = 0;
            for (u32 i = 0; i < pixels; ++i) {
                if (plain.surface[i] == Sky) {
                    continue;
                }
                if (plain.surface[i] == Ball) {
                    ball_off += !Same(rest[i], fixed[i]);
                    ball_marked += std::abs(Change(plain, roll, i)) > 0.02;
                } else {
                    // (Beside a smoothed ball the colour lock's means are other ones.)
                    world_off += !Same(rest[i], fixed[i]);
                    world_beside += !Same(roll[i], fixed[i]);
                }
            }
            std::printf("every surface has a vector, %s: %u of %u pixels of the world are not "
                        "the strokes they get without vectors; of the ball's %u pixels %u are "
                        "not when it lies still, and %u change by more than 2%% when it moves "
                        "3 pixels a frame (%u pixels of the world beside it are other ones "
                        "then)\n",
                        c.name, world_off, world, ball, ball_off, ball_marked, world_beside);
            ok &= world_off == 0 && ball_off == 0 && ball_marked < ball / 20 &&
                  world_beside < world / 100;
        }
        {
            const Vectors still{&walked, &large, true, {}};
            const Scene at_rest = MakeScene(large, first, Paint::Plain, 1.0f, still);
            const auto blind = gpu.Run(at_rest, Words(large, first, Look::ViewOff, true, true, 1.0f,
                                                      1.0f));
            u32 marked = 0;
            for (u32 i = 0; i < pixels; ++i) {
                marked += plain.surface[i] != Sky && plain.surface[i] != Ball &&
                          std::abs(Change(plain, blind, i)) > 0.02;
            }
            std::printf("the same without the camera of the frame before: %u pixels of the world "
                        "change by more than 2%% (%u with strokes)\n", marked, world_stroked);
            ok &= marked < world_stroked / 5;
        }
        Expect(ok, "a surface that lies still gets its strokes although it has a vector, "
                   "whatever the camera did; what moves against the camera's move does not");
    }
    {
        // The words of the camera of the frame before (DrawnLookParams::Make).
        const auto same = Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first);
        bool ok = (same.flags & Look::FlagPrevious) != 0 &&
                  (same.flags >> Look::ZoomShift) == 32768u;
        for (int k = 0; k < 3; ++k) {
            ok &= std::abs(same.back_turn[k]) < 1e-6f && std::abs(same.back_shift[k]) < 1e-5f;
        }
        const auto none = Words(large, first, Look::ViewOff, true, true);
        ok &= !(none.flags & Look::FlagPrevious) && (none.flags >> Look::ZoomShift) == 32768u;
        // A cut: the camera looks the other way; and a lens three times as long.
        Camera behind = first;
        behind.yaw += 3.0;
        const Lens tele{large.width, large.height, large.ys * 3.0};
        ok &= !(Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &behind).flags &
                Look::FlagPrevious);
        ok &= !(Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first, &tele).flags &
                Look::FlagPrevious);
        // A mirrored camera (a reflection's) is no turn of this one.
        Look::Previous mirrored{first.View(), large.Proj()};
        for (int k = 0; k < 4; ++k) {
            mirrored.view[4 + k] = -mirrored.view[4 + k];
        }
        ok &= !(Look::Make({}, first.InvView(), large.Proj(), large.width, large.height,
                           first.jitter, true, true, &mirrored).flags & Look::FlagPrevious);
        const Lens longer{large.width, large.height, large.ys * 1.07};
        const auto zoomed = Words(large, first, Look::ViewOff, true, true, 0.6f, 0.5f, &first,
                                  &longer);
        ok &= (zoomed.flags & Look::FlagPrevious) != 0 &&
              std::abs(int(zoomed.flags >> Look::ZoomShift) - 32768 - int(0.07 * 32768.0)) <= 1;
        // The zoom's bits lie above the test view's: the view is read without them.
        ok &= Look::ViewOf(zoomed.flags) == u32(Look::ViewOff) &&
              Look::ViewOf(Words(large, first, Look::ViewBold, true, true, 0.6f, 0.5f, &first,
                                 &longer).flags) == u32(Look::ViewBold);
        Expect(ok, "the camera of the frame before becomes a turn, a shift and a zoom, and is "
                   "left out after a cut");
    }
    {
        // Which draws of six indices or fewer are transparents (the rasterizer's scene hook):
        // blended, not bypassed, no depth written, depth tested with a function that can fail.
        using Look::SmallTransparent;
        bool ok = SmallTransparent(true, false, false, true, false);
        u32 counted = 0;
        for (u32 bits = 0; bits < 32; ++bits) {
            const bool blend = bits & 1, bypass = bits & 2, write = bits & 4, test = bits & 8,
                       always = bits & 16;
            if (SmallTransparent(blend, bypass, write, test, always)) {
                ++counted;
                ok &= blend && !bypass && !write && test && !always;
            }
        }
        // A full-screen pass: not blended (a lighting pass, a copy), or blended without a depth
        // test or with one that always passes (the fog composite). A decal: it writes depth.
        ok &= counted == 1 && !SmallTransparent(false, false, false, true, false) &&
              !SmallTransparent(true, false, false, false, false) &&
              !SmallTransparent(true, false, false, true, true) &&
              !SmallTransparent(true, false, true, true, false) &&
              !SmallTransparent(true, true, false, true, false);
        static_assert(SmallTransparent(true, false, false, true, false));
        Expect(ok, "of the draws of six indices or fewer only a blended, depth-tested one that "
                   "writes no depth is a transparent");
    }
    {
        // A colour that is no number, an endless one and one below 0 stay where they are.
        Scene broken = MakeScene(lens, straight, Paint::Grit);
        const u32 at = (lens.height * 3 / 4) * lens.width + lens.width / 2;
        broken.colour[at] = {0x7e00, 0x7e00, 0x7e00, broken.colour[at][3]};
        broken.colour[at + 40] = {0x7c00, 0x7c00, 0x7c00, broken.colour[at + 40][3]};
        broken.colour[at + 80] = {ToHalf(-2.0f), ToHalf(-2.0f), ToHalf(-2.0f),
                                  broken.colour[at + 80][3]};
        const auto out = gpu.Run(broken, Words(lens, straight, Look::ViewOff, true, false, 1.0f));
        u32 bad = 0;
        for (u32 i = 0; i < n; ++i) {
            const Rgb c = Colour(out[i]);
            bad += i != at && i != at + 40 && i != at + 80 &&
                   !(std::isfinite(c[0]) && std::isfinite(c[1]) && std::isfinite(c[2]) &&
                     c[0] >= 0.0f && c[1] >= 0.0f && c[2] >= 0.0f);
        }
        std::printf("three broken pixels in the scene: %u other pixels are no colour after the "
                    "look\n", bad);
        Expect(bad == 0, "a broken pixel does not spread");
    }
    if (argc > 1) {
        const Lens half{960, 540};
        const Scene lit = MakeScene(half, first, Paint::Grit);
        const auto look = gpu.Run(lit, Words(half, first, Look::ViewOff, true, true, 1.0f));
        const auto mixed = gpu.Run(lit, Words(half, first, Look::ViewStrokes, true, true));
        const auto all_bold = gpu.Run(lit, Words(half, first, Look::ViewBold, true, true));
        WritePicture(argv[1], half.width, half.height, {&lit.colour, &look, &mixed, &all_bold});
    }
    std::puts(failed ? "FAILED: drawn look" : "PASS: drawn look");
    return failed ? 1 : 0;
}
