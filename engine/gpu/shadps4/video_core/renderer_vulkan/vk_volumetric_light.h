// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <chrono>
#include <span>
#include <vector>

#include <span>

#include "video_core/buffer_cache/buffer.h"
#include "video_core/renderer_vulkan/lamp_fog_lights.h"
#include "video_core/renderer_vulkan/lamp_fog_shafts.h" // bbport (r80_lamp-fog-shafts)
#include "video_core/renderer_vulkan/lamp_fog_shaft_cap.h" // bbport (r106_lamp-fog-shaft-cap)
#include "video_core/renderer_vulkan/lamp_fog_shaft_fast.h" // bbport (r106c_shaft-march-cheaper)
#include "video_core/renderer_vulkan/lamp_fog_shaft_smooth.h" // bbport (r80b_shafts-smooth-visible)
#include "video_core/renderer_vulkan/vk_contact_shadow.h"
#include "video_core/renderer_vulkan/vk_point_shadow.h"
#include "video_core/renderer_vulkan/volumetric_occlusion.h" // bbport (r76_sun-fog-outdoors)
#include "video_core/renderer_vulkan/volumetric_area_gate.h"  // bbport (r81_sun-fog-no-rt)
#include "video_core/renderer_vulkan/volumetric_roof.h" // bbport (r115b_sun-fog-out-of-sewer-library)
#include "video_core/renderer_vulkan/volumetric_fog_noise.h" // bbport (r94_fog-noise)

namespace Vulkan {
class SceneTargets;

class VolumetricLight {
public:
    VolumetricLight(const Instance& instance, Scheduler& scheduler,
                    VideoCore::TextureCache& texture_cache, Runtime& runtime,
                    SceneTargets& scene_targets);
    ~VolumetricLight();

    void Reset() { ready = tinted = false; scene = {}; fog_lights.Clear(); }
    void Integrate(VideoCore::ImageId shadow_target, const vk::DescriptorImageInfo& depth,
                   const ContactShadow::Inputs& inputs);
    void Tint(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes);
    /// bbport (r81_sun-fog-no-rt): BB_VOLUMETRIC_AREA_GATE=1: after a march (bbport
    /// (r85_area-with-rt-gate): with the ray traced sun gate or without it, not one the gate view
    /// draws), weighs its fog with the game's light sets (volumetric_area_gate.comp). `lighting`
    /// and `offset_bytes` as Tint's; `records` the directional draw's texture 0, whose alpha byte
    /// names each pixel's record (a null view: none; the fog is then as without the gate). Called
    /// right after Tint at the same draw; does nothing unless the last Integrate kept the layout.
    void AreaGate(const vk::DescriptorBufferInfo& lighting, u32 offset_bytes,
                  const vk::DescriptorImageInfo& records);
    void Scene(VideoCore::ImageId color);
    void AddPointLights(const u32* constants, const u32* lights, u32 count);
    void SetCamera(const LampFog::Camera& camera) { fog_camera = camera; }
    /// bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS set only: this frame's ray traced scene
    /// (RtShadow::Scene, in the camera's view space) for the next Composite's lamp fog shadow
    /// maps. Taken (and cleared) by that lamp fog; null: the lamp fog of before.
    void SetLampScene(vk::AccelerationStructureKHR scene_) noexcept { lamp_scene = scene_; }
    /// bbport (r82_wind-stage1): BB_WIND=1 only, right before Integrate: the fog noise's offsets
    /// (cells, BbWind::Snapshot) and the camera's view to world matrix (3x4 rows) at that call.
    /// The next Integrate marches with the drifting density; without a camera, the plain way.
    /// `show`: BB_WIND_SHOW=1 (read once by the rasterizer) for the "Wind fog:" line.
    void SetWind(const std::array<float, 3>& off1, const std::array<float, 3>& off2,
                 const std::array<float, 12>& view_to_world, bool camera_valid, bool show);
    /// bbport (r94_fog-noise): BB_FOG_NOISE above 0 or BB_FOG_NOISE_SHOW=1 (read and said once, at
    /// the first call): the sun fog's world anchored noise is on. The rasterizer asks it before
    /// every Integrate and calls SetFogNoise only when it is true.
    static bool FogNoiseKnob();
    /// bbport (r94_fog-noise): right before Integrate, after SetWind: the G-buffer pass's view to
    /// world matrix at this call and the wind's snapshot (on, its time in s, its velocity in m/s),
    /// which moves the noise only while the wind is on. The next Integrate marches with the noise
    /// (its NOISE builds carry the drift, so r82's WIND build is not bound for it); without a
    /// camera, as it would without the noise.
    void SetFogNoise(bool wind_on, double wind_time, const std::array<float, 3>& wind_velocity,
                     const std::array<float, 12>& view_to_world, bool camera_valid);
    /// bbport: the sun atlas cascades drawn in full (the first `count`); the march treats the
    /// others as outside the atlas (Rasterizer::SunAtlasSkipDraw). bbport (r51_volumetric-leak):
    /// and those not in `valid` (VolumetricOcclusion::Valid).
    void SetAtlasCascades(u32 count, u32 valid) noexcept {
        atlas_cascades = count;
        atlas_valid = valid;
    }
    /// bbport (r51b_volumetric-rt-check): this frame's ray traced scene (RtShadow::Scene, in the
    /// camera's view space) and the instance mask the sun gate traces (BB_VOLUMETRIC_RT_GATE;
    /// r76_sun-fog-outdoors: 1 when not set, 0 without a scene: VolumetricOcclusion::GateInForce),
    /// for the next Integrate. A null scene or mask 0: no gate, the march of stage A.
    void SetSunScene(vk::AccelerationStructureKHR scene_, u32 mask) noexcept {
        sun_scene = scene_;
        sun_scene_mask = mask;
    }
    /// bbport (r76_sun-fog-outdoors): the scene's instances in TLAS order (RtShadow::GateTable,
    /// filled only with BB_VOLUMETRIC_GATE_PROBE=1; null: no scene), for the next Integrate.
    void SetSunSceneTable(const std::vector<VolumetricOcclusion::GateInstance>* table) noexcept {
        sun_scene_table = table;
    }
    /// bbport (r76c_sun-fog-shells): what the capture knew of those instances, in the same order
    /// (RtShadow::GateCaptures; probe only; null: none), for the next Integrate.
    void SetSunSceneCaptures(const std::vector<VolumetricOcclusion::GateCapture>* captures) noexcept {
        sun_scene_captures = captures;
    }
    /// bbport (r76_sun-fog-outdoors): the light as the host reads it at this resolve
    /// (VolumetricOcclusion::MakeSunLight), for the next Integrate's line (SayLight).
    void SetSunLight(const VolumetricOcclusion::SunLight& light) noexcept {
        sun_light = light;
    }
    /// How far the last Integrate marched through the sun atlas (m); 0: it did not sample it.
    [[nodiscard]] float AtlasReach() const noexcept { return atlas_reach; }
    /// bbport (r115b_sun-fog-out-of-sewer-library): BB_VOLUMETRIC_ROOF as the engine reads it (live): 1
    /// scales the sun fog's strength by VolumetricRoof::Keep of the cover SetRoofCover gave right before
    /// Integrate (-1: no shelter field); 0 off, and then SetRoofCover is not called.
    static u32 RoofMode();
    void SetRoofCover(float cover) noexcept { roof_cover = cover; }
    void Composite(VideoCore::ImageId fallback = {}, const char* where = "HDR post");

private:
    struct Pass {
        vk::UniqueDescriptorSetLayout set;
        vk::UniquePipelineLayout layout;
        vk::UniquePipeline pipeline;
    };
    bool Ready();
    void RecordLampFog(std::span<const std::array<u32, 16>> lights, u32 w, u32 h);
    // bbport (r80_lamp-fog-shafts): BB_LAMP_FOG_SHAFTS: the shadow maps' pass, the march's SHAFTS
    // build and the maps, made at the first lamp fog with lights and a scene; the maps and the
    // shadowed march in place of RecordLampFog's pass
    bool ShaftsReady(u32 level);
    // bbport (r106_lamp-fog-shaft-cap): in RecordShafts: which lamps get a map this frame within
    // BB_LAMP_FOG_SHAFTS_RAYS (shaft_planner), the table both passes read (`table`), the r106
    // line's sums; returns the maps to build this frame
    u32 PlanShafts(const std::vector<u32>& data, u32 count, std::vector<u32>& table);
    void RecordShafts(vk::AccelerationStructureKHR shaft_scene, u32 count, float intensity,
                      float glow_size, std::vector<u32> data,
                      const vk::DescriptorBufferInfo& constants,
                      const vk::DescriptorBufferInfo& records, const vk::DescriptorImageInfo& depth,
                      const vk::DescriptorImageInfo& out, u32 w, u32 h);
    bool CreatePass(Pass& pass, std::initializer_list<vk::DescriptorType> types,
                    std::span<const u32> code, u32 push_size, const char* name,
                    bool dispatch_base = false);
    void EnsureImage(u32 width, u32 height);
    bool Enabled();
    // bbport (r51b_volumetric-rt-check): the sun gate's passes and image, made at first use
    bool GateReady();
    void RecordGate(const ContactShadow::Inputs& in, u32 offsets, bool probing, bool viewing,
                    const vk::DescriptorImageInfo& depth);
    // bbport (r76_sun-fog-outdoors): BB_VOLUMETRIC_GATE_PROBE / BB_VOLUMETRIC_GATE_VIEW
    bool DiagReady();
    bool EnsureGateView();
    void ReadGateProbe();
    void ReadGateInstances(const std::array<u32, VolumetricOcclusion::GateProbeWords>& words); // (r76c)
    void SayLight();
    // bbport (r81_sun-fog-no-rt): the area light gate (BB_VOLUMETRIC_AREA_GATE=1), made at the first
    // march while the knob is on (bbport (r85_area-with-rt-gate): with the ray traced gate or
    // without it): the march's AREA builds, its two passes, its state (volumetric_area_layout.h,
    // 35 KB) and the probe's copy of it for the host
    bool AreaReady();
    void ReadAreaProbe();
    Pass integrate_area, repair_area, area_camera, area_apply;
    // bbport (r85_area-with-rt-gate): the march's AREA+GATE builds (the GATE builds' bindings), made
    // at the first march with the ray traced gate while the knob is on (AreaGatedReady; failing
    // leaves such marches without the area gate); AreaPass: the build an area gate march binds, by
    // (gated, repairing); AreaViewKnob: BB_VOLUMETRIC_GATE_VIEW as Integrate's area decision reads
    // it (once a march, only while the knob is on); the flags of the once-lines that say which
    // case acts (Integrate)
    bool AreaGatedReady();
    const Pass& AreaPass(bool gated, bool repairing, bool dual = false) const {
        if (dual) { // bbport (r115_sun-fog-indoors): a DUAL march (DualReady made them)
            return repairing ? repair_dual : integrate_dual;
        }
        return gated ? (repairing ? repair_gated_area : integrate_gated_area)
                     : (repairing ? repair_area : integrate_area);
    }
    static bool AreaViewKnob() { return VolumetricOcclusion::GateView(); }
    Pass integrate_gated_area, repair_gated_area;
    bool area_rt_tried = false, area_rt_failed = false;
    bool area_said_plain = false, area_said_traced = false, area_said_view = false;
    std::unique_ptr<VideoCore::Buffer> area_state, area_readback;
    std::chrono::steady_clock::time_point area_time{};
    VolumetricAreaGate::ProbeClock area_clock;
    VolumetricOcclusion::SunLight area_probe_light{};
    u64 area_probe_tick = 0, area_marches = 0, area_gated = 0;
    bool area_tried = false, area_failed = false, area_said = false;
    bool area_pending = false; ///< the last Integrate kept the AREA layout: AreaGate is owed
    bool area_probe_pending = false;
    // bbport (r115_sun-fog-indoors): BB_VOLUMETRIC_AREA_GATE read live (AreaMode: 0 off, 1 r81 and
    // r85, 2 r115); DualReady makes at the first DUAL march the gate's DUAL build, the march's two
    // DUAL builds and the wider answer's image (160x90x32 bytes); RecordGate traces the DUAL build
    // while gate_dual_on; the flags the last Integrate left for AreaGate and the probe's; the mode
    // last said and the counts of the 600-march line (SayAreaMode); the probe's near line
    static u32 AreaMode();
    bool DualReady();
    void SayAreaMode(u32 mode, bool area, bool gated, bool dual);
    void SayAreaNearProbe(const u32* words);
    // bbport (r115b_sun-fog-out-of-sewer-library): the factor of this march's strength (1.0f when off),
    // the cover SetRoofCover gave, the counts of the 600-march line and the mode last said
    float RoofKeep();
    float roof_cover = -1.0f;
    VolumetricRoof::Counts roof_counts{};
    u32 roof_mode_seen = ~0u;
    bool roof_said_no_field = false;
    Pass gate_dual, integrate_dual, repair_dual;
    VideoCore::UniqueImage gate_open;
    vk::UniqueImageView gate_open_view;
    bool dual_tried = false, dual_failed = false, gate_dual_on = false;
    bool area_near_pending = false, area_dual_pending = false;
    u32 area_probe_flags = 0, area_mode_seen = ~0u;
    u64 r115_marches = 0, r115_area = 0, r115_dual = 0, r115_plain = 0;
    // bbport (r82_wind-stage1): makes the WIND builds once (the gated ones at the first gated
    // march that drifts); false: the march stays plain. WindFogCheck: the BB_WIND_SHOW=1 line.
    bool WindPasses(bool gated);
    void WindFogCheck();
    // bbport (r94_fog-noise): BB_FOG_NOISE above 0 only (vk_volumetric_fog_noise.cpp): whether the
    // march takes the noise (after SetFogNoise; not a march the gate view draws; the NOISE builds
    // of its (gated, area) pair made at the pair's first march, a failure said once), the build it
    // then binds, its push words after Params, the builds (index: bit 0 gated, 1 area, 2 repair),
    // and the state: the next Integrate's input, the drift, the pairs tried and failed, and the
    // counts of the 600-march line
    bool FogNoiseMarch(bool viewing, bool gated, bool area);
    bool NoisePasses(bool gated, bool area);
    const Pass& NoisePass(bool gated, bool area, bool repairing) const;
    VolumetricFogNoise::Tail FogNoiseTail() const;
    std::array<Pass, 8> noise_passes;
    struct FogNoise {
        bool on = false, drifting = false;
        std::array<bool, 4> tried{}, failed{};
        std::array<float, 12> view_to_world{};
        VolumetricFogNoise::Drift drift;
        u64 marches = 0, gated = 0, area = 0, drifted = 0, even = 0, no_camera = 0;
    } fog_noise;

    const Instance& instance;
    Scheduler& scheduler;
    VideoCore::TextureCache& texture_cache;
    Runtime& runtime;
    SceneTargets& scene_targets;
    Pass integrate, repair, tint, filter, composite, point;
    std::unique_ptr<VideoCore::Buffer> tint_state;
    std::chrono::steady_clock::time_point tint_time{};
    std::unique_ptr<VideoCore::Buffer> fog_data;
    std::array<u32, 16> fog_matrix{};
    LampFog::FrameLights fog_lights;
    bool fog_mode_logged = false;
    LampFog::Memory fog_memory;
    LampFog::Camera fog_camera;
    // bbport (r80_lamp-fog-shafts): the scene SetLampScene gave; the passes ShaftsReady made; the
    // maps (a layer per lamp with r106, shaft_size texels a side); the 600-frame line's counts and
    // the once-line's flag
    vk::AccelerationStructureKHR lamp_scene{};
    Pass shaft_map, point_shafts;
    VideoCore::UniqueImage shaft_maps;
    vk::UniqueImageView shaft_maps_view;
    u32 shaft_size = 0;
    u64 shafts_frames = 0, shafts_shadowed = 0;
    bool shafts_tried = false, shafts_failed = false, shafts_said = false;
    // bbport (r106_lamp-fog-shaft-cap): BB_LAMP_FOG_SHAFTS set only: the lamps' maps from frame
    // to frame, the table (made by ShaftsReady), whether the maps hold earlier frames' layers
    // (no Undefined layout then), the once-line's flag, the plan's clock, the r106 line's sums
    LampFogShaftCap::Planner shaft_planner;
    std::unique_ptr<VideoCore::Buffer> shaft_table;
    bool shaft_maps_kept = false, shaft_cap_said = false;
    std::chrono::steady_clock::time_point shaft_time{};
    LampFogShaftCap::Totals shaft_totals;
    std::chrono::steady_clock::time_point fog_memory_time{};
    vk::UniqueSampler sampler;
    VideoCore::UniqueImage fog;
    vk::UniqueImageView fog_view;
    VideoCore::UniqueImage filtered_fog;
    vk::UniqueImageView filtered_view;
    VideoCore::UniqueImage repair_fog;
    vk::UniqueImageView repair_view;
    VideoCore::UniqueImage point_fog;
    vk::UniqueImageView point_view;
    VideoCore::UniqueImage depth_snapshot;
    vk::UniqueImageView depth_view;
    VideoCore::ImageId scene{};
    u64 scene_uid = 0;
    u32 depth_width = 0, depth_height = 0;
    u32 width = 0, height = 0;
    float strength = 0.08f;
    float reach = 40.0f;
    float density = 0.025f;
    float anisotropy = 0.4f;
    u32 steps = 32;
    u32 atlas_cascades = 4;
    u32 atlas_valid = 0xF; ///< bbport (r51_volumetric-leak): bit c set: cascade c may be read
    float atlas_reach = 0.0f;
    // bbport (r51b_volumetric-rt-check): the ray traced sun gate (SetSunScene, GateReady)
    vk::AccelerationStructureKHR sun_scene{};
    u32 sun_scene_mask = 0;
    Pass gate_volume, integrate_gated, repair_gated;
    vk::UniqueSampler gate_sampler;
    VideoCore::UniqueImage gate;
    vk::UniqueImageView gate_view;
    // bbport (r76_sun-fog-outdoors): each column's first open slice (volumetric_rt_gate.comp)
    VideoCore::UniqueImage gate_first;
    vk::UniqueImageView gate_first_view;
    u64 gate_marches = 0, gate_traced = 0;
    bool gate_tried = false, gate_failed = false;
    bool gate_off_said = false; ///< bbport (r76_sun-fog-outdoors): the once-line of an ungated run
    // bbport (r84_live-test-knobs): the gate's knobs as Integrate last saw them (a change is said)
    u32 gate_knob_seen = ~0u;
    bool probe_knob_seen = false, view_knob_seen = false;
    // bbport (r76_sun-fog-outdoors): the gate's diagnostics (DiagReady, EnsureGateView, made only
    // with their knobs): the DIAG build of the gate and the GATE_VIEW builds of the march and the
    // composite; each cell's band; the view's image (the march's size); the probe's words on the
    // GPU and their copy for the host; the instances and light of the march probed
    Pass gate_diag, integrate_gated_view, composite_view;
    VideoCore::UniqueImage gate_band;
    vk::UniqueImageView gate_band_view;
    VideoCore::UniqueImage gate_view_image;
    vk::UniqueImageView gate_view_image_view;
    u32 gate_view_width = 0, gate_view_height = 0;
    std::unique_ptr<VideoCore::Buffer> probe_buffer, probe_readback;
    const std::vector<VolumetricOcclusion::GateInstance>* sun_scene_table = nullptr;
    std::vector<VolumetricOcclusion::GateInstance> probe_table;
    // bbport (r76c_sun-fog-shells): the instances' captures (SetSunSceneCaptures) and those of the
    // march probed; the DIAG build's words per instance and their copy for the host, and how many
    // instances that copy holds; whether the probe's file was begun this run
    const std::vector<VolumetricOcclusion::GateCapture>* sun_scene_captures = nullptr;
    std::vector<VolumetricOcclusion::GateCapture> probe_caps;
    std::unique_ptr<VideoCore::Buffer> probe_stats, probe_stats_readback;
    std::size_t probe_stats_count = 0;
    bool probe_file_begun = false;
    VolumetricOcclusion::SunLight sun_light{}, probe_light{};
    u32 probe_mask = 0;
    u64 probe_marches = 0, probe_due = 120, probe_tick = 0;
    bool probe_pending = false, diag_tried = false, diag_failed = false, diag_said = false;
    bool view_drawn = false; ///< this frame's march wrote the view's image (Composite reads it)
    // bbport (r76_sun-fog-outdoors): SayLight's last direction said, its march and the line count
    std::array<float, 3> light_said{};
    u64 light_marches = 0, light_said_at = 0;
    u32 light_lines = 0;
    // bbport (r82_wind-stage1): the WIND builds of the march (plain and gated), the view
    // composite (BB_WIND_VIEW=1), and the drift's state: the next Integrate's input (SetWind: on,
    // the matrix, the offsets with the contrast and the view flag in [3]), whether the last
    // Integrate drifted (used), and the counts of the BB_WIND_SHOW=1 line (WindFogCheck).
    Pass integrate_wind, repair_wind, integrate_gated_wind, repair_gated_wind, composite_wind_view;
    struct WindFog {
        bool wanted = false, on = false, used = false, show = false;
        bool tried = false, failed = false, gate_tried = false, gate_failed = false;
        std::array<float, 12> view_to_world{};
        std::array<float, 4> off1{}, off2{};
        u32 frames = 0, no_camera = 0, compared = 0;
        float gap = 0.0f;
        std::chrono::steady_clock::time_point next_line{};
    } wind_fog;
    // bbport (r88_wind-lamp-fog): BB_WIND=1 only: the lamp fog's WIND builds (point_wind; with
    // r80's shadow maps point_shafts_wind, SHAFTS or SHAFTS VIEW as ShaftsReady's level), made at
    // the first lamp fog that drifts (LampWindPasses; false: that lamp fog stays even);
    // LampWindDrift: this frame's decision with its once-line and the 120/600-frame line; the
    // offsets SetWind gave, the contrast, and the counts of that line
    bool LampWindPasses(bool shafts, u32 level);
    bool LampWindDrift(u32 lights);
    Pass point_wind, point_shafts_wind;
    struct LampWind {
        bool wanted = false, drift = false, said = false;
        bool tried = false, failed = false, shafts_tried = false, shafts_failed = false;
        std::array<float, 3> off1{}, off2{};
        float contrast = 0.0f;
        u32 lines = 0;
        u64 frames = 0, drifted = 0, shafts_drifted = 0, no_camera = 0, even = 0;
    } lamp_wind;
    bool ready = false;
    bool tinted = false;
    bool tried = false;
    bool failed = false;
    bool composite_reported = false;
    bool tint_reported = false;
};

}
