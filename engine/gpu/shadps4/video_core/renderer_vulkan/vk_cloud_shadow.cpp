// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r105_cloud-shadows): FEATURE, slow moving cloud shadows (vk_cloud_shadow.h says what
// is dimmed and what is not; cloud_shadow_params.h the knobs and rules).
#include "video_core/renderer_vulkan/vk_cloud_shadow.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "bbport_toggles.h"
#include "video_core/host_shaders/cloud_shadow_comp.h"
#include "video_core/host_shaders/cloud_shadow_gate_comp.h"
#include "video_core/renderer_vulkan/vk_effect_pass.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"

namespace Vulkan {
namespace {
namespace CS = CloudShadows;

constexpr auto Compute = vk::PipelineStageFlagBits2::eComputeShader;
/// The GPU profile row (BB_GPU_PROFILE=1): "Lighting: cloud shadows", both passes.
constexpr u64 ProfileRow = 105;

CloudShadow* active = nullptr;

/// The knobs, read once.
const CS::Knobs& Load() {
    static const CS::Knobs knobs =
        CS::MakeKnobs(std::getenv("BB_CLOUD_SHADOWS"), std::getenv("BB_CLOUD_SHADOWS_SCALE"),
                      std::getenv("BB_CLOUD_SHADOWS_SHOW"), std::getenv("BB_CLOUDS_DIR"),
                      std::getenv("BB_WIND_DIR"), std::getenv("BB_WIND_SPEED")); // r105b
    return knobs;
}

double Seconds() {
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

/// The barriers around a pass that reads and writes an image the GPU wrote just before (the ray
/// traced sun's filter, the gate's trace) and that the game or the march reads right after.
void Before(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eAllCommands,
                              vk::AccessFlagBits2::eMemoryWrite, Compute,
                              vk::AccessFlagBits2::eShaderRead | vk::AccessFlagBits2::eShaderWrite);
}

void After(vk::CommandBuffer cmd) {
    EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                              vk::PipelineStageFlagBits2::eAllCommands,
                              vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite);
}
} // namespace

bool CloudShadow::Wanted() {
    return Load().On();
}

CloudShadow* CloudShadow::Active() noexcept {
    return active;
}

CloudShadow::CloudShadow(const Instance& instance_, Scheduler& scheduler_)
    : instance{instance_}, scheduler{scheduler_}, knobs{Load()} {
    active = this;
    // bbport (r105b_clouds-visible): the speed is a multiple of the wind's; the direction is the
    // wind's with BB_WIND=1 (read here as Rasterizer::WindOnFrameEnd reads it: starts with 1)
    const char* wind_env = std::getenv("BB_WIND");
    const bool wind_on = wind_env != nullptr && wind_env[0] == '1';
    BbReport::Printf("Cloud shadows (r105, BB_CLOUD_SHADOWS=%.2f%s): a full cloud keeps %.0f%% of "
                     "the sun or moon light, clear below n %.2f, full above %.2f, size %.0f m, "
                     "%.1f m/s (%.0fx the wind's %.2f m/s) toward %s; needs the ray traced sun "
                     "or the VSM\n", // under 300 characters (the slot runs keep that much)
                     double(knobs.strength), knobs.show ? ", SHOW" : "",
                     100.0 * (1.0 - double(knobs.Depth())), double(knobs.LowEdge()),
                     double(knobs.HighEdge()), double(knobs.scale), double(knobs.Velocity()),
                     double(knobs.show ? CS::ShowSpeedRatio : CS::SpeedRatio),
                     double(knobs.wind_speed),
                     wind_on ? "the wind (BB_WIND=1; BB_CLOUDS_DIR ignored)"
                     : knobs.dir == CS::Source::Env  ? "BB_CLOUDS_DIR"
                     : knobs.dir == CS::Source::Auto ? "auto (across the light)"
                                                     : "the wind's BB_WIND_DIR (wind off)");
}

CloudShadow::~CloudShadow() {
    if (active == this) {
        active = nullptr;
    }
}

bool CloudShadow::Ready() {
    if (tried) {
        return !failed;
    }
    tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR8G8B8A8Unorm) &&
        EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) &&
        EffectPass::CreateSampler(instance, sampler, vk::Filter::eNearest) &&
        EffectPass::Create(instance, ground_set_layout, ground_layout, ground_pipeline,
                           {eStorageBuffer, eCombinedImageSampler, eStorageImage},
                           sizeof(CS::Push), CLOUD_SHADOW_COMP, "Cloud shadows") &&
        EffectPass::Create(instance, gate_set_layout, gate_layout, gate_pipeline,
                           {eStorageBuffer, eStorageBuffer, eStorageImage}, sizeof(CS::Push),
                           CLOUD_SHADOW_GATE_COMP, "Cloud shadows (sun fog)");
    if (!made) {
        failed = true;
        BbReport::Printf("Cloud shadows (r105): off - this GPU cannot run the passes\n");
    }
    return made;
}

void CloudShadow::SetSunLight(const std::array<float, 3>& world,
                              const std::array<float, 12>& view_to_world, bool valid) {
    ++resolves;
    light = world;
    rows = view_to_world;
    light_valid = valid;
}

void CloudShadow::OnFrameEnd(bool wind_on, float wind_deg, float wind_speed, float cover_shift) {
    const double now = Seconds();
    const double seconds = clock_last < 0.0 ? 0.0 : now - clock_last;
    clock_last = now;
    state.Advance(knobs, wind_on, wind_deg, light_valid, light, seconds, wind_speed, cover_shift);
    ground_last = ground_now;
    ground_now = false;
    ++frames;
    const bool due = knobs.show ? std::floor(state.Time() / CS::ShowPeriod) !=
                                      std::floor(said_at / CS::ShowPeriod)
                                : frames >= CS::PeriodFrames;
    if (!due) {
        return;
    }
    said_at = state.Time();
    const auto c0 = state.Offsets().Cells(0);
    const double elevation =
        light_valid ? std::asin(std::clamp(double(light[1]), -1.0, 1.0)) * 57.29577951308232 : 0.0;
    // Kept under 300 characters (the slot runs keep that much of a line).
    BbReport::Printf("Cloud shadows (r105): %u frames, %u ground passes (%u resolves without the ray "
                     "traced sun, %u without a light), %u sun fog passes (%u skipped), toward %.0f "
                     "deg (%s), offset %.2f %.2f, light %.0f deg up\n",
                     frames, ground_passes, resolves > ground_calls ? resolves - ground_calls : 0u,
                     unlit, gate_passes, gate_skipped, double(state.Direction()),
                     CS::SourceName(state.From()), double(c0[0]), double(c0[2]), elevation);
    frames = resolves = unlit = ground_calls = ground_passes = gate_passes = gate_skipped = 0;
}

void CloudShadow::Ground(const ContactShadow::Inputs& in, vk::ImageView depth,
                         vk::ImageView target, u32 width, u32 height) {
    ++ground_calls; // a resolve the ray traced sun (or the VSM) wrote
    if (!light_valid) {
        ++unlit;
        return;
    }
    if (!depth || !target || width == 0 || height == 0 || !in.constants || !Ready()) {
        return;
    }
    ground_now = true;
    ++ground_passes;
    // Every value is made before the capture list (nothing in it is moved).
    const CS::Push push =
        CS::MakePush(rows, state, knobs, light, in.constants_offset_word & 0xFFFFu, 0.0f);
    EffectPass::Mark(ProfileRow, "cloud shadows");
    scheduler.RecordCrumb(
        {.name = "Cloud shadows"},
        [push, width, height, depth, target, sampler = *sampler, constants = in.constants,
         constants_offset = in.constants_offset, constants_range = in.constants_range,
         pipeline = *ground_pipeline, layout = *ground_layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const vk::DescriptorBufferInfo cb{constants, constants_offset, constants_range};
            const vk::DescriptorImageInfo depth_info{sampler, depth, vk::ImageLayout::eGeneral};
            const vk::DescriptorImageInfo target_info{{}, target, vk::ImageLayout::eGeneral};
            const std::array writes{
                vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageBuffer,
                                       .pBufferInfo = &cb},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                                       .pImageInfo = &depth_info},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &target_info}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + 7) / 8, (height + 7) / 8, 1);
            After(cmd);
        });
}

void CloudShadow::Gate(const ContactShadow::Inputs& in, vk::ImageView gate, u32 width, u32 height,
                       u32 slices, float reach) {
    if (!ground_last || !light_valid) {
        ++gate_skipped;
        return;
    }
    if (!gate || !in.constants || !in.uniforms || !Ready()) {
        return;
    }
    ++gate_passes;
    const CS::Push push =
        CS::MakePush(rows, state, knobs, light, in.constants_offset_word & 0xFFFFu, reach);
    EffectPass::Mark(ProfileRow, "cloud shadows");
    scheduler.RecordCrumb(
        {.name = "Cloud shadows (sun fog gate)"},
        [push, width, height, slices, gate, constants = in.constants,
         constants_offset = in.constants_offset, constants_range = in.constants_range,
         uniforms = in.uniforms, uniforms_offset = in.uniforms_offset,
         uniforms_range = in.uniforms_range, pipeline = *gate_pipeline,
         layout = *gate_layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const vk::DescriptorBufferInfo cb{constants, constants_offset, constants_range};
            const vk::DescriptorBufferInfo ub{uniforms, uniforms_offset, uniforms_range};
            const vk::DescriptorImageInfo gate_info{{}, gate, vk::ImageLayout::eGeneral};
            const std::array writes{
                vk::WriteDescriptorSet{.dstBinding = 0, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageBuffer,
                                       .pBufferInfo = &cb},
                vk::WriteDescriptorSet{.dstBinding = 1, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageBuffer,
                                       .pBufferInfo = &ub},
                vk::WriteDescriptorSet{.dstBinding = 2, .descriptorCount = 1,
                                       .descriptorType = vk::DescriptorType::eStorageImage,
                                       .pImageInfo = &gate_info}};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(push), &push);
            cmd.dispatch((width + 3) / 4, (height + 3) / 4, (slices + 3) / 4);
            After(cmd);
        });
}

} // namespace Vulkan
