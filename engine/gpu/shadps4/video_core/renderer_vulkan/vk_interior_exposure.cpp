// SPDX-License-Identifier: GPL-3.0-or-later
#include "video_core/renderer_vulkan/vk_interior_exposure.h"

#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

#include <vk_mem_alloc.h>

#include "bbport_interior_exposure.h"
#include "bbport_settings.h"
#include "video_core/host_shaders/interior_meter_comp.h"
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan::InteriorExposure {
namespace {
namespace Policy = BbInteriorExposure;
using Clock = std::chrono::steady_clock;

constexpr u32 SlotCount = 4;
constexpr float SampleCount = float(Policy::GridX * Policy::GridY);

// bbport (r99c_interior-default): graphics_interior_brightness is the largest lift.
static_assert(BbSettings::InteriorBrightnessDefault == Policy::DefaultMaxEv &&
              BbSettings::InteriorBrightnessMax == Policy::MaxEvLimit &&
              BbSettings::InteriorBrightnessMin == 0.0f);

/// interior_meter.comp's Slot (std430).
struct Slot {
    float log_sum, samples, sky, quarter;
    u32 frame;
    float halfway, open, twice;
};
static_assert(sizeof(Slot) == 32);

/// interior_meter.comp's Push.
struct Push {
    u32 width, height, grid_x, grid_y, slot, frame;
    float lum_min, lum_max;
    float z_scale, z_offset, open_m, pad0;
};
static_assert(sizeof(Push) == 48);

/// The meter's objects, made at its first call with the knob on. They are never freed: the process
/// ends with the device (one compute pipeline and a 128-byte host buffer).
struct State {
    bool tried = false, ready = false;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;
    vk::Buffer buffer{};
    VmaAllocation allocation{};
    void* mapped = nullptr;
    std::array<u64, SlotCount> tick{};    ///< the scheduler tick each slot's dispatch was recorded in
    std::array<u32, SlotCount> frame{};   ///< the frame number pushed with it
    std::array<bool, SlotCount> pending{}; ///< recorded, not read back yet
    std::array<float, SlotCount> open_at{}; ///< the open distance pushed with it (0: depth 1 only)
    u32 next_frame = 1;
    float applied_ev = 0.0f;
    float open_eased = Policy::OpenStart;
    float far_eased = Policy::OpenStart; ///< r99d: the far share after easing
    Policy::Lift last{};
    Policy::Reading last_reading{};
    float last_open_m = 0.0f; ///< the open distance the last reading was metered with
    bool have_read = false;
    Clock::time_point last_read{}, last_line{};
    u32 metered = 0, read = 0, held = 0, busy = 0, no_camera = 0; ///< since the last line
    bool active = false;   ///< the meter ran at the last call (the setting or a variable said on)
    bool was_off = false;  ///< it was switched off after it had run: the next on says so
    float said_max = 0.0f; ///< the largest lift the log last named
};

/// The meter's state once it exists (null before the first call with the meter on).
State* g_state = nullptr;

/// The meter is switched off (the setting went to 0): no lift at once, the factor exactly 1, the
/// readings forgotten (the pipeline and the buffer stay). Does nothing when it was not running.
void Rest(State& s) {
    if (!s.active) {
        return;
    }
    s.active = false;
    s.was_off = true;
    s.applied_ev = 0.0f;
    s.open_eased = Policy::OpenStart;
    s.far_eased = Policy::OpenStart;
    s.last = Policy::Lift{};
    s.last_reading = Policy::Reading{};
    s.last_open_m = 0.0f;
    s.have_read = false;
    s.pending.fill(false);
    s.metered = s.read = s.held = s.busy = s.no_camera = 0;
    Policy::applied_scale.store(1.0f, std::memory_order_relaxed);
    std::printf("Interior exposure (r99c): off (graphics_interior_brightness is 0): no lift, the "
                "exposure is the game's own\n");
}

bool MakeBuffer(const Instance& instance, State& s) {
    const VkBufferCreateInfo buffer_ci{
        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = sizeof(Slot) * SlotCount,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT,
    };
    VmaAllocationCreateInfo alloc_ci{.usage = VMA_MEMORY_USAGE_AUTO};
    alloc_ci.requiredFlags = VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    alloc_ci.flags = VMA_ALLOCATION_CREATE_MAPPED_BIT | VMA_ALLOCATION_CREATE_HOST_ACCESS_RANDOM_BIT;
    VkBuffer raw{};
    VmaAllocationInfo info{};
    if (vmaCreateBuffer(instance.GetAllocator(), &buffer_ci, &alloc_ci, &raw, &s.allocation, &info) !=
            VK_SUCCESS ||
        !info.pMappedData) {
        return false;
    }
    s.buffer = raw;
    s.mapped = info.pMappedData;
    std::memset(s.mapped, 0, sizeof(Slot) * SlotCount);
    return true;
}

const char* ToneName(int tone) {
    return tone == BbSettings::TonemapperGt7    ? "GT7"
           : tone == BbSettings::TonemapperAces ? "ACES"
                                                : "the game's curve: no effect";
}

void SayOn(const Policy::Config& knobs, bool ready, const char* on_by, const char* max_from) {
    if (!ready) {
        std::printf("Interior exposure (r99b): off - no meter pipeline or host buffer\n");
        return;
    }
    const int tone = BbSettings::Get().graphics_tonemapper.load(std::memory_order_relaxed);
    char open[64];
    if (knobs.open_m > 0.0f) {
        std::snprintf(open, sizeof(open), "depth 1 or %.0f m or farther", knobs.open_m);
    } else {
        std::snprintf(open, sizeof(open), "depth 1 only");
    }
    std::printf("Interior exposure (r99c, on by %s%s): meter of %ux%u samples of "
                "the HDR scene at the upscaler (one 256-thread group, a %u-byte host buffer); "
                "target %.3f (%s: %.4f at the largest lift), strength %.2f, at most %+.2f EV (from %s); open samples: %s; no lift with %.0f%% "
                "open or more (fading from %.0f%%) or with %.0f%% far (depth 1 or %.0f m or farther) "
                "or more (fading from %.0f%%), the open share eased up over %.2f s and down "
                "over %.1f s, the far share over %.2f s and %.1f s; the lift rises over %.1f s, "
                "falls over %.1f s; acts through the "
                "GT7/ACES exposure (tonemapper now: %s); each line: metered = log-average "
                "luminance before the tone curve, sky left out; counts since the last line\n",
                on_by, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.follow ? "followed" : "fixed",
                Policy::EffectiveTarget(knobs), knobs.strength, knobs.max_ev, max_from, open,
                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::FarNone * 100.0f,
                0.25f * knobs.open_m, Policy::FarFull * 100.0f, Policy::OpenRiseSeconds,
                Policy::OpenFallSeconds, Policy::FarRiseSeconds, Policy::FarFallSeconds,
                Policy::RiseSeconds, Policy::FallSeconds, ToneName(tone));
}

float Percent(float count) {
    return count * (100.0f / SampleCount);
}
} // namespace

void Meter(const Instance& instance, Scheduler& scheduler, const CameraMotion& camera,
           vk::ImageView color, vk::ImageView depth, u32 w, u32 h) {
    // bbport (r99c_interior-default): the setting (live) and the environment (read once) at every call.
    const Policy::Env& env = Policy::Environment();
    const float setting =
        BbSettings::Get().graphics_interior_brightness.load(std::memory_order_relaxed);
    const Policy::Config knobs = Policy::Resolve(env, setting);
    if (knobs.mode == Policy::Off) {
        if (g_state) {
            Rest(*g_state);
        }
        return;
    }
    if (!color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    g_state = &s;
    if (!s.tried) {
        s.tried = true;
        s.ready = EffectPass::Create(instance, s.set_layout, s.layout, s.pipeline,
                                     {vk::DescriptorType::eStorageImage,
                                      vk::DescriptorType::eSampledImage,
                                      vk::DescriptorType::eStorageBuffer},
                                     sizeof(Push), INTERIOR_METER_COMP, "Interior exposure (r99b)") &&
                  MakeBuffer(instance, s);
        SayOn(knobs, s.ready, env.mode_set ? "BB_INTERIOR_EXPOSURE" : "graphics_interior_brightness",
              Policy::MaxSource(env, setting));
        s.said_max = knobs.max_ev;
        s.last_line = Clock::now();
    }
    if (!s.ready) {
        return;
    }
    if (!s.active) {
        s.active = true;
        if (s.was_off) {
            s.was_off = false;
            std::printf("Interior exposure (r99c): on again, at most %+.2f EV (from %s)\n", knobs.max_ev,
                        Policy::MaxSource(env, setting));
            s.said_max = knobs.max_ev;
        }
    }
    const auto now = Clock::now();

    // The newest reading the GPU has finished; a slot that holds another frame's numbers is skipped.
    bool got = false;
    Slot newest{};
    u32 newest_frame = 0;
    float newest_open_m = 0.0f;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i] || !scheduler.IsFree(s.tick[i])) {
            continue;
        }
        s.pending[i] = false;
        Slot slot;
        std::memcpy(&slot, static_cast<const u8*>(s.mapped) + i * sizeof(Slot), sizeof(Slot));
        if (slot.frame != s.frame[i]) {
            ++s.held;
            continue;
        }
        if (!got || s.frame[i] > newest_frame) {
            newest = slot;
            newest_frame = s.frame[i];
            newest_open_m = s.open_at[i];
            got = true;
        }
    }
    if (got) {
        ++s.read;
        const Policy::Reading reading{newest.log_sum, newest.samples, newest.sky, SampleCount,
                                      newest.quarter, newest.halfway, newest.open, newest.twice};
        const float dt = s.have_read ? std::chrono::duration<float>(now - s.last_read).count() : 0.0f;
        s.have_read = true;
        s.last_read = now;
        // A reading metered without the open distance (no usable camera then) saw only depth-1
        // sky: it does not move the eased share, so it cannot start a lift outdoors.
        const bool full = newest_open_m == knobs.open_m;
        if (Policy::Usable(reading) && full) {
            s.open_eased = Policy::StepOpen(s.open_eased, Policy::OpenShare(reading), dt);
            s.far_eased = Policy::StepFar(s.far_eased, Policy::FarShare(reading), dt);
        }
        const Policy::Lift lift = Policy::Want(knobs, reading, s.open_eased, s.far_eased);
        s.last_reading = reading;
        s.last_open_m = newest_open_m;
        if (lift.valid) {
            s.applied_ev = Policy::Step(s.applied_ev, lift.wanted_ev, dt);
            s.last = lift;
        } else {
            ++s.held;
        }
        Policy::applied_scale.store(std::exp2(s.applied_ev), std::memory_order_relaxed);
    }

    // The projection's z terms (depth = z_scale + z_offset / z, z_offset < 0 in front); without a
    // usable camera only depth 1 counts as open this frame.
    const std::array<float, 4> proj = camera.CameraMatrices().proj;
    const bool camera_ok = std::isfinite(proj[2]) && std::isfinite(proj[3]) && proj[3] < 0.0f;
    const float open_m = camera_ok ? knobs.open_m : 0.0f;
    if (!camera_ok) {
        ++s.no_camera;
    }

    // This frame's meter, into a slot nobody waits on.
    u32 slot = SlotCount;
    for (u32 i = 0; i < SlotCount; ++i) {
        if (!s.pending[i]) {
            slot = i;
            break;
        }
    }
    if (slot == SlotCount) {
        ++s.busy;
    } else {
        const Push push{w, h, Policy::GridX, Policy::GridY, slot, s.next_frame,
                        Policy::LumMin, Policy::LumMax, proj[2], proj[3], open_m, 0.0f};
        s.frame[slot] = s.next_frame;
        s.open_at[slot] = open_m;
        s.next_frame = s.next_frame == 0xffffffffu ? 1u : s.next_frame + 1u;
        s.pending[slot] = true;
        s.tick[slot] = scheduler.CurrentTick();
        ++s.metered;
        EffectPass::Mark(99, "interior exposure meter", true);
        scheduler.Record([push, color, depth, buffer = s.buffer, pipeline = *s.pipeline,
                          layout = *s.layout](vk::CommandBuffer cmd) {
            const vk::DescriptorImageInfo scene_info{.imageView = color,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo depth_info{.imageView = depth,
                                                     .imageLayout = vk::ImageLayout::eGeneral};
            const vk::DescriptorBufferInfo slots_info{buffer, 0, VK_WHOLE_SIZE};
            const std::array<vk::WriteDescriptorSet, 3> writes{{
                {.dstBinding = 0,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage,
                 .pImageInfo = &scene_info},
                {.dstBinding = 1,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eSampledImage,
                 .pImageInfo = &depth_info},
                {.dstBinding = 2,
                 .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer,
                 .pBufferInfo = &slots_info},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch(1, 1, 1);
            EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eComputeShader,
                                      vk::AccessFlagBits2::eShaderWrite,
                                      vk::PipelineStageFlagBits2::eHost,
                                      vk::AccessFlagBits2::eHostRead);
        });
    }

    const float since = std::chrono::duration<float>(now - s.last_line).count();
    if (since >= (knobs.mode == Policy::Show ? 1.0f : 2.0f)) {
        s.last_line = now;
        if (std::fabs(knobs.max_ev - s.said_max) > 1e-4f) {
            std::printf("Interior exposure (r99c): the largest lift is now %+.2f EV (from %s), target now %.4f\n",
                        knobs.max_ev, Policy::MaxSource(env, setting), Policy::EffectiveTarget(knobs));
            s.said_max = knobs.max_ev;
        }
        const auto& settings = BbSettings::Get();
        const int tone = settings.graphics_tonemapper.load(std::memory_order_relaxed);
        const float gt7 = settings.graphics_gt7_exposure.load(std::memory_order_relaxed);
        const float scale = Policy::Scale();
        const Policy::Reading& r = s.last_reading;
        const float m = s.last_open_m;
        std::printf("Interior exposure (r99b): applied %+.3f EV (x%.4f), wanted %+.2f EV, metered "
                    "%.5f (target %.4f); open %.1f%%, eased %.1f%%, far (depth 1 or %.0f m+) %.1f%%, eased "
                    "%.1f%%, indoor %.2f = open gate %.2f x far gate %.2f (depth 1 %.1f%%; at least "
                    "%.0f/%.0f/%.0f/%.0f m: %.1f/%.1f/%.1f/%.1f%%); GT7/ACES exposure %.2f -> %.3f "
                    "(%s); %u meters, %u read, %u held, %u busy, %u no camera\n",
                    s.applied_ev, scale, s.last.wanted_ev, s.last.metered, s.last.target,
                    Policy::OpenShare(r) * 100.0f, s.open_eased * 100.0f, 0.25f * m,
                    Policy::FarShare(r) * 100.0f, s.far_eased * 100.0f, s.last.indoor,
                    s.last.open_gate, s.last.far_gate,
                    Percent(r.sky), 0.25f * m, 0.5f * m, m, 2.0f * m, Percent(r.quarter),
                    Percent(r.halfway), Percent(r.open), Percent(r.twice), gt7, gt7 * scale,
                    ToneName(tone), s.metered, s.read, s.held, s.busy, s.no_camera);
        s.metered = s.read = s.held = s.busy = s.no_camera = 0;
    }
}

} // namespace Vulkan::InteriorExposure
