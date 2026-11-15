// SPDX-License-Identifier: GPL-3.0-or-later
// bbport (r50_leaf-stage1, r50b_leaf-matcher): the cut-out analysis, stage 1 of the ray traced
// foliage shadows. It reads from a pixel shader's IR which texture channel its discard compares
// with which reference, and at which input the texture is sampled (Info::Cutout). It changes
// nothing in the shader.
#pragma once

#include <array>
#include <string>
#include "shader_recompiler/info.h"

namespace Shader::IR {
struct Program;
}

namespace Shader::Optimization {

/// BB_RT_CARD_ALPHA_LOG=1 or (r54) BB_RT_CARD_ALPHA=1 (each read once): pixel shaders are
/// analysed as they compile, and the cache warm-up leaves the discarding ones to compile in
/// play. Otherwise off, and none of this runs.
[[nodiscard]] bool CutoutAnalysisOn();

/// (r54_leaf-stage2) BB_RT_CARD_ALPHA_LOG=1 (read once): the log lines of r50 and r50b (the
/// shader lines, the draw-time lines, the 600-frame lines) and what only they count.
/// BB_RT_CARD_ALPHA=1 alone prints none of them.
[[nodiscard]] bool CutoutLogOn();

/// (r54_leaf-stage2) BB_RT_CARD_ALPHA=1 (read once; Vulkan::ReadCardAlpha): the capture of
/// the cut-out cards' UVs (RtShadow; renderer_vulkan/rt_card_uv.h). A value neither 0 nor 1
/// is said once in the log, as off.
[[nodiscard]] bool CardAlphaOn();

/// What the discards of a fragment program test (no knob, no log).
[[nodiscard]] Info::Cutout AnalyzeCutout(const IR::Program& program, const RuntimeInfo& runtime_info);

/// The log line of a pixel shader's info.cutout (under 512 characters).
[[nodiscard]] std::string CutoutLine(const Info& info, const RuntimeInfo& runtime_info);

/// AnalyzeCutout into program.info.cutout (the Info of every compile, so of every permutation);
/// a log line for a pixel shader not seen before, whose record FindCutout keeps.
void CutoutAnalysisPass(IR::Program& program, const RuntimeInfo& runtime_info);

/// (r50b) The record of the first analysed compile of this pgm_hash, or null. The map only grows
/// and a record is not changed once in it, so the pointer stays valid. A caller uses it only for
/// an Info whose images.size() and buffers.size() equal the record's image_count and
/// buffer_count.
[[nodiscard]] const Info::Cutout* FindCutout(u64 pgm_hash);

/// The warm-up left a discarding pixel shader's cache record to compile in play (counted for the
/// summary line).
void NoteCutoutCacheRefusal();

/// The class the r46 card rule (RtShadow::PrepareScene, LampCard) gives a cut-out instance.
enum class CutoutCardClass : u8 {
    Plant,       ///< left out of lamp rays: a skeleton, no sun shadow pass draws it (lone)
    Static,      ///< left out of lamp rays: no skeleton
    SkinnedOut,  ///< left out of lamp rays: a skeleton, not lone (rule 2 or the old rule)
    SkinnedKept, ///< kept whole in lamp rays: a skeleton, not lone (hair, cloth, characters)
    OtherKept,   ///< kept whole in lamp rays otherwise (rules 0 and 1)
    Count,
};

/// A cut-out instance of the ray tracing scene: the pixel shaders (pgm_hash, 0: none) of its
/// camera pass draw that discards and of its sun shadow pass draw that samples a texture.
void NoteCutoutCard(u64 camera_ps, u64 sun_ps, CutoutCardClass card_class);

/// (r50b) A draw of a record's pixel shader, by its memory dwords: all read and none of them in a
/// region the GPU wrote (BufferCache::IsRegionGpuModified); one in such a region that is bound in
/// place (BufferCache::IsInPlace, BB_GUEST_IN_PLACE: a write still pending; not read); one in a
/// region the GPU wrote, or in a buffer the shader writes (not read); one not readable (no such
/// buffer, a special one, an invalid V#, outside the buffer or the mapping). Of the dwords of one
/// draw the last of these wins. OtherPermutation: the draw's pixel shader inputs are not the ones
/// the record was analysed with (CutoutSamePermutation), so nothing was read.
enum class CutoutConstants : u8 { CpuWritten, InPlace, GpuWritten, Unreadable, OtherPermutation };

/// (r50b E6) Whether a draw with these pixel shader inputs (regs.num_interp, and a bit per input
/// i < num_inputs for regs.ps_inputs[i].use_default and .flat_shade) is drawn by the permutation
/// whose analysis made the record: the inputs are part of the permutation key, and a default
/// input is an immediate in the IR (V_INTERP_P2_F32), so another permutation may test otherwise.
[[nodiscard]] bool CutoutSamePermutation(const Info::Cutout& c, u32 num_inputs, u32 default_mask,
                                         u32 flat_mask);

/// (r50b) A memory dword a record names: kind Immediate for a slot the record leaves unused.
struct CutoutDword {
    Info::Cutout::Ref kind = Info::Cutout::Ref::Immediate;
    u8 buffer = 0;
    u16 dword = 0;
};

/// (r50b) The record's memory dwords, in the order the draw-time line takes their values: the
/// coordinates' scale u, v and offset u, v, the reference's first and second dword, the dither's.
[[nodiscard]] std::array<CutoutDword, 7> CutoutDwords(const Info::Cutout& c);

/// (r50b) vs_out of CutoutConstantsLine: the input is flat shaded.
constexpr int CutoutFlatInput = 0x100;

/// (r50b) The draw-time line of a record whose RepeatableWithConstants() holds, from the values of
/// CutoutDwords (as floats; NaN where not read). vs_out: the vertex shader output a pixel shader
/// input reads (regs.ps_inputs[i].input_offset, | CutoutFlatInput when flat shaded), or -1 for a
/// default value (use_default). dither_size: the draw's T# of the dither, width and height (0:
/// not known).
[[nodiscard]] std::string CutoutConstantsLine(u64 pgm_hash, const Info::Cutout& c,
                                              const std::array<f32, 7>& values, int uv_vs_out,
                                              int alpha_vs_out, u8 stored, CutoutConstants state,
                                              std::array<u32, 2> dither_size);

/// (r50b) One draw of this pixel shader, counted by its state for the cut-out cards' line (every
/// draw of a record with RepeatableWithConstants(), BB_RT_CARD_ALPHA_LOG=1 only). True for the
/// first draw of the pgm_hash in a state other than OtherPermutation: that draw prints the
/// draw-time line.
[[nodiscard]] bool NoteCutoutConstants(u64 pgm_hash, CutoutConstants state);

/// The two 600-frame lines (empty while nothing is to be said, or the knob is off).
[[nodiscard]] std::string CutoutSummaryText();
[[nodiscard]] std::string CutoutCardsText();

/// With the knob on, both lines on stdout (every 600 frames, RtShadow::OnFrameEnd).
void PrintCutoutSummary();

} // namespace Shader::Optimization
