# r105_cloud-shadows: FEATURE patch (order items "Foliage sway and clouds" and "Fog and wind go by
# cloud direction"). Slow moving cloud shadows: a large, soft, world anchored noise mask that dims
# the sun's (at night the moon's) term on the ground and in the engine's sun fog, drifting with the
# clouds' direction (BB_CLOUDS_DIR, else the wind's with BB_WIND=1, else "auto": across the light).
# Off by default behind BB_CLOUD_SHADOWS (strength 0..1; unset or 0: off) and BB_CLOUD_SHADOWS_SHOW.
#
# Review fixes (r105_cloud-shadows.fixed.py, 2026-11-15): FullDepth 0.6 -> 0.45 (a full cloud at
# strength 1 keeps 55% of the sun or moon term, mean 0.85: "visible but gentle" at night); the
# frame end hook anchored before `effects_wanted = AnyWanted();` (r89 adds its own line after
# WindOnFrameEnd, which made this script's check fail once r89 was applied after it); the periodic
# line's "resolves without the ray traced sun" no longer counts the resolves without a light or
# whose pass could not run; README/header state the shadow distance limit of "interiors are not
# touched"; the README's fog noise numbers are tied to fog_noise_layout.h (rule 10).
#
# What is dimmed, exactly (vk_cloud_shadow.h says the same):
#  - the screen shadow target's alpha (the sun visibility the game's directional light reads),
#    right after the ray traced sun (or the VSM) wrote it (RtShadow::Record in ContactShadow::Flush),
#    where 0 < depth < 1 and alpha > 0: alpha *= the cloud's light share. So the ground, walls,
#    characters and anything the game's directional light shades through that target. Interiors the
#    ray traced sun already shuts (alpha 0) are not written; sunlight through a window is dimmed.
#  - the sun fog's ray traced gate cells (R8, 160x90x32), right after they are traced
#    (VolumetricLight::Integrate): every GATE build of the march multiplies its sun answer by the
#    gate, so the fog's lit samples dim under the clouds (also the r94 noise, r82 wind and r85 area
#    gate builds of a gated march).
# What cannot be dimmed here: anything without the ray traced sun's alpha (graphics_rt_sun and the
# VSM off, or a frame neither ran: the game's own cascade alpha cannot tell an interior from open
# sky past its shadow distance, so it is left alone and counted in the log), a sun fog march without
# the ray traced gate (no scene, BB_VOLUMETRIC_RT_GATE=0, the gate view), the area gate's share of
# samples in sun, lamp fog, the game's own fog sprites and distance fog, the sky dome (no clouds are
# drawn in the sky; the probe r104 is the first step there), reflections, and any game shader that
# lights with the sun without that target (not known which, if any). The sun fog is clouded only on
# frames after one whose ground was (one frame apart at worst).
#
# What (new files; the shared files get only hook lines, each insertion a block of its own):
#  1. renderer_vulkan/cloud_shadow_params.h (new, pure): the knobs (read once by vk_cloud_shadow.cpp
#     and passed in as text), the light rule, the direction rule (env > wind > auto, auto eased with
#     8 s), the drift (r94's VolumetricFogNoise::Drift, shared, not copied) and the 120-byte push
#     block. tests/test_cloud_shadows.cpp (new): its checks, built and run by engine/build.sh --test
#     and the CMake target cloud-shadows-test.
#  2. host_shaders/cloud_shadow.comp (new, two builds: the ground pass, and GATE=1 for the sun fog
#     gate). The noise is r94's: fog_noise.glsl's fog_noise_value and fog_noise_cells with
#     fog_noise_layout.h's octave numbers, included with FOG_NOISE_VALUE_ONLY defined.
#     host_shaders/fog_noise.glsl: an #ifndef FOG_NOISE_VALUE_ONLY ... #endif around its two
#     functions that read r94's push words (fog_noise_m, fog_noise_weight); the NOISE builds of
#     volumetric_light.comp never define it, so their SPIR-V is byte-identical (proved).
#  3. renderer_vulkan/vk_cloud_shadow.h/.cpp (new): class CloudShadow: the two passes, two
#     pipelines and a sampler made at the first pass, the once-line and the periodic line.
#  Hooks in shared files:
#   - vk_rasterizer.h: the include (after vk_contact_shadow.h's) and the member (after
#     contact_shadow).
#   - vk_rasterizer.cpp: made after the contact shadows, only when CloudShadow::Wanted().
#   - vk_rasterizer_effects.cpp: the light and camera (after volumetric_light->SetSunLight) and the
#     frame end (before `effects_wanted = AnyWanted();`, so after WindOnFrameEnd: this frame's wind).
#   - vk_contact_shadow.cpp: the include and the ground pass right after the ray traced sun's Record.
#   - vk_volumetric_light.cpp: the include and the gate pass right after RecordGate.
#   - engine/gpu/CMakeLists.txt: the shader's dependency on fog_noise.glsl and fog_noise_layout.h
#     (after r94's block), the two builds (before sky_seam's) and cloud-shadows-test (before r51's
#     volumetric-occlusion-test block).
#   - engine/build.sh: cloud-shadows-test (after r94's volumetric-fog-noise-test).
#   - engine/tests/test_effect_pipelines.cpp: the includes and the two pipeline rows (after the
#     contact shadows').
#   - README.md: a "Cloud shadows (in development)" section before "Halation (in development)".
#
# Off: the rasterizer makes no CloudShadow (unique_ptr null; CloudShadow::Active() null), and the
# four hooks are null pointer tests; no pipeline, sampler, image, buffer, pass or barrier; the frame
# is bit-identical. The shader's SPIR-V is in the binary only as two header arrays.
# Cost on: the ground pass is one compute dispatch over the shadow target (8x8 groups; per pixel a
# depth fetch, an image load and store, and 3 octaves x 8 hashed lattice corners: 24 lowbias32
# hashes), skipped early on sky, shadow and interiors; the gate pass touches 460,800 cells (24
# hashes each, open cells only). Estimate 0.02-0.05 ms at 1080p internal for the ground pass and
# under 0.01 ms for the gate, not measured; row "Lighting: cloud shadows" of BB_GPU_PROFILE=1.
# Memory: no image or buffer (the noise is ALU only); two pipelines and a sampler.
# Night: the same rule; the moon term is the one dimmed, which is already small, so the change is
# gentle in absolute terms (a full cloud at strength 1 keeps 55% of it).
# Noise numbers in the README (44% clear, 15% full, mean 0.85) are from a CPU probe of 60000 points
# of the same noise (scratch r105_noise_sim.py), not from the game.
#
# Use: python -I -X utf8 r105_cloud-shadows.py check | apply | revert. Root from R105_CLOUD_SHADOWS_ROOT
# (or R105_ROOT), else <tree>. Files keep their line ends; new files are written with CRLF.
# apply keeps the edited files' originals in r105_backup/ next to this script. revert removes
# exactly this patch's blocks (so patches applied after it in the same files stay) and the new files
# (only when unchanged); it refuses when a block is not found exactly once. Revert r105 before r94
# (its fog_noise.glsl guard sits in r94's file).
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "r105_backup")
ROOT = os.environ.get("R105_CLOUD_SHADOWS_ROOT") or os.environ.get("R105_ROOT") or "<tree>"
V = "engine/gpu/shadps4/video_core/"
R = V + "renderer_vulkan/"
H = V + "host_shaders/"

NEW = {
    R + "cloud_shadow_params.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

// bbport (r105_cloud-shadows): FEATURE. Slow moving cloud shadows (BB_CLOUD_SHADOWS): the knobs,
// the direction rule, the drift and the push words of host_shaders/cloud_shadow.comp. Pure: no
// Vulkan, no settings, no environment (vk_cloud_shadow.cpp reads the variables once and passes
// their text to MakeKnobs). Tested by tests/test_cloud_shadows.cpp.
//
// The mask (cloud_shadow.comp's cloud_light): a world point p goes along the light to a plane,
// q = p.xz - p.y * Slope(L) (Plane), and n = 0.5 + the sum of Weight[k] (N_k - 0.5) of the three
// value noises of r94's fog noise lattice (volumetric_fog_noise.h, host_shaders/fog_noise.glsl),
// read at (q.x, 0, q.y) / size minus each octave's offset (Drift::Cells). The light kept there is
// Light(n) = 1 - depth * smoothstep(low, high, n): 1 (no cloud) below low, 1 - depth (a full
// cloud) above high. depth = strength * FullDepth. Over the world n has a mean of 0.50 and a
// spread (sd) of 0.13 (CPU probe of 60000 points, scratch r105_noise_sim.py); with the default
// edges 44% of the ground is clear, 15% under a full cloud, 41% in between, and the mean light
// kept at strength 1 is 0.85 of the sun term (with BB_CLOUD_SHADOWS_SHOW: 28% clear, 39% full,
// mean 0.52).
//
// The drift: Drift (r94's, shared) is advanced with a "wind" of Speed m/s toward the clouds'
// direction across xz and, in its third axis, a morph rate that moves the largest octave one
// lattice cell every MorphSeconds (the finer ones 1.3 and 1.7 times as fast, divided by their
// ratio, as Drift moves them), so the shapes change slowly while they pass.
// The direction (deg, 0 = +x, 90 = +z, the way the clouds move, as the wind's): BB_CLOUDS_DIR
// when it is a number; else, with BB_WIND=1, the wind's own direction at that frame (its wander
// included); else "auto": across the light, atan2(L.z, L.x) + 90 deg (the clouds cross the moon
// or sun sideways in the view toward it), eased toward that with an 8 s time constant along the
// shorter arc. Which side "+90" is on screen is not checked (the handedness of the game's world).

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>

#include "volumetric_fog_noise.h"

namespace CloudShadows {

inline constexpr float MaxStrength = 1.0f;     ///< BB_CLOUD_SHADOWS's clamp
inline constexpr float FullDepth = 0.45f;      ///< share of the sun term a full cloud takes at strength 1
inline constexpr float ShowDepth = 0.85f;      ///< BB_CLOUD_SHADOWS_SHOW=1: that share
inline constexpr float DefaultScale = 160.0f;  ///< m: BB_CLOUD_SHADOWS_SCALE, the largest cells
inline constexpr float ShowScale = 70.0f;      ///< m: the size with BB_CLOUD_SHADOWS_SHOW=1
inline constexpr float MinScale = 40.0f, MaxScale = 600.0f; ///< BB_CLOUD_SHADOWS_SCALE's clamp
inline constexpr float Low = 0.48f, High = 0.64f;         ///< n's edges (clear below, full above)
inline constexpr float ShowLow = 0.42f, ShowHigh = 0.54f; ///< with BB_CLOUD_SHADOWS_SHOW=1
inline constexpr float Speed = 6.0f;           ///< m/s: how fast the largest patches travel
inline constexpr float ShowSpeed = 15.0f;      ///< m/s with BB_CLOUD_SHADOWS_SHOW=1
inline constexpr double MorphSeconds = 120.0;  ///< s per lattice cell of the largest octave's morph
inline constexpr float MinLightY = 0.1f;       ///< Slope's floor of L.y (a light 6 deg up or lower)
inline constexpr double EaseSeconds = 8.0;     ///< s: the auto direction's time constant
inline constexpr float AutoTurn = 90.0f;       ///< deg: auto is the light's azimuth plus this
inline constexpr float StartDirection = 225.0f; ///< deg: auto before any light (the wind's default)
inline constexpr double MaxStep = 0.1;         ///< s: the longest step one Advance takes
inline constexpr std::uint32_t PeriodFrames = 600; ///< the periodic log line (2 s with SHOW)
inline constexpr double ShowPeriod = 2.0;      ///< s

/// The value of `text` when it starts with a finite number, else `fallback` (r94's Number).
inline float Number(const char* text, float fallback) {
    return VolumetricFogNoise::Number(text, fallback);
}

/// v wrapped into [0, 360); a value that is not finite gives 0.
inline float Wrap360(float v) {
    if (!std::isfinite(v)) {
        return 0.0f;
    }
    float r = std::fmod(v, 360.0f);
    if (r < 0.0f) {
        r += 360.0f;
    }
    return r >= 360.0f ? 0.0f : r;
}

/// BB_CLOUD_SHADOWS: 0 (off) when missing, empty, not a number or not finite; else clamped to
/// 0-MaxStrength.
inline float ParseStrength(const char* text) {
    return std::clamp(Number(text, 0.0f), 0.0f, MaxStrength);
}

/// BB_CLOUD_SHADOWS_SCALE (m): `fallback` when missing or not a number; else clamped to
/// MinScale-MaxScale.
inline float ParseScale(const char* text, float fallback) {
    return std::clamp(Number(text, fallback), MinScale, MaxScale);
}

/// BB_CLOUDS_DIR: true and the degrees wrapped into [0, 360) when it starts with a finite number;
/// false ("auto") when missing, empty, "auto" or other text.
inline bool ParseDirection(const char* text, float* deg) {
    const float nan = std::numeric_limits<float>::quiet_NaN();
    const float v = Number(text, nan);
    if (!std::isfinite(v)) {
        return false;
    }
    *deg = Wrap360(v);
    return true;
}

struct Knobs {
    float strength = 0.0f; ///< 0: off
    float scale = DefaultScale;
    bool show = false;
    bool dir_set = false;  ///< BB_CLOUDS_DIR named a direction
    float dir_deg = 0.0f;
    bool On() const {
        return strength > 0.0f;
    }
    float Depth() const {
        return strength * (show ? ShowDepth : FullDepth);
    }
    float LowEdge() const {
        return show ? ShowLow : Low;
    }
    float HighEdge() const {
        return show ? ShowHigh : High;
    }
    float Velocity() const {
        return show ? ShowSpeed : Speed;
    }
};

/// The knobs from the variables' text (null: not set). BB_CLOUD_SHADOWS_SHOW starting with 1 turns
/// the shadows on at MaxStrength with the show look (ShowDepth, the show edges, ShowSpeed and,
/// unless BB_CLOUD_SHADOWS_SCALE says otherwise, ShowScale), whatever BB_CLOUD_SHADOWS says.
inline Knobs MakeKnobs(const char* strength, const char* scale, const char* show, const char* dir) {
    Knobs knobs;
    knobs.show = show != nullptr && show[0] == '1';
    knobs.strength = knobs.show ? MaxStrength : ParseStrength(strength);
    knobs.scale = ParseScale(scale, knobs.show ? ShowScale : DefaultScale);
    knobs.dir_set = ParseDirection(dir, &knobs.dir_deg);
    return knobs;
}

/// The light kept at noise value n: 1 - depth * smoothstep(low, high, n) (cloud_light's last line).
inline float Light(float n, float depth, float low, float high) {
    const float t = std::clamp((n - low) / (high - low), 0.0f, 1.0f);
    return 1.0f - depth * (t * t * (3.0f - 2.0f * t));
}

/// L.xz / max(L.y, MinLightY): how far a point's plane coordinate moves per metre of height.
inline std::array<float, 2> Slope(const std::array<float, 3>& light) {
    const float y = std::max(light[1], MinLightY);
    return {light[0] / y, light[2] / y};
}

/// The plane coordinate of world point p (cloud_light's first line): p.xz - p.y * slope.
inline std::array<float, 2> Plane(const std::array<float, 3>& p, const std::array<float, 2>& slope) {
    return {p[0] - p[1] * slope[0], p[2] - p[1] * slope[1]};
}

/// "auto": atan2(L.z, L.x) + AutoTurn, wrapped; false when L has no horizontal part to speak of
/// (the light within about half a degree of straight up) or is not finite.
inline bool AutoDeg(const std::array<float, 3>& light, float* deg) {
    const double x = light[0], z = light[2];
    if (!std::isfinite(x) || !std::isfinite(z) || x * x + z * z < 1e-4) {
        return false;
    }
    *deg = Wrap360(float(std::atan2(z, x) * 57.29577951308232) + AutoTurn);
    return true;
}

/// The angle from `from` to `to` along the shorter arc, in (-180, 180].
inline float ArcDeg(float from, float to) {
    float d = Wrap360(to - from);
    return d > 180.0f ? d - 360.0f : d;
}

/// `current` eased toward `target` over dt seconds with time constant tau, along the shorter arc.
inline float EaseDeg(float current, float target, double dt, double tau) {
    const double k = dt > 0.0 && tau > 0.0 ? 1.0 - std::exp(-dt / tau) : 0.0;
    return Wrap360(current + float(k) * ArcDeg(current, target));
}

/// What drives the drift this frame: Drift's "wind" (m/s): speed toward deg across xz and the
/// morph in the third axis (scale / (MorphSeconds Squash), which Drift turns into
/// 1 / MorphSeconds cells a second for the largest octave).
inline std::array<float, 3> DriftVelocity(float deg, float speed, float scale) {
    const double rad = double(deg) * (3.14159265358979323846 / 180.0);
    return {float(speed * std::cos(rad)),
            float(double(scale) / (MorphSeconds * double(VolumetricFogNoise::Squash))),
            float(speed * std::sin(rad))};
}

enum class Source : std::uint32_t { Env, Wind, Auto };

inline const char* SourceName(Source s) {
    return s == Source::Env ? "BB_CLOUDS_DIR" : s == Source::Wind ? "the wind" : "auto";
}

/// The clouds' state: the direction, its source, the drift's offsets and the clamped real time.
class State {
public:
    /// One step of `seconds` (not finite: 0; clamped to 0-MaxStep). The direction: BB_CLOUDS_DIR,
    /// else the wind's (wind_on), else auto from `light` (light_valid), eased (the first light
    /// sets it at once); without a light auto keeps its last value. Then the drift moves.
    void Advance(const Knobs& knobs, bool wind_on, float wind_deg, bool light_valid,
                 const std::array<float, 3>& light, double seconds) {
        const double dt = std::isfinite(seconds) ? std::clamp(seconds, 0.0, MaxStep) : 0.0;
        time += dt;
        float target = 0.0f;
        if (knobs.dir_set) {
            source = Source::Env;
            direction = knobs.dir_deg;
        } else if (wind_on) {
            source = Source::Wind;
            direction = Wrap360(wind_deg);
        } else {
            source = Source::Auto;
            if (light_valid && AutoDeg(light, &target)) {
                direction = auto_known ? EaseDeg(direction, target, dt, EaseSeconds) : target;
                auto_known = true;
            }
        }
        drift.Advance(true, time, DriftVelocity(direction, knobs.Velocity(), knobs.scale),
                      knobs.scale);
    }

    float Direction() const {
        return direction;
    }
    Source From() const {
        return source;
    }
    double Time() const {
        return time;
    }
    const VolumetricFogNoise::Drift& Offsets() const {
        return drift;
    }

private:
    VolumetricFogNoise::Drift drift;
    double time = 0.0;
    float direction = StartDirection;
    Source source = Source::Auto;
    bool auto_known = false;
};

/// cloud_shadow.comp's push constants (its Params block, in order).
struct Push {
    std::array<float, 12> view_to_world{}; ///< 3x4 rows, translation in [3], [7], [11]
    std::array<float, 4> off0{};           ///< octave 0's offset; w: depth
    std::array<float, 4> off1{};           ///< octave 1's offset; w: 1 / scale
    std::array<float, 4> off2{};           ///< octave 2's offset; w: the low edge
    std::array<float, 2> slope{};
    float high = 0.0f;
    std::uint32_t offsets = 0; ///< the shadow constants' byte offset (bits 0-7), the uniforms' (8-15)
    float reach = 0.0f;        ///< the gate build: the march's reach (m)
    std::uint32_t unused = 0;
};
static_assert(sizeof(Push) == 120 && sizeof(Push) <= 128, "Vulkan guarantees 128 push bytes");

inline Push MakePush(const std::array<float, 12>& rows, const State& state, const Knobs& knobs,
                     const std::array<float, 3>& light, std::uint32_t offsets, float reach) {
    Push push;
    push.view_to_world = rows;
    const auto& drift = state.Offsets();
    const std::array<float, 3> c0 = drift.Cells(0), c1 = drift.Cells(1), c2 = drift.Cells(2);
    push.off0 = {c0[0], c0[1], c0[2], knobs.Depth()};
    push.off1 = {c1[0], c1[1], c1[2], 1.0f / knobs.scale};
    push.off2 = {c2[0], c2[1], c2[2], knobs.LowEdge()};
    push.slope = Slope(light);
    push.high = knobs.HighEdge();
    push.offsets = offsets;
    push.reach = reach;
    return push;
}

} // namespace CloudShadows
''',
    R + "vk_cloud_shadow.h": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
    /// Each frame end: the direction and drift move (the wind's direction with BB_WIND=1), the
    /// periodic line.
    void OnFrameEnd(bool wind_on, float wind_deg);
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
''',
    R + "vk_cloud_shadow.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
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
                      std::getenv("BB_CLOUD_SHADOWS_SHOW"), std::getenv("BB_CLOUDS_DIR"));
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
    BbReport::Printf("Cloud shadows (r105, BB_CLOUD_SHADOWS=%.2f%s): a full cloud keeps %.0f%% of "
                     "the sun or moon light, clear below n %.2f, full above %.2f, size %.0f m, "
                     "%.1f m/s toward %s; acts on the ray traced sun's (or VSM's) shadow "
                     "target and the sun "
                     "fog's ray traced gate only\n",
                     double(knobs.strength), knobs.show ? ", SHOW" : "",
                     100.0 * (1.0 - double(knobs.Depth())), double(knobs.LowEdge()),
                     double(knobs.HighEdge()), double(knobs.scale), double(knobs.Velocity()),
                     knobs.dir_set ? "BB_CLOUDS_DIR" : "the wind (BB_WIND=1) or auto");
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

void CloudShadow::OnFrameEnd(bool wind_on, float wind_deg) {
    const double now = Seconds();
    const double seconds = clock_last < 0.0 ? 0.0 : now - clock_last;
    clock_last = now;
    state.Advance(knobs, wind_on, wind_deg, light_valid, light, seconds);
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
''',
    H + "cloud_shadow.comp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r105_cloud-shadows): FEATURE, BB_CLOUD_SHADOWS above 0 only. Slow moving cloud shadows:
// a large, soft, world anchored mask that dims the sun or moon term, made by
// renderer_vulkan/vk_cloud_shadow.cpp (the knobs and rules are cloud_shadow_params.h's).
//  - the default build: on the screen shadow target, right after the ray traced sun (or the VSM)
//    wrote its alpha, the sun visibility the game's directional light reads (RtShadow::Record in
//    ContactShadow::Flush). alpha *= the cloud's light share where 0 < depth < 1 and alpha > 0:
//    sky, shadow and interiors the ray traced sun shuts (alpha 0) are not written at all.
//  - GATE: on the sun fog's ray traced gate (volumetric_rt_gate.comp's cells, R8, 1 where the
//    sun reaches the cell), right after it is traced (VolumetricLight::Integrate): every GATE build
//    of the march multiplies its sun answer by the gate, so its lit samples dim under the clouds.
// The cloud mask: the world point p is carried along the light to a plane, q = p.xz - p.y *
// slope, slope = L.xz / max(L.y, 0.1) (L toward the light, world space, +y up), so walls take the
// pattern stretched along the light as real cloud shadows do. n = 0.5 + the sum of WEIGHTk (Nk -
// 0.5) of three value noises Nk (fog_noise.glsl's fog_noise_value, shared with r94's fog noise,
// on its lattice: cells of the size, 0.43 and 0.19 of it, each turned about the up axis by
// fog_noise_cells), read at (q.x, 0, q.y) / size minus each octave's offset (the drift along xz,
// a slow morph along the third axis). The light kept is 1 - depth * smoothstep(low, high, n).
#version 450
#extension GL_EXT_scalar_block_layout : require
#extension GL_GOOGLE_include_directive : require

#ifdef GATE
layout(local_size_x = 4, local_size_y = 4, local_size_z = 4) in;
#else
layout(local_size_x = 8, local_size_y = 8) in;
#endif

layout(scalar, binding = 0) readonly buffer ShadowConstants { uint d[]; } cb;
#ifdef GATE
layout(scalar, binding = 1) readonly buffer SceneConstants { uint d[]; } ub;
layout(binding = 2, r8) uniform image3D gate_img;
#else
layout(binding = 1) uniform sampler2D depth_tex;
layout(binding = 2, rgba8) uniform image2D shadow_img;
#endif

// CloudShadows::Push (cloud_shadow_params.h, 120 bytes)
layout(push_constant) uniform Params {
    vec4 cloud_row0, cloud_row1, cloud_row2; // view to world, 3x4 rows (the frame's camera)
    vec4 cloud_off0; // octave 0's offset in its lattice cells; w: depth (strength x the full depth)
    vec4 cloud_off1; // octave 1's offset; w: 1 / size (1/m)
    vec4 cloud_off2; // octave 2's offset; w: low (n below it: no cloud)
    vec2 cloud_slope; // L.xz / max(L.y, 0.1)
    float cloud_high; // n above it: a full cloud
    uint offsets;     // the shadow constants' byte offset (bits 0-7), the uniforms' (8-15)
    float reach;      // GATE: the march's reach (m), as GateRange
    uint unused;
};

// fog_noise.glsl's value noise and lattice turn only (its fog_noise_m reads r94's push words)
#define FOG_NOISE_VALUE_ONLY
#include "fog_noise.glsl"

shared mat4 shared_inverse_projection;
#ifdef GATE
shared float shared_range;
#endif

float c(uint base, int i) { return uintBitsToFloat(cb.d[base + uint(i)]); }
vec4 row(uint base, int i) { return vec4(c(base, i), c(base, i + 1), c(base, i + 2), c(base, i + 3)); }

// The share of the sun or moon light a cloud lets through at world point p: 1 - depth *
// smoothstep(low, high, n); 1 for a point that is not finite.
float cloud_light(vec3 p) {
    vec2 q = p.xz - p.y * cloud_slope;
    vec3 x = vec3(q.x, 0.0, q.y) * cloud_off1.w;
    if (any(isnan(x)) || any(isinf(x))) return 1.0;
    float n = 0.5;
    n += float(FOG_NOISE_WEIGHT0) *
         (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS0), float(FOG_NOISE_YAW_SIN0),
                                          float(FOG_NOISE_RATIO0)) - cloud_off0.xyz) - 0.5);
    n += float(FOG_NOISE_WEIGHT1) *
         (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS1), float(FOG_NOISE_YAW_SIN1),
                                          float(FOG_NOISE_RATIO1)) - cloud_off1.xyz) - 0.5);
    n += float(FOG_NOISE_WEIGHT2) *
         (fog_noise_value(fog_noise_cells(x, float(FOG_NOISE_YAW_COS2), float(FOG_NOISE_YAW_SIN2),
                                          float(FOG_NOISE_RATIO2)) - cloud_off2.xyz) - 0.5);
    return 1.0 - cloud_off0.w * smoothstep(cloud_off2.w, cloud_high, n);
}

vec3 to_world(vec3 v) {
    vec4 h = vec4(v, 1.0);
    return vec3(dot(cloud_row0, h), dot(cloud_row1, h), dot(cloud_row2, h));
}

void main() {
    if (gl_LocalInvocationIndex == 0u) {
        uint base = (offsets & 255u) >> 2;
        shared_inverse_projection = transpose(mat4(row(base, 0), row(base, 4), row(base, 8),
                                                   row(base, 12)));
#ifdef GATE
        // as volumetric_rt_gate.comp's prepare(): the shadow distance when shorter than the reach
        uint ubase = ((offsets >> 8) & 255u) >> 2;
        float d = uintBitsToFloat(ub.d[ubase + 72u]);
        shared_range = d > 0.0 && d < reach ? d : reach;
#endif
    }
    barrier();
#ifdef GATE
    // A cell's centre as volumetric_rt_gate.comp places it: the view ray through the column's
    // centre, at the slice's distance range * s^2, s = (slice + 0.5) / slices.
    ivec3 cell = ivec3(gl_GlobalInvocationID);
    ivec3 size = imageSize(gate_img);
    if (any(greaterThanEqual(cell, size))) return;
    float open = imageLoad(gate_img, cell).r;
    if (!(open > 0.0)) return;
    vec2 uv = (vec2(cell.xy) + 0.5) / vec2(size.xy);
    vec4 h = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.5, 1.0);
    if (abs(h.w) < 1e-8) return;
    vec3 ray = h.xyz / h.w;
    float len = length(ray);
    if (!(ray.z > 0.0 && len > 0.0)) return;
    float s = (float(cell.z) + 0.5) / float(size.z);
    float k = cloud_light(to_world(ray / len * (shared_range * s * s)));
    if (!(k < 1.0)) return;
    imageStore(gate_img, cell, vec4(open * k));
#else
    ivec2 px = ivec2(gl_GlobalInvocationID.xy);
    ivec2 size = imageSize(shadow_img);
    if (any(greaterThanEqual(px, size))) return;
    vec2 uv = (vec2(px) + 0.5) / vec2(size);
    float depth = textureLod(depth_tex, uv, 0.0).r;
    if (!(depth > 0.0 && depth < 1.0)) return;
    vec4 target = imageLoad(shadow_img, px);
    if (!(target.a > 0.0)) return;
    vec4 h = shared_inverse_projection * vec4(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, depth, 1.0);
    if (abs(h.w) < 1e-8) return;
    float k = cloud_light(to_world(h.xyz / h.w));
    if (!(k < 1.0)) return;
    // A fixed per-pixel dither of under half an 8-bit step (interleaved gradient noise), so a
    // slow cloud edge does not show the alpha's 1/255 steps as bands.
    float dither = 0.98 * (fract(52.9829189 * fract(dot(vec2(px), vec2(0.06711056, 0.00583715)))) -
                           0.5) / 255.0;
    target.a = clamp(target.a * k + dither, 0.0, 1.0);
    imageStore(shadow_img, px, target);
#endif
}
''',
    "engine/tests/test_cloud_shadows.cpp": r'''// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r105_cloud-shadows): checks of gpu/shadps4/video_core/renderer_vulkan/cloud_shadow_params.h,
// the cloud shadows' knobs, direction rule, drift and push words (built and run by engine/build.sh
// --test and the CMake target cloud-shadows-test).
//  a. BB_CLOUD_SHADOWS: missing, empty, not a number or below 0: 0 (off); clamped to 1.
//  b. BB_CLOUD_SHADOWS_SCALE: missing or not a number: 160 m (70 m with SHOW); clamped to 40-600.
//  c. BB_CLOUD_SHADOWS_SHOW=1 turns them on at strength 1 with the show look.
//  d. BB_CLOUDS_DIR: a number (wrapped into [0, 360)) or auto (missing, empty, "auto", text).
//  e. The light kept: 1 below the low edge, 1 - depth above the high edge, never rising with n.
//  f. Slope and Plane: the light's height floor, a point carried along the light.
//  g. Auto: across the light (its azimuth + 90 deg); none for a light straight up.
//  h. Easing goes the shorter way round and reaches the target.
//  i. The direction's source: BB_CLOUDS_DIR, then the wind, then auto; auto snaps to the first light,
//     then eases, and keeps its value without a light.
//  j. The drift: the largest octave's offset is the lattice point of the clouds' travel (speed x
//     time toward the direction) and of the morph (time / MorphSeconds) in its third axis.
//  k. The push words: the Params block's order and the knobs in their slots.
#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdio>
#include <initializer_list>

#include "gpu/shadps4/video_core/renderer_vulkan/cloud_shadow_params.h"

using namespace CloudShadows;

namespace {

bool Near(double a, double b, double eps) {
    return std::fabs(a - b) <= eps;
}

// The difference a - b of two lattice coordinates, wrapped into [-Period / 2, Period / 2).
double CellGap(double a, double b) {
    const double p = VolumetricFogNoise::Period;
    return VolumetricFogNoise::WrapCells(a - b + p / 2.0) - p / 2.0;
}

double DegGap(double a, double b) {
    return std::fabs(double(ArcDeg(float(b), float(a))));
}

} // namespace

int main() {
    // a.
    for (const char* off : {static_cast<const char*>(nullptr), "", "0", "-1", "abc", "nan", "inf"}) {
        assert(!MakeKnobs(off, nullptr, nullptr, nullptr).On());
    }
    assert(Near(MakeKnobs("0.5", nullptr, nullptr, nullptr).strength, 0.5, 1e-6));
    assert(Near(MakeKnobs("1", nullptr, nullptr, nullptr).strength, 1.0, 1e-6));
    assert(Near(MakeKnobs("3", nullptr, nullptr, nullptr).strength, MaxStrength, 1e-6));
    const Knobs plain = MakeKnobs("1", nullptr, nullptr, nullptr);
    assert(!plain.show && Near(plain.Depth(), FullDepth, 1e-6));
    assert(plain.LowEdge() == Low && plain.HighEdge() == High && plain.Velocity() == Speed);
    // b.
    assert(plain.scale == DefaultScale);
    assert(MakeKnobs("1", "10", nullptr, nullptr).scale == MinScale);
    assert(MakeKnobs("1", "5000", nullptr, nullptr).scale == MaxScale);
    assert(MakeKnobs("1", "250", nullptr, nullptr).scale == 250.0f);
    assert(MakeKnobs("1", "wide", nullptr, nullptr).scale == DefaultScale);
    // c.
    const Knobs show = MakeKnobs(nullptr, nullptr, "1", nullptr);
    assert(show.On() && show.show && show.strength == MaxStrength && show.scale == ShowScale);
    assert(Near(show.Depth(), ShowDepth, 1e-6) && show.LowEdge() == ShowLow &&
           show.HighEdge() == ShowHigh && show.Velocity() == ShowSpeed);
    assert(MakeKnobs("0", "100", "1", nullptr).scale == 100.0f);
    assert(!MakeKnobs("0", nullptr, "0", nullptr).On());
    assert(Low < High && ShowLow < ShowHigh && FullDepth < 1.0f && ShowDepth < 1.0f);
    // d.
    for (const char* autos : {static_cast<const char*>(nullptr), "", "auto", "left"}) {
        assert(!MakeKnobs("1", nullptr, nullptr, autos).dir_set);
    }
    assert(MakeKnobs("1", nullptr, nullptr, "90").dir_set &&
           MakeKnobs("1", nullptr, nullptr, "90").dir_deg == 90.0f);
    assert(Near(MakeKnobs("1", nullptr, nullptr, "-90").dir_deg, 270.0, 1e-4));
    assert(Near(MakeKnobs("1", nullptr, nullptr, "720.5").dir_deg, 0.5, 1e-3));
    // e.
    assert(Light(0.0f, 0.6f, Low, High) == 1.0f && Light(Low, 0.6f, Low, High) == 1.0f);
    assert(Near(Light(High, 0.6f, Low, High), 0.4, 1e-6) && Near(Light(1.0f, 0.6f, Low, High), 0.4, 1e-6));
    float last = 1.0f;
    for (int i = 0; i <= 100; ++i) {
        const float l = Light(float(i) / 100.0f, 0.6f, Low, High);
        assert(l <= last + 1e-7f && l >= 0.4f - 1e-6f);
        last = l;
    }
    assert(Light(0.9f, 0.0f, Low, High) == 1.0f);
    // f.
    const auto low_sun = Slope({0.0f, 0.05f, 1.0f});
    assert(Near(low_sun[0], 0.0, 1e-6) && Near(low_sun[1], 1.0 / MinLightY, 1e-4));
    const auto slope = Slope({0.6f, 0.8f, 0.0f});
    assert(Near(slope[0], 0.75, 1e-6) && slope[1] == 0.0f);
    // a point 4 m up the light's ray from p lands where p does
    const std::array<float, 3> p{10.0f, 2.0f, -3.0f}, up{10.0f + 0.6f * 4.0f, 2.0f + 0.8f * 4.0f, -3.0f};
    assert(Near(Plane(p, slope)[0], Plane(up, slope)[0], 1e-4) && Plane(p, slope)[1] == -3.0f);
    // g.
    float deg = -1.0f;
    assert(AutoDeg({1.0f, 0.5f, 0.0f}, &deg) && Near(deg, 90.0, 1e-4));
    assert(AutoDeg({0.0f, 0.3f, 1.0f}, &deg) && Near(deg, 180.0, 1e-4));
    // a light logged in a slot run (world -0.803, 0.375, 0.464): azimuth 149.98 deg, auto 239.98
    assert(AutoDeg({-0.803f, 0.375f, 0.464f}, &deg) && Near(deg, 239.98, 0.01));
    assert(AutoDeg({-1.0f, 0.0f, 0.0f}, &deg) && Near(deg, 270.0, 1e-4));
    assert(!AutoDeg({0.0f, 1.0f, 0.0f}, &deg) && !AutoDeg({NAN, 0.5f, 0.5f}, &deg));
    // h.
    float e = 350.0f;
    for (int i = 0; i < 4; ++i) {
        e = EaseDeg(e, 10.0f, 1.0, EaseSeconds);
        assert(e > 350.0f || e < 10.0f);
    }
    e = EaseDeg(e, 10.0f, 1000.0, EaseSeconds);
    assert(DegGap(e, 10.0) < 1e-3);
    assert(EaseDeg(40.0f, 100.0f, 0.0, EaseSeconds) == 40.0f);
    assert(Near(EaseDeg(0.0f, 100.0f, EaseSeconds, EaseSeconds), 100.0 * (1.0 - std::exp(-1.0)), 1e-3));
    // i.
    {
        const Knobs env = MakeKnobs("1", nullptr, nullptr, "30");
        State s;
        s.Advance(env, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);
        assert(s.From() == Source::Env && s.Direction() == 30.0f);
        State w;
        w.Advance(plain, true, 200.0f, true, {1.0f, 0.5f, 0.0f}, 0.05);
        assert(w.From() == Source::Wind && w.Direction() == 200.0f);
        State a;
        a.Advance(plain, false, 200.0f, false, {}, 0.05);
        assert(a.From() == Source::Auto && a.Direction() == StartDirection);
        a.Advance(plain, false, 0.0f, true, {1.0f, 0.5f, 0.0f}, 0.05); // first light: at once
        assert(Near(a.Direction(), 90.0, 1e-4));
        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 0.1); // eased toward 180
        assert(a.Direction() > 90.0f && a.Direction() < 95.0f);
        const float held = a.Direction();
        a.Advance(plain, false, 0.0f, false, {}, 0.1); // no light: kept
        assert(a.Direction() == held);
        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, NAN); // no time: kept
        assert(a.Direction() == held && Near(a.Time(), 0.3, 1e-9));
        a.Advance(plain, false, 0.0f, true, {0.0f, 0.5f, 1.0f}, 50.0); // clamped to MaxStep
        assert(Near(a.Time(), 0.3 + MaxStep, 1e-9));
    }
    // j.
    {
        const Knobs k = MakeKnobs("1", "200", nullptr, "60");
        State s;
        const int steps = 2000; // 100 s after the first step (which only takes the time)
        for (int i = 0; i <= steps; ++i) {
            s.Advance(k, false, 0.0f, true, {0.0f, 1.0f, 0.0f}, 0.05);
        }
        const double t = steps * 0.05;
        const auto v = DriftVelocity(60.0f, Speed, 200.0f);
        assert(Near(std::hypot(v[0], v[2]), Speed, 1e-4) && Near(std::atan2(v[2], v[0]) * 57.29577951308232, 60.0, 1e-3));
        const std::array<float, 3> travel{float(v[0] * t), float(v[1] * t), float(v[2] * t)};
        const auto want = VolumetricFogNoise::LatticePoint(travel, 0, 200.0f);
        const auto got = s.Offsets().Cells(0);
        for (int i = 0; i < 3; ++i) {
            assert(Near(CellGap(got[i], want[i]), 0.0, 1e-3));
        }
        assert(Near(got[1], t / MorphSeconds, 1e-4));
        for (std::size_t o = 0; o < 3; ++o) {
            for (const float c : s.Offsets().Cells(o)) {
                assert(c >= 0.0f && c < 256.0f);
            }
        }
    }
    // k.
    {
        static_assert(offsetof(Push, off0) == 48 && offsetof(Push, off1) == 64 &&
                      offsetof(Push, off2) == 80 && offsetof(Push, slope) == 96 &&
                      offsetof(Push, high) == 104 && offsetof(Push, offsets) == 108 &&
                      offsetof(Push, reach) == 112 && sizeof(Push) == 120);
        const Knobs k = MakeKnobs("0.5", "100", nullptr, nullptr);
        State s;
        const std::array<float, 12> rows{1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7};
        const Push push = MakePush(rows, s, k, {0.6f, 0.8f, 0.0f}, 0x1234u, 40.0f);
        assert(push.view_to_world == rows && Near(push.off0[3], 0.5 * FullDepth, 1e-6));
        assert(Near(push.off1[3], 0.01, 1e-7) && push.off2[3] == Low && push.high == High);
        assert(Near(push.slope[0], 0.75, 1e-6) && push.offsets == 0x1234u && push.reach == 40.0f);
    }
    std::puts("cloud shadows: ok");
    return 0;
}
''',
}

EDITS = {
    R + "vk_rasterizer.h": [
        ('#include "video_core/renderer_vulkan/vk_contact_shadow.h"\n',
         '#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)\n',
         "after"),
        ("    std::unique_ptr<ContactShadow> contact_shadow;\n",
         "    /// bbport (r105_cloud-shadows): made only with BB_CLOUD_SHADOWS above 0 or\n"
         "    /// BB_CLOUD_SHADOWS_SHOW=1 (CloudShadow::Wanted), else null.\n"
         "    std::unique_ptr<CloudShadow> cloud_shadow;\n",
         "after"),
    ],
    R + "vk_rasterizer.cpp": [
        ("    contact_shadow = std::make_unique<ContactShadow>(instance, scheduler, texture_cache, runtime,\n"
         "                                                     *scene_targets, *camera_motion, *rt_shadow);\n",
         "    // bbport (r105_cloud-shadows): BB_CLOUD_SHADOWS above 0 or BB_CLOUD_SHADOWS_SHOW=1 only\n"
         "    // (CloudShadow::Wanted, read once); otherwise none is made and its hooks are null tests.\n"
         "    if (CloudShadow::Wanted()) {\n"
         "        cloud_shadow = std::make_unique<CloudShadow>(instance, scheduler);\n"
         "    }\n",
         "after"),
    ],
    R + "vk_rasterizer_effects.cpp": [
        ("    effects_wanted = AnyWanted();\n",
         "    // bbport (r105_cloud-shadows): the clouds' direction and drift (null when off), after the\n"
         "    // wind's step so that BB_WIND=1 gives this frame's direction\n"
         "    if (cloud_shadow) {\n"
         "        const BbWind::Snapshot w = wind.Get();\n"
         "        cloud_shadow->OnFrameEnd(w.on, w.direction_deg);\n"
         "    }\n",
         "before"),
        ("            volumetric_light->SetSunLight(light);\n",
         "            // bbport (r105_cloud-shadows): the light and the camera (null when off)\n"
         "            if (cloud_shadow) {\n"
         "                cloud_shadow->SetSunLight(light.world, light.view_to_world, light.valid);\n"
         "            }\n",
         "after"),
    ],
    R + "vk_contact_shadow.cpp": [
        ('#include "video_core/renderer_vulkan/vk_camera_motion.h"\n',
         '#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)\n',
         "after"),
        ("        return;\n"
         "    }\n"
         '    EffectPass::Mark(4, "contact shadows and PCSS");\n',
         "        // bbport (r105_cloud-shadows): the clouds into the alpha the ray traced sun (or the\n"
         "        // VSM) just wrote, before the game's directional light reads it (null when off)\n"
         "        if (auto* clouds = CloudShadow::Active(); clouds && sun_replaced) {\n"
         "            clouds->Ground(in, depth_view, target_view, width, height);\n"
         "        }\n",
         "before"),
    ],
    R + "vk_volumetric_light.cpp": [
        ('#include "video_core/renderer_vulkan/vk_effect_pass.h"\n',
         '#include "video_core/renderer_vulkan/vk_cloud_shadow.h" // bbport (r105_cloud-shadows)\n',
         "after"),
        ("        RecordGate(in, in.constants_offset_word, probing, viewing, di);\n",
         "        // bbport (r105_cloud-shadows): the clouds into the gate's cells (null when off)\n"
         "        if (auto* clouds = CloudShadow::Active()) {\n"
         "            clouds->Gate(in, *gate_view, GateWidth, GateHeight, GateSlices, reach);\n"
         "        }\n",
         "after"),
    ],
    H + "fog_noise.glsl": [
        ("// m, the fog density factor at view space point v, t metres from the camera along the march's\n",
         "// bbport (r105_cloud-shadows): cloud_shadow.comp defines FOG_NOISE_VALUE_ONLY to take the value\n"
         "// noise and the lattice turn above without the two functions below, which read r94's push\n"
         "// words; the NOISE builds of volumetric_light.comp never define it.\n"
         "#ifndef FOG_NOISE_VALUE_ONLY\n",
         "before"),
        ("    return fog_noise_m(p, t);\n"
         "}\n",
         "#endif // FOG_NOISE_VALUE_ONLY (bbport r105_cloud-shadows)\n",
         "after"),
    ],
    "engine/gpu/CMakeLists.txt": [
        ('    # bbport (r94_fog-noise): the NOISE builds include the fog noise and its numbers\n'
         '    if (FILENAME MATCHES "^volumetric_light")\n'
         '        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h)\n'
         '    endif()\n',
         '    # bbport (r105_cloud-shadows): the cloud shadows take the fog noise and its numbers\n'
         '    if (FILENAME MATCHES "^cloud_shadow")\n'
         '        list(APPEND INCLUDES ${SHADER_SRC}/fog_noise.glsl ${SHADER_SRC}/fog_noise_layout.h)\n'
         '    endif()\n',
         "after"),
        ("add_host_shader(sky_seam.comp sky_seam_comp)\n",
         "# bbport (r105_cloud-shadows): BB_CLOUD_SHADOWS above 0 only (both made at the first pass): the\n"
         "# ground pass on the sun shadow target and the GATE build on the sun fog's ray traced gate\n"
         "add_host_shader(cloud_shadow.comp cloud_shadow_comp)\n"
         "add_host_shader(cloud_shadow.comp cloud_shadow_gate_comp GATE=1)\n",
         "before"),
        ("# bbport (r51_volumetric-leak): the volumetric march's cascades and knob (volumetric_occlusion.h)\n",
         "# bbport (r105_cloud-shadows): the cloud shadows' knobs, direction rule, drift and push words\n"
         "# (cloud_shadow_params.h); also built and run by engine/build.sh --test.\n"
         "add_executable(cloud-shadows-test EXCLUDE_FROM_ALL ../tests/test_cloud_shadows.cpp)\n"
         "target_compile_options(cloud-shadows-test PRIVATE -UNDEBUG -Wall -Wextra -Werror)\n"
         "target_include_directories(cloud-shadows-test PRIVATE ..)\n",
         "before"),
    ],
    "engine/build.sh": [
        ('    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_volumetric_fog_noise.cpp -o out/volumetric-fog-noise-test\n'
         "    out/volumetric-fog-noise-test\n",
         "    # bbport (r105_cloud-shadows): the cloud shadows' knobs, direction rule, drift and push words\n"
         '    "${CXX:-clang++}" -std=c++20 -O1 -UNDEBUG -Wall -Wextra -Werror -I. tests/test_cloud_shadows.cpp -o out/cloud-shadows-test\n'
         "    out/cloud-shadows-test\n",
         "after"),
    ],
    "engine/tests/test_effect_pipelines.cpp": [
        ('#include "video_core/host_shaders/contact_shadow_comp.h"\n',
         '#include "video_core/host_shaders/cloud_shadow_comp.h"      // bbport (r105_cloud-shadows)\n'
         '#include "video_core/host_shaders/cloud_shadow_gate_comp.h" // bbport (r105_cloud-shadows)\n',
         "after"),
        ('        {"contact shadows",\n'
         "         CONTACT_SHADOW_COMP,\n"
         "         {eStorageBuffer, eCombinedImageSampler, eStorageImage, eCombinedImageSampler,\n"
         "          eStorageBuffer},\n"
         "         68},\n",
         "        // bbport (r105_cloud-shadows): CloudShadow's two passes (CloudShadows::Push, 120 bytes)\n"
         '        {"cloud shadows", CLOUD_SHADOW_COMP, {eStorageBuffer, eCombinedImageSampler, eStorageImage},\n'
         "         120},\n"
         '        {"cloud shadows gate", CLOUD_SHADOW_GATE_COMP, {eStorageBuffer, eStorageBuffer, eStorageImage},\n'
         "         120},\n",
         "after"),
    ],
    "README.md": [None],
}

README_BLOCK = r'''### Cloud shadows (in development)

Slow moving cloud shadows: large, soft, world anchored patches that dim the sun's light (at night the moon's) on the ground and in the sun fog, as clouds passing over would, drifting across the place and slowly changing shape. Only the sun or moon light is dimmed: ambient and sky light, lamps, the torch, the sky itself (no clouds are drawn in it) and the game's own fog stay as they are, and a pixel the ray traced sun already shades fully, such as a room under a roof, is not touched; sunlight through a window is dimmed as outdoors. That holds within the game's sun shadow distance: past it the ray traced sun lights every pixel, and the clouds dim that light like any other. It needs the ray traced sun or the virtual shadow maps (ray tracing on); without them nothing is drawn and the log counts the frames. The sun fog (`effect_volumetric_light`) is dimmed through its ray traced gate, so not with `BB_VOLUMETRIC_RT_GATE=0`. Off unless `BB_CLOUD_SHADOWS` is above 0 or `BB_CLOUD_SHADOWS_SHOW=1`; then the session log says the knobs once in a line starting `Cloud shadows (r105, BB_CLOUD_SHADOWS=` and, every 600 frames (every 2 s with SHOW), counts the ground and sun fog passes and says the direction and where it came from in a line starting `Cloud shadows (r105):`. These environment variables are read once when the game starts; they are for testing and are part of no look; no ini key yet.

| Variable | Effect | Default |
| --- | --- | --- |
| `BB_CLOUD_SHADOWS` | Strength s, 0 (off) to 1; `1` is the intended look; missing, not a number or not finite is off. At a world point the light of the sun or moon is multiplied by 1 - 0.45 s smoothstep(0.48, 0.64, n), n being 0.5 plus the sum of 0.55, 0.30 and 0.15 times (N - 0.5) of three value noises N (the fog noise's, `BB_FOG_NOISE`) with cells of the size (`BB_CLOUD_SHADOWS_SCALE`), 0.43 and 0.19 of it. The point is first carried along the light to the ground plane, so a wall takes the shadow that falls on it, stretched along the light. At strength 1 about 44% of the ground is in the clear, 15% under a full cloud (0.55 of the light kept) and the rest in the soft edges; the mean light kept is 0.85 (from a sample of the noise, not measured in the game). The patches travel at 6 m/s and change shape over about 2 minutes. Cost: an estimate of 0.02 to 0.05 ms at 1080p internal (24 hashed lattice corners per lit pixel and per open sun fog gate cell; on sky, shadow and interiors only a depth and a target read, no noise), not measured; read it on the `Lighting: cloud shadows` row of `BB_GPU_PROFILE=1`. No video memory beyond two pipelines | off |
| `BB_CLOUD_SHADOWS_SCALE` | Size of the largest patches in metres, 40 to 600 | `160` (`70` with SHOW) |
| `BB_CLOUD_SHADOWS_SHOW` | Test only: `1` turns them on at strength 1 with a stronger look, whatever `BB_CLOUD_SHADOWS` says: a full cloud keeps 0.15 of the light, the edges at 0.42 and 0.54 (about 28% clear, 39% full), patches 70 m across travelling at 15 m/s | off |
| `BB_CLOUDS_DIR` | The direction the clouds move, in degrees (0 toward +x, 90 toward +z, as `BB_WIND_DIR`). Missing, `auto` or other text: with `BB_WIND=1` the wind's direction, else across the light (the light's direction across the ground plus 90 degrees, eased over about 8 s as the light turns) | `auto` |

'''
EDITS["README.md"][0] = ("### Halation (in development)\n", README_BLOCK, "before")

# README numbers tied to the header's constants.
TIES = [("MaxStrength = 1.0f", "| `BB_CLOUD_SHADOWS` |", "0 (off) to 1"),
        ("FullDepth = 0.45f", "| `BB_CLOUD_SHADOWS` |", "1 - 0.45 s smoothstep"),
        ("Low = 0.48f, High = 0.64f", "| `BB_CLOUD_SHADOWS` |", "smoothstep(0.48, 0.64, n)"),
        ("FullDepth = 0.45f", "| `BB_CLOUD_SHADOWS` |", "(0.55 of the light kept)"),
        ("Speed = 6.0f", "| `BB_CLOUD_SHADOWS` |", "travel at 6 m/s"),
        ("MorphSeconds = 120.0", "| `BB_CLOUD_SHADOWS` |", "about 2 minutes"),
        ("MinScale = 40.0f, MaxScale = 600.0f", "| `BB_CLOUD_SHADOWS_SCALE` |", "40 to 600"),
        ("DefaultScale = 160.0f", "| `BB_CLOUD_SHADOWS_SCALE` |", "| `160` (`70` with SHOW) |"),
        ("ShowScale = 70.0f", "| `BB_CLOUD_SHADOWS_SCALE` |", "(`70` with SHOW)"),
        ("ShowScale = 70.0f", "| `BB_CLOUD_SHADOWS_SHOW` |", "patches 70 m across"),
        ("ShowDepth = 0.85f", "| `BB_CLOUD_SHADOWS_SHOW` |", "keeps 0.15 of the light"),
        ("ShowLow = 0.42f, ShowHigh = 0.54f", "| `BB_CLOUD_SHADOWS_SHOW` |", "at 0.42 and 0.54"),
        ("ShowSpeed = 15.0f", "| `BB_CLOUD_SHADOWS_SHOW` |", "at 15 m/s"),
        ("EaseSeconds = 8.0", "| `BB_CLOUDS_DIR` |", "about 8 s"),
        ("AutoTurn = 90.0f", "| `BB_CLOUDS_DIR` |", "plus 90 degrees"),
        ("PeriodFrames = 600", "Slow moving cloud shadows:", "every 600 frames"),
        ("ShowPeriod = 2.0", "Slow moving cloud shadows:", "(every 2 s with SHOW)")]

# README numbers that are r94's (host_shaders/fog_noise_layout.h, read from the tree): the octaves'
# weights and cell ratios the cloud mask shares (rule 10: tied by a check, not by a comment).
LAYOUT = H + "fog_noise_layout.h"
LAYOUT_TIES = [(("#define FOG_NOISE_WEIGHT0 0.55\n", "#define FOG_NOISE_WEIGHT1 0.30\n",
                 "#define FOG_NOISE_WEIGHT2 0.15\n"), "0.55, 0.30 and 0.15"),
               (("#define FOG_NOISE_RATIO0 1.0\n", "#define FOG_NOISE_RATIO1 0.43\n",
                 "#define FOG_NOISE_RATIO2 0.19\n"), "0.43 and 0.19")]

PARAMS = R + "cloud_shadow_params.h"
TMP = ".r105tmp"


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
            at = texts[path].find(anchor + block if where == "after" else block + anchor)
            if at < 0:
                raise SystemExit("text check: %s: block not next to its anchor: %r" % (path, block[:70]))
    for const, row, value in TIES:
        line = [l for l in texts["README.md"].split("\n") if l.startswith(row)]
        if NEW[PARAMS].count(const) != 1 or len(line) != 1 or value not in line[0]:
            raise SystemExit("tie check: %r against README row %r (%r)" % (const, row, value))
    layout = load(LAYOUT)[2]
    row = [l for l in texts["README.md"].split("\n") if l.startswith("| `BB_CLOUD_SHADOWS` |")]
    for defines, value in LAYOUT_TIES:
        if not all(layout.count(d) == 1 for d in defines) or len(row) != 1 or value not in row[0]:
            raise SystemExit("tie check: %s against the README row's %r" % (LAYOUT, value))
    for path, text in list(NEW.items()) + [("README block", README_BLOCK)]:
        if not all(ord(c) < 128 for c in text) or "\r" in text:
            raise SystemExit("%s: new text must be ASCII with LF in the script" % path)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd not in ("check", "apply", "revert"):
        raise SystemExit("use check | apply | revert")
    if not os.path.isdir(os.path.join(ROOT, "engine/gpu")):
        raise SystemExit("%s is not a source tree root (see the header for the root variable)" % ROOT)
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
                tmp = full + TMP
                open(tmp, "wb").write(data)
                os.replace(tmp, full)
                written.append((path, raw))
        except Exception:
            for path, data, raw in outs:
                tmp = os.path.join(ROOT, path) + TMP
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
    outs = []
    for path, edits, raw, eol, cur, _ in edited:
        for anchor, block, where in reversed(edits):
            if cur.count(block) != 1:
                raise SystemExit("%s: block not found exactly once: %r" % (path, block[:70]))
            cur = cur.replace(block, "", 1)
        outs.append((path, cur.replace("\n", eol).encode("utf-8")))
    for path, data in outs:
        open(os.path.join(ROOT, path), "wb").write(data)
    for path in NEW:
        os.remove(os.path.join(ROOT, path))
    print("reverted (%d files edited back, %d removed)" % (len(edited), len(NEW)))


main()
