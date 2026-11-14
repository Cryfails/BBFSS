// SPDX-License-Identifier: GPL-3.0-or-later

#include "video_core/renderer_vulkan/vk_rt_shadow.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <span>

#include <xxhash.h>

#include "bbport_sections.h"
#include "bbport_settings.h"
#include "bbport_sun_cascades.h"
#include "bbport_toggles.h"
#include "shader_recompiler/runtime_info.h"
#include "video_core/host_shaders/rt_shadow_coverage_comp.h"
#include "video_core/host_shaders/rt_shadow_filter_r25_comp.h" // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_shadow_half_comp.h"       // bbport (r25_rt-sun-trace)
#include "video_core/host_shaders/rt_unproject_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_object_motion.h"
#include "video_core/renderer_vulkan/vk_platform.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_sun_vsm.h"

namespace Vulkan {
namespace {
constexpr u32 MaxParams = 8192;
static_assert(1 + 4 * MaxParams == Shader::MotionVectors::CaptureParamsCapacity);
constexpr u32 MaxPositions = 8u << 20;
constexpr u32 MaxInstances = 8192;
constexpr u32 MaxInstancesPerDraw = 64;
constexpr u32 MaxTrianglesPerBlas = 2u << 20;
constexpr u32 NewTrianglesPerFrame = 200000;
constexpr u32 RebuiltTrianglesPerFrame = 300000;
constexpr u32 RebuildEveryFrames = 120;
constexpr u32 RebuildSpread = 32;
constexpr u64 UnusedFrames = 240;
constexpr u64 KeptFrames = 2;
// bbport (r14_cascade_rt): a cascade drawn once every `period` frames leaves its casters undrawn
// for period - 1 frames in a row; they stay in the scene HoldMarginFrames longer: one for a frame
// with no shadow pass at all inside such a gap (the game's schedule does not advance), one for
// frames still arriving under a longer period after the game thread published a shorter one.
// The window only bounds frames in which a cascade is not drawn at all: a cascade drawn without
// an entry drops it at once. Periods above MaxHoldPeriod are held as MaxHoldPeriod.
constexpr u64 HoldMarginFrames = 2;
constexpr u32 MaxHoldPeriod = 16;
// The game culls its sun shadow casters to its own short cascades; the virtual shadow map reaches
// further, so static casters keep drawing from their world copies long after the game stops
// submitting them (about an hour at 60 fps); the entry memory cap evicts the oldest first.
constexpr u64 VsmKeepFrames = 60ull * 60 * 60;
// A prop seen unchanged (same mesh, same bone palette) on this many distinct frames gets an
// entry of its own; candidates not seen for CandidateFrames are dropped.
constexpr u32 PromoteFrames = 3;
constexpr u64 CandidateFrames = 120;
constexpr std::size_t MaxCandidates = 32768;
// Captured geometry shares video memory with the texture cache, which evicts (and stalls) long
// before the driver budget runs out, so the geometry gets its own cap.
constexpr u64 MaxEntryBytes = 1536ull << 20;
constexpr vk::DeviceSize ScratchBytes = 192ull << 20;
constexpr VkBufferUsageFlags InputUsage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR;
constexpr u8 ShadowMask = 1, CameraMask = 2;
// bbport: what lamp rays hit (point_shadow_ray.comp). A ray cannot test a texture, so a cut-out
// card (a leaf on a vine) shadows as its whole polygon: rectangles of shadow on the ground. The
// cards the shadow pass draws (Entry::shadow_card) stay out and cast no lamp shadow, as in the
// game; skinned meshes keep theirs (cloth).
constexpr u8 LampMask = 4;

// bbport: experiment mask 256 (a diagnostic): copies of a mesh drawn more than once in a pass
// ("shared" entries, see PrepareDraw) are built once and then not refreshed, which shows what
// their refresh costs and whether anything visibly depends on it.
u32 RebuiltBudget() {
    return BbToggle::Experiment(256) ? 0u : RebuiltTrianglesPerFrame;
}

// bbport: only the sun VSM reads the casters' world copies (Record's VSM branch, the kept
// casters and their eviction guard). With it off they are neither allocated nor filled: no
// copyBuffer per build, no copy barrier, no buffer per caster. Experiment mask 16777216 restores
// the copies whatever the VSM setting.
bool WorldCopies() {
    return BbToggle::Experiment(16777216) ||
           BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed);
}
// Builds recorded, world copies recorded (and their bytes), sun shadow builds whose copy was not
// made, since the last "Ray tracing world copies:" line.
struct WorldCopyStats {
    u64 builds = 0, copies = 0, bytes = 0, skipped = 0, skipped_bytes = 0;
    u64 printed_frame = 0;
};
WorldCopyStats world_copy_stats;

// bbport (r17_rt-upkeep): experiment 4398046511104 set = the old upkeep (TLAS built in full every
// frame without eAllowUpdate, shared copies rebuilt for fast tracing, ToWorld for every draw, the
// opt-ins off). Read at each use.
bool UpkeepOn() {
    return !BbToggle::Experiment(4398046511104ull);
}
// BB_RT_UNCHANGED: 0 off (default), 1 count, 2 skip.
u32 UnchangedMode() {
    static const u32 mode = [] {
        const char* env = std::getenv("BB_RT_UNCHANGED");
        if (!env) {
            return 0u;
        }
        return std::strcmp(env, "skip") == 0 ? 2u : std::strcmp(env, "count") == 0 ? 1u : 0u;
    }();
    return mode;
}
// BB_RT_REFIT_EVERY: 2..16, else 0 (off). bbport (r37_menu-options): set, it decides; not set,
// lantern.ini's graphics_rt_far_refit does (8 on, 0 off), read at each use. Turned on while the
// game runs, the near draws of the frame before were not booked (r19_far_book): a caster whose far
// draw comes first can miss one refit in that one frame.
constexpr u32 FarRefitSetting = 8;
u32 RefitEvery() {
    static const s32 env_every = [] {
        const char* env = std::getenv("BB_RT_REFIT_EVERY");
        if (!env || !env[0]) {
            return -1;
        }
        const u32 n = u32(std::strtoul(env, nullptr, 10));
        return n >= 2 && n <= 16 ? s32(n) : 0;
    }();
    if (env_every >= 0) {
        return u32(env_every);
    }
    return BbSettings::Get().graphics_rt_far_refit.load(std::memory_order_relaxed) ? FarRefitSetting
                                                                                  : 0u;
}
// bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE, a measuring probe of ray tracing upkeep, off
// unless set: "blas" 1 (BLAS refits and builds left out), "tlas" 2 (the TLAS traced as last
// built), "all" 3 (both); else 0. Read once.
u32 UpkeepProbeMode() {
    static const u32 mode = [] {
        const char* env = std::getenv("BB_RT_UPKEEP_FREEZE");
        if (!env) {
            return 0u;
        }
        const u32 m = std::strcmp(env, "all") == 0    ? 3u
                      : std::strcmp(env, "tlas") == 0 ? 2u
                      : std::strcmp(env, "blas") == 0 ? 1u
                                                      : 0u;
        if (m == 0) {
            std::printf("Ray tracing upkeep probe (r26): BB_RT_UPKEEP_FREEZE=%s not understood "
                        "(all, blas or tlas): off\n",
                        env);
        }
        return m;
    }();
    return mode;
}
// Frames in a row with casters in the ray tracing scene before the probe acts (scene built).
constexpr u64 R26AfterFrames = 300;
// Experiment bit set = the probe does nothing (normal upkeep); read at each frame end.
constexpr u64 R26ProbeOffBit = 2251799813685248ull; // 1 << 51
// TLAS refits in a row before a full build.
constexpr u32 TlasRefitsBetweenBuilds = 30;
static_assert(sizeof(vk::AccelerationStructureInstanceKHR) == 64);

struct TracePush {
    u32 buf_off;
    u32 frame_index;
    std::array<float, 2> size;
    u32 rays;
    float light_tan;
    float bias_m;
    float max_distance;
    s32 far_radius; // rt_shadow.comp COVERAGE_SKIP: the filter's radius, < 0 traces every pixel
    u32 r25_flags;  // bbport (r25_rt-sun-trace): R25Exact | R25Count | R25HalfFirst | R25HalfFill
};
static_assert(sizeof(TracePush) == 40);

struct FilterPush {
    u32 buf_off;
    s32 radius;
    std::array<float, 2> size;
    u32 r25_flags; // bbport (r25_rt-sun-trace): R25Exact | R25Count (rt_shadow_filter.comp R25)
};
static_assert(sizeof(FilterPush) == 20);

// bbport (r25_rt-sun-trace): experiment bit: set = the old sun trace and filter paths (read at
// every sun trace). Push constant bits, as in rt_shadow.comp and rt_shadow_filter.comp.
constexpr u64 R25SunTraceOffBit = 1125899906842624ull;
constexpr u32 R25Exact = 1, R25Count = 2, R25HalfFirst = 4, R25HalfFill = 8;

struct UnprojectPush {
    std::array<float, 12> rows;
    u32 first;
    u32 count;
};
static_assert(sizeof(UnprojectPush) == 56);

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
constexpr auto AsBuild = vk::PipelineStageFlagBits2::eAccelerationStructureBuildKHR;

std::array<float, 16> Invert(const float* m, bool& ok) {
    std::array<double, 32> t{};
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            t[r * 8 + c] = m[r * 4 + c];
        }
        t[r * 8 + 4 + r] = 1.0;
    }
    ok = false;
    std::array<float, 16> out{};
    for (int p = 0; p < 4; ++p) {
        int best = p;
        for (int r = p + 1; r < 4; ++r) {
            if (std::abs(t[r * 8 + p]) > std::abs(t[best * 8 + p])) {
                best = r;
            }
        }
        if (std::abs(t[best * 8 + p]) < 1e-12) {
            return out;
        }
        for (int c = 0; c < 8; ++c) {
            std::swap(t[p * 8 + c], t[best * 8 + c]);
        }
        const double scale = 1.0 / t[p * 8 + p];
        for (int c = 0; c < 8; ++c) {
            t[p * 8 + c] *= scale;
        }
        for (int r = 0; r < 4; ++r) {
            if (r != p) {
                const double f = t[r * 8 + p];
                for (int c = 0; c < 8; ++c) {
                    t[r * 8 + c] -= f * t[p * 8 + c];
                }
            }
        }
    }
    for (int r = 0; r < 4; ++r) {
        for (int c = 0; c < 4; ++c) {
            out[r * 4 + c] = float(t[r * 8 + 4 + c]);
        }
    }
    ok = true;
    return out;
}

template <class Index>
bool AppendTriangles(std::span<const Index> source, bool strip, bool restart, u32 lo,
                     std::vector<u32>& out) {
    const Index cut = std::numeric_limits<Index>::max();
    const auto emit = [&](u32 a, u32 b, u32 c) {
        if (a != b && b != c && a != c) {
            out.insert(out.end(), {a - lo, b - lo, c - lo});
        }
    };
    if (!strip) {
        for (std::size_t i = 0; i + 2 < source.size(); i += 3) {
            if (restart && (source[i] == cut || source[i + 1] == cut || source[i + 2] == cut)) {
                return false;
            }
            emit(source[i], source[i + 1], source[i + 2]);
        }
        return true;
    }
    u32 run = 0;
    u32 a = 0, b = 0;
    for (const Index index : source) {
        if (restart && index == cut) {
            run = 0;
            continue;
        }
        if (run >= 2) {
            emit(a, b, index);
        }
        a = b;
        b = index;
        ++run;
    }
    return true;
}
}

RtShadow::RtShadow(const Instance& instance_, Scheduler& scheduler_, CameraMotion& camera_motion_,
                   const ObjectMotion& object_motion)
    : instance{instance_}, scheduler{scheduler_}, camera_motion{camera_motion_} {
    if (!BbSettings::Get().startup_effects[BbSettings::EffectRayTracing]) {
        return;
    }
    if (!instance.IsRayQuerySupported()) {
        std::printf("Ray tracing: off - this GPU or driver has no ray query\n");
        return;
    }
    if (!instance.GetPhysicalDevice().getFeatures().vertexPipelineStoresAndAtomics) {
        std::printf("Ray tracing: off - no vertex shader stores\n");
        return;
    }
    if (!camera_motion.Enabled()) {
        std::printf("Ray tracing: off - the camera is not tracked (BB_UPSCALER=none)\n");
        return;
    }
    if (const char* env = std::getenv("LANTERN_RT_SCENE_MB"); env && env[0]) {
        blas_limit = u64(std::clamp(std::strtoul(env, nullptr, 10), 64ul, 4096ul)) << 20;
    }
    if (const char* env = std::getenv("LANTERN_RT_SHADOW_RAYS"); env && env[0]) {
        rays = std::clamp(u32(std::strtoul(env, nullptr, 10)), 1u, 16u);
    }
    // bbport (r37_menu-options): set, BB_RT_SUN_HALF decides ("1" on, else off); not set,
    // graphics_rt_sun_half does (R25HalfWanted, at every sun trace).
    if (const char* env = std::getenv("BB_RT_SUN_HALF"); env && env[0]) {
        r25_half_env = env[0] == '1' ? 1 : 0;
    }
    if (r25_half_env == 1) { // bbport (r25_rt-sun-trace)
        std::printf("Ray traced sun (r25): BB_RT_SUN_HALF=1, one ray per 2x2 block first, then "
                    "full-resolution rays where those differ (changes the picture)\n");
    }
    capturing = Setup(object_motion);
    if (capturing) {
        std::printf("Ray tracing: on, sun %u rays a pixel, lamps and bounced light\n", rays);
    } else {
        std::printf("Ray tracing: off - setup failed\n");
    }
}

RtShadow::~RtShadow() {
    if (!tried) {
        return;
    }
    scheduler.Finish();
    vsm.reset();
    const auto device = instance.GetDevice();
    for (auto& [key, entry] : entries) {
        device.destroyAccelerationStructureKHR(entry->handle);
        Free(entry->storage);
        Free(entry->indices);
        Free(entry->world);
    }
    if (tlas) {
        device.destroyAccelerationStructureKHR(tlas);
    }
    Free(r25_counts); // bbport (r25_rt-sun-trace)
    Free(r25_readback);
    if (raw_view) {
        device.destroyImageView(raw_view);
    }
    if (raw_image) {
        vmaDestroyImage(instance.GetAllocator(), raw_image, raw_allocation);
    }
    for (Buffer* b : {&capture_addresses, &both_addresses, &params, &positions, &scratch,
                      &instance_data, &tlas_storage, &tlas_scratch}) {
        Free(*b);
    }
}

bool RtShadow::Make(Buffer& out, vk::DeviceSize size, bool host, VkBufferUsageFlags usage) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = size,
        .usage = usage | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
    if (host) {
        alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT |
                         VMA_ALLOCATION_CREATE_HOST_ACCESS_SEQUENTIAL_WRITE_BIT;
    } else {
        alloc_ci.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE;
    }
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &out.allocation,
                        &info) != VK_SUCCESS) {
        return false;
    }
    out.buffer = raw;
    out.mapped = info.pMappedData;
    out.address = instance.GetDevice().getBufferAddress({.buffer = out.buffer});
    return out.address != 0;
}

void RtShadow::Free(Buffer& buffer) {
    if (buffer.buffer) {
        vmaDestroyBuffer(instance.GetAllocator(), buffer.buffer, buffer.allocation);
    }
    buffer = {};
}

void RtShadow::Destroy(Entry& entry) {
    entry_bytes -= std::min(entry_bytes, entry.bytes);
    blas_bytes -= std::min(blas_bytes, entry.scene_bytes);
    entry.bytes = 0;
    entry.scene_bytes = 0;
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    // bbport (r35_pending-ops): a pure free (the entry is gone from the scene): may be carried.
    scheduler.DeferOperation(
        [device, allocator, handle = entry.handle, storage = entry.storage,
         indices = entry.indices, world = entry.world] {
            device.destroyAccelerationStructureKHR(handle);
            vmaDestroyBuffer(allocator, storage.buffer, storage.allocation);
            vmaDestroyBuffer(allocator, indices.buffer, indices.allocation);
            if (world.buffer) {
                vmaDestroyBuffer(allocator, world.buffer, world.allocation);
            }
        },
        "BLAS free (RtShadow::Destroy)", true);
}

bool RtShadow::EnsureWorld(Entry& entry) {
    if (entry.world.buffer) {
        return true;
    }
    const vk::DeviceSize world_bytes = vk::DeviceSize(entry.vertices) * entry.instances * 16;
    if (entry_bytes + world_bytes > MaxEntryBytes || !EffectPass::HasRoom(instance, world_bytes)) {
        return false;
    }
    if (!Make(entry.world, world_bytes, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT)) {
        Free(entry.world);
        return false;
    }
    entry.bytes += world_bytes;
    entry_bytes += world_bytes;
    return true;
}

// bbport (r37_menu-options): the half-resolution sun trace (r25) while BB_RT_SUN_HALF=1 or, with
// the variable not set, while graphics_rt_sun_half is on. Read at every sun trace: both ways write
// every pixel the filter reads within the trace (rt_shadow.comp Shade), nothing is kept from the
// frame before, so it can change from one frame to the next. The pipeline is made the first time.
bool RtShadow::R25HalfWanted() {
    // bbport (r39_master-debug): engine_previous_paths on: full resolution as before r25,
    // whatever the setting and BB_RT_SUN_HALF say (this mode has no experiment bit of its own).
    const bool wanted =
        !BbSettings::Get().engine_previous_paths.load(std::memory_order_relaxed) &&
        (r25_half_env >= 0 ? r25_half_env == 1
                           : BbSettings::Get().graphics_rt_sun_half.load(std::memory_order_relaxed));
    if (wanted && !r25_half_tried) {
        r25_half_tried = true;
        using enum vk::DescriptorType;
        const bool made =
            EffectPass::Create(instance, r25_half_set, r25_half_layout, r25_half_pipeline,
                               {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                                eAccelerationStructureKHR, eStorageBuffer, eStorageBuffer},
                               sizeof(TracePush), RT_SHADOW_HALF_COMP,
                               "Ray traced shadows (half resolution)");
        std::printf("Ray traced sun (r25): half resolution (%s) %s\n",
                    r25_half_env == 1 ? "BB_RT_SUN_HALF=1" : "graphics_rt_sun_half=1",
                    made ? "ready" : "ignored - no pipeline");
    }
    return wanted && r25_half_pipeline;
}

bool RtShadow::Setup(const ObjectMotion& object_motion) {
    tried = true;
    const auto device = instance.GetDevice();
    using enum vk::DescriptorType;
    const VkBufferUsageFlags as_storage = VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR;
    if (!EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) ||
        !EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) ||
        !EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest) ||
        !EffectPass::Create(instance, trace_set, trace_layout, trace_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eStorageImage,
                             eAccelerationStructureKHR, eStorageBuffer,
                             eStorageBuffer}, // r25: counters
                            sizeof(TracePush), RT_SHADOW_COVERAGE_COMP, "Ray traced shadows") ||
        !EffectPass::Create(instance, filter_set, filter_layout, filter_pipeline,
                            {eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                             eStorageImage, eStorageBuffer, eStorageBuffer}, // r25: counters
                            sizeof(FilterPush), RT_SHADOW_FILTER_R25_COMP,
                            "Ray traced shadow filter") ||
        !EffectPass::Create(instance, unproject_set, unproject_layout, unproject_pipeline,
                            {eStorageBuffer}, sizeof(UnprojectPush), RT_UNPROJECT_COMP,
                            "Ray tracing positions")) {
        return false;
    }
    if (!Make(params, vk::DeviceSize(1 + 4 * MaxParams) * 32, true, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        !Make(positions, vk::DeviceSize(MaxPositions) * 16, false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | InputUsage) ||
        !Make(scratch, ScratchBytes, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT) ||
        !Make(instance_data,
              vk::DeviceSize(4 * MaxInstances) * sizeof(vk::AccelerationStructureInstanceKHR), true,
              InputUsage) ||
        !Make(capture_addresses, 16, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT) ||
        !Make(both_addresses, 32, true, VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT)) {
        return false;
    }
    std::memset(params.mapped, 0, 32);
    // bbport (r25_rt-sun-trace): the pass counters (zeroed on the GPU by the first sun trace).
    if (!Make(r25_counts, R25Slots * sizeof(u32), false,
              VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT |
                  VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !Make(r25_readback, R25Slots * sizeof(u32), true, VK_BUFFER_USAGE_TRANSFER_DST_BIT) ||
        !r25_readback.mapped) {
        return false;
    }
    std::memset(r25_readback.mapped, 0, R25Slots * sizeof(u32));
    // bbport (r37_menu-options): the half-resolution trace is made by R25HalfWanted, when first wanted.
    const std::array<u64, 2> capture_table{params.address, positions.address};
    std::memcpy(capture_addresses.mapped, capture_table.data(), sizeof(capture_table));
    const auto motion_table = object_motion.AddressTable();
    const std::array<u64, 4> both_table{motion_table.params, motion_table.positions, params.address,
                                        positions.address};
    std::memcpy(both_addresses.mapped, both_table.data(), sizeof(both_table));
    address_layout = ObjectMotion::CreateAddressLayout(device);
    const vk::DescriptorPoolSize pool_size{vk::DescriptorType::eUniformBuffer, 2};
    auto [pool_result, pool] = device.createDescriptorPoolUnique(
        {.maxSets = 2, .poolSizeCount = 1, .pPoolSizes = &pool_size});
    if (pool_result != vk::Result::eSuccess) {
        return false;
    }
    address_pool = std::move(pool);
    const std::array<vk::DescriptorSetLayout, 2> layouts{*address_layout, *address_layout};
    auto [set_result, sets] = device.allocateDescriptorSets(
        {.descriptorPool = *address_pool, .descriptorSetCount = 2, .pSetLayouts = layouts.data()});
    if (set_result != vk::Result::eSuccess) {
        return false;
    }
    capture_set = sets[0];
    both_set = sets[1];
    const vk::DescriptorBufferInfo capture_info{capture_addresses.buffer, 0, 16};
    const vk::DescriptorBufferInfo both_info{both_addresses.buffer, 0, 32};
    const std::array<vk::WriteDescriptorSet, 2> writes{{
        {.dstSet = capture_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer,
         .pBufferInfo = &capture_info},
        {.dstSet = both_set, .dstBinding = Shader::MotionVectors::AddressBinding,
         .descriptorCount = 1, .descriptorType = vk::DescriptorType::eUniformBuffer,
         .pBufferInfo = &both_info},
    }};
    device.updateDescriptorSets(writes, {});

    const vk::AccelerationStructureGeometryKHR geometry{
        .geometryType = vk::GeometryTypeKHR::eInstances,
        .geometry = {.instances = vk::AccelerationStructureGeometryInstancesDataKHR{}},
        .flags = vk::GeometryFlagBitsKHR::eOpaque,
    };
    const vk::AccelerationStructureBuildGeometryInfoKHR info{
        .type = vk::AccelerationStructureTypeKHR::eTopLevel,
        .flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace,
        .mode = vk::BuildAccelerationStructureModeKHR::eBuild,
        .geometryCount = 1,
        .pGeometries = &geometry,
    };
    const u32 max_instances = MaxInstances;
    auto sizes = device.getAccelerationStructureBuildSizesKHR(
        vk::AccelerationStructureBuildTypeKHR::eDevice, info, max_instances);
    { // bbport (r17_rt-upkeep): room for builds with eAllowUpdate and for refits (PrepareScene)
        vk::AccelerationStructureBuildGeometryInfoKHR updatable = info;
        updatable.flags |= vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate;
        const auto more = device.getAccelerationStructureBuildSizesKHR(
            vk::AccelerationStructureBuildTypeKHR::eDevice, updatable, max_instances);
        sizes.accelerationStructureSize =
            std::max(sizes.accelerationStructureSize, more.accelerationStructureSize);
        sizes.buildScratchSize =
            std::max({sizes.buildScratchSize, more.buildScratchSize, more.updateScratchSize});
    }
    if (!Make(tlas_storage, sizes.accelerationStructureSize, false, as_storage) ||
        !Make(tlas_scratch, sizes.buildScratchSize, false, VK_BUFFER_USAGE_STORAGE_BUFFER_BIT)) {
        return false;
    }
    const auto [result, handle] = device.createAccelerationStructureKHR({
        .buffer = tlas_storage.buffer,
        .size = sizes.accelerationStructureSize,
        .type = vk::AccelerationStructureTypeKHR::eTopLevel,
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    tlas = handle;
    scratch_align = std::max<u64>(
        1, instance.GetPhysicalDevice()
               .getProperties2<vk::PhysicalDeviceProperties2,
                               vk::PhysicalDeviceAccelerationStructurePropertiesKHR>()
               .get<vk::PhysicalDeviceAccelerationStructurePropertiesKHR>()
               .minAccelerationStructureScratchOffsetAlignment);
    return true;
}

bool RtShadow::RayTracing() const {
    return capturing && !failed &&
           BbSettings::Get().effects[BbSettings::EffectRayTracing].load(std::memory_order_relaxed);
}

bool RtShadow::VsmWanted() const {
    // A VSM that could not be made leaves nothing to capture for.
    return RayTracing() && BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed) &&
           !(vsm_tried && (!vsm || !vsm->Ready()));
}

bool RtShadow::SunRayTraced() const {
    if (!RayTracing()) {
        return false;
    }
    const auto& s = BbSettings::Get();
    return s.graphics_rt_sun.load(std::memory_order_relaxed) ||
           (s.graphics_sun_vsm.load(std::memory_order_relaxed) && vsm_tried &&
            (!vsm || !vsm->Ready()));
}

bool RtShadow::SunWanted() const {
    return VsmWanted() || SunRayTraced();
}

bool RtShadow::Wanted() const {
    // Ray tracing on with nothing using the scene or the VSM captures nothing.
    return RayTracing() && (VsmWanted() || SceneWanted());
}

bool RtShadow::Complete() const {
    return Wanted() && !frame_entries.empty() &&
           camera_motion.PassMatrices().valid;
}

void RtShadow::BindAddresses(vk::PipelineLayout layout, u32 mode) {
    const vk::DescriptorSet set = mode == 3u ? both_set : capture_set;
    scheduler.Record([layout, set](vk::CommandBuffer command) {
        command.bindDescriptorSets(vk::PipelineBindPoint::eGraphics, layout,
                                   Shader::MotionVectors::DescriptorSet, set, {});
    });
}

bool RtShadow::ToWorld(const float* constants, bool perspective, std::array<float, 12>& out) const {
    const float* proj = constants + 52;
    const bool ortho = proj[12] == 0.0f && proj[13] == 0.0f && proj[14] == 0.0f && proj[15] == 1.0f;
    if (!ortho && !perspective) {
        return false;
    }
    bool ok = false;
    const auto inverse = Invert(proj, ok);
    if (!ok) {
        return false;
    }
    const float* inv_view = constants + 180;
    for (int r = 0; r < 3; ++r) {
        for (int c = 0; c < 4; ++c) {
            float sum = inv_view[r * 4 + 3] * inverse[12 + c];
            for (int k = 0; k < 3; ++k) {
                sum += inv_view[r * 4 + k] * inverse[k * 4 + c];
            }
            out[r * 4 + c] = sum;
        }
    }
    return std::ranges::all_of(out, [](float v) { return std::isfinite(v); });
}

// bbport (r17_rt-upkeep): ToWorld's result kept for the same inputs: the 16 projection floats at
// word 52, the 12 view-to-world floats at word 180 (all it reads) and the pass kind. The draws of
// one cascade share one camera, so the double precision inverse ran ~3,400 times a frame for a
// handful of cameras. Matched on the bytes, so a camera rewritten in place is computed again.
bool RtShadow::R17ToWorld(const float* constants, bool perspective, std::array<float, 12>& out) {
    if (!UpkeepOn()) {
        ++r17_stats.world_computed;
        return ToWorld(constants, perspective, out);
    }
    const u32 n = u32(r17_memo.size());
    // bbport (r19_draw-cost): the memo compared with the constants where they are (the same 112
    // bytes, the same order of memos); copied only on a miss, to fill a memo.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    for (u32 i = 0; r19 && i < n; ++i) {
        const u32 at = (r17_memo_last + i) % n;
        const ToWorldMemo& memo = r17_memo[at];
        if (memo.used && memo.perspective == perspective &&
            std::memcmp(memo.in.data(), constants + 52, 16 * sizeof(float)) == 0 &&
            std::memcmp(memo.in.data() + 16, constants + 180, 12 * sizeof(float)) == 0) {
            r17_memo_last = at;
            ++r17_stats.world_reused;
            ++r19_stats.world_in_place;
            out = memo.out;
            return memo.ok;
        }
    }
    std::array<float, 28> in;
    std::memcpy(in.data(), constants + 52, 16 * sizeof(float));
    std::memcpy(in.data() + 16, constants + 180, 12 * sizeof(float));
    for (u32 i = 0; !r19 && i < n; ++i) {
        const u32 at = (r17_memo_last + i) % n;
        const ToWorldMemo& memo = r17_memo[at];
        if (memo.used && memo.perspective == perspective &&
            std::memcmp(memo.in.data(), in.data(), sizeof(in)) == 0) {
            r17_memo_last = at;
            ++r17_stats.world_reused;
            out = memo.out;
            return memo.ok;
        }
    }
    ToWorldMemo& memo = r17_memo[r17_memo_next];
    r17_memo_last = r17_memo_next;
    r17_memo_next = (r17_memo_next + 1) % n;
    memo.used = true;
    memo.perspective = perspective;
    memo.in = in;
    memo.out = {};
    memo.ok = ToWorld(constants, perspective, memo.out);
    ++r17_stats.world_computed;
    out = memo.out;
    return memo.ok;
}

bool RtShadow::InputsWanted() const {
    return capturing && UnchangedMode() != 0 && UpkeepOn();
}

u32 RtShadow::Param(u32 store, const Entry& entry) {
    if (params_used >= MaxParams) {
        return 0;
    }
    const u32 slot = u32(frame % 4);
    const u32 index = 1 + slot * MaxParams + params_used++;
    auto* param = static_cast<u32*>(params.mapped) + index * 8;
    param[0] = store;
    param[1] = 0;
    param[2] = entry.vertices;
    param[3] = Shader::MotionVectors::FlagStore;
    param[4] = entry.first_vertex;
    param[5] = entry.first_instance;
    param[6] = entry.instances;
    param[7] = 0;
    slot_ticks[slot] = scheduler.CurrentTick();
    return index;
}

std::unique_ptr<RtShadow::Entry> RtShadow::MakeEntry(const Draw& draw, u8 mask) {
    const auto device = instance.GetDevice();
    u32 lo = UINT32_MAX, hi = 0;
    const auto scan = [&]<class Index>(const Index* data) {
        const Index cut = std::numeric_limits<Index>::max();
        for (u32 i = 0; i < draw.index_count; ++i) {
            if (draw.restart && data[i] == cut) {
                continue;
            }
            lo = std::min(lo, u32(data[i]));
            hi = std::max(hi, u32(data[i]));
        }
    };
    std::vector<u32> list;
    list.reserve(std::size_t(draw.index_count) * (draw.strip ? 3 : 1));
    const void* source = reinterpret_cast<const void*>(draw.indices);
    bool good = false;
    if (draw.index_size == 2) {
        scan(static_cast<const u16*>(source));
        good = lo <= hi && AppendTriangles<u16>({static_cast<const u16*>(source), draw.index_count},
                                                draw.strip, draw.restart, lo, list);
    } else {
        scan(static_cast<const u32*>(source));
        good = lo <= hi && AppendTriangles<u32>({static_cast<const u32*>(source), draw.index_count},
                                                draw.strip, draw.restart, lo, list);
    }
    const u64 vertex_count = u64(hi - lo + 1);
    if (!good || list.empty() || list.size() / 3 * draw.instances > MaxTrianglesPerBlas ||
        vertex_count * draw.instances > MaxPositions / 4) {
        ++stats.unsupported;
        return nullptr;
    }
    const std::size_t per_instance = list.size();
    list.resize(per_instance * draw.instances);
    for (u32 i = 1; i < draw.instances; ++i) {
        for (std::size_t k = 0; k < per_instance; ++k) {
            list[i * per_instance + k] = list[k] + i * u32(vertex_count);
        }
    }
    auto entry = std::make_unique<Entry>();
    entry->first_vertex = u32(s64(lo) + s64(s32(draw.first_vertex)));
    entry->vertices = u32(vertex_count);
    entry->instances = draw.instances;
    entry->first_instance = draw.first_instance;
    entry->triangles = u32(list.size() / 3);
    entry->palette = draw.palette;
    entry->dynamic = draw.skinned;
    entry->mask = mask;
    entry->shadow = mask == ShadowMask;
    const vk::DeviceSize world_bytes = vk::DeviceSize(entry->vertices) * entry->instances * 16;
    const vk::DeviceSize world_estimate = entry->shadow && WorldCopies() ? world_bytes : 0;
    const bool scene_over = need_scene && blas_bytes + vk::DeviceSize(entry->triangles) * 64 > blas_limit;
    if (scene_over ||
        entry_bytes + vk::DeviceSize(entry->triangles) * 96 + world_estimate > MaxEntryBytes ||
        !EffectPass::HasRoom(instance, vk::DeviceSize(entry->triangles) * 96) ||
        !Make(entry->indices, list.size() * sizeof(u32), true, InputUsage)) {
        ++stats.over_budget;
        ++missed;
        return nullptr;
    }
    std::memcpy(entry->indices.mapped, list.data(), list.size() * sizeof(u32));
    vk::AccelerationStructureGeometryKHR geometry{
        .geometryType = vk::GeometryTypeKHR::eTriangles,
        .geometry = {.triangles = vk::AccelerationStructureGeometryTrianglesDataKHR{
            .vertexFormat = vk::Format::eR32G32B32Sfloat,
            .vertexStride = 16,
            .maxVertex = entry->vertices * entry->instances - 1,
            .indexType = vk::IndexType::eUint32,
        }},
        .flags = vk::GeometryFlagBitsKHR::eOpaque,
    };
    const vk::AccelerationStructureBuildGeometryInfoKHR info{
        .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
        .flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace |
                 vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate,
        .mode = vk::BuildAccelerationStructureModeKHR::eBuild,
        .geometryCount = 1,
        .pGeometries = &geometry,
    };
    auto sizes = device.getAccelerationStructureBuildSizesKHR(
        vk::AccelerationStructureBuildTypeKHR::eDevice, info, entry->triangles);
    { // bbport (r17_rt-upkeep): a shared copy's refresh builds use ePreferFastBuild alone (see
      // RecordBuilds): storage and scratch fit both flag sets, whatever the experiment bit.
        vk::AccelerationStructureBuildGeometryInfoKHR fast = info;
        fast.flags = vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastBuild;
        const auto other = device.getAccelerationStructureBuildSizesKHR(
            vk::AccelerationStructureBuildTypeKHR::eDevice, fast, entry->triangles);
        sizes.accelerationStructureSize =
            std::max(sizes.accelerationStructureSize, other.accelerationStructureSize);
        sizes.buildScratchSize = std::max(sizes.buildScratchSize, other.buildScratchSize);
    }
    entry->scratch = sizes.buildScratchSize;
    entry->update_scratch = sizes.updateScratchSize;
    entry->scene_bytes = sizes.accelerationStructureSize + list.size() * sizeof(u32);
    entry->bytes = entry->scene_bytes;
    if (!Make(entry->storage, sizes.accelerationStructureSize, false,
              VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_STORAGE_BIT_KHR)) {
        Free(entry->indices);
        ++stats.over_budget;
        ++missed;
        return nullptr;
    }
    const auto [result, handle] = device.createAccelerationStructureKHR({
        .buffer = entry->storage.buffer,
        .size = sizes.accelerationStructureSize,
        .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
    });
    if (result != vk::Result::eSuccess) {
        Free(entry->indices);
        Free(entry->storage);
        failed = true;
        return nullptr;
    }
    entry->handle = handle;
    entry->address = device.getAccelerationStructureAddressKHR({.accelerationStructure = handle});
    entry_bytes += entry->bytes;
    blas_bytes += entry->scene_bytes;
    // The shared positions buffer is reused every frame; static VSM casters keep this world copy.
    if (entry->shadow && WorldCopies()) {
        EnsureWorld(*entry);
    }
    return entry;
}

u32 RtShadow::NextOccurrence(u64 hash) {
    if (BbToggle::Experiment(2097152)) {
        return occurrences[hash]++;
    }
    for (u32 probe = 0; probe < 32; ++probe) {
        OccurrenceSlot& slot = occurrence_slots[(hash + probe) & (OccurrenceSlots - 1)];
        if (slot.epoch != occurrence_epoch) {
            slot = OccurrenceSlot{hash, occurrence_epoch, 1u};
            return 0;
        }
        if (slot.hash == hash) {
            return slot.count++;
        }
    }
    return occurrences[hash]++;
}

// bbport (r14_cascade_rt): the sun cascade of a shadow pass draw: the quadrant of the sun atlas
// (the largest square shadow target; lamp shadow maps are smaller) holding its viewport, numbered
// as SunAtlasSkipDraw does (bit 0 east, bit 1 south); 4: another target or no single quadrant.
u8 RtShadow::SunCascade(const Draw& draw) {
    atlas_side = std::max(atlas_side, draw.target);
    if (draw.target == 0 || draw.target != atlas_side) {
        return 4;
    }
    const float half = 0.5f * float(draw.target);
    const float sx = std::abs(draw.viewport[2]), sy = std::abs(draw.viewport[3]);
    const float x0 = draw.viewport[0] - sx, x1 = draw.viewport[0] + sx;
    const float y0 = draw.viewport[1] - sy, y1 = draw.viewport[1] + sy;
    if (!(x1 > x0) || !(y1 > y0)) {
        return 4;
    }
    const bool east = x0 >= half - 0.5f, south = y0 >= half - 0.5f;
    if ((!east && x1 > half + 0.5f) || (!south && y1 > half + 0.5f)) {
        return 4;
    }
    return u8((east ? 1u : 0u) | (south ? 2u : 0u));
}

// bbport (r14_cascade_rt): an entry last drawn into sun cascades none of which drew this frame
// (so far), within the window: the game left its cascade undrawn, so it still casts the sun's
// shadow. Its BLAS and world copy are the ones of its last draw (a moving caster's last pose).
// Only the four sun cascades count: a draw in no single quadrant (bit 4) is never held.
bool RtShadow::Holds(const Entry& entry) const {
    return hold_frames && entry.shadow_frame != frame &&
           frame - entry.shadow_frame <= hold_frames &&
           (entry.cascades & ~frame_cascades & 0x0f) != 0 && !entry.gone;
}

// bbport (r14_cascade_rt): the held entries not drawn this frame, as of now (entries drawn later
// in the frame move to frame_entries; cascades drawn later drop theirs).
void RtShadow::CollectHeld() {
    held_now.clear();
    for (Entry* entry : held) {
        if (entry->seen_frame != frame && Holds(*entry)) {
            held_now.push_back(entry);
        }
    }
}

// bbport (r14_cascade_rt): at the end of a frame, the entries that may be held next frame: those
// drawn into a cascade this frame, and those held this frame still inside the window. One drawn
// neither this frame nor by a cascade that drew is dropped; so is one whose cascades all drew
// without it (it left them), or that the VSM or a promotion declared gone.
void RtShadow::UpdateHeld() {
    const u32 period = BbToggle::Experiment(BbSunCascades::kOffBit)
                           ? 0u
                           : BbSunCascades::skip_period.load(std::memory_order_relaxed);
    const u64 window = period > 1 ? u64(std::min(period, MaxHoldPeriod)) - 1 + HoldMarginFrames : 0;
    for (Entry* entry : held) {
        entry->held = false;
    }
    held_next.clear();
    if (hold_frames) {
        ++hold_stats.frames;
        for (u32 c = 0; c < 5; ++c) {
            hold_stats.cascade_frames[c] += (frame_cascades >> c) & 1u;
        }
        for (Entry* entry : held) {
            if (entry->held || entry->shadow_frame == frame) {
                continue; // drawn into a cascade this frame: taken below with the frame's entries
            }
            if (!Holds(*entry)) {
                if (frame - entry->shadow_frame > hold_frames) {
                    ++hold_stats.aged;
                } else {
                    ++hold_stats.dropped;
                }
                continue;
            }
            if (entry->seen_frame == frame) {
                ++hold_stats.lent; // drawn by the camera pass only: kept in the sun's ray mask
            } else {
                ++hold_stats.kept;
            }
            if (frame + 1 - entry->shadow_frame > window) {
                ++hold_stats.aged;
                continue;
            }
            entry->held = true;
            held_next.push_back(entry);
        }
        if (window) {
            for (Entry* entry : frame_entries) {
                if (!entry->held && entry->shadow_frame == frame && (entry->cascades & 0x0f)) {
                    entry->held = true;
                    held_next.push_back(entry);
                }
            }
        }
    }
    std::swap(held, held_next);
    held_next.clear();
    held_now.clear();
    if (hold_frames && frame % 600 == 0 && hold_stats.frames) {
        const double f = double(hold_stats.frames);
        std::printf("Ray tracing held sun casters (r14): skip period %u, held up to %llu frames "
                    "undrawn; %.1f entries kept a frame, %.1f more drawn by the camera pass only "
                    "kept in the sun's mask; %llu dropped (their cascades drawn without them, or "
                    "gone) and %llu aged out since the last line; %zu held now; frames with draws "
                    "in c0 %llu c1 %llu c2 %llu c3 %llu, in no single quadrant %llu, of %llu\n",
                    period, static_cast<unsigned long long>(window), double(hold_stats.kept) / f,
                    double(hold_stats.lent) / f,
                    static_cast<unsigned long long>(hold_stats.dropped),
                    static_cast<unsigned long long>(hold_stats.aged), held.size(),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[0]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[1]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[2]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[3]),
                    static_cast<unsigned long long>(hold_stats.cascade_frames[4]),
                    static_cast<unsigned long long>(hold_stats.frames));
        hold_stats = {};
    }
    if (!window) {
        hold_stats = {};
    }
    hold_frames = window;
    frame_cascades = 0;
}

u32 RtShadow::PrepareDraw(const Draw& draw) {
    // bbport (r19_draw-cost): experiment 17592186044416 clear: the short paths marked r19 below,
    // each giving what the old code computes from the same inputs; set: the old code.
    const bool r19 = !BbToggle::Experiment(R19DrawCostOffBit);
    if (r19 && draw.r19_wanted) {
        ++r19_stats.wanted_skipped;
    } else if (!Wanted()) {
        return 0;
    }
    if (!draw.shadow_pass && !draw.camera_pass) {
        return 0;
    }
    r19_stats.calls += r19 ? 1u : 0u;
    // bbport (r14_cascade_rt): with sun cascades left undrawn on some frames, the cascade of each
    // shadow pass draw and the cascades drawn this frame, learned from the draws that arrive (the
    // game thread runs frames ahead: its schedule is not assumed).
    u8 cascade = 4;
    if (hold_frames && draw.shadow_pass) {
        cascade = SunCascade(draw);
        frame_cascades |= u8(1u << cascade);
    }
    // The mesh without its shader: the camera pass and the shadow pass draw it with different
    // ones, and only the camera pass shows whether its pixel shader cuts the surface out.
    // bbport (r19_draw-cost): the mesh hash is made only where it is read (a camera pass cut-out,
    // a new entry); the old path makes it for every draw.
    const auto mesh_of = [&] {
        r19_stats.mesh_made += r19 ? 1u : 0u;
        const std::array<u64, 4> mesh_parts{draw.geometry, draw.indices, draw.index_count,
                                            draw.first_vertex};
        return XXH3_64bits(mesh_parts.data(), sizeof(mesh_parts));
    };
    const u64 mesh = r19 ? 0 : mesh_of();
    if (draw.camera_pass && draw.alpha) {
        if (cutout_meshes.size() >= 65536) {
            cutout_meshes.clear();
        }
        cutout_meshes.insert(r19 ? mesh_of() : mesh);
    }

    // Camera pass casters only serve the ray traced scene (lamp shadows, bounced light).
    if (draw.camera_pass && !need_scene) {
        return 0;
    }
    draw.camera_pass ? ++stats.camera_draws : ++stats.draws;
    if (!draw.solid) {
        return 0;
    }
    // Sun shadow shaders discard even for opaque casters; camera-pass characters also need
    // their cut-out geometry in the ray traced scene.
    if (draw.alpha) {
        const bool character = draw.skinned || draw.palette != 0;
        if (character) {
            ++stats.cut_characters;
        } else {
            ++stats.alpha;
        }
        if (!draw.shadow_pass && !character) {
            return 0;
        }
    }
    if (!draw.constants) {
        ++stats.no_camera;
        return 0;
    }
    std::array<float, 12> to_world{};
    if (!R17ToWorld(draw.constants, draw.camera_pass, to_world)) { // bbport (r17_rt-upkeep)
        ++stats.not_ortho;
        return 0;
    }
    if (!draw.triangles || !draw.indices || draw.instances == 0 ||
        draw.instances > MaxInstancesPerDraw) {
        draw.instances > MaxInstancesPerDraw ? ++stats.instanced : ++stats.unsupported;
        return 0;
    }
    stats.strips += draw.strip ? 1 : 0;
    const u8 mask = draw.camera_pass ? CameraMask : ShadowMask;
    u64 key;
    if (draw.positions) {
        const std::array<u64, 4> mesh{draw.positions, draw.indices,
                                      (u64(draw.index_count) << 32) | draw.first_vertex,
                                      draw.instances};
        key = XXH3_64bits(mesh.data(), sizeof(mesh));
    } else {
        key = draw.geometry ^ (draw.shader * 0x9e3779b97f4a7c15ull);
        key = XXH3_64bits_withSeed(&draw.indices, sizeof(draw.indices), key);
        const std::array<u32, 4> parts{draw.index_count, draw.first_vertex, draw.instances,
                                       draw.camera_pass ? 1u : 0u};
        key = XXH3_64bits_withSeed(parts.data(), sizeof(parts), key);
    }

    // bbport (r14_cascade_rt): a shadow pass draw's copies are known by its cascade, not by the
    // order its camera arrived in this frame (which shifts when an earlier cascade is not drawn);
    // far above any index of frame_cameras, which the other draws still use.
    u32 camera_index = cascade < 4 ? 0x80000000u + cascade : 0u;
    // bbport (r19_draw-cost): the draws of one pass share their constants: the last draw's index
    // when frame_cameras holds the same pointer there. A pointer is in frame_cameras once (pushed
    // only when the scan does not find it, cleared only at the frame's end): the scan stops there.
    if (cascade >= 4 && r19 && r19_camera_last < frame_cameras.size() &&
        frame_cameras[r19_camera_last] == draw.constants) {
        camera_index = r19_camera_last;
        ++r19_stats.camera_cached;
    } else {
        for (; cascade >= 4 && camera_index < frame_cameras.size(); ++camera_index) {
            if (frame_cameras[camera_index] == draw.constants) {
                break;
            }
        }
        if (cascade >= 4 && camera_index == frame_cameras.size()) {
            frame_cameras.push_back(draw.constants);
        }
    }
    if (cascade >= 4) {
        r19_camera_last = camera_index;
    }
    // A small bone palette holds world space bones, so with the mesh key it identifies one
    // object in one pose whatever the camera or the draw order: a prop seen unchanged on three
    // frames gets an entry of its own, so the game drawing other instances first, or not drawing
    // this one, neither re-captures it nor makes it look moving.
    const bool palette_draw = draw.palette != 0 && !draw.skinned;
    u64 instance_key = 0;
    bool instance_entry = false;
    bool promote = false;
    if (palette_draw) {
        instance_key = XXH3_64bits_withSeed(&draw.palette, sizeof(draw.palette), key ^ 0xa24baed4963ee407ull);
        instance_entry = entries.contains(instance_key);
        if (!instance_entry) {
            if (candidates.size() >= MaxCandidates) {
                candidates.clear();
            }
            auto& candidate = candidates[instance_key];
            if (candidate.last != frame + 1) {
                candidate.last = frame + 1;
                ++candidate.frames;
            }
            promote = candidate.frames >= PromoteFrames && new_triangles < NewTrianglesPerFrame;
        }
    }
    u64 entry_key = key;
    bool shared = false;
    // bbport (r19_draw-cost): the memo slot of a draw without a palette (never an instance entry,
    // never promoted: its entry_key is `key` unless shared), see R19EntryMemo.
    R19EntryMemo* r19_memo = nullptr;
    if (!instance_entry) {
        const std::array<u64, 2> occurrence_key{key, camera_index};
        const u64 occurrence_hash = XXH3_64bits(occurrence_key.data(), sizeof(occurrence_key));
        const u32 occurrence = NextOccurrence(occurrence_hash);
        if (occurrence > 0) {
            shared_keys.insert(key);
        }
        if (r19 && !palette_draw) {
            r19_memo = &r19_entry_memo[key & (R19EntryMemos - 1)];
        }
        if (r19 && occurrence > 0) {
            shared = true; // in the set: inserted just above
            ++r19_stats.shared_known;
        } else if (r19_memo && r19_memo->entry && r19_memo->key == key &&
                   r19_memo->shared_size == shared_keys.size()) {
            shared = false; // not in it when the memo was filled; an insert-only set of the same
            ++r19_stats.shared_memo; // size is the same set
        } else {
            shared = shared_keys.contains(key);
        }
        if (shared) {
            const std::array<u64, 3> copy{key, camera_index, occurrence};
            entry_key = XXH3_64bits(copy.data(), sizeof(copy));
        }
        if (promote) {
            // The draw order entry of this very instance, when unchanged, becomes the instance's.
            if (auto old = entries.find(entry_key);
                old != entries.end() && old->second && !old->second->dynamic &&
                old->second->palette == draw.palette &&
                old->second->mask == (draw.camera_pass ? CameraMask : ShadowMask)) {
                auto adopted = std::move(old->second);
                entries.erase(old);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                adopted->rebuilt = false;
                adopted->instance = true;
                entries[instance_key] = std::move(adopted);
                ++stats.promoted;
            }
            instance_entry = true;
            entry_key = instance_key;
            shared = false;
            const std::array<u64, 3> retired{key, draw.palette, draw.camera_pass ? 1u : 0u};
            promoted_now.insert(XXH3_64bits(retired.data(), sizeof(retired)));
        }
    } else {
        entry_key = instance_key;
    }

    // bbport (r19_draw-cost): a plain draw whose key's Entry is in its memo slot with no erase or
    // move in `entries` since: the Entry that entries[key] holds.
    Entry* r19_entry = nullptr;
    if (r19_memo && !shared && r19_memo->entry && r19_memo->key == key &&
        r19_memo->entries_gen == r19_entries_gen) {
        r19_entry = r19_memo->entry;
        ++r19_stats.entry_memo;
    }
    if (!r19_entry) {
        auto& slot = entries[entry_key];
        if (!slot) {
            if (new_triangles >= NewTrianglesPerFrame) {
                ++stats.over_budget;
                ++missed;
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            // bbport (r26_upkeep-probe): BLAS and TLAS frozen: no new caster (nothing would
            // build it, the TLAS traced as it was would not hold it), so no memory is taken.
            if (r26_freeze == 3u) {
                ++r26_stats.left_out;
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            slot = MakeEntry(draw, mask);
            if (!slot) {
                entries.erase(entry_key);
                ++r19_entries_gen; // bbport (r19_draw-cost)
                return 0;
            }
            slot->rebuilt = shared;
            slot->mesh = r19 ? mesh_of() : mesh;
            slot->base = key;
            slot->instance = instance_entry;
            slot->rebuild_every = RebuildEveryFrames + u32(entry_key % RebuildSpread);
            stats.promoted += promote ? 1 : 0;
        }
        r19_entry = slot.get();
        if (r19_memo && !shared) { // entry_key == key here
            *r19_memo = {key, r19_entry, r19_entries_gen, u64(shared_keys.size())};
            ++r19_stats.entry_filled;
        }
    }
    Entry& entry = *r19_entry;
    if (hold_frames && draw.shadow_pass) { // bbport (r14_cascade_rt): see Holds
        if (entry.shadow_frame != frame) {
            entry.shadow_frame = frame;
            entry.cascades = 0;
        }
        entry.cascades |= u8(1u << cascade);
    }
    // bbport (r17_rt-upkeep): a draw in sun cascade c2/c3 is far; any other (camera pass, c0/c1,
    // not the atlas) is near. A moving caster's first draw this frame is "far only" when it is
    // far and the caster had no near draw last frame (BB_RT_REFIT_EVERY, its counters).
    // bbport (r19_draw-cost, r37_menu-options): with RefitEvery() 0 (BB_RT_REFIT_EVERY and
    // graphics_rt_far_refit, read at each use) r17_far only feeds the far_refit counters and
    // r17_near_frame only r17_far: neither is kept up then (turned on while running: RefitEvery).
    // SunCascade's learning of the atlas side (r14) is kept.
    const bool r19_far_book = !r19 || RefitEvery() != 0;
    u8 r17_cascade = 4;
    if (draw.shadow_pass) {
        if (cascade < 4) {
            r17_cascade = cascade;
        } else if (r19_far_book) {
            r17_cascade = SunCascade(draw);
        } else {
            atlas_side = std::max(atlas_side, draw.target);
            ++r19_stats.far_book_skipped;
        }
    }
    const bool r17_far_draw =
        r19_far_book && draw.shadow_pass && (r17_cascade == 2 || r17_cascade == 3);
    const bool r17_far =
        r17_far_draw && entry.seen_frame != frame && entry.r17_near_frame + 1 < frame;
    if (!r17_far_draw && r19_far_book) {
        entry.r17_near_frame = frame;
    }
    if (entry.seen_frame == frame) {
        if ((entry.mask & mask) == 0) {
            entry.mask |= mask;
            tlas_count = 0;
            ++stats.merged;
        }
        return 0;
    }
    entry.mask = mask;
    // Drawn by the game again: the object is back.
    entry.gone = false;
    entry.gone_streak = 0;
    if (mask == ShadowMask) {
        entry.shadow_card = draw.textured;
        entry.shadow = true;
        if (WorldCopies()) {
            EnsureWorld(entry);
        }
    }
    entry.rebuilt = entry.rebuilt || shared;
    if (entry.palette != draw.palette) {
        entry.palette = draw.palette;
        entry.dynamic = true;
    }
    const bool needs_data = !entry.built || entry.dynamic || entry.rebuilt ||
                            (need_scene && !entry.blas) ||
                            (entry.shadow && entry.world.buffer && !entry.copied &&
                             WorldCopies());
    // Over budget, a caster built before keeps last frame's BLAS and world copy (exact for static
    // props drawn several times, a frame late for moving ones) rather than vanishing.
    const auto skip = [&] {
        ++stats.over_budget;
        if (!entry.built) {
            ++missed;
            return 0u;
        }
        entry.seen_frame = frame;
        frame_entries.push_back(&entry);
        return 0u;
    };
    u32 param = 0;
    if (needs_data) {
        const bool update = need_scene && entry.blas && entry.built && !entry.rebuilt &&
                            frame - entry.built_frame < entry.rebuild_every &&
                            entry.r17_updatable; // bbport (r17_rt-upkeep): not fast-built
        // bbport (r17_rt-upkeep): opt-in refit skips of moving casters, keeping the BLAS (as the
        // over-budget skip does). BB_RT_UNCHANGED=skip: what the vertex shader reads hashes the
        // same as for the capture the BLAS holds. BB_RT_REFIT_EVERY: far only, refit recently.
        if (update && entry.dynamic) {
            const bool on = UpkeepOn();
            const auto keep = [&] {
                entry.seen_frame = frame;
                frame_entries.push_back(&entry);
                return 0u;
            };
            if (draw.inputs != 0 && draw.inputs == entry.r17_inputs) {
                if (on && UnchangedMode() == 2) {
                    ++r17_stats.same_skipped;
                    r17_stats.same_skipped_triangles += entry.triangles;
                    return keep();
                }
                ++r17_stats.same_would;
                r17_stats.same_would_triangles += entry.triangles;
            } else if (draw.inputs == 0 && on && UnchangedMode() != 0) {
                ++r17_stats.same_unknown;
            }
            if (r17_far) {
                const u32 every = RefitEvery();
                if (on && every > 1 && frame - entry.r17_capture_frame < every) {
                    ++r17_stats.far_skipped;
                    r17_stats.far_skipped_triangles += entry.triangles;
                    return keep();
                }
                ++r17_stats.far_refit;
                r17_stats.far_refit_triangles += entry.triangles;
            }
        }
        const bool refresh = entry.rebuilt && entry.built;
        // With no ray tracing scene nothing is built: a caster captured before is only captured
        // again, which must not use up the budget that lets new casters in.
        const bool recapture = !need_scene && entry.built && !refresh;
        const u64 stored = u64(entry.vertices) * entry.instances;
        const u64 needed = need_scene ? (update ? entry.update_scratch : entry.scratch) + 256 : 0;
        const bool over = refresh ? rebuilt_triangles >= RebuiltBudget()
                                  : !update && !recapture && new_triangles >= NewTrianglesPerFrame;
        if (positions_used + stored > MaxPositions || scratch_used + needed > ScratchBytes || over) {
            return skip();
        }
        // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE with BLAS work frozen: this refit or
        // build is left out. A caster with a BLAS keeps it as it is, as skip() does (no capture
        // param, positions or scratch); with the TLAS frozen too, one without stays out of this
        // frame (the TLAS traced as it was could not hold it).
        if (r26_freeze != 0) {
            if ((r26_freeze & 1u) && entry.built && entry.blas) {
                // Counted as today's cadence would record it: a kept BLAS ages past its rebuild
                // window only because of the freeze, and today it is refit on every frame but
                // each rebuild_every-th (where it is built again).
                const bool refit =
                    update || (entry.r17_updatable && !entry.rebuilt &&
                               (frame - entry.built_frame) % entry.rebuild_every != 0);
                if (refit) {
                    ++r26_stats.refits_left;
                    r26_stats.refit_triangles += entry.triangles;
                } else {
                    ++r26_stats.builds_left;
                    r26_stats.build_triangles += entry.triangles;
                }
                entry.seen_frame = frame;
                frame_entries.push_back(&entry);
                return 0;
            }
            if (r26_freeze == 3u) {
                ++r26_stats.left_out;
                return 0;
            }
            ++r26_stats.recorded;
        }
        param = Param(positions_used, entry);
        if (!param) {
            return skip();
        }
        builds.push_back({&entry, positions_used, update, to_world});
        stats.refit_triangles += update ? entry.triangles : 0;
        // bbport (r17_rt-upkeep): a shared copy's refresh (never refit) is built for speed
        builds.back().fast = UpkeepOn() && refresh;
        builds.back().inputs = draw.inputs;
        positions_used += u32(stored);
        scratch_used += needed;
        if (!update) {
            if (refresh) {
                rebuilt_triangles += entry.triangles;
                ++stats.shared_builds;
            } else if (!recapture) {
                new_triangles += entry.triangles;
            }
            if (need_scene) {
                stats.built_triangles += entry.triangles;
            }
        }
        if (!update) {
            entry.built_frame = frame;
        }
        stats.dynamic_draws += entry.dynamic ? 1 : 0;
    }
    entry.seen_frame = frame;
    frame_entries.push_back(&entry);
    return param;
}

void RtShadow::RecordBuilds() {
    if (builds.empty()) {
        return;
    }
    BB_SECTION(RtBuilds);
    const bool world_copies = WorldCopies();
    if (need_scene) {
        r17_blas_dirty = true; // bbport (r17_rt-upkeep): the TLAS cannot be skipped
    }
    struct Job {
        std::vector<vk::AccelerationStructureGeometryKHR> geometries;
        std::vector<vk::AccelerationStructureBuildGeometryInfoKHR> infos;
        std::vector<vk::AccelerationStructureBuildRangeInfoKHR> ranges;
        std::vector<const vk::AccelerationStructureBuildRangeInfoKHR*> pointers;
        std::vector<UnprojectPush> unproject;
        std::vector<std::pair<vk::Buffer, vk::BufferCopy>> copies;
    };
    auto job = std::make_shared<Job>();
    job->geometries.reserve(builds.size());
    job->ranges.reserve(builds.size());
    job->unproject.reserve(builds.size());
    u64 scratch_at = 0;
    const auto align = [&](u64 v) { return (v + scratch_align - 1) / scratch_align * scratch_align; };
    for (const Build& build : builds) {
        Entry& e = *build.entry;
        job->unproject.push_back({build.to_world, build.store, e.vertices * e.instances});
        e.built = true;
        e.blas = need_scene;
        // bbport (r17_rt-upkeep): what the BLAS now holds and how it was built
        e.r17_inputs = need_scene ? build.inputs : 0;
        if (need_scene) {
            e.r17_updatable = !build.fast;
            e.r17_capture_frame = frame; // BB_RT_REFIT_EVERY: the BLAS holds this frame's pose
            if (build.update) {
                ++r17_stats.refit;
                r17_stats.refit_triangles += e.triangles;
            } else {
                ++r17_stats.rebuilt;
                r17_stats.rebuilt_triangles += e.triangles;
                r17_stats.fast += build.fast ? 1 : 0;
                r17_stats.fast_triangles += build.fast ? e.triangles : 0;
            }
        }
        const vk::DeviceSize world_bytes = vk::DeviceSize(e.vertices) * e.instances * 16;
        ++world_copy_stats.builds;
        if (e.world.buffer && world_copies) {
            job->copies.push_back({e.world.buffer,
                                   vk::BufferCopy{u64(build.store) * 16, 0, world_bytes}});
            e.copied = true;
            e.copied_at = ++copies;
            ++world_copy_stats.copies;
            world_copy_stats.bytes += world_bytes;
        } else {
            // A copy made before the VSM was switched off is stale from now on: turning it back
            // on recaptures this caster (PrepareDraw's needs_data).
            if (e.world.buffer) {
                e.copied = false;
            }
            if (e.shadow) {
                ++world_copy_stats.skipped;
                world_copy_stats.skipped_bytes += world_bytes;
            }
        }
        if (!need_scene) {
            continue;
        }
        job->geometries.push_back({
            .geometryType = vk::GeometryTypeKHR::eTriangles,
            .geometry = {.triangles = vk::AccelerationStructureGeometryTrianglesDataKHR{
                .vertexFormat = vk::Format::eR32G32B32Sfloat,
                .vertexData = {.deviceAddress = positions.address + u64(build.store) * 16},
                .vertexStride = 16,
                .maxVertex = e.vertices * e.instances - 1,
                .indexType = vk::IndexType::eUint32,
                .indexData = {.deviceAddress = e.indices.address},
            }},
            .flags = vk::GeometryFlagBitsKHR::eOpaque,
        });
        job->infos.push_back({
            .type = vk::AccelerationStructureTypeKHR::eBottomLevel,
            // bbport (r17_rt-upkeep): a shared copy's refresh: rebuilt next time, never refit
            .flags = build.fast ? vk::BuildAccelerationStructureFlagsKHR(
                                      vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastBuild)
                                : vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace |
                                      vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate,
            .mode = build.update ? vk::BuildAccelerationStructureModeKHR::eUpdate
                                 : vk::BuildAccelerationStructureModeKHR::eBuild,
            .srcAccelerationStructure = build.update ? e.handle : vk::AccelerationStructureKHR{},
            .dstAccelerationStructure = e.handle,
            .geometryCount = 1,
            .pGeometries = &job->geometries.back(),
            .scratchData = {.deviceAddress = scratch.address + scratch_at},
        });
        scratch_at += align(build.update ? e.update_scratch : e.scratch);
        if (BbSpike::on && !build.update) { // bbport (r23_spike-trace)
            BbSpike::rt_builds.fetch_add(1, std::memory_order_relaxed);
            BbSpike::rt_build_triangles.fetch_add(e.triangles, std::memory_order_relaxed);
        }
        job->ranges.push_back({.primitiveCount = e.triangles});
        job->pointers.push_back(&job->ranges.back());
    }
    builds.clear();
    positions_used = 0;
    scratch_used = 0;
    if (frame >= world_copy_stats.printed_frame + 600) {
        std::printf("Ray tracing world copies: %llu builds, %llu copied (%.1f MB), %llu sun shadow "
                    "builds not copied (%.1f MB) since the last line; copies %s (sun VSM %s, "
                    "experiment 16777216 %s)\n",
                    static_cast<unsigned long long>(world_copy_stats.builds),
                    static_cast<unsigned long long>(world_copy_stats.copies),
                    double(world_copy_stats.bytes) / 1048576.0,
                    static_cast<unsigned long long>(world_copy_stats.skipped),
                    double(world_copy_stats.skipped_bytes) / 1048576.0,
                    world_copies ? "on" : "off",
                    BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed) ? "on" : "off",
                    BbToggle::Experiment(16777216) ? "set" : "clear");
        world_copy_stats = {};
        world_copy_stats.printed_frame = frame;
    }
    // bbport: its own row in the GPU profile (BB_GPU_PROFILE=1); before, its time went to the
    // pass recorded before it (with the ray traced sun: the game's shadow blur, ps 11ffdfb5).
    EffectPass::Mark(16, "ray tracing geometry");
    scheduler.RecordCrumb(
        {.name = "Ray tracing geometry"},
        [job, positions = positions.buffer, unproject_pipeline = *unproject_pipeline,
         unproject_layout = *unproject_layout](vk::CommandBuffer cmdbuf) {
            EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eAllCommands, vk::AccessFlagBits2::eMemoryWrite, Compute,
                   vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            const vk::DescriptorBufferInfo position_info{positions, 0, VK_WHOLE_SIZE};
            const vk::WriteDescriptorSet write{.dstBinding = 0,
                                               .descriptorCount = 1,
                                               .descriptorType = vk::DescriptorType::eStorageBuffer,
                                               .pBufferInfo = &position_info};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, unproject_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, unproject_layout, 0, write);
            for (const UnprojectPush& push : job->unproject) {
                cmdbuf.pushConstants(unproject_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push),
                                     &push);
                cmdbuf.dispatch((push.count + 63) / 64, 1, 1);
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                   AsBuild | vk::PipelineStageFlagBits2::eCopy,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR |
                       vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eTransferRead);
            if (!job->infos.empty()) {
                cmdbuf.buildAccelerationStructuresKHR(job->infos, job->pointers);
            }
            for (const auto& [dst, region] : job->copies) {
                cmdbuf.copyBuffer(positions, dst, region);
            }
            if (!job->copies.empty()) {
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy, vk::AccessFlagBits2::eTransferWrite,
                       Compute | vk::PipelineStageFlagBits2::eVertexShader,
                       vk::AccessFlagBits2::eShaderRead);
            }
            EffectPass::MemoryBarrier(cmdbuf, AsBuild, vk::AccessFlagBits2::eAccelerationStructureWriteKHR, AsBuild,
                   vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                       vk::AccessFlagBits2::eAccelerationStructureWriteKHR);
        });
    tlas_count = 0;
}

bool RtShadow::SceneWanted() const {
    if (!RayTracing()) {
        return false;
    }
    const auto& s = BbSettings::Get();
    return SunRayTraced() || s.graphics_rt_point_shadows.load(std::memory_order_relaxed) ||
           (s.graphics_rt_bounce.load(std::memory_order_relaxed) &&
            !(s.graphics_gi_probes.load(std::memory_order_relaxed) &&
              s.effects[BbSettings::EffectGi].load(std::memory_order_relaxed)));
}

bool RtShadow::PrepareCapture() {
    if (!Wanted()) {
        return false;
    }
    RecordBuilds();
    return Complete() && camera_motion.PassMatrices().valid;
}

bool RtShadow::PrepareScene() {
    if (!need_scene || !PrepareCapture()) {
        return false;
    }
    const auto camera = camera_motion.PassMatrices();
    // bbport (r14_cascade_rt): after the drawn entries, those held for cascades not drawn (none
    // when off); rebuilt too when entries moved from held to drawn or a cascade's draws arrived.
    CollectHeld();
    const u32 count = std::min<u32>(u32(frame_entries.size() + held_now.size()), MaxInstances);
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE with the TLAS frozen: the TLAS last built
    // is traced as it is (no records, no build; the BLAS it holds stay alive, see R26FrameEnd).
    // BLAS builds recorded since (=tlas) get the barrier the TLAS build would have given the
    // tracing. BLAS work frozen alone (=blas): the TLAS is built or refit as whenever a BLAS
    // changed (every frame today), so that only the BLAS work is left out.
    if ((r26_freeze & 2u) && r26_tlas_built) {
        if (tlas_count == 0) {
            stats.instances += count;
            ++stats.frames;
            ++r26_stats.tlas_kept;
            if ((r26_freeze & 1u) == 0) {
                scheduler.Record([](vk::CommandBuffer cmdbuf) {
                    const vk::MemoryBarrier2 after{
                        .srcStageMask = AsBuild,
                        .srcAccessMask = vk::AccessFlagBits2::eAccelerationStructureWriteKHR,
                        .dstStageMask = Compute,
                        .dstAccessMask = vk::AccessFlagBits2::eAccelerationStructureReadKHR};
                    cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
                });
            }
        }
        tlas_count = count;
        r26_tlas_kept = true;
        return true;
    }
    if (r26_freeze == 1u) {
        r17_blas_dirty = true;
    }
    if (count == tlas_count && (!hold_frames || (tlas_drawn == frame_entries.size() &&
                                                 tlas_cascades == frame_cascades))) {
        return true;
    }
    tlas_drawn = frame_entries.size();
    // bbport (r26_upkeep-probe): from here the TLAS is built, refit or found the same as last
    // built: it holds only entries of this frame, so it may later be traced as it is.
    r26_tlas_built = true;
    ++r26_stats.tlas_prepared;
    tlas_cascades = frame_cascades;
    const u32 slot = u32(frame % 4);
    auto* ring = static_cast<vk::AccelerationStructureInstanceKHR*>(instance_data.mapped) +
                 slot * MaxInstances;
    // bbport (r17_rt-upkeep): the records go to a CPU list first, to compare with the last TLAS's
    const bool upkeep = UpkeepOn();
    if (upkeep) {
        r17_records.resize(count);
    }
    auto* out = upkeep ? r17_records.data() : ring;
    u64 triangles = 0;
    // Entries kept stale over budget since the scene was last skipped have no BLAS yet.
    u32 built = 0;
    for (u32 i = 0; i < count; ++i) {
        // bbport (r14_cascade_rt): a held entry, or a held one drawn only by the camera pass while
        // its cascades are not drawn, keeps casting the sun's shadow (rt_shadow.comp's ray mask 1).
        // Not held (dropped: its cascade drew without it): the camera pass's mask only, as before.
        const bool kept = i >= frame_entries.size();
        const Entry* entry = kept ? held_now[i - frame_entries.size()] : frame_entries[i];
        if (!entry->blas) {
            continue;
        }
        const bool card = entry->shadow_card && !entry->dynamic;
        const u8 mask =
            kept ? ShadowMask
                 : u8(entry->mask | (entry->held && Holds(*entry) ? ShadowMask : 0));
        vk::AccelerationStructureInstanceKHR record{
            .mask = u8(mask | (card ? 0 : LampMask)),
            .accelerationStructureReference = entry->address,
        };
        std::memcpy(&record.transform, camera.view.data(), sizeof(camera.view));
        out[built++] = record;
        triangles += entry->triangles;
    }
    if (tlas_count == 0) {
        stats.instances += count;
        stats.triangles += triangles;
        ++stats.frames;
    }
    tlas_count = count;
    // bbport (r17_rt-upkeep): nothing changed since the TLAS was last built or refit (no BLAS
    // build or refit recorded since, the same records byte for byte): it is left as it is. Only
    // transforms and BLAS contents changed (same references, masks, flags and count): refit.
    auto tlas_mode = vk::BuildAccelerationStructureModeKHR::eBuild;
    vk::BuildAccelerationStructureFlagsKHR tlas_flags =
        vk::BuildAccelerationStructureFlagBitsKHR::ePreferFastTrace;
    if (upkeep) {
        constexpr std::size_t Transform = sizeof(vk::TransformMatrixKHR);
        constexpr std::size_t Record = sizeof(vk::AccelerationStructureInstanceKHR);
        bool same_refs = r17_tlas_valid && r17_tlas_records.size() == built;
        bool same_all = same_refs;
        for (u32 i = 0; same_refs && i < built; ++i) {
            const auto* a = reinterpret_cast<const char*>(&r17_records[i]);
            const auto* b = reinterpret_cast<const char*>(&r17_tlas_records[i]);
            same_refs = std::memcmp(a + Transform, b + Transform, Record - Transform) == 0;
            same_all = same_refs && same_all && std::memcmp(a, b, Transform) == 0;
        }
        if (same_all && !r17_blas_dirty) {
            ++r17_stats.tlas_skipped;
            return true;
        }
        tlas_flags |= vk::BuildAccelerationStructureFlagBitsKHR::eAllowUpdate;
        if (same_refs && built > 0 && r17_tlas_age < TlasRefitsBetweenBuilds) {
            tlas_mode = vk::BuildAccelerationStructureModeKHR::eUpdate;
            ++r17_tlas_age;
            ++r17_stats.tlas_updated;
        } else {
            r17_tlas_age = 0;
            ++r17_stats.tlas_built;
            if (BbSpike::on) { // bbport (r23_spike-trace)
                BbSpike::tlas_builds.fetch_add(1, std::memory_order_relaxed);
            }
        }
        std::memcpy(ring, r17_records.data(), std::size_t(built) * Record);
        r17_tlas_records.assign(r17_records.begin(), r17_records.begin() + built);
        r17_tlas_valid = true;
    } else {
        r17_tlas_valid = false;
        ++r17_stats.tlas_built;
    }
    r17_blas_dirty = false;
    slot_ticks[slot] = scheduler.CurrentTick();
    const u64 instances_address =
        instance_data.address + u64(slot) * MaxInstances * sizeof(vk::AccelerationStructureInstanceKHR);
    EffectPass::Mark(17, "ray tracing scene"); // bbport: as in RecordBuilds
    scheduler.RecordCrumb(
        {.name = "Ray tracing scene"},
        [count = built, instances_address, tlas = tlas, tlas_mode, tlas_flags, // r17_rt-upkeep
         tlas_scratch = tlas_scratch.address](vk::CommandBuffer cmdbuf) {
            const vk::AccelerationStructureGeometryKHR geometry{
                .geometryType = vk::GeometryTypeKHR::eInstances,
                .geometry = {.instances = vk::AccelerationStructureGeometryInstancesDataKHR{
                    .data = {.deviceAddress = instances_address}}},
                .flags = vk::GeometryFlagBitsKHR::eOpaque,
            };
            const vk::AccelerationStructureBuildGeometryInfoKHR info{
                .type = vk::AccelerationStructureTypeKHR::eTopLevel,
                .flags = tlas_flags, // bbport (r17_rt-upkeep): eAllowUpdate unless experiment set
                .mode = tlas_mode,
                .srcAccelerationStructure = tlas_mode == vk::BuildAccelerationStructureModeKHR::eUpdate
                                                ? tlas
                                                : vk::AccelerationStructureKHR{},
                .dstAccelerationStructure = tlas,
                .geometryCount = 1,
                .pGeometries = &geometry,
                .scratchData = {.deviceAddress = tlas_scratch},
            };
            const vk::AccelerationStructureBuildRangeInfoKHR range{.primitiveCount = count};
            const vk::AccelerationStructureBuildRangeInfoKHR* range_pointer = &range;
            const vk::MemoryBarrier2 before{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = AsBuild,
                .dstAccessMask = vk::AccessFlagBits2::eAccelerationStructureReadKHR |
                                 vk::AccessFlagBits2::eAccelerationStructureWriteKHR};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &before});
            cmdbuf.buildAccelerationStructuresKHR(info, range_pointer);
            const vk::MemoryBarrier2 after{.srcStageMask = AsBuild,
                                           .srcAccessMask =
                                               vk::AccessFlagBits2::eAccelerationStructureWriteKHR,
                                           .dstStageMask = Compute,
                                           .dstAccessMask =
                                               vk::AccessFlagBits2::eAccelerationStructureReadKHR};
            cmdbuf.pipelineBarrier2({.memoryBarrierCount = 1, .pMemoryBarriers = &after});
        });
    return true;
}

bool RtShadow::MakeRaw(u32 width, u32 height) {
    if (raw_image && raw_width == width && raw_height == height) {
        return true;
    }
    const auto device = instance.GetDevice();
    const auto allocator = instance.GetAllocator();
    if (raw_image) {
        scheduler.DeferOperation([device, allocator, image = raw_image, memory = raw_allocation,
                                  view = raw_view] {
            device.destroyImageView(view);
            vmaDestroyImage(allocator, image, memory);
        });
        raw_image = vk::Image{};
        raw_view = vk::ImageView{};
    }
    const VkImageCreateInfo image_ci{
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8_UNORM,
        .extent = {width, height, 1},
        .mipLevels = 1,
        .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_SAMPLED_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    const VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE};
    VkImage raw{};
    if (vmaCreateImage(allocator, &image_ci, &alloc_ci, &raw, &raw_allocation, nullptr) != VK_SUCCESS) {
        return false;
    }
    raw_image = raw;
    const auto [result, view] = device.createImageView({
        .image = raw_image,
        .viewType = vk::ImageViewType::e2D,
        .format = vk::Format::eR8Unorm,
        .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
    });
    if (result != vk::Result::eSuccess) {
        return false;
    }
    raw_view = view;
    raw_width = width;
    raw_height = height;
    return true;
}

bool RtShadow::Record(const Inputs& in) {
    if (!(need_scene ? PrepareScene() : PrepareCapture()) || !MakeRaw(in.width, in.height)) {
        return false;
    }
    if (!need_scene) {
        stats.instances += frame_entries.size();
        ++stats.frames;
    }
    bool use_vsm = false;
    if (BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed)) {
        if (!vsm_tried) {
            vsm_tried = true;
            vsm = std::make_unique<SunVsm>(instance, scheduler);
        }
        const auto camera = camera_motion.PassMatrices();
        if (vsm && vsm->Ready() && camera.valid) {
            auto& casters = vsm_casters;
            casters.clear();
            casters.reserve(frame_entries.size());
            // bbport (r14_cascade_rt): entries held for cascades not drawn this frame are casters
            // as if drawn (moving ones in their last pose), not kept casters to verify or cull.
            CollectHeld();
            for (std::size_t i = 0; i < frame_entries.size() + held_now.size(); ++i) {
                Entry* entry = i < frame_entries.size() ? frame_entries[i]
                                                        : held_now[i - frame_entries.size()];
                if (entry->shadow && entry->world.buffer && entry->copied) {
                    if (const auto* box = vsm->Box(entry->world.address)) {
                        entry->box = *box;
                        entry->has_box = true;
                    }
                    casters.push_back({entry->world.address, entry->indices.address,
                                       entry->triangles, entry->dynamic,
                                       entry->copied_at > vsm_copies});
                }
            }
            // A caster the game draws now in nearly the same place as a kept one has replaced it
            // (a swapped level of detail): their boxes overlap by half of their union or more.
            const auto replaced = [&](const std::array<float, 6>& box) {
                constexpr float Pad = 5e-4f;
                float volume = 1.0f;
                for (int k = 0; k < 3; ++k) {
                    volume *= box[k + 3] - box[k] + 2.0f * Pad;
                }
                for (std::size_t i = 0; i < frame_entries.size() + held_now.size(); ++i) {
                    const Entry* drawn = i < frame_entries.size()
                                             ? frame_entries[i]
                                             : held_now[i - frame_entries.size()]; // r14
                    if (!drawn->shadow || !drawn->has_box) {
                        continue;
                    }
                    float overlap = 1.0f, other = 1.0f;
                    for (int k = 0; k < 3; ++k) {
                        const float span = std::min(box[k + 3], drawn->box[k + 3]) -
                                           std::max(box[k], drawn->box[k]) + 2.0f * Pad;
                        if (span <= 0.0f) {
                            overlap = 0.0f;
                            break;
                        }
                        overlap *= span;
                        other *= drawn->box[k + 3] - drawn->box[k] + 2.0f * Pad;
                    }
                    if (overlap > 0.0f && overlap * 3.0f >= volume + other) {
                        return true;
                    }
                }
                return false;
            };
            const std::array<float, 2> camera_proj{camera.proj[0], camera.proj[1]};
            if (!cull_serial || cull_view != camera.view || cull_inv_view != camera.inv_view ||
                cull_proj != camera_proj ||
                cull_drawn != frame_entries.size() + held_now.size()) {
                cull_view = camera.view;
                cull_inv_view = camera.inv_view;
                cull_proj = camera_proj;
                cull_drawn = frame_entries.size() + held_now.size();
                ++cull_serial;
            }
            for (const auto& item : entries) {
                Entry* entry = item.second.get();
                if (entry && entry->shadow && entry->seen_frame != frame &&
                    !(entry->held && Holds(*entry)) && // r14: listed above as drawn
                    !entry->gone && frame - entry->seen_frame <= VsmKeepFrames &&
                    !entry->dynamic && entry->built && entry->copied && entry->world.buffer) {
                    if (const auto* box = vsm->Box(entry->world.address)) {
                        entry->box = *box;
                        entry->has_box = true;
                    }
                    // Alpha cut-outs float over the scene depth where the texture discards.
                    const bool cutout = cutout_meshes.contains(entry->mesh);
                    u32 tested = 0, floating = 0;
                    if (!cutout && vsm->Verdict(entry->world.address, tested, floating)) {
                        ++stats.vsm_verified;
                        if (tested >= 12 && floating * 10 >= tested * 6) {
                            if (++entry->gone_streak >= 3) {
                                entry->gone = true;
                                ++stats.vsm_gone;
                                continue;
                            }
                        } else {
                            entry->gone_streak = 0;
                        }
                    }
                    if (entry->has_box) {
                        // Re-tested when the drawn set may have changed, a quarter of the
                        // casters each frame.
                        if (entry->cull_serial != cull_serial || entry->cull_box != entry->box) {
                            if (!entry->cull_serial || entry->cull_box != entry->box ||
                                (frame + (item.first & 3)) % 4 == 0) {
                                entry->culled = replaced(entry->box);
                                entry->cull_box = entry->box;
                                entry->cull_serial = cull_serial;
                            }
                        }
                        if (entry->culled) {
                            ++stats.vsm_culled;
                            continue;
                        }
                    }
                    ++stats.vsm_kept;
                    casters.push_back({entry->world.address, entry->indices.address,
                                       entry->triangles, false, entry->copied_at > vsm_copies,
                                       !cutout});
                }
            }
            const SunVsm::Inputs vsm_in{
                .constants = in.constants,
                .constants_offset = in.constants_offset,
                .constants_range = in.constants_range,
                .depth = in.depth,
                .raw_image = raw_image,
                .raw_view = raw_view,
                .view = camera.view,
                .inv_view = camera.inv_view,
                .constants_offset_word = in.constants_offset_word,
                .frame_index = in.frame_index,
                .width = in.width,
                .height = in.height,
            };
            use_vsm = vsm->Record(casters, vsm_in);
            if (use_vsm) {
                vsm_copies = copies;
            }
        }
    }
    if (!use_vsm && !(need_scene && SunRayTraced())) {
        return false;
    }
    // bbport (experiment mask 4194304 = the old behaviour): pixels whose ray the filter cannot
    // show (outside the game's shadow coverage, with every neighbour it reads) are not traced;
    // rt_shadow.comp RayIsSeen. The same radius for both passes keeps that exact.
    constexpr s32 FilterRadius = 2;
    // bbport (r25_rt-sun-trace): experiment 1125899906842624 clear (default): the exact savings
    // (rt_shadow.comp Shade, rt_shadow_filter.comp R25); set: the old paths. One sun trace in 8
    // counts; every 600 the means per counted frame (u32 differences survive the wrap; read while
    // the GPU may still copy a later frame's counters, which then fall in the next window).
    r25_half = R25HalfWanted(); // bbport (r37_menu-options)
    const bool r25_exact = !BbToggle::Experiment(R25SunTraceOffBit);
    if (++r25_frames >= 600 && r25_readback.mapped) {
        std::array<u32, R25Slots> now{};
        std::memcpy(now.data(), r25_readback.mapped, sizeof(now));
        const u32 counted = now[0] - r25_last[0];
        std::array<double, R25Slots> d{};
        for (u32 i = 0; i < R25Slots && counted != 0; ++i) {
            d[i] = double(u32(now[i] - r25_last[i])) / double(counted);
        }
        r25_last = now;
        std::printf("Ray traced sun (r25): experiment 1125899906842624 %s, half resolution %s, "
                    "%ux%u; a frame (mean of %u counted): pixels traced %.0f (%.0f full "
                    "resolution or first pass, %.0f second pass); skipped: sky %.0f, beyond the "
                    "shadow distance %.0f (%s), facing away %.0f, taken from the first pass %.0f; "
                    "workgroups with no ray %.0f of %.0f; filter: fade 0 %.0f (%s), 5x5 blur "
                    "%.0f, plain %.0f, workgroups with no fade > 0 %.0f of %.0f\n",
                    r25_exact ? "clear" : "set (old paths)", r25_half ? "on" : "off", raw_width,
                    raw_height, counted, d[4] + d[5], d[4], d[5], d[1], d[2],
                    r25_exact ? "not stored" : "stored", d[3], d[6], d[7], d[8], d[9],
                    r25_exact ? "ray result not read" : "read as before", d[10], d[11], d[12],
                    d[13]);
        r25_frames = 0;
    }
    const u32 r25_flags =
        (r25_exact ? R25Exact : 0u) | ((r25_recorded++ & 7) == 0 ? R25Count : 0u);
    const bool r25_clear = !r25_cleared;
    r25_cleared = true;
    const TracePush trace{
        .buf_off = in.constants_offset_word,
        .frame_index = 0u,
        .size = {float(in.width), float(in.height)},
        .rays = rays,
        .light_tan = 0.02f,
        .bias_m = 0.01f,
        .max_distance = 800.0f,
        .far_radius = BbToggle::Experiment(4194304) ? -1 : FilterRadius,
        .r25_flags = r25_flags,
    };
    const FilterPush filter{
        .buf_off = in.constants_offset_word,
        .radius = FilterRadius,
        .size = {float(in.width), float(in.height)},
        .r25_flags = r25_flags,
    };
    EffectPass::Mark(14, "ray traced sun");
    scheduler.RecordCrumb(
        {.name = "Ray traced sun"},
        [in, trace, filter, use_vsm, tlas = tlas, raw_image = raw_image, raw_view = raw_view,
         sampler = *sampler, trace_pipeline = *trace_pipeline, trace_layout = *trace_layout,
         filter_pipeline = *filter_pipeline, filter_layout = *filter_layout,
         r25_counts = r25_counts.buffer, r25_readback = r25_readback.buffer, r25_half = r25_half,
         half_pipeline = r25_half ? *r25_half_pipeline : vk::Pipeline{},
         half_layout = r25_half ? *r25_half_layout : vk::PipelineLayout{},
         r25_clear](vk::CommandBuffer cmdbuf) {
            const vk::ImageMemoryBarrier2 to_general{
                .srcStageMask = Compute,
                .dstStageMask = Compute,
                .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined,
                .newLayout = vk::ImageLayout::eGeneral,
                .image = raw_image,
                .subresourceRange = {vk::ImageAspectFlagBits::eColor, 0, 1, 0, 1},
            };
            if (!use_vsm) {
                cmdbuf.pipelineBarrier2(
                    {.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &to_general});
            }
            if (r25_clear) { // bbport (r25_rt-sun-trace): the counters start at zero
                cmdbuf.fillBuffer(r25_counts, 0, VK_WHOLE_SIZE, 0);
                // vkCmdFillBuffer is a transfer command: eTransfer covers it whichever
                // transfer sub-stage (clear or copy) a driver or the validation layer files it
                // under.
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eTransfer,
                                          vk::AccessFlagBits2::eTransferWrite, Compute,
                                          vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            }
            const vk::DescriptorBufferInfo r25_info{r25_counts, 0, VK_WHOLE_SIZE};

            const vk::DescriptorBufferInfo constants{in.constants, in.constants_offset, in.constants_range};
            const vk::DescriptorBufferInfo uniforms{in.uniforms, in.uniforms_offset, in.uniforms_range};
            const vk::DescriptorImageInfo depth{sampler, in.depth, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo raw_write{{}, raw_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo raw_read{sampler, raw_view, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo target{{}, in.target, vk::ImageLayout::eGeneral};
            const vk::WriteDescriptorSetAccelerationStructureKHR scene{
                .accelerationStructureCount = 1, .pAccelerationStructures = &tlas};
            const std::array<vk::WriteDescriptorSet, 6> trace_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &raw_write},
                {.pNext = &scene, .dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &uniforms},
                {.dstBinding = 5, .descriptorCount = 1, // r25: counters
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},
            }};
            if (!use_vsm) {
                cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, trace_pipeline);
                cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, trace_layout, 0,
                                            trace_writes);
                cmdbuf.pushConstants(trace_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                     sizeof(trace), &trace);
                if (!r25_half) {
                    cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
                } else {
                    // bbport (r25_rt-sun-trace): BB_RT_SUN_HALF=1: pixel (2x, 2y) of each 2x2
                    // block, then the other three (taken from those, or traced), with the
                    // rt_shadow_half_comp build (same bindings and push constants).
                    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, half_pipeline);
                    cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, half_layout, 0,
                                                trace_writes);
                    TracePush pass = trace;
                    pass.r25_flags = trace.r25_flags | R25HalfFirst;
                    cmdbuf.pushConstants(half_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(pass), &pass);
                    cmdbuf.dispatch(((in.width + 1) / 2 + 7) / 8, ((in.height + 1) / 2 + 7) / 8,
                                    1);
                    EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite,
                                              Compute,
                                              vk::AccessFlagBits2::eShaderRead |
                                                  vk::AccessFlagBits2::eShaderWrite);
                    pass.r25_flags = trace.r25_flags | R25HalfFill;
                    cmdbuf.pushConstants(half_layout, vk::ShaderStageFlagBits::eCompute, 0,
                                         sizeof(pass), &pass);
                    cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
                }
            }
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, Compute,
                   vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
            const std::array<vk::WriteDescriptorSet, 6> filter_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &constants},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &depth},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &raw_read},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &target},
                {.dstBinding = 4, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &uniforms},
                {.dstBinding = 5, .descriptorCount = 1, // r25: counters
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &r25_info},
            }};
            cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, filter_pipeline);
            cmdbuf.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, filter_layout, 0, filter_writes);
            cmdbuf.pushConstants(filter_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(filter), &filter);
            cmdbuf.dispatch((in.width + 7) / 8, (in.height + 7) / 8, 1);
            EffectPass::MemoryBarrier(cmdbuf, Compute, vk::AccessFlagBits2::eShaderWrite, vk::PipelineStageFlagBits2::eAllCommands,
                   vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
            // bbport (r25_rt-sun-trace): a counted frame's counters to the host (Record reads
            // them); later counting waits for the copy.
            if ((filter.r25_flags & R25Count) != 0) {
                const vk::BufferCopy region{0, 0, R25Slots * sizeof(u32)};
                cmdbuf.copyBuffer(r25_counts, r25_readback, region);
                EffectPass::MemoryBarrier(cmdbuf, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite |
                                              vk::AccessFlagBits2::eTransferRead,
                                          vk::PipelineStageFlagBits2::eHost | Compute,
                                          vk::AccessFlagBits2::eHostRead |
                                              vk::AccessFlagBits2::eShaderRead |
                                              vk::AccessFlagBits2::eShaderWrite);
            }
        });
    return true;
}

// bbport (r26_upkeep-probe): at each frame end while BB_RT_UPKEEP_FREEZE is set, after `frame`
// moved on and before the evictions. Counts the frames in the level (in a row with casters in the
// ray tracing scene), decides what the next frame freezes, prints, and returns whether this frame
// end's evictions wait: the TLAS traced as it was holds the BLAS addresses of its entries, so none
// is destroyed while it stays frozen. An eviction pass that does run may destroy one, so a new
// TLAS is built before one is kept again.
bool RtShadow::R26FrameEnd() {
    const u32 mode = UpkeepProbeMode();
    const u32 was = r26_freeze;
    r26_level_frames = need_scene && !frame_entries.empty() ? r26_level_frames + 1 : 0;
    const bool bit = BbToggle::Experiment(R26ProbeOffBit);
    r26_freeze = !bit && need_scene && r26_level_frames >= R26AfterFrames ? mode : 0u;
    const bool evicting = frame % 64 == 0 || blas_bytes > blas_limit - blas_limit / 8 ||
                          entry_bytes > MaxEntryBytes / 8 * 7;
    const bool hold = r26_tlas_kept && (r26_freeze & 2u) != 0;
    if (evicting && hold) {
        ++r26_stats.evictions_held;
    } else if (evicting || !need_scene) {
        r26_tlas_built = false;
    }
    r26_tlas_kept = false;
    static constexpr const char* mode_names[] = {"off", "blas", "tlas", "all"};
    static constexpr const char* frozen_names[] = {
        "nothing", "BLAS refits and builds (TLAS built as usual)",
        "the TLAS (BLAS refits and builds as usual)", "BLAS refits and builds and the TLAS"};
    const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
    if (r26_freeze != 0 && was == 0) {
        std::printf("Ray tracing upkeep probe (r26): engaged from frame %llu after %llu frames in "
                    "the level: BB_RT_UPKEEP_FREEZE=%s freezes %s; experiment 2251799813685248 "
                    "set releases it\n",
                    u(frame), u(r26_level_frames), mode_names[mode], frozen_names[mode]);
    } else if (r26_freeze == 0 && was != 0) {
        std::printf("Ray tracing upkeep probe (r26): released from frame %llu (%s)\n", u(frame),
                    bit           ? "experiment 2251799813685248 set"
                    : !need_scene ? "ray tracing scene off"
                                  : "no casters in the scene: left the level");
    }
    ++r26_stats.frames;
    r26_stats.frozen += was != 0 ? 1 : 0;
    if (r26_stats.frames >= 600 || (r26_stats.frames > 1 && bit != r26_stats.bit)) {
        const double f = double(r26_stats.frames);
        std::printf("Ray tracing upkeep probe (r26): BB_RT_UPKEEP_FREEZE=%s (freezes %s), "
                    "experiment 2251799813685248 %s; over %llu frames, %llu frozen: a frame %.1f "
                    "BLAS refits (%.0f triangles) and %.1f BLAS builds (%.0f triangles) left out, "
                    "%.1f casters without a BLAS left out, %.1f BLAS refits and builds still "
                    "recorded, %.2f TLAS builds left out (%llu kept as built, %llu prepared as "
                    "usual); %llu eviction passes held back; %llu frames in the level\n",
                    mode_names[mode], frozen_names[mode],
                    r26_stats.bit ? "set (probe off)" : "clear (probe on)", u(r26_stats.frames),
                    u(r26_stats.frozen), double(r26_stats.refits_left) / f,
                    double(r26_stats.refit_triangles) / f, double(r26_stats.builds_left) / f,
                    double(r26_stats.build_triangles) / f, double(r26_stats.left_out) / f,
                    double(r26_stats.recorded) / f, double(r26_stats.tlas_kept) / f,
                    u(r26_stats.tlas_kept), u(r26_stats.tlas_prepared),
                    u(r26_stats.evictions_held), u(r26_level_frames));
        r26_stats = {};
    }
    r26_stats.bit = bit;
    return hold;
}

void RtShadow::OnFrameEnd() {
    if (!capturing) {
        return;
    }
    if (vsm) {
        vsm->OnFrameEnd();
    }
    need_scene = SceneWanted();
    // Frames whose casters were too incomplete for Complete(): the game's own shadows showed.
    stats.missed += missed;
    stats.incomplete += !frame_entries.empty() && missed * 4 > u32(frame_entries.size()) ? 1 : 0;
    for (const Build& build : builds) {
        build.entry->built = build.entry->built && build.update;
        build.entry->r17_inputs = 0; // bbport (r17_rt-upkeep): its BLAS did not get this capture
    }
    builds.clear();
    if (stats.frames >= 600) {
        const double f = double(stats.frames);
        std::printf("Ray tracing: %.0f shadow + %.0f camera draws, %.0f instances, %.0f triangles a "
                    "frame; %zu BLAS; alpha %.1f, not ortho %.1f, no camera %.1f, unsupported %.1f, "
                    "many instances %.1f, over budget %.1f, moving %.1f, copies rebuilt %.1f, strips "
                    "%.1f, in both passes %.1f, cut-out characters %.1f, new triangles built %.0f, "
                    "evicted %.1f a frame; scene %.0f MB of %.0f; missed %.1f, kept casters %.1f "
                    "drawn %.1f culled %.1f verified a frame, %llu declared gone since the last line; "
                    "%llu prop instances promoted since the last line, %zu candidates; %llu frames "
                    "fell back to the game's shadows\n",
                    double(stats.draws) / f, double(stats.camera_draws) / f,
                    double(stats.instances) / f, double(stats.triangles) / f, entries.size(),
                    double(stats.alpha) / f, double(stats.not_ortho) / f, double(stats.no_camera) / f,
                    double(stats.unsupported) / f, double(stats.instanced) / f,
                    double(stats.over_budget) / f, double(stats.dynamic_draws) / f,
                    double(stats.shared_builds) / f, double(stats.strips) / f,
                    double(stats.merged) / f, double(stats.cut_characters) / f,
                    double(stats.built_triangles) / f, double(stats.evicted) / f,
                    double(blas_bytes) / 1048576.0, double(blas_limit) / 1048576.0,
                    double(stats.missed) / f, double(stats.vsm_kept) / f,
                    double(stats.vsm_culled) / f, double(stats.vsm_verified) / f,
                    static_cast<unsigned long long>(stats.vsm_gone),
                    static_cast<unsigned long long>(stats.promoted), candidates.size(),
                    static_cast<unsigned long long>(stats.incomplete));
        // bbport: what the shared entries are: copies of a mesh drawn more than once in a pass,
        // known by draw order and fully rebuilt every frame within RebuiltTrianglesPerFrame (see
        // PrepareDraw).
        u64 shared = 0, shared_triangles = 0, shared_moving = 0, shared_palette = 0,
            shared_camera = 0, shared_rebuilt = 0, shared_rebuilt_triangles = 0;
        std::unordered_set<u64> shared_meshes;
        for (const auto& item : entries) {
            const Entry* e = item.second.get();
            if (!e || !e->rebuilt || e->seen_frame != frame) {
                continue;
            }
            ++shared;
            shared_triangles += e->triangles;
            shared_moving += e->dynamic ? 1 : 0;
            shared_palette += e->palette != 0 ? 1 : 0;
            shared_camera += (e->mask & CameraMask) != 0 ? 1 : 0;
            shared_meshes.insert(e->base);
            if (e->built_frame == frame) {
                ++shared_rebuilt;
                shared_rebuilt_triangles += e->triangles;
            }
        }
        std::printf("Ray tracing: %.0f triangles refit a frame; shared copies drawn on the last "
                    "frame: %llu of %zu meshes, %llu triangles, %llu moving, %llu with a palette, "
                    "%llu in the camera pass, %llu (%llu triangles) rebuilt on it; rebuilt budget "
                    "%u\n",
                    double(stats.refit_triangles) / f, static_cast<unsigned long long>(shared),
                    shared_meshes.size(), static_cast<unsigned long long>(shared_triangles),
                    static_cast<unsigned long long>(shared_moving),
                    static_cast<unsigned long long>(shared_palette),
                    static_cast<unsigned long long>(shared_camera),
                    static_cast<unsigned long long>(shared_rebuilt),
                    static_cast<unsigned long long>(shared_rebuilt_triangles), RebuiltBudget());
        stats = {};
    }
    // bbport (r17_rt-upkeep): one line every 600 frames
    ++r17_stats.frames;
    if (frame % 600 == 0 && r17_stats.tlas_built + r17_stats.tlas_updated +
                                    r17_stats.tlas_skipped + r17_stats.world_computed +
                                    r17_stats.world_reused != 0) {
        const double f = double(r17_stats.frames);
        const auto u = [](u64 v) { return static_cast<unsigned long long>(v); };
        static constexpr const char* unchanged_names[] = {"off", "count", "skip"};
        std::printf("Ray tracing upkeep (r17): a frame %.1f meshes refit (%.0f triangles), %.1f "
                    "built (%.0f triangles), %.1f of them shared copies built fast (%.0f "
                    "triangles); unchanged inputs (BB_RT_UNCHANGED=%s): %.1f refits skipped (%.0f "
                    "triangles), %.1f refit although unchanged (%.0f triangles), %.1f not provable; "
                    "far only (every %u, 0 off; BB_RT_REFIT_EVERY or graphics_rt_far_refit): "
                    "%.1f refits skipped (%.0f triangles), %.1f "
                    "refit (%.0f triangles); TLAS over %llu frames: %llu built, %llu refit, %llu "
                    "skipped as unchanged; to-world %.0f computed, %.0f reused a frame; experiment "
                    "4398046511104 %s\n",
                    double(r17_stats.refit) / f, double(r17_stats.refit_triangles) / f,
                    double(r17_stats.rebuilt) / f, double(r17_stats.rebuilt_triangles) / f,
                    double(r17_stats.fast) / f, double(r17_stats.fast_triangles) / f,
                    unchanged_names[UnchangedMode()], double(r17_stats.same_skipped) / f,
                    double(r17_stats.same_skipped_triangles) / f, double(r17_stats.same_would) / f,
                    double(r17_stats.same_would_triangles) / f, double(r17_stats.same_unknown) / f,
                    RefitEvery(), double(r17_stats.far_skipped) / f,
                    double(r17_stats.far_skipped_triangles) / f, double(r17_stats.far_refit) / f,
                    double(r17_stats.far_refit_triangles) / f, u(r17_stats.frames),
                    u(r17_stats.tlas_built), u(r17_stats.tlas_updated), u(r17_stats.tlas_skipped),
                    double(r17_stats.world_computed) / f, double(r17_stats.world_reused) / f,
                    UpkeepOn() ? "clear (new)" : "set (old)");
    }
    if (frame % 600 == 0) {
        r17_stats = {};
    }
    // The draw order entries of instances promoted this frame (their other cascades' copies, an
    // old pose's) would otherwise stay behind as duplicate kept casters.
    if (!promoted_now.empty()) {
        for (auto& item : entries) {
            Entry& e = *item.second;
            if (e.instance || e.dynamic || !e.palette || e.gone || e.seen_frame == frame) {
                continue;
            }
            const std::array<u64, 3> shadow_id{e.base, e.palette, 0u};
            const std::array<u64, 3> camera_id{e.base, e.palette, 1u};
            if (promoted_now.contains(XXH3_64bits(shadow_id.data(), sizeof(shadow_id))) ||
                promoted_now.contains(XXH3_64bits(camera_id.data(), sizeof(camera_id)))) {
                e.gone = true;
            }
        }
        promoted_now.clear();
    }
    if (frame % 60 == 0) {
        std::erase_if(candidates, [&](const auto& item) {
            return item.second.last + CandidateFrames < frame + 1;
        });
    }
    UpdateHeld(); // bbport (r14_cascade_rt): before the evictions, which spare held entries
    ++frame;
    // bbport (r26_upkeep-probe): BB_RT_UPKEEP_FREEZE set: true while the TLAS traced as it was
    // stays frozen (it holds BLAS addresses: no entry is destroyed). Unset: false, as before.
    const bool r26_hold = UpkeepProbeMode() != 0 && R26FrameEnd();
    if (!r26_hold && (frame % 64 == 0 || blas_bytes > blas_limit - blas_limit / 8)) {
        const bool keep_casters = vsm && vsm->Ready() &&
                                  BbSettings::Get().graphics_sun_vsm.load(std::memory_order_relaxed);
        const auto protected_vsm = [&](const Entry& entry) {
            return keep_casters && frame - entry.seen_frame <= VsmKeepFrames && entry.shadow &&
                   !entry.dynamic && !entry.gone && entry.built && entry.copied && entry.world.buffer;
        };
        u64 keep_from = frame > UnusedFrames ? frame - UnusedFrames : 0;
        if (blas_bytes > blas_limit - blas_limit / 8) {
            u64 bytes = blas_bytes;
            const u64 target = blas_limit - blas_limit / 4;
            std::size_t at = 0;
            std::vector<std::pair<u64, u64>> aged;
            aged.reserve(entries.size());
            for (const auto& [key, entry] : entries) {
                if (!protected_vsm(*entry) && !entry->held) {
                    aged.emplace_back(entry->seen_frame, entry->scene_bytes);
                }
            }
            std::ranges::sort(aged);
            for (; at < aged.size() && bytes > target && aged[at].first + KeptFrames < frame; ++at) {
                bytes -= std::min(bytes, aged[at].second);
                keep_from = std::max(keep_from, aged[at].first + 1);
            }
        }
        ++r19_entries_gen; // bbport (r19_draw-cost): entries may be erased below
        std::erase_if(entries, [&](auto& item) {
            const Entry& entry = *item.second;
            if (entry.seen_frame >= keep_from || protected_vsm(entry) || entry.held) {
                return false;
            }
            Destroy(*item.second);
            ++stats.evicted;
            return true;
        });
    }
    if (!r26_hold && entry_bytes > MaxEntryBytes / 8 * 7) {
        std::vector<std::pair<u64, u64>> order;
        order.reserve(entries.size());
        for (const auto& [key, entry] : entries) {
            if (frame - entry->seen_frame > 2 && !entry->held) {
                order.emplace_back(entry->seen_frame, key);
            }
        }
        std::ranges::sort(order);
        for (const auto& [seen, key] : order) {
            if (entry_bytes <= MaxEntryBytes / 4 * 3) {
                break;
            }
            const auto it = entries.find(key);
            Destroy(*it->second);
            entries.erase(it);
            ++r19_entries_gen; // bbport (r19_draw-cost)
        }
    }
    const u32 slot = u32(frame % 4);
    if (slot_ticks[slot]) {
        scheduler.Wait(slot_ticks[slot]);
        slot_ticks[slot] = 0;
    }
    params_used = 0;
    positions_used = 0;
    scratch_used = 0;
    new_triangles = 0;
    rebuilt_triangles = 0;
    missed = 0;
    tlas_count = 0;
    frame_entries.clear();
    frame_cameras.clear();
    occurrences.clear();
    if (++occurrence_epoch == 0) { // 2^32 frames: slots of epoch 0 would read as this frame's
        occurrence_slots.fill(OccurrenceSlot{});
        occurrence_epoch = 1;
    }
}

}
