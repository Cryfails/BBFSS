# r51b_volumetric-rt-check: stage B of the volumetric sun leak fix, on top of r51 (stage A).
#
# Why: the r51 game test (2026-11-15 11:2x, save copy dark-interior, a roofed library) showed that
# stage A changes nothing there: BB_VOLUMETRIC_OCCLUSION 1, 3 and 7 look like 0 with the BB PC
# Remaster mod on and off. The log says why: the cascades the march reads in that room DO hold
# casters (c0 and c1 get 55-75 draws a frame, in every frame), so "empty cascade" (A1) is not the
# cause, and A2 (darkest answer of every cascade) changes nothing either, so no cascade of the
# game's sun atlas holds the ceiling above the hazy air. With the mod on the game's splits are
# 20 / 40 / 150 m (the whole room in c0), without it 2 / 8 / 15 m. A2 doubled the pass's GPU time
# (0.198 -> 0.431 ms at dark-interior, mod off) for no visible change.
#
# What: one ray toward the sun from the centre of every cell of a fixed 160 x 90 x 32 grid in
# front of the camera (columns and rows across the screen, 32 slices in the square root of the
# distance out to the shadow distance or the 40 m reach, whichever is shorter), traced through
# the frame's ray traced scene (RtShadow::Scene, the same TLAS the ray traced sun traces, in the
# camera's view space). 1 where the ray left the scene, 0 where it hit. The march (new GATE
# builds of the INTEGRATE and REPAIR passes) multiplies its atlas answer by the gate, read
# trilinearly, only where the atlas said lit. The gate only removes light, never adds it.
#
# Knob: environment variable BB_VOLUMETRIC_RT_GATE, read once (restart per value): the
# instance mask the gate's rays trace. 0, unset or anything else: no gate, the passes and
# pipelines of stage A exactly as before (the gate's pipelines are not even made). 1: the sun's
# casters (rt_shadow.comp's mask 0x01). 2: the camera pass's geometry. 3: both. Needs ray
# tracing with a scene (graphics_rt_sun=1, or ray traced lamps or bounce); without one the
# march stays stage A's and the 600-march log line says so. BB_VOLUMETRIC_OCCLUSION is
# independent (stage A bits as before).
#
# Cost (NOT MEASURED): 460,800 rays a frame whatever the resolution (the ray traced sun traced
# 1.46 M rays in 0.104 ms on this machine: about 0.03 ms by scaling, more for open-air rays that
# run to 800 m without a hit) plus one trilinear fetch per lit march sample (16.6 M at most at
# 960x540, 66 M at 1920x1080 half resolution for 4K output). Estimate 0.05-0.15 ms at 1080p,
# up to 0.3 ms at 4K output. The profile row is "Lighting: volumetric sun gate" (mark 51) for the
# rays; the fetches count in "Lighting: volumetric sunlight". No reuse over frames (the scene is
# rebuilt in view space each frame; reuse would need reprojection).
#
# Files: host_shaders/volumetric_light.comp (GATE: binding 6, repair 7, GateRange, GateAt, the
# march multiply; the builds without GATE compile to the same SPIR-V as before),
# host_shaders/volumetric_rt_gate.comp (NEW), renderer_vulkan/volumetric_occlusion.h
# (ParseRtGate, RtGateMask), renderer_vulkan/vk_volumetric_light.h (SetSunScene, members),
# renderer_vulkan/vk_volumetric_light.cpp (GateReady, RecordGate, gated pipelines in
# Integrate, log lines), renderer_vulkan/vk_rasterizer_effects.cpp (SetSunScene before
# Integrate at the shadow resolve), engine/gpu/CMakeLists.txt (three shader builds).
#
# Use: cd <tree> && python -I -X utf8 r51b_volumetric-rt-check.py check | apply | revert
# (root from R51B_ROOT, else the current directory). Files keep their line ends (CRLF in the
# tree; the new file is written with the line ends of volumetric_light.comp). Originals are kept
# in r51b_backup/ next to this script. Needs r51 applied (its anchors hold r51's text). Apply
# refuses if the new file exists; revert deletes it only if its text is what apply wrote.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r51b_backup")
ROOT = os.environ.get("R51B_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW_SHADER = r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r51b_volumetric-rt-check): the ray traced sun gate of the volumetric sunlight. One ray
// toward the sun from the centre of every cell of a grid in front of the camera: columns and rows
// across the screen, slices in the square root of the distance out to the gate's range (the
// shadow distance when it is shorter than the march's reach, else the reach; GateRange in
// volumetric_light.comp). 1 where the ray left the scene, 0 where it hit something. The march's
// GATE builds multiply their atlas answer by it, so the gate only removes light: a roof or a
// bridge that no cascade of the game's sun atlas holds but the ray traced scene does
// (RtShadow::PrepareScene: this frame's instances in the camera's view space) no longer lets the
// sun into the fog under it.
#version 460
#extension GL_EXT_scalar_block_layout : require
#extension GL_EXT_ray_query : require

layout(local_size_x = 4, local_size_y = 4, local_size_z = 4) in;

layout(scalar, binding = 0) readonly buffer ShadowConstants { uint d[]; } cb;
layout(scalar, binding = 1) readonly buffer SceneConstants { uint d[]; } ub;
layout(binding = 2) uniform accelerationStructureEXT scene;
layout(binding = 3, r8) uniform writeonly image3D gate_out;

layout(push_constant) uniform Params {
    uint offsets;       // as the march's: bits 0-7 the shadow constants' bytes, 8-15 the uniforms'
    float reach;        // the march's reach (m)
    uint mask;          // the scene's instance mask (BB_VOLUMETRIC_RT_GATE)
    float max_distance; // how far a ray looks for a hit (m), as the ray traced sun's
};

shared mat4 shared_inverse_projection;
shared vec3 shared_direction;
shared float shared_range;
shared uint shared_valid;

uint base;
float c(int i) { return uintBitsToFloat(cb.d[base + uint(i)]); }
vec4 row(int i) { return vec4(c(i), c(i + 1), c(i + 2), c(i + 3)); }

// As volumetric_light.comp's prepare(): the camera's inverse projection and the direction toward
// the sun from cascade 0's light matrix; and the gate's range as its GateRange() reads it.
void prepare() {
    shared_inverse_projection = transpose(mat4(row(0), row(4), row(8), row(12)));
    mat4 projection = inverse(shared_inverse_projection);
    mat4 light = transpose(mat4(row(16), row(20), row(24), row(28))) * projection;
    vec3 a = vec3(light[0][0], light[1][0], light[2][0]);
    vec3 b = vec3(light[0][1], light[1][1], light[2][1]);
    vec3 z = vec3(light[0][2], light[1][2], light[2][2]);
    vec3 direction = cross(a, b);
    uint ubase = ((offsets >> 8) & 255u) >> 2;
    float d = uintBitsToFloat(ub.d[ubase + 72u]);
    shared_range = d > 0.0 && d < reach ? d : reach;
    shared_valid = 0u;
    if (any(isnan(direction)) || any(isinf(direction)) || dot(direction, direction) < 1e-16) return;
    direction = normalize(direction);
    shared_direction = dot(z, direction) > 0.0 ? -direction : direction;
    shared_valid = 1u;
}

void main() {
    base = (offsets & 255u) >> 2;
    if (gl_LocalInvocationIndex == 0u) prepare();
    barrier();

    ivec3 cell = ivec3(gl_GlobalInvocationID);
    ivec3 size = imageSize(gate_out);
    if (any(greaterThanEqual(cell, size))) return;
    // Open (1) where nothing can be asked: the march keeps the atlas's answer there.
    float open = 1.0;
    vec2 uv = (vec2(cell.xy) + 0.5) / vec2(size.xy);
    vec4 h = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.5, 1.0);
    if (shared_valid != 0u && abs(h.w) >= 1e-8) {
        vec3 ray = h.xyz / h.w;
        float len = length(ray);
        if (ray.z > 0.0 && len > 0.0) {
            float s = (float(cell.z) + 0.5) / float(size.z);
            vec3 p = ray / len * (shared_range * s * s);
            rayQueryEXT query;
            rayQueryInitializeEXT(query, scene, gl_RayFlagsTerminateOnFirstHitEXT | gl_RayFlagsOpaqueEXT,
                                  mask, p, 0.02, shared_direction, max_distance);
            rayQueryProceedEXT(query);
            open = rayQueryGetIntersectionTypeEXT(query, true) ==
                           gl_RayQueryCommittedIntersectionNoneEXT
                       ? 1.0
                       : 0.0;
        }
    }
    imageStore(gate_out, cell, vec4(open));
}
'''

NEW_FILES = {H + "volumetric_rt_gate.comp": (NEW_SHADER, H + "volumetric_light.comp")}

EDITS = {
    H + "volumetric_light.comp": [
        (r'''#ifdef REPAIR
layout(binding = 6, rgba16f) uniform readonly image2D half_fog;
#endif
''', r'''#ifdef REPAIR
layout(binding = 6, rgba16f) uniform readonly image2D half_fog;
#endif
#ifdef GATE
// bbport (r51b_volumetric-rt-check): the ray traced sun gate (volumetric_rt_gate.comp): 1 where a
// ray from the cell toward the sun left the scene, 0 where it hit; cells across the screen and in
// the square root of the distance over GateRange().
#ifdef REPAIR
layout(binding = 7) uniform sampler3D sun_gate;
#else
layout(binding = 6) uniform sampler3D sun_gate;
#endif
#endif
'''),
        (r'''    return answer <= 1.0 ? answer : 0.0;
}
''', r'''    return answer <= 1.0 ? answer : 0.0;
}

#ifdef GATE
// bbport (r51b_volumetric-rt-check): the gate's depth, as volumetric_rt_gate.comp lays it out: the
// shadow distance when it is shorter than the reach (past it the fade is 0), else the reach.
float GateRange() {
    float d = shared_coverage.x;
    return d > 0.0 && d < reach ? d : reach;
}

float GateAt(vec2 uv, float t, float range) {
    return textureLod(sun_gate, vec3(uv, sqrt(clamp(t / range, 0.0, 1.0))), 0.0).r;
}
#endif
'''),
        (r'''    for (uint i = 0u; i < steps; ++i) {
        float t = (float(i) + jitter) * ds;
        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
    }
''', r'''#ifdef GATE
    float gate_range = GateRange();
#endif
    for (uint i = 0u; i < steps; ++i) {
        float t = (float(i) + jitter) * ds;
#ifdef GATE
        // bbport (r51b_volumetric-rt-check): the atlas's answer, then the ray traced gate's
        float v = visibility(ray * t, texel);
        if (v > 0.0) v *= GateAt(uv, t, gate_range);
        energy += exp(-density * t) * density * ds * v;
#else
        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
#endif
    }
'''),
    ],
    R + "volumetric_occlusion.h": [
        (r'''/// The knob, read once.
inline std::uint32_t Bits() {
    static const std::uint32_t bits = Parse(std::getenv("BB_VOLUMETRIC_OCCLUSION"));
    return bits;
}
''', r'''/// The knob, read once.
inline std::uint32_t Bits() {
    static const std::uint32_t bits = Parse(std::getenv("BB_VOLUMETRIC_OCCLUSION"));
    return bits;
}

/// bbport (r51b_volumetric-rt-check): BB_VOLUMETRIC_RT_GATE's text, the instance mask the ray
/// traced sun gate traces: "1" the sun's casters (rt_shadow.comp's mask), "2" the camera pass's
/// geometry, "3" both. "0", unset, empty or anything else: 0, no gate (stage A exactly).
inline std::uint32_t ParseRtGate(const char* text) {
    if (!text || text[0] < '0' || text[0] > '3' || text[1] != '\0') {
        return 0;
    }
    return std::uint32_t(text[0] - '0');
}

/// The gate's knob, read once.
inline std::uint32_t RtGateMask() {
    static const std::uint32_t mask = ParseRtGate(std::getenv("BB_VOLUMETRIC_RT_GATE"));
    return mask;
}
'''),
    ],
    R + "vk_volumetric_light.h": [
        (r'''    /// How far the last Integrate marched through the sun atlas (m); 0: it did not sample it.
''', r'''    /// bbport (r51b_volumetric-rt-check): this frame's ray traced scene (RtShadow::Scene, in the
    /// camera's view space) and the instance mask the sun gate traces (BB_VOLUMETRIC_RT_GATE),
    /// for the next Integrate. A null scene or mask 0: no gate, the march of stage A.
    void SetSunScene(vk::AccelerationStructureKHR scene_, u32 mask) noexcept {
        sun_scene = scene_;
        sun_scene_mask = mask;
    }
    /// How far the last Integrate marched through the sun atlas (m); 0: it did not sample it.
'''),
        (r'''    void EnsureImage(u32 width, u32 height);
    bool Enabled();
''', r'''    void EnsureImage(u32 width, u32 height);
    bool Enabled();
    // bbport (r51b_volumetric-rt-check): the sun gate's passes and image, made at first use
    bool GateReady();
    void RecordGate(const ContactShadow::Inputs& in, u32 offsets);
'''),
        (r'''    float atlas_reach = 0.0f;
    bool ready = false;
''', r'''    float atlas_reach = 0.0f;
    // bbport (r51b_volumetric-rt-check): the ray traced sun gate (SetSunScene, GateReady)
    vk::AccelerationStructureKHR sun_scene{};
    u32 sun_scene_mask = 0;
    Pass gate_volume, integrate_gated, repair_gated;
    vk::UniqueSampler gate_sampler;
    VideoCore::UniqueImage gate;
    vk::UniqueImageView gate_view;
    u64 gate_marches = 0, gate_traced = 0;
    bool gate_tried = false, gate_failed = false;
    bool ready = false;
'''),
    ],
    R + "vk_volumetric_light.cpp": [
        (r'''#include "video_core/host_shaders/point_volumetric_comp.h"
''', r'''#include "video_core/host_shaders/point_volumetric_comp.h"
// bbport (r51b_volumetric-rt-check): the ray traced sun gate and the march's builds reading it
#include "video_core/host_shaders/volumetric_light_integrate_gate_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_comp.h"
#include "video_core/host_shaders/volumetric_rt_gate_comp.h"
'''),
        (r'''static_assert(sizeof(Params) == 32);
''', r'''static_assert(sizeof(Params) == 32);
// bbport (r51b_volumetric-rt-check): the ray traced sun gate's cells (columns, rows, depth slices),
// the same whatever the resolution, and how far its rays look for a hit (the ray traced sun's).
constexpr u32 GateWidth = 160, GateHeight = 90, GateSlices = 32;
constexpr float GateMaxDistance = 800.0f;
struct GateParams {
    u32 offsets;
    float reach;
    u32 mask;
    float max_distance;
};
static_assert(sizeof(GateParams) == 16);
'''),
        (r'''void VolumetricLight::EnsureImage(u32 w, u32 h) {
''', r'''// bbport (r51b_volumetric-rt-check): made at the gate's first use, only with BB_VOLUMETRIC_RT_GATE
// and a ray traced scene, so a GPU without ray queries never makes them. Failing leaves the march
// as stage A left it.
bool VolumetricLight::GateReady() {
    if (gate_tried) {
        return !gate_failed;
    }
    gate_tried = true;
    using enum vk::DescriptorType;
    const bool made =
        EffectPass::StorageFormat(instance, vk::Format::eR8Unorm) &&
        EffectPass::HasRoom(instance, u64(GateWidth) * GateHeight * GateSlices) &&
        EffectPass::CreateSampler(instance, gate_sampler, vk::Filter::eLinear) &&
        CreatePass(gate_volume, {eStorageBuffer, eStorageBuffer, eAccelerationStructureKHR, eStorageImage},
                   VOLUMETRIC_RT_GATE_COMP, sizeof(GateParams), "Volumetric sun gate") &&
        CreatePass(integrate_gated,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_INTEGRATE_GATE_COMP, sizeof(Params), "Volumetric integrate (gate)") &&
        CreatePass(repair_gated,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage, eCombinedImageSampler},
                   VOLUMETRIC_LIGHT_REPAIR_GATE_COMP, sizeof(Params), "Volumetric repair (gate)");
    if (!made) {
        gate_failed = true;
        std::printf("Volumetric lighting (r51b): ray traced sun gate off - its passes could not be "
                    "made; the march stays as stage A\n");
        return false;
    }
    const auto device = instance.GetDevice();
    gate = VideoCore::UniqueImage(device, instance.GetAllocator());
    gate.Create({
        .imageType = vk::ImageType::e3D,
        .format = vk::Format::eR8Unorm,
        .extent = {GateWidth, GateHeight, GateSlices}, .mipLevels = 1, .arrayLayers = 1,
        .samples = vk::SampleCountFlagBits::e1,
        .tiling = vk::ImageTiling::eOptimal,
        .usage = vk::ImageUsageFlagBits::eStorage | vk::ImageUsageFlagBits::eSampled,
        .initialLayout = vk::ImageLayout::eUndefined,
    });
    gate_view = Check<"create volumetric sun gate view">(device.createImageViewUnique({
        .image = vk::Image(gate), .viewType = vk::ImageViewType::e3D,
        .format = vk::Format::eR8Unorm, .subresourceRange = ColorRange,
    }));
    SetObjectName(device, vk::Image(gate), "Volumetric sun gate (ray traced)");
    std::printf("Volumetric lighting (r51b): ray traced sun gate, %ux%ux%u cells, one ray each, "
                "scene mask 0x%x (BB_VOLUMETRIC_RT_GATE)\n",
                GateWidth, GateHeight, GateSlices, sun_scene_mask);
    return true;
}

// bbport (r51b_volumetric-rt-check): one ray toward the sun from the centre of every cell, before
// the march (volumetric_rt_gate.comp).
void VolumetricLight::RecordGate(const ContactShadow::Inputs& in, u32 offsets) {
    const GateParams params{offsets, reach, sun_scene_mask, GateMaxDistance};
    const vk::DescriptorBufferInfo cb{in.constants, in.constants_offset, in.constants_range};
    const vk::DescriptorBufferInfo ub{in.uniforms, in.uniforms_offset, in.uniforms_range};
    const vk::DescriptorImageInfo out{{}, *gate_view, vk::ImageLayout::eGeneral};
    EffectPass::Mark(51, "volumetric sun gate");
    scheduler.RecordCrumb(
        {.name = "Volumetric sun gate (ray traced)"},
        [params, cb, ub, out, scene = sun_scene, image = vk::Image(gate),
         pipeline = *gate_volume.pipeline, layout = *gate_volume.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const vk::ImageMemoryBarrier2 barrier{
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryRead | vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = Compute, .dstAccessMask = vk::AccessFlagBits2::eShaderWrite,
                .oldLayout = vk::ImageLayout::eUndefined, .newLayout = vk::ImageLayout::eGeneral,
                .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                .image = image, .subresourceRange = ColorRange,
            };
            cmd.pipelineBarrier2({.imageMemoryBarrierCount = 1, .pImageMemoryBarriers = &barrier});
            const vk::WriteDescriptorSetAccelerationStructureKHR scene_info{
                .accelerationStructureCount = 1, .pAccelerationStructures = &scene};
            const std::array<vk::WriteDescriptorSet, 4> writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &cb},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &ub},
                {.pNext = &scene_info, .dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eAccelerationStructureKHR},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageImage, .pImageInfo = &out},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0, writes);
            cmd.pushConstants(layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params), &params);
            cmd.dispatch((GateWidth + 3) / 4, (GateHeight + 3) / 4, (GateSlices + 3) / 4);
            After(cmd);
        });
}

void VolumetricLight::EnsureImage(u32 w, u32 h) {
'''),
        (r'''    atlas_reach = live_strength > 0.0f ? reach : 0.0f;
''', r'''    atlas_reach = live_strength > 0.0f ? reach : 0.0f;
    // bbport (r51b_volumetric-rt-check): with BB_VOLUMETRIC_RT_GATE and this frame's ray traced
    // scene (SetSunScene), one ray toward the sun from each cell of the gate first; the march then
    // multiplies its atlas answer by the gate. Without them the march is stage A's, unchanged.
    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
    if (live_strength > 0.0f && VolumetricOcclusion::RtGateMask() != 0) {
        gate_traced += gated ? 1 : 0;
        if (++gate_marches % 600 == 0) {
            std::printf("Volumetric lighting (r51b): ray traced sun gate on %llu of 600 marches, "
                        "BB_VOLUMETRIC_RT_GATE %u (0 of 600: no ray traced scene, stage A only)\n",
                        static_cast<unsigned long long>(gate_traced), sun_scene_mask);
            gate_traced = 0;
        }
    }
    if (gated) {
        RecordGate(in, in.constants_offset_word);
    }
    sun_scene = vk::AccelerationStructureKHR{};
    const vk::DescriptorImageInfo gi{*gate_sampler, *gate_view, vk::ImageLayout::eGeneral};
'''),
        (r'''        const auto& pass = repairing ? repair : integrate;
''', r'''        // bbport (r51b_volumetric-rt-check): the builds reading the gate (binding 6, repair 7)
        const auto& pass = repairing ? (gated ? repair_gated : repair)
                                     : (gated ? integrate_gated : integrate);
'''),
        (r'''        [params, di, si, out, repaired, zout, in, repairing,
''', r'''        [params, di, si, out, repaired, zout, in, repairing, gi, gated,
'''),
        (r'''            const std::array<vk::WriteDescriptorSet, 7> writes{{
''', r'''            std::array<vk::WriteDescriptorSet, 8> writes{{
'''),
        (r'''            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), repairing ? 7u : 6u});
''', r'''            }};
            // bbport (r51b_volumetric-rt-check): the gate after the pass's own bindings
            u32 count = repairing ? 7u : 6u;
            if (gated) {
                writes[count] = vk::WriteDescriptorSet{
                    .dstBinding = count, .descriptorCount = 1,
                    .descriptorType = vk::DescriptorType::eCombinedImageSampler, .pImageInfo = &gi};
                ++count;
            }
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, layout, 0,
                                    std::span{writes.data(), count});
'''),
    ],
    R + "vk_rasterizer_effects.cpp": [
        (r'''        volumetric_light->SetAtlasCascades(count, sun_atlas.valid_mask);
        sun_atlas.skipped_mask = 0;
''', r'''        volumetric_light->SetAtlasCascades(count, sun_atlas.valid_mask);
        sun_atlas.skipped_mask = 0;
        // bbport (r51b_volumetric-rt-check): with BB_VOLUMETRIC_RT_GATE the march also asks this
        // frame's ray traced scene (in the camera's view space) whether the sun reaches each cell
        // of its gate. The ray traced sun prepares the scene at the next draw (ContactShadow::
        // Flush) from the same entries (nothing is captured in between), so this call only moves
        // that build forward and the sun's call then returns at once. No scene: stage A's march.
        const u32 rt_gate = VolumetricOcclusion::RtGateMask();
        volumetric_light->SetSunScene(rt_gate != 0 && rt_shadow->PrepareScene()
                                          ? rt_shadow->Scene()
                                          : vk::AccelerationStructureKHR{},
                                      rt_gate);
'''),
    ],
    "engine/gpu/CMakeLists.txt": [
        (r'''add_host_shader(volumetric_light.comp volumetric_light_filter_comp FILTER=1)
''', r'''add_host_shader(volumetric_light.comp volumetric_light_filter_comp FILTER=1)
# bbport (r51b_volumetric-rt-check): the march and its repair reading the ray traced sun gate, and
# the gate's pass (ray queries); made only with BB_VOLUMETRIC_RT_GATE
add_host_shader(volumetric_light.comp volumetric_light_integrate_gate_comp INTEGRATE=1 GATE=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_gate_comp REPAIR=1 GATE=1)
add_host_shader(volumetric_rt_gate.comp volumetric_rt_gate_comp)
'''),
    ],
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "volumetric_light.comp": [("#ifdef GATE", 4), ("GateAt(uv, t, gate_range)", 1),
                                  ("visibility(ray * t, texel)", 2)],
    R + "vk_volumetric_light.cpp": [("gated ? integrate_gated : integrate", 1),
                                    ("RecordGate(in, in.constants_offset_word);", 1),
                                    ("sun_scene = vk::AccelerationStructureKHR{};", 1), ("std::span{writes.data(), count}", 1)],
    R + "vk_rasterizer_effects.cpp": [("volumetric_light->SetSunScene(", 1)],
    "engine/gpu/CMakeLists.txt": [("GATE=1)", 2), ("volumetric_rt_gate_comp)", 1)],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def new_state(path, text, eol):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        return "clean"
    if open(full, "rb").read() == text.replace("\n", eol).encode("utf-8"):
        return "applied"
    raise SystemExit("%s exists with other text: refusing" % path)

def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R51B_ROOT)" % ROOT)
    plan = []
    for path, edits in EDITS.items():
        raw, eol, cur = load(path)
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): state = "applied"
        elif todo == len(edits): state = "clean"
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
        plan.append((path, edits, raw, eol, cur, state))
    news = []
    for path, (text, eol_from) in NEW_FILES.items():
        eol = load(eol_from)[1]
        news.append((path, text, eol, new_state(path, text, eol)))
    states = {p[5] for p in plan} | {n[3] for n in news}
    if len(states) != 1:
        raise SystemExit("mixed state: " + ", ".join(["%s %s" % (p[0], p[5]) for p in plan] +
                                                      ["%s %s" % (n[0], n[3]) for n in news]))
    state = states.pop()
    if cmd == "check":
        if state == "applied":
            text_checks({p[0]: p[4] for p in plan})
            print("applied (text checks pass)")
        else:
            texts = {}
            for path, edits, raw, eol, cur, _ in plan:
                for old, new in edits: cur = cur.replace(old, new)
                texts[path] = cur
            text_checks(texts)
            print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
                  % (len(plan), len(news)))
        return
    if cmd == "apply":
        if state == "applied": print("already applied"); return
        texts, outs = {}, []
        for path, edits, raw, eol, cur, _ in plan:
            for old, new in edits: cur = cur.replace(old, new)
            texts[path] = cur
            outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
        text_checks(texts)
        os.makedirs(BACKUP, exist_ok=True)
        for path, data, raw in outs:
            open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
        written = []
        try:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r51btmp"
                open(tmp, "wb").write(data)
                os.replace(tmp, os.path.join(ROOT, path))
                written.append((path, raw))
            for path, text, eol, _ in news:
                open(os.path.join(ROOT, path), "wb").write(text.replace("\n", eol).encode("utf-8"))
                written.append((path, None))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + ".r51btmp"
                if os.path.exists(tmp): os.remove(tmp)
            for path, raw in written:
                if raw is None: os.remove(os.path.join(ROOT, path))
                else: open(os.path.join(ROOT, path), "wb").write(raw)
            raise
        print("applied"); return
    if state != "applied": print("nothing to revert"); return
    for path, edits, raw, eol, cur, _ in plan:
        for old, new in reversed(edits): cur = cur.replace(new, old)
        open(os.path.join(ROOT, path), "wb").write(cur.replace("\n", eol).encode("utf-8"))
    for path, text, eol, _ in news:
        os.remove(os.path.join(ROOT, path))
    print("reverted")

main()
