# r99_interior-exposure: FEATURE patch (lamp work, "dim interiors and auto exposure"). A
# brighten-only exposure floor for rooms lit only by lamps: the first stage the interior study
# (bbfss-ctx-interior-exposure.md) points to after its slot batch of 2026-11-15 19:07 ("raising
# lamp intensity is no cure for the dim library; exposure is the lever"), in the shape of its plan
# items 3 and 5 (a lift only indoors, through the GT7/ACES exposure the composite already takes per
# draw), but with its own meter instead of the game's YEBIS meter: YEBIS is coarse in the dark (raw
# 3-5 of 255), needs graphics_auto_exposure=1 and a learned reference, and relearns in the room
# after an area change; the study measured the scenes with exactly this statistic (log-average of
# Rec.709 luminance before the tone curve, sky masked by depth), so the target is in its numbers.
# Off by default behind BB_INTERIOR_EXPOSURE (environment, read once).
#
# REVIEW FIXES (2026-11-15, the .fixed.py; the draft r99_interior-exposure.py is left as it was):
#  a. Default target 0.04 / strength 0.5 -> 0.02 / 1 (a floor at L = 0.02): the draft lifted the
#     outdoor dark alley (study, mod off, hero light off: L 0.0251, sky 0.0 %) by +0.34 EV, and the
#     depth sky gate never saw any sky in any view the study measured (all 0.0 %), so it cannot keep
#     night streets out; the owner wants no general lift of night streets. Now the measured night
#     street is untouched (0.0251 > 0.02); the library still gets +0.49 EV level, +0.87 EV looking up
#     (mod off), the cap +1.5 EV with the Remaster mod. The alley WITH the mod (L 0.0097) still gets
#     about +1.0 EV: luminance cannot tell it from a room; said in the README.
#  b. LumMin/LumMax were written twice (header and shader), tied only by this script's text check
#     (maintainer rule 10): now pushed from the header (Push 24 -> 32 bytes), the shader has none.
#  c. The test includes <initializer_list> (range-for over braced lists) and checks the dark alley
#     case; README states the exact rule and that it is not an indoor test.
#
# What:
#  1. engine/gpu/shim/bbport_interior_exposure.h (new, pure, header only): the knobs (Parse, Knobs),
#     the rule (Want: lift = min(max_ev, strength * log2(target / metered)), never below 0, times
#     indoor = 1 - smoothstep(0.03, 0.15, sky share)), the easing in real time (Step: rise 1 s, fall
#     0.4 s), and the factor the composite reads (Scale(): an atomic float, 1 until the meter writes).
#  2. host_shaders/interior_meter.comp (new; build interior_meter_comp, no defines): one group of
#     256 threads, 64x36 samples of the HDR scene colour and depth: sum of log2 luminance, ground
#     and sky counts, written with the frame number into one 32-byte slot of a host buffer.
#  3. renderer_vulkan/vk_interior_exposure.h/.cpp (new): InteriorExposure::Meter: makes the pipeline
#     and the 128-byte host buffer (4 slots) at its first call with the knob on, reads the newest
#     slot the GPU has finished (Scheduler::IsFree on the tick it was recorded in), updates the lift,
#     records one dispatch (profile row "Lighting: interior exposure meter", pinned), prints the
#     lines.
#  4. Hooks in shared files (each its own few lines; the rest of each file untouched):
#     - vk_temporal_upscaler.cpp: one include; one call in TemporalUpscaler::Run (the HDR scene
#       path: DLSS, FSR, XeSS or TAA before the post) right before MarkUpscalerPart(4, ...): the
#       colour and depth the upscaler is about to read, already in GENERAL for compute reads.
#     - vk_pipeline_common.cpp: one include; the Gt7Push's exposure is graphics_gt7_exposure times
#       BbInteriorExposure::Scale().
#     - CMakeLists.txt: the shader build after upscale_reactive_comp; interior-exposure-test after
#       exposure-policy-test. build.sh --test: interior-exposure-test after draw-tokens-test.
#     - README.md: an "Interior exposure (in development)" section before "### Lamp fog shafts".
#  5. engine/tests/test_interior_exposure.cpp (new): knobs, the rule at the study's measured
#     scenes, the easing, the factor 1 by default.
#
# Knobs (environment, read once; no ini key, menu or launcher row yet: env for work in progress):
#   BB_INTERIOR_EXPOSURE      1 on, 2 SHOW (test: target 0.15, strength 1, max 3 EV unless set);
#                             anything else off (default).
#   BB_INTERIOR_EXPOSURE_TARGET    0.005-1, 0.02: scene log-average luminance aimed at (a floor).
#   BB_INTERIOR_EXPOSURE_STRENGTH  0-1, 1: share of the gap in stops the lift closes.
#   BB_INTERIOR_EXPOSURE_MAX_EV    0-3, 1.5: the largest lift in stops.
# Log (knob on): once "Interior exposure (r99, BB_INTERIOR_EXPOSURE=..): ..." at the first metered
#   frame; every 2 s (1 s with 2) "Interior exposure (r99): metered L (log-average luminance before
#   the tone curve, sky left out), sky S %, indoor I, wanted +W EV, applied +A EV (xF), GT7/ACES
#   exposure g -> g*F; N meters, R read, H held, B busy since the last line".
# Off: Meter returns after one static's mode test (no pipeline, no buffer, no dispatch, no line);
#   Scale() stays 1.0f, and x * 1.0f is x bit for bit, so the pushed exposure and the picture are
#   identical. Shared files gain only the call, the multiply and the includes.
# Cost (NOT MEASURED): one dispatch of one 256-thread group, 2304 depth and 2304 colour reads at
#   the render size (1080p internal at 4K DLSS Performance), an estimate of 0.01-0.03 ms (latency
#   bound on one SM); no image, no full-screen pass, no extra pass over the frame: the lift rides
#   on the exposure word the composite is already pushed. Memory: a 128-byte host buffer and one
#   compute pipeline. CPU: up to 4 timeline semaphore checks and a few float operations a frame.
#
# Use: python -I -X utf8 r99_interior-exposure.py check | apply | revert (root from R99_ROOT,
# else <tree>). Files keep their line ends (CRLF in the tree); new files are written with
# CRLF and removed by revert (only when unchanged). Originals of edited files are kept in
# r99_backup/ next to this script. Every insertion is found and removed by its own text, so another
# patch that later inserts next to the same anchor does not break check or revert here.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r99_backup")
ROOT = os.environ.get("R99_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"
TAG = "r99_interior-exposure"

NEW = {
    "engine/gpu/shim/bbport_interior_exposure.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r99_interior-exposure): a brighten-only exposure floor for dark interiors, part of the
// lamp work. A meter (Vulkan::InteriorExposure::Meter, host_shaders/interior_meter.comp) takes
// GridX x GridY samples of the HDR scene colour at the upscaler, before the tone curve: the
// log-average of their Rec.709 luminance, each clamped to [LumMin, LumMax], leaving out the sky
// (depth 1, the clear value), and the sky's share of the samples. Want() turns one reading into a
// lift in stops; Step() eases the applied lift toward it in real time; the lift, as a factor,
// multiplies the GT7/ACES exposure pushed to the game's final composite (Pipeline::BindResources).
// The game's own curve (graphics_tonemapper=original) and the HDR curve extension take no
// exposure, so with them it changes nothing.
//
// The rule (Want): gap = log2(target / metered), at least 0; wanted = min(max_ev, strength * gap)
// * indoor, indoor = 1 - smoothstep(SkyOpen, SkyGone, sky share). So a scene metered at or above
// the target, or one with SkyGone or more sky among the samples, gets no lift, and the lift never
// darkens. A reading metered below BlackFrame (a black or fading frame) or without a number keeps
// the lift as it is. Pure: no Vulkan, no settings; tested by tests/test_interior_exposure.cpp.
//
// Knobs (environment, read once by Knobs()): BB_INTERIOR_EXPOSURE 1 on, 2 SHOW (the Show* values
// for every number not set), anything else off; BB_INTERIOR_EXPOSURE_TARGET, _STRENGTH, _MAX_EV.
// A missing, unreadable or non-finite number takes the default, then the range.
//
// It is a floor on dark views, not an indoor test: the sky share only removes the lift where the
// samples see sky at depth 1. Measured 2026-11-15 (hero light off, no view with any such sky): the
// library 0.014 (looking up 0.011), the dream house 0.055, the dark alley 0.025 without the
// Remaster mod (so the default target 0.02 leaves that street alone) and 0.0097 with it (lifted).

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>

namespace BbInteriorExposure {

inline constexpr float DefaultTarget = 0.02f;  ///< log-average luminance aimed at (the floor)
inline constexpr float DefaultStrength = 1.0f; ///< share of the gap in stops that is closed
inline constexpr float DefaultMaxEv = 1.5f;    ///< the largest lift, stops
inline constexpr float ShowTarget = 0.15f;     ///< BB_INTERIOR_EXPOSURE=2 (test): exaggerated
inline constexpr float ShowStrength = 1.0f;
inline constexpr float ShowMaxEv = 3.0f;
inline constexpr float TargetMin = 0.005f, TargetMax = 1.0f;
inline constexpr float MaxEvLimit = 3.0f;
inline constexpr float SkyOpen = 0.03f;    ///< sky share of the samples where the lift starts to fade
inline constexpr float SkyGone = 0.15f;    ///< sky share from which there is no lift
inline constexpr float BlackFrame = 4e-4f; ///< metered below this: a black or fading frame, hold
inline constexpr float RiseSeconds = 1.0f; ///< time constant while the lift grows
inline constexpr float FallSeconds = 0.4f; ///< time constant while it shrinks
inline constexpr float MaxStep = 0.25f;    ///< s: the longest step one Step takes
inline constexpr unsigned GridX = 64, GridY = 36; ///< the meter's samples across, down
inline constexpr float LumMin = 1e-4f, LumMax = 64.0f; ///< each sample's luminance clamp (pushed)

enum Mode : int { Off = 0, On = 1, Show = 2 };

struct Config {
    int mode = Off;
    float target = DefaultTarget;
    float strength = DefaultStrength;
    float max_ev = DefaultMaxEv;
};

inline float Number(const char* text, float fallback, float lo, float hi) {
    float value = fallback;
    if (text && *text) {
        char* end = nullptr;
        const float read = std::strtof(text, &end);
        if (end != text && *end == '\0' && std::isfinite(read)) {
            value = read;
        }
    }
    return std::clamp(value, lo, hi);
}

inline Config Parse(const char* mode, const char* target, const char* strength, const char* max_ev) {
    Config c;
    if (mode && mode[0] && !mode[1]) {
        c.mode = mode[0] == '1' ? On : mode[0] == '2' ? Show : Off;
    }
    const bool show = c.mode == Show;
    c.target = Number(target, show ? ShowTarget : DefaultTarget, TargetMin, TargetMax);
    c.strength = Number(strength, show ? ShowStrength : DefaultStrength, 0.0f, 1.0f);
    c.max_ev = Number(max_ev, show ? ShowMaxEv : DefaultMaxEv, 0.0f, MaxEvLimit);
    return c;
}

/// The knobs, read from the environment at the first call.
inline const Config& Knobs() {
    static const Config config = Parse(
        std::getenv("BB_INTERIOR_EXPOSURE"), std::getenv("BB_INTERIOR_EXPOSURE_TARGET"),
        std::getenv("BB_INTERIOR_EXPOSURE_STRENGTH"), std::getenv("BB_INTERIOR_EXPOSURE_MAX_EV"));
    return config;
}

/// One meter reading (interior_meter.comp's slot): the sum of log2 luminance over the ground
/// samples, their number, the sky samples, and all samples.
struct Reading {
    float log_sum = 0, samples = 0, sky = 0, total = 0;
};

struct Lift {
    bool valid = false;   ///< false: hold the applied lift
    float metered = 0;    ///< log-average luminance of the ground samples (0 without any)
    float sky_share = 0;  ///< sky samples / all samples
    float indoor = 0;     ///< 1 - smoothstep(SkyOpen, SkyGone, sky_share)
    float wanted_ev = 0;  ///< the lift this reading asks for, stops, 0..max_ev
};

inline float Smoothstep(float a, float b, float x) {
    const float t = std::clamp((x - a) / (b - a), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

inline Lift Want(const Config& c, const Reading& r) {
    Lift l;
    if (!(r.total > 0.0f) || !std::isfinite(r.log_sum) || !std::isfinite(r.samples) ||
        !std::isfinite(r.sky) || !std::isfinite(r.total) || r.samples < 0.0f || r.sky < 0.0f) {
        return l;
    }
    l.sky_share = std::clamp(r.sky / r.total, 0.0f, 1.0f);
    l.indoor = 1.0f - Smoothstep(SkyOpen, SkyGone, l.sky_share);
    l.metered = r.samples >= 1.0f ? std::exp2(r.log_sum / r.samples) : 0.0f;
    if (l.indoor <= 0.0f) {
        l.valid = true; // open sky: no lift
        return l;
    }
    if (r.samples < 1.0f || !(l.metered >= BlackFrame)) {
        return l; // nothing to meter, or a black frame: hold
    }
    l.valid = true;
    const float gap = std::max(0.0f, std::log2(c.target / l.metered));
    l.wanted_ev = std::min(c.max_ev, c.strength * gap) * l.indoor;
    return l;
}

/// The applied lift after `dt` seconds (clamped to 0..MaxStep; not a number: 0) of easing toward
/// `wanted`: exponential, RiseSeconds while it grows, FallSeconds while it shrinks. Never passes
/// `wanted`.
inline float Step(float applied, float wanted, float dt) {
    dt = std::isfinite(dt) ? std::clamp(dt, 0.0f, MaxStep) : 0.0f;
    const float tau = wanted > applied ? RiseSeconds : FallSeconds;
    return applied + (wanted - applied) * (1.0f - std::exp(-dt / tau));
}

/// The factor on the GT7/ACES exposure, exp2(applied lift). Exactly 1 unless the knob is on: only
/// Vulkan::InteriorExposure::Meter writes it.
inline std::atomic<float> applied_scale{1.0f};
inline float Scale() {
    return applied_scale.load(std::memory_order_relaxed);
}

} // namespace BbInteriorExposure
''',

    H + "interior_meter.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure): the interior exposure meter (vk_interior_exposure.cpp). One group
// of 256 threads takes grid.x * grid.y samples at cell centres over the render size: a sample
// whose depth is 1 (the clear value: sky) is counted apart, every other one adds log2 of its
// Rec.709 luminance clamped to [lum_min, lum_max] (pushed from bbport_interior_exposure.h's
// LumMin, LumMax; one that is not a number is left out). Thread 0
// writes the sums and the frame number into one slot of a small host buffer; the CPU reads it once
// the GPU has passed that frame (gpu/shim/bbport_interior_exposure.h has the rule).
#version 450
#extension GL_EXT_samplerless_texture_functions : require

layout(local_size_x = 256) in;

layout(binding = 0, rgba16f) uniform readonly image2D scene_img; // HDR scene, before the tone curve
layout(binding = 1) uniform texture2D depth_tex;                 // D32, 1 = sky

struct Slot {
    float log_sum; // sum of log2 luminance over the ground samples
    float samples; // ground samples
    float sky;     // sky samples
    float total;   // all samples
    uint frame;    // the frame number pushed with this dispatch
    uint pad0;
    uint pad1;
    uint pad2;
};
layout(binding = 2, std430) writeonly buffer Slots {
    Slot slots[];
};

layout(push_constant) uniform Push {
    uvec2 size; // render pixels
    uvec2 grid; // samples across, down
    uint slot;
    uint frame;
    float lum_min; // each sample's luminance clamp
    float lum_max;
};

shared float s_log[256];
shared float s_ground[256];
shared float s_sky[256];

void main() {
    const uint t = gl_LocalInvocationIndex;
    const uint count = grid.x * grid.y;
    float log_sum = 0.0;
    float ground = 0.0;
    float sky = 0.0;
    for (uint i = t; i < count; i += 256u) {
        const uvec2 cell = uvec2(i % grid.x, i / grid.x);
        const ivec2 p = ivec2((vec2(cell) + 0.5) * vec2(size) / vec2(grid));
        if (texelFetch(depth_tex, p, 0).r >= 1.0) {
            sky += 1.0;
            continue;
        }
        const float y = dot(imageLoad(scene_img, p).rgb, vec3(0.2126, 0.7152, 0.0722));
        if (isnan(y) || isinf(y)) {
            continue;
        }
        log_sum += log2(clamp(y, lum_min, lum_max));
        ground += 1.0;
    }
    s_log[t] = log_sum;
    s_ground[t] = ground;
    s_sky[t] = sky;
    barrier();
    for (uint stride = 128u; stride > 0u; stride >>= 1u) {
        if (t < stride) {
            s_log[t] += s_log[t + stride];
            s_ground[t] += s_ground[t + stride];
            s_sky[t] += s_sky[t + stride];
        }
        barrier();
    }
    if (t == 0u) {
        slots[slot] = Slot(s_log[0], s_ground[0], s_sky[0], float(count), frame, 0u, 0u, 0u);
    }
}
''',

    R + "vk_interior_exposure.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include "common/types.h"
#include "video_core/renderer_vulkan/vk_common.h"

namespace Vulkan {
class Instance;
class Scheduler;

/// bbport (r99_interior-exposure): the meter of the interior exposure floor
/// (gpu/shim/bbport_interior_exposure.h has the rule and the knobs).
namespace InteriorExposure {

/// Called by TemporalUpscaler::Run with the frame's HDR scene colour (`color`: rgba16f, GENERAL,
/// storage) and depth (`depth`: GENERAL, sampled) of w x h render pixels, before the upscaler
/// reads them. Reads the newest earlier reading the GPU has finished, eases the lift and stores
/// its factor (BbInteriorExposure::Scale), then records this frame's meter dispatch. With
/// BB_INTERIOR_EXPOSURE not 1 or 2 it returns at once: nothing is made, recorded or printed.
void Meter(const Instance& instance, Scheduler& scheduler, vk::ImageView color, vk::ImageView depth,
           u32 w, u32 h);

} // namespace InteriorExposure
} // namespace Vulkan
''',

    R + "vk_interior_exposure.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan::InteriorExposure {
namespace {
namespace Policy = BbInteriorExposure;
using Clock = std::chrono::steady_clock;

constexpr u32 SlotCount = 4;

/// interior_meter.comp's Slot (std430).
struct Slot {
    float log_sum, samples, sky, total;
    u32 frame, pad[3];
};
static_assert(sizeof(Slot) == 32);

/// interior_meter.comp's Push.
struct Push {
    u32 width, height, grid_x, grid_y, slot, frame;
    float lum_min, lum_max;
};
static_assert(sizeof(Push) == 32);

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
    u32 next_frame = 1;
    float applied_ev = 0.0f;
    Policy::Lift last{};
    bool have_read = false;
    Clock::time_point last_read{}, last_line{};
    u32 metered = 0, read = 0, held = 0, busy = 0; ///< since the last line
};

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

void SayOn(const Policy::Config& knobs, bool ready) {
    if (!ready) {
        std::printf("Interior exposure (r99): off - no meter pipeline or host buffer\n");
        return;
    }
    const int tone = BbSettings::Get().graphics_tonemapper.load(std::memory_order_relaxed);
    std::printf("Interior exposure (r99, BB_INTERIOR_EXPOSURE=%d%s): meter of %ux%u samples of the "
                "HDR scene at the upscaler (one 256-thread group, a %u-byte host buffer); target "
                "%.3f, strength %.2f, at most %+.2f EV, no lift with %.0f%% sky or more (fading from "
                "%.0f%%), rises over %.1f s, falls over %.1f s; acts through the GT7/ACES exposure "
                "(tonemapper now: %s)\n",
                knobs.mode, knobs.mode == Policy::Show ? ", SHOW" : "", Policy::GridX, Policy::GridY,
                u32(sizeof(Slot) * SlotCount), knobs.target, knobs.strength, knobs.max_ev,
                Policy::SkyGone * 100.0f, Policy::SkyOpen * 100.0f, Policy::RiseSeconds,
                Policy::FallSeconds, ToneName(tone));
}
} // namespace

void Meter(const Instance& instance, Scheduler& scheduler, vk::ImageView color, vk::ImageView depth,
           u32 w, u32 h) {
    const Policy::Config& knobs = Policy::Knobs();
    if (knobs.mode == Policy::Off || !color || !depth || w == 0 || h == 0) {
        return;
    }
    static State& s = *new State;
    if (!s.tried) {
        s.tried = true;
        s.ready = EffectPass::Create(instance, s.set_layout, s.layout, s.pipeline,
                                     {vk::DescriptorType::eStorageImage,
                                      vk::DescriptorType::eSampledImage,
                                      vk::DescriptorType::eStorageBuffer},
                                     sizeof(Push), INTERIOR_METER_COMP, "Interior exposure (r99)") &&
                  MakeBuffer(instance, s);
        SayOn(knobs, s.ready);
        s.last_line = Clock::now();
    }
    if (!s.ready) {
        return;
    }
    const auto now = Clock::now();

    // The newest reading the GPU has finished; a slot that holds another frame's numbers is skipped.
    bool got = false;
    Slot newest{};
    u32 newest_frame = 0;
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
            got = true;
        }
    }
    if (got) {
        ++s.read;
        const Policy::Lift lift =
            Policy::Want(knobs, {newest.log_sum, newest.samples, newest.sky, newest.total});
        const float dt = s.have_read ? std::chrono::duration<float>(now - s.last_read).count() : 0.0f;
        s.have_read = true;
        s.last_read = now;
        if (lift.valid) {
            s.applied_ev = Policy::Step(s.applied_ev, lift.wanted_ev, dt);
            s.last = lift;
        } else {
            ++s.held;
        }
        Policy::applied_scale.store(std::exp2(s.applied_ev), std::memory_order_relaxed);
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
                        Policy::LumMin, Policy::LumMax};
        s.frame[slot] = s.next_frame;
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
        const auto& settings = BbSettings::Get();
        const int tone = settings.graphics_tonemapper.load(std::memory_order_relaxed);
        const float gt7 = settings.graphics_gt7_exposure.load(std::memory_order_relaxed);
        const float scale = Policy::Scale();
        std::printf("Interior exposure (r99): metered %.5f (log-average luminance before the tone "
                    "curve, sky left out), sky %.1f%%, indoor %.2f, wanted %+.2f EV, applied %+.3f EV "
                    "(x%.4f), GT7/ACES exposure %.2f -> %.3f (tonemapper: %s); %u meters, %u read, %u "
                    "held, %u busy since the last line\n",
                    s.last.metered, s.last.sky_share * 100.0f, s.last.indoor, s.last.wanted_ev,
                    s.applied_ev, scale, gt7, gt7 * scale, ToneName(tone), s.metered, s.read, s.held,
                    s.busy);
        s.metered = s.read = s.held = s.busy = 0;
    }
}

} // namespace Vulkan::InteriorExposure
''',

    "engine/tests/test_interior_exposure.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r99_interior-exposure): the interior exposure floor's knobs, rule and easing
// (gpu/shim/bbport_interior_exposure.h). Built and run by engine/build.sh --test and the CMake
// target interior-exposure-test.
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "gpu/shim/bbport_interior_exposure.h"

using namespace BbInteriorExposure;

static bool Near(float a, float b, float eps) {
    return std::fabs(a - b) <= eps;
}

// A reading of `ground` samples all at luminance `lum` and `sky` sky samples.
static Reading Scene(float lum, float ground, float sky) {
    Reading r;
    r.log_sum = std::log2(lum) * ground;
    r.samples = ground;
    r.sky = sky;
    r.total = ground + sky;
    return r;
}

int main() {
    const float all = float(GridX * GridY);
    // a. Knobs: off unless exactly "1" or "2"; defaults; SHOW's defaults; set values win; ranges.
    {
        const Config off = Parse(nullptr, nullptr, nullptr, nullptr);
        assert(off.mode == Off && off.target == DefaultTarget && off.strength == DefaultStrength &&
               off.max_ev == DefaultMaxEv);
        for (const char* m : {"", "0", "3", "12", "on", "1 ", "-1"}) {
            assert(Parse(m, nullptr, nullptr, nullptr).mode == Off);
        }
        const Config on = Parse("1", nullptr, nullptr, nullptr);
        assert(on.mode == On && on.target == DefaultTarget && on.strength == DefaultStrength &&
               on.max_ev == DefaultMaxEv);
        const Config show = Parse("2", nullptr, nullptr, nullptr);
        assert(show.mode == Show && show.target == ShowTarget && show.strength == ShowStrength &&
               show.max_ev == ShowMaxEv);
        const Config set = Parse("2", "0.02", "0.25", "1");
        assert(set.target == 0.02f && set.strength == 0.25f && set.max_ev == 1.0f);
        const Config high = Parse("1", "9", "-1", "7");
        assert(high.target == TargetMax && high.strength == 0.0f && high.max_ev == MaxEvLimit);
        const Config low = Parse("1", "0", "2", "-3");
        assert(low.target == TargetMin && low.strength == 1.0f && low.max_ev == 0.0f);
        const Config junk = Parse("1", "abc", "0.5x", "nan");
        assert(junk.target == DefaultTarget && junk.strength == DefaultStrength &&
               junk.max_ev == DefaultMaxEv);
        assert(Parse("1", "inf", "", nullptr).target == DefaultTarget);
        assert(DefaultMaxEv <= MaxEvLimit && ShowMaxEv <= MaxEvLimit && SkyOpen < SkyGone);
    }
    // b. The rule at the study's measured scenes (2026-11-15, hero light off, sky masked).
    const Config on = Parse("1", nullptr, nullptr, nullptr);
    const Config show = Parse("2", nullptr, nullptr, nullptr);
    {
        const Lift level = Want(on, Scene(0.01425f, all, 0)); // library, mod off, level
        assert(level.valid && Near(level.metered, 0.01425f, 1e-5f) && level.indoor == 1.0f);
        assert(Near(level.wanted_ev, std::log2(0.02f / 0.01425f), 1e-4f));
        assert(level.wanted_ev > 0.45f && level.wanted_ev < 0.53f);
        const Lift up = Want(on, Scene(0.01098f, all, 0)); // looking up
        assert(up.valid && up.wanted_ev > 0.83f && up.wanted_ev < 0.90f);
        const Lift mod = Want(on, Scene(0.00432f, all, 0)); // library, Remaster mod on
        assert(mod.valid && mod.wanted_ev == DefaultMaxEv);
        const Lift house = Want(on, Scene(0.05514f, all, 0)); // dream house: above the target
        assert(house.valid && house.wanted_ev == 0.0f);
        const Lift alley = Want(on, Scene(0.02509f, all, 0)); // dark alley, mod off: no sky seen
        assert(alley.valid && alley.indoor == 1.0f && alley.wanted_ev == 0.0f);
        const Lift alley_mod = Want(on, Scene(0.0097f, all, 0)); // with the mod: lifted (floor)
        assert(alley_mod.valid && alley_mod.wanted_ev > 1.0f && alley_mod.wanted_ev < 1.1f);
        const Lift at = Want(on, Scene(DefaultTarget, all, 0));
        assert(at.valid && Near(at.wanted_ev, 0.0f, 1e-5f));
        const Lift bright = Want(on, Scene(0.5f, all, 0)); // never darkens
        assert(bright.valid && bright.wanted_ev == 0.0f);
        const Lift house_show = Want(show, Scene(0.05514f, all, 0)); // SHOW lifts the house
        assert(Near(house_show.wanted_ev, std::log2(0.15f / 0.05514f), 1e-4f));
        assert(house_show.wanted_ev > 1.4f && house_show.wanted_ev < 1.5f);
        assert(Want(show, Scene(0.01425f, all, 0)).wanted_ev == ShowMaxEv);
        assert(Want(Parse("1", nullptr, "0", nullptr), Scene(0.001f, all, 0)).wanted_ev == 0.0f);
    }
    // c. The sky gate: up to SkyOpen full, from SkyGone none, half way between half.
    {
        const Lift full = Want(on, Scene(0.01425f, 97, 3));
        assert(full.valid && Near(full.indoor, 1.0f, 1e-5f) && full.wanted_ev > 0.45f);
        const Lift half = Want(on, Scene(0.01425f, 91, 9));
        assert(half.valid && Near(half.indoor, 0.5f, 1e-3f));
        assert(Near(half.wanted_ev, 0.5f * std::log2(0.02f / 0.01425f), 2e-3f));
        const Lift street = Want(on, Scene(0.01f, 80, 20));
        assert(street.valid && street.indoor == 0.0f && street.wanted_ev == 0.0f);
        const Lift sky_only = Want(on, Scene(1.0f, 0, all));
        assert(sky_only.valid && sky_only.metered == 0.0f && sky_only.wanted_ev == 0.0f);
    }
    // d. Readings that hold the lift: a black frame, nothing read, numbers that are not numbers.
    {
        assert(!Want(on, Scene(LumMin, all, 0)).valid);
        assert(!Want(on, Scene(BlackFrame * 0.5f, all, 0)).valid);
        assert(Want(on, Scene(BlackFrame * 2.0f, all, 0)).valid);
        assert(!Want(on, Reading{}).valid);
        Reading nan = Scene(0.01f, all, 0);
        nan.log_sum = std::nanf("");
        assert(!Want(on, nan).valid);
        Reading negative = Scene(0.01f, all, 0);
        negative.sky = -1.0f;
        assert(!Want(on, negative).valid);
    }
    // e. Easing: RiseSeconds up, FallSeconds down, steps clamped, never past the wanted lift.
    {
        assert(Near(Step(0.0f, 1.0f, 0.2f), 1.0f - std::exp(-0.2f / RiseSeconds), 1e-6f));
        assert(Near(Step(1.0f, 0.0f, 0.2f), std::exp(-0.2f / FallSeconds), 1e-6f));
        assert(Step(0.0f, 1.0f, 5.0f) == Step(0.0f, 1.0f, MaxStep));
        assert(Step(0.5f, 1.0f, -1.0f) == 0.5f && Step(0.5f, 1.0f, std::nanf("")) == 0.5f);
        float a = 0.0f;
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 1.2f, 1.0f / 60.0f);
            assert(b >= a && b <= 1.2f);
            a = b;
        }
        assert(Near(a, 1.2f, 1e-3f));
        for (int i = 0; i < 600; ++i) {
            const float b = Step(a, 0.0f, 1.0f / 60.0f);
            assert(b <= a && b >= 0.0f);
            a = b;
        }
        assert(Near(a, 0.0f, 1e-3f));
    }
    // f. The factor is exactly 1 until the meter writes it, so x * Scale() is x bit for bit.
    {
        assert(Scale() == 1.0f);
        for (const float x : {1.0f, 0.25f, 4.0f, 1.41f, 0.3333333f}) {
            const float y = x * Scale();
            assert(std::memcmp(&x, &y, sizeof x) == 0);
        }
        assert(std::exp2(0.0f) == 1.0f);
    }
    std::puts("interior-exposure-test: all checks passed");
    return 0;
}
''',
}

README_SECTION = r'''### Interior exposure (in development)

Part of the lamp work: a brighten-only exposure floor, so rooms lit only by lamps (tested with `graphics_disable_player_light=1`) read dim but legible instead of black. It is a floor on dark views, not an indoor test: it lifts any view metered below the target that shows little sky at depth 1, outdoors too. Measured with the hero light off (2026-11-15, no measured view had any sky at depth 1): the library 0.014 (looking up 0.011) gets +0.49 EV (+0.87 EV) at the defaults, the Hunter's Dream house 0.055 and the dark alley 0.025 without the BB PC Remaster mod get nothing, the library with the mod reaches the +1.5 EV cap and the dark alley with the mod (0.0097) gets about +1.0 EV. Off unless `BB_INTERIOR_EXPOSURE` is `1` or `2`. These environment variables are read once when the game starts; a missing or unreadable number takes the default, then the range is applied. They are for testing; no ini key yet.

| Variable | What it does | Default |
|---|---|---|
| `BB_INTERIOR_EXPOSURE` | `1` turns it on, `2` is the test setting with the exaggerated values in brackets below. At each frame the upscaler takes as an HDR scene (DLSS, FSR, XeSS or TAA before the game's post, as with `upscale_before_post=1`), one group of 256 threads takes 64x36 samples of the scene colour before the tone curve: samples at depth 1 (sky) are counted apart, the others give the log-average L of their Rec.709 luminance (each clamped to 0.0001..64, values pushed to the meter). A reading the GPU has finished is read back (a 128-byte host buffer, 4 frames in a ring). The lift in stops is min(max, strength x log2(target / L)), never below 0, times 1 - smoothstep(0.03, 0.15, sky share): no lift at or above the target, none with 15% or more sky among the samples. A reading with L below 0.0004 (a black or fading frame) keeps the lift as it is. The applied lift eases toward that in real time (1 s time constant while it grows, 0.4 s while it shrinks) and, as the factor 2^lift, multiplies the exposure of the GT7 or ACES tone map (`graphics_tonemapper`, times `graphics_gt7_exposure`); with the game's own curve or the HDR curve extension it changes nothing. With it on, the log has a line once and then every 2 s (1 s with `2`): `Interior exposure (r99): metered L ..., sky ...%, indoor ..., wanted ... EV, applied ... EV (x...), GT7/ACES exposure a -> b`; no such line means no frame went through that upscaler path. Cost: one dispatch of one group, 2304 samples, an estimate of 0.01 to 0.03 ms at 1080p internal, not measured; read it on the `Lighting: interior exposure meter` row of `BB_GPU_PROFILE=1`. Off, nothing is made or dispatched and the factor is exactly 1 | off |
| `BB_INTERIOR_EXPOSURE_TARGET` | The target L, a log-average luminance before the tone curve, 0.005 to 1 (measured with the hero light off: the library about 0.014, the dark alley about 0.025, the Hunter's Dream house about 0.055) | `0.02` (`0.15`) |
| `BB_INTERIOR_EXPOSURE_STRENGTH` | The share of the gap in stops the lift closes, 0 to 1 | `1` (`1`) |
| `BB_INTERIOR_EXPOSURE_MAX_EV` | The largest lift in stops, 0 to 3 | `1.5` (`3`) |

'''

# Edits: ("after", anchor, text) inserts `text` right after the line(s) `anchor`; ("before",
# anchor, text) right before them; ("replace", old, new). Anchors and texts are whole lines with
# their "\n"; each anchor must be found exactly once. An insertion is applied when its text is
# found once and is removed by its own text, so neighbours inserted later by other patches do not
# matter; a replacement is applied when `new` is found once and `old` is not.
EDITS = {
    R + "vk_temporal_upscaler.cpp": [
        ("after", '#include "video_core/renderer_vulkan/vk_hdr_native.h"\n',
         '#include "video_core/renderer_vulkan/vk_interior_exposure.h" // bbport (r99_interior-exposure)\n'),
        ("before", '    MarkUpscalerPart(4, "upscaler: evaluate (DLSS, FSR, XeSS or TAA)");\n',
         '    // bbport (r99_interior-exposure): meters this HDR scene for the interior exposure floor\n'
         '    // (only with BB_INTERIOR_EXPOSURE=1 or 2; otherwise it returns at once and makes nothing).\n'
         '    InteriorExposure::Meter(instance, scheduler, input_color_view, input_depth_view, w, h);\n'),
    ],
    R + "vk_pipeline_common.cpp": [
        ("after", '#include "bbport_settings.h"\n',
         '#include "bbport_interior_exposure.h" // bbport (r99_interior-exposure)\n'),
        ("replace", '            .exposure = settings.graphics_gt7_exposure.load(std::memory_order_relaxed),\n',
         '            // bbport (r99_interior-exposure): times the interior lift, exactly 1 unless\n'
         '            // BB_INTERIOR_EXPOSURE is on (gpu/shim/bbport_interior_exposure.h)\n'
         '            .exposure = settings.graphics_gt7_exposure.load(std::memory_order_relaxed) *\n'
         '                        BbInteriorExposure::Scale(),\n'),
    ],
    "engine/gpu/CMakeLists.txt": [
        ("after", 'add_host_shader(upscale_reactive.comp upscale_reactive_comp)\n',
         '# bbport (r99_interior-exposure): the interior exposure meter (made only with BB_INTERIOR_EXPOSURE=1 or 2)\n'
         'add_host_shader(interior_meter.comp interior_meter_comp)\n'),
        ("after", 'target_include_directories(exposure-policy-test PRIVATE ..)\n',
         '# bbport (r99_interior-exposure): the interior exposure floor\'s knobs, rule and easing\n'
         '# (shim/bbport_interior_exposure.h); also built and run by engine/build.sh --test.\n'
         'add_executable(interior-exposure-test EXCLUDE_FROM_ALL ../tests/test_interior_exposure.cpp)\n'
         'target_compile_options(interior-exposure-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n'
         'target_include_directories(interior-exposure-test PRIVATE ..)\n'),
    ],
    "engine/build.sh": [
        ("after", '    out/draw-tokens-test\n',
         '    # bbport (r99_interior-exposure): the interior exposure floor\'s knobs, rule and easing\n'
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_interior_exposure.cpp -o out/interior-exposure-test\n'
         '    out/interior-exposure-test\n'),
    ],
    "README.md": [
        ("before", '### Lamp fog shafts\n', README_SECTION),
    ],
}

# The README's defaults and the header's constants must agree.
TIES = [
    ("DefaultTarget = 0.02f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.02` (`0.15`)"),
    ("ShowTarget = 0.15f", "| `BB_INTERIOR_EXPOSURE_TARGET`", "`0.02` (`0.15`)"),
    ("DefaultStrength = 1.0f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`1` (`1`)"),
    ("ShowStrength = 1.0f", "| `BB_INTERIOR_EXPOSURE_STRENGTH`", "`1` (`1`)"),
    ("DefaultMaxEv = 1.5f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "`1.5` (`3`)"),
    ("ShowMaxEv = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "`1.5` (`3`)"),
    ("MaxEvLimit = 3.0f", "| `BB_INTERIOR_EXPOSURE_MAX_EV`", "0 to 3"),
    ("SkyOpen = 0.03f", "| `BB_INTERIOR_EXPOSURE` |", "smoothstep(0.03, 0.15"),
    ("SkyGone = 0.15f", "| `BB_INTERIOR_EXPOSURE` |", "15% or more sky"),
    ("BlackFrame = 4e-4f", "| `BB_INTERIOR_EXPOSURE` |", "below 0.0004"),
    ("RiseSeconds = 1.0f", "| `BB_INTERIOR_EXPOSURE` |", "1 s time constant while it grows"),
    ("FallSeconds = 0.4f", "| `BB_INTERIOR_EXPOSURE` |", "0.4 s while it shrinks"),
    ("GridX = 64, GridY = 36", "| `BB_INTERIOR_EXPOSURE` |", "64x36 samples"),
    ("LumMin = 1e-4f, LumMax = 64.0f", "| `BB_INTERIOR_EXPOSURE` |", "clamped to 0.0001..64"),
]
# The shader's constants and the header's.
# (review fix b: the clamp is pushed from the header, so the shader must not hold its own copy)
SHADER_TIES = [("Policy::LumMin, Policy::LumMax", "float lum_min; // each sample's luminance clamp"),
               ("float lum_min, lum_max;", "    float lum_max;\n};")]


def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")


def new_bytes(text):
    return text.replace("\n", "\r\n").encode("utf-8")


def edit_state(text, edit):
    kind, a, b = edit
    if kind == "replace":
        if text.count(b) == 1 and text.count(a) == 0: return "applied"
        if text.count(a) == 1 and text.count(b) == 0: return "clean"
        return "broken (old %d, new %d)" % (text.count(a), text.count(b))
    if text.count(b) == 1: return "applied"
    if text.count(b) == 0 and text.count(a) == 1: return "clean"
    return "broken (anchor %d, text %d)" % (text.count(a), text.count(b))


def apply_edit(text, edit):
    kind, a, b = edit
    if kind == "replace": return text.replace(a, b)
    if kind == "after": return text.replace(a, a + b)
    return text.replace(a, b + a)


def revert_edit(text, edit):
    kind, a, b = edit
    if kind == "replace": return text.replace(b, a)
    return text.replace(b, "", 1)


def text_checks(texts):
    header = NEW["engine/gpu/shim/bbport_interior_exposure.h"]
    shader = NEW[H + "interior_meter.comp"]
    for const, row, value in TIES:
        lines = [l for l in texts["README.md"].split("\n") if l.startswith(row)]
        if header.count(const) != 1 or len(lines) != 1 or value not in lines[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    cpp = NEW[R + "vk_interior_exposure.cpp"]
    for const, glsl in SHADER_TIES:
        if cpp.count(const) != 1 or shader.count(glsl) != 1:
            raise SystemExit("tie check: %r against the shader's %r" % (const, glsl))
    if "LUM_MIN" in shader or "LUM_MAX" in shader or "static_assert(sizeof(Push) == 32);" not in cpp:
        raise SystemExit("tie check: the shader must take the clamp from the push block (32 bytes)")
    up = texts[R + "vk_temporal_upscaler.cpp"]
    call = up.find("InteriorExposure::Meter(instance, scheduler, input_color_view, input_depth_view, w, h);")
    if not (up.find("void TemporalUpscaler::Run() {") < up.find("const bool has_reactive = mask_ready || RecordReactive(input_color_view);") < call
            < up.find('MarkUpscalerPart(4, "upscaler: evaluate (DLSS, FSR, XeSS or TAA)");') < up.find("void TemporalUpscaler::RunUiOnly(")):
        raise SystemExit("order check: the meter call is not in TemporalUpscaler::Run between the reactive mask and the evaluate")
    pc = texts[R + "vk_pipeline_common.cpp"]
    if pc.count("BbInteriorExposure::Scale()") != 1 or pc.find("const Shader::Native::Gt7Push tone_map{") > pc.find("BbInteriorExposure::Scale()"):
        raise SystemExit("order check: the factor is not in the Gt7Push of BindResources")
    cm = texts["engine/gpu/CMakeLists.txt"]
    if cm.count("interior_meter.comp") != 1 or cm.count("interior-exposure-test") != 3:
        raise SystemExit("CMake check")
    for path, text in NEW.items():
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)
    if not all(ord(c) < 128 for c in README_SECTION):
        raise SystemExit("README section must be ASCII")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R99_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        states = [edit_state(cur, e) for e in edits]
        for e, st in zip(edits, states):
            if st.startswith("broken"):
                raise SystemExit("%s: edit %r: %s" % (path, e[1][:70], st))
        if len(set(states)) != 1:
            raise SystemExit("%s: some edits applied, some not: %s" % (path, states))
        plan.append((path, edits, raw, eol, cur, states[0]))
    for path, text in NEW.items():
        full = os.path.join(ROOT, path)
        if not os.path.exists(full): state = "clean"
        elif open(full, "rb").read() == new_bytes(text): state = "applied"
        else: raise SystemExit("%s exists and is not this patch's file" % path)
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
                for e in edits: cur = apply_edit(cur, e)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(edited), len(NEW)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in edited:
            for e in edits: cur = apply_edit(cur, e)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        for path, text in NEW.items():
            outs.append((path, new_bytes(text), None))
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            if raw is not None:
                open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r99tmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r99tmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in edited:
        for e in reversed(edits): cur = revert_edit(cur, e)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted")


main()
