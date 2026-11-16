// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r105_cloud-shadows): FEATURE, slow moving cloud shadows (cloud_shadow_params.h has the
// knobs and rules, host_shaders/cloud_shadow.comp the two passes).
//
// What gets dimmed: the sun or moon term only, by the light share of a large, soft, world
// anchored cloud mask that drifts with the clouds' direction:
//  - on the ground, walls, characters and anything else the game's directional light shades
//    through the screen shadow target: its alpha, which the ray traced sun (or the VSM) wrote
//    over every pixel with 0 < depth < 1 (RtShadow::Record in ContactShadow::Flush; Ground is
//    called right after it, before the game's directional light draw reads it). Ambient and sky
//    light, lamps, the torch, the sky and the game's own fog stay as they are. Where the ray
//    traced sun found shadow (alpha 0, so every interior its scene roofs over within the game's
//    shadow distance; past it the sun's filter writes 1, lit, for every pixel) nothing is written;
//    sunlight through a window is a cloud's to dim, as outdoors.
//  - in the engine's sun fog (effect_volumetric_light): its ray traced gate's cells, right after
//    they are traced (Gate, from VolumetricLight::Integrate), which every GATE build of the march
//    multiplies its sun answer by; so the lit samples dim under the clouds, also in the fog noise
//    (r94), wind (r82) and area gate (r85) builds of a gated march.
// What cannot be dimmed here: anything without the ray traced sun's alpha (graphics_rt_sun off,
// or a frame it did not run on: the game's own cascade alpha cannot tell an interior from the
// open sky past its shadow distance, so it is left alone and counted), a sun fog march without
// the ray traced gate (no ray traced scene, BB_VOLUMETRIC_RT_GATE=0, or the gate view), the
// march's area gate share of samples in sun (r81's beam measure, from the atlas), the lamp fog,
// the game's own fog sprites and distance fog, the sky dome, reflections of the sky, and any
// game shader that lights with the sun without that target (not known which, if any). The sun
// fog is clouded only on frames after one whose ground was (both, or neither, one frame apart).
//
// Off (BB_CLOUD_SHADOWS unset or 0 and no BB_CLOUD_SHADOWS_SHOW=1): the rasterizer makes no
// CloudShadow (Wanted), Active() stays null, and the four hooks are null pointer tests; no
// pipeline, sampler, buffer, image, pass or barrier; the frame is bit-identical. On: two
// pipelines and a sampler, made at the first pass; no image or buffer (the noise is ALU only).
#pragma once

#include <array>

#include "common/types.h"
#include "video_core/renderer_vulkan/cloud_shadow_params.h"
#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/renderer_vulkan/vk_contact_shadow.h"

namespace Vulkan {
class Instance;
class Scheduler;

class CloudShadow {
public:
    /// BB_CLOUD_SHADOWS above 0 or BB_CLOUD_SHADOWS_SHOW=1 (read once).
    [[nodiscard]] static bool Wanted();
    /// The one made by the rasterizer while it lives, else null (the passes' hooks in
    /// ContactShadow::Flush and VolumetricLight::Integrate ask it).
    [[nodiscard]] static CloudShadow* Active() noexcept;

    /// Says the knobs once.
    CloudShadow(const Instance& instance, Scheduler& scheduler);
    ~CloudShadow();
    CloudShadow(const CloudShadow&) = delete;
    CloudShadow& operator=(const CloudShadow&) = delete;

    /// At each sun shadow resolve: the direction toward the light (world) and the frame's camera
    /// (view to world rows), as VolumetricOcclusion::MakeSunLight found them; valid: both known.
    void SetSunLight(const std::array<float, 3>& world, const std::array<float, 12>& view_to_world,
                     bool valid);
    /// bbport (r119_volumetric-clouds): the clock the cloud layer shares: the drift state (offsets,
    /// heading) and the knobs (size, edges, speed).
    [[nodiscard]] const CloudShadows::State& ClockState() const {
        return state;
    }
    [[nodiscard]] const CloudShadows::Knobs& ClockKnobs() const {
        return knobs;
    }
    /// Each frame end: the direction and drift move (the wind's direction with BB_WIND=1), the
    /// periodic line.
    /// bbport (r116b_wind-weather): `wind_speed` (m/s) and `cover_shift` are the wind's weather this frame
    /// (CloudShadows::State::Advance); the defaults leave the knobs' speed and the edges.
    void OnFrameEnd(bool wind_on, float wind_deg, float wind_speed = -1.0f, float cover_shift = 0.0f);
    /// bbport (r116_wind-one-source): the heading (deg) and speed (m/s) the clouds move at now, for the
    /// wind's follower line.
    float Direction() const {
        return state.Direction();
    }
    float Velocity() const {
        return state.Velocity(knobs); // bbport (r116b): follows the wind's weather
    }
    /// Right after the ray traced sun (or the VSM) wrote the shadow target's alpha: the clouds
    /// into that alpha. `in`: the resolve's inputs (the shadow constants hold the camera's inverse
    /// projection); `depth`, `target`: the views ContactShadow::Flush gave RtShadow::Record (the
    /// reduced proxies while the scene is reduced), in the general layout.
    void Ground(const ContactShadow::Inputs& in, vk::ImageView depth, vk::ImageView target,
                u32 width, u32 height);
    /// Right after the sun fog's ray traced gate was traced: the clouds into its cells (R8, general
    /// layout); `reach`: the march's (GateRange).
    void Gate(const ContactShadow::Inputs& in, vk::ImageView gate, u32 width, u32 height,
              u32 slices, float reach);

private:
    bool Ready();

    const Instance& instance;
    Scheduler& scheduler;
    const CloudShadows::Knobs knobs;
    CloudShadows::State state;

    vk::UniqueDescriptorSetLayout ground_set_layout, gate_set_layout;
    vk::UniquePipelineLayout ground_layout, gate_layout;
    vk::UniquePipeline ground_pipeline, gate_pipeline;
    vk::UniqueSampler sampler;
    bool tried = false;
    bool failed = false;

    std::array<float, 3> light{};
    std::array<float, 12> rows{};
    bool light_valid = false;
    bool ground_now = false;  ///< Ground ran this frame
    bool ground_last = false; ///< ... in the frame before (Gate acts then)
    double clock_last = -1.0; ///< s (steady clock) at the last OnFrameEnd; below 0: none yet
    double said_at = 0.0;     ///< state time of the last SHOW line
    u32 frames = 0, resolves = 0, unlit = 0, ground_calls = 0, ground_passes = 0, gate_passes = 0,
        gate_skipped = 0;
};

} // namespace Vulkan
