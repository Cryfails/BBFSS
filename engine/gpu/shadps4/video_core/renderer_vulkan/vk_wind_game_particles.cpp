// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r122b_game-particles-follow-wind, FEATURE): the draw side of the game's particles leaning with our
// wind (gpu/shim/bbport_wind_game_particles.h has the rule, the shader patch and the word). The rasterizer
// calls WindGameParticlesDraw for every draw, right before the pipeline binds its resources, only while
// BbWindParticles::On() (BB_WIND_GAME=1 and BB_WIND_GAME_PARTICLES above 0; a function-local static, read once).
// For a draw whose vertex stage (the LS of the tessellation pipeline) is the game's particle shader 4cd21a0f it
// sets the push constant word the patched shader reads (PushData::motion_param, byte 120): the lean of this
// frame's wind for a draw of a pair that leans, else 0 (so a draw of the same shader that is not an ambient
// particle draw stays as it was). Off: this file's function is never called, nothing is made, GPU 0, memory 0.
// On: per draw two hash compares; for a particle draw also one wind snapshot copy (about 120 bytes), a
// square root and a few multiplications; about 40 particle draws a frame.
#include "video_core/renderer_vulkan/vk_rasterizer.h"

namespace Vulkan {

// the word's member in the shader's push block is PushData::motion_param (the patched module reads member 11)
static_assert(Shader::PushData::MotionParamIndex == BbWindParticles::WordMember,
              "the particle vertex shader's patch reads the push block's motion_param");

void Rasterizer::WindGameParticlesDraw(const GraphicsPipeline* pipeline, const Shader::Info* fragment) {
    if (fragment == nullptr ||
        pipeline->GetStage(Shader::SwStage::Vertex).pgm_hash != BbWindParticles::LocalHash) {
        return;
    }
    BbWindParticles::Announce();
    BbWindParticles::Counters& counters = BbWindParticles::Count();
    counters.draws.fetch_add(1, std::memory_order_relaxed);
    auto& dc = Dc();
    dc.push_data.motion_param = 0; // the word of every other draw of this shader (no motion pipeline sets it)
    // Additive into colour target 0 (destination factor One, function Add): the motes and embers.
    const auto& blend = Regs().blend_control[0];
    const bool additive = blend.enable &&
                          blend.color_dst_factor == AmdGpu::BlendControl::BlendFactor::One &&
                          blend.color_func == AmdGpu::BlendControl::BlendFunc::Add;
    if (!BbWindParticles::PairWanted(fragment->pgm_hash, additive)) {
        return;
    }
    counters.leaning.fetch_add(1, std::memory_order_relaxed);
    // The wind at the camera as the other followers read it (heading, speed, gust front and the shelter's calm
    // share included); without BB_WIND=1 the snapshot is off and the word stays 0.
    const BbWind::Snapshot snapshot = wind.Get();
    if (!snapshot.on) {
        return;
    }
    const BbWindParticles::Knob& knob = BbWindParticles::KnobOnce();
    const u32 word = BbWindParticles::Word(snapshot.wind[0], snapshot.wind[2], knob.strength, knob.swap);
    if (word != 0) {
        dc.push_data.motion_param = word;
        counters.moved.fetch_add(1, std::memory_order_relaxed);
        counters.last.store(word, std::memory_order_relaxed);
    }
}

} // namespace Vulkan
