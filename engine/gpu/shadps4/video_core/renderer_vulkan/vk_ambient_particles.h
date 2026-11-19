// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r98_ambient-particles): ambient motes (dust and ash, a few embers) drawn into the
// output-size frame right after the upscale and before any UI pixel, on the upscaler's scaled
// path (outputs other than 1080p: TemporalUpscaler::RunScaled calls after_upscale; with the
// upscale before the game's post, r98b_particles-reduced-scene, RunUiOnly calls it after its
// output-size copy of the game's finished frame). Made by the
// Rasterizer only with BB_PARTICLES above 0 (ambient_particles.h); otherwise nothing of it
// exists and after_upscale stays empty.
//
// Why after the upscale: the motes move against the surfaces behind them and have no motion
// vectors; drawn before DLSS (or FSR, XeSS, TAA) they would be taken from a history that follows
// the surfaces, which dims and smears small moving points. Drawn after it they are sharp at the
// output size and need no vectors. The depth test reads the render-size scene depth at the
// mote's place (the jitter added back), the light the frame before the UI (the render-size
// frame the upscaler read, or the game's output-size frame after an upscale before its post).
//
// One draw a frame: 6 vertices x AmbientMotes::Instances instances (r98c_particles-visible: and
// AmbientMotes::FlameInstances while the lamps are on), no vertex buffer, no image of its own;
// r98c: one uniform buffer, the lamps' block (AmbientMotes::LampBlock, 928 bytes since r98e, written in the
// draw's own commands); the frame is screened (colour + frame (1 - colour)) through the UI
// image's UNORM view, alpha untouched. A GPU profile row "Ambient particles (r98)".

#pragma once

#include <array>
#include <chrono>

#include "common/types.h"
#include "video_core/renderer_vulkan/ambient_particles.h"
#include "video_core/renderer_vulkan/ambient_particles_lamps.h" // bbport (r98c_particles-visible)
#include "video_core/renderer_vulkan/ambient_particles_still.h" // bbport (r98d_particles-still-indoors)
#include "video_core/renderer_vulkan/ambient_particles_moths.h" // bbport (r98e_moths-at-lamps)
#include "video_core/renderer_vulkan/vk_camera_motion.h"
#include "video_core/renderer_vulkan/vk_common.h"
// bbport (r98c_particles-visible): after vk_common.h (its Vulkan configuration first)
#include <vk_mem_alloc.h>
#include "video_core/renderer_vulkan/vk_temporal_upscaler.h"

namespace Vulkan {

class Instance;
class Scheduler;

class AmbientParticles {
public:
    /// Makes the pipeline (BB_PARTICLES above 0 only: the Rasterizer makes no object otherwise)
    /// and says the knobs once.
    AmbientParticles(const Instance& instance, Scheduler& scheduler);
    ~AmbientParticles();

    /// The pipeline was made; without it Draw records nothing.
    [[nodiscard]] bool Ready() const noexcept {
        return bool(pipeline);
    }

    /// Advances the drift by the real time since the last call and records the draw into
    /// `frame` (TemporalUpscaler::after_upscale). `wind_on`/`wind`: the shared wind's snapshot
    /// (BbWind::Snapshot on and wind, m/s).
    void Draw(const TemporalUpscaler::UpscaledFrame& frame, const CameraMotion::Matrices& camera,
              bool wind_on, const std::array<float, 3>& wind,
              float open = 1.0f); // bbport (r98d_particles-still-indoors): the camera's open share of
                                  // air (WindShelter::CameraOpen; 1 without the field)

    /// bbport (r98c_particles-visible): BB_PARTICLES_LAMPS above 0 (read once): the lamps are
    /// gathered (AddLamps) and light the dust; flames throw embers.
    [[nodiscard]] bool LampsWanted() const noexcept {
        return lamp_gain > 0.0f;
    }
    /// A G-buffer pass begins: the lamps gathered so far were another view's.
    void ClearLamps() {
        lamps.Clear();
    }
    /// One tile's light list of the game's lamp pass, as drawn (`count` records of 16 words).
    void AddLamps(const u32* records, u32 count) {
        lamps.Add(records, count);
    }

private:
    bool CreatePipeline();

    const Instance& instance;
    Scheduler& scheduler;
    vk::UniqueDescriptorSetLayout set_layout;
    vk::UniquePipelineLayout layout;
    vk::UniquePipeline pipeline;

    AmbientMotes::Drift drift{};
    std::chrono::steady_clock::time_point last{};   ///< the last Draw (zero: none yet)
    std::chrono::steady_clock::time_point window{}; ///< start of the log line's 10 s
    u32 draws = 0;   ///< draws recorded since `window`
    u32 skipped = 0; ///< calls without a usable frame or camera since `window`
    bool first_said = false;

    // bbport (r98c_particles-visible): the lamps' block (binding 2), the lamps, and the counters
    // of the r98c line (since `window`).
    const float lamp_gain = AmbientMotes::LampGain();
    vk::Buffer lamp_buffer{};
    VmaAllocation lamp_allocation{};
    AmbientMotes::LampSet lamps;
    struct LampWindow {
        u32 frames = 0;      ///< frames the lamps were updated
        u32 lit = 0;         ///< of them with a lamp in the block
        u32 lamps = 0;       ///< lamps in the block, summed
        u32 flames = 0;      ///< flames in the block, summed
        u32 most_flames = 0; ///< at most in one frame
        u32 most_listed = 0; ///< lamps the game listed, at most in one frame
        u32 left_out = 0;    ///< at most in one frame
        float reach_min = 0.0f, reach_max = 0.0f; ///< the flames' reach (m)
        /// The nearest flame of the last frame with one, back in view space (m): it must equal
        /// its lamp record's place (the r64 probe's "at="), else the embers are misplaced.
        std::array<float, 3> flame_view{};
    } lamp_window;
    // bbport (r98d_particles-still-indoors): the camera's open share of air, followed (1: open),
    // and what the r98d line of the last 10 s says.
    float open_follow = 1.0f;
    AmbientMotes::StillStats still_stats;
    // bbport (r98e_moths-at-lamps): BB_PARTICLES_MOTHS (0: off; read once), the moths' lamps with their
    // fades, and the counters of the r98e line (since `window`).
    const int moth_level = AmbientMotes::MothLevel();
    AmbientMotes::MothSet moths;
    AmbientMotes::MothWindow moth_window;
};

} // namespace Vulkan
