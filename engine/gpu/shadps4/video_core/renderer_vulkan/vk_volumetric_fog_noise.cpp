// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r94_fog-noise): FEATURE. The sun fog's world anchored noise (BB_FOG_NOISE above 0, or
// BB_FOG_NOISE_SHOW=1): VolumetricLight's members for it (the pure parts are
// volumetric_fog_noise.h). Off, the default: the knobs are read and said once at the first
// FogNoiseKnob; it is false, so the rasterizer never calls SetFogNoise, fog_noise.on stays false,
// FogNoiseMarch returns false at its first test, no NOISE build is made, and every march binds
// and pushes what it did before.
// bbport (r94b_fog-noise-visible): BB_FOG_NOISE_BANKS=1 picks the banks look (MakeTail in
// volumetric_fog_noise.h); it is read with the other knobs, once, and does nothing while the
// noise is off.
#include <cmath> // bbport (r94b_fog-noise-visible)
#include <cstdio>
#include <cstdlib>
#include <span>
#include <utility>

#include "video_core/renderer_vulkan/vk_volumetric_light.h"

#include "video_core/host_shaders/volumetric_light_integrate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_dual_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_gate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_integrate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_dual_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_area_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_gate_noise_comp.h"
#include "video_core/host_shaders/volumetric_light_repair_noise_comp.h"

namespace Vulkan {
namespace {

// BB_FOG_NOISE (strength 0-2; unset, 0 or not a number: off), BB_FOG_NOISE_SCALE (m, 2-100;
// 10) and BB_FOG_NOISE_SHOW (1: on at strength 3), read once and said once (on or off).
const VolumetricFogNoise::Knobs& FogNoiseKnobs() {
    static const VolumetricFogNoise::Knobs knobs = [] {
        const VolumetricFogNoise::Knobs k = VolumetricFogNoise::MakeKnobs(
            std::getenv("BB_FOG_NOISE"), std::getenv("BB_FOG_NOISE_SCALE"),
            std::getenv("BB_FOG_NOISE_SHOW"), std::getenv("BB_FOG_NOISE_BANKS")); // bbport r94b
        if (k.On()) {
            std::printf("Volumetric lighting (r94): fog noise on (BB_FOG_NOISE), strength %.2f%s "
                        "(amplitude %.2f, gain %.2f), largest patches %.1f m "
                        "(BB_FOG_NOISE_SCALE): the sun fog's light "
                        "varies in world anchored patches, still without wind and drifting with "
                        "it when BB_WIND=1 (then in place of r82's drift, also on area gate "
                        "marches); the extinction stays at the mean density\n",
                        double(k.strength), k.show ? " (BB_FOG_NOISE_SHOW=1)" : "",
                        double(VolumetricFogNoise::Amplitude(k.strength)),
                        double(VolumetricFogNoise::Gain(k.strength)), double(k.scale));
        } else {
            std::printf("Volumetric lighting (r94): fog noise off (BB_FOG_NOISE unset, 0 or not "
                        "a number, and BB_FOG_NOISE_SHOW not 1); the sun fog is even\n");
        }
        // bbport (r94b_fog-noise-visible): the look, said once while the noise is on
        if (k.On() && k.banks) {
            const float clear = VolumetricFogNoise::BankClear(k.strength);
            const float gain = VolumetricFogNoise::BankGain(k.strength);
            std::printf("Volumetric lighting (r94b): fog noise look: banks (BB_FOG_NOISE_BANKS=1), "
                        "%.1f m across, %.1f times wider than tall; m %.2f in the clear air, "
                        "%.2f in a bank's core (%.2f + %.2f smoothstep(%.2f, %.2f, d), mean 1); "
                        "drifting only with BB_WIND=1\n",
                        double(k.scale), double(VolumetricFogNoise::BankSquash), double(clear),
                        double(clear + gain), double(clear), double(gain),
                        double(VolumetricFogNoise::BankFrom), double(VolumetricFogNoise::BankTo));
        } else if (k.On()) {
            std::printf("Volumetric lighting (r94b): fog noise look: r94's soft patches "
                        "(BB_FOG_NOISE_BANKS not 1)\n");
        }
        return k;
    }();
    return knobs;
}

// noise_passes's index of a build: bit 0 the ray traced gate, bit 1 the area gate, bit 2 repair.
// bbport (r94c_fog-noise-dual-gate): bit 3 the dual gate (a gated area march), so 16 builds
constexpr std::size_t NoiseIndex(bool gated, bool area, bool repairing, bool dual = false) {
    return (gated ? 1u : 0u) | (area ? 2u : 0u) | (repairing ? 4u : 0u) | (dual ? 8u : 0u);
}

const char* NoisePairName(bool gated, bool area, bool dual) {
    if (dual) { // bbport (r94c_fog-noise-dual-gate)
        return "ray traced gate, area gate and dual gate";
    }
    return gated ? (area ? "ray traced gate and area gate" : "ray traced gate")
                 : (area ? "area gate" : "plain");
}

// bbport (r94b_fog-noise-visible): the largest octave's offset (cells) at the last 600-march line,
// for the banks' travel since then
std::array<float, 3> banks_last{};

} // namespace

bool VolumetricLight::FogNoiseKnob() {
    return FogNoiseKnobs().On();
}

// Right before Integrate, after SetWind: the camera's view to world matrix at this call and the
// wind's snapshot. The offsets move only while the wind is on (Drift). With a camera the next
// Integrate marches with the noise, whose NOISE build carries the wind's drift, so the request
// SetWind left for r82's WIND build is taken back; without one it marches as it would without
// the noise (counted).
void VolumetricLight::SetFogNoise(bool wind_on, double wind_time,
                                  const std::array<float, 3>& wind_velocity,
                                  const std::array<float, 12>& view_to_world, bool camera_valid) {
    const VolumetricFogNoise::Knobs& knobs = FogNoiseKnobs();
    if (!knobs.On()) {
        return;
    }
    fog_noise.drift.Advance(wind_on, wind_time, wind_velocity, knobs.scale);
    fog_noise.drifting = wind_on;
    fog_noise.on = camera_valid;
    if (!camera_valid) {
        ++fog_noise.no_camera;
        return;
    }
    fog_noise.view_to_world = view_to_world;
    wind_fog.on = false;
}

// The NOISE builds of a (gated, area) pair, made at the pair's first march with the noise, so a
// game that never marches with the ray traced gate or the area gate never makes those. The
// builds take the bindings of the builds they stand for (plain and area: the pass's own; gated
// and gated area: then the gate and each column's first open slice) and PushBytes of push
// constants. A failure is said once; that pair's marches then stay even.
bool VolumetricLight::NoisePasses(bool gated, bool area, bool dual) {
    const std::size_t pair = NoiseIndex(gated, area, false, dual);
    if (fog_noise.tried[pair]) {
        return !fog_noise.failed[pair];
    }
    fog_noise.tried[pair] = true;
    using enum vk::DescriptorType;
    constexpr u32 bytes = VolumetricFogNoise::PushBytes;
    Pass& march = noise_passes[NoiseIndex(gated, area, false, dual)];
    Pass& repair_march = noise_passes[NoiseIndex(gated, area, true, dual)];
    bool made = false;
    if (dual) {
        // bbport (r94c_fog-noise-dual-gate): the GATE+AREA march with the dual gate's wider answer
        // after the gate's bindings, as DualReady's builds have them
        made =
            CreatePass(march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_DUAL_NOISE_COMP, bytes,
                       "Volumetric integrate (gate, area gate, dual, fog noise)") &&
            CreatePass(repair_march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler, eCombinedImageSampler},
                       VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_DUAL_NOISE_COMP, bytes,
                       "Volumetric repair (gate, area gate, dual, fog noise)");
    } else if (gated) {
        made =
            CreatePass(march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       area ? std::span<const u32>(VOLUMETRIC_LIGHT_INTEGRATE_GATE_AREA_NOISE_COMP)
                            : std::span<const u32>(VOLUMETRIC_LIGHT_INTEGRATE_GATE_NOISE_COMP),
                       bytes,
                       area ? "Volumetric integrate (gate, area gate, fog noise)"
                            : "Volumetric integrate (gate, fog noise)") &&
            CreatePass(repair_march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage,
                        eCombinedImageSampler, eCombinedImageSampler},
                       area ? std::span<const u32>(VOLUMETRIC_LIGHT_REPAIR_GATE_AREA_NOISE_COMP)
                            : std::span<const u32>(VOLUMETRIC_LIGHT_REPAIR_GATE_NOISE_COMP),
                       bytes,
                       area ? "Volumetric repair (gate, area gate, fog noise)"
                            : "Volumetric repair (gate, fog noise)");
    } else {
        made =
            CreatePass(march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage},
                       area ? std::span<const u32>(VOLUMETRIC_LIGHT_INTEGRATE_AREA_NOISE_COMP)
                            : std::span<const u32>(VOLUMETRIC_LIGHT_INTEGRATE_NOISE_COMP),
                       bytes,
                       area ? "Volumetric integrate (area gate, fog noise)"
                            : "Volumetric integrate (fog noise)") &&
            CreatePass(repair_march,
                       {eStorageBuffer, eStorageBuffer, eCombinedImageSampler,
                        eCombinedImageSampler, eStorageImage, eStorageImage, eStorageImage},
                       area ? std::span<const u32>(VOLUMETRIC_LIGHT_REPAIR_AREA_NOISE_COMP)
                            : std::span<const u32>(VOLUMETRIC_LIGHT_REPAIR_NOISE_COMP),
                       bytes,
                       area ? "Volumetric repair (area gate, fog noise)"
                            : "Volumetric repair (fog noise)");
    }
    fog_noise.failed[pair] = !made;
    std::printf(made ? "Volumetric lighting (r94): fog noise builds for %s marches made\n"
                     : "Volumetric lighting (r94): the fog noise builds for %s marches could "
                       "not be made; those marches stay even and do not drift with the "
                       "wind\n",
                NoisePairName(gated, area, dual));
    return made;
}

const VolumetricLight::Pass& VolumetricLight::NoisePass(bool gated, bool area, bool repairing,
                                                        bool dual) const {
    return noise_passes[NoiseIndex(gated, area, repairing, dual)];
}

VolumetricFogNoise::Tail VolumetricLight::FogNoiseTail() const {
    return VolumetricFogNoise::MakeTail(fog_noise.view_to_world, fog_noise.drift, FogNoiseKnobs());
}

// In Integrate, once its gate, area gate and gate view are decided: whether this march takes the
// noise (SetFogNoise gave a camera for it; not a march the gate view draws, which shows the gate
// alone; its pair's NOISE builds made). Every 600 marches with the noise a line counts them, those
// with the ray traced gate, the area gate and the wind, the marches since the last line that
// stayed even or had no camera, and the largest octave's offset (it moves only with the wind).
bool VolumetricLight::FogNoiseMarch(bool viewing, bool gated, bool area, bool dual) {
    if (!std::exchange(fog_noise.on, false)) {
        return false;
    }
    if (viewing || !NoisePasses(gated, area, dual)) {
        ++fog_noise.even;
        return false;
    }
    ++fog_noise.marches;
    fog_noise.gated += gated ? 1 : 0;
    fog_noise.area += area ? 1 : 0;
    fog_noise.dual += dual ? 1 : 0; // bbport (r94c_fog-noise-dual-gate)
    fog_noise.drifted += fog_noise.drifting ? 1 : 0;
    if (fog_noise.marches % 600 == 0) {
        const std::array<float, 3> cells = fog_noise.drift.Cells(0);
        std::printf("Volumetric lighting (r94): 600 marches with the fog noise (%llu with the "
                    "ray traced gate, "
                    "%llu with the area gate, %llu drifting with the wind); %llu marched even "
                    "(gate view or no builds) and %llu without a camera since the last line; "
                    "largest octave's offset %.2f %.2f %.2f cells\n",
                    static_cast<unsigned long long>(fog_noise.gated),
                    static_cast<unsigned long long>(fog_noise.area),
                    static_cast<unsigned long long>(fog_noise.drifted),
                    static_cast<unsigned long long>(fog_noise.even),
                    static_cast<unsigned long long>(fog_noise.no_camera), double(cells[0]),
                    double(cells[1]), double(cells[2]));
        // bbport (r94c_fog-noise-dual-gate): of those marches, how many had r115's dual gate
        std::printf("Volumetric lighting (r94c): %llu of those 600 marches with the noise had the "
                    "dual gate (BB_VOLUMETRIC_AREA_GATE=2)\n",
                    static_cast<unsigned long long>(fog_noise.dual));
        fog_noise.dual = 0;
        // bbport (r94b_fog-noise-visible): with the banks look, how far they moved since the last
        // line: the largest octave's offset across the ground (x, z; the wind has no up part),
        // each axis wrapped the short way, in cells of the scale (its ratio is 1), so metres
        if (FogNoiseKnobs().banks) {
            const double period = VolumetricFogNoise::Period;
            double moved = 0.0;
            for (std::size_t i = 0; i < 3; i += 2) {
                const double gap =
                    std::fmod(double(cells[i]) - double(banks_last[i]) + 1.5 * period, period) -
                    0.5 * period;
                moved += gap * gap;
            }
            banks_last = cells;
            std::printf("Volumetric lighting (r94b): banks look on those 600 marches; the banks "
                        "moved %.1f m (net) since the last line\n",
                        std::sqrt(moved) * double(FogNoiseKnobs().scale));
        }
        fog_noise.gated = fog_noise.area = fog_noise.drifted = 0;
        fog_noise.even = fog_noise.no_camera = 0;
    }
    return true;
}

} // namespace Vulkan
