# r81_sun-fog-no-rt: FEATURE patch. The sun fog kept out of interiors for players WITHOUT ray
# tracing: an area light gate, off unless BB_VOLUMETRIC_AREA_GATE=1. On top of r51, r51b and r76.
# This is the reviewed version (r81_sun-fog-no-rt.fixed.py, 2026-11-15): the probe prints a
# summary line and one short line per record (the slot runner keeps evidence lines only up to 300
# characters and only the first and last line of each shape), with the light colours as the table
# holds them; `near`/`far` names (macros of windows.h) renamed; the record layout tied to Tint's
# by a static_assert and the camera pass's workgroup size to AREA_GROUP; comments and the README
# say the far part's real rule (the last 6 m of the march) and the buffers' real size.
#
# Why: the owner's rules (2026-11-15, verbatim): "The sun fog shouldn't go indoors at all"; "Well
# how would we keep the shafts from the sun through the window. It looks nice"; "Shouldn't this fix
# work without ray tracing or it needs ray tracing to work?"; "for the church sun shafts I don't
# think we can just relay on that because what about other interiors unless they all have baked
# shafts". r76's ray traced gate (BB_VOLUMETRIC_RT_GATE, default 1) runs only with a ray traced
# scene. Without one the fog follows the game's sun shadow atlas alone, and the atlas holds no roof
# over the dark library (dark-interior, a lattice roof) or the church hall (church-candles), so the
# fog fills them. What the engine has without ray tracing: the atlas (no roof there in any cascade,
# game test of r51: bits 1, 3, 7 look like 0), the depth buffer (blind to a ceiling above the view),
# the map block id (far coarser than "indoors"), and the game's own light sets: the directional
# light draw d92266b9 lights each pixel with one record of a 225-record table, named by the alpha
# byte of its texture 0 (engine/tools/re/ggx_directional_controls.py). With the ray traced sun off
# and effect_ray_tracing off the library's surfaces under the roofless atlas show no sun patch, so
# the game keeps it dark by its light set, not by shadow (2026-11-15 cause study, INFERRED).
#
# What (BB_VOLUMETRIC_AREA_GATE=1, read once; only marches without the ray traced gate):
# 1. The march's AREA builds (volumetric_light.comp INTEGRATE / REPAIR with AREA=1, same bindings
#    and push constants) keep in the fog image r the energy of the samples nearer the camera, g of
#    those in the march's last 6 m (it ends at the surface, at the reach or at the shadow distance,
#    whichever is nearest), b the share of samples the atlas has in sun.
# 2. Right after the fog's tint at the directional light draw (VolumetricLight::AreaGate),
#    volumetric_area_gate.comp's CAMERA pass (one workgroup of 256) weighs each record:
#    smoothstep(0.15, 0.5, its light 0 luminance over the brightest record's) (light 0's colour is
#    what the fog's tint already takes; the built-in white record left out and weighed 1), and the
#    camera's light set: the mean weight of a 16x16 grid's surfaces, each weighed by 1 - depth
#    (about 1 / distance), faded as the tint is (no surface: 1).
# 3. Its APPLY pass (the half resolution fog, then the full resolution repair image) writes the
#    fog: r (w_cam + (1 - w_cam) k) + g (w_end + (1 - w_end) k), w_end the weight of the pixel's own
#    record (w_cam at the sky), k = 1 - smoothstep(0.35, 0.65, b) the beam keep: lit air on a ray
#    that is mostly in the atlas's shadow (a beam through a window in a roof the atlas holds) stays
#    whatever the light set. Composite's filter and composite are unchanged.
# 4. Log: once at the first march "Volumetric lighting (r81): area light gate on (...)" or "...
#    off (BB_VOLUMETRIC_AREA_GATE not 1) ..."; with it on, once "... made (...)" and at the 120th
#    gated march, then every 600th, the probe: a line "... area gate probe: ..." (camera weight, the
#    grid's fog before and after, whether the host's copy of the weight rule agrees with the GPU's)
#    and a line "... area gate record ranked first|second|third|fourth: ..." for each of the four
#    records the most grid points showed (weight, light 0 against the brightest as the rule takes
#    it, light 0's colour as stored, the stored luminance of lights 0-3 and their directions' angles
#    to the light the march uses, view and world); every line stays under 300 characters. GPU
#    profile row "Lighting: volumetric area gate" (pinned).
# 5. Tests: volumetric-area-gate-test (CMake and engine/build.sh --test), effect-pipelines-test
#    builds the four new pipelines. README row.
#
# Why it is off by default: it can remove outdoor fog wherever an outdoor surface's record has less
# than half the sun of the brightest record in the table, or the light sets on screen say so, and
# nobody has seen the table's records yet (which light is the sun, whether interior records lack
# it). The probe line answers that in one run per place; only then can it be argued safe.
# Expected (not seen): dark-interior and the church hall lose their haze; window beams in rooms
# whose roof the atlas holds stay; outdoors (records with the sun) nothing changes, under the
# graveyard vault too as long as its surfaces use outdoor records. Known losses: a beam seen along
# its length (the view ray mostly in sun) goes; looking out of a room through a door, the street's
# fog keeps only its last 6 m; looking into a doorway from outside, the last 6 m before the room's
# back wall go; a room the table holds no brighter record for (an interior map) keeps its haze.
#
# Cost (estimates, NOT measured; RTX 4090, 1080p internal, fog at 960x540): knob off: nothing (the
# default builds are byte-identical SPIR-V, no pass is made, one bool a march). On: the march adds
# two adds and a compare a sample (no extra atlas taps; the study's ring beam test, 4 taps a lit
# sample, about 0.1-0.15 ms indoors, is replaced by the free lit share); CAMERA one workgroup
# (about 3 K loads); APPLY reads 0.5 M + 2.1 M RGBA16F texels and writes the marched ones, about
# 0.01-0.03 ms. Two buffers of 35 KB (70 KB). Probe: a 35 KB copy at the 120th gated march, then
# every 600th. The default path also gets one once-line, two counters a march and one call a
# directional draw that returns at its first test.
#
# Files: host_shaders/volumetric_light.comp (4 blocks, all under AREA), vk_volumetric_light.h,
# vk_volumetric_light.cpp, vk_rasterizer_effects.cpp (the directional draw's branch),
# engine/gpu/CMakeLists.txt, engine/build.sh, engine/tests/test_effect_pipelines.cpp, README.md;
# new: host_shaders/volumetric_area_layout.h, host_shaders/volumetric_area_gate.comp,
# renderer_vulkan/volumetric_area_gate.h, engine/tests/test_volumetric_area_gate.cpp.
#
# Use: cd <tree> && python -I -X utf8 r81_sun-fog-no-rt.py check | apply | revert (root from
# R81_ROOT, else the current directory). Files keep their line ends (CRLF in the tree); new files
# are written with CRLF. Originals are kept in r81_backup/ next to this script. Apply refuses if a
# new file already exists; revert deletes a new file only if its text is exactly what apply wrote.
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r81_backup")
ROOT = os.environ.get("R81_ROOT") or os.getcwd()
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

# Edits of existing files, in order: (path, anchor text, its replacement). Each anchor must occur
# exactly once; every replacement keeps its anchor's text whole, so the anchors are the lead's
# list of what this patch touches.
EDITS = [
    (H + "volumetric_light.comp",
r'''#version 450
#extension GL_EXT_scalar_block_layout : require

#ifdef TINT
''',
r'''#version 450
#extension GL_EXT_scalar_block_layout : require
#ifdef AREA
// bbport (r81_sun-fog-no-rt): the march's builds for the area light gate (BB_VOLUMETRIC_AREA_GATE=1,
// marches without the ray traced gate): the fog image keeps r the energy of the samples nearer the
// camera, g of those in the march's last AREA_FAR_METRES, b the share of samples in sun, for
// volumetric_area_gate.comp to weigh at the game's directional light draw
#extension GL_GOOGLE_include_directive : require
#include "volumetric_area_layout.h"
#if defined(GATE) || !(defined(INTEGRATE) || defined(REPAIR))
#error AREA is a build of INTEGRATE or REPAIR without GATE
#endif
#endif

#ifdef TINT
'''),
    (H + "volumetric_light.comp",
r'''    local_splits = shared_splits;
#ifdef GATE
''',
r'''    local_splits = shared_splits;
#ifdef AREA
    // bbport (r81_sun-fog-no-rt): the samples nearer the camera, those in the march's last
    // AREA_FAR_METRES (`limit`: the surface, the reach or the shadow distance, whichever is nearest;
    // at the sky the gate weighs both alike), and the sun's share
    const float area_far_from = limit - float(AREA_FAR_METRES);
    float area_near = 0.0, area_far = 0.0, area_lit = 0.0;
#endif
#ifdef GATE
'''),
    (H + "volumetric_light.comp",
r'''#else
        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
#endif
''',
r'''#elif defined(AREA)
        // bbport (r81_sun-fog-no-rt): the same sample, kept apart by where it lies
        float v = visibility(ray * t, texel);
        float e = exp(-density * t) * density * ds * v;
        area_lit += v;
        if (t < area_far_from) {
            area_near += e;
        } else {
            area_far += e;
        }
#else
        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);
#endif
'''),
    (H + "volumetric_light.comp",
r'''    imageStore(fog_out, px, vec4(vec3(strength * phase * energy), 1.0 - depth));
}
#elif defined(TINT)
''',
r'''#ifdef AREA
    // bbport (r81_sun-fog-no-rt): near, far and the share in sun (volumetric_area_gate.comp's
    // APPLY turns them into the fog before anything else reads it)
    imageStore(fog_out, px, vec4(strength * phase * area_near, strength * phase * area_far,
                                 area_lit / float(steps), 1.0 - depth));
#else
    imageStore(fog_out, px, vec4(vec3(strength * phase * energy), 1.0 - depth));
#endif
}
#elif defined(TINT)
'''),
    (R + "vk_volumetric_light.h",
r'''#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
''',
r'''#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
#include "video_core/renderer_vulkan/volumetric_area_gate.h"  // bbport (r81_sun-fog-no-rt)
'''),
    (R + "vk_volumetric_light.h",
r'''    void Tint(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes);
''',
r'''    void Tint(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes);
    /// bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march without the ray traced
    /// sun gate, weighs its fog with the game's light sets (volumetric_area_gate.comp). `lighting`
    /// and `offset_bytes` as Tint's; `records` the directional draw's texture 0, whose alpha byte
    /// names each pixel's record (a null view: none; the fog is then as without the gate). Called
    /// right after Tint at the same draw; does nothing unless the last Integrate kept the layout.
    void AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,
                  const vk::DescriptorImageInfo& records);
'''),
    (R + "vk_volumetric_light.h",
r'''    void SayLight();
''',
r'''    void SayLight();
    // bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1), made at the first
    // march without the ray traced gate while the knob is on: the march's AREA builds, its two
    // passes, its state (volumetric_area_layout.h, 35 KB) and the probe's copy of it for the host
    bool AreaReady();
    void ReadAreaProbe();
    Pass integrate_area, repair_area, area_camera, area_apply;
    std::unique_ptr<VideoCore::Buffer> area_state, area_readback;
    std::chrono::steady_clock::time_point area_time{};
    VolumetricAreaGate::ProbeClock area_clock;
    VolumetricOcclusion::SunLight area_probe_light{};
    u64 area_probe_tick = 0, area_marches = 0, area_gated = 0;
    bool area_tried = false, area_failed = false, area_said = false;
    bool area_pending = false; ///< the last Integrate kept the AREA layout: AreaGate is owed
    bool area_probe_pending = false;
'''),
    (R + "vk_volumetric_light.cpp",
r'''#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
''',
r'''#include "video_core/host_shaders/volumetric_rt_gate_diag_comp.h"
// bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1)
#include "video_core/host_shaders/volumetric_area_gate_apply_comp.h"
#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
'''),
    (R + "vk_volumetric_light.cpp",
r'''void VolumetricLight::EnsureImage(u32 w, u32 h) {
''',
r'''// bbport (r81_sun-fog-no-rt): the area light gate's push constants (volumetric_area_gate.comp)
namespace {
struct AreaParams {
    u32 offset_bytes, record_count;
    float blend;
    u32 flags; // VolumetricAreaGate::FlagRecords, FlagProbe
};
static_assert(sizeof(AreaParams) == 16);
// The table as Tint reads it (its RecordBytes = 72 floats a record, at most 256 records) and as
// volumetric_light.comp's TINT build reads light 0's colour (dwords 16-18).
static_assert(VolumetricAreaGate::RecordBytes == 72 * sizeof(float) &&
              VolumetricAreaGate::Records == 256 && VolumetricAreaGate::RecordColour == 16);
}

// bbport (r81_sun-fog-no-rt): made at the first march without the ray traced gate while
// BB_VOLUMETRIC_AREA_GATE=1: the march's AREA builds (the bindings and push constants of the plain
// ones), the gate's CAMERA and APPLY passes, its state and the probe's copy of it. Failing leaves
// the march as without the gate.
bool VolumetricLight::AreaReady() {
    if (area_tried) {
        return !area_failed;
    }
    area_tried = true;
    using enum vk::DescriptorType;
    using namespace VolumetricAreaGate;
    bool made =
        EffectPass::HasRoom(instance, 2ull * StateBytes) &&
        CreatePass(integrate_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage},
                   VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP, sizeof(Params),
                   "Volumetric integrate (area gate)") &&
        CreatePass(repair_area,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
                    eStorageImage, eStorageImage, eStorageImage},
                   VOLUMETRIC_LIGHT_REPAIR_AREA_COMP, sizeof(Params),
                   "Volumetric repair (area gate)") &&
        CreatePass(area_camera,
                   {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
                   VOLUMETRIC_AREA_GATE_CAMERA_COMP, sizeof(AreaParams),
                   "Volumetric area gate (camera)") &&
        CreatePass(area_apply, {eStorageBuffer, eCombinedImageSampler, eStorageImage},
                   VOLUMETRIC_AREA_GATE_APPLY_COMP, sizeof(AreaParams),
                   "Volumetric area gate (apply)");
    if (made) {
        area_state = std::make_unique<VideoCore::Buffer>(
            instance, 0, StateBytes, VideoCore::MemoryType::DeviceLocal, "Volumetric area gate");
        area_readback = std::make_unique<VideoCore::Buffer>(
            instance, 0, StateBytes, VideoCore::MemoryType::HostCached,
            "Volumetric area gate probe readback");
        made = area_readback->mapped_data.size() >= StateBytes;
    }
    if (!made) {
        area_failed = true;
        std::printf("Volumetric lighting (r81): area light gate off - its passes or buffers could "
                    "not be made; the march stays as without it\n");
        return false;
    }
    std::printf("Volumetric lighting (r81): area light gate made (the camera's light sets from a "
                "%ux%u grid, at most %u records, each ray's last %.0f m weighed by its surface's "
                "light set)\n",
                GridX, GridY, Records, FarMetres);
    return true;
}

// bbport (r81_sun-fog-no-rt): the area light gate, right after Tint at the game's directional
// light draw (the G-buffer and this frame's lighting table are there): CAMERA weighs the records
// and the camera's light sets, then APPLY turns the march's near, far and lit share into the fog,
// in the half resolution image and in the full resolution repair image, before Composite's filter
// reads either. On a probe march (the 120th, then every 600th) CAMERA also writes the grid's
// records and every record's rows 0-7, copied to the host for ReadAreaProbe.
void VolumetricLight::AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,
                               const vk::DescriptorImageInfo& records) {
    using namespace VolumetricAreaGate;
    if (area_probe_pending && scheduler.IsFree(area_probe_tick)) {
        ReadAreaProbe();
    }
    if (!std::exchange(area_pending, false) || !ready || !tinted || !Enabled()) {
        return;
    }
    const u32 record_count =
        records.imageView && lighting.buffer ? RecordCount(lighting.range, offset_bytes) : 0u;
    const bool has_records = record_count != 0;
    const auto now = std::chrono::steady_clock::now();
    const float seconds = std::chrono::duration<float>(now - area_time).count();
    area_time = now;
    const bool probing = !area_probe_pending && area_clock.Next();
    // The camera's weight fades as the fog's colour does (Tint).
    const AreaParams params{
        offset_bytes, record_count,
        seconds <= TintSnapAfter ? 1.0f - std::exp(-seconds / TintFadeConstant) : 1.0f,
        (has_records ? FlagRecords : 0u) | (probing ? FlagProbe : 0u)};
    const vk::DescriptorBufferInfo state{area_state->Handle(), 0, StateBytes};
    // Without the table or texture 0 the state buffer and the march's depth copy stand in (the
    // passes do not read them then: every weight is 1)
    const vk::DescriptorBufferInfo table = has_records ? lighting : state;
    const vk::DescriptorImageInfo record_info{
        *sampler, has_records ? records.imageView : *depth_view,
        has_records ? records.imageLayout : vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_read{*sampler, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_half{{}, *fog_view, vk::ImageLayout::eGeneral};
    const vk::DescriptorImageInfo fog_full{{}, *repair_view, vk::ImageLayout::eGeneral};
    scheduler.EndRendering();
    EffectPass::Mark(81, "volumetric area gate", true);
    scheduler.RecordCrumb(
        {.name = "Volumetric area gate"},
        [params, table, state, record_info, fog_read, fog_half, fog_full, probing,
         readback = probing ? area_readback->Handle() : vk::Buffer{}, half_w = width,
         half_h = height, full_w = depth_width, full_h = depth_height,
         camera_pipeline = *area_camera.pipeline, camera_layout = *area_camera.layout,
         apply_pipeline = *area_apply.pipeline,
         apply_layout = *area_apply.layout](vk::CommandBuffer cmd) {
            Before(cmd);
            const std::array<vk::WriteDescriptorSet, 4> camera_writes{{
                {.dstBinding = 0, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &table},
                {.dstBinding = 1, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
                {.dstBinding = 2, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &record_info},
                {.dstBinding = 3, .descriptorCount = 1,
                 .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                 .pImageInfo = &fog_read},
            }};
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, camera_pipeline);
            cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, camera_layout, 0,
                                    camera_writes);
            cmd.pushConstants(camera_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
            cmd.dispatch(1, 1, 1);
            EffectPass::ComputeBarrier(cmd);
            if (probing) {
                EffectPass::MemoryBarrier(cmd, Compute, vk::AccessFlagBits2::eShaderWrite,
                                          vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferRead);
                cmd.copyBuffer(state.buffer, readback, vk::BufferCopy{0, 0, StateBytes});
                EffectPass::MemoryBarrier(cmd, vk::PipelineStageFlagBits2::eCopy,
                                          vk::AccessFlagBits2::eTransferWrite,
                                          vk::PipelineStageFlagBits2::eHost,
                                          vk::AccessFlagBits2::eHostRead);
            }
            cmd.bindPipeline(vk::PipelineBindPoint::eCompute, apply_pipeline);
            cmd.pushConstants(apply_layout, vk::ShaderStageFlagBits::eCompute, 0, sizeof(params),
                              &params);
            for (u32 image = 0; image < 2; ++image) {
                const bool half = image == 0;
                const std::array<vk::WriteDescriptorSet, 3> writes{{
                    {.dstBinding = 0, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageBuffer, .pBufferInfo = &state},
                    {.dstBinding = 1, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eCombinedImageSampler,
                     .pImageInfo = &record_info},
                    {.dstBinding = 2, .descriptorCount = 1,
                     .descriptorType = vk::DescriptorType::eStorageImage,
                     .pImageInfo = half ? &fog_half : &fog_full},
                }};
                cmd.pushDescriptorSetKHR(vk::PipelineBindPoint::eCompute, apply_layout, 0, writes);
                cmd.dispatch(((half ? half_w : full_w) + 7) / 8, ((half ? half_h : full_h) + 7) / 8,
                             1);
            }
            After(cmd);
        });
    if (probing) {
        area_probe_pending = true;
        area_probe_tick = scheduler.CurrentTick();
        area_probe_light = sun_light;
    }
}

// bbport (r81_sun-fog-no-rt): the probe's lines from the state the GPU copied back. First a summary:
// the camera's weight, the grid's fog before and after the gate, and whether the host's copy of the
// weight rule (volumetric_area_gate.h) gives the GPU's weights. Then one line for each of the
// records the most grid points showed (ranked first to fourth): its weight, its light 0 against
// the brightest record's as the rule takes it (colours scaled to at most 1 a channel), light 0's
// colour and the luminance of its four lights as the table holds them (which shows whether that
// scaling matters), and their directions' angles to the light the march marches (view and world
// space, -1: unknown), which tells which of them is the sun and in which space the table holds them.
// Every line stays under 300 characters, and the rank is a word: the slot runner keeps evidence
// lines up to 300 characters, the first and last line of each shape (digits aside).
void VolumetricLight::ReadAreaProbe() {
    using namespace VolumetricAreaGate;
    area_probe_pending = false;
    std::vector<u32> w(StateWords);
    area_readback->Invalidate(0, StateBytes);
    std::memcpy(w.data(), area_readback->mapped_data.data(), StateBytes);
    const auto word = [&w](u32 at) { return std::bit_cast<float>(w[at]); };
    const float best = word(AREA_STATE_BEST);
    const u32 counted = w[AREA_STATE_RECORD_COUNT];
    std::vector<std::string> lines;
    float differs = 0.0f;
    for (const u32 id : TopRecords(w.data() + AREA_STATE_COUNTS)) {
        if (id >= Records) {
            break;
        }
        std::array<float, ProbeRowFloats> row{};
        std::memcpy(row.data(), w.data() + AREA_STATE_ROWS + id * ProbeRowFloats, sizeof(row));
        const float gpu = word(AREA_STATE_WEIGHTS + id);
        const float scaled = SunLuminance(row.data() + RecordColour);
        const float host = id < counted && !IsFallback(row.data()) ? SunWeight(scaled, best) : 1.0f;
        differs = std::max(differs, std::abs(host - gpu));
        std::array<float, 4> stored{}, view{}, world{};
        for (u32 s = 0; s < 4; ++s) {
            stored[s] = RawLuminance(row.data() + RecordColour + 4 * s);
            const std::array<float, 3> dir{row[4 * s], row[4 * s + 1], row[4 * s + 2]};
            view[s] = area_probe_light.valid ? VolumetricOcclusion::AngleDeg(dir, area_probe_light.view)
                                             : -1.0f;
            world[s] = area_probe_light.valid
                           ? VolumetricOcclusion::AngleDeg(dir, area_probe_light.world)
                           : -1.0f;
        }
        char part[300];
        std::snprintf(part, sizeof(part),
                      "Volumetric lighting (r81): area gate record ranked %s: #%u on %u points, "
                      "weight %.2f, light 0 at %.2f of the brightest, rgb %.3g/%.3g/%.3g; lights "
                      "0-3 luminance %.3g/%.3g/%.3g/%.3g; angles view %.0f/%.0f/%.0f/%.0f world "
                      "%.0f/%.0f/%.0f/%.0f deg",
                      RankName(u32(lines.size())), id, w[AREA_STATE_COUNTS + id], gpu,
                      best > 0.0f ? scaled / best : 0.0f, row[RecordColour], row[RecordColour + 1],
                      row[RecordColour + 2], stored[0], stored[1], stored[2], stored[3], view[0],
                      view[1], view[2], view[3], world[0], world[1], world[2], world[3]);
        lines.emplace_back(part);
    }
    const float before = word(AREA_STATE_BEFORE), after = word(AREA_STATE_AFTER);
    char check[48];
    if (lines.empty()) {
        std::snprintf(check, sizeof(check), "no records seen");
    } else if (differs < 1e-3f) {
        std::snprintf(check, sizeof(check), "agree");
    } else {
        std::snprintf(check, sizeof(check), "differ by %.4f", differs);
    }
    std::printf("Volumetric lighting (r81): area gate probe: on %llu of %llu marches since the last; "
                "camera weight %.2f (now %.2f); brightest light 0 %.3f of %u records; grid %u "
                "surface %u sky, fog kept %.0f%% (%.4f of %.4f), sun share %.2f; host weights %s\n",
                static_cast<unsigned long long>(area_gated),
                static_cast<unsigned long long>(area_marches), word(AREA_STATE_CAMERA),
                word(AREA_STATE_CAMERA_NOW), best, counted, w[AREA_STATE_SURFACE],
                w[AREA_STATE_SKY], before > 0.0f ? 100.0f * after / before : 100.0f, after, before,
                word(AREA_STATE_LIT), check);
    for (const std::string& line : lines) {
        std::printf("%s\n", line.c_str());
    }
    area_gated = area_marches = 0;
}

void VolumetricLight::EnsureImage(u32 w, u32 h) {
'''),
    (R + "vk_volumetric_light.cpp",
r'''    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
''',
r'''    const bool gated = live_strength > 0.0f && sun_scene && sun_scene_mask != 0 && GateReady();
    // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1 (read once, said once at the first
    // march): a march without the ray traced gate keeps the AREA layout, which AreaGate weighs at
    // the directional light draw. Off: nothing of it is made or run.
    const bool area = live_strength > 0.0f && !gated && VolumetricAreaGate::On() && AreaReady();
    if (live_strength > 0.0f) {
        if (!area_said) {
            area_said = true;
            if (VolumetricAreaGate::On()) {
                std::printf("Volumetric lighting (r81): area light gate on "
                            "(BB_VOLUMETRIC_AREA_GATE=1): a march without the ray traced sun gate "
                            "keeps its sun fog only where the game's light set has sun (the "
                            "surface's for the last %.0f m of each ray, those on screen for the "
                            "rest) or where the air along the view is mostly in the atlas's "
                            "shadow (a beam)\n",
                            VolumetricAreaGate::FarMetres);
            } else {
                std::printf("Volumetric lighting (r81): area light gate off "
                            "(BB_VOLUMETRIC_AREA_GATE not 1): without the ray traced sun gate "
                            "the sun fog follows the atlas alone and can show indoors\n");
            }
        }
        ++area_marches;
        area_gated += area ? 1 : 0;
    }
'''),
    (R + "vk_volumetric_light.cpp",
r'''         pipeline = *pass.pipeline, layout = *pass.layout](vk::CommandBuffer cmd) {
''',
r'''         // bbport (r81_sun-fog-no-rt): the AREA builds on an area gate march (same bindings)
         pipeline = *(area ? (repairing ? repair_area : integrate_area) : pass).pipeline,
         layout = *(area ? (repairing ? repair_area : integrate_area) : pass).layout](
            vk::CommandBuffer cmd) {
'''),
    (R + "vk_volumetric_light.cpp",
r'''    ready = true;
}

void VolumetricLight::Tint(''',
r'''    area_pending = area; // bbport (r81_sun-fog-no-rt): AreaGate is owed at the directional draw
    ready = true;
}

void VolumetricLight::Tint('''),
    (R + "vk_rasterizer_effects.cpp",
r'''        volumetric_light->Tint(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u);
''',
r'''        volumetric_light->Tint(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u);
        // bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march without the ray
        // traced gate, the fog weighed with the game's light sets; the draw's texture 0 names each
        // pixel's record in its alpha byte (engine/tools/re/ggx_directional_controls.py)
        volumetric_light->AreaGate(dc.buffer_infos[0], dc.push_data.buf_offsets[0] & 255u,
                                   dc.image_infos.empty() || ps_info->images.empty()
                                       ? vk::DescriptorImageInfo{}
                                       : dc.image_infos[0]);
'''),
    ("engine/gpu/CMakeLists.txt",
r'''    add_custom_command(OUTPUT ${OUT}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${SHADER_DIR}
''',
r'''    # bbport (r81_sun-fog-no-rt): the area light gate's numbers, shared with C++ (volumetric_area_gate.h)
    if (FILENAME MATCHES "^volumetric_(light|area_gate)")
        list(APPEND INCLUDES ${SHADER_SRC}/volumetric_area_layout.h)
    endif()
    add_custom_command(OUTPUT ${OUT}
        COMMAND ${CMAKE_COMMAND} -E make_directory ${SHADER_DIR}
'''),
    ("engine/gpu/CMakeLists.txt",
r'''add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
''',
r'''add_host_shader(volumetric_light.comp volumetric_light_composite_gate_view_comp COMPOSITE=1 GATE_VIEW=1)
# bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1, off unless set; for
# marches without the ray traced gate): the march's builds keeping near and far energy and the
# share in sun apart, and the gate's two passes; the builds above are unchanged
add_host_shader(volumetric_light.comp volumetric_light_integrate_area_comp INTEGRATE=1 AREA=1)
add_host_shader(volumetric_light.comp volumetric_light_repair_area_comp REPAIR=1 AREA=1)
add_host_shader(volumetric_area_gate.comp volumetric_area_gate_camera_comp CAMERA=1)
add_host_shader(volumetric_area_gate.comp volumetric_area_gate_apply_comp APPLY=1)
'''),
    ("engine/gpu/CMakeLists.txt",
r'''add_executable(volumetric-occlusion-test EXCLUDE_FROM_ALL ../tests/test_volumetric_occlusion.cpp)
target_compile_options(volumetric-occlusion-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-occlusion-test PRIVATE ..)
''',
r'''add_executable(volumetric-occlusion-test EXCLUDE_FROM_ALL ../tests/test_volumetric_occlusion.cpp)
target_compile_options(volumetric-occlusion-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-occlusion-test PRIVATE ..)
# bbport (r81_sun-fog-no-rt): the area light gate's knob and weights (volumetric_area_gate.h)
add_executable(volumetric-area-gate-test EXCLUDE_FROM_ALL ../tests/test_volumetric_area_gate.cpp)
target_compile_options(volumetric-area-gate-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)
target_include_directories(volumetric-area-gate-test PRIVATE ..)
'''),
    ("engine/build.sh",
r'''    out/rt-still-check-test
''',
r'''    out/rt-still-check-test
    # bbport (r81_sun-fog-no-rt): the sun fog's area light gate (volumetric_area_gate.h)
    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_volumetric_area_gate.cpp -o out/volumetric-area-gate-test
    out/volumetric-area-gate-test
'''),
    ("engine/tests/test_effect_pipelines.cpp",
r'''#include "video_core/host_shaders/volumetric_light_tint_comp.h"
''',
r'''#include "video_core/host_shaders/volumetric_light_tint_comp.h"
// bbport (r81_sun-fog-no-rt): the march's AREA builds and the area light gate's two passes
#include "video_core/host_shaders/volumetric_area_gate_apply_comp.h"
#include "video_core/host_shaders/volumetric_area_gate_camera_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_area_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_comp.h"
'''),
    ("engine/tests/test_effect_pipelines.cpp",
r'''        {"volumetric tint",
         VOLUMETRIC_LIGHT_TINT_COMP,
''',
r'''        // bbport (r81_sun-fog-no-rt): as VolumetricLight::AreaReady makes them: the march's AREA
        // builds take the plain builds' bindings; the area light gate's camera and apply passes
        {"volumetric integrate (area gate)",
         VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage},
         32},
        {"volumetric repair (area gate)",
         VOLUMETRIC_LIGHT_REPAIR_AREA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler,
          eStorageImage, eStorageImage, eStorageImage},
         32},
        {"volumetric area gate (camera)",
         VOLUMETRIC_AREA_GATE_CAMERA_COMP,
         {eStorageBuffer, eStorageBuffer, eCombinedImageSampler, eCombinedImageSampler},
         16},
        {"volumetric area gate (apply)",
         VOLUMETRIC_AREA_GATE_APPLY_COMP,
         {eStorageBuffer, eCombinedImageSampler, eStorageImage},
         16},
        {"volumetric tint",
         VOLUMETRIC_LIGHT_TINT_COMP,
'''),
    ("README.md",
r'''| `BB_VOLUMETRIC_GATE_VIEW` |''',
r'''| `BB_VOLUMETRIC_AREA_GATE` | Sun fog indoors without ray tracing: `1` keeps the sun fog of every march without the ray traced sun gate (`effect_ray_tracing` off, no ray traced scene this frame, or `BB_VOLUMETRIC_RT_GATE=0`) only where the game's own light set has sun: for the last 6 m of each march (which ends at the surface, at the fog's reach or at the sun shadow distance, whichever is nearest) the set that lights the surface the pixel shows, for the rest the sets on screen, nearer ones counting more (at the sky those alone). A set whose first light's colour (scaled to at most 1 a channel) has at least half the luminance of the brightest set's counts in full, one at 15% or less not at all, the game's built-in white set always in full. Lit air whose ray has at most 35% of its samples in sun in the sun shadow map (a beam between shadows, as through a window) stays whatever the set, at 65% or more only the set decides, in between a mix. At the 120th such march and then every 600th the log shows the camera's weight, how much fog the gate kept on a 16x16 grid and the four light sets seen most | off |
| `BB_VOLUMETRIC_GATE_VIEW` |'''),
]

# New files (written with CRLF).
NEW = {
    H + "volumetric_area_layout.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r81_sun-fog-no-rt): what the sun fog's area light gate shares between its shaders
// (volumetric_area_gate.comp, the AREA builds of volumetric_light.comp) and the engine
// (renderer_vulkan/volumetric_area_gate.h, VolumetricLight::AreaGate). Plain #define lines only:
// the shaders include this file through GL_GOOGLE_include_directive and C++ includes it as it is,
// so one text holds every number both sides use.
#ifndef VOLUMETRIC_AREA_LAYOUT_H
#define VOLUMETRIC_AREA_LAYOUT_H

// The camera pass: one workgroup, a thread per record of the game's directional lighting table
// (the table has 225; VolumetricLight::Tint reads at most 256) and per point of a 16x16 grid over
// the screen.
#define AREA_GROUP 256u
#define AREA_GRID_X 16u
#define AREA_GRID_Y 16u
#define AREA_RECORDS 256u
// A record of the table: 18 vec4 (72 floats, 288 bytes). Rows 0-3: direction and width of lights
// 0-3; rows 4-7: their diffuse colours. The sun share is read from light 0's colour (dwords 16-18),
// the colour VolumetricLight::Tint's TINT build takes for the fog.
#define AREA_RECORD_FLOATS 72u
#define AREA_RECORD_COLOUR 16u
// The rows the probe copies of each record: 0-7 (directions and diffuse colours), 32 floats.
#define AREA_PROBE_ROW_FLOATS 32u

// A record's weight: smoothstep(AREA_SUN_LO, AREA_SUN_HI, its light 0 luminance over the
// brightest record's), the fallback record (the built-in white one) left out of the brightest and
// weighed 1. A record as bright as half the brightest or more weighs 1 (no change).
#define AREA_SUN_LO 0.15
#define AREA_SUN_HI 0.5
// The beam test: the mean atlas visibility along the march (the share of its samples in sun).
// At AREA_BEAM_LO or less the lit air is a beam between shadows and is kept whatever the light
// set; at AREA_BEAM_HI or more it is air the atlas has no roof over and only the light set keeps
// it; in between a smooth mix.
#define AREA_BEAM_LO 0.35
#define AREA_BEAM_HI 0.65
// The far part of a ray: its samples in the march's last this many metres (the march ends at the
// surface, at the reach or at the shadow distance, whichever is nearest); they take the weight of
// the light set of the surface the pixel shows, the nearer ones the camera's. A ray to the sky
// takes the camera's for all of it.
#define AREA_FAR_METRES 6.0
// The camera's weight: the grid points' record weights, each weighed by 1 - depth (about the
// inverse of its distance); with less than this summed weight (all sky) the camera weighs 1.
#define AREA_CAMERA_EPS 1e-6

// Push word `flags`: the lighting table and texture 0 of the directional draw are there; the
// camera pass also writes the probe's words (counts and rows).
#define AREA_FLAG_RECORDS 1u
#define AREA_FLAG_PROBE 2u

// The state buffer, 32-bit words. Read by the apply pass: AREA_STATE_CAMERA and the weights.
#define AREA_STATE_CAMERA 0u        // float: the camera's weight, faded (VolumetricLight::Tint's fade)
#define AREA_STATE_CAMERA_NOW 1u    // float: this frame's, before the fade
#define AREA_STATE_BEST 2u          // float: the brightest record's light 0 luminance
#define AREA_STATE_SURFACE 3u       // uint: grid points on a surface (probe)
#define AREA_STATE_SKY 4u           // uint: grid points at the sky (probe)
#define AREA_STATE_BEFORE 5u        // float: the grid's fog before the gate (probe)
#define AREA_STATE_AFTER 6u         // float: and after it (probe)
#define AREA_STATE_LIT 7u           // float: the grid's lit share along the view, fog-weighted (probe)
#define AREA_STATE_RECORD_COUNT 8u  // uint: records weighed
#define AREA_STATE_WEIGHTS 16u      // AREA_RECORDS floats: each record's weight
#define AREA_STATE_COUNTS 272u      // AREA_RECORDS uints: grid points on each record (probe)
#define AREA_STATE_ROWS 528u        // AREA_RECORDS x AREA_PROBE_ROW_FLOATS floats (probe)
#define AREA_STATE_WORDS 8720u

#endif
''',
    H + "volumetric_area_gate.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#version 450
#extension GL_EXT_scalar_block_layout : require
#extension GL_GOOGLE_include_directive : require

// bbport (r81_sun-fog-no-rt): the sun fog's area light gate, for marches without the ray traced
// gate (BB_VOLUMETRIC_AREA_GATE=1; VolumetricLight::AreaGate, right after the fog's tint at the
// game's directional light draw d92266b9). The AREA builds of volumetric_light.comp's march keep
// in the fog image r: the energy of the samples nearer the camera, g: of those in the march's last
// AREA_FAR_METRES (it ends at the surface, the reach or the shadow distance), b: the mean atlas
// visibility along the ray
// (the share of its samples in sun), a: 1 - depth as always. The game lights each pixel with one
// record of that draw's table, the alpha byte of its texture 0 (engine/tools/re/
// ggx_directional_controls.py: `profiles = table[textures[0][..., 3]]`). An interior's records
// are expected to carry little or no sun, an outdoor record the sun; that is what the gate
// relies on and what BB_VOLUMETRIC_AREA_GATE's probe line shows.
//   CAMERA (one workgroup): each record's weight, smoothstep(AREA_SUN_LO, AREA_SUN_HI, its light
//     0 luminance over the brightest record's) (the built-in white record left out and weighed
//     1); the camera's weight, the mean weight of a 16x16 grid's surfaces weighed by 1 - depth
//     (about 1 / distance; no surface: 1), faded as the tint is; with the probe also the grid's
//     records, fog before and after, and rows 0-7 of every record.
//   APPLY (each pixel of the half resolution fog and of the full resolution repair image): the
//     beam keep k = 1 - smoothstep(AREA_BEAM_LO, AREA_BEAM_HI, b); fog = r (w_cam + (1 - w_cam) k)
//     + g (w_end + (1 - w_end) k), w_end the weight of the pixel's own record (the camera's at the
//     sky). A weight of 1 gives r + g: the fog as without the gate. Missing records weigh 1.
#include "volumetric_area_layout.h"

// The camera pass takes one grid point and one record a thread: AREA_GRID_X * AREA_GRID_Y and
// AREA_RECORDS equal AREA_GROUP, its workgroup size (static_asserts in volumetric_area_gate.h).

#ifdef CAMERA
layout(local_size_x = AREA_GROUP, local_size_y = 1) in;
#else
layout(local_size_x = 8, local_size_y = 8) in;
#endif

layout(push_constant) uniform AreaParams {
    uint offset_bytes;
    uint record_count;
    float blend;
    uint flags;
};

float BeamKeep(float lit) {
    return 1.0 - smoothstep(AREA_BEAM_LO, AREA_BEAM_HI, lit);
}

float Segment(float weight, float keep) {
    return weight + (1.0 - weight) * keep;
}

// The alpha byte of texture 0 at uv: the record that lights the pixel.
uint RecordAt(sampler2D records, vec2 uv) {
    ivec2 size = textureSize(records, 0);
    ivec2 p = clamp(ivec2(uv * vec2(size)), ivec2(0), size - 1);
    return min(uint(texelFetch(records, p, 0).a * 255.0 + 0.5), AREA_RECORDS - 1u);
}

#ifdef CAMERA
layout(scalar, binding = 0) readonly buffer Lighting { uint d[]; } lighting;
layout(scalar, binding = 1) buffer AreaState { uint w[]; } state;
layout(binding = 2) uniform sampler2D record_tex;
layout(binding = 3) uniform sampler2D fog_tex;

// As volumetric_light.comp's TINT build reads a record's colour, the light 0 colour clamped to 0
// and scaled to at most 1 per channel, and its test for the built-in white record.
vec3 record_vec3(uint id, uint field) {
    uint at = (offset_bytes >> 2) + id * AREA_RECORD_FLOATS + field;
    return vec3(uintBitsToFloat(lighting.d[at]), uintBitsToFloat(lighting.d[at + 1u]),
                uintBitsToFloat(lighting.d[at + 2u]));
}

bool is_fallback(uint id) {
    return record_vec3(id, 16u) == vec3(1.0) && record_vec3(id, 20u) == vec3(0.0) &&
           all(lessThan(abs(record_vec3(id, 0u) - vec3(0.70710678, 0.70710678, 0.0)), vec3(1e-3)));
}

float sun_luminance(uint id) {
    vec3 rgb = record_vec3(id, AREA_RECORD_COLOUR);
    if (any(isnan(rgb)) || any(isinf(rgb))) return 0.0;
    rgb = max(rgb, vec3(0.0));
    rgb /= max(1.0, max(rgb.r, max(rgb.g, rgb.b)));
    return dot(rgb, vec3(0.2126, 0.7152, 0.0722));
}

shared float s_a[AREA_GROUP];
shared float s_b[AREA_GROUP];
shared vec4 s_v[AREA_GROUP];
shared float s_weight[AREA_RECORDS];
shared uint s_count[AREA_RECORDS];
shared float s_camera;

void main() {
    const uint id = gl_LocalInvocationIndex;
    const bool records = (flags & AREA_FLAG_RECORDS) != 0u;
    const bool probe = (flags & AREA_FLAG_PROBE) != 0u;

    // 1. Each thread its record's light 0 luminance; the brightest of them (not the white one).
    float lum = 0.0;
    bool fallback = false;
    if (records && id < record_count) {
        fallback = is_fallback(id);
        lum = sun_luminance(id);
    }
    s_a[id] = fallback ? 0.0 : lum;
    s_count[id] = 0u;
    for (uint stride = AREA_GROUP / 2u; stride > 0u; stride >>= 1u) {
        barrier();
        if (id < stride) s_a[id] = max(s_a[id], s_a[id + stride]);
    }
    barrier();
    const float best = s_a[0];
    float weight = 1.0;
    if (records && id < record_count && !fallback && best > 0.0) {
        weight = smoothstep(AREA_SUN_LO, AREA_SUN_HI, lum / best);
    }
    s_weight[id] = weight;
    state.w[AREA_STATE_WEIGHTS + id] = floatBitsToUint(weight);
    barrier();

    // 2. The camera's weight: the grid's surfaces, nearer ones more (1 - depth, about 1 / distance).
    const vec2 uv = (vec2(float(id % AREA_GRID_X), float(id / AREA_GRID_X)) + 0.5) /
                    vec2(float(AREA_GRID_X), float(AREA_GRID_Y));
    const ivec2 fog_size = textureSize(fog_tex, 0);
    const vec4 fog = texelFetch(fog_tex, clamp(ivec2(uv * vec2(fog_size)), ivec2(0), fog_size - 1), 0);
    const bool surface = fog.a > 0.0 && fog.a < 1.0;
    const uint record = records ? RecordAt(record_tex, uv) : 0u;
    const float here = records ? s_weight[record] : 1.0;
    s_a[id] = surface ? fog.a * here : 0.0;
    s_b[id] = surface ? fog.a : 0.0;
    if (probe && records && surface) atomicAdd(s_count[record], 1u);
    for (uint stride = AREA_GROUP / 2u; stride > 0u; stride >>= 1u) {
        barrier();
        if (id < stride) {
            s_a[id] += s_a[id + stride];
            s_b[id] += s_b[id + stride];
        }
    }
    barrier();
    if (id == 0u) {
        const float now = s_b[0] > AREA_CAMERA_EPS ? clamp(s_a[0] / s_b[0], 0.0, 1.0) : 1.0;
        const float before = uintBitsToFloat(state.w[AREA_STATE_CAMERA]);
        // At blend 1 (the first gate, after a gap) or when the buffer holds no weight yet: now.
        const float faded = blend >= 1.0 || !(before >= 0.0 && before <= 1.0)
                                ? now
                                : mix(before, now, blend);
        s_camera = faded;
        state.w[AREA_STATE_CAMERA] = floatBitsToUint(faded);
        state.w[AREA_STATE_CAMERA_NOW] = floatBitsToUint(now);
        state.w[AREA_STATE_BEST] = floatBitsToUint(best);
        state.w[AREA_STATE_RECORD_COUNT] = records ? record_count : 0u;
    }
    if (!probe) return;

    // 3. The probe (uniform: a push constant): the grid's fog before and after the gate, the
    // records it saw and rows 0-7 of every record.
    barrier();
    const float camera = s_camera;
    const float keep = BeamKeep(fog.b);
    const float end = fog.a == 0.0 ? camera : here;
    const float before = fog.r + fog.g;
    const float after = fog.r * Segment(camera, keep) + fog.g * Segment(end, keep);
    s_v[id] = vec4(before, after, fog.b * before, fog.a == 0.0 ? 1.0 : 0.0);
    s_a[id] = surface ? 1.0 : 0.0;
    for (uint stride = AREA_GROUP / 2u; stride > 0u; stride >>= 1u) {
        barrier();
        if (id < stride) {
            s_v[id] += s_v[id + stride];
            s_a[id] += s_a[id + stride];
        }
    }
    barrier();
    if (id == 0u) {
        state.w[AREA_STATE_SURFACE] = uint(s_a[0] + 0.5);
        state.w[AREA_STATE_SKY] = uint(s_v[0].w + 0.5);
        state.w[AREA_STATE_BEFORE] = floatBitsToUint(s_v[0].x);
        state.w[AREA_STATE_AFTER] = floatBitsToUint(s_v[0].y);
        state.w[AREA_STATE_LIT] = floatBitsToUint(s_v[0].x > 0.0 ? s_v[0].z / s_v[0].x : 0.0);
    }
    state.w[AREA_STATE_COUNTS + id] = s_count[id];
    for (uint i = 0u; i < AREA_PROBE_ROW_FLOATS; ++i) {
        state.w[AREA_STATE_ROWS + id * AREA_PROBE_ROW_FLOATS + i] =
            records && id < record_count
                ? lighting.d[(offset_bytes >> 2) + id * AREA_RECORD_FLOATS + i]
                : 0u;
    }
}
#elif defined(APPLY)
layout(scalar, binding = 0) readonly buffer AreaState { uint w[]; } state;
layout(binding = 1) uniform sampler2D record_tex;
layout(binding = 2, rgba16f) uniform image2D fog_img;

void main() {
    const ivec2 px = ivec2(gl_GlobalInvocationID.xy);
    const ivec2 size = imageSize(fog_img);
    if (any(greaterThanEqual(px, size))) return;
    const vec4 v = imageLoad(fog_img, px);
    // Not marched, or no light: (0, 0, 0, 1 - depth), the same in both layouts.
    if (v.r == 0.0 && v.g == 0.0 && v.b == 0.0) return;
    float camera = uintBitsToFloat(state.w[AREA_STATE_CAMERA]);
    if (!(camera >= 0.0 && camera <= 1.0)) camera = 1.0;
    float end = camera;
    if (v.a != 0.0 && (flags & AREA_FLAG_RECORDS) != 0u) {
        end = uintBitsToFloat(state.w[AREA_STATE_WEIGHTS +
                                      RecordAt(record_tex, (vec2(px) + 0.5) / vec2(size))]);
    }
    const float keep = BeamKeep(v.b);
    const float fog = v.r * Segment(camera, keep) + v.g * Segment(end, keep);
    imageStore(fog_img, px, vec4(vec3(fog), v.a));
}
#else
#error build CAMERA or APPLY
#endif
''',
    R + "volumetric_area_gate.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r81_sun-fog-no-rt): the sun fog's area light gate, the part of "no sun fog indoors"
// that works without ray tracing. No Vulkan here: tests/test_volumetric_area_gate.cpp builds this
// header alone. The numbers are in host_shaders/volumetric_area_layout.h, which the shaders
// include too.
//
// BB_VOLUMETRIC_AREA_GATE, read once (at the first march): "1" on, anything else (unset too) off. On, every
// march WITHOUT the ray traced sun gate (no ray traced scene: effect_ray_tracing off, a GPU
// without ray queries, BB_VOLUMETRIC_RT_GATE=0, or a frame without a scene) keeps near and far
// energy and the lit share apart (the AREA builds of volumetric_light.comp), and right after the
// fog's tint at the game's directional light draw volumetric_area_gate.comp weighs them with the
// game's light sets: each pixel's record (the alpha byte of that draw's texture 0) and the
// camera's (a grid of them, nearer ones more). A record whose light 0 is as bright as half the
// brightest record's or more weighs 1 (the fog as without the gate); one at 15% or less weighs 0.
// Lit air whose ray is mostly in the atlas's shadow (a beam through a window in a roof the atlas
// holds) is kept whatever the light set. Off: none of it is made or run, and the march's builds
// are the ones before r81 (byte-identical SPIR-V).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>

#include "../host_shaders/volumetric_area_layout.h"

namespace Vulkan::VolumetricAreaGate {

inline constexpr std::uint32_t Group = AREA_GROUP, GridX = AREA_GRID_X, GridY = AREA_GRID_Y;
inline constexpr std::uint32_t Records = AREA_RECORDS, RecordFloats = AREA_RECORD_FLOATS;
inline constexpr std::uint32_t RecordBytes = RecordFloats * 4, RecordColour = AREA_RECORD_COLOUR;
inline constexpr std::uint32_t ProbeRowFloats = AREA_PROBE_ROW_FLOATS;
inline constexpr float SunLo = float(AREA_SUN_LO), SunHi = float(AREA_SUN_HI);
inline constexpr float BeamLo = float(AREA_BEAM_LO), BeamHi = float(AREA_BEAM_HI);
inline constexpr float FarMetres = float(AREA_FAR_METRES);
inline constexpr float CameraEps = float(AREA_CAMERA_EPS);
inline constexpr std::uint32_t FlagRecords = AREA_FLAG_RECORDS, FlagProbe = AREA_FLAG_PROBE;
inline constexpr std::uint32_t StateWords = AREA_STATE_WORDS, StateBytes = StateWords * 4;
// The state buffer's parts follow each other without a gap and the camera pass takes one grid
// point and one record a thread (local_size_x = 256 in volumetric_area_gate.comp).
static_assert(GridX * GridY == Group && Records == Group && Group == 256);
static_assert(AREA_STATE_RECORD_COUNT < AREA_STATE_WEIGHTS);
static_assert(AREA_STATE_COUNTS == AREA_STATE_WEIGHTS + Records);
static_assert(AREA_STATE_ROWS == AREA_STATE_COUNTS + Records);
static_assert(StateWords == AREA_STATE_ROWS + Records * ProbeRowFloats);
static_assert(ProbeRowFloats == 32 && RecordColour + 3 <= ProbeRowFloats);
static_assert(SunLo < SunHi && BeamLo < BeamHi && FarMetres > 0.0f);
static_assert(StateBytes <= 65536, "one vkCmdCopyBuffer region, a small buffer");

/// BB_VOLUMETRIC_AREA_GATE's text: exactly "1" is on.
inline bool Parse(const char* text) {
    return text && text[0] == '1' && text[1] == '\0';
}

/// The knob, read once.
inline bool On() {
    static const bool on = Parse(std::getenv("BB_VOLUMETRIC_AREA_GATE"));
    return on;
}

/// The records the camera pass weighs: as VolumetricLight::Tint counts them, at most 256.
inline std::uint32_t RecordCount(std::uint64_t range, std::uint32_t offset_bytes) {
    if (range < std::uint64_t(offset_bytes) + RecordBytes) {
        return 0;
    }
    return std::uint32_t(std::min<std::uint64_t>((range - offset_bytes) / RecordBytes, Records));
}

/// GLSL's smoothstep (edge0 < edge1).
inline float Smooth(float edge0, float edge1, float x) {
    const float t = std::clamp((x - edge0) / (edge1 - edge0), 0.0f, 1.0f);
    return t * t * (3.0f - 2.0f * t);
}

/// A record's light 0 colour as the TINT build and the camera pass read it: not a number gives 0,
/// clamped to 0, scaled to at most 1 per channel; its luminance.
inline float SunLuminance(const float* colour) {
    float rgb[3];
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(colour[i])) {
            return 0.0f;
        }
        rgb[i] = std::max(colour[i], 0.0f);
    }
    const float top = std::max(1.0f, std::max(rgb[0], std::max(rgb[1], rgb[2])));
    return (rgb[0] / top) * 0.2126f + (rgb[1] / top) * 0.7152f + (rgb[2] / top) * 0.0722f;
}

/// A light's colour as the table holds it (not scaled, unlike SunLuminance): not a number gives 0,
/// clamped to 0; its luminance. The probe shows it, so that a table whose colours exceed 1 (which
/// the scaling flattens) is seen.
inline float RawLuminance(const float* colour) {
    float rgb[3];
    for (int i = 0; i < 3; ++i) {
        if (!std::isfinite(colour[i])) {
            return 0.0f;
        }
        rgb[i] = std::max(colour[i], 0.0f);
    }
    return rgb[0] * 0.2126f + rgb[1] * 0.7152f + rgb[2] * 0.0722f;
}

/// The probe's rank of a record line as a word (the slot runner tells lines apart by their text
/// with the digits left out).
inline const char* RankName(std::uint32_t rank) {
    constexpr std::array<const char*, 4> names{"first", "second", "third", "fourth"};
    return rank < names.size() ? names[rank] : "-";
}

/// The TINT build's built-in white record: light 0 white, light 1 black, light 0 toward
/// (0.7071, 0.7071, 0). `record`: at least its first 24 floats.
inline bool IsFallback(const float* record) {
    for (int i = 0; i < 3; ++i) {
        if (record[RecordColour + i] != 1.0f || record[RecordColour + 4 + i] != 0.0f) {
            return false;
        }
    }
    return std::abs(record[0] - 0.70710678f) < 1e-3f && std::abs(record[1] - 0.70710678f) < 1e-3f &&
           std::abs(record[2]) < 1e-3f;
}

/// A record's weight from its light 0 luminance and the brightest record's. No brightest record
/// (all black, or none): 1, no gate.
inline float SunWeight(float luminance, float best) {
    if (!(best > 0.0f) || !std::isfinite(best)) {
        return 1.0f;
    }
    return Smooth(SunLo, SunHi, luminance / best);
}

/// How much of the lit air a ray keeps whatever the light set, from its share of samples in sun.
inline float BeamKeep(float lit) {
    return 1.0f - Smooth(BeamLo, BeamHi, lit);
}

/// A part of a ray: its light set's weight, and the beam's keep for the rest.
inline float Segment(float weight, float keep) {
    return weight + (1.0f - weight) * keep;
}

/// The fog a pixel keeps (the apply pass): `near_energy` and `far_energy` the march's energies (not
/// `near`/`far`: windows.h defines both as empty macros), `lit` its share in sun, `camera` and
/// `end` the weights of the camera's and the surface's light sets.
inline float Apply(float near_energy, float far_energy, float lit, float camera, float end) {
    const float keep = BeamKeep(lit);
    return near_energy * Segment(camera, keep) + far_energy * Segment(end, keep);
}

/// The camera's weight from the grid's sums (weight times 1 - depth, and 1 - depth): no surface
/// (all sky) is 1.
inline float CameraWeight(float weighted, float sum) {
    return sum > CameraEps ? std::clamp(weighted / sum, 0.0f, 1.0f) : 1.0f;
}

/// The probe's schedule: the first line at the 120th gated march, then every 600th.
struct ProbeClock {
    std::uint64_t marches = 0, due = 120;
    bool Next() {
        if (++marches < due) {
            return false;
        }
        marches = 0;
        due = 600;
        return true;
    }
};

/// The records the most grid points showed, most first (ties: the lower index), at most 4; a
/// record no point showed is left out (index Records).
inline std::array<std::uint32_t, 4> TopRecords(const std::uint32_t* counts) {
    std::array<std::uint32_t, 4> top{Records, Records, Records, Records};
    for (std::uint32_t id = 0; id < Records; ++id) {
        if (counts[id] == 0) {
            continue;
        }
        for (std::uint32_t k = 0; k < top.size(); ++k) {
            if (top[k] == Records || counts[id] > counts[top[k]]) {
                for (std::uint32_t m = std::uint32_t(top.size()) - 1; m > k; --m) {
                    top[m] = top[m - 1];
                }
                top[k] = id;
                break;
            }
        }
    }
    return top;
}

} // namespace Vulkan::VolumetricAreaGate
''',
    "engine/tests/test_volumetric_area_gate.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r81_sun-fog-no-rt): the sun fog's area light gate (volumetric_area_gate.h): the knob's
// text, the records' weights, the beam keep, the fog a pixel keeps, the camera's weight, the
// probe's schedule and its list of records.
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include "gpu/shadps4/video_core/renderer_vulkan/volumetric_area_gate.h"

using namespace Vulkan::VolumetricAreaGate;

namespace {
bool Near(float a, float b) {
    return std::abs(a - b) < 1e-5f;
}
}

int main() {
    // The knob: exactly "1" is on; unset, empty and anything else off.
    assert(!Parse(nullptr) && !Parse("") && !Parse("0") && !Parse("2") && !Parse("10") &&
           !Parse(" 1") && !Parse("1 ") && !Parse("on"));
    assert(Parse("1"));

    // Records as Tint counts them: whole 288-byte records after the offset, at most 256.
    assert(RecordBytes == 288 && RecordCount(64800, 0) == 225 && RecordCount(64800 + 100, 100) == 225);
    assert(RecordCount(287, 0) == 0 && RecordCount(288, 0) == 1 && RecordCount(400, 200) == 0);
    assert(RecordCount(1u << 20, 0) == 256);

    // GLSL's smoothstep.
    assert(Smooth(0.15f, 0.5f, 0.0f) == 0.0f && Smooth(0.15f, 0.5f, 0.15f) == 0.0f &&
           Smooth(0.15f, 0.5f, 0.5f) == 1.0f && Smooth(0.15f, 0.5f, 2.0f) == 1.0f);
    assert(Near(Smooth(0.15f, 0.5f, 0.325f), 0.5f));

    // Light 0's luminance: clamped, scaled to at most 1 a channel, not a number gives 0.
    const float white[3]{1.0f, 1.0f, 1.0f}, bright[3]{4.0f, 2.0f, 0.0f}, dark[3]{-1.0f, 0.1f, 0.0f};
    const float bad[3]{1.0f, std::numeric_limits<float>::quiet_NaN(), 0.0f};
    assert(Near(SunLuminance(white), 1.0f));
    assert(Near(SunLuminance(bright), 0.2126f + 0.5f * 0.7152f));
    assert(Near(SunLuminance(dark), 0.07152f) && SunLuminance(bad) == 0.0f);
    // As stored (the probe): not scaled, clamped, not a number gives 0.
    assert(Near(RawLuminance(bright), 4.0f * 0.2126f + 2.0f * 0.7152f) &&
           Near(RawLuminance(dark), 0.07152f) && RawLuminance(bad) == 0.0f);
    // The probe's ranks are words (the slot runner drops lines that differ only in digits).
    assert(std::strcmp(RankName(0), "first") == 0 && std::strcmp(RankName(3), "fourth") == 0 &&
           std::strcmp(RankName(4), "-") == 0);

    // The built-in white record (as the TINT build's is_fallback).
    std::array<float, AREA_PROBE_ROW_FLOATS> record{};
    record[0] = 0.70710678f;
    record[1] = 0.70710678f;
    record[16] = record[17] = record[18] = 1.0f;
    assert(IsFallback(record.data()));
    record[21] = 0.5f; // light 1 not black
    assert(!IsFallback(record.data()));
    record[21] = 0.0f;
    record[2] = 0.1f; // another direction
    assert(!IsFallback(record.data()));

    // Weights: half the brightest or more is 1 (no change), 15% or less is 0; no brightest is 1.
    assert(SunWeight(0.8f, 0.8f) == 1.0f && SunWeight(0.4f, 0.8f) == 1.0f);
    assert(SunWeight(0.1f, 0.8f) == 0.0f && SunWeight(0.0f, 0.8f) == 0.0f);
    assert(SunWeight(0.26f, 0.8f) > 0.0f && SunWeight(0.26f, 0.8f) < 1.0f);
    assert(SunWeight(0.0f, 0.0f) == 1.0f && SunWeight(0.3f, -1.0f) == 1.0f &&
           SunWeight(0.3f, std::numeric_limits<float>::infinity()) == 1.0f);

    // The beam keep: a ray mostly in shadow keeps its lit air, one mostly in sun does not.
    assert(BeamKeep(0.0f) == 1.0f && BeamKeep(0.35f) == 1.0f && BeamKeep(0.65f) == 0.0f &&
           BeamKeep(1.0f) == 0.0f && Near(BeamKeep(0.5f), 0.5f));

    // The fog a pixel keeps. Outdoors (weights 1): near + far, whatever the lit share.
    assert(Near(Apply(0.3f, 0.2f, 1.0f, 1.0f, 1.0f), 0.5f) && Near(Apply(0.3f, 0.2f, 0.0f, 1.0f, 1.0f), 0.5f));
    // Indoors (weights 0), air all in sun (no roof in the atlas): nothing.
    assert(Apply(0.3f, 0.2f, 1.0f, 0.0f, 0.0f) == 0.0f);
    // Indoors, a beam (a fifth of the ray in sun): all of it.
    assert(Near(Apply(0.3f, 0.2f, 0.2f, 0.0f, 0.0f), 0.5f));
    // Outdoor camera looking into a room: the near air stays, the room's does not.
    assert(Near(Apply(0.3f, 0.2f, 0.9f, 1.0f, 0.0f), 0.3f));
    // Indoor camera looking out at a sunlit street: only its last part (at the street) stays.
    assert(Near(Apply(0.3f, 0.2f, 0.9f, 0.0f, 1.0f), 0.2f));

    // The camera's weight: the grid's mean; no surface (all sky) is 1.
    assert(CameraWeight(0.0f, 0.0f) == 1.0f && CameraWeight(0.5f, 0.0f) == 1.0f);
    assert(Near(CameraWeight(0.25f, 1.0f), 0.25f) && CameraWeight(3.0f, 1.0f) == 1.0f);

    // The probe's schedule: the 120th march, then every 600th.
    ProbeClock clock;
    std::uint32_t lines = 0, first = 0, second = 0;
    for (std::uint32_t march = 1; march < 1320; ++march) {
        if (clock.Next()) {
            ++lines;
            (lines == 1 ? first : second) = march;
        }
    }
    assert(lines == 2 && first == 120 && second == 720);

    // The records the most grid points showed: most first, ties by index, no empty ones.
    std::array<std::uint32_t, Records> counts{};
    auto top = TopRecords(counts.data());
    assert(top[0] == Records && top[3] == Records);
    counts[7] = 30;
    counts[3] = 100;
    counts[200] = 30;
    counts[5] = 1;
    counts[9] = 2;
    top = TopRecords(counts.data());
    assert(top[0] == 3 && top[1] == 7 && top[2] == 200 && top[3] == 9);

    std::printf("volumetric area gate: all checks passed\n");
    return 0;
}
''',
}

# Text checks on the patched result (each string must occur exactly this often).
CHECKS = {
    H + "volumetric_light.comp": [('#ifdef AREA\n', 3), ('#elif defined(AREA)\n', 1), ('#include "volumetric_area_layout.h"', 1), ('area_lit / float(steps), 1.0 - depth));', 1), ('imageStore(fog_out, px, vec4(vec3(strength * phase * energy), 1.0 - depth));', 1), ('        energy += exp(-density * t) * density * ds * visibility(ray * t, texel);', 1), ('if (t < area_far_from) {', 1)],
    R + "vk_volumetric_light.h": [('#include "video_core/renderer_vulkan/volumetric_area_gate.h"', 1), ('void AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,', 1), ('Pass integrate_area, repair_area, area_camera, area_apply;', 1)],
    R + "vk_volumetric_light.cpp": [('bool VolumetricLight::AreaReady() {', 1), ('void VolumetricLight::AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,', 1), ('void VolumetricLight::ReadAreaProbe() {', 1), ('EffectPass::Mark(81, "volumetric area gate", true);', 1), ('const bool area = live_strength > 0.0f && !gated && VolumetricAreaGate::On() && AreaReady();', 1), ('pipeline = *(area ? (repairing ? repair_area : integrate_area) : pass).pipeline,', 1), ('layout = *(area ? (repairing ? repair_area : integrate_area) : pass).layout](', 1), ('pipeline = *pass.pipeline, layout = *pass.layout]', 0), ('area_pending = area;', 1), ('VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP', 1), ('VOLUMETRIC_LIGHT_REPAIR_AREA_COMP', 1), ('VOLUMETRIC_AREA_GATE_CAMERA_COMP', 1), ('VOLUMETRIC_AREA_GATE_APPLY_COMP', 1), ('Volumetric lighting (r81): area gate probe: on %llu of %llu marches', 1), ('Volumetric lighting (r81): area gate record ranked %s:', 1), ('static_assert(VolumetricAreaGate::RecordBytes == 72 * sizeof(float) &&', 1), ('Volumetric lighting (r81): area light gate on "', 1), ('Volumetric lighting (r81): area light gate off "', 1)],
    R + "vk_rasterizer_effects.cpp": [('volumetric_light->AreaGate(', 1)],
    "engine/gpu/CMakeLists.txt": [('volumetric_light_integrate_area_comp INTEGRATE=1 AREA=1)', 1), ('volumetric_light_repair_area_comp REPAIR=1 AREA=1)', 1), ('volumetric_area_gate_camera_comp CAMERA=1)', 1), ('volumetric_area_gate_apply_comp APPLY=1)', 1), ('list(APPEND INCLUDES ${SHADER_SRC}/volumetric_area_layout.h)', 1), ('volumetric-area-gate-test', 3)],
    "engine/build.sh": [('out/volumetric-area-gate-test', 2)],
    "engine/tests/test_effect_pipelines.cpp": [('VOLUMETRIC_LIGHT_INTEGRATE_AREA_COMP,', 1), ('VOLUMETRIC_LIGHT_REPAIR_AREA_COMP,', 1), ('VOLUMETRIC_AREA_GATE_CAMERA_COMP,', 1), ('VOLUMETRIC_AREA_GATE_APPLY_COMP,', 1)],
    "README.md": [('| `BB_VOLUMETRIC_AREA_GATE` |', 1), ('| `BB_VOLUMETRIC_GATE_VIEW` |', 1)],
    H + "volumetric_area_gate.comp": [('#include "volumetric_area_layout.h"', 1), ('#ifdef CAMERA', 2), ('#elif defined(APPLY)', 1), ('layout(local_size_x = AREA_GROUP, local_size_y = 1) in;', 1)],
    R + "volumetric_area_gate.h": [('#include "../host_shaders/volumetric_area_layout.h"', 1), ('float near,', 0), ('float far,', 0), ('inline float RawLuminance(', 1), ('inline const char* RankName(', 1)],
}

# Order checks on the patched result: each string after the one before it.
ORDER = {
    R + "vk_volumetric_light.cpp": ['bool VolumetricLight::AreaReady() {', 'void VolumetricLight::AreaGate(', 'void VolumetricLight::ReadAreaProbe() {', 'void VolumetricLight::EnsureImage(', 'const bool gated = live_strength', 'const bool area = live_strength', 'pipeline = *(area ?', 'area_pending = area;', '    ready = true;', 'void VolumetricLight::Tint('],
    R + "vk_rasterizer_effects.cpp": ['volumetric_light->Tint(dc.buffer_infos[0]', 'volumetric_light->AreaGate('],
    H + "volumetric_light.comp": ['#ifdef AREA\n// bbport (r81', '    local_splits = shared_splits;\n#ifdef AREA', '#elif defined(AREA)', 'area_lit / float(steps)', '#elif defined(TINT)'],
}

def load(path):
    raw = open(os.path.join(ROOT, path), "rb").read()
    crlf = raw.count(b"\r\n")
    if crlf not in (0, raw.count(b"\n")):
        raise SystemExit("%s: mixed line ends" % path)
    return raw, ("\r\n" if crlf else "\n"), raw.decode("utf-8").replace("\r\n", "\n")

def text_checks(texts):
    for path, items in CHECKS.items():
        for s, n in items:
            if texts[path].count(s) != n:
                raise SystemExit("text check: %s holds %r %d times, wanted %d"
                                 % (path, s, texts[path].count(s), n))
    for path, items in ORDER.items():
        at = -1
        for s in items:
            i = texts[path].find(s, at + 1)
            if i < 0:
                raise SystemExit("order check: %s: %r not after the one before" % (path, s))
            at = i

def new_state():
    """'clean' (no new file there), 'applied' (each holds exactly our text) or an error."""
    there = [p for p in NEW if os.path.exists(os.path.join(ROOT, p))]
    if not there:
        return "clean"
    if len(there) != len(NEW):
        raise SystemExit("new files: %d of %d there (%s)" % (len(there), len(NEW), ", ".join(there)))
    for p in NEW:
        if load(p)[2] != NEW[p]:
            raise SystemExit("%s exists with other text" % p)
    return "applied"

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (set R81_ROOT)" % ROOT)
    plan = {}
    for path, old, new in EDITS:
        if path not in plan:
            raw, eol, cur = load(path)
            plan[path] = [raw, eol, cur, []]
        plan[path][3].append((old, new))
    states = set()
    for path, (raw, eol, cur, edits) in plan.items():
        done = sum(cur.count(new) == 1 for old, new in edits)
        todo = sum(cur.count(old) == 1 and cur.count(new) == 0 for old, new in edits)
        if done == len(edits): states.add("applied")
        elif todo == len(edits): states.add("clean")
        else: raise SystemExit("%s: %d of %d edits applied, %d anchors found once" % (path, done, len(edits), todo))
    states.add(new_state())
    if len(states) != 1:
        raise SystemExit("mixed state: edits and new files disagree (%s)" % ", ".join(sorted(states)))
    state = states.pop()
    if state == "applied":
        texts = {p: v[2] for p, v in plan.items()}
        texts.update(NEW)
        if cmd == "check":
            text_checks(texts)
            print("applied (text checks pass)"); return
        if cmd == "apply":
            print("already applied"); return
        # revert: the new files hold exactly our text (new_state); the edits come out first
        outs = []
        for path, (raw, eol, cur, edits) in plan.items():
            for old, new in reversed(edits): cur = cur.replace(new, old)
            outs.append((path, cur.replace("\n", eol).encode("utf-8")))
        for path, data in outs:
            open(os.path.join(ROOT, path), "wb").write(data)
        for p in NEW:
            os.remove(os.path.join(ROOT, p))
        print("reverted"); return
    texts, outs = {}, []
    for path, (raw, eol, cur, edits) in plan.items():
        for old, new in edits: cur = cur.replace(old, new)
        texts[path] = cur
        outs.append((path, cur.replace("\n", eol).encode("utf-8"), raw))
    texts.update(NEW)
    text_checks(texts)
    if cmd == "check":
        print("not applied; would apply (%d files edited, %d new; text checks on the result pass)"
              % (len(plan), len(NEW))); return
    if cmd == "revert":
        print("nothing to revert"); return
    os.makedirs(BACKUP, exist_ok=True)
    for path, data, raw in outs:
        open(os.path.join(BACKUP, os.path.basename(path)), "wb").write(raw)
    written, made = [], []
    try:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r81tmp"
            open(tmp, "wb").write(data)
            os.replace(tmp, os.path.join(ROOT, path))
            written.append((path, raw))
        for p, text in NEW.items():
            full = os.path.join(ROOT, p)
            with open(full, "xb") as f:  # never over a file that is there
                f.write(text.replace("\n", "\r\n").encode("utf-8"))
            made.append(full)
    except Exception:
        for path, data, raw in outs:
            tmp = os.path.join(ROOT, path) + ".r81tmp"
            if os.path.exists(tmp): os.remove(tmp)
        for path, raw in written:
            open(os.path.join(ROOT, path), "wb").write(raw)
        for full in made:
            os.remove(full)
        raise
    print("applied"); return

main()
